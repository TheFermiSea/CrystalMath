//! Materials Project search modal overlay.
//!
//! Renders a centered modal with:
//! - Search input field
//! - Results table with material properties
//! - Status/error messages
//! - Loading indicator

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Cell, Clear, Paragraph, Row, Table, TableState, Wrap};

use crate::app::{App, MaterialsSearchState};

/// Render the materials search modal overlay.
///
/// This is called on top of the regular content when the modal is active.
/// The modal is centered and uses Clear to provide a proper background.
pub fn render(frame: &mut Frame, app: &App) {
    if !app.materials.active {
        return;
    }

    // Calculate modal size - 80% of screen width, up to 100 chars, min 60
    let area = frame.area();
    let modal_width = (area.width * 80 / 100).clamp(60, 100);
    let modal_height = (area.height * 70 / 100).clamp(20, 35);

    // Dim the background
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    // Center the modal
    let modal_area = centered_rect(modal_width, modal_height, area);

    // Clear the background for the modal
    frame.render_widget(Clear, modal_area);

    // Main modal block
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan))
        .title(" Import from Materials Project ")
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );

    let inner_area = block.inner(modal_area);
    frame.render_widget(block, modal_area);

    // Layout: Search row, Status, Results table, Button hints
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Search input
            Constraint::Length(2), // Status message
            Constraint::Min(5),    // Results table
            Constraint::Length(2), // Button hints
        ])
        .split(inner_area);

    render_search_input(frame, &app.materials, chunks[0]);
    render_status(frame, &app.materials, chunks[1]);
    render_results_table(frame, &app.materials, chunks[2]);
    render_button_hints(frame, &app.materials, chunks[3]);
}

/// Render the search input field.
fn render_search_input(frame: &mut Frame, state: &MaterialsSearchState, area: Rect) {
    let query = state.query();
    let is_empty = query.is_empty();

    let (display_text, style) = if is_empty {
        (
            "Enter formula (e.g., MoS2, Si, LiFePO4)".to_string(),
            Style::default().fg(Color::DarkGray),
        )
    } else {
        (query, Style::default().fg(Color::White))
    };

    let input = Paragraph::new(display_text).style(style).block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(Style::default().fg(Color::Yellow))
            .title(" Formula ")
            .title_style(Style::default().fg(Color::Yellow)),
    );

    frame.render_widget(input, area);

    // Show cursor position at end of query
    if !state.loading {
        let cursor_x = area.x + 1 + state.query().len() as u16;
        let cursor_y = area.y + 1;
        if cursor_x < area.x + area.width - 1 {
            frame.set_cursor_position(Position::new(cursor_x, cursor_y));
        }
    }
}

/// Render the status message.
fn render_status(frame: &mut Frame, state: &MaterialsSearchState, area: Rect) {
    let (message, style) = if state.loading {
        // Show loading indicator
        let spinner = ['◐', '◓', '◑', '◒'];
        let idx = (std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis()
            / 200) as usize
            % spinner.len();
        (
            format!(" {} Loading...", spinner[idx]),
            Style::default().fg(Color::Yellow),
        )
    } else if let Some(ref msg) = state.status {
        let color = if state.status_is_error {
            Color::Red
        } else {
            Color::Green
        };
        (format!(" {}", msg), Style::default().fg(color))
    } else {
        (" ".to_string(), Style::default())
    };

    let para = Paragraph::new(message).style(style);
    frame.render_widget(para, area);
}

/// Render the results table.
fn render_results_table(frame: &mut Frame, state: &MaterialsSearchState, area: Rect) {
    if state.results.is_empty() {
        // Empty state
        let msg = if state.loading {
            "Searching..."
        } else {
            "No results. Enter a formula and press Enter to search."
        };

        let paragraph = Paragraph::new(msg)
            .style(Style::default().fg(Color::DarkGray))
            .alignment(Alignment::Center)
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(Color::DarkGray))
                    .title(" Results ")
                    .title_style(Style::default().fg(Color::DarkGray)),
            )
            .wrap(Wrap { trim: true });

        frame.render_widget(paragraph, area);
        return;
    }

    // Table header
    let header = Row::new(vec![
        Cell::from("ID").style(Style::default().fg(Color::Yellow)),
        Cell::from("Formula").style(Style::default().fg(Color::Yellow)),
        Cell::from("Space Group").style(Style::default().fg(Color::Yellow)),
        Cell::from("Band Gap").style(Style::default().fg(Color::Yellow)),
        Cell::from("Stability").style(Style::default().fg(Color::Yellow)),
    ])
    .height(1)
    .bottom_margin(1);

    // Table rows from results
    let rows: Vec<Row> = state
        .results
        .iter()
        .map(|record| {
            // Use MaterialResult methods for consistent display
            let stability = record.stability_display();
            let stability_style = if record.is_stable() {
                Style::default().fg(Color::Green)
            } else if stability != "-" {
                Style::default().fg(Color::Yellow)
            } else {
                Style::default()
            };

            Row::new(vec![
                Cell::from(record.material_id.clone()),
                Cell::from(record.display_formula().to_string()),
                Cell::from(record.space_group()),
                Cell::from(record.band_gap_display()),
                Cell::from(stability).style(stability_style),
            ])
        })
        .collect();

    // Column widths
    let widths = [
        Constraint::Length(14), // ID (mp-12345)
        Constraint::Min(12),    // Formula
        Constraint::Length(14), // Space Group
        Constraint::Length(12), // Band Gap
        Constraint::Length(12), // Stability
    ];

    let table = Table::new(rows, widths)
        .header(header)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(Style::default().fg(Color::Blue))
                .title(format!(" Results ({}) ", state.results.len()))
                .title_style(Style::default().fg(Color::Blue)),
        )
        .row_highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    // Render with state for selection
    let mut table_state = TableState::default();
    table_state.select(state.table_state.selected());

    frame.render_stateful_widget(table, area, &mut table_state);
}

/// Render keyboard shortcuts / button hints.
fn render_button_hints(frame: &mut Frame, state: &MaterialsSearchState, area: Rect) {
    let hints = if state.loading {
        vec![
            Span::styled(
                " Esc ",
                Style::default().bg(Color::DarkGray).fg(Color::White),
            ),
            Span::raw(" Cancel "),
        ]
    } else if state.results.is_empty() {
        vec![
            Span::styled(
                " Enter ",
                Style::default().bg(Color::Green).fg(Color::Black),
            ),
            Span::raw(" Search  "),
            Span::styled(
                " Esc ",
                Style::default().bg(Color::DarkGray).fg(Color::White),
            ),
            Span::raw(" Close "),
        ]
    } else {
        vec![
            Span::styled(
                " Enter ",
                Style::default().bg(Color::Green).fg(Color::Black),
            ),
            Span::raw(" Import  "),
            Span::styled(" ↑↓ ", Style::default().bg(Color::Blue).fg(Color::White)),
            Span::raw(" Navigate  "),
            Span::styled(
                " Esc ",
                Style::default().bg(Color::DarkGray).fg(Color::White),
            ),
            Span::raw(" Close "),
        ]
    };

    let hints_line = Line::from(hints);
    let para = Paragraph::new(hints_line).alignment(Alignment::Center);
    frame.render_widget(para, area);
}

/// Create a centered rect with given width and height.
fn centered_rect(width: u16, height: u16, area: Rect) -> Rect {
    let x = area.x + (area.width.saturating_sub(width)) / 2;
    let y = area.y + (area.height.saturating_sub(height)) / 2;
    Rect::new(x, y, width.min(area.width), height.min(area.height))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_centered_rect() {
        let area = Rect::new(0, 0, 100, 50);
        let modal = centered_rect(60, 30, area);

        assert_eq!(modal.x, 20);
        assert_eq!(modal.y, 10);
        assert_eq!(modal.width, 60);
        assert_eq!(modal.height, 30);
    }

    #[test]
    fn test_centered_rect_clamps_to_area() {
        let area = Rect::new(0, 0, 50, 20);
        let modal = centered_rect(100, 40, area);

        // Should clamp to available size
        assert_eq!(modal.width, 50);
        assert_eq!(modal.height, 20);
    }
}
