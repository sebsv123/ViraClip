use anyhow::{anyhow, Result};
use serde_json::Value;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{info, warn};

use crate::state::AgentState;
use crate::tools::{get_all_tools, Tool};

pub struct AgentRunner;

impl AgentRunner {
    pub async fn run(
        task: String,
        context: Option<Value>,
        max_iterations: u32,
        state: Arc<RwLock<AgentState>>,
    ) -> Result<(String, u32, Vec<String>)> {
        info!("🤖 Agent starting task: {}", task);

        let tools = get_all_tools();
        let mut tools_used = Vec::new();
        let mut iteration = 0;

        // Simple task routing based on keywords
        let result = if task.to_lowercase().contains("render") || task.contains("ffmpeg") {
            // Video rendering task
            iteration += 1;
            tools_used.push("ffmpeg".to_string());
            
            let ffmpeg_tool = tools
                .iter()
                .find(|t| t.name() == "ffmpeg")
                .ok_or_else(|| anyhow!("FFmpeg tool not found"))?;

            // Extract parameters from context
            let params = context.ok_or_else(|| anyhow!("FFmpeg requires context parameters"))?;
            
            ffmpeg_tool.execute(params).await?
        } else if task.to_lowercase().contains("diagnostic") || task.contains("health") {
            // Diagnostics task
            iteration += 1;
            tools_used.push("diagnostics".to_string());
            
            let diag_tool = tools
                .iter()
                .find(|t| t.name() == "diagnostics")
                .ok_or_else(|| anyhow!("Diagnostics tool not found"))?;

            diag_tool.execute(serde_json::json!({})).await?
        } else if task.to_lowercase().contains("find") || task.contains("glob") {
            // File search task
            iteration += 1;
            tools_used.push("glob".to_string());
            
            let glob_tool = tools
                .iter()
                .find(|t| t.name() == "glob")
                .ok_or_else(|| anyhow!("Glob tool not found"))?;

            let params = context.unwrap_or_else(|| serde_json::json!({
                "pattern": "*",
                "directory": "/app/temp"
            }));
            
            glob_tool.execute(params).await?
        } else if task.to_lowercase().contains("read") {
            // File read task
            iteration += 1;
            tools_used.push("file_read".to_string());
            
            let read_tool = tools
                .iter()
                .find(|t| t.name() == "file_read")
                .ok_or_else(|| anyhow!("FileRead tool not found"))?;

            let params = context.ok_or_else(|| anyhow!("file_read requires path in context"))?;
            
            read_tool.execute(params).await?
        } else if task.to_lowercase().contains("bash") || task.to_lowercase().contains("command") {
            // Bash command task
            iteration += 1;
            tools_used.push("bash".to_string());
            
            let bash_tool = tools
                .iter()
                .find(|t| t.name() == "bash")
                .ok_or_else(|| anyhow!("Bash tool not found"))?;

            let params = context.ok_or_else(|| anyhow!("bash requires command in context"))?;
            
            bash_tool.execute(params).await?
        } else {
            warn!("⚠️  Unknown task type, returning available tools");
            format!(
                "Available tools:\n{}",
                tools
                    .iter()
                    .map(|t| format!("- {}: {}", t.name(), t.description()))
                    .collect::<Vec<_>>()
                    .join("\n")
            )
        };

        info!("✅ Agent completed in {} iteration(s)", iteration);

        Ok((result, iteration, tools_used))
    }
}
