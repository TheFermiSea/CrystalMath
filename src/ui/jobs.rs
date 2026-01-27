//! Jobs list view with status dashboard.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Cell, Paragraph, Row, Table, TableState, Wrap};

use crate::app::App;
use crate::models::JobState;

/// Format elapsed time in a human-readable way.
fn format_elapsed(elapsed: std::time::Duration) -> String {
    let secs = elapsed.as_secs();
    if secs < 60 {
        format!("{}s ago", secs)
    } else if secs < 3600 {
        format!("{}m ago", secs / 60)
    } else {
        format!("{}h ago", secs / 3600)
    }
}

pub fn render(frame: &mut Frame, app: &App, area: Rect) {
    // Handle empty state with helpful message
    if app.jobs_state.jobs.is_empty() {
        render_empty_state(frame, app, area);
        return;
    }

    // Table header
    let header = Row::new(vec![
        Cell::from("ID").style(Style::default().fg(Color::Yellow)),
        Cell::from("Name").style(Style::default().fg(Color::Yellow)),
        Cell::from("Status").style(Style::default().fg(Color::Yellow)),
        Cell::from("Info").style(Style::default().fg(Color::Yellow)), // Progress % or error snippet
        Cell::from("Time").style(Style::default().fg(Color::Yellow)),
        Cell::from("Code").style(Style::default().fg(Color::Yellow)),
    ])
    .height(1)
    .bottom_margin(1);

    // Table rows with changed job highlighting
    let rows: Vec<Row> = app
        .jobs_state
        .jobs
        .iter()
        .map(|job| {
            // Check if this job changed since last refresh
            let is_changed = app.jobs_state.changed_pks.contains(&job.pk);

            // Status cell with color
            let status_style = Style::default().fg(job.state.color());
            let status_text = if is_changed {
                format!("● {}", job.state.as_str()) // Bullet for changed jobs
            } else {
                job.state.as_str().to_string()
            };
            let status_cell = Cell::from(status_text).style(status_style);

            // Progress bar visualization / Error snippet for failed jobs
            let (progress_text, progress_style) = if job.state == JobState::Running {
                (format!("{:.0}%", job.progress_percent), Style::default())
            } else if job.state == JobState::Completed {
                ("100%".to_string(), Style::default().fg(Color::Blue))
            } else if job.state == JobState::Failed {
                // Show error snippet for failed jobs (truncated to fit column)
                let error_text = job
                    .error_snippet
                    .as_ref()
                    .map(|s: &String| {
                        if s.len() > 12 {
                            format!("{}...", &s[..9])
                        } else {
                            s.clone()
                        }
                    })
                    .unwrap_or_else(|| "Error".to_string());
                (error_text, Style::default().fg(Color::Red))
            } else {
                ("-".to_string(), Style::default())
            };
            let progress_cell = Cell::from(progress_text).style(progress_style);

            // DFT code
            let code = job
                .dft_code
                .map(|c: crate::models::DftCode| c.as_str())
                .unwrap_or("-");

            // Base row style - bold if changed
            let row_style = if is_changed {
                Style::default().add_modifier(Modifier::BOLD)
            } else {
                Style::default()
            };

            Row::new(vec![
                Cell::from(job.pk.to_string()),
                Cell::from(job.name.clone()),
                status_cell,
                progress_cell,
                Cell::from(job.wall_time_display()),
                Cell::from(code),
            ])
            .style(row_style)
        })
        .collect();

    // Column widths
    let widths = [
        Constraint::Length(6),  // ID
        Constraint::Min(20),    // Name
        Constraint::Length(14), // Status (wider for bullet)
        Constraint::Length(12), // Info (progress % or error snippet)
        Constraint::Length(12), // Time
        Constraint::Length(8),  // Code
    ];

    // Build title with refresh timestamp and job counts
    let (running, failed, completed) = count_job_states(&app.jobs_state.jobs);
    let refresh_info = app
        .jobs_state
        .last_refresh
        .map(|t| format_elapsed(t.elapsed()))
        .unwrap_or_else(|| "never".to_string());

    let title = format!(
        " Jobs │ {} {} {} │ {} ",
        format_status_count(running, "▶", Color::Green),
        format_status_count(failed, "✗", Color::Red),
        format_status_count(completed, "✓", Color::Blue),
        refresh_info
    );

    let table = Table::new(rows, widths)
        .header(header)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(title)
                .title_style(Style::default().fg(Color::Cyan)),
        )
        .row_highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    // Render with state for selection
    let mut state = TableState::default();
    state.select(app.jobs_state.selected_index);

    frame.render_stateful_widget(table, area, &mut state);
}

/// Count jobs by state category.
fn count_job_states(jobs: &[crate::models::JobStatus]) -> (usize, usize, usize) {
    let mut running = 0;
    let mut failed = 0;
    let mut completed = 0;

    for job in jobs {
        // Use is_terminal() to distinguish active from finished jobs
        if job.state.is_terminal() {
            match job.state {
                JobState::Failed => failed += 1,
                JobState::Completed => completed += 1,
                _ => {} // Cancelled counts as terminal but not shown separately
            }
        } else if job.state == JobState::Running {
            running += 1;
        }
    }

    (running, failed, completed)
}

/// Format a status count with icon for the title bar.
fn format_status_count(count: usize, icon: &str, _color: Color) -> String {
    if count > 0 {
        format!("{}{}", icon, count)
    } else {
        format!("{}-", icon)
    }
}

/// Render helpful message when job list is empty.
fn render_empty_state(frame: &mut Frame, app: &App, area: Rect) {
    let cyan = Style::default().fg(Color::Cyan);
    let yellow_bold = Style::default()
        .fg(Color::Yellow)
        .add_modifier(Modifier::BOLD);
    let gray = Style::default().fg(Color::DarkGray);
    let green = Style::default().fg(Color::Green);

    // Last refresh info
    let refresh_info = app
        .jobs_state
        .last_refresh
        .map(|t| format!("Last refresh: {}", format_elapsed(t.elapsed())))
        .unwrap_or_else(|| "Press Ctrl+R to refresh".to_string());

    let message = vec![
        Line::from(""),
        Line::from(Span::styled("No jobs found", yellow_bold)),
        Line::from(""),
        Line::from("To get started:"),
        Line::from(""),
        Line::from(vec![
            Span::styled("  1. ", cyan),
            Span::raw("Press "),
            Span::styled("Tab", cyan),
            Span::raw(" to switch to the Editor tab"),
        ]),
        Line::from(vec![
            Span::styled("  2. ", cyan),
            Span::raw("Paste your input file content"),
        ]),
        Line::from(vec![
            Span::styled("  3. ", cyan),
            Span::raw("Press "),
            Span::styled("Ctrl+Enter", cyan),
            Span::raw(" to submit"),
        ]),
        Line::from(""),
        Line::from(Span::styled(
            "Or use the Python TUI for full job creation:",
            gray,
        )),
        Line::from(Span::styled("  cd tui && uv run crystal-tui", green)),
        Line::from(""),
        Line::from(vec![
            Span::styled("Press ", gray),
            Span::styled("L", cyan),
            Span::styled(" to view job logs, ", gray),
            Span::styled("Ctrl+R", cyan),
            Span::styled(" to refresh", gray),
        ]),
        Line::from(""),
        Line::from(Span::styled(refresh_info, gray)),
    ];

    let paragraph = Paragraph::new(message)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Jobs ")
                .title_style(Style::default().fg(Color::Cyan)),
        )
        .alignment(Alignment::Center)
        .wrap(Wrap { trim: true });

    frame.render_widget(paragraph, area);
}
