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

use std::fs;
use std::io::{self, Write};
use std::panic;
use std::path::{Path, PathBuf};
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

/// Configure Python home/path before initializing PyO3.
///
/// This avoids runtime failures when the embedded Python prefix points at a
/// non-existent location (e.g. `/install`) by preferring an active venv.
fn configure_python_env() {
    if std::env::var_os("PYTHONHOME").is_some() {
        tracing::info!("PYTHONHOME already set; using existing value");
        return;
    }

    let mut candidates = Vec::new();
    push_env_candidate(&mut candidates, "CRYSTAL_PYTHON_HOME");
    push_env_candidate(&mut candidates, "CRYSTAL_PYTHON");
    push_env_candidate(&mut candidates, "PYTHON_SYS_EXECUTABLE");
    push_env_candidate(&mut candidates, "VIRTUAL_ENV");

    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join(".venv"));
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join(".venv"));
            if let Some(parent) = dir.parent() {
                candidates.push(parent.join(".venv"));
            }
        }
    }

    for candidate in candidates {
        if let Some(root) = normalize_venv_root(candidate) {
            if apply_python_env(&root) {
                return;
            }
        }
    }

    tracing::warn!(
        "Python stdlib not configured; set PYTHONHOME or CRYSTAL_PYTHON_HOME/VIRTUAL_ENV"
    );
}

fn push_env_candidate(candidates: &mut Vec<PathBuf>, var: &str) {
    if let Ok(value) = std::env::var(var) {
        candidates.push(PathBuf::from(value));
    }
}

fn normalize_venv_root(candidate: PathBuf) -> Option<PathBuf> {
    if candidate.is_dir() {
        return Some(candidate);
    }

    if candidate.is_file() {
        if let Some(parent) = candidate.parent() {
            let parent_name = parent.file_name().and_then(|name| name.to_str());
            if matches!(parent_name, Some("bin") | Some("Scripts")) {
                if let Some(root) = parent.parent() {
                    return Some(root.to_path_buf());
                }
            }
        }
    }

    None
}

fn apply_python_env(venv_root: &Path) -> bool {
    if !venv_root.is_dir() {
        return false;
    }

    // Check if this is a venv by looking for pyvenv.cfg
    let pyvenv_cfg = venv_root.join("pyvenv.cfg");
    let base_prefix = if pyvenv_cfg.exists() {
        // Read pyvenv.cfg to find the base Python installation
        if let Some(base) = read_pyvenv_home(&pyvenv_cfg) {
            base
        } else {
            venv_root.to_path_buf()
        }
    } else {
        venv_root.to_path_buf()
    };

    std::env::set_var("PYTHONHOME", &base_prefix);

    if std::env::var_os("PYTHONPATH").is_none() {
        if let Some(paths) = build_pythonpath_with_venv(&base_prefix, venv_root) {
            if let Ok(joined) = std::env::join_paths(paths) {
                std::env::set_var("PYTHONPATH", joined);
            }
        }
    }

    tracing::info!("Using PYTHONHOME={}", base_prefix.display());
    if let Ok(path) = std::env::var("PYTHONPATH") {
        tracing::info!("Using PYTHONPATH={}", path);
    }
    true
}

/// Read the base Python home from a venv's pyvenv.cfg file.
fn read_pyvenv_home(pyvenv_cfg: &Path) -> Option<PathBuf> {
    let content = fs::read_to_string(pyvenv_cfg).ok()?;
    for line in content.lines() {
        let line = line.trim();
        if let Some(value) = line.strip_prefix("home") {
            let value = value.trim_start_matches(|c| c == ' ' || c == '=').trim();
            // The 'home' value points to bin/, so get parent for prefix
            let bin_path = PathBuf::from(value);
            return bin_path.parent().map(|p| p.to_path_buf());
        }
    }
    None
}

/// Build PYTHONPATH with base Python stdlib and venv site-packages.
///
/// For venvs, we need BOTH:
/// - Base Python's stdlib (e.g., /usr/lib/python3.12/)
/// - Venv's site-packages (e.g., .venv/lib/python3.12/site-packages/)
/// - Paths from .pth files (for editable installs)
fn build_pythonpath_with_venv(base_prefix: &Path, venv_root: &Path) -> Option<Vec<PathBuf>> {
    let mut paths = Vec::new();

    // Find base Python's stdlib directory
    let base_lib = ["lib", "Lib"]
        .iter()
        .map(|base| base_prefix.join(base))
        .find(|path| path.is_dir());

    if let Some(lib_dir) = base_lib {
        // Find python version directory (e.g., python3.12)
        if let Ok(entries) = fs::read_dir(&lib_dir) {
            let mut python_dirs: Vec<PathBuf> = entries
                .flatten()
                .filter_map(|e| {
                    let path = e.path();
                    if path.is_dir() {
                        if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                            if name.starts_with("python") {
                                return Some(path);
                            }
                        }
                    }
                    None
                })
                .collect();
            python_dirs.sort();
            if let Some(python_dir) = python_dirs.pop() {
                paths.push(python_dir);
            }
        }
    }

    // Add venv's site-packages and process .pth files
    let venv_lib = ["lib", "Lib"]
        .iter()
        .map(|base| venv_root.join(base))
        .find(|path| path.is_dir());

    if let Some(lib_dir) = venv_lib {
        if let Ok(entries) = fs::read_dir(&lib_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                        if name.starts_with("python") {
                            let site_packages = path.join("site-packages");
                            if site_packages.is_dir() {
                                // Add site-packages itself
                                paths.push(site_packages.clone());

                                // Process .pth files for editable installs
                                if let Some(pth_paths) = read_pth_files(&site_packages) {
                                    paths.extend(pth_paths);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if paths.is_empty() {
        None
    } else {
        Some(paths)
    }
}

/// Read .pth files from site-packages and return paths they contain.
///
/// .pth files are used by pip for editable installs to point to the actual
/// package source directory. PyO3's embedded Python doesn't process these
/// automatically, so we need to handle them manually.
fn read_pth_files(site_packages: &Path) -> Option<Vec<PathBuf>> {
    let mut paths = Vec::new();

    if let Ok(entries) = fs::read_dir(site_packages) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_file() {
                if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                    // Only process .pth files (skip __editable__ ones that contain code)
                    if name.ends_with(".pth") && !name.starts_with("__editable__") {
                        if let Ok(content) = fs::read_to_string(&path) {
                            for line in content.lines() {
                                let line = line.trim();
                                // Skip empty lines and comments
                                if line.is_empty() || line.starts_with('#') {
                                    continue;
                                }
                                // Skip lines that look like Python code (import statements)
                                if line.starts_with("import ") {
                                    continue;
                                }
                                let pth_path = PathBuf::from(line);
                                if pth_path.is_dir() {
                                    tracing::debug!("Adding path from {}: {}", name, line);
                                    paths.push(pth_path);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if paths.is_empty() {
        None
    } else {
        Some(paths)
    }
}

fn build_pythonpath(venv_root: &Path) -> Option<Vec<PathBuf>> {
    let lib_dir = ["lib", "Lib"]
        .iter()
        .map(|base| venv_root.join(base))
        .find(|path| path.is_dir())?;

    let mut python_dirs = Vec::new();
    let entries = fs::read_dir(&lib_dir).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            if let Some(name) = path.file_name().and_then(|name| name.to_str()) {
                if name.starts_with("python") {
                    python_dirs.push(path);
                }
            }
        }
    }

    python_dirs.sort();
    let python_dir = python_dirs.pop()?;

    let mut paths = vec![python_dir.clone()];
    let site_packages = python_dir.join("site-packages");
    if site_packages.is_dir() {
        paths.push(site_packages);
    }

    Some(paths)
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
    configure_python_env();
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
