use super::Tool;
use anyhow::{anyhow, Result};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::Value;
use std::path::Path;
use tracing::{info, error};

pub struct FFmpegTool;

impl FFmpegTool {
    pub fn new() -> Self {
        Self
    }

    fn parse_timestamp(ts: &str) -> Result<f64> {
        let parts: Vec<&str> = ts.split(':').collect();
        match parts.len() {
            1 => Ok(parts[0].parse::<f64>()?),
            2 => {
                let minutes = parts[0].parse::<f64>()?;
                let seconds = parts[1].parse::<f64>()?;
                Ok(minutes * 60.0 + seconds)
            }
            3 => {
                let hours = parts[0].parse::<f64>()?;
                let minutes = parts[1].parse::<f64>()?;
                let seconds = parts[2].parse::<f64>()?;
                Ok(hours * 3600.0 + minutes * 60.0 + seconds)
            }
            _ => Err(anyhow!("Invalid timestamp format: {}", ts)),
        }
    }
}

#[derive(Deserialize)]
struct FFmpegParams {
    input: String,
    output: String,
    start: String,
    end: String,
    #[serde(default = "default_codec")]
    codec: String,
    #[serde(default)]
    use_gpu: bool,
}

fn default_codec() -> String {
    "h264_nvenc".to_string()
}

#[async_trait]
impl Tool for FFmpegTool {
    fn name(&self) -> &str {
        "ffmpeg"
    }

    fn description(&self) -> &str {
        "Render video clips using FFmpeg with GPU acceleration (h264_nvenc). Parameters: input (path), output (path), start (MM:SS), end (MM:SS), codec (optional), use_gpu (optional bool)."
    }

    async fn execute(&self, params: Value) -> Result<String> {
        let params: FFmpegParams = serde_json::from_value(params)?;

        info!(
            "🎬 FFmpeg render: {} -> {} ({} to {})",
            params.input, params.output, params.start, params.end
        );

        // Validate input file exists
        if !Path::new(&params.input).exists() {
            return Err(anyhow!("Input file not found: {}", params.input));
        }

        // Parse timestamps
        let start_sec = Self::parse_timestamp(&params.start)?;
        let end_sec = Self::parse_timestamp(&params.end)?;
        let duration = end_sec - start_sec;

        if duration <= 0.0 {
            return Err(anyhow!("Invalid duration: {} seconds", duration));
        }

        info!("⏱️  Duration: {:.2}s ({}s to {}s)", duration, start_sec, end_sec);

        // Build FFmpeg command using native bindings
        use std::process::{Command, Stdio};

        let mut cmd = Command::new("ffmpeg");
        cmd.arg("-y") // Overwrite output
            .arg("-ss")
            .arg(start_sec.to_string())
            .arg("-i")
            .arg(&params.input)
            .arg("-t")
            .arg(duration.to_string());

        // Video codec with GPU acceleration
        if params.use_gpu {
            cmd.arg("-c:v").arg(&params.codec);
            
            // NVENC-specific optimizations
            if params.codec.contains("nvenc") {
                cmd.arg("-preset").arg("p4") // Medium preset
                    .arg("-tune").arg("hq")
                    .arg("-rc").arg("vbr")
                    .arg("-cq").arg("23")
                    .arg("-b:v").arg("5M")
                    .arg("-maxrate").arg("8M")
                    .arg("-bufsize").arg("10M");
            }
        } else {
            cmd.arg("-c:v").arg("libx264")
                .arg("-preset").arg("medium")
                .arg("-crf").arg("23");
        }

        // Audio codec
        cmd.arg("-c:a").arg("aac")
            .arg("-b:a").arg("192k")
            .arg("-ar").arg("48000");

        // Output
        cmd.arg(&params.output)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        info!("🚀 Executing FFmpeg command");

        let output = cmd.output()?;

        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);

        if output.status.success() {
            info!("✅ FFmpeg render complete: {}", params.output);
            
            // Get output file size
            let size = std::fs::metadata(&params.output)
                .map(|m| m.len())
                .unwrap_or(0);

            Ok(format!(
                "✅ Video rendered successfully\nOutput: {}\nSize: {:.2} MB\nDuration: {:.2}s\nCodec: {}",
                params.output,
                size as f64 / 1_048_576.0,
                duration,
                params.codec
            ))
        } else {
            error!("❌ FFmpeg failed: {}", stderr);
            Err(anyhow!(
                "FFmpeg failed with exit code: {:?}\nStderr:\n{}\nStdout:\n{}",
                output.status.code(),
                stderr,
                stdout
            ))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_timestamp_parsing() {
        assert_eq!(FFmpegTool::parse_timestamp("30").unwrap(), 30.0);
        assert_eq!(FFmpegTool::parse_timestamp("1:30").unwrap(), 90.0);
        assert_eq!(FFmpegTool::parse_timestamp("0:01:30").unwrap(), 90.0);
        assert_eq!(FFmpegTool::parse_timestamp("1:00:00").unwrap(), 3600.0);
    }
}
