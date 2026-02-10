//! Help modal rendering.
//!
//! This module renders the hierarchical help modal with a two-pane layout:
//! sidebar for topics and main area for content.

use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    prelude::*,
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Clear, List, ListItem, ListState, Paragraph, Wrap},
    Frame,
};

use crate::state::help::{HelpPaneFocus, HelpState};

use super::help_content;

/// Render the help modal.
pub fn render(frame: &mut Frame, help: &HelpState) {
    let area = frame.area();

    // Modal size: 85% width, 80% height, centered
    let modal_width = (area.width * 85 / 100).clamp(60, 120);
    let modal_height = (area.height * 80 / 100).clamp(20, 40);
    let modal_area = centered_rect_fixed(modal_width, modal_height, area);

    // Clear the area behind the modal
    frame.render_widget(Clear, modal_area);

    // Outer block with title
    let outer_block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan))
        .title(" Help ")
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );

    let inner_area = outer_block.inner(modal_area);
    frame.render_widget(outer_block, modal_area);

    // Layout: breadcrumb (top), main content (middle), keybindings (bottom)
    let layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // Breadcrumb
            Constraint::Min(0),    // Main content
            Constraint::Length(2), // Keybindings
        ])
        .split(inner_area);

    // Render breadcrumb
    render_breadcrumb(frame, help, layout[0]);

    // Render main content (two-pane layout)
    render_main_content(frame, help, layout[1]);

    // Render key hints
    render_keybindings(frame, help, layout[2]);
}

/// Render the breadcrumb navigation.
fn render_breadcrumb(frame: &mut Frame, help: &HelpState, area: Rect) {
    let crumbs = help.breadcrumb();
    let mut spans: Vec<Span> = Vec::new();

    for (i, crumb) in crumbs.iter().enumerate() {
        if i > 0 {
            spans.push(Span::styled(" > ", Style::default().fg(Color::DarkGray)));
        }
        let style = if i == crumbs.len() - 1 {
            // Current level is highlighted
            Style::default().fg(Color::Yellow)
        } else {
            Style::default().fg(Color::Gray)
        };
        spans.push(Span::styled(*crumb, style));
    }

    let line = Line::from(spans);
    let paragraph = Paragraph::new(line);
    frame.render_widget(paragraph, area);
}

/// Render the main two-pane content area.
fn render_main_content(frame: &mut Frame, help: &HelpState, area: Rect) {
    // Two-pane layout: sidebar (left) and content (right)
    let panes = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(30), // Sidebar
            Constraint::Percentage(70), // Content
        ])
        .split(area);

    render_sidebar(frame, help, panes[0]);
    render_content_pane(frame, help, panes[1]);
}

/// Render the sidebar with topic list.
fn render_sidebar(frame: &mut Frame, help: &HelpState, area: Rect) {
    let is_focused = help.focus == HelpPaneFocus::Sidebar;

    let border_style = if is_focused {
        Style::default().fg(Color::Cyan)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(" Topics ")
        .title_style(if is_focused {
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::DarkGray)
        });

    let inner_area = block.inner(area);
    frame.render_widget(block, area);

    // Build list items from visible topics
    let items: Vec<ListItem> = help
        .visible_topics()
        .iter()
        .enumerate()
        .map(|(i, topic)| {
            let has_children = !topic.children().is_empty();
            let marker = if has_children { " >" } else { "" };
            let content = format!("{}{}", topic.title(), marker);

            let style = if i == help.selected_index && is_focused {
                Style::default()
                    .fg(Color::Black)
                    .bg(Color::Cyan)
                    .add_modifier(Modifier::BOLD)
            } else if i == help.selected_index {
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::White)
            };

            ListItem::new(Line::from(Span::styled(content, style)))
        })
        .collect();

    let list = List::new(items);

    // Create ListState for scrolling
    let mut list_state = ListState::default();
    list_state.select(Some(help.selected_index));

    frame.render_stateful_widget(list, inner_area, &mut list_state);
}

/// Render the content pane with help text.
fn render_content_pane(frame: &mut Frame, help: &HelpState, area: Rect) {
    let is_focused = help.focus == HelpPaneFocus::Content;

    let border_style = if is_focused {
        Style::default().fg(Color::Cyan)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    // Get the selected topic's title for the content pane title
    let title = help
        .selected_topic()
        .map(|t| t.title())
        .unwrap_or("Content");

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(format!(" {} ", title))
        .title_style(if is_focused {
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::DarkGray)
        });

    let inner_area = block.inner(area);
    frame.render_widget(block, area);

    // Get content for selected topic
    let content = help
        .selected_topic()
        .map(help_content::get_content)
        .unwrap_or("Select a topic from the sidebar.");

    // Apply scroll offset
    let lines: Vec<&str> = content.lines().collect();
    let scroll_offset = help.content_scroll.min(lines.len().saturating_sub(1));

    let visible_content: String = lines
        .iter()
        .skip(scroll_offset)
        .take(inner_area.height as usize)
        .cloned()
        .collect::<Vec<_>>()
        .join("\n");

    let paragraph = Paragraph::new(visible_content)
        .style(Style::default().fg(Color::White))
        .wrap(Wrap { trim: false });

    frame.render_widget(paragraph, inner_area);

    // Show scroll indicator if content is scrollable
    let total_lines = lines.len();
    let visible_lines = inner_area.height as usize;
    if total_lines > visible_lines {
        let scroll_pct = if total_lines > visible_lines {
            (scroll_offset * 100) / (total_lines - visible_lines).max(1)
        } else {
            0
        };
        let indicator = format!(" {}% ", scroll_pct.min(100));
        let indicator_span = Span::styled(indicator, Style::default().fg(Color::DarkGray));

        // Position at bottom-right of content area
        let indicator_area = Rect {
            x: area.x + area.width - 8,
            y: area.y + area.height - 1,
            width: 7,
            height: 1,
        };
        frame.render_widget(Paragraph::new(Line::from(indicator_span)), indicator_area);
    }
}

/// Render the keybindings hint at the bottom.
fn render_keybindings(frame: &mut Frame, help: &HelpState, area: Rect) {
    let hints = match help.focus {
        HelpPaneFocus::Sidebar => vec![
            ("j/k", "navigate"),
            ("Enter/l", "drill in"),
            ("h/Backspace", "go back"),
            ("Tab", "content"),
            ("?/Esc", "close"),
        ],
        HelpPaneFocus::Content => vec![
            ("j/k", "scroll"),
            ("PgUp/PgDn", "page"),
            ("Tab", "sidebar"),
            ("h/Backspace", "go back"),
            ("?/Esc", "close"),
        ],
    };

    let mut spans: Vec<Span> = Vec::new();
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

    let line = Line::from(spans);
    let paragraph = Paragraph::new(line).alignment(Alignment::Center);
    frame.render_widget(paragraph, area);
}

/// Helper for fixed-size centered rect.
fn centered_rect_fixed(width: u16, height: u16, area: Rect) -> Rect {
    let x = area.x + (area.width.saturating_sub(width)) / 2;
    let y = area.y + (area.height.saturating_sub(height)) / 2;
    Rect::new(x, y, width.min(area.width), height.min(area.height))
}
