//! SLURM Queue modal view for monitoring and managing remote batch jobs.
//!
//! This modal displays the SLURM queue for a selected cluster, showing:
//! - Job ID, user, name, state, partition
//! - Resource allocation (nodes, GPUs)
//! - Time usage and limits
//! - Node assignments
//! - State reasons for pending/failed jobs
//!
//! Supports:
//! - Real-time queue refresh
//! - Job cancellation
//! - State-based colorization
//! - Detailed status information

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Cell, Clear, Paragraph, Row, Table, Wrap};

use crate::app::App;
use crate::models::SlurmQueueEntry;

/// SLURM Queue modal state.
#[derive(Debug, Clone, Default)]
pub struct SlurmQueueState {
    /// Whether the modal is active.
    pub active: bool,
    /// Loading state.
    pub loading: bool,
    /// Error message.
    pub error: Option<String>,
    /// Selected job index in the queue.
    pub selected_index: Option<usize>,
    /// ID of the cluster being queried.
    pub cluster_id: Option<i32>,
    /// Request ID for async operations.
    pub request_id: usize,
}

impl SlurmQueueState {
    /// Open the modal and trigger a queue fetch for the given cluster.
    pub fn open(&mut self, cluster_id: i32) {
        self.active = true;
        self.loading = true;
        self.error = None;
        self.cluster_id = Some(cluster_id);
        self.selected_index = None;
    }

    /// Close the modal.
    pub fn close(&mut self) {
        self.active = false;
        self.loading = false;
        self.error = None;
        self.selected_index = None;
    }

    /// Move selection up in the queue list.
    pub fn select_prev(&mut self, queue_len: usize) {
        if queue_len == 0 {
            self.selected_index = None;
            return;
        }

        if let Some(idx) = self.selected_index {
            if idx > 0 {
                self.selected_index = Some(idx - 1);
            }
        } else {
            self.selected_index = Some(0);
        }
    }

    /// Move selection down in the queue list.
    pub fn select_next(&mut self, queue_len: usize) {
        if queue_len == 0 {
            self.selected_index = None;
            return;
        }

        if let Some(idx) = self.selected_index {
            if idx + 1 < queue_len {
                self.selected_index = Some(idx + 1);
            }
        } else {
            self.selected_index = Some(0);
        }
    }

    /// Get the currently selected queue entry.
    pub fn selected_entry<'a>(&self, queue: &'a [SlurmQueueEntry]) -> Option<&'a SlurmQueueEntry> {
        self.selected_index.and_then(|idx| queue.get(idx))
    }
}

/// Render the SLURM queue modal overlay.
pub fn render(frame: &mut Frame, app: &App) {
    let area = frame.area();

    // Center the modal (85% width, 80% height)
    let modal_area = centered_rect(85, 80, area);

    // Clear the background
    frame.render_widget(Clear, modal_area);

    // Modal border
    let border_style = if app.slurm_queue_state.error.is_some() {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Cyan)
    };

    // Build title with cluster name and job counts
    let title = build_queue_title(app);

    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(title)
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(modal_block, modal_area);

    // Layout: Queue table, Status, Footer
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Min(5),    // Queue table
            Constraint::Length(4), // Status/Details
            Constraint::Length(3), // Footer buttons
        ])
        .split(modal_area);

    // Render content
    if app.slurm_queue_state.loading {
        render_loading(frame, chunks[0]);
    } else if app.slurm_queue.is_empty() {
        render_empty_queue(frame, chunks[0]);
    } else {
        render_queue_table(frame, app, chunks[0]);
    }

    render_status_area(frame, app, chunks[1]);
    render_footer(frame, chunks[2]);
}

/// Build the modal title with cluster name and job counts.
fn build_queue_title(app: &App) -> String {
    // Get cluster name
    let cluster_name = app
        .slurm_queue_state
        .cluster_id
        .and_then(|id| {
            app.cluster_manager
                .clusters
                .iter()
                .find(|c| c.id == Some(id))
                .map(|c| c.name.clone())
        })
        .unwrap_or_else(|| "Unknown".to_string());

    // Count jobs by state
    let total = app.slurm_queue.len();
    let running = app
        .slurm_queue
        .iter()
        .filter(|j| j.state.to_uppercase() == "RUNNING")
        .count();
    let pending = app
        .slurm_queue
        .iter()
        .filter(|j| j.state.to_uppercase() == "PENDING")
        .count();

    format!(
        " SLURM Queue: {} - {} jobs ({} running, {} pending) ",
        cluster_name, total, running, pending
    )
}

/// Render loading message.
fn render_loading(frame: &mut Frame, area: Rect) {
    let loading = Paragraph::new("Loading SLURM queue...")
        .style(Style::default().fg(Color::Yellow))
        .alignment(Alignment::Center);
    frame.render_widget(loading, area);
}

/// Render empty queue message.
fn render_empty_queue(frame: &mut Frame, area: Rect) {
    let empty = Paragraph::new("No jobs in SLURM queue.\n\nPress 'r' to refresh.")
        .style(Style::default().fg(Color::DarkGray))
        .alignment(Alignment::Center);
    frame.render_widget(empty, area);
}

/// Render the SLURM queue table.
fn render_queue_table(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.slurm_queue_state;

    let header = Row::new(vec![
        "JobID",
        "User",
        "Name",
        "State",
        "Partition",
        "Nodes",
        "GPUs",
        "Time",
        "NodeList",
    ])
    .style(
        Style::default()
            .fg(Color::Cyan)
            .add_modifier(Modifier::BOLD),
    )
    .height(1);

    let rows: Vec<Row> = app
        .slurm_queue
        .iter()
        .enumerate()
        .map(|(idx, entry)| {
            let is_selected = state.selected_index == Some(idx);

            // Base style based on selection
            let base_style = if is_selected {
                Style::default().bg(Color::DarkGray).fg(Color::White)
            } else {
                Style::default().fg(Color::White)
            };

            let state_color = match entry.state.to_uppercase().as_str() {
                "RUNNING" => Color::Green,
                "PENDING" | "CONFIGURING" => Color::Yellow,
                "COMPLETED" => Color::Blue,
                "FAILED" | "CANCELLED" | "TIMEOUT" | "NODE_FAIL" | "PREEMPTED" => Color::Red,
                _ => {
                    if is_selected {
                        Color::White
                    } else {
                        Color::Gray
                    }
                }
            };

            Row::new(vec![
                Cell::from(entry.job_id.clone()),
                Cell::from(entry.user.clone()),
                Cell::from(truncate(&entry.name, 18)),
                Cell::from(Span::styled(
                    entry.state.clone(),
                    Style::default().fg(state_color),
                )),
                Cell::from(entry.partition.clone()),
                Cell::from(
                    entry
                        .nodes
                        .map(|n| n.to_string())
                        .unwrap_or_else(|| "-".to_string()),
                ),
                Cell::from(
                    entry
                        .gpus
                        .map(|n| n.to_string())
                        .unwrap_or_else(|| "-".to_string()),
                ),
                Cell::from(format_time(&entry.time_used, &entry.time_limit)),
                Cell::from(entry.node_list.clone().unwrap_or_else(|| "-".to_string())),
            ])
            .style(base_style)
            .height(1)
        })
        .collect();

    // Column widths
    let widths = [
        Constraint::Length(10), // JobID
        Constraint::Length(10), // User
        Constraint::Length(18), // Name
        Constraint::Length(12), // State
        Constraint::Length(12), // Partition
        Constraint::Length(6),  // Nodes
        Constraint::Length(6),  // GPUs
        Constraint::Length(12), // Time
        Constraint::Min(10),    // NodeList
    ];

    let table = Table::new(rows, widths)
        .header(header)
        .block(Block::default().borders(Borders::ALL).title(" Jobs "));

    frame.render_widget(table, area);
}

/// Render the status area showing selected job details or error.
fn render_status_area(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.slurm_queue_state;

    let (text, style) = if let Some(ref error) = state.error {
        (format!("Error: {}", error), Style::default().fg(Color::Red))
    } else if let Some(entry) = state.selected_entry(&app.slurm_queue) {
        // Show detailed info about selected job
        let mut details = vec![format!(
            "Job ID: {} | User: {} | Partition: {}",
            entry.job_id, entry.user, entry.partition
        )];

        if let Some(ref reason) = entry.state_reason {
            if !reason.is_empty() {
                details.push(format!("State Reason: {}", reason));
            }
        }

        if let Some(ref nodes) = entry.node_list {
            if !nodes.is_empty() && nodes != "-" {
                details.push(format!("Nodes: {}", nodes));
            }
        }

        (details.join("\n"), Style::default().fg(Color::White))
    } else {
        (
            "Use j/k or arrow keys to select a job. Press 'c' to cancel selected job.".to_string(),
            Style::default().fg(Color::DarkGray),
        )
    };

    let paragraph = Paragraph::new(text)
        .style(style)
        .wrap(Wrap { trim: true })
        .block(Block::default().borders(Borders::ALL).title(" Details "));

    frame.render_widget(paragraph, area);
}

/// Render footer with keybindings.
fn render_footer(frame: &mut Frame, area: Rect) {
    let buttons = Line::from(vec![
        Span::styled(
            " r ",
            Style::default()
                .fg(Color::Green)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Refresh", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " c ",
            Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
        ),
        Span::styled("Cancel Job", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " j/k ",
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Navigate", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " Esc ",
            Style::default()
                .fg(Color::DarkGray)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Close", Style::default().fg(Color::White)),
    ]);

    let paragraph = Paragraph::new(buttons).alignment(Alignment::Center);
    frame.render_widget(paragraph, area);
}

/// Format time display (used/limit).
fn format_time(used: &Option<String>, limit: &Option<String>) -> String {
    match (used, limit) {
        (Some(u), Some(l)) => format!("{}/{}", u, l),
        (Some(u), None) => u.clone(),
        (None, Some(l)) => format!("-/{}", l),
        (None, None) => "-".to_string(),
    }
}

/// Truncate string to max length.
fn truncate(s: &str, max_len: usize) -> String {
    if s.len() > max_len {
        format!("{}...", &s[..max_len - 3])
    } else {
        s.to_string()
    }
}

/// Helper function to create a centered rectangle.
fn centered_rect(percent_x: u16, percent_y: u16, r: Rect) -> Rect {
    let popup_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - percent_y) / 2),
            Constraint::Percentage(percent_y),
            Constraint::Percentage((100 - percent_y) / 2),
        ])
        .split(r);

    Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - percent_x) / 2),
            Constraint::Percentage(percent_x),
            Constraint::Percentage((100 - percent_x) / 2),
        ])
        .split(popup_layout[1])[1]
}
