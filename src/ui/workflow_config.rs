//! Workflow configuration modal overlay.
//!
//! Renders per-workflow parameter forms before launching workflows.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use tui_textarea::TextArea;

use crate::state::{
    BandPathPreset, ConvergenceParameter, WorkflowConfigField, WorkflowConfigState,
};

/// Render the workflow configuration modal.
pub fn render(frame: &mut Frame, state: &WorkflowConfigState) {
    if !state.active {
        return;
    }

    let area = frame.area();

    // Dim the background.
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    // Centered modal area.
    let modal_area = centered_rect(80, 85, area);
    frame.render_widget(Clear, modal_area);

    let border_style = if state.error.is_some() {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Cyan)
    };

    let title = format!(" Workflow Config: {} ", state.workflow_type.as_str());
    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(title)
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );

    let inner = modal_block.inner(modal_area);
    frame.render_widget(modal_block, modal_area);

    match state.workflow_type {
        crate::models::WorkflowType::Convergence => render_convergence(frame, state, inner),
        crate::models::WorkflowType::BandStructure => render_band_structure(frame, state, inner),
        crate::models::WorkflowType::Phonon => render_phonon(frame, state, inner),
        crate::models::WorkflowType::Eos => render_eos(frame, state, inner),
        crate::models::WorkflowType::GeometryOptimization => {
            render_geometry_opt(frame, state, inner)
        }
    }
}

fn render_convergence(frame: &mut Frame, state: &WorkflowConfigState, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // parameter
            Constraint::Length(3), // values
            Constraint::Min(8),    // base input
            Constraint::Length(3), // status
            Constraint::Length(3), // buttons
        ])
        .split(area);

    render_select_input(
        frame,
        "Parameter (Space to cycle)",
        convergence_param_label(state.convergence.parameter),
        state.focused_field == WorkflowConfigField::ConvergenceParameter,
        chunks[0],
    );

    render_text_input(
        frame,
        "Values (comma-separated)",
        &state.convergence.values,
        state.focused_field == WorkflowConfigField::ConvergenceValues,
        chunks[1],
    );

    render_text_area(
        frame,
        "Base Input (.d12)",
        &state.convergence.base_input,
        state.focused_field == WorkflowConfigField::ConvergenceBaseInput,
        chunks[2],
    );

    render_status(frame, state, chunks[3]);
    render_buttons(frame, state.focused_field, chunks[4]);
}

fn render_band_structure(frame: &mut Frame, state: &WorkflowConfigState, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // source job
            Constraint::Length(3), // path preset
            Constraint::Length(3), // custom path
            Constraint::Length(3), // status
            Constraint::Length(3), // buttons
        ])
        .split(area);

    render_text_input(
        frame,
        "Source Job PK",
        &state.band_structure.source_job_pk,
        state.focused_field == WorkflowConfigField::BandSourceJob,
        chunks[0],
    );

    render_select_input(
        frame,
        "K-Path Preset (Space to cycle)",
        band_path_label(state.band_structure.path_preset),
        state.focused_field == WorkflowConfigField::BandPathPreset,
        chunks[1],
    );

    render_text_input(
        frame,
        "Custom Path (Gamma X M Gamma)",
        &state.band_structure.custom_path,
        state.focused_field == WorkflowConfigField::BandCustomPath,
        chunks[2],
    );

    render_status(frame, state, chunks[3]);
    render_buttons(frame, state.focused_field, chunks[4]);
}

fn render_phonon(frame: &mut Frame, state: &WorkflowConfigState, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // source job
            Constraint::Length(3), // supercell
            Constraint::Length(3), // displacement
            Constraint::Length(3), // status
            Constraint::Length(3), // buttons
        ])
        .split(area);

    render_text_input(
        frame,
        "Source Job PK",
        &state.phonon.source_job_pk,
        state.focused_field == WorkflowConfigField::PhononSourceJob,
        chunks[0],
    );

    let supercell_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(33),
            Constraint::Percentage(33),
            Constraint::Percentage(34),
        ])
        .split(chunks[1]);

    render_text_input(
        frame,
        "Supercell A",
        &state.phonon.supercell_a,
        state.focused_field == WorkflowConfigField::PhononSupercellA,
        supercell_chunks[0],
    );
    render_text_input(
        frame,
        "Supercell B",
        &state.phonon.supercell_b,
        state.focused_field == WorkflowConfigField::PhononSupercellB,
        supercell_chunks[1],
    );
    render_text_input(
        frame,
        "Supercell C",
        &state.phonon.supercell_c,
        state.focused_field == WorkflowConfigField::PhononSupercellC,
        supercell_chunks[2],
    );

    render_text_input(
        frame,
        "Displacement (Angstrom)",
        &state.phonon.displacement,
        state.focused_field == WorkflowConfigField::PhononDisplacement,
        chunks[2],
    );

    render_status(frame, state, chunks[3]);
    render_buttons(frame, state.focused_field, chunks[4]);
}

fn render_eos(frame: &mut Frame, state: &WorkflowConfigState, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // source job
            Constraint::Length(3), // strain min/max
            Constraint::Length(3), // steps
            Constraint::Length(3), // status
            Constraint::Length(3), // buttons
        ])
        .split(area);

    render_text_input(
        frame,
        "Source Job PK",
        &state.eos.source_job_pk,
        state.focused_field == WorkflowConfigField::EosSourceJob,
        chunks[0],
    );

    let strain_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(chunks[1]);

    render_text_input(
        frame,
        "Strain Min",
        &state.eos.strain_min,
        state.focused_field == WorkflowConfigField::EosStrainMin,
        strain_chunks[0],
    );
    render_text_input(
        frame,
        "Strain Max",
        &state.eos.strain_max,
        state.focused_field == WorkflowConfigField::EosStrainMax,
        strain_chunks[1],
    );

    render_text_input(
        frame,
        "Steps",
        &state.eos.strain_steps,
        state.focused_field == WorkflowConfigField::EosStrainSteps,
        chunks[2],
    );

    render_status(frame, state, chunks[3]);
    render_buttons(frame, state.focused_field, chunks[4]);
}

fn render_geometry_opt(frame: &mut Frame, state: &WorkflowConfigState, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // structure pk
            Constraint::Length(3), // code label
            Constraint::Length(3), // fmax
            Constraint::Length(3), // max steps
            Constraint::Length(3), // status
            Constraint::Length(3), // buttons
        ])
        .split(area);

    render_text_input(
        frame,
        "Structure PK",
        &state.geometry_opt.structure_pk,
        state.focused_field == WorkflowConfigField::GeomStructurePk,
        chunks[0],
    );

    render_text_input(
        frame,
        "Code Label",
        &state.geometry_opt.code_label,
        state.focused_field == WorkflowConfigField::GeomCodeLabel,
        chunks[1],
    );

    render_text_input(
        frame,
        "Fmax Threshold",
        &state.geometry_opt.fmax,
        state.focused_field == WorkflowConfigField::GeomFmax,
        chunks[2],
    );

    render_text_input(
        frame,
        "Max Iterations",
        &state.geometry_opt.max_steps,
        state.focused_field == WorkflowConfigField::GeomMaxSteps,
        chunks[3],
    );

    render_status(frame, state, chunks[4]);
    render_buttons(frame, state.focused_field, chunks[5]);
}

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

fn render_select_input(frame: &mut Frame, label: &str, value: &str, focused: bool, area: Rect) {
    let border_style = if focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let paragraph = Paragraph::new(value)
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

fn render_text_area(
    frame: &mut Frame,
    label: &str,
    editor: &TextArea<'static>,
    focused: bool,
    area: Rect,
) {
    let border_style = if focused {
        Style::default().fg(Color::Yellow)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(format!(" {} ", label))
        .title_style(Style::default().fg(Color::Cyan));
    let inner = block.inner(area);

    frame.render_widget(block, area);
    frame.render_widget(editor, inner);
}

fn render_status(frame: &mut Frame, state: &WorkflowConfigState, area: Rect) {
    let (message, style) = if let Some(ref error) = state.error {
        (error.clone(), Style::default().fg(Color::Red))
    } else if let Some(ref status) = state.status {
        (status.clone(), Style::default().fg(Color::Green))
    } else {
        (
            "Tab to navigate, Enter to launch, Esc to cancel".to_string(),
            Style::default().fg(Color::DarkGray),
        )
    };

    let paragraph = Paragraph::new(message)
        .style(style)
        .wrap(Wrap { trim: true })
        .block(Block::default().borders(Borders::ALL).title(" Status "));

    frame.render_widget(paragraph, area);
}

fn render_buttons(frame: &mut Frame, focused: WorkflowConfigField, area: Rect) {
    let launch_style = if focused == WorkflowConfigField::BtnLaunch {
        Style::default()
            .fg(Color::Black)
            .bg(Color::Green)
            .add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(Color::Green).add_modifier(Modifier::BOLD)
    };

    let cancel_style = if focused == WorkflowConfigField::BtnCancel {
        Style::default()
            .fg(Color::Black)
            .bg(Color::DarkGray)
            .add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(Color::DarkGray).add_modifier(Modifier::BOLD)
    };

    let buttons = Line::from(vec![
        Span::styled(" Enter ", launch_style),
        Span::styled("Launch", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(" Esc ", cancel_style),
        Span::styled("Cancel", Style::default().fg(Color::White)),
    ]);

    let paragraph = Paragraph::new(buttons).alignment(Alignment::Center);
    frame.render_widget(paragraph, area);
}

fn convergence_param_label(param: ConvergenceParameter) -> &'static str {
    match param {
        ConvergenceParameter::Kpoints => "kpoints",
        ConvergenceParameter::Shrink => "shrink",
        ConvergenceParameter::Basis => "basis",
        ConvergenceParameter::Encut => "encut",
        ConvergenceParameter::Ecutwfc => "ecutwfc",
    }
}

fn band_path_label(preset: BandPathPreset) -> &'static str {
    match preset {
        BandPathPreset::Auto => "auto",
        BandPathPreset::Cubic => "cubic",
        BandPathPreset::Fcc => "fcc",
        BandPathPreset::Bcc => "bcc",
        BandPathPreset::Hexagonal => "hexagonal",
        BandPathPreset::Tetragonal => "tetragonal",
        BandPathPreset::Custom => "custom",
    }
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
