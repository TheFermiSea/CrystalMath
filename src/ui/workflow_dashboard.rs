//! Workflow progress dashboard (Jobs tab grouped view).

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Cell, Paragraph, Row, Table, TableState, Wrap};

use crate::app::App;
use crate::models::JobState;
use crate::state::{WorkflowDashboardFocus, WorkflowStatus};

pub fn render(frame: &mut Frame, app: &App, area: Rect) {
    if app.workflow_list.workflows.is_empty() {
        render_empty_state(frame, app, area);
        return;
    }

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(0), Constraint::Length(3)])
        .split(area);

    let body_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(35), Constraint::Percentage(65)])
        .split(chunks[0]);

    render_workflow_list(frame, app, body_chunks[0]);
    render_workflow_jobs(frame, app, body_chunks[1]);
    render_status(frame, app, chunks[1]);
}

fn render_workflow_list(frame: &mut Frame, app: &App, area: Rect) {
    let focus = app.workflow_list.focus == WorkflowDashboardFocus::Workflows;
    let border_style = if focus {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let header = Row::new(vec![
        Cell::from("Workflow").style(Style::default().fg(Color::Yellow)),
        Cell::from("Status").style(Style::default().fg(Color::Yellow)),
        Cell::from("Done").style(Style::default().fg(Color::Yellow)),
        Cell::from("Fail").style(Style::default().fg(Color::Yellow)),
    ])
    .height(1)
    .bottom_margin(1);

    let rows: Vec<Row> = app
        .workflow_list
        .workflows
        .iter()
        .map(|wf| {
            let status_style = Style::default().fg(workflow_status_color(wf.status));
            Row::new(vec![
                Cell::from(wf.workflow_id.clone()),
                Cell::from(wf.status.as_str()).style(status_style),
                Cell::from(format!("{}/{}", wf.completed_jobs, wf.total_jobs)),
                Cell::from(format!("{}", wf.failed_jobs)),
            ])
        })
        .collect();

    let widths = [
        Constraint::Min(16),
        Constraint::Length(10),
        Constraint::Length(10),
        Constraint::Length(6),
    ];

    let title = format!(" Workflows ({}) ", app.workflow_list.workflows.len());
    let table = Table::new(rows, widths)
        .header(header)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(title),
        )
        .row_highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    let mut state = TableState::default();
    state.select(app.workflow_list.selected_workflow);
    frame.render_stateful_widget(table, area, &mut state);
}

fn render_workflow_jobs(frame: &mut Frame, app: &App, area: Rect) {
    let focus = app.workflow_list.focus == WorkflowDashboardFocus::Jobs;
    let border_style = if focus {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let Some(summary) = app.selected_workflow_summary() else {
        let empty = Paragraph::new("Select a workflow to view jobs")
            .style(Style::default().fg(Color::DarkGray))
            .alignment(Alignment::Center)
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(border_style)
                    .title(" Workflow Jobs "),
            );
        frame.render_widget(empty, area);
        return;
    };

    let title = format!(
        " Workflow {} │ {} / {} done │ {} failed │ {} running │ {} pending ",
        summary.workflow_id, summary.completed_jobs, summary.total_jobs, summary.failed_jobs
        , summary.running_jobs, summary.pending_jobs
    );

    let header = Row::new(vec![
        Cell::from("ID").style(Style::default().fg(Color::Yellow)),
        Cell::from("Name").style(Style::default().fg(Color::Yellow)),
        Cell::from("Status").style(Style::default().fg(Color::Yellow)),
        Cell::from("Info").style(Style::default().fg(Color::Yellow)),
    ])
    .height(1)
    .bottom_margin(1);

    let rows: Vec<Row> = app
        .selected_workflow_jobs()
        .unwrap_or_default()
        .iter()
        .map(|job| {
            let status_style = Style::default().fg(job.state.color());
            let status_text = format!("{}", job.state.as_str());
            let status_cell = Cell::from(status_text).style(status_style);

            let info_text = if job.state == JobState::Running {
                format!("{:.0}%", job.progress_percent)
            } else if job.state == JobState::Completed {
                "100%".to_string()
            } else if job.state == JobState::Failed {
                job.error_snippet
                    .as_ref()
                    .map(|s| {
                        if s.len() > 18 {
                            format!("{}...", &s[..15])
                        } else {
                            s.clone()
                        }
                    })
                    .unwrap_or_else(|| "Error".to_string())
            } else {
                "-".to_string()
            };

            Row::new(vec![
                Cell::from(job.pk.to_string()),
                Cell::from(job.name.clone()),
                status_cell,
                Cell::from(info_text),
            ])
        })
        .collect();

    let widths = [
        Constraint::Length(6),
        Constraint::Min(20),
        Constraint::Length(12),
        Constraint::Length(18),
    ];

    let table = Table::new(rows, widths)
        .header(header)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(title),
        )
        .row_highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    let mut state = TableState::default();
    state.select(app.workflow_list.selected_job);
    frame.render_stateful_widget(table, area, &mut state);
}

fn render_status(frame: &mut Frame, app: &App, area: Rect) {
    let (text, style) = if let Some(ref msg) = app.workflow_list.status {
        let color = if app.workflow_list.status_is_error {
            Color::Red
        } else {
            Color::Green
        };
        (msg.clone(), Style::default().fg(color))
    } else {
        (
            "Tab: switch pane │ Enter: details │ r: retry failed │ Esc: back"
                .to_string(),
            Style::default().fg(Color::DarkGray),
        )
    };

    let paragraph = Paragraph::new(text)
        .style(style)
        .wrap(Wrap { trim: true })
        .block(Block::default().borders(Borders::ALL).title(" Status "));
    frame.render_widget(paragraph, area);
}

fn render_empty_state(frame: &mut Frame, _app: &App, area: Rect) {
    let text = Paragraph::new(
        "No workflow-linked jobs found.\n\nSubmit jobs via a workflow to see progress here.",
    )
    .style(Style::default().fg(Color::DarkGray))
    .alignment(Alignment::Center)
    .wrap(Wrap { trim: true })
    .block(
        Block::default()
            .borders(Borders::ALL)
            .title(" Workflow Dashboard "),
    );
    frame.render_widget(text, area);
}

fn workflow_status_color(status: WorkflowStatus) -> Color {
    match status {
        WorkflowStatus::Pending => Color::Yellow,
        WorkflowStatus::Running => Color::Green,
        WorkflowStatus::Completed => Color::Blue,
        WorkflowStatus::Failed => Color::Red,
    }
}
