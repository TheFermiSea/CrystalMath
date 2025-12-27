//! Footer bar with keybindings.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Paragraph};

use crate::app::{App, AppTab};

pub fn render(frame: &mut Frame, app: &App, area: Rect) {
    let keybindings = match app.current_tab {
        AppTab::Jobs => {
            vec![
                ("j/k", "Select"),
                ("Enter", "Details"),
                ("Tab", "Next Tab"),
                ("Ctrl+R", "Refresh"),
                ("Ctrl+Q", "Quit"),
            ]
        }
        AppTab::Editor => {
            vec![
                ("Type", "Edit"),
                ("Tab", "Next Tab"),
                ("Ctrl+S", "Save"),
                ("Ctrl+Q", "Quit"),
            ]
        }
        AppTab::Results => {
            vec![
                ("j/k", "Scroll"),
                ("PgUp/Dn", "Page"),
                ("Tab", "Next Tab"),
                ("Ctrl+Q", "Quit"),
            ]
        }
        AppTab::Log => {
            vec![
                ("j/k", "Scroll"),
                ("Home/End", "Top/Bottom"),
                ("Tab", "Next Tab"),
                ("Ctrl+Q", "Quit"),
            ]
        }
    };

    let spans: Vec<Span> = keybindings
        .iter()
        .flat_map(|(key, action)| {
            vec![
                Span::styled(
                    format!(" {} ", key),
                    Style::default().bg(Color::DarkGray).fg(Color::White),
                ),
                Span::raw(format!(" {} ", action)),
                Span::raw(" "),
            ]
        })
        .collect();

    let paragraph = Paragraph::new(Line::from(spans))
        .block(Block::default().borders(Borders::ALL))
        .alignment(Alignment::Left);

    frame.render_widget(paragraph, area);
}
