//! Application state management.
//!
//! This module contains the central `App` struct that holds all application state,
//! and methods for state manipulation.

use std::sync::mpsc::{self, Receiver};

use pyo3::PyObject;
use tracing::{debug, info, warn};
use tui_textarea::TextArea;

use crate::bridge::{BridgeHandle, BridgeRequestKind, BridgeResponse};
use crate::lsp::{DftCodeType, Diagnostic, LspClient, LspEvent};
use crate::models::{JobDetails, JobStatus};

/// Application tabs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppTab {
    Jobs,
    Editor,
    Results,
    Log,
}

impl AppTab {
    /// Get tab display name.
    pub fn name(&self) -> &'static str {
        match self {
            AppTab::Jobs => "Jobs",
            AppTab::Editor => "Editor",
            AppTab::Results => "Results",
            AppTab::Log => "Log",
        }
    }

    /// Get all tabs in order.
    pub fn all() -> &'static [AppTab] {
        &[AppTab::Jobs, AppTab::Editor, AppTab::Results, AppTab::Log]
    }
}

/// Main application state.
pub struct App<'a> {
    /// Flag to exit the application.
    pub should_quit: bool,

    /// Currently active tab.
    pub current_tab: AppTab,

    /// Last non-fatal error message (displayed in status bar, auto-clears).
    pub last_error: Option<String>,

    /// Timestamp when last_error was set (for auto-clear after 5 seconds).
    last_error_time: Option<std::time::Instant>,

    /// Dirty flag - set when UI needs to be redrawn.
    /// Resets to false after each draw.
    needs_redraw: bool,

    // ===== Jobs Tab State =====
    /// List of jobs from backend.
    pub jobs: Vec<JobStatus>,

    /// Currently selected job index.
    pub selected_job_index: Option<usize>,

    // ===== Editor Tab State =====
    /// Text editor widget.
    pub editor: TextArea<'a>,

    /// Path of file being edited.
    pub editor_file_path: Option<String>,

    /// URI of file being edited (for LSP matching).
    pub editor_file_uri: Option<String>,

    /// DFT code type for the current file.
    pub editor_dft_code: Option<DftCodeType>,

    /// Editor document version (for LSP).
    pub editor_version: i32,

    /// LSP diagnostics for current file.
    pub lsp_diagnostics: Vec<Diagnostic>,

    // ===== Results Tab State =====
    /// Details of the selected job.
    pub current_job_details: Option<JobDetails>,

    /// Scroll offset for results view.
    pub results_scroll: usize,

    // ===== Log Tab State =====
    /// Log lines for the selected job.
    pub log_lines: Vec<String>,

    /// Scroll offset for log view.
    pub log_scroll: usize,

    // ===== Python Backend (Async Bridge) =====
    /// Handle to the Python bridge worker thread.
    bridge: BridgeHandle,

    /// Currently pending bridge request (for UI feedback and preventing duplicate requests).
    pub pending_bridge_request: Option<BridgeRequestKind>,

    // ===== LSP Integration =====
    /// LSP client for dft-language-server.
    pub lsp_client: Option<LspClient>,

    /// Receiver for LSP events.
    pub lsp_receiver: Receiver<LspEvent>,

    /// Timestamp of last editor change (for LSP debounce).
    last_editor_change: Option<std::time::Instant>,

    /// Whether there are pending LSP changes to flush.
    pending_lsp_change: bool,
}

impl<'a> App<'a> {
    /// Default path to the dft-language-server.
    const LSP_SERVER_PATH: &'static str = "./dft-language-server/out/server.js";

    /// Create a new application with the Python controller.
    ///
    /// Spawns a worker thread that owns the PyObject and handles all
    /// Python calls asynchronously via channels.
    pub fn new(py_controller: PyObject) -> Self {
        // Spawn the async bridge worker thread
        let bridge = BridgeHandle::spawn(py_controller)
            .expect("Failed to spawn Python bridge worker");

        let mut editor = TextArea::default();
        editor.set_line_number_style(
            ratatui::style::Style::default().fg(ratatui::style::Color::DarkGray),
        );

        // Create channel for LSP events
        let (lsp_tx, lsp_rx) = mpsc::channel();

        // Try to start the LSP server (graceful degradation if unavailable)
        let lsp_client = match LspClient::start(Self::LSP_SERVER_PATH, lsp_tx) {
            Ok(client) => {
                info!("LSP server started successfully");
                Some(client)
            }
            Err(e) => {
                warn!("Failed to start LSP server: {}. Editor will work without validation.", e);
                None
            }
        };

        Self {
            should_quit: false,
            current_tab: AppTab::Jobs,
            last_error: None,
            last_error_time: None,
            needs_redraw: true, // Initial draw required
            jobs: Vec::new(),
            selected_job_index: None,
            editor,
            editor_file_path: None,
            editor_file_uri: None,
            editor_dft_code: None,
            editor_version: 1,
            lsp_diagnostics: Vec::new(),
            current_job_details: None,
            results_scroll: 0,
            log_lines: Vec::new(),
            log_scroll: 0,
            bridge,
            pending_bridge_request: None,
            lsp_client,
            lsp_receiver: lsp_rx,
            last_editor_change: None,
            pending_lsp_change: false,
        }
    }

    // ===== Dirty Flag (Rendering Optimization) =====

    /// Mark UI as needing redraw.
    pub fn mark_dirty(&mut self) {
        self.needs_redraw = true;
    }

    /// Check if redraw is needed and reset the flag.
    pub fn take_needs_redraw(&mut self) -> bool {
        std::mem::take(&mut self.needs_redraw)
    }

    /// Check if redraw is needed without resetting.
    pub fn needs_redraw(&self) -> bool {
        self.needs_redraw
    }

    // ===== Error Handling =====

    /// Set a non-fatal error to display in the UI.
    /// Errors auto-clear after 5 seconds.
    pub fn set_error(&mut self, message: impl Into<String>) {
        self.last_error = Some(message.into());
        self.last_error_time = Some(std::time::Instant::now());
        self.mark_dirty();
    }

    /// Clear the current error.
    pub fn clear_error(&mut self) {
        if self.last_error.is_some() {
            self.last_error = None;
            self.last_error_time = None;
            self.mark_dirty();
        }
    }

    /// Check if error should auto-clear (after 5 seconds).
    pub fn maybe_clear_error(&mut self) {
        const ERROR_DISPLAY_DURATION: std::time::Duration = std::time::Duration::from_secs(5);

        if let Some(error_time) = self.last_error_time {
            if error_time.elapsed() > ERROR_DISPLAY_DURATION {
                self.clear_error();
            }
        }
    }

    // ===== Tab Navigation =====

    /// Move to the next tab.
    pub fn next_tab(&mut self) {
        self.current_tab = match self.current_tab {
            AppTab::Jobs => AppTab::Editor,
            AppTab::Editor => AppTab::Results,
            AppTab::Results => AppTab::Log,
            AppTab::Log => AppTab::Jobs,
        };
        self.mark_dirty();
    }

    /// Move to the previous tab.
    pub fn prev_tab(&mut self) {
        self.current_tab = match self.current_tab {
            AppTab::Jobs => AppTab::Log,
            AppTab::Editor => AppTab::Jobs,
            AppTab::Results => AppTab::Editor,
            AppTab::Log => AppTab::Results,
        };
        self.mark_dirty();
    }

    /// Set the current tab directly.
    pub fn set_tab(&mut self, tab: AppTab) {
        if self.current_tab != tab {
            self.current_tab = tab;
            self.mark_dirty();
        }
    }

    // ===== Jobs Management (Async Bridge) =====

    /// Request a job list refresh (non-blocking).
    ///
    /// The actual fetch happens on the worker thread. Results are
    /// delivered via `poll_bridge_responses()`.
    pub fn request_refresh_jobs(&mut self) {
        if self.pending_bridge_request.is_some() {
            // Already have a pending request - skip to avoid queue buildup
            return;
        }

        match self.bridge.request_fetch_jobs() {
            Ok(()) => {
                self.pending_bridge_request = Some(BridgeRequestKind::FetchJobs);
            }
            Err(e) => {
                self.set_error(format!("Failed to request jobs: {}", e));
            }
        }
    }

    /// Request job details for a specific job (non-blocking).
    ///
    /// The actual fetch happens on the worker thread. Results are
    /// delivered via `poll_bridge_responses()`.
    pub fn request_job_details(&mut self, pk: i32) {
        if self.pending_bridge_request.is_some() {
            return;
        }

        match self.bridge.request_fetch_job_details(pk) {
            Ok(()) => {
                self.pending_bridge_request = Some(BridgeRequestKind::FetchJobDetails);
            }
            Err(e) => {
                self.set_error(format!("Failed to request job details: {}", e));
            }
        }
    }

    /// Poll for bridge responses and update state (non-blocking).
    ///
    /// Call this each frame to receive results from async Python operations.
    pub fn poll_bridge_responses(&mut self) {
        while let Some(response) = self.bridge.poll_response() {
            self.pending_bridge_request = None;

            match response {
                BridgeResponse::Jobs(result) => {
                    match result {
                        Ok(jobs) => {
                            self.jobs = jobs;
                            // Adjust selection if needed
                            if !self.jobs.is_empty() {
                                if self.selected_job_index.is_none() {
                                    self.selected_job_index = Some(0);
                                } else if let Some(idx) = self.selected_job_index {
                                    if idx >= self.jobs.len() {
                                        self.selected_job_index = Some(self.jobs.len() - 1);
                                    }
                                }
                            } else {
                                self.selected_job_index = None;
                            }
                            self.clear_error();
                        }
                        Err(e) => {
                            self.set_error(format!("Failed to fetch jobs: {}", e));
                        }
                    }
                }
                BridgeResponse::JobDetails(result) => {
                    match result {
                        Ok(details) => {
                            self.current_job_details = details;
                            self.results_scroll = 0;
                            if let Some(ref d) = self.current_job_details {
                                self.log_lines = d.stdout_tail.clone();
                                self.log_scroll = 0;
                            }
                            self.clear_error();
                        }
                        Err(e) => {
                            self.set_error(format!("Failed to fetch job details: {}", e));
                        }
                    }
                }
                BridgeResponse::JobSubmitted(result) => {
                    match result {
                        Ok(pk) => {
                            info!("Job submitted with pk: {}", pk);
                            self.clear_error();
                            // Trigger a refresh to show the new job
                            self.request_refresh_jobs();
                        }
                        Err(e) => {
                            self.set_error(format!("Failed to submit job: {}", e));
                        }
                    }
                }
                BridgeResponse::JobCancelled(result) => {
                    match result {
                        Ok(success) => {
                            if success {
                                info!("Job cancelled successfully");
                                self.clear_error();
                                // Trigger a refresh to update status
                                self.request_refresh_jobs();
                            } else {
                                self.set_error("Failed to cancel job");
                            }
                        }
                        Err(e) => {
                            self.set_error(format!("Failed to cancel job: {}", e));
                        }
                    }
                }
                BridgeResponse::JobLog(result) => {
                    match result {
                        Ok(log) => {
                            self.log_lines = log.stdout;
                            self.log_scroll = 0;
                            self.clear_error();
                        }
                        Err(e) => {
                            self.set_error(format!("Failed to fetch job log: {}", e));
                        }
                    }
                }
            }
            self.mark_dirty();
        }
    }

    /// Convenience method that triggers an async job refresh.
    /// Kept for backwards compatibility with existing call sites.
    pub fn try_refresh_jobs(&mut self) {
        self.request_refresh_jobs();
    }

    /// Get the currently selected job.
    pub fn selected_job(&self) -> Option<&JobStatus> {
        self.selected_job_index.and_then(|idx| self.jobs.get(idx))
    }

    /// Select the previous job in the list.
    pub fn select_prev_job(&mut self) {
        if let Some(idx) = self.selected_job_index {
            if idx > 0 {
                self.selected_job_index = Some(idx - 1);
                self.mark_dirty();
            }
        }
    }

    /// Select the next job in the list.
    pub fn select_next_job(&mut self) {
        if let Some(idx) = self.selected_job_index {
            if idx + 1 < self.jobs.len() {
                self.selected_job_index = Some(idx + 1);
                self.mark_dirty();
            }
        }
    }

    /// Select the first job.
    pub fn select_first_job(&mut self) {
        if !self.jobs.is_empty() && self.selected_job_index != Some(0) {
            self.selected_job_index = Some(0);
            self.mark_dirty();
        }
    }

    /// Select the last job.
    pub fn select_last_job(&mut self) {
        let last = self.jobs.len().saturating_sub(1);
        if !self.jobs.is_empty() && self.selected_job_index != Some(last) {
            self.selected_job_index = Some(last);
            self.mark_dirty();
        }
    }

    /// Load job details with non-fatal error handling (async).
    ///
    /// This is a convenience wrapper around `request_job_details`.
    pub fn try_load_job_details(&mut self, pk: i32) {
        self.request_job_details(pk);
    }

    // ===== Results Scrolling =====

    /// Get the content length for results view (number of lines in job details).
    /// This matches the content rendered in src/ui/results.rs.
    fn results_content_length(&self) -> usize {
        self.current_job_details
            .as_ref()
            .map(|details| {
                let mut lines = 0;
                // Base lines always present
                lines += 1; // Job name
                lines += 1; // Status
                lines += 1; // Empty separator
                lines += 1; // === Results === header
                lines += 1; // Final Energy
                lines += 1; // Band Gap
                lines += 1; // Convergence

                // Optional fields
                if details.scf_cycles.is_some() {
                    lines += 1;
                }
                if details.wall_time_seconds.is_some() {
                    lines += 1;
                }

                // Warnings section
                if !details.warnings.is_empty() {
                    lines += 1; // Empty separator
                    lines += 1; // === Warnings === header
                    lines += details.warnings.len();
                }

                // Errors section
                if !details.errors.is_empty() {
                    lines += 1; // Empty separator
                    lines += 1; // === Errors === header
                    lines += details.errors.len();
                }

                lines
            })
            .unwrap_or(0)
    }

    pub fn scroll_results_up(&mut self) {
        if self.results_scroll > 0 {
            self.results_scroll -= 1;
            self.mark_dirty();
        }
    }

    pub fn scroll_results_down(&mut self) {
        let max_scroll = self.results_content_length().saturating_sub(1);
        if self.results_scroll < max_scroll {
            self.results_scroll += 1;
            self.mark_dirty();
        }
    }

    pub fn scroll_results_page_up(&mut self) {
        let old = self.results_scroll;
        self.results_scroll = self.results_scroll.saturating_sub(10);
        if old != self.results_scroll {
            self.mark_dirty();
        }
    }

    pub fn scroll_results_page_down(&mut self) {
        let max_scroll = self.results_content_length().saturating_sub(1);
        let new_scroll = (self.results_scroll + 10).min(max_scroll);
        if new_scroll != self.results_scroll {
            self.results_scroll = new_scroll;
            self.mark_dirty();
        }
    }

    // ===== Log Scrolling =====

    /// Calculate the maximum scroll offset for the log view.
    /// Uses a conservative estimate for visible height since actual viewport
    /// size is only known at render time. The render function will clamp
    /// to the actual max based on the real area.height.
    fn log_max_scroll(&self) -> usize {
        // Estimate visible height as 20 lines (conservative default)
        // Actual clamping happens in ui/log.rs with real area.height
        const ESTIMATED_VISIBLE_HEIGHT: usize = 20;
        self.log_lines.len().saturating_sub(ESTIMATED_VISIBLE_HEIGHT)
    }

    pub fn scroll_log_up(&mut self) {
        if self.log_scroll > 0 {
            self.log_scroll -= 1;
            self.mark_dirty();
        }
    }

    pub fn scroll_log_down(&mut self) {
        let max = self.log_max_scroll();
        if self.log_scroll < max {
            self.log_scroll += 1;
            self.mark_dirty();
        }
    }

    pub fn scroll_log_page_up(&mut self) {
        let old = self.log_scroll;
        self.log_scroll = self.log_scroll.saturating_sub(10);
        if old != self.log_scroll {
            self.mark_dirty();
        }
    }

    pub fn scroll_log_page_down(&mut self) {
        let old = self.log_scroll;
        let max = self.log_max_scroll();
        self.log_scroll = (self.log_scroll + 10).min(max);
        if old != self.log_scroll {
            self.mark_dirty();
        }
    }

    pub fn scroll_log_top(&mut self) {
        if self.log_scroll != 0 {
            self.log_scroll = 0;
            self.mark_dirty();
        }
    }

    pub fn scroll_log_bottom(&mut self) {
        let max = self.log_max_scroll();
        if self.log_scroll != max {
            self.log_scroll = max;
            self.mark_dirty();
        }
    }

    // ===== Editor =====

    /// Open a file in the editor with LSP support.
    pub fn open_file(&mut self, path: &str, content: &str) {
        // Close previous file in LSP if any
        if let (Some(ref mut client), Some(ref old_path)) =
            (&mut self.lsp_client, &self.editor_file_path)
        {
            if let Err(e) = client.did_close(old_path) {
                debug!("Failed to close previous file in LSP: {}", e);
            }
        }

        // Setup editor
        self.editor = TextArea::from(content.lines());
        self.editor.set_line_number_style(
            ratatui::style::Style::default().fg(ratatui::style::Color::DarkGray),
        );
        self.editor_file_path = Some(path.to_string());
        self.editor_file_uri = Some(LspClient::path_to_uri(path));
        self.editor_dft_code = DftCodeType::from_filename(path);
        self.editor_version = 1;
        self.lsp_diagnostics.clear();
        self.mark_dirty();

        // Notify LSP of new file
        if let Some(ref mut client) = self.lsp_client {
            if let Err(e) = client.did_open(path, content) {
                warn!("Failed to notify LSP of file open: {}", e);
            } else {
                debug!(
                    "LSP notified of file open: {} (type: {:?})",
                    path, self.editor_dft_code
                );
            }
        }
    }

    /// Notify LSP of editor content changes (debounced).
    /// Sets a timestamp and flag; actual LSP notification is sent by `tick()`.
    pub fn on_editor_change(&mut self) {
        self.mark_dirty(); // Editor content changed
        self.editor_version += 1;
        self.last_editor_change = Some(std::time::Instant::now());
        self.pending_lsp_change = true;
    }

    /// Called each frame to handle time-based updates.
    /// Currently handles LSP debounce - flushes changes after 200ms.
    pub fn tick(&mut self) {
        const LSP_DEBOUNCE_MS: u128 = 200;

        if self.pending_lsp_change {
            if let Some(change_time) = self.last_editor_change {
                if change_time.elapsed().as_millis() >= LSP_DEBOUNCE_MS {
                    self.flush_lsp_change();
                }
            }
        }
    }

    /// Send pending LSP change notification.
    fn flush_lsp_change(&mut self) {
        self.pending_lsp_change = false;
        self.last_editor_change = None;

        if let (Some(ref mut client), Some(ref path)) =
            (&mut self.lsp_client, &self.editor_file_path)
        {
            let content = self.editor.lines().join("\n");
            if let Err(e) = client.did_change(path, self.editor_version, &content) {
                debug!("Failed to notify LSP of change: {}", e);
            }
        }
    }

    /// Get the current editor content.
    pub fn editor_content(&self) -> String {
        self.editor.lines().join("\n")
    }

    /// Process pending LSP events (non-blocking).
    /// Returns true if any events were processed (UI may need redraw).
    pub fn poll_lsp_events(&mut self) {
        while let Ok(event) = self.lsp_receiver.try_recv() {
            match event {
                LspEvent::Diagnostics(uri, diags) => {
                    // Only update if diagnostics are for current file (exact URI match)
                    if let Some(ref current_uri) = self.editor_file_uri {
                        if &uri == current_uri {
                            debug!("Received {} diagnostics for {}", diags.len(), uri);
                            self.lsp_diagnostics = diags;
                            self.mark_dirty();
                        } else {
                            debug!(
                                "Ignoring diagnostics for {} (current: {})",
                                uri, current_uri
                            );
                        }
                    }
                }
                LspEvent::ServerReady => {
                    info!("LSP server ready");
                    self.mark_dirty();

                    // Send initialized notification (required by LSP spec)
                    if let Some(ref mut client) = self.lsp_client {
                        if let Err(e) = client.send_initialized() {
                            warn!("Failed to send initialized notification: {}", e);
                        }
                    }

                    // Re-open current file if any
                    if let Some(path) = self.editor_file_path.clone() {
                        let content = self.editor.lines().join("\n");
                        if let Some(ref mut client) = self.lsp_client {
                            let _ = client.did_open(&path, &content);
                        }
                    }
                }
                LspEvent::ServerError(err) => {
                    warn!("LSP server error: {}. Disabling LSP.", err);
                    // Disable LSP client and clear diagnostics
                    self.lsp_client = None;
                    self.lsp_diagnostics.clear();
                    self.mark_dirty();
                }
            }
        }
    }
}
