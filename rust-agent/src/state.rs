use parking_lot::RwLock;
use std::collections::HashMap;
use std::sync::Arc;

#[derive(Debug, Clone)]
pub struct AgentState {
    pub working_directory: String,
    pub environment: Arc<RwLock<HashMap<String, String>>>,
    pub task_history: Arc<RwLock<Vec<TaskRecord>>>,
}

#[derive(Debug, Clone)]
pub struct TaskRecord {
    pub task_id: String,
    pub task: String,
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub success: bool,
    pub iterations: u32,
}

impl AgentState {
    pub fn new() -> Self {
        Self {
            working_directory: std::env::var("WORKDIR")
                .unwrap_or_else(|_| "/app/temp".to_string()),
            environment: Arc::new(RwLock::new(HashMap::new())),
            task_history: Arc::new(RwLock::new(Vec::new())),
        }
    }

    pub fn add_task_record(&self, record: TaskRecord) {
        self.task_history.write().push(record);
    }

    pub fn get_env(&self, key: &str) -> Option<String> {
        self.environment.read().get(key).cloned()
    }

    pub fn set_env(&self, key: String, value: String) {
        self.environment.write().insert(key, value);
    }
}

impl Default for AgentState {
    fn default() -> Self {
        Self::new()
    }
}
