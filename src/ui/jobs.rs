//! Jobs list view.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Cell, Row, Table, TableState};

use crate::app::App;
use crate::models::JobState;

pub fn render(frame: &mut Frame, app: &App, area: Rect) {
    // Table header
    let header = Row::new(vec![
        Cell::from("ID").style(Style::default().fg(Color::Yellow)),
        Cell::from("Name").style(Style::default().fg(Color::Yellow)),
        Cell::from("Status").style(Style::default().fg(Color::Yellow)),
        Cell::from("Progress").style(Style::default().fg(Color::Yellow)),
        Cell::from("Time").style(Style::default().fg(Color::Yellow)),
        Cell::from("Code").style(Style::default().fg(Color::Yellow)),
    ])
    .height(1)
    .bottom_margin(1);

    // Table rows
    let rows: Vec<Row> = app
        .jobs
        .iter()
        .map(|job| {
            // Status cell with color
            let status_style = Style::default().fg(job.state.color());
            let status_cell = Cell::from(job.state.as_str()).style(status_style);

            // Progress bar visualization
            let progress = if job.state == JobState::Running {
                format!("{:.0}%", job.progress_percent)
            } else if job.state == JobState::Completed {
                "100%".to_string()
            } else {
                "-".to_string()
            };

            // DFT code
            let code = job
                .dft_code
                .map(|c| c.as_str())
                .unwrap_or("-");

            Row::new(vec![
                Cell::from(job.pk.to_string()),
                Cell::from(job.name.clone()),
                status_cell,
                Cell::from(progress),
                Cell::from(job.wall_time_display()),
                Cell::from(code),
            ])
        })
        .collect();

    // Column widths
    let widths = [
        Constraint::Length(6),   // ID
        Constraint::Min(20),     // Name
        Constraint::Length(12),  // Status
        Constraint::Length(10),  // Progress
        Constraint::Length(12),  // Time
        Constraint::Length(8),   // Code
    ];

    let table = Table::new(rows, widths)
        .header(header)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Jobs ")
                .title_style(Style::default().fg(Color::Cyan)),
        )
        .row_highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    // Render with state for selection
    let mut state = TableState::default();
    state.select(app.selected_job_index);

    frame.render_stateful_widget(table, area, &mut state);
}
