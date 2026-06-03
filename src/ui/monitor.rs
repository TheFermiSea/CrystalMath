//! Monitor tab rendering — GPU overview, node health, and SLURM status.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Gauge, Paragraph, Sparkline};

use crate::app::App;
use crate::monitor::{threshold_color, MonitorSubView};

/// Main render entry point for the Monitor tab.
pub fn render(frame: &mut Frame, app: &App, area: Rect) {
    // Sub-view tab bar (top) + content (rest)
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(0)])
        .split(area);

    render_sub_view_tabs(frame, app, chunks[0]);

    match app.monitor.sub_view {
        MonitorSubView::GpuOverview => render_gpu_overview(frame, app, chunks[1]),
        MonitorSubView::NodeHealth => render_node_health(frame, app, chunks[1]),
        MonitorSubView::SlurmStatus => render_slurm_status(frame, app, chunks[1]),
    }
}

/// Render the sub-view tab bar with "Last updated" indicator.
fn render_sub_view_tabs(frame: &mut Frame, app: &App, area: Rect) {
    let tabs: Vec<Span> = MonitorSubView::all()
        .iter()
        .enumerate()
        .flat_map(|(i, sv)| {
            let style = if *sv == app.monitor.sub_view {
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::DarkGray)
            };
            let mut spans = vec![Span::styled(format!(" {} ", sv.name()), style)];
            if i < MonitorSubView::all().len() - 1 {
                spans.push(Span::styled(" │ ", Style::default().fg(Color::DarkGray)));
            }
            spans
        })
        .collect();

    // Connection status + last updated
    let status = if !app.monitor.connected {
        Span::styled(" ● Connecting... ", Style::default().fg(Color::DarkGray))
    } else if let Some(err) = &app.monitor.error {
        Span::styled(format!(" ● {} ", err), Style::default().fg(Color::Red))
    } else if let Some(age) = app.monitor.last_update_age() {
        Span::styled(
            format!(" ● {}s ago ", age.as_secs()),
            Style::default().fg(Color::Green),
        )
    } else {
        Span::styled(" ● Connected ", Style::default().fg(Color::Green))
    };

    // Left: tabs, Right: status
    let left = Line::from(tabs);
    let right = Line::from(vec![status]);

    let inner = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Min(0),
            Constraint::Length(right.width() as u16 + 2),
        ])
        .split(area);

    let block = Block::default().borders(Borders::ALL).title("Monitor");
    let tab_para = Paragraph::new(left).block(block);
    frame.render_widget(tab_para, inner[0]);

    let status_para = Paragraph::new(right)
        .alignment(Alignment::Right)
        .block(Block::default().borders(Borders::ALL));
    frame.render_widget(status_para, inner[1]);
}

// ===== GPU Overview =====

fn render_gpu_overview(frame: &mut Frame, app: &App, area: Rect) {
    if app.monitor.gpu_metrics.is_empty() {
        let msg = if app.monitor.connected {
            "No GPU metrics available"
        } else {
            "Connecting to Prometheus..."
        };
        let p = Paragraph::new(msg)
            .alignment(Alignment::Center)
            .block(Block::default().borders(Borders::ALL).title("GPUs"));
        frame.render_widget(p, area);
        return;
    }

    let gpu_count = app.monitor.gpu_metrics.len();
    let constraints: Vec<Constraint> = (0..gpu_count).map(|_| Constraint::Min(6)).collect();
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints(constraints)
        .split(area);

    for (i, gpu) in app.monitor.gpu_metrics.iter().enumerate() {
        if i >= rows.len() {
            break;
        }
        let selected = i == app.monitor.selected_index;
        render_gpu_panel(frame, gpu, rows[i], selected);
    }
}

fn render_gpu_panel(
    frame: &mut Frame,
    gpu: &crate::monitor::GpuMetrics,
    area: Rect,
    selected: bool,
) {
    let border_style = if selected {
        Style::default().fg(Color::Cyan)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let title = if gpu.memory_total_gb > 0.0 {
        format!(
            " {} / GPU {} ({:.0} GiB) ",
            gpu.node, gpu.gpu_index, gpu.memory_total_gb
        )
    } else {
        format!(" {} / GPU {} ", gpu.node, gpu.gpu_index)
    };
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(title);
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // Util + Temp + Power
            Constraint::Length(1), // Mem + Freq
            Constraint::Min(1),    // Sparkline
        ])
        .split(inner);

    // Row 1: Utilization bar + Temp + Power
    let util_color = threshold_color(gpu.utilization_pct, 70.0, 90.0);
    let temp_color = threshold_color(gpu.temperature_c, 65.0, 80.0);

    let row1 = Line::from(vec![
        Span::raw(" Util: "),
        Span::styled(
            format!("{:3.0}%", gpu.utilization_pct),
            Style::default().fg(util_color).add_modifier(Modifier::BOLD),
        ),
        Span::raw("    Temp: "),
        Span::styled(
            format!("{:.0}°C", gpu.temperature_c),
            Style::default().fg(temp_color),
        ),
        Span::raw("    Power: "),
        Span::raw(if gpu.power_limit_watts > 0.0 {
            format!("{:.0}/{:.0}W", gpu.power_watts, gpu.power_limit_watts)
        } else if gpu.power_watts > 0.0 {
            format!("{:.0}W", gpu.power_watts)
        } else {
            "n/a".to_string()
        }),
    ]);
    frame.render_widget(Paragraph::new(row1), chunks[0]);

    // Row 2: Memory + Freq
    let mem_pct = if gpu.memory_total_gb > 0.0 {
        gpu.memory_used_gb / gpu.memory_total_gb * 100.0
    } else {
        0.0
    };
    let mem_color = threshold_color(mem_pct, 70.0, 90.0);

    let row2 = Line::from(vec![
        Span::raw(" Mem:  "),
        Span::styled(
            format!("{:.1}/{:.1} GiB", gpu.memory_used_gb, gpu.memory_total_gb),
            Style::default().fg(mem_color),
        ),
        Span::raw("    Freq: "),
        Span::raw(format!("{:.0} MHz", gpu.frequency_mhz)),
    ]);
    frame.render_widget(Paragraph::new(row2), chunks[1]);

    // Row 3: Sparkline (utilization history)
    if !gpu.utilization_history.is_empty() {
        let data: Vec<u64> = gpu.utilization_history.iter().copied().collect();
        let sparkline = Sparkline::default()
            .data(&data)
            .max(100)
            .style(Style::default().fg(Color::Cyan));
        frame.render_widget(sparkline, chunks[2]);
    }
}

// ===== GPU Gauge rendering =====

fn render_gauge_line(
    frame: &mut Frame,
    label: &str,
    value: f64,
    max: f64,
    color: Color,
    area: Rect,
) {
    let pct = if max > 0.0 {
        (value / max).min(1.0)
    } else {
        0.0
    };
    let gauge = Gauge::default()
        .gauge_style(Style::default().fg(color))
        .ratio(pct)
        .label(format!("{}: {:.0}%", label, pct * 100.0));
    frame.render_widget(gauge, area);
}

// ===== Node Health =====

fn render_node_health(frame: &mut Frame, app: &App, area: Rect) {
    if app.monitor.node_metrics.is_empty() {
        let msg = if app.monitor.connected {
            "No node metrics available"
        } else {
            "Connecting to Prometheus..."
        };
        let p = Paragraph::new(msg)
            .alignment(Alignment::Center)
            .block(Block::default().borders(Borders::ALL).title("Nodes"));
        frame.render_widget(p, area);
        return;
    }

    let node_count = app.monitor.node_metrics.len();

    // 2x2 grid (or fewer if less than 4 nodes)
    let rows_n = node_count.div_ceil(2).max(1);
    let row_constraints: Vec<Constraint> = (0..rows_n).map(|_| Constraint::Min(7)).collect();
    let row_areas = Layout::default()
        .direction(Direction::Vertical)
        .constraints(row_constraints)
        .split(area);

    for (i, node) in app.monitor.node_metrics.iter().enumerate() {
        let row_idx = i / 2;
        let col_idx = i % 2;
        if row_idx >= row_areas.len() {
            break;
        }
        let cols = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
            .split(row_areas[row_idx]);
        let selected = i == app.monitor.selected_index;
        render_node_panel(frame, node, cols[col_idx], selected);
    }
}

fn render_node_panel(
    frame: &mut Frame,
    node: &crate::monitor::NodeMetrics,
    area: Rect,
    selected: bool,
) {
    let border_style = if selected {
        Style::default().fg(Color::Cyan)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let uptime_str = format_uptime(node.uptime_seconds);
    let title = format!(" {} (up {}) ", node.hostname, uptime_str);
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(title);
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // CPU + Load
            Constraint::Length(1), // RAM
            Constraint::Length(1), // Disk
            Constraint::Min(1),    // Sparkline
        ])
        .split(inner);

    // CPU + Load
    let cpu_color = threshold_color(node.cpu_usage_pct, 70.0, 90.0);
    let row1 = Line::from(vec![
        Span::raw(" CPU: "),
        Span::styled(
            format!("{:5.1}%", node.cpu_usage_pct),
            Style::default().fg(cpu_color).add_modifier(Modifier::BOLD),
        ),
        Span::raw(format!(
            "  Load: {:.1}/{:.1}/{:.1}",
            node.load_1m, node.load_5m, node.load_15m
        )),
    ]);
    frame.render_widget(Paragraph::new(row1), chunks[0]);

    // RAM
    let mem_pct = if node.memory_total_gb > 0.0 {
        node.memory_used_gb / node.memory_total_gb * 100.0
    } else {
        0.0
    };
    let mem_color = threshold_color(mem_pct, 70.0, 90.0);
    let row2 = Line::from(vec![
        Span::raw(" RAM: "),
        Span::styled(
            format!("{:.1}/{:.1} GiB", node.memory_used_gb, node.memory_total_gb),
            Style::default().fg(mem_color),
        ),
        Span::styled(
            format!(" ({:.0}%)", mem_pct),
            Style::default().fg(mem_color),
        ),
    ]);
    frame.render_widget(Paragraph::new(row2), chunks[1]);

    // Disk
    let disk_pct = if node.disk_total_gb > 0.0 {
        node.disk_used_gb / node.disk_total_gb * 100.0
    } else {
        0.0
    };
    let disk_color = threshold_color(disk_pct, 70.0, 90.0);
    let row3 = Line::from(vec![
        Span::raw(" Disk: "),
        Span::styled(format!("{:.0}%", disk_pct), Style::default().fg(disk_color)),
        Span::raw(format!(
            " ({:.1}/{:.1} GiB)",
            node.disk_used_gb, node.disk_total_gb
        )),
    ]);
    frame.render_widget(Paragraph::new(row3), chunks[2]);

    // Sparkline (CPU history)
    if !node.cpu_history.is_empty() {
        let data: Vec<u64> = node.cpu_history.iter().copied().collect();
        let sparkline = Sparkline::default()
            .data(&data)
            .max(100)
            .style(Style::default().fg(Color::Cyan));
        frame.render_widget(sparkline, chunks[3]);
    }
}

// ===== SLURM Status =====

fn render_slurm_status(frame: &mut Frame, app: &App, area: Rect) {
    let metrics = match &app.monitor.slurm_metrics {
        Some(m) => m,
        None => {
            let msg = if app.monitor.connected {
                "No SLURM metrics available"
            } else {
                "Connecting to Prometheus..."
            };
            let p = Paragraph::new(msg)
                .alignment(Alignment::Center)
                .block(Block::default().borders(Borders::ALL).title("SLURM"));
            frame.render_widget(p, area);
            return;
        }
    };

    let block = Block::default()
        .borders(Borders::ALL)
        .title(" SLURM Cluster Status ");
    let inner = block.inner(area);
    frame.render_widget(block, area);

    // Two columns: left = capacity gauges, right = node/job stats
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(inner);

    // Left column: CPU and Memory gauges
    let left_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(2), // CPU gauge
            Constraint::Length(1), // spacer
            Constraint::Length(2), // Memory gauge
            Constraint::Min(0),
        ])
        .split(cols[0]);

    let cpu_used = metrics.cpus_total.saturating_sub(metrics.cpus_idle);
    let cpu_color = threshold_color(
        if metrics.cpus_total > 0 {
            cpu_used as f64 / metrics.cpus_total as f64 * 100.0
        } else {
            0.0
        },
        70.0,
        90.0,
    );
    render_gauge_line(
        frame,
        "CPUs",
        cpu_used as f64,
        metrics.cpus_total as f64,
        cpu_color,
        left_chunks[0],
    );

    let mem_color = threshold_color(
        if metrics.mem_total_gb > 0.0 {
            metrics.mem_alloc_gb / metrics.mem_total_gb * 100.0
        } else {
            0.0
        },
        70.0,
        90.0,
    );
    render_gauge_line(
        frame,
        "Memory",
        metrics.mem_alloc_gb,
        metrics.mem_total_gb,
        mem_color,
        left_chunks[2],
    );

    // Right column: Node states + Job counts
    let right_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Min(0),
        ])
        .split(cols[1]);

    let node_lines = vec![
        Line::from(vec![Span::styled(
            " Nodes ",
            Style::default().add_modifier(Modifier::BOLD),
        )]),
        Line::from(vec![
            Span::styled("  ● ", Style::default().fg(Color::Green)),
            Span::raw(format!("Idle: {}", metrics.nodes_idle)),
            Span::raw("  "),
            Span::styled("  ● ", Style::default().fg(Color::Yellow)),
            Span::raw(format!("Alloc: {}", metrics.nodes_alloc)),
        ]),
        Line::from(vec![
            Span::styled("  ● ", Style::default().fg(Color::Red)),
            Span::raw(format!("Down: {}", metrics.nodes_down)),
            Span::raw("  "),
            Span::styled("  ● ", Style::default().fg(Color::Magenta)),
            Span::raw(format!("Drain: {}", metrics.nodes_drain)),
        ]),
        Line::from(Span::raw("")),
        Line::from(vec![Span::styled(
            " Jobs ",
            Style::default().add_modifier(Modifier::BOLD),
        )]),
        Line::from(vec![
            Span::styled("  ● ", Style::default().fg(Color::Green)),
            Span::raw(format!("Running: {}", metrics.jobs_running)),
            Span::raw("  "),
            Span::styled("  ● ", Style::default().fg(Color::Yellow)),
            Span::raw(format!("Pending: {}", metrics.jobs_pending)),
        ]),
    ];

    for (i, line) in node_lines.into_iter().enumerate() {
        if i < right_chunks.len() {
            frame.render_widget(Paragraph::new(line), right_chunks[i]);
        }
    }
}

// ===== Helpers =====

fn format_uptime(seconds: f64) -> String {
    let secs = seconds as u64;
    let days = secs / 86400;
    let hours = (secs % 86400) / 3600;
    if days > 0 {
        format!("{}d {}h", days, hours)
    } else if hours > 0 {
        format!("{}h", hours)
    } else {
        format!("{}m", secs / 60)
    }
}
