//! Text editor view with LSP diagnostic display.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, List, ListItem};

use crate::app::App;
use crate::lsp::{DftCodeType, DiagnosticSeverity};

pub fn render(frame: &mut Frame, app: &mut App, area: Rect) {
    // Split area: editor (main) + diagnostics panel (bottom, if any diagnostics)
    let has_diagnostics = !app.lsp_diagnostics.is_empty();
    let chunks = if has_diagnostics {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(5), Constraint::Length(6)])
            .split(area)
    } else {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Percentage(100)])
            .split(area)
    };

    // Render editor
    render_editor(frame, app, chunks[0]);

    // Render diagnostics panel if needed
    if has_diagnostics && chunks.len() > 1 {
        render_diagnostics(frame, app, chunks[1]);
    }
}

/// Render the main editor widget.
fn render_editor(frame: &mut Frame, app: &App, area: Rect) {
    // Build title with DFT code type
    let title = build_title(app);

    // Diagnostic indicator
    let diag_indicator = build_diagnostic_indicator(app);

    // Build block with title
    let block = Block::default()
        .borders(Borders::ALL)
        .title(title)
        .title_style(Style::default().fg(Color::Cyan))
        .title_bottom(Line::from(diag_indicator).right_aligned());

    // Render editor widget
    let inner = block.inner(area);
    frame.render_widget(block, area);
    frame.render_widget(&app.editor, inner);
}

/// Render the diagnostics panel below the editor.
fn render_diagnostics(frame: &mut Frame, app: &App, area: Rect) {
    let items: Vec<ListItem> = app
        .lsp_diagnostics
        .iter()
        .take(5) // Limit to 5 diagnostics
        .map(|d| {
            let severity = d.severity.unwrap_or(1);
            let (icon, color) = match DiagnosticSeverity::from_i32(severity) {
                DiagnosticSeverity::Error => ("✗", Color::Red),
                DiagnosticSeverity::Warning => ("!", Color::Yellow),
                DiagnosticSeverity::Information => ("i", Color::Blue),
                DiagnosticSeverity::Hint => ("?", Color::Cyan),
            };

            let line = d.range.start.line + 1; // 1-indexed for display
            let text = format!("{} Line {}: {}", icon, line, d.message);

            ListItem::new(text).style(Style::default().fg(color))
        })
        .collect();

    let remaining = app.lsp_diagnostics.len().saturating_sub(5);
    let title = if remaining > 0 {
        format!(" Diagnostics (+{} more) ", remaining)
    } else {
        " Diagnostics ".to_string()
    };

    let diagnostics_list = List::new(items).block(
        Block::default()
            .borders(Borders::ALL)
            .title(title)
            .border_style(Style::default().fg(Color::Red)),
    );

    frame.render_widget(diagnostics_list, area);
}

/// Build the editor title with file path and DFT code type.
fn build_title(app: &App) -> String {
    let code_type = match app.editor_dft_code {
        Some(DftCodeType::Crystal) => "CRYSTAL23",
        Some(DftCodeType::Vasp) => "VASP",
        None => "Text",
    };

    match &app.editor_file_path {
        Some(path) => {
            // Extract filename from path for cleaner display
            let filename = std::path::Path::new(path)
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or(path);
            format!(" {} Editor: {} ", code_type, filename)
        }
        None => format!(" {} Editor (New File) ", code_type),
    }
}

/// Build diagnostic indicator span for the title bar.
fn build_diagnostic_indicator(app: &App) -> Span<'static> {
    let diag_count = app.lsp_diagnostics.len();

    if diag_count == 0 {
        return Span::styled(" [OK] ", Style::default().fg(Color::Green));
    }

    // Find highest severity
    let has_error = app.lsp_diagnostics.iter().any(|d| {
        d.severity
            .map(|s| DiagnosticSeverity::from_i32(s) == DiagnosticSeverity::Error)
            .unwrap_or(true)
    });

    let has_warning = app.lsp_diagnostics.iter().any(|d| {
        d.severity
            .map(|s| DiagnosticSeverity::from_i32(s) == DiagnosticSeverity::Warning)
            .unwrap_or(false)
    });

    let (text, color) = if has_error {
        (format!(" [{} errors] ", diag_count), Color::Red)
    } else if has_warning {
        (format!(" [{} warnings] ", diag_count), Color::Yellow)
    } else {
        (format!(" [{} notes] ", diag_count), Color::Blue)
    };

    Span::styled(text, Style::default().fg(color).add_modifier(Modifier::BOLD))
}
