//! CrystalMath TUI - High-performance terminal interface for CRYSTAL23.
//!
//! This is the main entry point for the Rust TUI application.
//! It initializes the Python backend via PyO3, sets up the terminal,
//! and runs the main event loop.

mod app;
mod bridge;
mod lsp;
mod models;
mod ui;

use std::io::{self, Write};
use std::panic;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use anyhow::Result;
use crossterm::{
    event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyModifiers},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::prelude::*;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use app::App;

/// Global flag to track if terminal is in raw mode (for panic cleanup)
static TERMINAL_RAW: AtomicBool = AtomicBool::new(false);

/// RAII guard for terminal state management.
/// Ensures terminal is restored to normal state when dropped, even on panic or early return.
struct TerminalGuard {
    active: bool,
}

impl TerminalGuard {
    /// Initialize terminal for TUI mode (raw mode, alternate screen, mouse capture).
    fn new() -> Result<Self> {
        enable_raw_mode()?;
        TERMINAL_RAW.store(true, Ordering::SeqCst);
        execute!(io::stdout(), EnterAlternateScreen, EnableMouseCapture)?;
        Ok(Self { active: true })
    }

    /// Deactivate the guard (prevents cleanup on drop).
    /// Call this when you want to handle cleanup manually.
    #[allow(dead_code)]
    fn deactivate(&mut self) {
        self.active = false;
    }
}

impl Drop for TerminalGuard {
    fn drop(&mut self) {
        if self.active {
            let _ = disable_raw_mode();
            let _ = execute!(io::stdout(), LeaveAlternateScreen, DisableMouseCapture);
            TERMINAL_RAW.store(false, Ordering::SeqCst);
        }
    }
}

/// Install a panic hook that restores terminal state before printing panic info.
fn install_panic_hook() {
    let default_hook = panic::take_hook();
    panic::set_hook(Box::new(move |panic_info| {
        // Only cleanup if terminal was put in raw mode
        if TERMINAL_RAW.load(Ordering::SeqCst) {
            // Best effort cleanup - ignore errors
            let _ = disable_raw_mode();
            let _ = execute!(
                io::stdout(),
                LeaveAlternateScreen,
                DisableMouseCapture
            );
            let _ = io::stdout().flush();
        }
        // Call the default panic handler
        default_hook(panic_info);
    }));
}

/// Target frame rate for UI rendering (60fps = ~16ms per frame)
const FRAME_DURATION: Duration = Duration::from_millis(16);

fn main() -> Result<()> {
    // Install panic hook FIRST for terminal safety
    install_panic_hook();

    // Initialize logging
    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new(
            std::env::var("RUST_LOG").unwrap_or_else(|_| "crystalmath=info".into()),
        ))
        .with(tracing_subscriber::fmt::layer().with_target(false))
        .init();

    tracing::info!("Starting CrystalMath TUI v{}", env!("CARGO_PKG_VERSION"));

    // Initialize Python interpreter
    tracing::info!("Initializing Python backend...");
    pyo3::prepare_freethreaded_python();
    let py_controller = bridge::init_python_backend()?;
    tracing::info!("Python backend initialized");

    // Setup terminal with RAII guard - ensures cleanup on any exit path
    let _terminal_guard = TerminalGuard::new()?;

    let stdout = io::stdout();
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // Create application state
    let mut app = App::new(py_controller);

    // Run main loop - guard handles cleanup on success, error, or panic
    let result = run_app(&mut terminal, &mut app);

    // Show cursor before guard drops (guard handles the rest)
    terminal.show_cursor()?;

    // Report any errors after terminal is restored
    if let Err(e) = result {
        // Guard will drop here, restoring terminal state
        drop(_terminal_guard);
        tracing::error!("Application error: {}", e);
        eprintln!("Error: {}", e);
        std::process::exit(1);
    }

    tracing::info!("CrystalMath TUI exited cleanly");
    // Guard drops here, restoring terminal state
    Ok(())
}

/// Main application loop.
fn run_app<B: Backend>(terminal: &mut Terminal<B>, app: &mut App) -> Result<()> {
    // Initial job fetch (non-fatal - errors shown in UI)
    app.try_refresh_jobs();

    loop {
        // Poll Python bridge responses (non-blocking)
        app.poll_bridge_responses();

        // Poll LSP events (non-blocking)
        app.poll_lsp_events();

        // Handle time-based updates (LSP debounce)
        app.tick();

        // Check for error auto-clear
        app.maybe_clear_error();

        // Only redraw if state has changed (dirty-flag optimization)
        if app.take_needs_redraw() {
            terminal.draw(|f| ui::render(f, app))?;
        }

        // Poll for events with frame-rate limiting
        if event::poll(FRAME_DURATION)? {
            match event::read()? {
                Event::Key(key) => {
                    // Global key handlers
                    match (key.code, key.modifiers) {
                        // Quit: Ctrl+Q or Ctrl+C
                        (KeyCode::Char('q'), KeyModifiers::CONTROL)
                        | (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
                            app.should_quit = true;
                        }

                        // Tab navigation
                        (KeyCode::Tab, KeyModifiers::NONE) => {
                            app.next_tab();
                        }
                        (KeyCode::BackTab, KeyModifiers::SHIFT) => {
                            app.prev_tab();
                        }

                        // Number keys for direct tab access
                        (KeyCode::Char('1'), _) => app.set_tab(app::AppTab::Jobs),
                        (KeyCode::Char('2'), _) => app.set_tab(app::AppTab::Editor),
                        (KeyCode::Char('3'), _) => app.set_tab(app::AppTab::Results),
                        (KeyCode::Char('4'), _) => app.set_tab(app::AppTab::Log),

                        // Refresh jobs (non-fatal - errors shown in UI)
                        (KeyCode::Char('r'), KeyModifiers::CONTROL) => {
                            app.try_refresh_jobs();
                        }

                        // Tab-specific handlers (non-fatal)
                        _ => {
                            handle_tab_input(app, key);
                        }
                    }
                }
                Event::Resize(_, _) => {
                    // Terminal resized - trigger redraw
                    app.mark_dirty();
                }
                _ => {}
            }
        }

        // Check for quit
        if app.should_quit {
            break;
        }
    }

    Ok(())
}

/// Handle input specific to the current tab.
/// Uses non-fatal error handling - errors shown in UI.
fn handle_tab_input(app: &mut App, key: event::KeyEvent) {
    match app.current_tab {
        app::AppTab::Jobs => {
            match key.code {
                KeyCode::Up | KeyCode::Char('k') => app.select_prev_job(),
                KeyCode::Down | KeyCode::Char('j') => app.select_next_job(),
                KeyCode::Enter => {
                    // Show details for selected job (non-fatal)
                    if let Some(job) = app.selected_job() {
                        let pk = job.pk;
                        app.try_load_job_details(pk);
                        app.set_tab(app::AppTab::Results);
                    }
                }
                KeyCode::Home => app.select_first_job(),
                KeyCode::End => app.select_last_job(),
                _ => {}
            }
        }
        app::AppTab::Editor => {
            // Pass input to text editor and notify LSP if content changed
            if app.editor.input(key) {
                app.on_editor_change();
            }
        }
        app::AppTab::Results => {
            match key.code {
                KeyCode::Up | KeyCode::Char('k') => app.scroll_results_up(),
                KeyCode::Down | KeyCode::Char('j') => app.scroll_results_down(),
                KeyCode::PageUp => app.scroll_results_page_up(),
                KeyCode::PageDown => app.scroll_results_page_down(),
                _ => {}
            }
        }
        app::AppTab::Log => {
            match key.code {
                KeyCode::Up | KeyCode::Char('k') => app.scroll_log_up(),
                KeyCode::Down | KeyCode::Char('j') => app.scroll_log_down(),
                KeyCode::Home => app.scroll_log_top(),
                KeyCode::End => app.scroll_log_bottom(),
                _ => {}
            }
        }
    }
}
