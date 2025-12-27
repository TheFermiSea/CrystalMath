//! Log viewer.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Paragraph};

use crate::app::App;

/// Calculate the maximum scroll offset to prevent overscroll.
/// Returns the maximum valid scroll position given total lines and visible height.
pub fn max_scroll(total_lines: usize, visible_height: usize) -> usize {
    total_lines.saturating_sub(visible_height)
}

pub fn render(frame: &mut Frame, app: &App, area: Rect) {
    // Calculate visible height (area height minus 2 for borders)
    let visible_height = area.height.saturating_sub(2) as usize;

    let total_lines = app.log_lines.len();

    // Clamp scroll to prevent overscroll
    let clamped_scroll = app.log_scroll.min(max_scroll(total_lines, visible_height));

    let lines: Vec<Line> = if app.log_lines.is_empty() {
        vec![Line::from("No log output available...")]
    } else {
        // Only render lines visible in the viewport (virtualization)
        let start = clamped_scroll;
        let end = (clamped_scroll + visible_height).min(total_lines);

        app.log_lines[start..end]
            .iter()
            .enumerate()
            .map(|(i, line)| {
                // Line number is relative to the full log, not the viewport
                let line_num = format!("{:4} | ", start + i + 1);
                Line::from(vec![
                    Span::styled(line_num, Style::default().fg(Color::DarkGray)),
                    Span::raw(line.as_str()),
                ])
            })
            .collect()
    };

    let visible_start = clamped_scroll + 1;
    let title = format!(" Log ({}/{}) ", visible_start, total_lines.max(1));

    // No scroll offset needed since we're only rendering visible lines
    let paragraph = Paragraph::new(Text::from(lines)).block(
        Block::default()
            .borders(Borders::ALL)
            .title(title)
            .title_style(Style::default().fg(Color::Cyan)),
    );

    frame.render_widget(paragraph, area);
}
