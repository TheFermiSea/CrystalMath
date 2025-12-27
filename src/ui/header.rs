//! Header bar with tab navigation.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Tabs};

use crate::app::{App, AppTab};

pub fn render(frame: &mut Frame, app: &App, area: Rect) {
    let tab_titles: Vec<Line> = AppTab::all()
        .iter()
        .enumerate()
        .map(|(i, tab)| {
            let num = i + 1;
            let style = if *tab == app.current_tab {
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::DarkGray)
            };
            Line::from(format!(" {} {} ", num, tab.name())).style(style)
        })
        .collect();

    let selected = AppTab::all()
        .iter()
        .position(|t| *t == app.current_tab)
        .unwrap_or(0);

    let tabs = Tabs::new(tab_titles)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(" CrystalMath TUI ")
                .title_style(Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)),
        )
        .select(selected)
        .style(Style::default().fg(Color::White))
        .highlight_style(Style::default().fg(Color::Yellow))
        .divider(symbols::line::VERTICAL);

    frame.render_widget(tabs, area);
}
