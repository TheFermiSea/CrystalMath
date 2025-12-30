//! New Job modal for job creation.
//!
//! This modal allows users to create new jobs with:
//! - Job name input
//! - DFT code selection (CRYSTAL23, VASP, Quantum Espresso)
//! - Runner type selection (local, SSH, SLURM)
//! - Cluster selection (for remote runners)

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Clear, List, ListItem, Paragraph, Wrap};

use crate::app::App;
use crate::models::DftCode;

/// Render the new job modal overlay.
pub fn render(frame: &mut Frame, app: &App) {
    let area = frame.area();

    // Center the modal (70% width, 80% height)
    let modal_area = centered_rect(70, 80, area);

    // Clear the background
    frame.render_widget(Clear, modal_area);

    // Modal layout: Title, Form Fields, Status, Buttons
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // Job Name
            Constraint::Length(5), // DFT Code
            Constraint::Length(5), // Runner Type
            Constraint::Length(5), // Cluster (if remote)
            Constraint::Min(3),    // Status/Hints
            Constraint::Length(3), // Buttons
        ])
        .split(modal_area);

    // Modal border
    let border_style = if app.new_job.has_error() {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Cyan)
    };

    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(" New Job ")
        .title_style(Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD));
    frame.render_widget(modal_block, modal_area);

    // Job Name Input
    render_job_name_input(frame, app, chunks[0]);

    // DFT Code Selector
    render_dft_code_selector(frame, app, chunks[1]);

    // Runner Type Selector
    render_runner_type_selector(frame, app, chunks[2]);

    // Cluster Selector (if applicable)
    render_cluster_selector(frame, app, chunks[3]);

    // Status/Hints
    render_status(frame, app, chunks[4]);

    // Buttons
    render_buttons(frame, app, chunks[5]);
}

/// Render the job name input field.
fn render_job_name_input(frame: &mut Frame, app: &App, area: Rect) {
    let is_focused = app.new_job.focused_field == NewJobField::Name;

    let style = if is_focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::White)
    };

    let border_style = if is_focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let name_display = if app.new_job.job_name.is_empty() {
        "Enter job name...".to_string()
    } else {
        app.new_job.job_name.clone()
    };

    let cursor = if is_focused { "_" } else { "" };

    let paragraph = Paragraph::new(format!("{}{}", name_display, cursor))
        .style(style)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(" Job Name ")
                .title_style(Style::default().fg(Color::Cyan)),
        );

    frame.render_widget(paragraph, area);
}

/// Render the DFT code selector.
fn render_dft_code_selector(frame: &mut Frame, app: &App, area: Rect) {
    let is_focused = app.new_job.focused_field == NewJobField::DftCode;

    let border_style = if is_focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let codes = [
        ("CRYSTAL23", DftCode::Crystal),
        ("VASP", DftCode::Vasp),
        ("Quantum Espresso", DftCode::QuantumEspresso),
    ];

    let items: Vec<ListItem> = codes
        .iter()
        .map(|(name, code)| {
            let selected = app.new_job.dft_code == *code;
            let prefix = if selected { "[*] " } else { "[ ] " };
            let style = if selected {
                Style::default()
                    .fg(Color::Green)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::White)
            };
            ListItem::new(format!("{}{}", prefix, name)).style(style)
        })
        .collect();

    let list = List::new(items).block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(" DFT Code (Space to cycle) ")
            .title_style(Style::default().fg(Color::Cyan)),
    );

    frame.render_widget(list, area);
}

/// Render the runner type selector.
fn render_runner_type_selector(frame: &mut Frame, app: &App, area: Rect) {
    let is_focused = app.new_job.focused_field == NewJobField::RunnerType;

    let border_style = if is_focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let runners = ["local", "ssh", "slurm"];

    let items: Vec<ListItem> = runners
        .iter()
        .map(|runner| {
            let selected = app.new_job.runner_type == *runner;
            let prefix = if selected { "[*] " } else { "[ ] " };
            let style = if selected {
                Style::default()
                    .fg(Color::Green)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::White)
            };
            ListItem::new(format!("{}{}", prefix, runner)).style(style)
        })
        .collect();

    let list = List::new(items).block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(" Runner Type (Space to cycle) ")
            .title_style(Style::default().fg(Color::Cyan)),
    );

    frame.render_widget(list, area);
}

/// Render the cluster selector (for remote runners).
fn render_cluster_selector(frame: &mut Frame, app: &App, area: Rect) {
    let is_remote = app.new_job.runner_type != "local";
    let is_focused = app.new_job.focused_field == NewJobField::Cluster;

    let border_style = if is_focused && is_remote {
        Style::default().fg(Color::Yellow)
    } else if is_remote {
        Style::default().fg(Color::DarkGray)
    } else {
        Style::default().fg(Color::DarkGray).add_modifier(Modifier::DIM)
    };

    let content = if !is_remote {
        "N/A (local runner)".to_string()
    } else if let Some(cluster_id) = app.new_job.cluster_id {
        format!("Cluster ID: {}", cluster_id)
    } else {
        "None selected (use j/k to select)".to_string()
    };

    let style = if is_remote {
        Style::default().fg(Color::White)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let paragraph = Paragraph::new(content).style(style).block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(" Cluster ")
            .title_style(Style::default().fg(Color::Cyan)),
    );

    frame.render_widget(paragraph, area);
}

/// Render the status/hints area.
fn render_status(frame: &mut Frame, app: &App, area: Rect) {
    let (text, style) = if let Some(ref error) = app.new_job.error {
        (error.clone(), Style::default().fg(Color::Red))
    } else {
        let hint = match app.new_job.focused_field {
            NewJobField::Name => "Enter a unique job name (alphanumeric, hyphens, underscores)",
            NewJobField::DftCode => "Space to cycle through DFT codes",
            NewJobField::RunnerType => "Space to cycle through runner types",
            NewJobField::Cluster => "j/k to navigate clusters (for remote runners)",
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
    let can_submit = app.new_job.can_submit();

    let submit_style = if can_submit {
        Style::default().fg(Color::Green).add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let buttons = Line::from(vec![
        Span::styled(" [Enter] ", submit_style),
        Span::styled("Create", submit_style),
        Span::raw("  "),
        Span::styled(" [Esc] ", Style::default().fg(Color::Yellow)),
        Span::styled("Cancel", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(" [Tab] ", Style::default().fg(Color::Cyan)),
        Span::styled("Next Field", Style::default().fg(Color::White)),
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

// Re-export the field enum for use in keyboard handling
pub use crate::app::NewJobField;
