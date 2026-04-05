use super::Tool;
use anyhow::Result;
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::Value;
use std::path::Path;
use tokio::fs;
use tracing::info;

pub struct FileReadTool;

impl FileReadTool {
    pub fn new() -> Self {
        Self
    }
}

#[derive(Deserialize)]
struct FileReadParams {
    path: String,
}

#[async_trait]
impl Tool for FileReadTool {
    fn name(&self) -> &str {
        "file_read"
    }

    fn description(&self) -> &str {
        "Read file contents. Parameters: path (string)."
    }

    async fn execute(&self, params: Value) -> Result<String> {
        let params: FileReadParams = serde_json::from_value(params)?;
        
        info!("📖 Reading file: {}", params.path);

        let content = fs::read_to_string(&params.path).await?;
        
        Ok(format!(
            "File: {}\nSize: {} bytes\nContent:\n{}",
            params.path,
            content.len(),
            content
        ))
    }
}

pub struct FileWriteTool;

impl FileWriteTool {
    pub fn new() -> Self {
        Self
    }
}

#[derive(Deserialize)]
struct FileWriteParams {
    path: String,
    content: String,
}

#[async_trait]
impl Tool for FileWriteTool {
    fn name(&self) -> &str {
        "file_write"
    }

    fn description(&self) -> &str {
        "Write content to file. Parameters: path (string), content (string)."
    }

    async fn execute(&self, params: Value) -> Result<String> {
        let params: FileWriteParams = serde_json::from_value(params)?;
        
        info!("✍️  Writing file: {}", params.path);

        // Create parent directories if needed
        if let Some(parent) = Path::new(&params.path).parent() {
            fs::create_dir_all(parent).await?;
        }

        fs::write(&params.path, &params.content).await?;
        
        Ok(format!(
            "✅ File written successfully\nPath: {}\nSize: {} bytes",
            params.path,
            params.content.len()
        ))
    }
}
