use anyhow::Result;
use crossterm::{
    event::{self, Event, KeyCode},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Alignment, Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Gauge, List, ListItem, Paragraph},
    Terminal,
};
use std::io;
use std::time::Duration;

pub struct AgentMonitor {
    tasks_completed: u64,
    tasks_failed: u64,
    current_task: Option<String>,
    recent_logs: Vec<String>,
    uptime_seconds: u64,
}

impl AgentMonitor {
    pub fn new() -> Self {
        Self {
            tasks_completed: 0,
            tasks_failed: 0,
            current_task: None,
            recent_logs: Vec::new(),
            uptime_seconds: 0,
        }
    }

    pub fn add_log(&mut self, log: String) {
        self.recent_logs.push(log);
        if self.recent_logs.len() > 20 {
            self.recent_logs.remove(0);
        }
    }

    pub fn set_current_task(&mut self, task: Option<String>) {
        self.current_task = task;
    }

    pub fn complete_task(&mut self, success: bool) {
        if success {
            self.tasks_completed += 1;
        } else {
            self.tasks_failed += 1;
        }
        self.current_task = None;
    }

    pub fn increment_uptime(&mut self) {
        self.uptime_seconds += 1;
    }

    fn success_rate(&self) -> f64 {
        let total = self.tasks_completed + self.tasks_failed;
        if total == 0 {
            return 0.0;
        }
        (self.tasks_completed as f64 / total as f64) * 100.0
    }
}

pub async fn run_tui() -> Result<()> {
    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut monitor = AgentMonitor::new();
    monitor.add_log("🦀 ViraClip Rust Agent TUI started".to_string());
    monitor.add_log("📡 Monitoring agent activity...".to_string());

    // Simulate some activity for demonstration
    monitor.set_current_task(Some("Rendering clip_001.mp4".to_string()));

    loop {
        terminal.draw(|f| {
            let size = f.size();

            // Main layout
            let chunks = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(3),  // Title
                    Constraint::Length(7),  // Stats
                    Constraint::Min(10),    // Logs
                    Constraint::Length(3),  // Footer
                ])
                .split(size);

            // Title
            let title = Paragraph::new("🦀 ViraClip Rust Agent Monitor")
                .style(Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD))
                .alignment(Alignment::Center)
                .block(Block::default().borders(Borders::ALL));
            f.render_widget(title, chunks[0]);

            // Stats section
            let stats_chunks = Layout::default()
                .direction(Direction::Horizontal)
                .constraints([
                    Constraint::Percentage(50),
                    Constraint::Percentage(50),
                ])
                .split(chunks[1]);

            // Left stats
            let uptime_hours = monitor.uptime_seconds / 3600;
            let uptime_mins = (monitor.uptime_seconds % 3600) / 60;
            let uptime_secs = monitor.uptime_seconds % 60;

            let left_stats = vec![
                Line::from(vec![
                    Span::styled("Tasks: ", Style::default().fg(Color::Green)),
                    Span::raw(format!("{} ✅ {} ❌", monitor.tasks_completed, monitor.tasks_failed)),
                ]),
                Line::from(vec![
                    Span::styled("Success Rate: ", Style::default().fg(Color::Green)),
                    Span::raw(format!("{:.1}%", monitor.success_rate())),
                ]),
                Line::from(vec![
                    Span::styled("Uptime: ", Style::default().fg(Color::Green)),
                    Span::raw(format!("{}h {}m {}s", uptime_hours, uptime_mins, uptime_secs)),
                ]),
            ];

            let left_panel = Paragraph::new(left_stats)
                .block(Block::default().title("📊 Statistics").borders(Borders::ALL));
            f.render_widget(left_panel, stats_chunks[0]);

            // Right stats - current task
            let current_task_text = if let Some(ref task) = monitor.current_task {
                format!("🎬 {}", task)
            } else {
                "⏸️  Idle".to_string()
            };

            let right_stats = vec![
                Line::from(vec![Span::styled(
                    "Current Task:",
                    Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
                )]),
                Line::from(vec![Span::raw(current_task_text)]),
            ];

            let right_panel = Paragraph::new(right_stats)
                .block(Block::default().title("⚡ Activity").borders(Borders::ALL));
            f.render_widget(right_panel, stats_chunks[1]);

            // Success rate gauge
            let gauge = Gauge::default()
                .block(Block::default().title("Success Rate").borders(Borders::ALL))
                .gauge_style(Style::default().fg(Color::Green).bg(Color::Black))
                .percent(monitor.success_rate() as u16);
            
            // Add gauge to a small section if needed
            // f.render_widget(gauge, some_chunk);

            // Logs section
            let log_items: Vec<ListItem> = monitor
                .recent_logs
                .iter()
                .rev()
                .map(|log| {
                    let style = if log.contains("✅") {
                        Style::default().fg(Color::Green)
                    } else if log.contains("❌") {
                        Style::default().fg(Color::Red)
                    } else if log.contains("⚠️") {
                        Style::default().fg(Color::Yellow)
                    } else {
                        Style::default().fg(Color::White)
                    };
                    ListItem::new(log.clone()).style(style)
                })
                .collect();

            let logs = List::new(log_items)
                .block(Block::default().title("📜 Recent Logs").borders(Borders::ALL));
            f.render_widget(logs, chunks[2]);

            // Footer
            let footer = Paragraph::new("Press 'q' to quit | 'r' to refresh")
                .style(Style::default().fg(Color::DarkGray))
                .alignment(Alignment::Center)
                .block(Block::default().borders(Borders::ALL));
            f.render_widget(footer, chunks[3]);
        })?;

        // Poll for events with timeout
        if event::poll(Duration::from_millis(1000))? {
            if let Event::Key(key) = event::read()? {
                match key.code {
                    KeyCode::Char('q') => break,
                    KeyCode::Char('r') => {
                        monitor.add_log("🔄 Manual refresh".to_string());
                    }
                    _ => {}
                }
            }
        }

        // Increment uptime
        monitor.increment_uptime();

        // Simulate task completion
        if monitor.uptime_seconds % 10 == 0 && monitor.current_task.is_some() {
            monitor.complete_task(true);
            monitor.add_log(format!("✅ Task completed (uptime: {}s)", monitor.uptime_seconds));
        }

        // Simulate new task
        if monitor.uptime_seconds % 15 == 0 && monitor.current_task.is_none() {
            let new_task = format!("clip_{:03}.mp4", (monitor.uptime_seconds / 15) % 100);
            monitor.set_current_task(Some(format!("Rendering {}", new_task)));
            monitor.add_log(format!("🎬 Starting task: {}", new_task));
        }
    }

    // Restore terminal
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;

    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    run_tui().await
}
