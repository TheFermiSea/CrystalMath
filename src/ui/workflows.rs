//! Workflow launcher modal overlay.
//!
//! Renders a centered modal with:
//! - List of available workflow types
//! - Workflow descriptions
//! - Status/error messages
//! - Loading indicator

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Cell, Clear, Paragraph, Row, Table, TableState};
use tachyonfx::{fx, Effect, Motion};

use crate::models::WorkflowType;

/// State for the workflow launcher modal.
#[derive(Debug, Default)]
pub struct WorkflowState {
    /// Whether the modal is active.
    pub active: bool,
    /// Selected workflow index.
    pub selected: usize,
    /// Whether we're loading workflow availability.
    pub loading: bool,
    /// Whether workflows are available.
    pub workflows_available: bool,
    /// Whether AiiDA is available.
    pub aiida_available: bool,
    /// Status message.
    pub status: Option<String>,
    /// Whether status is an error.
    pub status_is_error: bool,
    /// Request ID for current operation.
    pub request_id: Option<usize>,

    /// Animation effect for open/close.
    pub effect: Option<Effect>,

    /// Whether the modal is closing.
    pub closing: bool,
}

impl WorkflowState {
    /// Create a new workflow state.
    pub fn new() -> Self {
        Self::default()
    }

    /// Open the workflow modal.
    pub fn open(&mut self) {
        self.active = true;
        self.closing = false;
        self.selected = 0;
        self.status = None;
        self.status_is_error = false;
        // Slide in from bottom
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));
    }

    /// Close the workflow modal.
    pub fn close(&mut self) {
        self.closing = true;
        self.status = None;
        self.status_is_error = false;
        // Slide out to bottom
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
    }

    /// Move selection up.
    pub fn select_previous(&mut self) {
        let count = WorkflowType::all().len();
        if self.selected > 0 {
            self.selected -= 1;
        } else {
            self.selected = count - 1;
        }
    }

    /// Move selection down.
    pub fn select_next(&mut self) {
        let count = WorkflowType::all().len();
        self.selected = (self.selected + 1) % count;
    }

    /// Get the currently selected workflow type.
    pub fn selected_workflow(&self) -> WorkflowType {
        WorkflowType::all()[self.selected]
    }

    /// Set status message.
    pub fn set_status(&mut self, message: String, is_error: bool) {
        self.status = Some(message);
        self.status_is_error = is_error;
    }

    /// Set loading state.
    pub fn set_loading(&mut self, loading: bool) {
        self.loading = loading;
    }

    /// Update availability from backend response.
    pub fn set_availability(&mut self, available: bool, aiida_available: bool) {
        self.workflows_available = available;
        self.aiida_available = aiida_available;
    }
}

/// Render the workflow launcher modal overlay.
///
/// This is called on top of the regular content when the modal is active.
pub fn render(frame: &mut Frame, state: &WorkflowState) {
    if !state.active {
        return;
    }

    // Calculate modal size - centered, reasonable size
    let area = frame.area();
    let modal_width = (area.width * 70 / 100).clamp(50, 80);
    let modal_height = (area.height * 60 / 100).clamp(15, 25);

    // Dim the background
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    // Center the modal
    let modal_area = centered_rect(modal_width, modal_height, area);

    // Clear the background for the modal
    frame.render_widget(Clear, modal_area);

    // Main modal block - pulsing border when loading
    let border_color = if state.loading {
        // Cycle through colors to indicate loading
        let colors = [Color::Yellow, Color::Cyan, Color::Green, Color::Magenta];
        let idx = (std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis()
            / 250) as usize
            % colors.len();
        colors[idx]
    } else {
        Color::Magenta
    };

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(border_color))
        .title(" Workflow Launcher ")
        .title_style(
            Style::default()
                .fg(border_color)
                .add_modifier(Modifier::BOLD),
        );

    let inner_area = block.inner(modal_area);
    frame.render_widget(block, modal_area);

    // Layout: Status, Workflow table, Button hints
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(2), // Status message
            Constraint::Min(5),    // Workflow table
            Constraint::Length(2), // Button hints
        ])
        .split(inner_area);

    render_status(frame, state, chunks[0]);
    render_workflow_table(frame, state, chunks[1]);
    render_button_hints(frame, state, chunks[2]);
}

/// Render the status message.
fn render_status(frame: &mut Frame, state: &WorkflowState, area: Rect) {
    let (message, style) = if state.loading {
        // Show loading indicator
        let spinner = ['◐', '◓', '◑', '◒'];
        let idx = (std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis()
            / 200) as usize
            % spinner.len();
        (
            format!(" {} Processing...", spinner[idx]),
            Style::default().fg(Color::Yellow),
        )
    } else if let Some(ref msg) = state.status {
        let color = if state.status_is_error {
            Color::Red
        } else {
            Color::Green
        };
        (format!(" {}", msg), Style::default().fg(color))
    } else if !state.workflows_available {
        (
            " Workflows not available".to_string(),
            Style::default().fg(Color::Yellow),
        )
    } else {
        (
            " Select a workflow to launch".to_string(),
            Style::default().fg(Color::DarkGray),
        )
    };

    let para = Paragraph::new(message).style(style);
    frame.render_widget(para, area);
}

/// Render the workflow selection table.
fn render_workflow_table(frame: &mut Frame, state: &WorkflowState, area: Rect) {
    let workflows = WorkflowType::all();

    // Table header
    let header = Row::new(vec![
        Cell::from("Workflow").style(Style::default().fg(Color::Yellow)),
        Cell::from("Description").style(Style::default().fg(Color::Yellow)),
        Cell::from("Status").style(Style::default().fg(Color::Yellow)),
    ])
    .height(1)
    .bottom_margin(1);

    // Table rows
    let rows: Vec<Row> = workflows
        .iter()
        .map(|wf| {
            // Check availability
            let (status, status_style) = if *wf == WorkflowType::GeometryOptimization {
                if state.aiida_available {
                    ("Ready", Style::default().fg(Color::Green))
                } else {
                    ("AiiDA required", Style::default().fg(Color::Yellow))
                }
            } else if state.workflows_available {
                ("Ready", Style::default().fg(Color::Green))
            } else {
                ("Unavailable", Style::default().fg(Color::DarkGray))
            };

            Row::new(vec![
                Cell::from(wf.as_str()),
                Cell::from(wf.description()),
                Cell::from(status).style(status_style),
            ])
        })
        .collect();

    // Column widths
    let widths = [
        Constraint::Length(22), // Workflow name
        Constraint::Min(30),    // Description
        Constraint::Length(15), // Status
    ];

    let table = Table::new(rows, widths)
        .header(header)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(Style::default().fg(Color::Blue))
                .title(format!(" Workflows ({}) ", workflows.len()))
                .title_style(Style::default().fg(Color::Blue)),
        )
        .row_highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    // Render with state for selection
    let mut table_state = TableState::default();
    table_state.select(Some(state.selected));

    frame.render_stateful_widget(table, area, &mut table_state);
}

/// Render keyboard shortcuts / button hints.
fn render_button_hints(frame: &mut Frame, state: &WorkflowState, area: Rect) {
    let hints = if state.loading {
        vec![
            Span::styled(
                " Esc ",
                Style::default().bg(Color::DarkGray).fg(Color::White),
            ),
            Span::raw(" Cancel "),
        ]
    } else {
        vec![
            Span::styled(
                " Enter ",
                Style::default().bg(Color::Green).fg(Color::Black),
            ),
            Span::raw(" Launch  "),
            Span::styled(" ↑↓ ", Style::default().bg(Color::Blue).fg(Color::White)),
            Span::raw(" Select  "),
            Span::styled(
                " Esc ",
                Style::default().bg(Color::DarkGray).fg(Color::White),
            ),
            Span::raw(" Close "),
        ]
    };

    let hints_line = Line::from(hints);
    let para = Paragraph::new(hints_line).alignment(Alignment::Center);
    frame.render_widget(para, area);
}

/// Create a centered rect with given width and height.
fn centered_rect(width: u16, height: u16, area: Rect) -> Rect {
    let x = area.x + (area.width.saturating_sub(width)) / 2;
    let y = area.y + (area.height.saturating_sub(height)) / 2;
    Rect::new(x, y, width.min(area.width), height.min(area.height))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_workflow_state_navigation() {
        let mut state = WorkflowState::new();
        state.open();

        assert_eq!(state.selected, 0);

        state.select_next();
        assert_eq!(state.selected, 1);

        state.select_previous();
        assert_eq!(state.selected, 0);

        // Wrap around
        state.select_previous();
        assert_eq!(state.selected, WorkflowType::all().len() - 1);
    }

    #[test]
    fn test_workflow_state_open_close() {
        let mut state = WorkflowState::new();
        assert!(!state.active);
        assert!(!state.closing);

        state.open();
        assert!(state.active);
        assert!(!state.closing);
        assert_eq!(state.selected, 0);
        assert!(state.effect.is_some()); // Animation started

        state.close();
        // Animation pattern: closing=true, active still true until animation finishes
        assert!(state.closing);
        assert!(state.active); // Still active during close animation
    }

    #[test]
    fn test_selected_workflow_matches_index() {
        let mut state = WorkflowState::new();
        state.open();

        assert_eq!(state.selected_workflow(), WorkflowType::all()[0]);
        state.select_next();
        assert_eq!(state.selected_workflow(), WorkflowType::all()[1]);
    }

    #[test]
    fn test_workflow_type_all() {
        let all = WorkflowType::all();
        assert!(!all.is_empty());
        assert!(all.contains(&WorkflowType::Convergence));
        assert!(all.contains(&WorkflowType::BandStructure));
        assert!(all.contains(&WorkflowType::Eos));
    }

    #[test]
    fn test_centered_rect() {
        let area = Rect::new(0, 0, 100, 50);
        let modal = centered_rect(60, 30, area);

        assert_eq!(modal.x, 20);
        assert_eq!(modal.y, 10);
        assert_eq!(modal.width, 60);
        assert_eq!(modal.height, 30);
    }
}
