//! Job results view.

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Paragraph, Wrap};

use crate::app::App;

pub fn render(frame: &mut Frame, app: &App, area: Rect) {
    let content = match &app.current_job_details {
        Some(details) => {
            let mut lines = vec![
                Line::from(vec![
                    Span::styled("Job: ", Style::default().fg(Color::Yellow)),
                    Span::raw(&details.name),
                ]),
                Line::from(vec![
                    Span::styled("Status: ", Style::default().fg(Color::Yellow)),
                    Span::styled(
                        details.state.as_str(),
                        Style::default().fg(details.state.color()),
                    ),
                ]),
                Line::from(""),
                Line::styled(
                    "=== Results ===",
                    Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
                ),
                Line::from(vec![
                    Span::styled("Final Energy: ", Style::default().fg(Color::Yellow)),
                    Span::raw(details.energy_display()),
                ]),
                Line::from(vec![
                    Span::styled("Band Gap: ", Style::default().fg(Color::Yellow)),
                    Span::raw(details.bandgap_display()),
                ]),
                Line::from(vec![
                    Span::styled("Convergence: ", Style::default().fg(Color::Yellow)),
                    Span::styled(
                        if details.convergence_met { "Yes" } else { "No" },
                        Style::default().fg(if details.convergence_met {
                            Color::Green
                        } else {
                            Color::Red
                        }),
                    ),
                ]),
            ];

            if let Some(cycles) = details.scf_cycles {
                lines.push(Line::from(vec![
                    Span::styled("SCF Cycles: ", Style::default().fg(Color::Yellow)),
                    Span::raw(cycles.to_string()),
                ]));
            }

            if let Some(wall) = details.wall_time_seconds {
                lines.push(Line::from(vec![
                    Span::styled("Wall Time: ", Style::default().fg(Color::Yellow)),
                    Span::raw(format!("{:.1}s", wall)),
                ]));
            }

            // Warnings
            if !details.warnings.is_empty() {
                lines.push(Line::from(""));
                lines.push(Line::styled(
                    "=== Warnings ===",
                    Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
                ));
                for warning in &details.warnings {
                    lines.push(Line::from(vec![
                        Span::styled("! ", Style::default().fg(Color::Yellow)),
                        Span::raw(warning.as_str()),
                    ]));
                }
            }

            // Errors
            if !details.errors.is_empty() {
                lines.push(Line::from(""));
                lines.push(Line::styled(
                    "=== Errors ===",
                    Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
                ));
                for error in &details.errors {
                    lines.push(Line::from(vec![
                        Span::styled("X ", Style::default().fg(Color::Red)),
                        Span::raw(error.as_str()),
                    ]));
                }
            }

            Text::from(lines)
        }
        None => Text::from("Select a job to view details..."),
    };

    let paragraph = Paragraph::new(content)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Results ")
                .title_style(Style::default().fg(Color::Cyan)),
        )
        .wrap(Wrap { trim: true })
        .scroll((app.results_scroll as u16, 0));

    frame.render_widget(paragraph, area);
}
