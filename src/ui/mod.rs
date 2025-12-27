//! UI rendering module.
//!
//! This module contains all the rendering logic for the TUI.

mod header;
mod jobs;
mod editor;
mod results;
mod log;
mod footer;

use ratatui::prelude::*;

use crate::app::App;

/// Main render function - called every frame.
pub fn render(frame: &mut Frame, app: &mut App) {
    // Main layout: Header, Content, Footer
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),  // Header
            Constraint::Min(0),     // Content
            Constraint::Length(3),  // Footer
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
}
