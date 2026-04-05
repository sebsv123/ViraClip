use super::Tool;
use anyhow::Result;
use async_trait::async_trait;
use serde_json::Value;
use std::process::Command;
use tracing::info;

pub struct DiagnosticsTool;

impl DiagnosticsTool {
    pub fn new() -> Self {
        Self
    }

    fn check_command(cmd: &str) -> bool {
        which::which(cmd).is_ok()
    }

    fn get_command_version(cmd: &str, args: &[&str]) -> Option<String> {
        let output = Command::new(cmd).args(args).output().ok()?;
        
        if output.status.success() {
            let stdout = String::from_utf8_lossy(&output.stdout);
            Some(stdout.lines().next()?.to_string())
        } else {
            None
        }
    }
}

#[async_trait]
impl Tool for DiagnosticsTool {
    fn name(&self) -> &str {
        "diagnostics"
    }

    fn description(&self) -> &str {
        "Run system diagnostics and health checks. No parameters required."
    }

    async fn execute(&self, _params: Value) -> Result<String> {
        info!("🏥 Running diagnostics");

        let mut report = String::new();
        report.push_str("=== ViraClip Rust Agent Diagnostics ===\n\n");

        // FFmpeg check
        if Self::check_command("ffmpeg") {
            let version = Self::get_command_version("ffmpeg", &["-version"])
                .unwrap_or_else(|| "unknown".to_string());
            report.push_str(&format!("✅ FFmpeg: {}\n", version));
        } else {
            report.push_str("❌ FFmpeg: NOT FOUND\n");
        }

        // FFprobe check
        if Self::check_command("ffprobe") {
            report.push_str("✅ FFprobe: available\n");
        } else {
            report.push_str("❌ FFprobe: NOT FOUND\n");
        }

        // Docker check
        if Self::check_command("docker") {
            let version = Self::get_command_version("docker", &["--version"])
                .unwrap_or_else(|| "unknown".to_string());
            report.push_str(&format!("✅ Docker: {}\n", version));
        } else {
            report.push_str("❌ Docker: NOT FOUND\n");
        }

        // Git check
        if Self::check_command("git") {
            let version = Self::get_command_version("git", &["--version"])
                .unwrap_or_else(|| "unknown".to_string());
            report.push_str(&format!("✅ Git: {}\n", version));
        } else {
            report.push_str("❌ Git: NOT FOUND\n");
        }

        // Disk space
        #[cfg(unix)]
        {
            if let Ok(output) = Command::new("df")
                .args(&["-h", "/app/temp"])
                .output()
            {
                let stdout = String::from_utf8_lossy(&output.stdout);
                report.push_str(&format!("\n📊 Disk Space:\n{}\n", stdout));
            }
        }

        // Environment
        report.push_str("\n🔧 Environment:\n");
        report.push_str(&format!(
            "- Rust Agent Port: {}\n",
            std::env::var("RUST_AGENT_PORT").unwrap_or_else(|_| "8001".to_string())
        ));
        report.push_str(&format!(
            "- Work Directory: {}\n",
            std::env::var("WORKDIR").unwrap_or_else(|_| "/app/temp".to_string())
        ));

        // System info
        #[cfg(unix)]
        {
            if let Ok(output) = Command::new("uname").arg("-a").output() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                report.push_str(&format!("\n💻 System: {}\n", stdout.trim()));
            }
        }

        Ok(report)
    }
}
