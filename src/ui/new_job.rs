//! New Job modal for job creation.
//!
//! This modal allows users to create new jobs with:
//! - Job name input
//! - DFT code selection (CRYSTAL23, VASP, Quantum Espresso)
//! - Runner type selection (local, SSH, SLURM)
//! - Cluster selection (for remote runners)

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};

use crate::app::App;
use crate::models::{DftCode, RunnerType};

/// Render the new job modal overlay.
pub fn render(frame: &mut Frame, app: &App) {
    let area = frame.area();

    // Dim the background
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    // Center the modal (70% width, 85% height)
    let modal_area = centered_rect(70, 85, area);

    // Clear the background
    frame.render_widget(Clear, modal_area);

    // Dynamic constraints based on state
    let mut constraints = vec![
        Constraint::Length(3), // Job Name
        Constraint::Length(3), // DFT Code
        Constraint::Length(3), // Runner Type
    ];

    // Cluster (if remote)
    let show_cluster = app.new_job.runner_type != RunnerType::Local;
    if show_cluster {
        constraints.push(Constraint::Length(3));
    }

    // Parallelism
    constraints.push(Constraint::Length(3));

    // Scheduler (SLURM only)
    let show_scheduler = app.new_job.runner_type == RunnerType::Slurm;
    if show_scheduler {
        constraints.push(Constraint::Length(3)); // Row 1: Walltime, Mem
        constraints.push(Constraint::Length(3)); // Row 2: CPUs, Nodes
        constraints.push(Constraint::Length(3)); // Row 3: Partition
    }

    // Aux Files (Crystal only)
    let show_aux = app.new_job.dft_code == DftCode::Crystal;
    if show_aux {
        constraints.push(Constraint::Length(3)); // Gui
        constraints.push(Constraint::Length(3)); // F9
        constraints.push(Constraint::Length(3)); // Hessopt
    }

    constraints.push(Constraint::Min(3)); // Status/Hints
    constraints.push(Constraint::Length(3)); // Buttons

    // Modal layout
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints(constraints)
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
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(modal_block, modal_area);

    // Track current chunk index
    let mut i = 0;

    // Job Name Input
    render_job_name_input(frame, app, chunks[i]);
    i += 1;

    // DFT Code Selector
    render_dft_code_selector(frame, app, chunks[i]);
    i += 1;

    // Runner Type Selector
    render_runner_type_selector(frame, app, chunks[i]);
    i += 1;

    // Cluster Selector
    if show_cluster {
        render_cluster_selector(frame, app, chunks[i]);
        i += 1;
    }

    // Parallelism
    render_parallel_settings(frame, app, chunks[i]);
    i += 1;

    // Scheduler
    if show_scheduler {
        render_scheduler_row1(frame, app, chunks[i]);
        i += 1;
        render_scheduler_row2(frame, app, chunks[i]);
        i += 1;
        render_partition(frame, app, chunks[i]);
        i += 1;
    }

    // Aux Files
    if show_aux {
        render_aux_file(
            frame,
            app,
            chunks[i],
            NewJobField::AuxGui,
            "Geometry (.gui)",
            &app.new_job.aux_gui_path,
            app.new_job.aux_gui_enabled,
        );
        i += 1;
        render_aux_file(
            frame,
            app,
            chunks[i + 0],
            NewJobField::AuxF9,
            "Wavefunction (.f9)",
            &app.new_job.aux_f9_path,
            app.new_job.aux_f9_enabled,
        );
        i += 1;
        render_aux_file(
            frame,
            app,
            chunks[i + 0],
            NewJobField::AuxHessopt,
            "Hessian (.hessopt)",
            &app.new_job.aux_hessopt_path,
            app.new_job.aux_hessopt_enabled,
        );
        i += 1;
    }

    // Status/Hints
    render_status(frame, app, chunks[i]);
    i += 1;

    // Buttons
    render_buttons(frame, app, chunks[i]);
}

/// Render the job name input field.
fn render_job_name_input(frame: &mut Frame, app: &App, area: Rect) {
    let is_focused = app.new_job.focused_field == NewJobField::Name;
    render_input_field(
        frame,
        area,
        " Job Name ",
        &app.new_job.job_name,
        is_focused,
        "Enter job name...",
    );
}

/// Render a generic input field.
fn render_input_field(
    frame: &mut Frame,
    area: Rect,
    title: &str,
    value: &str,
    is_focused: bool,
    placeholder: &str,
) {
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

    let display_value = if value.is_empty() && !is_focused {
        placeholder.to_string()
    } else {
        value.to_string()
    };

    let cursor = if is_focused { "_" } else { "" };

    let paragraph = Paragraph::new(format!("{}{}", display_value, cursor))
        .style(style)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(title)
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

    let selected_code = app.new_job.dft_code.as_str();
    let content = format!("< {} > (Space to cycle)", selected_code);

    let paragraph = Paragraph::new(content)
        .style(if is_focused {
            Style::default().fg(Color::Green)
        } else {
            Style::default()
        })
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(" DFT Code "),
        );
    frame.render_widget(paragraph, area);
}

/// Render the runner type selector.
fn render_runner_type_selector(frame: &mut Frame, app: &App, area: Rect) {
    let is_focused = app.new_job.focused_field == NewJobField::RunnerType;
    let border_style = if is_focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let selected_runner = app.new_job.runner_type.as_str();
    let content = format!("< {} > (Space to cycle)", selected_runner);

    let paragraph = Paragraph::new(content)
        .style(if is_focused {
            Style::default().fg(Color::Green)
        } else {
            Style::default()
        })
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(" Runner Type "),
        );
    frame.render_widget(paragraph, area);
}

/// Render the cluster selector (for remote runners).
fn render_cluster_selector(frame: &mut Frame, app: &App, area: Rect) {
    let is_focused = app.new_job.focused_field == NewJobField::Cluster;
    let border_style = if is_focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let content = if let Some(cluster_id) = app.new_job.cluster_id {
        format!("Cluster ID: {}", cluster_id)
    } else {
        "None selected (use j/k to select)".to_string()
    };

    let paragraph = Paragraph::new(content)
        .style(Style::default().fg(Color::White))
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .title(" Cluster "),
        );
    frame.render_widget(paragraph, area);
}

/// Render parallelism settings (Parallel/Serial toggle and MPI ranks).
fn render_parallel_settings(frame: &mut Frame, app: &App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(area);

    // Toggle
    let is_focused_mode = app.new_job.focused_field == NewJobField::ParallelMode;
    let mode_str = if app.new_job.is_parallel {
        "Parallel (MPI)"
    } else {
        "Serial"
    };
    let border_style_mode = if is_focused_mode {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let mode_widget = Paragraph::new(format!("< {} >", mode_str)).block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(border_style_mode)
            .title(" Mode "),
    );
    frame.render_widget(mode_widget, chunks[0]);

    // Ranks
    let is_focused_ranks = app.new_job.focused_field == NewJobField::MpiRanks;
    render_input_field(
        frame,
        chunks[1],
        " MPI Ranks ",
        &app.new_job.mpi_ranks,
        is_focused_ranks,
        "1",
    );
}

/// Render Scheduler Row 1: Walltime and Memory.
fn render_scheduler_row1(frame: &mut Frame, app: &App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(area);

    let is_focused_wt = app.new_job.focused_field == NewJobField::Walltime;
    render_input_field(
        frame,
        chunks[0],
        " Walltime ",
        &app.new_job.walltime,
        is_focused_wt,
        "24:00:00",
    );

    let is_focused_mem = app.new_job.focused_field == NewJobField::Memory;
    render_input_field(
        frame,
        chunks[1],
        " Memory (GB) ",
        &app.new_job.memory_gb,
        is_focused_mem,
        "32",
    );
}

/// Render Scheduler Row 2: CPUs and Nodes.
fn render_scheduler_row2(frame: &mut Frame, app: &App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(area);

    let is_focused_cpus = app.new_job.focused_field == NewJobField::Cpus;
    render_input_field(
        frame,
        chunks[0],
        " CPUs/Task ",
        &app.new_job.cpus_per_task,
        is_focused_cpus,
        "4",
    );

    let is_focused_nodes = app.new_job.focused_field == NewJobField::Nodes;
    render_input_field(
        frame,
        chunks[1],
        " Nodes ",
        &app.new_job.nodes,
        is_focused_nodes,
        "1",
    );
}

/// Render Partition.
fn render_partition(frame: &mut Frame, app: &App, area: Rect) {
    let is_focused = app.new_job.focused_field == NewJobField::Partition;
    render_input_field(
        frame,
        area,
        " Partition ",
        &app.new_job.partition,
        is_focused,
        "default",
    );
}

/// Render Auxiliary File input.
fn render_aux_file(
    frame: &mut Frame,
    _app: &App,
    area: Rect,
    field: NewJobField,
    title: &str,
    path: &str,
    enabled: bool,
) {
    let is_focused = _app.new_job.focused_field == field;
    let border_style = if is_focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let checkbox = if enabled { "[x] " } else { "[ ] " };
    let content = if enabled && !path.is_empty() {
        path
    } else if enabled {
        "Enter path..."
    } else {
        "Disabled"
    };
    let cursor = if is_focused && enabled { "_" } else { "" };

    let paragraph = Paragraph::new(format!("{}{}{}", checkbox, content, cursor)).block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(border_style)
            .title(title),
    );

    frame.render_widget(paragraph, area);
}

/// Render the status/hints area.
fn render_status(frame: &mut Frame, app: &App, area: Rect) {
    let (text, style) = if let Some(ref error) = app.new_job.error {
        (error.clone(), Style::default().fg(Color::Red))
    } else {
        let hint = match app.new_job.focused_field {
            NewJobField::Name => "Enter job name (alphanumeric, -, _)",
            NewJobField::DftCode => "Space to cycle DFT code",
            NewJobField::RunnerType => "Space to cycle runner type",
            NewJobField::Cluster => "j/k to select cluster",
            NewJobField::ParallelMode => "Space to toggle Serial/Parallel",
            NewJobField::MpiRanks => "Enter number of MPI ranks",
            NewJobField::Walltime => "Enter walltime limit (HH:MM:SS)",
            NewJobField::Memory => "Enter memory per node in GB",
            NewJobField::Cpus => "Enter CPUs per task",
            NewJobField::Nodes => "Enter number of nodes",
            NewJobField::Partition => "Enter SLURM partition/queue",
            NewJobField::AuxGui | NewJobField::AuxF9 | NewJobField::AuxHessopt => {
                "Space to toggle, type to enter path"
            }
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
        Style::default()
            .fg(Color::Green)
            .add_modifier(Modifier::BOLD)
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
