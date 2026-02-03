//! Output file viewer modal.
//!
//! Renders a modal for viewing VASP output files (OUTCAR, vasprun.xml, etc.)
//! with syntax highlighting, line numbers, and scroll support.

use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    prelude::*,
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Clear, Paragraph, Wrap},
    Frame,
};

use crate::state::{OutputFileType, OutputViewerState};

/// VASP keywords to highlight in output files.
const VASP_KEYWORDS: &[&str] = &[
    "TOTEN", "EDIFF", "ENCUT", "ISMEAR", "SIGMA", "IBRION", "ISIF", "NSW",
    "POTIM", "NELM", "NELMIN", "NELMDL", "PREC", "ALGO", "LREAL", "LWAVE",
    "LCHARG", "LORBIT", "ISPIN", "MAGMOM", "KPOINTS", "POSCAR", "POTCAR",
    "WARNING", "ERROR", "REACHED", "CONVERGED", "iteration", "LOOP",
    "energy", "forces", "stress", "magnetization", "TOTAL-FORCE",
    "E-fermi", "band", "EIGENVAL", "DOSCAR", "OUTCAR", "vasprun.xml",
];

/// CRYSTAL keywords to highlight.
const CRYSTAL_KEYWORDS: &[&str] = &[
    "CRYSTAL", "SLAB", "POLYMER", "MOLECULE", "EXTERNAL", "OPTGEOM",
    "FREQCALC", "ELASTIC", "EOS", "SCF", "TOTAL ENERGY", "CONVERGENCE",
    "GEOMETRY OPTIMIZATION", "CYCLE", "ITERATION", "WARNING", "ERROR",
    "SHRINK", "TOLINTEG", "TOLDEE", "TOLENE", "ANDERSON", "BROYDEN",
];

/// Render the output file viewer modal.
pub fn render(frame: &mut Frame, state: &OutputViewerState) {
    let area = frame.area();

    // Modal size: 90% width, 85% height, centered
    let modal_width = (area.width * 90 / 100).clamp(60, 140);
    let modal_height = (area.height * 85 / 100).clamp(20, 50);
    let modal_area = centered_rect_fixed(modal_width, modal_height, area);

    // Clear the area behind the modal
    frame.render_widget(Clear, modal_area);

    // Build title with file type and job info
    let title = build_title(state);

    // Outer block
    let border_color = if state.loading {
        Color::Yellow
    } else if state.error.is_some() {
        Color::Red
    } else {
        Color::Cyan
    };

    let outer_block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(border_color))
        .title(title)
        .title_style(Style::default().fg(border_color).add_modifier(Modifier::BOLD));

    let inner_area = outer_block.inner(modal_area);
    frame.render_widget(outer_block, modal_area);

    // Layout: content area + status bar
    let layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(0),    // Content
            Constraint::Length(2), // Status/keybindings
        ])
        .split(inner_area);

    // Render content area
    render_content(frame, state, layout[0]);

    // Render status bar
    render_status_bar(frame, state, layout[1]);
}

/// Build the modal title string.
fn build_title(state: &OutputViewerState) -> String {
    let file_type_str = state.file_type.as_str();
    
    match (&state.job_name, state.job_pk) {
        (Some(name), Some(pk)) => format!(" {} - {} (pk:{}) ", file_type_str, name, pk),
        (None, Some(pk)) => format!(" {} (pk:{}) ", file_type_str, pk),
        (Some(name), None) => format!(" {} - {} ", file_type_str, name),
        (None, None) => format!(" {} ", file_type_str),
    }
}

/// Render the main content area (file content or loading/error state).
fn render_content(frame: &mut Frame, state: &OutputViewerState, area: Rect) {
    if state.loading {
        render_loading(frame, area);
        return;
    }

    if let Some(ref error) = state.error {
        render_error(frame, error, area);
        return;
    }

    if state.content.is_empty() {
        render_empty(frame, area);
        return;
    }

    // Calculate visible range
    let visible_height = area.height.saturating_sub(0) as usize;
    let total_lines = state.content.len();
    let start = state.scroll.min(total_lines.saturating_sub(visible_height));
    let end = (start + visible_height).min(total_lines);

    // Build styled lines with line numbers and syntax highlighting
    let lines: Vec<Line> = state.content[start..end]
        .iter()
        .enumerate()
        .map(|(i, line_content)| {
            let line_num = start + i + 1;
            let line_num_span = Span::styled(
                format!("{:5} │ ", line_num),
                Style::default().fg(Color::DarkGray),
            );

            // Apply syntax highlighting based on file type
            let content_spans = highlight_line(line_content, state.file_type);

            let mut spans = vec![line_num_span];
            spans.extend(content_spans);
            Line::from(spans)
        })
        .collect();

    let paragraph = Paragraph::new(lines)
        .style(Style::default().fg(Color::White))
        .wrap(Wrap { trim: false });

    frame.render_widget(paragraph, area);

    // Render scroll indicator on the right side
    if total_lines > visible_height {
        render_scroll_indicator(frame, area, start, total_lines, visible_height);
    }
}

/// Render loading state with pulsing animation.
fn render_loading(frame: &mut Frame, area: Rect) {
    let dots = match (std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis()
        / 500)
        % 4
    {
        0 => "",
        1 => ".",
        2 => "..",
        _ => "...",
    };

    let lines = vec![
        Line::from(""),
        Line::from(""),
        Line::from(vec![Span::styled(
            format!("Loading output file{}", dots),
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )]),
        Line::from(""),
        Line::from(Span::styled(
            "This may take a moment for large files...",
            Style::default().fg(Color::DarkGray),
        )),
    ];

    let paragraph = Paragraph::new(lines)
        .alignment(Alignment::Center)
        .style(Style::default());

    frame.render_widget(paragraph, area);
}

/// Render error state.
fn render_error(frame: &mut Frame, error: &str, area: Rect) {
    let lines = vec![
        Line::from(""),
        Line::from(vec![Span::styled(
            "⚠ Error Loading File",
            Style::default()
                .fg(Color::Red)
                .add_modifier(Modifier::BOLD),
        )]),
        Line::from(""),
        Line::from(Span::styled(error, Style::default().fg(Color::Red))),
        Line::from(""),
        Line::from(Span::styled(
            "Press Esc to close this modal",
            Style::default().fg(Color::DarkGray),
        )),
    ];

    let paragraph = Paragraph::new(lines)
        .alignment(Alignment::Center)
        .style(Style::default());

    frame.render_widget(paragraph, area);
}

/// Render empty state.
fn render_empty(frame: &mut Frame, area: Rect) {
    let lines = vec![
        Line::from(""),
        Line::from(vec![Span::styled(
            "No content available",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )]),
        Line::from(""),
        Line::from(Span::styled(
            "The output file may not exist yet or is empty.",
            Style::default().fg(Color::DarkGray),
        )),
    ];

    let paragraph = Paragraph::new(lines)
        .alignment(Alignment::Center)
        .style(Style::default());

    frame.render_widget(paragraph, area);
}

/// Apply syntax highlighting to a line based on file type.
fn highlight_line(line: &str, file_type: OutputFileType) -> Vec<Span<'static>> {
    let keywords: &[&str] = match file_type {
        OutputFileType::Outcar | OutputFileType::VasprunXml | OutputFileType::Oszicar => {
            VASP_KEYWORDS
        }
        OutputFileType::CrystalOut => CRYSTAL_KEYWORDS,
        OutputFileType::GenericLog => &[],
    };

    // Simple highlighting: check if line contains any keyword
    let line_upper = line.to_uppercase();
    
    // Check for special patterns
    if line_upper.contains("ERROR") || line_upper.contains("FAILED") {
        return vec![Span::styled(
            line.to_string(),
            Style::default().fg(Color::Red),
        )];
    }
    
    if line_upper.contains("WARNING") || line_upper.contains("CAUTION") {
        return vec![Span::styled(
            line.to_string(),
            Style::default().fg(Color::Yellow),
        )];
    }
    
    if line_upper.contains("CONVERGED") || line_upper.contains("REACHED REQUIRED") {
        return vec![Span::styled(
            line.to_string(),
            Style::default().fg(Color::Green),
        )];
    }

    // Check for energy lines (common pattern)
    if line_upper.contains("TOTEN") || line_upper.contains("TOTAL ENERGY") {
        return vec![Span::styled(
            line.to_string(),
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
        )];
    }

    // Check for iteration/cycle lines
    if line_upper.contains("ITERATION") || line_upper.contains("CYCLE") || line_upper.contains("LOOP") {
        return vec![Span::styled(
            line.to_string(),
            Style::default().fg(Color::Blue),
        )];
    }

    // Check for any keyword match
    for keyword in keywords {
        if line_upper.contains(&(*keyword).to_uppercase().as_str()) {
            return vec![Span::styled(
                line.to_string(),
                Style::default().fg(Color::Cyan),
            )];
        }
    }

    // Default: no highlighting
    vec![Span::raw(line.to_string())]
}

/// Render scroll indicator on the right edge.
fn render_scroll_indicator(
    frame: &mut Frame,
    area: Rect,
    scroll_offset: usize,
    total_lines: usize,
    visible_height: usize,
) {
    let max_scroll = total_lines.saturating_sub(visible_height);
    let scroll_pct = if max_scroll > 0 {
        (scroll_offset * 100) / max_scroll
    } else {
        100
    };

    // Calculate scrollbar position
    let scrollbar_height = area.height.saturating_sub(2) as usize;
    if scrollbar_height == 0 {
        return;
    }

    let thumb_pos = (scroll_pct * scrollbar_height) / 100;
    let thumb_pos = thumb_pos.min(scrollbar_height.saturating_sub(1));

    // Draw scrollbar track and thumb
    for i in 0..scrollbar_height {
        let ch = if i == thumb_pos { "█" } else { "░" };
        let style = if i == thumb_pos {
            Style::default().fg(Color::Cyan)
        } else {
            Style::default().fg(Color::DarkGray)
        };

        let x = area.x + area.width.saturating_sub(1);
        let y = area.y + 1 + i as u16;

        if y < area.y + area.height - 1 {
            frame.buffer_mut().set_string(x, y, ch, style);
        }
    }
}

/// Render the status bar with keybindings and position info.
fn render_status_bar(frame: &mut Frame, state: &OutputViewerState, area: Rect) {
    let total_lines = state.content.len();
    let visible_height = 20; // Approximate
    let current_line = state.scroll + 1;

    // Position indicator
    let position = if total_lines > 0 {
        format!(" {}/{} ", current_line, total_lines)
    } else {
        " - ".to_string()
    };

    // Scroll percentage
    let scroll_pct = if total_lines > visible_height {
        let max_scroll = total_lines.saturating_sub(visible_height);
        if max_scroll > 0 {
            (state.scroll * 100) / max_scroll
        } else {
            100
        }
    } else {
        100
    };

    let pct_str = format!(" {}% ", scroll_pct.min(100));

    // Keybindings
    let hints = vec![
        ("j/k", "scroll"),
        ("PgUp/PgDn", "page"),
        ("g/G", "top/bottom"),
        ("Esc", "close"),
    ];

    let mut spans: Vec<Span> = Vec::new();
    
    // Position info on the left
    spans.push(Span::styled(
        position,
        Style::default().fg(Color::Cyan),
    ));
    spans.push(Span::raw(" │ "));

    // Keybindings
    for (i, (key, action)) in hints.iter().enumerate() {
        if i > 0 {
            spans.push(Span::raw("  "));
        }
        spans.push(Span::styled(
            *key,
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        ));
        spans.push(Span::styled(
            format!(":{}", action),
            Style::default().fg(Color::Gray),
        ));
    }

    // Percentage on the right
    spans.push(Span::raw(" │ "));
    spans.push(Span::styled(pct_str, Style::default().fg(Color::DarkGray)));

    let line = Line::from(spans);
    let paragraph = Paragraph::new(line)
        .style(Style::default())
        .alignment(Alignment::Center);

    frame.render_widget(paragraph, area);
}

/// Helper for fixed-size centered rect.
fn centered_rect_fixed(width: u16, height: u16, area: Rect) -> Rect {
    let x = area.x + (area.width.saturating_sub(width)) / 2;
    let y = area.y + (area.height.saturating_sub(height)) / 2;
    Rect::new(x, y, width.min(area.width), height.min(area.height))
}
