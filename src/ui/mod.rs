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
        
        if let Some(ref mut effect) = app.materials.effect {
            let delta = std::time::Duration::from_millis(16);
            let area = frame.area();
            let modal_width = (area.width * 80 / 100).clamp(60, 100);
            let modal_height = (area.height * 70 / 100).clamp(20, 35);
            let modal_area = centered_rect_fixed(modal_width, modal_height, area);
            effect.process(delta.into(), frame.buffer_mut(), modal_area);
            
            if !effect.running() {
                if app.materials.closing {
                    app.materials.active = false;
                    app.materials.closing = false;
                    app.materials.effect = None;
                } else {
                    app.materials.effect = None;
                }
            } else {
                app.mark_dirty();
            }
        }
    }

    if app.new_job.active {
        new_job::render(frame, app);
        
        // Apply modal effect if active
        if let Some(ref mut effect) = app.new_job.effect {
            let delta = std::time::Duration::from_millis(16);
            // Calculate modal area (must match new_job::render logic)
            let modal_area = centered_rect(70, 85, frame.area());
            effect.process(delta.into(), frame.buffer_mut(), modal_area);
            
            if !effect.running() {
                if app.new_job.closing {
                    app.new_job.active = false;
                    app.new_job.closing = false;
                    app.new_job.effect = None;
                } else {
                    app.new_job.effect = None;
                }
            } else {
                app.mark_dirty();
            }
        }
    }

    if app.cluster_manager.active {
        cluster_manager::render(frame, app);
        
        if let Some(ref mut effect) = app.cluster_manager.effect {
            let delta = std::time::Duration::from_millis(16);
            let modal_area = centered_rect(80, 85, frame.area());
            effect.process(delta.into(), frame.buffer_mut(), modal_area);
            
            if !effect.running() {
                if app.cluster_manager.closing {
                    app.cluster_manager.active = false;
                    app.cluster_manager.closing = false;
                    app.cluster_manager.effect = None;
                } else {
                    app.cluster_manager.effect = None;
                }
            } else {
                app.mark_dirty();
            }
        }
    }

    if app.slurm_queue_state.active {
        slurm_queue::render(frame, app);
        
        if let Some(ref mut effect) = app.slurm_queue_state.effect {
            let delta = std::time::Duration::from_millis(16);
            let modal_area = centered_rect(85, 80, frame.area());
            effect.process(delta.into(), frame.buffer_mut(), modal_area);
            
            if !effect.running() {
                if app.slurm_queue_state.closing {
                    app.slurm_queue_state.active = false;
                    app.slurm_queue_state.closing = false;
                    app.slurm_queue_state.effect = None;
                } else {
                    app.slurm_queue_state.effect = None;
                }
            } else {
                app.mark_dirty();
            }
        }
    }

    if app.vasp_input_state.active {
        vasp_input::render(frame, app);
        
        if let Some(ref mut effect) = app.vasp_input_state.effect {
            let delta = std::time::Duration::from_millis(16);
            let modal_area = centered_rect(90, 85, frame.area());
            effect.process(delta.into(), frame.buffer_mut(), modal_area);
            
            if !effect.running() {
                if app.vasp_input_state.closing {
                    app.vasp_input_state.active = false;
                    app.vasp_input_state.closing = false;
                    app.vasp_input_state.effect = None;
                } else {
                    app.vasp_input_state.effect = None;
                }
            } else {
                app.mark_dirty();
            }
        }
    }

    if app.workflow_state.active {
        workflows::render(frame, &app.workflow_state);

        if let Some(ref mut effect) = app.workflow_state.effect {
            let delta = std::time::Duration::from_millis(16);
            let area = frame.area();
            let modal_width = (area.width * 70 / 100).clamp(50, 80);
            let modal_height = (area.height * 60 / 100).clamp(15, 25);
            let modal_area = centered_rect_fixed(modal_width, modal_height, area);
            effect.process(delta.into(), frame.buffer_mut(), modal_area);

            if !effect.running() {
                if app.workflow_state.closing {
                    app.workflow_state.active = false;
                    app.workflow_state.closing = false;
                    app.workflow_state.effect = None;
                } else {
                    app.workflow_state.effect = None;
                }
            } else {
                app.mark_dirty();
            }
        }
    }

    if app.recipe_browser.active {
        recipes::render(frame, &mut app.recipe_browser);

        if let Some(ref mut effect) = app.recipe_browser.effect {
            let delta = std::time::Duration::from_millis(16);
            let modal_area = centered_rect(80, 80, frame.area());
            effect.process(delta.into(), frame.buffer_mut(), modal_area);

            if !effect.running() {
                if app.recipe_browser.closing {
                    app.recipe_browser.active = false;
                    app.recipe_browser.closing = false;
                    app.recipe_browser.effect = None;
                } else {
                    app.recipe_browser.effect = None;
                }
            } else {
                app.mark_dirty();
            }
        }
    }
}

/// Helper function to create a centered rectangle (replicated from new_job).
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

/// Helper for fixed-size centered rect with clamping (for Materials/Workflow).
fn centered_rect_fixed(width: u16, height: u16, area: Rect) -> Rect {
    let x = area.x + (area.width.saturating_sub(width)) / 2;
    let y = area.y + (area.height.saturating_sub(height)) / 2;
    Rect::new(x, y, width.min(area.width), height.min(area.height))
}
