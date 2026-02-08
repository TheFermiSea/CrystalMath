//! Recipe browser UI component.
//!
//! Displays available quacc VASP recipes from the recipes.list RPC call.
//! Shows recipe name, category, type (job/flow), and brief description.

use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap},
    Frame,
};
use tachyonfx::{fx, Effect, Motion};

use crate::models::{Recipe, WorkflowEngineStatus};

/// State for the recipe browser.
#[derive(Debug, Default)]
pub struct RecipeBrowserState {
    /// Currently selected recipe index.
    pub selected: usize,
    /// List widget state for scrolling.
    pub list_state: ListState,
    /// Loaded recipes (empty until fetched).
    pub recipes: Vec<Recipe>,
    /// Workflow engine status.
    pub engine_status: WorkflowEngineStatus,
    /// Error message if load failed.
    pub error: Option<String>,
    /// Whether data is currently loading.
    pub loading: bool,
    /// Whether the recipe browser modal is active.
    pub active: bool,

    /// Animation effect for open/close.
    pub effect: Option<Effect>,

    /// Whether the modal is closing.
    pub closing: bool,
}

impl RecipeBrowserState {
    /// Create a new recipe browser state.
    pub fn new() -> Self {
        Self::default()
    }

    /// Open the recipe browser modal.
    pub fn open(&mut self) {
        self.active = true;
        self.closing = false;
        self.loading = true; // Mark as loading to trigger fetch
        self.selected = 0;
        self.list_state.select(Some(0));
        self.error = None;
        // Slide in from bottom
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));
    }

    /// Close the recipe browser modal.
    pub fn close(&mut self) {
        self.closing = true;
        self.error = None;
        // Slide out to bottom
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
    }

    /// Select previous recipe.
    pub fn previous(&mut self) {
        if self.recipes.is_empty() {
            return;
        }
        self.selected = self.selected.saturating_sub(1);
        self.list_state.select(Some(self.selected));
    }

    /// Select next recipe.
    pub fn next(&mut self) {
        if self.recipes.is_empty() {
            return;
        }
        self.selected = (self.selected + 1).min(self.recipes.len().saturating_sub(1));
        self.list_state.select(Some(self.selected));
    }

    /// Get currently selected recipe.
    pub fn selected_recipe(&self) -> Option<&Recipe> {
        self.recipes.get(self.selected)
    }

    /// Update with loaded data.
    pub fn set_data(
        &mut self,
        recipes: Vec<Recipe>,
        engine_status: WorkflowEngineStatus,
        error: Option<String>,
    ) {
        self.recipes = recipes;
        self.engine_status = engine_status;
        self.error = error;
        self.loading = false;
        if !self.recipes.is_empty() {
            self.selected = 0;
            self.list_state.select(Some(0));
        }
    }
}

/// Render the recipe browser modal.
pub fn render(frame: &mut Frame, state: &mut RecipeBrowserState) {
    // Center the modal (80% of screen)
    let area = centered_rect(80, 80, frame.area());

    // Clear the area behind the modal
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        frame.area(),
    );

    // Layout: sidebar (recipe list) | main (recipe details)
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(40), Constraint::Percentage(60)])
        .split(area);

    render_recipe_list(frame, chunks[0], state);
    render_recipe_details(frame, chunks[1], state);
}

fn render_recipe_list(frame: &mut Frame, area: Rect, state: &mut RecipeBrowserState) {
    // Vertical layout: engine status bar | recipe list
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(0)])
        .split(area);

    // Engine status bar
    let engine_text = if state.engine_status.quacc_installed {
        format!(
            "Engine: {} | Installed: {}",
            state.engine_status.configured_display(),
            if state.engine_status.installed.is_empty() {
                "none".to_string()
            } else {
                state.engine_status.installed.join(", ")
            }
        )
    } else {
        "quacc not installed".to_string()
    };

    let engine_style = if state.engine_status.quacc_installed {
        Style::default().fg(Color::Green)
    } else {
        Style::default().fg(Color::Red)
    };

    let engine_block = Paragraph::new(engine_text).style(engine_style).block(
        Block::default()
            .borders(Borders::ALL)
            .title("Workflow Engine"),
    );
    frame.render_widget(engine_block, chunks[0]);

    // Recipe list
    if state.loading {
        // Pulsing border color when loading
        let colors = [Color::Yellow, Color::Cyan, Color::Green, Color::Magenta];
        let idx = (std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis()
            / 250) as usize
            % colors.len();
        let loading_color = colors[idx];

        let loading = Paragraph::new("Loading recipes...")
            .style(Style::default().fg(loading_color))
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(loading_color))
                    .title("Recipes"),
            );
        frame.render_widget(loading, chunks[1]);
        return;
    }

    if let Some(ref error) = state.error {
        let error_para = Paragraph::new(error.as_str())
            .style(Style::default().fg(Color::Red))
            .block(Block::default().borders(Borders::ALL).title("Recipes"));
        frame.render_widget(error_para, chunks[1]);
        return;
    }

    let items: Vec<ListItem> = state
        .recipes
        .iter()
        .enumerate()
        .map(|(i, recipe)| {
            let type_icon = if recipe.is_job() { "J" } else { "F" };
            let style = if i == state.selected {
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default()
            };

            ListItem::new(Line::from(vec![
                Span::styled(
                    format!("[{}] ", type_icon),
                    Style::default().fg(Color::Cyan),
                ),
                Span::styled(&recipe.name, style),
                Span::styled(
                    format!(" ({})", recipe.category()),
                    Style::default().fg(Color::DarkGray),
                ),
            ]))
        })
        .collect();

    let list = List::new(items)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(format!("Recipes ({} total)", state.recipes.len())),
        )
        .highlight_style(Style::default().bg(Color::DarkGray));

    frame.render_stateful_widget(list, chunks[1], &mut state.list_state);
}

fn render_recipe_details(frame: &mut Frame, area: Rect, state: &RecipeBrowserState) {
    let Some(recipe) = state.selected_recipe() else {
        let empty = Paragraph::new("Select a recipe to view details")
            .block(Block::default().borders(Borders::ALL).title("Details"));
        frame.render_widget(empty, area);
        return;
    };

    let content = vec![
        Line::from(vec![
            Span::styled("Name: ", Style::default().fg(Color::Cyan)),
            Span::raw(&recipe.name),
        ]),
        Line::from(vec![
            Span::styled("Module: ", Style::default().fg(Color::Cyan)),
            Span::raw(&recipe.module),
        ]),
        Line::from(vec![
            Span::styled("Type: ", Style::default().fg(Color::Cyan)),
            Span::raw(&recipe.recipe_type),
        ]),
        Line::from(vec![
            Span::styled("Signature: ", Style::default().fg(Color::Cyan)),
            Span::raw(&recipe.signature),
        ]),
        Line::from(""),
        Line::from(Span::styled(
            "Description:",
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
    ];

    // Add docstring lines
    let mut lines = content;
    for line in recipe.docstring.lines() {
        lines.push(Line::from(line));
    }

    let details = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Recipe Details"),
        )
        .wrap(Wrap { trim: false });

    frame.render_widget(details, area);
}

/// Helper function to create a centered rect.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_recipe_browser_state_default() {
        let state = RecipeBrowserState::default();
        assert!(!state.active);
        assert!(!state.loading);
        assert!(state.recipes.is_empty());
        assert!(state.error.is_none());
    }

    #[test]
    fn test_recipe_browser_open_close() {
        let mut state = RecipeBrowserState::new();
        assert!(!state.active);
        assert!(!state.closing);

        state.open();
        assert!(state.active);
        assert!(!state.closing);
        assert!(state.effect.is_some()); // Animation started

        state.close();
        // Animation pattern: closing=true, active still true until animation finishes
        assert!(state.closing);
        assert!(state.active); // Still active during close animation
    }

    #[test]
    fn test_recipe_browser_state_navigation() {
        let mut state = RecipeBrowserState::default();
        state.recipes = vec![
            Recipe {
                name: "relax_job".to_string(),
                module: "quacc.recipes.vasp.core".to_string(),
                fullname: "quacc.recipes.vasp.core.relax_job".to_string(),
                docstring: "Relax".to_string(),
                signature: "()".to_string(),
                recipe_type: "job".to_string(),
            },
            Recipe {
                name: "static_job".to_string(),
                module: "quacc.recipes.vasp.core".to_string(),
                fullname: "quacc.recipes.vasp.core.static_job".to_string(),
                docstring: "Static".to_string(),
                signature: "()".to_string(),
                recipe_type: "job".to_string(),
            },
        ];
        state.list_state.select(Some(0));

        state.next();
        assert_eq!(state.selected, 1);

        state.next();
        assert_eq!(state.selected, 1); // Can't go past end

        state.previous();
        assert_eq!(state.selected, 0);

        state.previous();
        assert_eq!(state.selected, 0); // Can't go past start
    }

    #[test]
    fn test_recipe_browser_set_data() {
        let mut state = RecipeBrowserState::default();
        state.loading = true;

        let recipes = vec![Recipe {
            name: "test_job".to_string(),
            module: "quacc.recipes.vasp.core".to_string(),
            fullname: "quacc.recipes.vasp.core.test_job".to_string(),
            docstring: "Test".to_string(),
            signature: "()".to_string(),
            recipe_type: "job".to_string(),
        }];

        let engine = WorkflowEngineStatus {
            configured: Some("parsl".to_string()),
            installed: vec!["parsl".to_string()],
            quacc_installed: true,
        };

        state.set_data(recipes, engine, None);

        assert!(!state.loading);
        assert_eq!(state.recipes.len(), 1);
        assert!(state.engine_status.quacc_installed);
        assert_eq!(state.selected, 0);
    }

    #[test]
    fn test_recipe_browser_empty_navigation() {
        let mut state = RecipeBrowserState::default();
        // Navigation on empty list should be no-op
        state.next();
        assert_eq!(state.selected, 0);
        state.previous();
        assert_eq!(state.selected, 0);
    }

    #[test]
    fn test_selected_recipe() {
        let mut state = RecipeBrowserState::default();
        assert!(state.selected_recipe().is_none());

        state.recipes = vec![Recipe {
            name: "test".to_string(),
            module: "mod".to_string(),
            fullname: "mod.test".to_string(),
            docstring: "doc".to_string(),
            signature: "()".to_string(),
            recipe_type: "job".to_string(),
        }];

        let recipe = state.selected_recipe().unwrap();
        assert_eq!(recipe.name, "test");
    }
}
