//! Batch Job Submission modal.
//!
//! Allows users to add multiple jobs to a batch and submit them all at once.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Clear, List, ListItem, Paragraph, Wrap};

use crate::app::App;
use crate::state::BatchSubmissionField;

/// Render the batch submission modal overlay.
pub fn render(frame: &mut Frame, app: &App) {
    let area = frame.area();

    // Dim the background
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    // Center the modal (85% width, 85% height)
    let modal_area = centered_rect(85, 85, area);

    // Clear the background
    frame.render_widget(Clear, modal_area);

    // Modal border
    let border_style = if app.batch_submission.error.is_some() {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Cyan)
    };

    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(" Batch Job Submission ")
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(modal_block, modal_area);

    // Layout: Settings (top) | Job List (middle) | Status (bottom) | Buttons (very bottom)
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(8), // Settings
            Constraint::Min(5),    // Job list
            Constraint::Length(3), // Status
            Constraint::Length(3), // Buttons
        ])
        .split(modal_area);

    // Render Settings
    render_settings(frame, app, chunks[0]);

    // Render Job List
    render_job_list(frame, app, chunks[1]);

    // Render Status
    render_status(frame, app, chunks[2]);

    // Render Buttons
    render_buttons(frame, app, chunks[3]);
}

/// Render the common settings for the batch.
fn render_settings(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.batch_submission;

    let block = Block::default()
        .borders(Borders::ALL)
        .title(" Common Settings ")
        .title_style(Style::default().fg(Color::Yellow));
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Length(3)])
        .split(inner);

    // Row 1: Cluster, MPI Ranks
    let row1 = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(chunks[0]);

    // Cluster field
    let is_cluster_focused = state.focused_field == BatchSubmissionField::Cluster;
    let cluster_text = if let Some(id) = state.common_cluster_id {
        format!("Cluster ID: {}", id)
    } else {
        "Local".to_string()
    };
    render_setting_field(frame, row1[0], "Cluster", &cluster_text, is_cluster_focused);

    // MPI Ranks
    let is_ranks_focused = state.focused_field == BatchSubmissionField::MpiRanks;
    render_setting_field(
        frame,
        row1[1],
        "MPI Ranks",
        &state.common_mpi_ranks,
        is_ranks_focused,
    );

    // Row 2: Walltime, Memory
    let row2 = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(chunks[1]);

    let is_wt_focused = state.focused_field == BatchSubmissionField::Walltime;
    render_setting_field(
        frame,
        row2[0],
        "Walltime",
        &state.common_walltime,
        is_wt_focused,
    );

    let is_mem_focused = state.focused_field == BatchSubmissionField::Memory;
    render_setting_field(
        frame,
        row2[1],
        "Memory (GB)",
        &state.common_memory_gb,
        is_mem_focused,
    );
}

/// Helper to render a single setting field.
fn render_setting_field(frame: &mut Frame, area: Rect, label: &str, value: &str, focused: bool) {
    let style = if focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::White)
    };

    let border_style = if focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let paragraph = Paragraph::new(value).style(style).block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(format!(" {} ", label)),
    );
    frame.render_widget(paragraph, area);
}

/// Render the list of jobs in the batch.
fn render_job_list(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.batch_submission;
    let is_focused = state.focused_field == BatchSubmissionField::JobList;

    let border_style = if is_focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    if state.jobs.is_empty() {
        let empty =
            Paragraph::new("No jobs added to batch. Press 'a' to add a job from current editor.")
                .style(Style::default().fg(Color::DarkGray))
                .alignment(Alignment::Center)
                .block(
                    Block::default()
                        .borders(Borders::ALL)
                        .border_style(border_style)
                        .title(" Jobs "),
                );
        frame.render_widget(empty, area);
        return;
    }

    let items: Vec<ListItem> = state
        .jobs
        .iter()
        .enumerate()
        .map(|(idx, job)| {
            let is_selected = state.selected_job_index == Some(idx);
            let style = if is_selected && is_focused {
                Style::default().bg(Color::DarkGray).fg(Color::White)
            } else if is_selected {
                Style::default().bg(Color::DarkGray).fg(Color::Gray)
            } else {
                Style::default().fg(Color::White)
            };

            ListItem::new(format!(" [{}] {} ", job.status, job.name)).style(style)
        })
        .collect();

    let list = List::new(items).block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(format!(" Jobs ({}) ", state.jobs.len())),
    );
    frame.render_widget(list, area);
}

/// Render the status/hints area.
fn render_status(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.batch_submission;

    let (text, style) = if let Some(ref error) = state.error {
        (error.clone(), Style::default().fg(Color::Red))
    } else if state.submitting {
        (
            "Submitting jobs...".to_string(),
            Style::default().fg(Color::Yellow),
        )
    } else {
        let hint = match state.focused_field {
            BatchSubmissionField::Cluster => "Space to cycle runner type / cluster",
            BatchSubmissionField::JobList => "j/k to navigate jobs, 'd' to remove",
            _ => "Tab to navigate, 'a' to add current editor to batch",
        };
        (hint.to_string(), Style::default().fg(Color::DarkGray))
    };

    let paragraph = Paragraph::new(text)
        .style(style)
        .wrap(Wrap { trim: true })
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Status ")
                .title_style(Style::default().fg(Color::Cyan)),
        );

    frame.render_widget(paragraph, area);
}

/// Render the action buttons.
fn render_buttons(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.batch_submission;

    let render_btn = |label: &str, field: BatchSubmissionField, color: Color| {
        let is_focused = state.focused_field == field;
        if is_focused {
            Span::styled(
                format!(" [{}] ", label),
                Style::default()
                    .bg(color)
                    .fg(Color::Black)
                    .add_modifier(Modifier::BOLD),
            )
        } else {
            Span::styled(format!("  {}  ", label), Style::default().fg(color))
        }
    };

    let buttons = Line::from(vec![
        render_btn("Add (a)", BatchSubmissionField::BtnAdd, Color::Green),
        Span::raw("  "),
        render_btn("Remove (d)", BatchSubmissionField::BtnRemove, Color::Red),
        Span::raw("  "),
        render_btn("Submit All", BatchSubmissionField::BtnSubmit, Color::Green),
        Span::raw("  "),
        render_btn("Cancel", BatchSubmissionField::BtnCancel, Color::Yellow),
    ]);

    let paragraph = Paragraph::new(buttons).alignment(Alignment::Center);
    frame.render_widget(paragraph, area);
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
