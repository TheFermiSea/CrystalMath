//! CrystalMath TUI - High-performance terminal interface for CRYSTAL23.
//!
//! This is the main entry point for the Rust TUI application.
//! It initializes the Python backend via PyO3, sets up the terminal,
//! and runs the main event loop.

mod app;
mod lsp;
mod state;
mod ui;

// Re-use modules from lib.rs (exposed for integration tests)
use crystalmath_tui::{bridge, models};

use std::fs::{self, File};
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
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use app::App;
use crate::state::{BatchSubmissionField, OutputFileType, WorkflowConfigField};

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

        // If execute! fails, we must restore terminal state before returning error
        if let Err(e) = execute!(io::stdout(), EnterAlternateScreen, EnableMouseCapture) {
            // Rollback: disable raw mode before returning error
            let _ = disable_raw_mode();
            TERMINAL_RAW.store(false, Ordering::SeqCst);
            return Err(e.into());
        }

        Ok(Self { active: true })
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
            let _ = execute!(io::stdout(), LeaveAlternateScreen, DisableMouseCapture);
            let _ = io::stdout().flush();
        }
        // Call the default panic handler
        default_hook(panic_info);
    }));
}

/// Configure Python home/path before initializing PyO3.
///
/// Queries the Python executable directly to get sys.prefix and sys.path,
/// avoiding fragile manual parsing of pyvenv.cfg and .pth files.
fn configure_python_env() {
    if std::env::var_os("PYTHONHOME").is_some() {
        tracing::info!("PYTHONHOME already set; using existing value");
        return;
    }

    // Find Python executable in order of preference
    let python_candidates = find_python_candidates();

    for python_exe in python_candidates {
        if let Some(env_info) = query_python_env(&python_exe) {
            // Set PYTHONHOME to base_prefix (the actual Python installation)
            std::env::set_var("PYTHONHOME", &env_info.base_prefix);
            tracing::info!("Using PYTHONHOME={}", env_info.base_prefix);

            // Log venv detection
            if env_info.is_venv() {
                tracing::info!(
                    "Detected venv: prefix={}, base_prefix={}",
                    env_info.prefix,
                    env_info.base_prefix
                );
            }

            // Set PYTHONPATH if not already set
            if std::env::var_os("PYTHONPATH").is_none() && !env_info.path.is_empty() {
                // Start with paths from Python's sys.path
                let mut paths = env_info.path.clone();

                // CRITICAL: For venvs, ensure the venv's site-packages is included
                // This is needed because PYTHONHOME points to base_prefix (system Python)
                // but we need packages from the venv's site-packages
                if let Some(venv_site_packages) = env_info.venv_site_packages() {
                    let site_packages_str = venv_site_packages.display().to_string();
                    if !paths.contains(&site_packages_str) {
                        // Prepend venv site-packages so it takes priority
                        paths.insert(0, site_packages_str.clone());
                        tracing::info!("Added venv site-packages to PYTHONPATH: {}", site_packages_str);
                    }
                }

                // Add project python/ directory for crystalmath.api
                if let Some(project_root) = find_project_root() {
                    let python_dir = project_root.join("python");
                    if python_dir.is_dir() {
                        let python_dir_str = python_dir.display().to_string();
                        if !paths.contains(&python_dir_str) {
                            paths.push(python_dir_str);
                        }
                    }
                }

                if let Ok(joined) = std::env::join_paths(&paths) {
                    std::env::set_var("PYTHONPATH", &joined);
                    tracing::info!("Using PYTHONPATH from Python query (venv-aware)");
                }
            }
            return;
        }
    }

    tracing::warn!("Python stdlib not configured; set PYTHONHOME or VIRTUAL_ENV");
}

/// Python environment info queried from the interpreter.
struct PythonEnvInfo {
    prefix: String,
    base_prefix: String,
    path: Vec<String>,
}

impl PythonEnvInfo {
    /// Returns true if this is a virtual environment (prefix != base_prefix).
    fn is_venv(&self) -> bool {
        self.prefix != self.base_prefix
    }

    /// Get the venv site-packages path if this is a venv.
    fn venv_site_packages(&self) -> Option<PathBuf> {
        if self.is_venv() {
            // Standard venv layout: {prefix}/lib/pythonX.Y/site-packages
            let prefix = Path::new(&self.prefix);
            let lib_dir = prefix.join("lib");
            if let Ok(entries) = std::fs::read_dir(&lib_dir) {
                for entry in entries.flatten() {
                    let name = entry.file_name();
                    let name_str = name.to_string_lossy();
                    if name_str.starts_with("python") {
                        let site_packages = entry.path().join("site-packages");
                        if site_packages.is_dir() {
                            return Some(site_packages);
                        }
                    }
                }
            }
        }
        None
    }
}

/// Query Python executable to get sys.prefix, sys.base_prefix, and sys.path.
fn query_python_env(python_exe: &Path) -> Option<PythonEnvInfo> {
    use std::process::Command;

    let script = r#"
import sys, json
print(json.dumps({
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "path": [p for p in sys.path if p]
}))
"#;

    let output = Command::new(python_exe)
        .args(["-c", script])
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let parsed: serde_json::Value = serde_json::from_str(stdout.trim()).ok()?;

    Some(PythonEnvInfo {
        prefix: parsed["prefix"].as_str()?.to_string(),
        base_prefix: parsed["base_prefix"].as_str()?.to_string(),
        path: parsed["path"]
            .as_array()?
            .iter()
            .filter_map(|v| v.as_str().map(String::from))
            .collect(),
    })
}

/// Build a path to the Python executable inside a directory (venv or prefix).
fn python_exe_in(base: &Path) -> PathBuf {
    let bin_dir = if cfg!(windows) { "Scripts" } else { "bin" };
    let exe_name = if cfg!(windows) { "python.exe" } else { "python" };
    base.join(bin_dir).join(exe_name)
}

/// Find Python executable candidates in order of preference.
fn find_python_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    // 1. Explicit environment variables
    for var in ["CRYSTAL_PYTHON", "PYTHON_SYS_EXECUTABLE"] {
        if let Ok(value) = std::env::var(var) {
            let path = PathBuf::from(&value);
            if path.is_file() {
                candidates.push(path);
            }
        }
    }

    // 2. VIRTUAL_ENV/bin/python
    if let Ok(venv) = std::env::var("VIRTUAL_ENV") {
        let venv_python = python_exe_in(Path::new(&venv));
        if venv_python.is_file() {
            candidates.push(venv_python);
        }
    }

    // 3. Project .venv/bin/python
    if let Some(project_root) = find_project_root() {
        let venv_python = python_exe_in(&project_root.join(".venv"));
        if venv_python.is_file() {
            candidates.push(venv_python);
        }
    }

    // 4. CWD .venv/bin/python (fallback)
    if let Ok(cwd) = std::env::current_dir() {
        let venv_python = python_exe_in(&cwd.join(".venv"));
        if venv_python.is_file() {
            candidates.push(venv_python);
        }
    }

    // 5. System python3 as last resort
    let system_exe = if cfg!(windows) { "python.exe" } else { "python3" };
    candidates.push(PathBuf::from(system_exe));

    candidates
}

/// Find the project root by looking for Cargo.toml, walking up from the executable.
fn find_project_root() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let mut dir = exe.parent()?;

    for _ in 0..5 {
        if dir.join("Cargo.toml").exists() {
            return Some(dir.to_path_buf());
        }
        dir = dir.parent()?;
    }

    None
}

/// Target frame rate for UI rendering (60fps = ~16ms per frame)
const FRAME_DURATION: Duration = Duration::from_millis(16);

fn main() -> Result<()> {
    // Install panic hook FIRST for terminal safety
    install_panic_hook();

    // Initialize logging to file (avoids interference with TUI)
    // Log file is stored at ~/.local/share/crystalmath/crystalmath.log (or platform equivalent)
    let log_dir = dirs::data_local_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("crystalmath");
    let _ = fs::create_dir_all(&log_dir);
    let log_file_path = log_dir.join("crystalmath.log");

    // Open log file (truncate on each run)
    let log_file = File::create(&log_file_path).ok();

    if let Some(file) = log_file {
        tracing_subscriber::registry()
            .with(tracing_subscriber::EnvFilter::new(
                std::env::var("RUST_LOG").unwrap_or_else(|_| "crystalmath=info".into()),
            ))
            .with(
                tracing_subscriber::fmt::layer()
                    .with_target(false)
                    .with_ansi(false)
                    .with_writer(std::sync::Mutex::new(file)),
            )
            .init();
    } else {
        // Fallback: no logging if file can't be created (don't use stderr to avoid TUI issues)
        tracing_subscriber::registry()
            .with(tracing_subscriber::EnvFilter::new("error"))
            .with(tracing_subscriber::fmt::layer().with_target(false))
            .init();
    }

    tracing::info!("Starting CrystalMath TUI v{}", env!("CARGO_PKG_VERSION"));

    // Initialize Python interpreter
    tracing::info!("Initializing Python backend...");
    configure_python_env();
    pyo3::Python::initialize();
    let py_controller = bridge::init_python_backend()?;
    tracing::info!("Python backend initialized");

    // Setup terminal with RAII guard - ensures cleanup on any exit path
    let _terminal_guard = TerminalGuard::new()?;

    let stdout = io::stdout();
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // Create application state (propagates error if Python bridge fails to spawn)
    let mut app = App::new(py_controller)?;

    // Run main loop - guard handles cleanup on success, error, or panic
    let result = run_app(&mut terminal, &mut app);

    // Show cursor before guard drops (guard handles the rest)
    terminal.show_cursor()?;

    // Report any errors after terminal is restored
    if let Err(e) = result {
        // Drop app first to ensure BridgeHandle and LspClient cleanup runs
        drop(app);
        // Then drop terminal guard to restore terminal state
        drop(_terminal_guard);
        tracing::error!("Application error: {}", e);
        eprintln!("Error: {}", e);
        // Return error instead of process::exit to allow proper cleanup
        return Err(e);
    }

    tracing::info!("CrystalMath TUI exited cleanly");
    // Guard drops here, restoring terminal state
    Ok(())
}

/// Main application loop.
fn run_app<B: Backend>(terminal: &mut Terminal<B>, app: &mut App) -> Result<()> {
    // Initial data fetch (non-fatal - errors shown in UI)
    app.try_refresh_jobs();
    app.try_refresh_clusters(); // Needed for SLURM queue access

    loop {
        // Poll Python bridge responses (non-blocking)
        app.poll_bridge_responses();

        // Poll job status updates (time-gated, non-blocking)
        app.poll_job_statuses();

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
                    // Help modal takes highest priority (can overlay other modals)
                    if app.is_help_modal_active() {
                        if !app.help.closing {
                            handle_help_modal_input(app, key);
                        }
                    // Output viewer modal (high priority, similar to help)
                    } else if app.is_output_viewer_active() {
                        if !app.output_viewer.closing {
                            handle_output_viewer_input(app, key);
                        }
                    // Modal input takes priority over all other handlers
                    } else if app.is_new_job_modal_active() {
                        if !app.new_job.closing {
                            handle_new_job_modal_input(app, key);
                        }
                    } else if app.is_materials_modal_active() {
                        if !app.materials.closing {
                            handle_materials_modal_input(app, key);
                        }
                    } else if app.is_cluster_manager_modal_active() {
                        if !app.cluster_manager.closing {
                            handle_cluster_manager_modal_input(app, key);
                        }
                    } else if app.is_slurm_queue_modal_active() {
                        if !app.slurm_queue_state.closing {
                            handle_slurm_queue_modal_input(app, key);
                        }
                    } else if app.is_vasp_input_modal_active() {
                        if !app.vasp_input_state.closing {
                            handle_vasp_input_modal_input(app, key);
                        }
                    } else if app.is_recipe_browser_active() {
                        if !app.recipe_browser.closing {
                            handle_recipe_browser_input(app, key);
                        }
                    } else if app.is_workflow_results_active() {
                        handle_workflow_results_input(app, key);
                    } else if app.is_workflow_config_active() {
                        if !app.workflow_config.closing {
                            handle_workflow_config_input(app, key);
                        }
                    } else if app.is_workflow_modal_active() {
                        if !app.workflow_state.closing {
                            handle_workflow_modal_input(app, key);
                        }
                    } else if app.is_template_browser_active() {
                        if !app.template_browser.closing {
                            handle_template_browser_input(app, key);
                        }
                    } else if app.is_batch_submission_active() {
                        if !app.batch_submission.closing {
                            handle_batch_submission_input(app, key);
                        }
                    } else {
                        if app.current_tab == app::AppTab::Jobs && app.workflow_list.active {
                            if handle_workflow_dashboard_input(app, key) {
                                continue;
                            }
                        }
                        // Global key handlers
                        match (key.code, key.modifiers) {
                            // Help (works from anywhere, including over other modals)
                            (KeyCode::Char('?'), _) => {
                                app.open_help_modal();
                            }

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

                            // Sync remote jobs (Shift+R) - updates status from squeue/sacct
                            (KeyCode::Char('R'), KeyModifiers::SHIFT) => {
                                app.request_sync_remote_jobs();
                            }

                            // Open Materials Project import modal (Ctrl+I from Editor)
                            (KeyCode::Char('i'), KeyModifiers::CONTROL) => {
                                if app.current_tab == app::AppTab::Editor {
                                    app.open_materials_modal();
                                }
                            }

                            // Open New Job modal (n from Jobs or Editor tab)
                            (KeyCode::Char('n'), KeyModifiers::NONE) => {
                                if app.current_tab == app::AppTab::Jobs
                                    || app.current_tab == app::AppTab::Editor
                                {
                                    app.open_new_job_modal();
                                }
                            }

                            // Open Cluster Manager modal (c from Jobs tab)
                            (KeyCode::Char('c'), KeyModifiers::NONE) => {
                                if app.current_tab == app::AppTab::Jobs {
                                    app.open_cluster_manager_modal();
                                }
                            }

                            // Open Recipe Browser modal (r from Jobs tab)
                            (KeyCode::Char('r'), KeyModifiers::NONE) => {
                                if app.current_tab == app::AppTab::Jobs {
                                    app.open_recipe_browser();
                                }
                            }

                            // Open Workflow Launcher modal (w from Jobs tab)
                            (KeyCode::Char('w'), KeyModifiers::NONE) => {
                                if app.current_tab == app::AppTab::Jobs {
                                    app.open_workflow_modal();
                                }
                            }

                            // Toggle Workflow Dashboard (Shift+W from Jobs tab)
                            (KeyCode::Char('W'), KeyModifiers::SHIFT) => {
                                if app.current_tab == app::AppTab::Jobs {
                                    app.toggle_workflow_dashboard();
                                }
                            }

                            // Open Template Browser modal (T from Jobs or Editor tab)
                            (KeyCode::Char('T'), KeyModifiers::SHIFT) => {
                                if app.current_tab == app::AppTab::Jobs
                                    || app.current_tab == app::AppTab::Editor
                                {
                                    app.open_template_browser();
                                }
                            }

                            // Open Batch Submission modal (B from Jobs or Editor tab)
                            (KeyCode::Char('B'), KeyModifiers::SHIFT) => {
                                if app.current_tab == app::AppTab::Jobs
                                    || app.current_tab == app::AppTab::Editor
                                {
                                    app.open_batch_submission();
                                }
                            }

                            // Open SLURM Queue modal (s from Jobs tab)
                            (KeyCode::Char('s'), KeyModifiers::NONE) => {
                                if app.current_tab == app::AppTab::Jobs {
                                    match app.resolve_slurm_cluster_id() {
                                        Some(cluster_id) => {
                                            app.open_slurm_queue_modal(cluster_id);
                                        }
                                        None => {
                                            app.set_error("No SLURM clusters configured. Use 'c' to add a cluster.");
                                        }
                                    }
                                }
                            }

                            // Open VASP Input modal (v from Jobs tab)
                            (KeyCode::Char('v'), KeyModifiers::NONE) => {
                                if app.current_tab == app::AppTab::Jobs {
                                    app.open_vasp_input_modal();
                                }
                            }

                            // Tab-specific handlers (non-fatal)
                            _ => {
                                handle_tab_input(app, key);
                            }
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

/// Handle input for the materials search modal.
///
/// Modal captures all input when active:
/// - Escape: Close modal
/// - Enter: Search (if no results) or Import selected material
/// - Up/Down: Navigate results table
/// - Other keys: Passed to text input
fn handle_materials_modal_input(app: &mut App, key: event::KeyEvent) {
    // Don't process input while loading
    if app.materials.loading {
        // Only allow Escape during loading (to cancel)
        if key.code == KeyCode::Esc {
            app.close_materials_modal();
        }
        return;
    }

    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_materials_modal();
        }

        // Enter: Search or Import
        KeyCode::Enter => {
            if app.materials.results.is_empty() {
                // No results - trigger search
                app.request_materials_search();
            } else if app.materials.table_state.selected().is_some() {
                // Have selection - trigger import
                app.request_generate_d12();
            }
        }

        // 'v' key: Generate VASP inputs (requires selection)
        KeyCode::Char('v') if app.materials.table_state.selected().is_some() => {
            app.request_generate_vasp_from_mp();
        }

        // 'p' key: Cycle VASP preset (requires selection)
        KeyCode::Char('p') if app.materials.table_state.selected().is_some() => {
            app.materials.cycle_vasp_preset();
            app.mark_dirty();
        }

        // 'K' key (shift+k): Cycle k-point density (requires selection)
        // Note: lowercase 'k' is used for navigation
        KeyCode::Char('K') if app.materials.table_state.selected().is_some() => {
            app.materials.cycle_kppra();
            app.mark_dirty();
        }

        // 's' key: Submit job to quacc (requires generated POSCAR)
        KeyCode::Char('s') if app.materials.can_submit() => {
            app.request_submit_quacc_job();
        }

        // 'c' key: Cycle through quacc clusters
        KeyCode::Char('c') if !app.quacc_clusters.is_empty() => {
            let max = app.quacc_clusters.len();
            app.materials.cycle_cluster(max);
            app.mark_dirty();
        }

        // Navigate results table
        KeyCode::Up | KeyCode::Char('k') if !app.materials.results.is_empty() => {
            app.materials.select_prev();
            app.request_structure_preview();
            app.mark_dirty();
        }
        KeyCode::Down | KeyCode::Char('j') if !app.materials.results.is_empty() => {
            app.materials.select_next();
            app.request_structure_preview();
            app.mark_dirty();
        }

        // Pass to text input
        _ => {
            // Forward to the text input widget
            if app.materials.input.input(key) {
                app.mark_dirty();
            }
        }
    }
}

/// Handle input specific to the current tab.
/// Uses non-fatal error handling - errors shown in UI.
fn handle_tab_input(app: &mut App, key: event::KeyEvent) {
    match app.current_tab {
        app::AppTab::Jobs => {
            if app.workflow_list.active {
                return;
            }
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
                // L - View log for selected job (with follow mode)
                KeyCode::Char('l') | KeyCode::Char('L') => {
                    app.view_job_log();
                }
                // o - View OUTCAR for selected job
                KeyCode::Char('o') => {
                    if let Some(job) = app.selected_job() {
                        let pk = job.pk;
                        let name = Some(job.name.clone());
                        app.open_output_viewer(OutputFileType::Outcar, pk, name);
                    }
                }
                // O - View vasprun.xml for selected job
                KeyCode::Char('O') => {
                    if let Some(job) = app.selected_job() {
                        let pk = job.pk;
                        let name = Some(job.name.clone());
                        app.open_output_viewer(OutputFileType::VasprunXml, pk, name);
                    }
                }
                // C - Cancel job (two-key confirmation: press twice within 3s)
                KeyCode::Char('c') | KeyCode::Char('C') => {
                    app.request_cancel_selected_job();
                }
                // D - Diff job inputs (select two jobs to compare)
                KeyCode::Char('d') | KeyCode::Char('D') => {
                    app.request_diff_job();
                }
                // U - Toggle SLURM queue view (matches Python TUI)
                KeyCode::Char('u') | KeyCode::Char('U') => {
                    tracing::info!("Key 'U' pressed on Jobs tab - calling toggle_slurm_view()");
                    app.toggle_slurm_view();
                }
                // f - Cycle status filter (Running -> Completed -> Failed -> Queued -> All)
                KeyCode::Char('f') => {
                    app.cycle_job_status_filter();
                }
                // F - Cycle DFT code filter (Crystal -> VASP -> QE -> All)
                KeyCode::Char('F') => {
                    app.cycle_job_code_filter();
                }
                // x - Clear all filters
                KeyCode::Char('x') => {
                    app.clear_job_filters();
                }
                KeyCode::Home => app.select_first_job(),
                KeyCode::End => app.select_last_job(),
                _ => {}
            }
        }
        app::AppTab::Editor => {
            // Handle Ctrl+Enter for job submission (before passing to editor)
            if key.code == KeyCode::Enter && key.modifiers.contains(KeyModifiers::CONTROL) {
                app.request_submit_from_editor();
                return;
            }

            // Pass input to text editor and notify LSP if content changed
            if app.editor.input(key) {
                app.on_editor_change();
            }
        }
        app::AppTab::Results => match key.code {
            KeyCode::Up | KeyCode::Char('k') => app.scroll_results_up(),
            KeyCode::Down | KeyCode::Char('j') => app.scroll_results_down(),
            KeyCode::PageUp => app.scroll_results_page_up(),
            KeyCode::PageDown => app.scroll_results_page_down(),
            _ => {}
        },
        app::AppTab::Log => match key.code {
            KeyCode::Up | KeyCode::Char('k') => app.scroll_log_up(),
            KeyCode::Down | KeyCode::Char('j') => app.scroll_log_down(),
            KeyCode::Home | KeyCode::Char('g') => app.scroll_log_top(),
            KeyCode::End | KeyCode::Char('G') => app.scroll_log_bottom(),
            KeyCode::PageUp => app.scroll_log_page_up(),
            KeyCode::PageDown => app.scroll_log_page_down(),
            // F - Toggle follow mode (auto-refresh every 2s)
            KeyCode::Char('f') | KeyCode::Char('F') => app.toggle_log_follow(),
            // R - Manual refresh
            KeyCode::Char('r') => {
                if let Some(pk) = app.log_job_pk {
                    app.request_log_refresh(pk);
                }
            }
            _ => {}
        },
    }
}

/// Handle input for the workflow dashboard (Jobs tab grouped view).
/// Returns true if the key was consumed.
fn handle_workflow_dashboard_input(app: &mut App, key: event::KeyEvent) -> bool {
    match (key.code, key.modifiers) {
        (KeyCode::Esc, _) => {
            app.workflow_list.set_active(false);
            app.mark_dirty();
            true
        }
        (KeyCode::Tab, KeyModifiers::NONE) | (KeyCode::BackTab, KeyModifiers::SHIFT) => {
            app.toggle_workflow_focus();
            true
        }
        (KeyCode::Up, _) | (KeyCode::Char('k'), _) => {
            if app.workflow_list.focus == crate::state::WorkflowDashboardFocus::Workflows {
                app.select_prev_dashboard_workflow();
            } else {
                app.select_prev_workflow_job();
            }
            true
        }
        (KeyCode::Down, _) | (KeyCode::Char('j'), _) => {
            if app.workflow_list.focus == crate::state::WorkflowDashboardFocus::Workflows {
                app.select_next_dashboard_workflow();
            } else {
                app.select_next_workflow_job();
            }
            true
        }
        (KeyCode::Enter, _) => {
            if app.workflow_list.focus == crate::state::WorkflowDashboardFocus::Workflows {
                app.open_selected_workflow_results();
            } else if let Some(jobs) = app.selected_workflow_jobs() {
                if let Some(idx) = app.workflow_list.selected_job {
                    if let Some(job) = jobs.get(idx) {
                        app.try_load_job_details(job.pk);
                        app.set_tab(app::AppTab::Results);
                    }
                }
            }
            true
        }
        (KeyCode::Char('r'), KeyModifiers::NONE) => {
            app.retry_selected_workflow_job();
            true
        }
        _ => false,
    }
}

/// Handle input for the workflow results modal.
fn handle_workflow_results_input(app: &mut App, key: event::KeyEvent) {
    match key.code {
        KeyCode::Esc => app.close_workflow_results(),
        KeyCode::Up | KeyCode::Char('k') => {
            if app.workflow_results.scroll > 0 {
                app.workflow_results.scroll -= 1;
                app.mark_dirty();
            }
        }
        KeyCode::Down | KeyCode::Char('j') => {
            app.workflow_results.scroll = app.workflow_results.scroll.saturating_add(1);
            app.mark_dirty();
        }
        _ => {}
    }
}

/// Handle input for the new job modal.
///
/// Modal captures all input when active:
/// - Escape: Close modal
/// - Tab: Next field
/// - Shift+Tab: Previous field
/// - Enter: Submit job
/// - Space: Cycle options (for DFT code, runner type)
/// - Backspace: Delete character (for name input)
/// - Other chars: Type into name input (when focused)
fn handle_new_job_modal_input(app: &mut App, key: event::KeyEvent) {
    use crate::app::NewJobField;

    // Don't process input while submitting
    if app.new_job.submitting {
        // Only allow Escape during submit (to cancel viewing)
        if key.code == KeyCode::Esc {
            app.close_new_job_modal();
        }
        return;
    }

    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_new_job_modal();
        }

        // Submit job
        KeyCode::Enter => {
            if app.new_job.can_submit() {
                app.submit_new_job();
            }
        }

        // Navigate fields
        KeyCode::Tab => {
            app.new_job.focused_field = app.new_job.focused_field.next();
            app.new_job.clear_error();
            app.mark_dirty();
        }
        KeyCode::BackTab => {
            app.new_job.focused_field = app.new_job.focused_field.prev();
            app.new_job.clear_error();
            app.mark_dirty();
        }

        // Field-specific input
        KeyCode::Char(' ') => {
            // Space cycles options for selector fields
            match app.new_job.focused_field {
                NewJobField::DftCode => {
                    app.new_job.cycle_dft_code();
                    app.mark_dirty();
                }
                NewJobField::RunnerType => {
                    app.new_job.cycle_runner_type();
                    app.mark_dirty();
                }
                NewJobField::ParallelMode => {
                    app.new_job.is_parallel = !app.new_job.is_parallel;
                    app.mark_dirty();
                }
                NewJobField::AuxGui => {
                    app.new_job.aux_gui_enabled = !app.new_job.aux_gui_enabled;
                    app.mark_dirty();
                }
                NewJobField::AuxF9 => {
                    app.new_job.aux_f9_enabled = !app.new_job.aux_f9_enabled;
                    app.mark_dirty();
                }
                NewJobField::AuxHessopt => {
                    app.new_job.aux_hessopt_enabled = !app.new_job.aux_hessopt_enabled;
                    app.mark_dirty();
                }
                _ => {}
            }
        }

        KeyCode::Backspace => {
            match app.new_job.focused_field {
                NewJobField::Name => {
                    app.new_job.job_name.pop();
                }
                NewJobField::MpiRanks => {
                    app.new_job.mpi_ranks.pop();
                }
                NewJobField::Walltime => {
                    app.new_job.walltime.pop();
                }
                NewJobField::Memory => {
                    app.new_job.memory_gb.pop();
                }
                NewJobField::Cpus => {
                    app.new_job.cpus_per_task.pop();
                }
                NewJobField::Nodes => {
                    app.new_job.nodes.pop();
                }
                NewJobField::Partition => {
                    app.new_job.partition.pop();
                }
                NewJobField::AuxGui => {
                    app.new_job.aux_gui_path.pop();
                }
                NewJobField::AuxF9 => {
                    app.new_job.aux_f9_path.pop();
                }
                NewJobField::AuxHessopt => {
                    app.new_job.aux_hessopt_path.pop();
                }
                _ => {}
            }
            app.new_job.clear_error();
            app.mark_dirty();
        }

        KeyCode::Char(c) => {
            match app.new_job.focused_field {
                NewJobField::Name => {
                    // Only allow valid characters
                    if c.is_alphanumeric() || c == '-' || c == '_' {
                        app.new_job.job_name.push(c);
                    }
                }
                NewJobField::MpiRanks => {
                    if c.is_ascii_digit() {
                        app.new_job.mpi_ranks.push(c);
                    }
                }
                NewJobField::Walltime => {
                    app.new_job.walltime.push(c);
                }
                NewJobField::Memory => {
                    app.new_job.memory_gb.push(c);
                }
                NewJobField::Cpus => {
                    app.new_job.cpus_per_task.push(c);
                }
                NewJobField::Nodes => {
                    app.new_job.nodes.push(c);
                }
                NewJobField::Partition => {
                    app.new_job.partition.push(c);
                }
                NewJobField::AuxGui if app.new_job.aux_gui_enabled => {
                    app.new_job.aux_gui_path.push(c);
                }
                NewJobField::AuxF9 if app.new_job.aux_f9_enabled => {
                    app.new_job.aux_f9_path.push(c);
                }
                NewJobField::AuxHessopt if app.new_job.aux_hessopt_enabled => {
                    app.new_job.aux_hessopt_path.push(c);
                }
                _ => {}
            }
            app.new_job.clear_error();
            app.mark_dirty();
        }

        // Arrow keys for field navigation
        KeyCode::Up => {
            app.new_job.focused_field = app.new_job.focused_field.prev();
            app.new_job.clear_error();
            app.mark_dirty();
        }
        KeyCode::Down => {
            app.new_job.focused_field = app.new_job.focused_field.next();
            app.new_job.clear_error();
            app.mark_dirty();
        }

        _ => {}
    }
}

/// Handle keyboard input for the cluster manager modal.
///
/// Key bindings (List mode):
/// - Esc: Close modal
/// - j/Down: Select next cluster
/// - k/Up: Select previous cluster
/// - a: Add new cluster
/// - e: Edit selected cluster
/// - d: Delete selected cluster
/// - t: Test connection to selected cluster
/// - r: Refresh cluster list
///
/// Key bindings (Add/Edit mode):
/// - Tab/Down: Next field
/// - Shift+Tab/Up: Previous field
/// - Enter: Save cluster
/// - Esc: Cancel (return to list)
/// - Space: Cycle options (for cluster type)
/// - Backspace: Delete character
/// - Other chars: Type into text fields
///
/// Key bindings (Delete confirm mode):
/// - y: Confirm delete
/// - n/Esc: Cancel delete
fn handle_cluster_manager_modal_input(app: &mut App, key: event::KeyEvent) {
    use crate::ui::{ClusterFormField, ClusterManagerMode};

    // Don't process input while loading
    if app.cluster_manager.loading {
        // Only allow Escape during loading
        if key.code == KeyCode::Esc {
            app.close_cluster_manager_modal();
        }
        return;
    }

    match app.cluster_manager.mode {
        ClusterManagerMode::List => {
            match key.code {
                // Close modal
                KeyCode::Esc => {
                    app.close_cluster_manager_modal();
                }

                // Navigation
                KeyCode::Char('j') | KeyCode::Down => {
                    app.cluster_manager.select_next();
                    app.cluster_manager.connection_result = None;
                    app.mark_dirty();
                }
                KeyCode::Char('k') | KeyCode::Up => {
                    app.cluster_manager.select_prev();
                    app.cluster_manager.connection_result = None;
                    app.mark_dirty();
                }

                // Actions
                KeyCode::Char('a') => {
                    app.cluster_manager.start_add();
                    app.mark_dirty();
                }
                KeyCode::Char('e') => {
                    if app.cluster_manager.selected_index.is_some() {
                        app.cluster_manager.start_edit();
                        app.mark_dirty();
                    }
                }
                KeyCode::Char('d') => {
                    if app.cluster_manager.selected_index.is_some() {
                        app.cluster_manager.start_delete();
                        app.mark_dirty();
                    }
                }
                KeyCode::Char('t') => {
                    app.test_selected_cluster_connection();
                }
                KeyCode::Char('r') => {
                    app.request_fetch_clusters();
                }

                _ => {}
            }
        }

        ClusterManagerMode::Add | ClusterManagerMode::Edit => {
            match key.code {
                // Cancel and return to list
                KeyCode::Esc => {
                    app.cluster_manager.cancel();
                    app.mark_dirty();
                }

                // Save cluster
                KeyCode::Enter => {
                    if app.cluster_manager.mode == ClusterManagerMode::Add {
                        app.create_cluster_from_form();
                    } else {
                        app.update_cluster_from_form();
                    }
                }

                // Navigate fields
                KeyCode::Tab | KeyCode::Down => {
                    app.cluster_manager.focused_field = app.cluster_manager.focused_field.next();
                    app.cluster_manager.error = None;
                    app.mark_dirty();
                }
                KeyCode::BackTab | KeyCode::Up => {
                    app.cluster_manager.focused_field = app.cluster_manager.focused_field.prev();
                    app.cluster_manager.error = None;
                    app.mark_dirty();
                }

                // Cycle cluster type
                KeyCode::Char(' ') => {
                    if app.cluster_manager.focused_field == ClusterFormField::ClusterType {
                        app.cluster_manager.form_cluster_type =
                            app.cluster_manager.form_cluster_type.cycle();
                        app.mark_dirty();
                    } else {
                        // Space in text fields adds a space (except for port/max_concurrent)
                        handle_cluster_form_char(app, ' ');
                    }
                }

                // Backspace
                KeyCode::Backspace => {
                    handle_cluster_form_backspace(app);
                }

                // Character input
                KeyCode::Char(c) => {
                    handle_cluster_form_char(app, c);
                }

                _ => {}
            }
        }

        ClusterManagerMode::ConfirmDelete => {
            match key.code {
                // Confirm delete
                KeyCode::Char('y') | KeyCode::Char('Y') => {
                    app.delete_selected_cluster();
                }

                // Cancel delete
                KeyCode::Char('n') | KeyCode::Char('N') | KeyCode::Esc => {
                    app.cluster_manager.cancel();
                    app.mark_dirty();
                }

                _ => {}
            }
        }
    }
}

/// Handle character input for cluster form text fields.
fn handle_cluster_form_char(app: &mut App, c: char) {
    use crate::ui::ClusterFormField;

    let field = match app.cluster_manager.focused_field {
        ClusterFormField::Name => &mut app.cluster_manager.form_name,
        ClusterFormField::Hostname => &mut app.cluster_manager.form_hostname,
        ClusterFormField::Port => {
            // Only allow digits for port
            if c.is_ascii_digit() {
                app.cluster_manager.form_port.push(c);
                app.mark_dirty();
            }
            return;
        }
        ClusterFormField::Username => &mut app.cluster_manager.form_username,
        ClusterFormField::KeyFile => &mut app.cluster_manager.form_key_file,
        ClusterFormField::RemoteWorkdir => &mut app.cluster_manager.form_remote_workdir,
        ClusterFormField::QueueName => &mut app.cluster_manager.form_queue_name,
        ClusterFormField::Cry23Root => &mut app.cluster_manager.form_cry23_root,
        ClusterFormField::VaspRoot => &mut app.cluster_manager.form_vasp_root,
        ClusterFormField::MaxConcurrent => {
            // Only allow digits for max concurrent
            if c.is_ascii_digit() {
                app.cluster_manager.form_max_concurrent.push(c);
                app.mark_dirty();
            }
            return;
        }
        ClusterFormField::ClusterType => return, // Handled by space key
    };

    field.push(c);
    app.cluster_manager.error = None;
    app.mark_dirty();
}

/// Handle backspace for cluster form text fields.
fn handle_cluster_form_backspace(app: &mut App) {
    use crate::ui::ClusterFormField;

    let field = match app.cluster_manager.focused_field {
        ClusterFormField::Name => &mut app.cluster_manager.form_name,
        ClusterFormField::Hostname => &mut app.cluster_manager.form_hostname,
        ClusterFormField::Port => &mut app.cluster_manager.form_port,
        ClusterFormField::Username => &mut app.cluster_manager.form_username,
        ClusterFormField::KeyFile => &mut app.cluster_manager.form_key_file,
        ClusterFormField::RemoteWorkdir => &mut app.cluster_manager.form_remote_workdir,
        ClusterFormField::QueueName => &mut app.cluster_manager.form_queue_name,
        ClusterFormField::Cry23Root => &mut app.cluster_manager.form_cry23_root,
        ClusterFormField::VaspRoot => &mut app.cluster_manager.form_vasp_root,
        ClusterFormField::MaxConcurrent => &mut app.cluster_manager.form_max_concurrent,
        ClusterFormField::ClusterType => return,
    };

    field.pop();
    app.cluster_manager.error = None;
    app.mark_dirty();
}

/// Handle keyboard input for the SLURM queue modal.
fn handle_slurm_queue_modal_input(app: &mut App, key: event::KeyEvent) {
    // Don't process input while loading (except Escape)
    if app.slurm_queue_state.loading {
        if key.code == KeyCode::Esc {
            app.close_slurm_queue_modal();
        }
        return;
    }

    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_slurm_queue_modal();
        }

        // Navigation
        KeyCode::Char('j') | KeyCode::Down => {
            let queue_len = app.slurm_queue.len();
            app.slurm_queue_state.select_next(queue_len);
            app.mark_dirty();
        }
        KeyCode::Char('k') | KeyCode::Up => {
            let queue_len = app.slurm_queue.len();
            app.slurm_queue_state.select_prev(queue_len);
            app.mark_dirty();
        }

        // Refresh queue
        KeyCode::Char('r') => {
            app.refresh_slurm_queue();
        }

        // Adopt selected job
        KeyCode::Char('a') => {
            if app
                .slurm_queue_state
                .selected_entry(&app.slurm_queue)
                .is_some()
            {
                app.adopt_selected_slurm_job();
            }
        }

        // Cancel selected job
        KeyCode::Char('c') => {
            if app
                .slurm_queue_state
                .selected_entry(&app.slurm_queue)
                .is_some()
            {
                app.cancel_selected_slurm_job_from_modal();
            }
        }

        _ => {}
    }
}

/// Handle keyboard input for the VASP input modal.
///
/// Key bindings:
/// - Esc: Close modal
/// - Tab: Next file tab
/// - Shift+Tab (BackTab): Previous file tab
/// - Ctrl+S: Submit VASP job
/// - Text input: Forward to current TextArea editor (for POSCAR, INCAR, KPOINTS)
/// - Character input: Type into POTCAR config (when POTCAR tab is active)
fn handle_vasp_input_modal_input(app: &mut App, key: event::KeyEvent) {
    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_vasp_input_modal();
        }

        // Submit VASP job
        KeyCode::Char('s') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.submit_vasp_job();
        }

        // Validate VASP inputs
        KeyCode::Char('v') if key.modifiers.is_empty() => {
            app.request_validate_vasp_inputs();
        }

        // Navigate between file tabs
        KeyCode::Tab => {
            app.vasp_input_state.next_tab();
            app.mark_dirty();
        }
        KeyCode::BackTab => {
            app.vasp_input_state.prev_tab();
            app.mark_dirty();
        }

        // Handle text input based on current tab
        _ => {
            use crate::ui::VaspFileTab;

            match app.vasp_input_state.current_tab {
                VaspFileTab::Poscar | VaspFileTab::Incar | VaspFileTab::Kpoints => {
                    // Forward to TextArea editor
                    if let Some(editor) = app.vasp_input_state.current_editor_mut() {
                        if editor.input(key) {
                            app.vasp_input_state.clear_messages();
                            app.mark_dirty();
                        }
                    }
                }
                VaspFileTab::Potcar => {
                    // Handle simple text input for POTCAR config
                    match key.code {
                        KeyCode::Char(c) => {
                            app.vasp_input_state.potcar_config.push(c);
                            app.vasp_input_state.clear_messages();
                            app.mark_dirty();
                        }
                        KeyCode::Backspace => {
                            app.vasp_input_state.potcar_config.pop();
                            app.vasp_input_state.clear_messages();
                            app.mark_dirty();
                        }
                        _ => {}
                    }
                }
            }
        }
    }
}

/// Handle keyboard input for the recipe browser modal.
///
/// Key bindings:
/// - Esc: Close modal
/// - j/Down: Select next recipe
/// - k/Up: Select previous recipe
/// - r: Refresh recipes
fn handle_recipe_browser_input(app: &mut App, key: event::KeyEvent) {
    // Don't process input while loading (except Escape)
    if app.recipe_browser.loading {
        if key.code == KeyCode::Esc {
            app.close_recipe_browser();
        }
        return;
    }

    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_recipe_browser();
        }

        // Navigation
        KeyCode::Char('j') | KeyCode::Down => {
            app.select_next_recipe();
            app.mark_dirty();
        }
        KeyCode::Char('k') | KeyCode::Up => {
            app.select_prev_recipe();
            app.mark_dirty();
        }

        // Refresh recipes
        KeyCode::Char('r') => {
            app.refresh_recipes();
        }

        _ => {}
    }
}

/// Handle keyboard input for the workflow launcher modal.
///
/// Key bindings:
/// - Esc: Close modal
/// - j/Down: Select next workflow
/// - k/Up: Select previous workflow
/// - Enter: Open workflow config
fn handle_workflow_modal_input(app: &mut App, key: event::KeyEvent) {
    // Don't process input while loading (except Escape)
    if app.workflow_state.loading {
        if key.code == KeyCode::Esc {
            app.close_workflow_modal();
        }
        return;
    }

    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_workflow_modal();
        }

        // Navigation
        KeyCode::Char('j') | KeyCode::Down => {
            app.select_next_workflow();
            app.mark_dirty();
        }
        KeyCode::Char('k') | KeyCode::Up => {
            app.select_prev_workflow();
            app.mark_dirty();
        }

        // Open workflow config
        KeyCode::Enter => {
            if app.workflow_state.workflows_available {
                let workflow_type = app.workflow_state.selected_workflow();
                app.open_workflow_config_modal(workflow_type);
            } else {
                app.workflow_state
                    .set_status("Workflows not available".to_string(), true);
            }
            app.mark_dirty();
        }

        _ => {}
    }
}

/// Handle keyboard input for the workflow config modal.
///
/// Key bindings:
/// - Esc: Close modal
/// - Tab/Shift+Tab: Next/Previous field
/// - Space: Cycle dropdowns
/// - Enter: Launch (or insert newline for base input)
/// - Backspace/Chars: Edit active field
fn handle_workflow_config_input(app: &mut App, key: event::KeyEvent) {
    let focused = app.workflow_config.focused_field;

    // Don't process input while submitting (except Escape)
    if app.workflow_config.submitting {
        if key.code == KeyCode::Esc {
            app.close_workflow_config_modal();
        }
        return;
    }

    match key.code {
        KeyCode::Esc => {
            app.close_workflow_config_modal();
        }
        KeyCode::Tab => {
            app.workflow_config.focus_next();
            app.workflow_config.error = None;
            app.workflow_config.status = None;
            app.mark_dirty();
        }
        KeyCode::BackTab => {
            app.workflow_config.focus_prev();
            app.workflow_config.error = None;
            app.workflow_config.status = None;
            app.mark_dirty();
        }
        KeyCode::Enter => {
            if focused == WorkflowConfigField::ConvergenceBaseInput {
                if app.workflow_config.convergence.base_input.input(key) {
                    app.mark_dirty();
                }
                return;
            }

            if focused == WorkflowConfigField::BtnCancel {
                app.close_workflow_config_modal();
            } else {
                app.launch_selected_workflow();
            }
            app.mark_dirty();
        }
        KeyCode::Backspace => {
            if focused == WorkflowConfigField::ConvergenceBaseInput {
                if app.workflow_config.convergence.base_input.input(key) {
                    app.mark_dirty();
                }
                return;
            }

            match focused {
                WorkflowConfigField::ConvergenceValues => {
                    app.workflow_config.convergence.values.pop();
                }
                WorkflowConfigField::BandSourceJob => {
                    app.workflow_config.band_structure.source_job_pk.pop();
                }
                WorkflowConfigField::BandCustomPath => {
                    app.workflow_config.band_structure.custom_path.pop();
                }
                WorkflowConfigField::PhononSourceJob => {
                    app.workflow_config.phonon.source_job_pk.pop();
                }
                WorkflowConfigField::PhononSupercellA => {
                    app.workflow_config.phonon.supercell_a.pop();
                }
                WorkflowConfigField::PhononSupercellB => {
                    app.workflow_config.phonon.supercell_b.pop();
                }
                WorkflowConfigField::PhononSupercellC => {
                    app.workflow_config.phonon.supercell_c.pop();
                }
                WorkflowConfigField::PhononDisplacement => {
                    app.workflow_config.phonon.displacement.pop();
                }
                WorkflowConfigField::EosSourceJob => {
                    app.workflow_config.eos.source_job_pk.pop();
                }
                WorkflowConfigField::EosStrainMin => {
                    app.workflow_config.eos.strain_min.pop();
                }
                WorkflowConfigField::EosStrainMax => {
                    app.workflow_config.eos.strain_max.pop();
                }
                WorkflowConfigField::EosStrainSteps => {
                    app.workflow_config.eos.strain_steps.pop();
                }
                WorkflowConfigField::GeomStructurePk => {
                    app.workflow_config.geometry_opt.structure_pk.pop();
                }
                WorkflowConfigField::GeomCodeLabel => {
                    app.workflow_config.geometry_opt.code_label.pop();
                }
                WorkflowConfigField::GeomFmax => {
                    app.workflow_config.geometry_opt.fmax.pop();
                }
                WorkflowConfigField::GeomMaxSteps => {
                    app.workflow_config.geometry_opt.max_steps.pop();
                }
                _ => {}
            }
            app.workflow_config.error = None;
            app.workflow_config.status = None;
            app.mark_dirty();
        }
        KeyCode::Char(c) => {
            if focused == WorkflowConfigField::ConvergenceBaseInput {
                if app.workflow_config.convergence.base_input.input(key) {
                    app.mark_dirty();
                }
                return;
            }

            let allow_float = |ch: char| ch.is_ascii_digit() || matches!(ch, '.' | '-' | 'e' | 'E');
            let allow_values = |ch: char| {
                ch.is_ascii_digit() || matches!(ch, '.' | '-' | 'e' | 'E' | ',' | ' ')
            };

            if c == ' ' {
                match focused {
                    WorkflowConfigField::ConvergenceParameter => {
                        app.workflow_config.convergence.parameter =
                            app.workflow_config.convergence.parameter.next();
                        app.workflow_config.error = None;
                        app.workflow_config.status = None;
                        app.mark_dirty();
                        return;
                    }
                    WorkflowConfigField::BandPathPreset => {
                        app.workflow_config.band_structure.path_preset =
                            app.workflow_config.band_structure.path_preset.next();
                        app.workflow_config.error = None;
                        app.workflow_config.status = None;
                        app.mark_dirty();
                        return;
                    }
                    _ => {}
                }
            }

            match focused {
                WorkflowConfigField::ConvergenceValues => {
                    if allow_values(c) {
                        app.workflow_config.convergence.values.push(c);
                    }
                }
                WorkflowConfigField::BandSourceJob => {
                    if c.is_ascii_digit() {
                        app.workflow_config.band_structure.source_job_pk.push(c);
                    }
                }
                WorkflowConfigField::BandCustomPath => {
                    if !c.is_control() {
                        app.workflow_config.band_structure.custom_path.push(c);
                    }
                }
                WorkflowConfigField::PhononSourceJob => {
                    if c.is_ascii_digit() {
                        app.workflow_config.phonon.source_job_pk.push(c);
                    }
                }
                WorkflowConfigField::PhononSupercellA => {
                    if c.is_ascii_digit() {
                        app.workflow_config.phonon.supercell_a.push(c);
                    }
                }
                WorkflowConfigField::PhononSupercellB => {
                    if c.is_ascii_digit() {
                        app.workflow_config.phonon.supercell_b.push(c);
                    }
                }
                WorkflowConfigField::PhononSupercellC => {
                    if c.is_ascii_digit() {
                        app.workflow_config.phonon.supercell_c.push(c);
                    }
                }
                WorkflowConfigField::PhononDisplacement => {
                    if allow_float(c) {
                        app.workflow_config.phonon.displacement.push(c);
                    }
                }
                WorkflowConfigField::EosSourceJob => {
                    if c.is_ascii_digit() {
                        app.workflow_config.eos.source_job_pk.push(c);
                    }
                }
                WorkflowConfigField::EosStrainMin => {
                    if allow_float(c) {
                        app.workflow_config.eos.strain_min.push(c);
                    }
                }
                WorkflowConfigField::EosStrainMax => {
                    if allow_float(c) {
                        app.workflow_config.eos.strain_max.push(c);
                    }
                }
                WorkflowConfigField::EosStrainSteps => {
                    if c.is_ascii_digit() {
                        app.workflow_config.eos.strain_steps.push(c);
                    }
                }
                WorkflowConfigField::GeomStructurePk => {
                    if c.is_ascii_digit() {
                        app.workflow_config.geometry_opt.structure_pk.push(c);
                    }
                }
                WorkflowConfigField::GeomCodeLabel => {
                    if !c.is_control() {
                        app.workflow_config.geometry_opt.code_label.push(c);
                    }
                }
                WorkflowConfigField::GeomFmax => {
                    if allow_float(c) {
                        app.workflow_config.geometry_opt.fmax.push(c);
                    }
                }
                WorkflowConfigField::GeomMaxSteps => {
                    if c.is_ascii_digit() {
                        app.workflow_config.geometry_opt.max_steps.push(c);
                    }
                }
                _ => {}
            }
            app.workflow_config.error = None;
            app.workflow_config.status = None;
            app.mark_dirty();
        }
        _ => {
            if focused == WorkflowConfigField::ConvergenceBaseInput {
                if app.workflow_config.convergence.base_input.input(key) {
                    app.mark_dirty();
                }
            }
        }
    }
}

/// Handle keyboard input for the template browser modal.
fn handle_template_browser_input(app: &mut App, key: event::KeyEvent) {
    // Don't process input while loading (except Escape)
    if app.template_browser.loading {
        if key.code == KeyCode::Esc {
            app.close_template_browser();
        }
        return;
    }

    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_template_browser();
        }

        // Navigation
        KeyCode::Char('j') | KeyCode::Down => {
            app.select_next_template();
            app.mark_dirty();
        }
        KeyCode::Char('k') | KeyCode::Up => {
            app.select_prev_template();
            app.mark_dirty();
        }

        // Enter: Render template (TODO: prompt for params)
        KeyCode::Enter => {
            if let Some(template) = app.template_browser.selected_template() {
                let name = template.name.clone();
                info!("Selected template: {}", name);
                // TODO: Show param input form or just render with defaults
                // For now, just close
                app.close_template_browser();
            }
        }

        _ => {}
    }
}

/// Handle keyboard input for the batch submission modal.
fn handle_batch_submission_input(app: &mut App, key: event::KeyEvent) {
    if app.batch_submission.submitting {
        return;
    }

    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_batch_submission();
        }

        // Navigate fields
        KeyCode::Tab => {
            app.batch_submission.focused_field = app.batch_submission.focused_field.next();
            app.mark_dirty();
        }
        KeyCode::BackTab => {
            app.batch_submission.focused_field = app.batch_submission.focused_field.prev();
            app.mark_dirty();
        }

        // Field-specific input
        KeyCode::Char('j') | KeyCode::Down if app.batch_submission.focused_field == BatchSubmissionField::JobList => {
            let len = app.batch_submission.jobs.len();
            if len > 0 {
                let i = match app.batch_submission.selected_job_index {
                    Some(i) if i >= len - 1 => 0,
                    Some(i) => i + 1,
                    None => 0,
                };
                app.batch_submission.selected_job_index = Some(i);
                app.mark_dirty();
            }
        }
        KeyCode::Char('k') | KeyCode::Up if app.batch_submission.focused_field == BatchSubmissionField::JobList => {
            let len = app.batch_submission.jobs.len();
            if len > 0 {
                let i = match app.batch_submission.selected_job_index {
                    Some(0) => len - 1,
                    Some(i) => i - 1,
                    None => 0,
                };
                app.batch_submission.selected_job_index = Some(i);
                app.mark_dirty();
            }
        }

        // Actions
        KeyCode::Char('a') => {
            app.add_current_editor_to_batch();
        }
        KeyCode::Char('d') => {
            app.batch_submission.remove_selected();
            app.mark_dirty();
        }
        KeyCode::Enter if app.batch_submission.focused_field == BatchSubmissionField::BtnSubmit => {
            app.submit_batch();
        }
        KeyCode::Enter if app.batch_submission.focused_field == BatchSubmissionField::BtnAdd => {
            app.add_current_editor_to_batch();
        }
        KeyCode::Enter if app.batch_submission.focused_field == BatchSubmissionField::BtnRemove => {
            app.batch_submission.remove_selected();
            app.mark_dirty();
        }
        KeyCode::Enter if app.batch_submission.focused_field == BatchSubmissionField::BtnCancel => {
            app.close_batch_submission();
        }

        _ => {}
    }
}

/// Handle keyboard input for the output file viewer modal.
///
/// Key bindings:
/// - Esc: Close modal
/// - j/k/Up/Down: Scroll line by line
/// - PgUp/PgDn: Scroll by page
/// - g/Home: Jump to top
/// - G/End: Jump to bottom
/// - 1/2/3: Switch file type (OUTCAR/vasprun.xml/OSZICAR)
/// - r: Refresh current file
fn handle_output_viewer_input(app: &mut App, key: event::KeyEvent) {
    // Don't process input while loading (except Escape)
    if app.output_viewer.loading {
        if key.code == KeyCode::Esc {
            app.close_output_viewer();
        }
        return;
    }

    // Calculate visible height (approximate based on modal size)
    let visible_height = 35_usize; // ~85% of typical terminal height minus chrome

    match key.code {
        // Close modal
        KeyCode::Esc => {
            app.close_output_viewer();
        }

        // Line scrolling
        KeyCode::Down | KeyCode::Char('j') => {
            app.output_viewer_scroll_down(visible_height);
        }
        KeyCode::Up | KeyCode::Char('k') => {
            app.output_viewer_scroll_up();
        }

        // Page scrolling
        KeyCode::PageDown => {
            app.output_viewer_page_down(visible_height);
        }
        KeyCode::PageUp => {
            app.output_viewer_page_up();
        }

        // Jump to top
        KeyCode::Home | KeyCode::Char('g') => {
            app.output_viewer_scroll_top();
        }

        // Jump to bottom
        KeyCode::End | KeyCode::Char('G') => {
            app.output_viewer_scroll_bottom(visible_height);
        }

        // Switch file type with number keys (if viewing a job)
        KeyCode::Char('1') => {
            if let Some(pk) = app.output_viewer.job_pk {
                let name = app.output_viewer.job_name.clone();
                app.open_output_viewer(OutputFileType::Outcar, pk, name);
            }
        }
        KeyCode::Char('2') => {
            if let Some(pk) = app.output_viewer.job_pk {
                let name = app.output_viewer.job_name.clone();
                app.open_output_viewer(OutputFileType::VasprunXml, pk, name);
            }
        }
        KeyCode::Char('3') => {
            if let Some(pk) = app.output_viewer.job_pk {
                let name = app.output_viewer.job_name.clone();
                app.open_output_viewer(OutputFileType::Oszicar, pk, name);
            }
        }

        // Refresh current file
        KeyCode::Char('r') => {
            if let Some(pk) = app.output_viewer.job_pk {
                let file_type = app.output_viewer.file_type;
                app.request_fetch_output_file(pk, file_type);
            }
        }

        _ => {}
    }
}

/// Handle keyboard input for the help modal.
fn handle_help_modal_input(app: &mut App, key: event::KeyEvent) {
    use crate::state::help::HelpPaneFocus;

    match key.code {
        // Close modal: Escape or '?'
        KeyCode::Esc | KeyCode::Char('?') => {
            app.close_help_modal();
        }

        // Navigate sidebar / scroll content
        KeyCode::Down | KeyCode::Char('j') => {
            app.help.select_next();
            app.mark_dirty();
        }
        KeyCode::Up | KeyCode::Char('k') => {
            app.help.select_prev();
            app.mark_dirty();
        }

        // Toggle focus between sidebar and content
        KeyCode::Tab => {
            app.help.toggle_focus();
            app.mark_dirty();
        }

        // Enter topic (drill in) - also 'l' for vim-style
        KeyCode::Enter | KeyCode::Char('l') if app.help.focus == HelpPaneFocus::Sidebar => {
            app.help.enter_topic();
            app.mark_dirty();
        }

        // Go back: Backspace or 'h' for vim-style
        KeyCode::Backspace | KeyCode::Char('h') => {
            app.help.go_back();
            app.mark_dirty();
        }

        // Page up/down for content scrolling
        KeyCode::PageUp => {
            app.help.page_up();
            app.mark_dirty();
        }
        KeyCode::PageDown => {
            app.help.page_down();
            app.mark_dirty();
        }

        // Home - go to root of help hierarchy
        KeyCode::Home => {
            app.help.go_to_root();
            app.mark_dirty();
        }

        _ => {}
    }
}
