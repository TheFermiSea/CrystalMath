//! Workflow results modal view.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};

use crate::app::App;
use crate::state::{ConvergenceResultsCache, EosResultsCache, WorkflowResultsCache};

pub fn render(frame: &mut Frame, app: &App) {
    if !app.workflow_results.active {
        return;
    }

    let area = frame.area();

    // Dim background
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    let modal_area = centered_rect(80, 80, area);
    frame.render_widget(Clear, modal_area);

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan))
        .title(" Workflow Results ")
        .title_style(Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD));

    let inner = block.inner(modal_area);
    frame.render_widget(block, modal_area);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(2),
            Constraint::Min(0),
            Constraint::Length(2),
        ])
        .split(inner);

    let workflow_id = app
        .workflow_results
        .workflow_id
        .as_deref()
        .unwrap_or("-");

    let (status_text, status_style) = if let Some(ref err) = app.workflow_results.error {
        (format!("Error: {}", err), Style::default().fg(Color::Red))
    } else if let Some(ref status) = app.workflow_results.status {
        (status.clone(), Style::default().fg(Color::Yellow))
    } else {
        (
            format!("Workflow: {}", workflow_id),
            Style::default().fg(Color::DarkGray),
        )
    };

    let status = Paragraph::new(status_text)
        .style(status_style)
        .wrap(Wrap { trim: true });
    frame.render_widget(status, chunks[0]);

    let content = match app.workflow_results.cache.as_ref() {
        Some(WorkflowResultsCache::Convergence(cache)) => {
            build_convergence_text(workflow_id, cache)
        }
        Some(WorkflowResultsCache::Eos(cache)) => build_eos_text(workflow_id, cache),
        None => Text::from("Awaiting results..."),
    };

    let body = Paragraph::new(content)
        .wrap(Wrap { trim: false })
        .scroll((app.workflow_results.scroll as u16, 0));
    frame.render_widget(body, chunks[1]);

    let footer = Paragraph::new("Esc: close | Up/Down: scroll")
        .style(Style::default().fg(Color::DarkGray))
        .alignment(Alignment::Center);
    frame.render_widget(footer, chunks[2]);
}

fn build_convergence_text(workflow_id: &str, cache: &ConvergenceResultsCache) -> Text<'static> {
    let mut lines: Vec<Line> = Vec::new();

    lines.push(Line::from(format!("Workflow: {}", workflow_id)));
    lines.push(Line::from(format!("Parameter: {}", cache.parameter)));
    if let Some(ref converged) = cache.converged_value {
        lines.push(Line::from(format!("Converged value: {}", converged)));
    }
    if let Some(ref recommendation) = cache.recommendation {
        lines.push(Line::from(format!("Recommendation: {}", recommendation)));
    }
    lines.push(Line::from(""));

    lines.push(Line::from("Value       Energy           E/atom          Status"));
    lines.push(Line::from("----------------------------------------------------"));

    for point in &cache.points {
        let value = truncate(&point.parameter_value, 10);
        let energy = format_energy(point.energy);
        let energy_pa = format_energy(point.energy_per_atom);
        let status = truncate(&point.status, 10);
        lines.push(Line::from(format!(
            "{:<10} {:>14} {:>14} {:<10}",
            value, energy, energy_pa, status
        )));
    }

    lines.push(Line::from(""));
    lines.push(Line::from("Plot: energy vs parameter"));
    lines.extend(build_convergence_plot(&cache.points));

    Text::from(lines)
}

fn build_convergence_plot(points: &[crate::state::ConvergencePointCache]) -> Vec<Line<'static>> {
    let mut energies: Vec<(String, f64)> = Vec::new();
    for point in points {
        let energy = point.energy_per_atom.or(point.energy);
        if let Some(value) = energy {
            energies.push((point.parameter_value.clone(), value));
        }
    }

    if energies.len() < 2 {
        return vec![Line::from("(awaiting energy values)")];
    }

    let mut min = f64::INFINITY;
    let mut max = f64::NEG_INFINITY;
    for (_, value) in &energies {
        if *value < min {
            min = *value;
        }
        if *value > max {
            max = *value;
        }
    }
    let span = if (max - min).abs() < 1e-12 { 1.0 } else { max - min };

    let width: usize = 40;
    let mut lines = Vec::new();
    for (label, value) in energies {
        let pos = (((value - min) / span) * (width as f64 - 1.0)).round() as usize;
        let mut chars = vec![' '; width];
        if pos < width {
            chars[pos] = '*';
        }
        let plot: String = chars.into_iter().collect();
        lines.push(Line::from(format!("{:<10} |{}", truncate(&label, 10), plot)));
    }

    lines
}

fn build_eos_text(workflow_id: &str, cache: &EosResultsCache) -> Text<'static> {
    let mut lines: Vec<Line> = Vec::new();

    lines.push(Line::from(format!("Workflow: {}", workflow_id)));
    if let Some(ref status) = cache.status {
        lines.push(Line::from(format!("Status: {}", status)));
    }

    if let Some(ref err) = cache.error_message {
        lines.push(Line::from(format!("Error: {}", err)));
    }

    if cache.v0.is_some() || cache.e0.is_some() || cache.b0.is_some() {
        lines.push(Line::from(""));
        lines.push(Line::from("Fit parameters"));
        lines.push(Line::from("--------------"));
        if let Some(v0) = cache.v0 {
            lines.push(Line::from(format!("V0: {:.4}", v0)));
        }
        if let Some(e0) = cache.e0 {
            lines.push(Line::from(format!("E0: {:.6}", e0)));
        }
        if let Some(b0) = cache.b0 {
            lines.push(Line::from(format!("B0: {:.3} GPa", b0)));
        }
        if let Some(bp) = cache.bp {
            lines.push(Line::from(format!("B' : {:.3}", bp)));
        }
        if let Some(residual) = cache.residual {
            lines.push(Line::from(format!("Residual: {:.6}", residual)));
        }
    } else {
        lines.push(Line::from(""));
        lines.push(Line::from("Awaiting results..."));
    }

    if !cache.points.is_empty() {
        lines.push(Line::from(""));
        lines.push(Line::from("Points"));
        lines.push(Line::from("------"));
        lines.push(Line::from("Scale     Volume        Energy         Status"));
        lines.push(Line::from("----------------------------------------------"));
        for point in &cache.points {
            let scale = point
                .volume_scale
                .map(|v| format!("{:.3}", v))
                .unwrap_or_else(|| "-".to_string());
            let volume = point
                .volume
                .map(|v| format!("{:.3}", v))
                .unwrap_or_else(|| "-".to_string());
            let energy = format_energy(point.energy);
            let status = point
                .status
                .as_deref()
                .map(|s| truncate(s, 10))
                .unwrap_or_else(|| "-".to_string());
            lines.push(Line::from(format!(
                "{:<8} {:>10} {:>14} {:<10}",
                scale, volume, energy, status
            )));
        }
    }

    Text::from(lines)
}

fn truncate(value: &str, max: usize) -> String {
    if value.len() <= max {
        value.to_string()
    } else if max <= 3 {
        value[..max].to_string()
    } else {
        format!("{}...", &value[..max - 3])
    }
}

fn format_energy(value: Option<f64>) -> String {
    value
        .map(|v| format!("{:.6}", v))
        .unwrap_or_else(|| "-".to_string())
}

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
