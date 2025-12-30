//! UI rendering module.
//!
//! This module contains all the rendering logic for the TUI.

mod cluster_manager;
mod editor;
mod footer;
mod header;
mod jobs;
mod log;
mod materials;
mod new_job;
mod results;
mod slurm_queue;
mod vasp_input;

pub use cluster_manager::{
    ClusterFormField, ClusterManagerMode, ClusterManagerState, ConnectionTestResult,
};
pub use slurm_queue::SlurmQueueState;
pub use vasp_input::{VaspFileTab, VaspInputFiles, VaspInputState};

use ratatui::prelude::*;

use crate::app::App;

/// Main render function - called every frame.
pub fn render(frame: &mut Frame, app: &mut App) {
    // Main layout: Header, Content, Footer
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Header
            Constraint::Min(0),    // Content
            Constraint::Length(3), // Footer
        ])
        .split(frame.area());

    // Render header
    header::render(frame, app, chunks[0]);

    // Render content based on current tab
    match app.current_tab {
        crate::app::AppTab::Jobs => jobs::render(frame, app, chunks[1]),
        crate::app::AppTab::Editor => editor::render(frame, app, chunks[1]),
        crate::app::AppTab::Results => results::render(frame, app, chunks[1]),
        crate::app::AppTab::Log => log::render(frame, app, chunks[1]),
    }

    // Render footer
    footer::render(frame, app, chunks[2]);

    // Render modal overlays on top of everything
    if app.materials.active {
        materials::render(frame, app);
    }

    if app.new_job.active {
        new_job::render(frame, app);
    }

    if app.cluster_manager.active {
        cluster_manager::render(frame, app);
    }

    if app.slurm_queue_state.active {
        slurm_queue::render(frame, app);
    }

    if app.vasp_input_state.active {
        vasp_input::render(frame, app);
    }
}
