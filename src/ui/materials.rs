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

    // Layout: Search row, Status, Results + Preview, Button hints
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Search input
            Constraint::Length(2), // Status message
            Constraint::Min(5),    // Results + Preview
            Constraint::Length(2), // Button hints
        ])
        .split(inner_area);

    render_search_input(frame, &app.materials, chunks[0]);
    render_status(frame, &app.materials, chunks[1]);

    // Split the middle area into results table and preview panel
    let content_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(60), // Results table
            Constraint::Percentage(40), // Preview panel
        ])
        .split(chunks[2]);

    render_results_table(frame, &app.materials, content_chunks[0]);
    render_preview_panel(frame, &app.materials, content_chunks[1]);

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

/// Render the structure preview panel.
fn render_preview_panel(frame: &mut Frame, state: &MaterialsSearchState, area: Rect) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Magenta))
        .title(" Structure Preview ")
        .title_style(Style::default().fg(Color::Magenta));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    // Check if we have a selection
    if state.table_state.selected().is_none() {
        let msg = Paragraph::new("Select a structure to preview")
            .style(Style::default().fg(Color::DarkGray))
            .alignment(Alignment::Center)
            .wrap(Wrap { trim: true });
        frame.render_widget(msg, inner);
        return;
    }

    // Check if loading
    if state.preview_loading {
        let spinner = ['◐', '◓', '◑', '◒'];
        let idx = (std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis()
            / 200) as usize
            % spinner.len();
        let msg = Paragraph::new(format!("{} Loading preview...", spinner[idx]))
            .style(Style::default().fg(Color::Yellow))
            .alignment(Alignment::Center);
        frame.render_widget(msg, inner);
        return;
    }

    // Check if we have preview data
    let Some(preview) = &state.preview else {
        // Selection but no preview yet - show waiting state
        let msg = Paragraph::new("Fetching structure info...")
            .style(Style::default().fg(Color::DarkGray))
            .alignment(Alignment::Center);
        frame.render_widget(msg, inner);
        return;
    };

    // Build preview lines
    let mut lines = vec![
        Line::from(vec![
            Span::styled(
                &preview.formula,
                Style::default()
                    .fg(Color::White)
                    .add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(""),
    ];

    // Space group
    if let Some(ref sym) = preview.symmetry {
        if let Some(ref sg) = sym.space_group {
            lines.push(Line::from(vec![
                Span::styled("Space Group: ", Style::default().fg(Color::DarkGray)),
                Span::styled(sg.as_str(), Style::default().fg(Color::Cyan)),
            ]));
        }
        if let Some(ref cs) = sym.crystal_system {
            lines.push(Line::from(vec![
                Span::styled("System: ", Style::default().fg(Color::DarkGray)),
                Span::styled(cs.as_str(), Style::default().fg(Color::White)),
            ]));
        }
    }

    lines.push(Line::from(""));

    // Lattice parameters
    lines.push(Line::from(vec![
        Span::styled("Lattice (Å):", Style::default().fg(Color::DarkGray)),
    ]));
    lines.push(Line::from(vec![
        Span::styled(" a=", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{:.3}", preview.lattice.a),
            Style::default().fg(Color::White),
        ),
        Span::styled(" b=", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{:.3}", preview.lattice.b),
            Style::default().fg(Color::White),
        ),
        Span::styled(" c=", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{:.3}", preview.lattice.c),
            Style::default().fg(Color::White),
        ),
    ]));
    lines.push(Line::from(vec![
        Span::styled(" α=", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{:.1}°", preview.lattice.alpha),
            Style::default().fg(Color::White),
        ),
        Span::styled(" β=", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{:.1}°", preview.lattice.beta),
            Style::default().fg(Color::White),
        ),
        Span::styled(" γ=", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{:.1}°", preview.lattice.gamma),
            Style::default().fg(Color::White),
        ),
    ]));

    lines.push(Line::from(""));

    // Volume and atoms
    lines.push(Line::from(vec![
        Span::styled("Volume: ", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{:.2} Å³", preview.volume),
            Style::default().fg(Color::White),
        ),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Atoms: ", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{}", preview.num_sites),
            Style::default().fg(Color::Green),
        ),
    ]));

    // Elements
    if !preview.species.is_empty() {
        lines.push(Line::from(vec![
            Span::styled("Elements: ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                preview.species.join(", "),
                Style::default().fg(Color::Yellow),
            ),
        ]));
    }

    // VASP config section
    lines.push(Line::from(""));
    lines.push(Line::from(vec![
        Span::styled("─── VASP Config ───", Style::default().fg(Color::DarkGray)),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Preset [p]: ", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{}", state.vasp_config.preset),
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
        ),
    ]));
    lines.push(Line::from(vec![
        Span::styled("K-pts [k]: ", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{} KPPRA", state.vasp_config.kppra),
            Style::default().fg(Color::Cyan),
        ),
    ]));

    let para = Paragraph::new(lines).wrap(Wrap { trim: true });
    frame.render_widget(para, inner);
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
            Span::raw(" D12 "),
            Span::styled(" v ", Style::default().bg(Color::Cyan).fg(Color::Black)),
            Span::raw(" VASP "),
            Span::styled(" p ", Style::default().bg(Color::Magenta).fg(Color::White)),
            Span::raw(" Preset "),
            Span::styled(" K ", Style::default().bg(Color::Magenta).fg(Color::White)),
            Span::raw(" K-pts "),
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
