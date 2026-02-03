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
pub mod recipes;
mod results;
mod slurm_queue;
mod vasp_input;
mod workflows;

pub use cluster_manager::{
    ClusterFormField, ClusterManagerMode, ClusterManagerState, ConnectionTestResult,
};
pub use recipes::RecipeBrowserState;
pub use slurm_queue::SlurmQueueState;
pub use vasp_input::{VaspFileTab, VaspInputState};
pub use workflows::WorkflowState;
// VaspInputFiles is now in crate::models

use ratatui::prelude::*;
use tachyonfx::Shader;

use crate::app::App;

/// Main render function - called every frame.
pub fn render(frame: &mut Frame, app: &mut App) {
    // Check if we have an active startup effect
    // We take it out of the app to avoid borrow checker issues with the closure
    let mut startup_effect = app.startup_effect.take();
    let area = frame.area();

    // Helper to render the actual UI content
    // We need to use RefCell or internal mutability if we were strictly capturing,
    // but since we took the effect out, app is free to be borrowed in the closure.
    // However, FnMut closure capturing &mut App can be tricky.
    // A simpler way is to just define a function and call it.
    let mut render_content = |frame: &mut Frame, _area: Rect| {
        render_app_ui(frame, app);
    };

    // Render content first
    render_content(frame, area);

    // Apply startup effect over the content
    if let Some(ref mut effect) = startup_effect {
        // Assume ~60FPS (16ms per frame)
        let delta = std::time::Duration::from_millis(16);
        effect.process(delta.into(), frame.buffer_mut(), area);
    }

    // Put effect back if it's still running
    if let Some(effect) = startup_effect {
        if effect.running() {
            app.startup_effect = Some(effect);
            // Ensure we keep redrawing while effect is running
            app.mark_dirty();
        } else {
            // Effect finished
            app.startup_effect = None;
            app.mark_dirty();
        }
    }
}

/// Render the core application UI (without top-level effects).
fn render_app_ui(frame: &mut Frame, app: &mut App) {
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

    if app.workflow_state.active {
        workflows::render(frame, &app.workflow_state);
    }

    if app.recipe_browser.active {
        recipes::render(frame, &mut app.recipe_browser);
    }
}
