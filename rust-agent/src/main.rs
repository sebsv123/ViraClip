use axum::{
    extract::{Json, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::RwLock;
use tower_http::cors::CorsLayer;
use tracing::{info, warn, error};

mod tools;
mod agent;
mod state;

use crate::agent::AgentRunner;
use crate::state::AgentState;

#[derive(Debug, Serialize, Deserialize)]
struct AgentRequest {
    task: String,
    context: Option<serde_json::Value>,
    max_iterations: Option<u32>,
}

#[derive(Debug, Serialize)]
struct AgentResponse {
    success: bool,
    result: Option<String>,
    error: Option<String>,
    iterations: u32,
    tools_used: Vec<String>,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: String,
    version: String,
    tools_available: Vec<String>,
    ffmpeg_available: bool,
}

type AppState = Arc<RwLock<AgentState>>;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"))
        )
        .json()
        .init();

    info!("🦀 ViraClip Rust Agent starting...");

    // Log API key status — not required for current tool-based operation
    match std::env::var("ANTHROPIC_API_KEY") {
        Ok(k) if !k.is_empty() => info!("ANTHROPIC_API_KEY present — LLM features enabled"),
        _ => warn!("ANTHROPIC_API_KEY not set — LLM features will be unavailable"),
    }

    // Initialize state
    let state = Arc::new(RwLock::new(AgentState::new()));

    // Build router
    let app = Router::new()
        .route("/agent/run", post(run_agent))
        .route("/agent/health", get(health_check))
        .route("/agent/tools", get(list_tools))
        .layer(CorsLayer::permissive())
        .with_state(state);

    // Get port from env or default to 8001
    let port = std::env::var("RUST_AGENT_PORT")
        .unwrap_or_else(|_| "8001".to_string())
        .parse::<u16>()?;

    let addr = format!("0.0.0.0:{}", port);
    info!("🚀 Listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}

async fn run_agent(
    State(state): State<AppState>,
    Json(request): Json<AgentRequest>,
) -> impl IntoResponse {
    info!("📋 Agent request: {}", request.task);

    let max_iterations = request.max_iterations.unwrap_or(10);

    match AgentRunner::run(
        request.task,
        request.context,
        max_iterations,
        state.clone(),
    )
    .await
    {
        Ok((result, iterations, tools_used)) => {
            info!("✅ Agent completed in {} iterations", iterations);
            (
                StatusCode::OK,
                Json(AgentResponse {
                    success: true,
                    result: Some(result),
                    error: None,
                    iterations,
                    tools_used,
                }),
            )
        }
        Err(e) => {
            error!("❌ Agent failed: {}", e);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(AgentResponse {
                    success: false,
                    result: None,
                    error: Some(e.to_string()),
                    iterations: 0,
                    tools_used: vec![],
                }),
            )
        }
    }
}

async fn health_check() -> impl IntoResponse {
    let ffmpeg_available = which::which("ffmpeg").is_ok();
    let tools_available = vec![
        "bash".to_string(),
        "ffmpeg".to_string(),
        "file_read".to_string(),
        "file_write".to_string(),
        "glob".to_string(),
        "diagnostics".to_string(),
    ];

    (
        StatusCode::OK,
        Json(HealthResponse {
            status: "healthy".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            tools_available,
            ffmpeg_available,
        }),
    )
}

async fn list_tools() -> impl IntoResponse {
    let tools = serde_json::json!({
        "tools": [
            {
                "name": "bash",
                "description": "Execute bash commands with whitelist validation",
                "parameters": {
                    "command": "string",
                    "timeout": "optional u64 (ms)"
                }
            },
            {
                "name": "ffmpeg",
                "description": "Render video clips with h264_nvenc",
                "parameters": {
                    "input": "string",
                    "output": "string",
                    "start": "string (MM:SS)",
                    "end": "string (MM:SS)",
                    "codec": "optional string"
                }
            },
            {
                "name": "file_read",
                "description": "Read file contents",
                "parameters": {
                    "path": "string"
                }
            },
            {
                "name": "file_write",
                "description": "Write file contents",
                "parameters": {
                    "path": "string",
                    "content": "string"
                }
            },
            {
                "name": "glob",
                "description": "Find files matching pattern",
                "parameters": {
                    "pattern": "string",
                    "directory": "optional string"
                }
            },
            {
                "name": "diagnostics",
                "description": "System diagnostics and health checks",
                "parameters": {}
            }
        ]
    });

    (StatusCode::OK, Json(tools))
}
