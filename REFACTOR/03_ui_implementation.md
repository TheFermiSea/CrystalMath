# UI Implementation: Rust & Ratatui

This guide details how to reconstruct your Textual UI using Ratatui.

## 1. Dependencies (`Cargo.toml`)

```toml
[package]
name = "crystalmath-tui"
version = "0.2.0"
edition = "2021"

[dependencies]
ratatui = "0.26.1"
crossterm = "0.27.0"
# For async runtime (if needed for network/LSP)
tokio = { version = "1", features = ["full"] }
# JSON & Serialization
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
# Python Integration
pyo3 = { version = "0.21", features = ["auto-initialize"] }
# Widgets
tui-textarea = "0.4"
# Error handling
anyhow = "1.0"
```

## 2. Application State (`src/app.rs`)

Ratatui is immediate mode. We need a central struct that holds all data needed to render the current frame.

```rust
use crate::models::{JobStatus, JobDetails};
use tui_textarea::TextArea;

pub enum AppTab {
    Jobs,
    Editor,
    Results,
    Log,
}

pub struct App<'a> {
    pub should_quit: bool,
    pub current_tab: AppTab,
    
    // Data Lists
    pub jobs: Vec<JobStatus>,
    pub selected_job_index: Option<usize>,
    
    // Editor State
    pub editor: TextArea<'a>,
    pub editor_file_path: Option<String>,
    pub lsp_diagnostics: Vec<crate::lsp::Diagnostic>,
    
    // Results View
    pub current_job_details: Option<JobDetails>,
    
    // Python Controller (Thread-safe reference)
    pub py_controller: pyo3::PyObject,
}

impl<'a> App<'a> {
    pub fn new(py_controller: pyo3::PyObject) -> Self {
        let mut editor = TextArea::default();
        editor.set_line_number_style(
            ratatui::style::Style::default().fg(ratatui::style::Color::DarkGray)
        );
        
        Self {
            should_quit: false,
            current_tab: AppTab::Jobs,
            jobs: Vec::new(),
            selected_job_index: None,
            editor,
            editor_file_path: None,
            lsp_diagnostics: Vec::new(),
            current_job_details: None,
            py_controller,
        }
    }
    
    pub fn next_tab(&mut self) {
        self.current_tab = match self.current_tab {
            AppTab::Jobs => AppTab::Editor,
            AppTab::Editor => AppTab::Results,
            AppTab::Results => AppTab::Log,
            AppTab::Log => AppTab::Jobs,
        };
    }
}
```

## 3. Main Loop & Layout (`src/main.rs`)

```rust
use std::{io, time::Duration};
use ratatui::{prelude::*, widgets::*, Terminal};
use crossterm::{event::{self, Event, KeyCode}, execute, terminal::*};

mod app;
mod ui;
mod models;
mod bridge;

use app::App;

fn main() -> anyhow::Result<()> {
    // 1. Initialize Python
    pyo3::prepare_freethreaded_python();
    let py_controller = bridge::init_python_backend()?;

    // 2. Setup Terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // 3. Create App State
    let mut app = App::new(py_controller);

    // 4. Main Loop
    loop {
        terminal.draw(|f| ui::render(f, &mut app))?;

        // Handle Input
        if event::poll(Duration::from_millis(16))? {
            if let Event::Key(key) = event::read()? {
                match key.code {
                    KeyCode::Char('q') => app.should_quit = true,
                    KeyCode::Tab => app.next_tab(),
                    // Pass inputs to editor if tab is active
                    _ => {
                        if let app::AppTab::Editor = app.current_tab {
                            app.editor.input(key);
                        }
                    }
                }
            }
        }

        // Periodic Data Refresh (e.g., every 1s)
        // In a real app, do this in a separate thread/timer to avoid blocking UI
        // bridge::refresh_jobs(&mut app)?; 

        if app.should_quit {
            break;
        }
    }

    // 5. Cleanup
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    Ok(())
}
```

## 4. Rendering Widgets (`src/ui.rs`)

Replacing `DataTable` with Ratatui `Table`.

```rust
use ratatui::{prelude::*, widgets::*};
use crate::app::{App, AppTab};

pub fn render(f: &mut Frame, app: &mut App) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Header
            Constraint::Min(0),    // Content
            Constraint::Length(3), // Footer
        ])
        .split(f.size());

    render_header(f, chunks[0]);
    
    match app.current_tab {
        AppTab::Jobs => render_jobs_list(f, app, chunks[1]),
        AppTab::Editor => render_editor(f, app, chunks[1]),
        _ => {}, // Implement others
    }
}

fn render_jobs_list(f: &mut Frame, app: &App, area: Rect) {
    let header = Row::new(vec!["ID", "Name", "Status", "Progress", "Wall Time"])
        .style(Style::default().fg(Color::Yellow));
        
    let rows: Vec<Row> = app.jobs.iter().map(|job| {
        Row::new(vec![
            job.pk.to_string(),
            job.name.clone(),
            format!("{:?}", job.state),
            format!("{:.1}%", job.progress_percent),
            job.wall_time_seconds
                .map(|t| format!("{:.1}s", t))
                .unwrap_or("-".into()),
        ])
        .style(Style::default().fg(job.state.color()))
    }).collect();

    let table = Table::new(rows, [
        Constraint::Length(6),
        Constraint::Min(20),
        Constraint::Length(12),
        Constraint::Length(10),
        Constraint::Length(12),
    ])
    .header(header)
    .block(Block::default().borders(Borders::ALL).title("Active Jobs"));

    f.render_widget(table, area);
}

fn render_editor(f: &mut Frame, app: &mut App, area: Rect) {
    let mut widget = app.editor.widget();
    widget.set_block(
        Block::default()
            .borders(Borders::ALL)
            .title("Input Editor (VASP/CRYSTAL)")
    );
    f.render_widget(widget, area);
}
```
