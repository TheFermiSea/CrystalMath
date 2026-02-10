//! Template Browser modal for calculation templates.
//!
//! This modal displays a list of available CRYSTAL23/VASP templates
//! from the backend, allowing users to select one for input generation.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Clear, List, ListItem, Paragraph, Wrap};

use crate::app::App;

/// Render the template browser modal overlay.
pub fn render(frame: &mut Frame, app: &App) {
    let area = frame.area();

    // Dim the background
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    // Center the modal (80% width, 80% height)
    let modal_area = centered_rect(80, 80, area);

    // Clear the background
    frame.render_widget(Clear, modal_area);

    // Modal border
    let border_style = if app.template_browser.error.is_some() {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Cyan)
    };

    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(" Calculation Templates ")
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(modal_block, modal_area);

    // Layout: List (left) | Details (right)
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Min(5),    // Main content
            Constraint::Length(3), // Buttons
        ])
        .split(modal_area);

    let main_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(40), // Template list
            Constraint::Percentage(60), // Details
        ])
        .split(chunks[0]);

    // Render Template List
    render_template_list(frame, app, main_chunks[0]);

    // Render Details
    render_template_details(frame, app, main_chunks[1]);

    // Render Buttons
    render_buttons(frame, chunks[1]);
}

/// Render the list of available templates.
fn render_template_list(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.template_browser;

    if state.loading {
        let loading = Paragraph::new("Loading templates...")
            .style(Style::default().fg(Color::Yellow))
            .alignment(Alignment::Center);
        frame.render_widget(loading, area);
        return;
    }

    if state.templates.is_empty() {
        let empty = Paragraph::new("No templates found.")
            .style(Style::default().fg(Color::DarkGray))
            .alignment(Alignment::Center);
        frame.render_widget(empty, area);
        return;
    }

    let items: Vec<ListItem> = state
        .templates
        .iter()
        .enumerate()
        .map(|(idx, template)| {
            let is_selected = state.selected_index == Some(idx);
            let style = if is_selected {
                Style::default().bg(Color::DarkGray).fg(Color::White)
            } else {
                Style::default().fg(Color::White)
            };

            ListItem::new(format!(" {} ", template.name)).style(style)
        })
        .collect();

    let list = List::new(items).block(Block::default().borders(Borders::ALL).title(" Templates "));
    frame.render_widget(list, area);
}

/// Render details for the selected template.
fn render_template_details(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.template_browser;

    let content = if let Some(template) = state.selected_template() {
        let mut lines = vec![
            Line::from(vec![
                Span::styled("Name: ", Style::default().fg(Color::Cyan)),
                Span::raw(&template.name),
            ]),
            Line::from(vec![
                Span::styled("Version: ", Style::default().fg(Color::Cyan)),
                Span::raw(&template.version),
            ]),
            Line::from(vec![
                Span::styled("Author: ", Style::default().fg(Color::Cyan)),
                Span::raw(&template.author),
            ]),
            Line::from(""),
            Line::from(Span::styled(
                "Description:",
                Style::default().add_modifier(Modifier::BOLD),
            )),
            Line::from(template.description.clone()),
            Line::from(""),
            Line::from(Span::styled(
                "Tags:",
                Style::default().add_modifier(Modifier::BOLD),
            )),
            Line::from(template.tags.join(", ")),
            Line::from(""),
            Line::from(Span::styled(
                "Parameters:",
                Style::default().add_modifier(Modifier::BOLD),
            )),
        ];

        for (name, param) in &template.parameters {
            lines.push(Line::from(vec![
                Span::raw(" - "),
                Span::styled(format!("{}: ", name), Style::default().fg(Color::Yellow)),
                Span::raw(&param.description),
            ]));
        }

        lines
    } else {
        vec![Line::from("Select a template to view details")]
    };

    let paragraph = Paragraph::new(content)
        .block(Block::default().borders(Borders::ALL).title(" Details "))
        .wrap(Wrap { trim: false });
    frame.render_widget(paragraph, area);
}

/// Render action buttons.
fn render_buttons(frame: &mut Frame, area: Rect) {
    let buttons = Line::from(vec![
        Span::styled(
            " [Enter] ",
            Style::default()
                .fg(Color::Green)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Select", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(" [Esc] ", Style::default().fg(Color::Yellow)),
        Span::styled("Cancel", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(" [j/k] ", Style::default().fg(Color::Cyan)),
        Span::styled("Navigate", Style::default().fg(Color::White)),
    ]);

    let paragraph = Paragraph::new(buttons).alignment(Alignment::Center);
    frame.render_widget(paragraph, area);
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
