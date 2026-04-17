use super::Tool;
use anyhow::Result;
use async_trait::async_trait;
use glob::glob as glob_pattern;
use serde::Deserialize;
use serde_json::Value;
use tracing::info;

pub struct GlobTool;

impl GlobTool {
    pub fn new() -> Self {
        Self
    }
}

#[derive(Deserialize)]
struct GlobParams {
    pattern: String,
    #[serde(default = "default_directory")]
    directory: String,
}

fn default_directory() -> String {
    "/app/temp".to_string()
}

#[async_trait]
impl Tool for GlobTool {
    fn name(&self) -> &str {
        "glob"
    }

    fn description(&self) -> &str {
        "Find files matching glob pattern. Parameters: pattern (string), directory (optional string, defaults to /app/temp)."
    }

    async fn execute(&self, params: Value) -> Result<String> {
        let params: GlobParams = serde_json::from_value(params)?;
        
        let full_pattern = format!("{}/{}", params.directory, params.pattern);
        info!("🔍 Glob search: {}", full_pattern);

        let mut results = Vec::new();
        for entry in glob_pattern(&full_pattern)? {
            if let Ok(path) = entry {
                results.push(path.display().to_string());
            }
        }

        if results.is_empty() {
            Ok(format!("No files found matching pattern: {}", full_pattern))
        } else {
            Ok(format!(
                "Found {} file(s):\n{}",
                results.len(),
                results.join("\n")
            ))
        }
    }
}
