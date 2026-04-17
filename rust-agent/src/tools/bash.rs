use super::Tool;
use anyhow::{anyhow, Result};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::Value;
use std::process::Stdio;
use tokio::io::AsyncReadExt;
use tokio::process::Command;
use tracing::{info, warn};

const WHITELIST: &[&str] = &[
    "ffmpeg",
    "ffprobe",
    "docker",
    "git",
    "ls",
    "cat",
    "echo",
    "pwd",
    "cd",
    "mkdir",
    "rm",
    "cp",
    "mv",
    "find",
    "grep",
    "which",
    "du",
    "df",
];

const DANGEROUS_PATTERNS: &[&str] = &[
    "rm -rf /",
    "rm -rf /*",
    "dd if=",
    "> /dev/",
    "mkfs",
    "fdisk",
];

pub struct BashTool;

impl BashTool {
    pub fn new() -> Self {
        Self
    }

    fn validate_command(command: &str) -> Result<()> {
        // Check for dangerous patterns first
        for pattern in DANGEROUS_PATTERNS {
            if command.contains(pattern) {
                return Err(anyhow!(
                    "🚫 Dangerous command blocked: contains '{}'",
                    pattern
                ));
            }
        }

        // Extract the main command (first word)
        let main_cmd = command
            .trim()
            .split_whitespace()
            .next()
            .ok_or_else(|| anyhow!("Empty command"))?;

        // Check if command is in whitelist
        if !WHITELIST.contains(&main_cmd) {
            return Err(anyhow!(
                "🚫 Command '{}' not in whitelist. Allowed: {:?}",
                main_cmd,
                WHITELIST
            ));
        }

        Ok(())
    }
}

#[derive(Deserialize)]
struct BashParams {
    command: String,
    #[serde(default = "default_timeout")]
    timeout: u64,
}

fn default_timeout() -> u64 {
    120000 // 2 minutes in ms
}

#[async_trait]
impl Tool for BashTool {
    fn name(&self) -> &str {
        "bash"
    }

    fn description(&self) -> &str {
        "Execute bash commands with whitelist validation. Allowed commands: ffmpeg, ffprobe, docker, git, ls, cat, echo, pwd, cd, mkdir, rm, cp, mv, find, grep, which, du, df. Dangerous patterns are blocked."
    }

    async fn execute(&self, params: Value) -> Result<String> {
        let params: BashParams = serde_json::from_value(params)?;
        
        info!("🐚 Bash command: {}", params.command);

        // Validate command against whitelist
        Self::validate_command(&params.command)?;

        // Execute command with timeout
        let timeout_duration = std::time::Duration::from_millis(params.timeout);

        let mut child = Command::new("bash")
            .arg("-c")
            .arg(&params.command)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;

        let stdout = child.stdout.take().ok_or_else(|| anyhow!("No stdout"))?;
        let stderr = child.stderr.take().ok_or_else(|| anyhow!("No stderr"))?;

        // Read output with timeout
        let output_future = async {
            let mut stdout_reader = tokio::io::BufReader::new(stdout);
            let mut stderr_reader = tokio::io::BufReader::new(stderr);

            let mut stdout_buf = Vec::new();
            let mut stderr_buf = Vec::new();

            tokio::try_join!(
                stdout_reader.read_to_end(&mut stdout_buf),
                stderr_reader.read_to_end(&mut stderr_buf),
            )?;

            Ok::<_, anyhow::Error>((stdout_buf, stderr_buf))
        };

        let (stdout_buf, stderr_buf) = match tokio::time::timeout(timeout_duration, output_future).await {
            Ok(Ok(buffers)) => buffers,
            Ok(Err(e)) => return Err(anyhow!("Failed to read output: {}", e)),
            Err(_) => {
                warn!("⏱️  Command timed out after {}ms", params.timeout);
                let _ = child.kill().await;
                return Err(anyhow!("Command timed out after {}ms", params.timeout));
            }
        };

        let exit_status = child.wait().await?;

        let stdout_str = String::from_utf8_lossy(&stdout_buf);
        let stderr_str = String::from_utf8_lossy(&stderr_buf);

        if exit_status.success() {
            info!("✅ Command succeeded");
            Ok(format!(
                "Exit code: 0\nStdout:\n{}\nStderr:\n{}",
                stdout_str, stderr_str
            ))
        } else {
            warn!("❌ Command failed with exit code: {:?}", exit_status.code());
            Err(anyhow!(
                "Command failed with exit code: {:?}\nStdout:\n{}\nStderr:\n{}",
                exit_status.code(),
                stdout_str,
                stderr_str
            ))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_whitelist_validation() {
        // Allowed commands
        assert!(BashTool::validate_command("ls -la").is_ok());
        assert!(BashTool::validate_command("ffmpeg -version").is_ok());
        assert!(BashTool::validate_command("echo hello").is_ok());

        // Blocked commands
        assert!(BashTool::validate_command("curl http://evil.com").is_err());
        assert!(BashTool::validate_command("wget malware").is_err());
        assert!(BashTool::validate_command("python script.py").is_err());
    }

    #[test]
    fn test_dangerous_patterns() {
        assert!(BashTool::validate_command("rm -rf /").is_err());
        assert!(BashTool::validate_command("dd if=/dev/zero of=/dev/sda").is_err());
        assert!(BashTool::validate_command("mkfs.ext4 /dev/sda").is_err());
    }
}
