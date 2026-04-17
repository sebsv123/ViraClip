pub mod bash;
pub mod ffmpeg;
pub mod file_ops;
pub mod glob;
pub mod diagnostics;

use anyhow::Result;
use async_trait::async_trait;
use serde_json::Value;

#[async_trait]
pub trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn description(&self) -> &str;
    async fn execute(&self, params: Value) -> Result<String>;
}

pub fn get_all_tools() -> Vec<Box<dyn Tool>> {
    vec![
        Box::new(bash::BashTool::new()),
        Box::new(ffmpeg::FFmpegTool::new()),
        Box::new(file_ops::FileReadTool::new()),
        Box::new(file_ops::FileWriteTool::new()),
        Box::new(glob::GlobTool::new()),
        Box::new(diagnostics::DiagnosticsTool::new()),
    ]
}
