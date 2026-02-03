//! Cluster Manager modal for managing remote cluster configurations.
//!
//! This modal allows users to:
//! - View configured clusters in a table
//! - Add new cluster configurations
//! - Edit existing clusters
//! - Test SSH connections
//! - Delete clusters

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Cell, Clear, List, ListItem, Paragraph, Row, Table, Wrap};

use tachyonfx::{fx, Effect, Motion};

use crate::app::App;
use crate::models::{ClusterConfig, ClusterType};

/// Cluster Manager view mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ClusterManagerMode {
    /// List view - shows all clusters in a table.
    #[default]
    List,
    /// Add new cluster form.
    Add,
    /// Edit existing cluster form.
    Edit,
    /// Confirm delete dialog.
    ConfirmDelete,
}

/// Focused field in add/edit form.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ClusterFormField {
    #[default]
    Name,
    ClusterType,
    Hostname,
    Port,
    Username,
    KeyFile,
    RemoteWorkdir,
    QueueName,
    MaxConcurrent,
}

impl ClusterFormField {
    /// Move to the next field.
    pub fn next(self) -> Self {
        match self {
            Self::Name => Self::ClusterType,
            Self::ClusterType => Self::Hostname,
            Self::Hostname => Self::Port,
            Self::Port => Self::Username,
            Self::Username => Self::KeyFile,
            Self::KeyFile => Self::RemoteWorkdir,
            Self::RemoteWorkdir => Self::QueueName,
            Self::QueueName => Self::MaxConcurrent,
            Self::MaxConcurrent => Self::Name,
        }
    }

    /// Move to the previous field.
    pub fn prev(self) -> Self {
        match self {
            Self::Name => Self::MaxConcurrent,
            Self::ClusterType => Self::Name,
            Self::Hostname => Self::ClusterType,
            Self::Port => Self::Hostname,
            Self::Username => Self::Port,
            Self::KeyFile => Self::Username,
            Self::RemoteWorkdir => Self::KeyFile,
            Self::QueueName => Self::RemoteWorkdir,
            Self::MaxConcurrent => Self::QueueName,
        }
    }
}

/// Cluster Manager modal state.
#[derive(Debug, Clone, Default)]
pub struct ClusterManagerState {
    /// Whether the modal is active.
    pub active: bool,
    /// Current view mode.
    pub mode: ClusterManagerMode,
    /// Cached clusters from the backend.
    pub clusters: Vec<ClusterConfig>,
    /// Selected cluster index in list view.
    pub selected_index: Option<usize>,
    /// Loading state.
    pub loading: bool,
    /// Error message.
    pub error: Option<String>,
    /// Status message.
    pub status: Option<String>,
    /// Request ID for async operations.
    pub request_id: usize,
    /// Connection test result.
    pub connection_result: Option<ConnectionTestResult>,

    // Form state for add/edit
    /// Currently focused form field.
    pub focused_field: ClusterFormField,
    /// Form: cluster name.
    pub form_name: String,
    /// Form: cluster type (ssh, slurm).
    pub form_cluster_type: ClusterType,
    /// Form: hostname.
    pub form_hostname: String,
    /// Form: port.
    pub form_port: String,
    /// Form: username.
    pub form_username: String,
    /// Form: key file path.
    pub form_key_file: String,
    /// Form: remote workdir.
    pub form_remote_workdir: String,
    /// Form: queue name (for SLURM).
    pub form_queue_name: String,
    /// Form: max concurrent jobs.
    pub form_max_concurrent: String,
    /// ID of cluster being edited (None for add mode).
    pub editing_cluster_id: Option<i32>,

    /// Animation effect for open/close.
    pub effect: Option<Effect>,

    /// Whether the modal is closing.
    pub closing: bool,
}

/// Connection test result.
#[derive(Debug, Clone)]
pub struct ConnectionTestResult {
    pub success: bool,
    pub system_info: Option<String>,
    pub error: Option<String>,
}

impl ClusterManagerState {
    /// Open the cluster manager modal.
    pub fn open(&mut self) {
        self.active = true;
        self.closing = false;
        self.mode = ClusterManagerMode::List;
        // Slide in from bottom
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));
        self.selected_index = None;
        self.error = None;
    }

    /// Close the cluster manager modal.
    pub fn close(&mut self) {
        self.closing = true;
        // Slide out to bottom
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
        self.mode = ClusterManagerMode::List;
        self.reset_form();
    }

    /// Reset the form fields to defaults.
    pub fn reset_form(&mut self) {
        self.clear_form();
        self.error = None;
    }

    /// Clear the form fields.
    pub fn clear_form(&mut self) {
        self.form_name.clear();
        self.form_cluster_type = ClusterType::Ssh;
        self.form_hostname.clear();
        self.form_port = "22".to_string();
        self.form_username.clear();
        self.form_key_file.clear();
        self.form_remote_workdir.clear();
        self.form_queue_name.clear();
        self.form_max_concurrent = "4".to_string();
        self.focused_field = ClusterFormField::Name;
        self.editing_cluster_id = None;
    }

    /// Switch to add mode.
    pub fn start_add(&mut self) {
        self.mode = ClusterManagerMode::Add;
        self.clear_form();
        self.error = None;
    }

    /// Switch to edit mode for the selected cluster.
    pub fn start_edit(&mut self) {
        if let Some(idx) = self.selected_index {
            if let Some(cluster) = self.clusters.get(idx) {
                self.mode = ClusterManagerMode::Edit;
                self.editing_cluster_id = cluster.id;
                self.form_name = cluster.name.clone();
                self.form_cluster_type = cluster.cluster_type;
                self.form_hostname = cluster.hostname.clone();
                self.form_port = cluster.port.to_string();
                self.form_username = cluster.username.clone();
                self.form_key_file = cluster.key_file.clone().unwrap_or_default();
                self.form_remote_workdir = cluster.remote_workdir.clone().unwrap_or_default();
                self.form_queue_name = cluster.queue_name.clone().unwrap_or_default();
                self.form_max_concurrent = cluster.max_concurrent.to_string();
                self.focused_field = ClusterFormField::Name;
                self.error = None;
            }
        }
    }

    /// Switch to confirm delete mode.
    pub fn start_delete(&mut self) {
        if self.selected_index.is_some() {
            self.mode = ClusterManagerMode::ConfirmDelete;
            self.error = None;
        }
    }

    /// Cancel current operation and return to list view.
    pub fn cancel(&mut self) {
        self.mode = ClusterManagerMode::List;
        self.error = None;
        self.connection_result = None;
    }

    /// Move selection up in list view.
    pub fn select_prev(&mut self) {
        if let Some(idx) = self.selected_index {
            if idx > 0 {
                self.selected_index = Some(idx - 1);
            }
        } else if !self.clusters.is_empty() {
            self.selected_index = Some(0);
        }
    }

    /// Move selection down in list view.
    pub fn select_next(&mut self) {
        if let Some(idx) = self.selected_index {
            if idx + 1 < self.clusters.len() {
                self.selected_index = Some(idx + 1);
            }
        } else if !self.clusters.is_empty() {
            self.selected_index = Some(0);
        }
    }

    /// Get the currently selected cluster.
    pub fn selected_cluster(&self) -> Option<&ClusterConfig> {
        self.selected_index.and_then(|idx| self.clusters.get(idx))
    }

    /// Build a ClusterConfig from form state.
    pub fn build_config(&self) -> Result<ClusterConfig, String> {
        if self.form_name.trim().is_empty() {
            return Err("Cluster name is required".to_string());
        }
        if self.form_hostname.trim().is_empty() {
            return Err("Hostname is required".to_string());
        }
        if self.form_username.trim().is_empty() {
            return Err("Username is required".to_string());
        }

        let port = self
            .form_port
            .parse::<i32>()
            .map_err(|_| "Invalid port number")?;
        let max_concurrent = self
            .form_max_concurrent
            .parse::<i32>()
            .map_err(|_| "Invalid max concurrent")?;

        Ok(ClusterConfig {
            id: self.editing_cluster_id,
            name: self.form_name.trim().to_string(),
            cluster_type: self.form_cluster_type,
            hostname: self.form_hostname.trim().to_string(),
            port,
            username: self.form_username.trim().to_string(),
            key_file: if self.form_key_file.trim().is_empty() {
                None
            } else {
                Some(self.form_key_file.trim().to_string())
            },
            remote_workdir: if self.form_remote_workdir.trim().is_empty() {
                None
            } else {
                Some(self.form_remote_workdir.trim().to_string())
            },
            queue_name: if self.form_queue_name.trim().is_empty() {
                None
            } else {
                Some(self.form_queue_name.trim().to_string())
            },
            max_concurrent,
            status: crate::models::ClusterStatus::Active,
        })
    }

    /// Set the status message.
    pub fn set_status(&mut self, msg: &str, is_error: bool) {
        if is_error {
            self.error = Some(msg.to_string());
            self.status = None;
        } else {
            self.status = Some(msg.to_string());
            self.error = None;
        }
    }
}

/// Render the cluster manager modal overlay.
pub fn render(frame: &mut Frame, app: &App) {
    let area = frame.area();

    // Dim the background
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    // Center the modal (80% width, 85% height)
    let modal_area = centered_rect(80, 85, area);

    // Clear the background
    frame.render_widget(Clear, modal_area);

    match app.cluster_manager.mode {
        ClusterManagerMode::List => render_list_view(frame, app, modal_area),
        ClusterManagerMode::Add | ClusterManagerMode::Edit => {
            render_form_view(frame, app, modal_area)
        }
        ClusterManagerMode::ConfirmDelete => render_delete_confirm(frame, app, modal_area),
    }
}

/// Render the cluster list view.
fn render_list_view(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.cluster_manager;

    // Modal border
    let border_style = if state.error.is_some() {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Cyan)
    };

    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(" Cluster Manager ")
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(modal_block, area);

    // Layout: Table, Status, Buttons
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Min(5),    // Cluster table
            Constraint::Length(4), // Status/Result
            Constraint::Length(3), // Buttons
        ])
        .split(area);

    // Render cluster table
    if state.loading {
        let loading = Paragraph::new("Loading clusters...")
            .style(Style::default().fg(Color::Yellow))
            .alignment(Alignment::Center);
        frame.render_widget(loading, chunks[0]);
    } else if state.clusters.is_empty() {
        let empty = Paragraph::new("No clusters configured. Press 'a' to add a new cluster.")
            .style(Style::default().fg(Color::DarkGray))
            .alignment(Alignment::Center);
        frame.render_widget(empty, chunks[0]);
    } else {
        render_cluster_table(frame, app, chunks[0]);
    }

    // Render status area
    render_list_status(frame, app, chunks[1]);

    // Render buttons
    render_list_buttons(frame, chunks[2]);
}

/// Render the cluster table.
fn render_cluster_table(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.cluster_manager;

    let header = Row::new(vec![
        "Name", "Type", "Hostname", "User", "Port", "Max Jobs", "Status",
    ])
    .style(
        Style::default()
            .fg(Color::Cyan)
            .add_modifier(Modifier::BOLD),
    )
    .height(1);

    let rows: Vec<Row> = state
        .clusters
        .iter()
        .enumerate()
        .map(|(idx, cluster)| {
            let is_selected = state.selected_index == Some(idx);
            // Use is_available() to dim unavailable clusters
            let is_available = cluster.status.is_available();
            let style = if is_selected {
                Style::default().bg(Color::DarkGray).fg(Color::White)
            } else if !is_available {
                // Dim unavailable clusters for visual distinction
                Style::default().fg(Color::DarkGray)
            } else {
                Style::default().fg(Color::White)
            };

            // Use ClusterStatus::color() for status display
            let status_cell = Cell::from(cluster.status.as_str().to_string())
                .style(Style::default().fg(cluster.status.color()));

            Row::new(vec![
                Cell::from(cluster.name.clone()),
                Cell::from(cluster.cluster_type.as_str().to_string()),
                Cell::from(cluster.hostname.clone()),
                Cell::from(cluster.username.clone()),
                Cell::from(cluster.port.to_string()),
                Cell::from(cluster.max_concurrent.to_string()),
                status_cell,
            ])
            .style(style)
            .height(1)
        })
        .collect();

    let table = Table::new(
        rows,
        [
            Constraint::Percentage(18), // Name
            Constraint::Percentage(10), // Type
            Constraint::Percentage(25), // Hostname
            Constraint::Percentage(15), // User
            Constraint::Percentage(8),  // Port
            Constraint::Percentage(10), // Max Jobs
            Constraint::Percentage(14), // Status
        ],
    )
    .header(header)
    .block(Block::default().borders(Borders::ALL).title(" Clusters "));

    frame.render_widget(table, area);
}

/// Render the status area in list view.
fn render_list_status(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.cluster_manager;

    let (text, style) = if let Some(ref error) = state.error {
        (format!("Error: {}", error), Style::default().fg(Color::Red))
    } else if let Some(ref result) = state.connection_result {
        if result.success {
            let info = result.system_info.as_deref().unwrap_or("-");
            (
                format!("Connection OK: {}", info),
                Style::default().fg(Color::Green),
            )
        } else {
            let err = result.error.as_deref().unwrap_or("Unknown error");
            (
                format!("Connection failed: {}", err),
                Style::default().fg(Color::Red),
            )
        }
    } else if let Some(ref status) = state.status {
        (status.clone(), Style::default().fg(Color::White))
    } else {
        (
            "Select a cluster and press 't' to test connection".to_string(),
            Style::default().fg(Color::DarkGray),
        )
    };

    let paragraph = Paragraph::new(text)
        .style(style)
        .wrap(Wrap { trim: true })
        .block(Block::default().borders(Borders::ALL).title(" Status "));

    frame.render_widget(paragraph, area);
}

/// Render action buttons for list view.
fn render_list_buttons(_frame: &mut Frame, _area: Rect) {
    let buttons = Line::from(vec![
        Span::styled(
            " a ",
            Style::default()
                .fg(Color::Green)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Add", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " e ",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Edit", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " t ",
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Test", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " d ",
            Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
        ),
        Span::styled("Delete", Style::default().fg(Color::White)),
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
    _frame.render_widget(paragraph, _area);
}

/// Render the add/edit form view.
fn render_form_view(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.cluster_manager;
    let is_edit = state.mode == ClusterManagerMode::Edit;
    let title = if is_edit {
        " Edit Cluster "
    } else {
        " Add Cluster "
    };

    // Modal border
    let border_style = if state.error.is_some() {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Cyan)
    };

    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(title)
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(modal_block, area);

    // Form layout
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // Name
            Constraint::Length(3), // Cluster Type
            Constraint::Length(3), // Hostname
            Constraint::Length(3), // Port + Username (horizontal)
            Constraint::Length(3), // Key File
            Constraint::Length(3), // Remote Workdir
            Constraint::Length(3), // Queue Name + Max Concurrent (horizontal)
            Constraint::Min(2),    // Status
            Constraint::Length(3), // Buttons
        ])
        .split(area);

    // Render form fields
    render_text_input(
        frame,
        "Name",
        &state.form_name,
        state.focused_field == ClusterFormField::Name,
        chunks[0],
    );
    render_type_selector(
        frame,
        state.form_cluster_type,
        state.focused_field == ClusterFormField::ClusterType,
        chunks[1],
    );
    render_text_input(
        frame,
        "Hostname",
        &state.form_hostname,
        state.focused_field == ClusterFormField::Hostname,
        chunks[2],
    );

    // Port + Username in horizontal layout
    let port_user_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(30), Constraint::Percentage(70)])
        .split(chunks[3]);
    render_text_input(
        frame,
        "Port",
        &state.form_port,
        state.focused_field == ClusterFormField::Port,
        port_user_chunks[0],
    );
    render_text_input(
        frame,
        "Username",
        &state.form_username,
        state.focused_field == ClusterFormField::Username,
        port_user_chunks[1],
    );

    render_text_input(
        frame,
        "Key File (optional)",
        &state.form_key_file,
        state.focused_field == ClusterFormField::KeyFile,
        chunks[4],
    );
    render_text_input(
        frame,
        "Remote Workdir (optional)",
        &state.form_remote_workdir,
        state.focused_field == ClusterFormField::RemoteWorkdir,
        chunks[5],
    );

    // Queue Name + Max Concurrent in horizontal layout
    let queue_max_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(70), Constraint::Percentage(30)])
        .split(chunks[6]);
    render_text_input(
        frame,
        "Queue Name (SLURM)",
        &state.form_queue_name,
        state.focused_field == ClusterFormField::QueueName,
        queue_max_chunks[0],
    );
    render_text_input(
        frame,
        "Max Jobs",
        &state.form_max_concurrent,
        state.focused_field == ClusterFormField::MaxConcurrent,
        queue_max_chunks[1],
    );

    // Status
    let (text, style) = if let Some(ref error) = state.error {
        (error.clone(), Style::default().fg(Color::Red))
    } else {
        (
            "Tab to navigate, Enter to save".to_string(),
            Style::default().fg(Color::DarkGray),
        )
    };
    let status = Paragraph::new(text)
        .style(style)
        .block(Block::default().borders(Borders::ALL).title(" Status "));
    frame.render_widget(status, chunks[7]);

    // Buttons
    let buttons = Line::from(vec![
        Span::styled(
            " Enter ",
            Style::default()
                .fg(Color::Green)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Save", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " Esc ",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Cancel", Style::default().fg(Color::White)),
    ]);
    let paragraph = Paragraph::new(buttons).alignment(Alignment::Center);
    frame.render_widget(paragraph, chunks[8]);
}

/// Render a text input field.
fn render_text_input(frame: &mut Frame, label: &str, value: &str, focused: bool, area: Rect) {
    let border_style = if focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let cursor = if focused { "_" } else { "" };
    let display = if value.is_empty() && !focused {
        "...".to_string()
    } else {
        format!("{}{}", value, cursor)
    };

    let paragraph = Paragraph::new(display)
        .style(Style::default().fg(Color::White))
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(format!(" {} ", label))
                .title_style(Style::default().fg(Color::Cyan)),
        );

    frame.render_widget(paragraph, area);
}

/// Render the cluster type selector.
fn render_type_selector(frame: &mut Frame, current_type: ClusterType, focused: bool, area: Rect) {
    let border_style = if focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let types = [ClusterType::Ssh, ClusterType::Slurm];
    let items: Vec<ListItem> = types
        .iter()
        .map(|t| {
            let selected = *t == current_type;
            let prefix = if selected { "[*] " } else { "[ ] " };
            let style = if selected {
                Style::default()
                    .fg(Color::Green)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::White)
            };
            ListItem::new(format!("{}{}", prefix, t.as_str())).style(style)
        })
        .collect();

    let list = List::new(items)
        .direction(ratatui::widgets::ListDirection::TopToBottom)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(" Cluster Type (Space to cycle) ")
                .title_style(Style::default().fg(Color::Cyan)),
        );

    frame.render_widget(list, area);
}

/// Render the delete confirmation dialog.
fn render_delete_confirm(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.cluster_manager;

    // Center a smaller dialog
    let dialog_area = centered_rect(50, 30, area);
    frame.render_widget(Clear, dialog_area);

    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Red))
        .title(" Confirm Delete ")
        .title_style(Style::default().fg(Color::Red).add_modifier(Modifier::BOLD));
    frame.render_widget(modal_block, dialog_area);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(2)
        .constraints([
            Constraint::Min(3),    // Message
            Constraint::Length(3), // Buttons
        ])
        .split(dialog_area);

    let cluster_name = state
        .selected_cluster()
        .map(|c| c.name.as_str())
        .unwrap_or("Unknown");

    let message = Paragraph::new(format!(
        "Are you sure you want to delete cluster '{}'?\n\nThis action cannot be undone.",
        cluster_name
    ))
    .style(Style::default().fg(Color::White))
    .alignment(Alignment::Center)
    .wrap(Wrap { trim: true });
    frame.render_widget(message, chunks[0]);

    let buttons = Line::from(vec![
        Span::styled(
            " y ",
            Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
        ),
        Span::styled("Yes, Delete", Style::default().fg(Color::White)),
        Span::raw("    "),
        Span::styled(
            " n ",
            Style::default()
                .fg(Color::Green)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("No, Cancel", Style::default().fg(Color::White)),
    ]);
    let paragraph = Paragraph::new(buttons).alignment(Alignment::Center);
    frame.render_widget(paragraph, chunks[1]);
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
