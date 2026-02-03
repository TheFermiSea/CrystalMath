//! Application state management.
//!
//! This module contains the central `App` struct that holds all application state,
//! and methods for state manipulation.

use std::sync::mpsc::{self, Receiver};

use anyhow::Context;
use pyo3::{Py, PyAny};
use tracing::{debug, error, info, warn};
use tui_textarea::TextArea;

use crate::bridge::{BridgeHandle, BridgeRequestKind, BridgeResponse, BridgeService};
use crate::lsp::{DftCodeType, Diagnostic, LspClient, LspEvent, LspService};
use crate::models::{ApiResponse, JobDetails, JobStatus, SlurmQueueEntry};
use crate::ui::{ClusterManagerState, RecipeBrowserState, SlurmQueueState};

use tachyonfx::{fx, Effect};

// Re-export state types for backward compatibility with existing imports from crate::app
pub use crate::state::{
    Action, AppTab, BatchSubmissionState, JobsState, MaterialsSearchState, NewJobField,
    NewJobState, TemplateBrowserState,
};

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
    /// Jobs state (extracted domain state).
    pub jobs_state: JobsState,

    // ===== SLURM Queue State =====
    /// SLURM queue entries from remote cluster.
    #[allow(dead_code)] // Planned for SLURM integration
    pub slurm_queue: Vec<SlurmQueueEntry>,

    /// Whether SLURM queue view is active.
    pub slurm_view_active: bool,

    /// Request ID for the current SLURM queue fetch (to ignore stale responses).
    pub slurm_request_id: usize,

    /// Selected index in SLURM queue table.
    #[allow(dead_code)] // Planned for SLURM integration
    pub slurm_selected: Option<usize>,

    /// Timestamp of last SLURM queue refresh.
    #[allow(dead_code)] // Planned for SLURM integration
    pub last_slurm_refresh: Option<std::time::Instant>,

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

    /// Job PK currently being viewed in log tab.
    pub log_job_pk: Option<i32>,

    /// Job name currently being viewed in log tab (for display).
    pub log_job_name: Option<String>,

    /// Whether log follow mode is active (auto-refresh every 2s).
    pub log_follow_mode: bool,

    /// Timestamp of last log refresh (for follow mode timing).
    last_log_refresh: Option<std::time::Instant>,

    // ===== Python Backend (Async Bridge) =====
    /// Handle to the Python bridge worker thread.
    ///
    /// Uses `Box<dyn BridgeService>` for dependency injection and testing.
    bridge: Box<dyn BridgeService>,

    /// Monotonically increasing counter for generating unique request IDs.
    /// Used to correlate requests with responses and detect stale responses.
    next_request_id: usize,

    /// Currently pending bridge request (for UI feedback and preventing duplicate requests).
    pub pending_bridge_request: Option<BridgeRequestKind>,

    /// Request ID of the current pending bridge request.
    /// Responses with a different ID are considered stale and ignored.
    pending_request_id: Option<usize>,

    /// Timestamp when the pending request was initiated (for timeout detection).
    pending_bridge_request_time: Option<std::time::Instant>,

    // ===== LSP Integration =====
    /// LSP client for dft-language-server.
    ///
    /// Uses `Box<dyn LspService>` for dependency injection and testing.
    pub lsp_client: Option<Box<dyn LspService>>,

    /// Receiver for LSP events.
    pub lsp_receiver: Receiver<LspEvent>,

    /// Timestamp of last editor change (for LSP debounce).
    last_editor_change: Option<std::time::Instant>,

    /// Whether there are pending LSP changes to flush.
    pending_lsp_change: bool,

    // ===== Materials Project Search Modal =====
    /// State for the materials search modal.
    pub materials: MaterialsSearchState<'a>,

    // ===== New Job Modal =====
    /// State for the new job creation modal.
    pub new_job: NewJobState,

    // ===== Cluster Manager Modal =====
    /// State for the cluster manager modal.
    pub cluster_manager: ClusterManagerState,

    // ===== SLURM Queue Modal =====
    /// State for the SLURM queue modal.
    pub slurm_queue_state: SlurmQueueState,

    /// Last SLURM cluster ID used (for 's' hotkey preference).
    pub last_slurm_cluster_id: Option<i32>,

    // ===== VASP Input Modal =====
    /// State for the VASP multi-file input modal.
    pub vasp_input_state: crate::ui::VaspInputState,

    // ===== Workflow Launcher Modal =====
    /// State for the workflow launcher modal.
    pub workflow_state: crate::ui::WorkflowState,

    // ===== Recipe Browser Modal =====
    /// State for the quacc recipe browser modal.
    pub recipe_browser: RecipeBrowserState,

    // ===== Template Browser Modal =====
    /// State for the calculation template browser modal.
    pub template_browser: TemplateBrowserState,

    // ===== Batch Submission Modal =====
    /// State for the batch job submission modal.
    pub batch_submission: BatchSubmissionState,

    /// Request ID for the current recipe fetch (to ignore stale responses).
    pub recipe_request_id: usize,

    /// Request ID for the current workflow availability check.
    pub workflow_request_id: usize,

    /// Request ID for the current VASP generation (to ignore stale responses).
    pub vasp_request_id: usize,

    // ===== quacc Integration State =====
    /// Available quacc cluster configurations.
    pub quacc_clusters: Vec<crate::models::QuaccClusterConfig>,

    /// Request ID for the current quacc job submission.
    pub submit_request_id: usize,

    // ===== Job Status Polling =====
    /// Timestamp of last job status poll.
    last_job_poll: std::time::Instant,

    /// Interval between status polls (default 30 seconds).
    poll_interval: std::time::Duration,

    /// Pending status requests (job_id -> request_id).
    pending_status_requests: std::collections::HashMap<String, usize>,

    /// Next request ID for status polls.
    status_request_counter: usize,

    /// Startup animation effect.
    pub startup_effect: Option<Effect>,
}

impl<'a> App<'a> {
    /// Default LSP command (fallback).
    /// Uses vasp-language-server CLI if installed on PATH.
    const LSP_SERVER_PATH_DEFAULT: &'static str = "vasp-lsp";

    /// Environment variable name for LSP server path/command override.
    const LSP_SERVER_PATH_ENV: &'static str = "CRYSTAL_TUI_LSP_PATH";

    /// Timeout for pending bridge requests (30 seconds).
    /// If a response is not received within this time, the request is considered failed
    /// and the pending state is cleared to prevent deadlocks.
    const BRIDGE_REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);

    /// Resolve the LSP server path using environment variable, bundled repo, or PATH.
    ///
    /// Lookup order:
    /// 1. CRYSTAL_TUI_LSP_PATH environment variable
    /// 2. Bundled repo (third_party/vasp-language-server) if built
    /// 3. Relative to executable directory
    /// 4. PATH command fallback
    fn resolve_lsp_path() -> String {
        use std::path::PathBuf;

        // 1. Environment variable override
        if let Ok(env_path) = std::env::var(Self::LSP_SERVER_PATH_ENV) {
            if PathBuf::from(&env_path).exists() {
                info!(
                    "Using LSP server from {}: {}",
                    Self::LSP_SERVER_PATH_ENV,
                    env_path
                );
            } else {
                info!(
                    "Using LSP server command from {}: {}",
                    Self::LSP_SERVER_PATH_ENV,
                    env_path
                );
            }
            return env_path;
        }

        // 2. Bundled repo (if present and built)
        let local_repo = PathBuf::from("third_party/vasp-language-server");
        let local_bin = local_repo.join("bin/vasp-lsp");
        let local_out = local_repo.join("out/server.js");
        if local_bin.exists() && local_out.exists() {
            info!(
                "Using bundled vasp-language-server: {}",
                local_bin.display()
            );
            return local_bin.to_string_lossy().to_string();
        }

        // 3. Relative to executable directory
        if let Ok(exe_path) = std::env::current_exe() {
            if let Some(exe_dir) = exe_path.parent() {
                let relative_path = exe_dir.join(Self::LSP_SERVER_PATH_DEFAULT);
                if relative_path.exists() {
                    let path_str = relative_path.to_string_lossy().to_string();
                    info!("Using LSP server relative to executable: {}", path_str);
                    return path_str;
                }
            }
        }

        // 4. PATH command fallback
        Self::LSP_SERVER_PATH_DEFAULT.to_string()
    }

    /// Create a new application with the Python controller.
    ///
    /// Spawns a worker thread that owns the Py<PyAny> and handles all
    /// Python calls asynchronously via channels.
    ///
    /// # Errors
    ///
    /// Returns an error if the Python bridge worker thread fails to spawn.
    /// This allows the caller to handle the failure gracefully (e.g., show
    /// an error message) instead of panicking.
    pub fn new(py_controller: Py<PyAny>) -> anyhow::Result<Self> {
        // Spawn the async bridge worker thread and box it for DI
        let bridge: Box<dyn BridgeService> = Box::new(
            BridgeHandle::spawn(py_controller)
                .context("Failed to spawn Python bridge worker thread")?,
        );

        let mut editor = TextArea::default();
        editor.set_line_number_style(
            ratatui::style::Style::default().fg(ratatui::style::Color::DarkGray),
        );

        // Create channel for LSP events
        let (lsp_tx, lsp_rx) = mpsc::channel();

        // Resolve LSP server path (env var -> relative to exe -> cwd)
        let lsp_path = Self::resolve_lsp_path();

        // Try to start the LSP server (graceful degradation if unavailable)
        // Box it for DI
        let lsp_client: Option<Box<dyn LspService>> = match LspClient::start(&lsp_path, lsp_tx) {
            Ok(client) => {
                info!("LSP server started successfully");
                Some(Box::new(client))
            }
            Err(e) => {
                warn!(
                    "Failed to start LSP server: {}. Editor will work without validation.",
                    e
                );
                None
            }
        };

        Ok(Self {
            should_quit: false,
            current_tab: AppTab::Jobs,
            last_error: None,
            last_error_time: None,
            needs_redraw: true, // Initial draw required
            jobs_state: JobsState::default(),
            slurm_queue: Vec::new(),
            slurm_view_active: false,
            slurm_request_id: 0,
            slurm_selected: None,
            last_slurm_refresh: None,
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
            log_job_pk: None,
            log_job_name: None,
            log_follow_mode: false,
            last_log_refresh: None,
            bridge,
            next_request_id: 0,
            pending_bridge_request: None,
            pending_request_id: None,
            pending_bridge_request_time: None,
            lsp_client,
            lsp_receiver: lsp_rx,
            last_editor_change: None,
            pending_lsp_change: false,
            materials: MaterialsSearchState::default(),
            new_job: NewJobState::default(),
            cluster_manager: ClusterManagerState::default(),
            slurm_queue_state: SlurmQueueState::default(),
            last_slurm_cluster_id: None,
            vasp_input_state: crate::ui::VaspInputState::default(),
            workflow_state: crate::ui::WorkflowState::default(),
            recipe_browser: RecipeBrowserState::default(),
            template_browser: TemplateBrowserState::default(),
            batch_submission: BatchSubmissionState::default(),
            recipe_request_id: 0,
            workflow_request_id: 0,
            vasp_request_id: 0,
            quacc_clusters: Vec::new(),
            submit_request_id: 0,
            last_job_poll: std::time::Instant::now(),
            poll_interval: std::time::Duration::from_secs(30),
            pending_status_requests: std::collections::HashMap::new(),
            status_request_counter: 0,
            startup_effect: Some(fx::coalesce(1500)),
        })
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
    #[allow(dead_code)] // Useful for debugging/testing
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

    // ===== MVU/Reducer: Centralized State Update =====

    /// Process an action and update application state.
    ///
    /// This is the central reducer function following the MVU pattern.
    /// All user-initiated state mutations should go through this method
    /// to ensure consistent state transitions and testability.
    ///
    /// # Example
    ///
    /// ```ignore
    /// // In input handler:
    /// match key.code {
    ///     KeyCode::Tab => app.update(Action::TabNext),
    ///     KeyCode::Char('j') => app.update(Action::JobSelectNext),
    ///     // ...
    /// }
    /// ```
    #[allow(dead_code)] // Public API for MVU pattern; used by callers
    pub fn update(&mut self, action: Action) {
        match action {
            // Tab Navigation
            Action::TabNext => self.next_tab(),
            Action::TabPrev => self.prev_tab(),
            Action::TabSet(tab) => self.set_tab(tab),

            // Jobs Tab
            Action::JobSelectNext => self.select_next_job(),
            Action::JobSelectPrev => self.select_prev_job(),
            Action::JobSelectFirst => self.select_first_job(),
            Action::JobSelectLast => self.select_last_job(),
            Action::JobViewLog => self.view_job_log(),
            Action::JobCancelRequest => self.request_cancel_selected_job(),
            Action::JobDiffRequest => self.request_diff_job(),
            Action::JobsRefresh => self.request_refresh_jobs(),
            Action::JobsSync => self.request_sync_remote_jobs(),

            // ===== Results Tab =====
            Action::ResultsScrollUp => self.scroll_results_up(),
            Action::ResultsScrollDown => self.scroll_results_down(),
            Action::ResultsPageUp => self.scroll_results_page_up(),
            Action::ResultsPageDown => self.scroll_results_page_down(),

            // Log Tab
            Action::LogScrollUp => self.scroll_log_up(),
            Action::LogScrollDown => self.scroll_log_down(),
            Action::LogPageUp => self.scroll_log_page_up(),
            Action::LogPageDown => self.scroll_log_page_down(),
            Action::LogScrollTop => self.scroll_log_top(),
            Action::LogScrollBottom => self.scroll_log_bottom(),
            Action::LogToggleFollow => self.toggle_log_follow(),

            // Editor Tab
            Action::EditorSubmitRequest => self.request_submit_from_editor(),

            // SLURM
            Action::SlurmToggle => self.toggle_slurm_view(),

            // Materials Modal
            Action::MaterialsOpen => self.open_materials_modal(),
            Action::MaterialsClose => self.close_materials_modal(),
            Action::MaterialsSearch => self.request_materials_search(),
            Action::MaterialsGenerateD12 => self.request_generate_d12(),
            Action::MaterialsSelectNext => self.materials.select_next(),
            Action::MaterialsSelectPrev => self.materials.select_prev(),

            // General
            Action::ErrorClear => self.clear_error(),
            Action::Quit => self.should_quit = true,
        }
    }

    // ===== Tab Navigation =====

    /// Move to the next tab.
    pub fn next_tab(&mut self) {
        let new_tab = match self.current_tab {
            AppTab::Jobs => AppTab::Editor,
            AppTab::Editor => AppTab::Results,
            AppTab::Results => AppTab::Log,
            AppTab::Log => AppTab::Jobs,
        };
        self.set_tab(new_tab);
    }

    /// Move to the previous tab.
    pub fn prev_tab(&mut self) {
        let new_tab = match self.current_tab {
            AppTab::Jobs => AppTab::Log,
            AppTab::Editor => AppTab::Jobs,
            AppTab::Results => AppTab::Editor,
            AppTab::Log => AppTab::Results,
        };
        self.set_tab(new_tab);
    }

    /// Set the current tab directly.
    ///
    /// When switching to the Log tab, automatically refreshes logs for the
    /// currently selected job to avoid showing stale logs from a different job.
    pub fn set_tab(&mut self, tab: AppTab) {
        if self.current_tab != tab {
            self.current_tab = tab;
            self.mark_dirty();

            // Auto-refresh logs when switching to Log tab
            if tab == AppTab::Log {
                self.auto_refresh_log_for_selected_job();
            }
        }
    }

    /// Auto-refresh log when the selected job differs from the loaded log.
    ///
    /// Called when navigating to the Log tab to ensure logs match the selection.
    fn auto_refresh_log_for_selected_job(&mut self) {
        if let Some(job) = self.selected_job() {
            let selected_pk = job.pk;
            let selected_name = job.name.clone();
            // Only refresh if the selected job differs from the loaded log
            if self.log_job_pk != Some(selected_pk) {
                self.log_job_pk = Some(selected_pk);
                self.log_job_name = Some(selected_name);
                self.log_lines.clear();
                self.log_scroll = 0;
                self.request_log_refresh(selected_pk);
            }
        }
    }

    // ===== Jobs Management (Async Bridge) =====

    /// Generate a new unique request ID.
    fn next_request_id(&mut self) -> usize {
        let id = self.next_request_id;
        self.next_request_id = self.next_request_id.wrapping_add(1);
        id
    }

    /// Request a job list refresh (non-blocking).
    ///
    /// The actual fetch happens on the worker thread. Results are
    /// delivered via `poll_bridge_responses()`.
    pub fn request_refresh_jobs(&mut self) {
        if self.pending_bridge_request.is_some() {
            // Already have a pending request - skip to avoid queue buildup
            return;
        }

        let request_id = self.next_request_id();
        match self.bridge.request_fetch_jobs(request_id) {
            Ok(()) => {
                self.pending_bridge_request = Some(BridgeRequestKind::FetchJobs);
                self.pending_request_id = Some(request_id);
                self.pending_bridge_request_time = Some(std::time::Instant::now());
            }
            Err(e) => {
                self.set_error(format!("Failed to request jobs: {}", e));
            }
        }
    }

    /// Request a sync of remote jobs (non-blocking).
    ///
    /// Queries squeue/sacct on remote clusters to update status of tracked jobs.
    pub fn request_sync_remote_jobs(&mut self) {
        if self.pending_bridge_request.is_some() {
            return;
        }

        let request_id = self.next_request_id();
        self.set_error("Syncing remote jobs (this may take a few seconds)...");
        match self.bridge.request_sync_remote_jobs(request_id) {
            Ok(()) => {
                self.pending_bridge_request = Some(BridgeRequestKind::SyncRemoteJobs);
                self.pending_request_id = Some(request_id);
                self.pending_bridge_request_time = Some(std::time::Instant::now());
            }
            Err(e) => {
                self.set_error(format!("Failed to request remote sync: {}", e));
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

        let request_id = self.next_request_id();
        match self.bridge.request_fetch_job_details(pk, request_id) {
            Ok(()) => {
                self.pending_bridge_request = Some(BridgeRequestKind::FetchJobDetails);
                self.pending_request_id = Some(request_id);
                self.pending_bridge_request_time = Some(std::time::Instant::now());
            }
            Err(e) => {
                self.set_error(format!("Failed to request job details: {}", e));
            }
        }
    }

    /// Poll for bridge responses and update state (non-blocking).
    ///
    /// Call this each frame to receive results from async Python operations.
    /// Also checks for request timeouts to prevent deadlocks if the Python worker crashes.
    pub fn poll_bridge_responses(&mut self) {
        // Check for request timeout to prevent deadlock if Python worker fails
        if let (Some(kind), Some(start_time)) = (
            self.pending_bridge_request.as_ref(),
            self.pending_bridge_request_time,
        ) {
            if start_time.elapsed() > Self::BRIDGE_REQUEST_TIMEOUT {
                warn!(
                    "Bridge request {:?} timed out after {:?}, clearing pending state",
                    kind,
                    Self::BRIDGE_REQUEST_TIMEOUT
                );
                self.set_error(format!(
                    "Python backend request timed out ({}s). The backend may be unresponsive.",
                    Self::BRIDGE_REQUEST_TIMEOUT.as_secs()
                ));
                self.pending_bridge_request = None;
                self.pending_request_id = None;
                self.pending_bridge_request_time = None;
                self.mark_dirty();
            }
        }

        while let Some(response) = self.bridge.poll_response() {
            // Extract request_id from response to match against pending request.
            // Only clear pending state if BOTH type and request ID match to prevent
            // race conditions where a stale response clears the pending state.
            let response_request_id = match &response {
                BridgeResponse::Jobs { request_id, .. }
                | BridgeResponse::JobDetails { request_id, .. }
                | BridgeResponse::JobSubmitted { request_id, .. }
                | BridgeResponse::JobCancelled { request_id, .. }
                | BridgeResponse::JobLog { request_id, .. }
                | BridgeResponse::MaterialsFound { request_id, .. }
                | BridgeResponse::D12Generated { request_id, .. }
                | BridgeResponse::SlurmQueue { request_id, .. }
                | BridgeResponse::SlurmJobCancelled { request_id, .. }
                | BridgeResponse::SlurmJobAdopted { request_id, .. }
                | BridgeResponse::Clusters { request_id, .. }
                | BridgeResponse::Cluster { request_id, .. }
                | BridgeResponse::ClusterCreated { request_id, .. }
                | BridgeResponse::ClusterUpdated { request_id, .. }
                | BridgeResponse::ClusterDeleted { request_id, .. }
                | BridgeResponse::ClusterConnectionTested { request_id, .. } => Some(*request_id),
                BridgeResponse::Templates { request_id, .. }
                | BridgeResponse::TemplateRendered { request_id, .. } => Some(*request_id),
                BridgeResponse::WorkflowsAvailable { request_id, .. }
                | BridgeResponse::WorkflowCreated { request_id, .. } => Some(*request_id),
                // JSON-RPC generic response (thin IPC pattern)
                BridgeResponse::RpcResult { request_id, .. } => Some(*request_id),
            };

            // Check if response matches pending request by BOTH type AND request ID
            let is_pending_match = match (&response, &self.pending_bridge_request) {
                (BridgeResponse::Jobs { .. }, Some(BridgeRequestKind::FetchJobs))
                | (BridgeResponse::Jobs { .. }, Some(BridgeRequestKind::SyncRemoteJobs))
                | (BridgeResponse::JobDetails { .. }, Some(BridgeRequestKind::FetchJobDetails))
                | (BridgeResponse::JobSubmitted { .. }, Some(BridgeRequestKind::SubmitJob))
                | (BridgeResponse::JobCancelled { .. }, Some(BridgeRequestKind::CancelJob))
                | (BridgeResponse::JobLog { .. }, Some(BridgeRequestKind::FetchJobLog)) => {
                    // Must also match request ID to prevent stale response race condition
                    response_request_id == self.pending_request_id
                }
                // Materials, SLURM, and Cluster responses use their own request_id tracking and should NOT
                // affect pending_bridge_request (which tracks Job operations)
                (BridgeResponse::MaterialsFound { .. }, _)
                | (BridgeResponse::D12Generated { .. }, _)
                | (BridgeResponse::SlurmQueue { .. }, _)
                | (BridgeResponse::SlurmJobCancelled { .. }, _)
                | (BridgeResponse::Clusters { .. }, _)
                | (BridgeResponse::Cluster { .. }, _)
                | (BridgeResponse::ClusterCreated { .. }, _)
                | (BridgeResponse::ClusterUpdated { .. }, _)
                | (BridgeResponse::ClusterDeleted { .. }, _)
                | (BridgeResponse::ClusterConnectionTested { .. }, _) => false,
                (BridgeResponse::Templates { .. }, _)
                | (BridgeResponse::TemplateRendered { .. }, _) => false,
                // Workflow responses use their own request_id tracking
                (BridgeResponse::WorkflowsAvailable { .. }, _)
                | (BridgeResponse::WorkflowCreated { .. }, _) => false,
                // JSON-RPC responses use their own request_id tracking (thin IPC pattern)
                (BridgeResponse::RpcResult { .. }, _) => false,
                // Response doesn't match pending request type
                _ => false,
            };

            if is_pending_match {
                self.pending_bridge_request = None;
                self.pending_request_id = None;
                self.pending_bridge_request_time = None;
            } else if response_request_id.is_some()
                && self.pending_request_id.is_some()
                && response_request_id != self.pending_request_id
            {
                // Log stale responses for debugging (request ID mismatch)
                debug!(
                    "Ignoring stale response (request_id {:?} != pending {:?})",
                    response_request_id, self.pending_request_id
                );
            }

            match response {
                BridgeResponse::Jobs { result, .. } => {
                    match result {
                        Ok(new_jobs) => {
                            // Track which jobs changed state since last refresh
                            self.jobs_state.changed_pks.clear();
                            let old_states: std::collections::HashMap<i32, _> = self
                                .jobs_state
                                .jobs
                                .iter()
                                .map(|j| (j.pk, j.state))
                                .collect();

                            for job in &new_jobs {
                                if let Some(old_state) = old_states.get(&job.pk) {
                                    if old_state != &job.state {
                                        self.jobs_state.changed_pks.insert(job.pk);
                                    }
                                } else {
                                    // New job - highlight it
                                    self.jobs_state.changed_pks.insert(job.pk);
                                }
                            }

                            self.jobs_state.jobs = new_jobs;
                            self.jobs_state.last_refresh = Some(std::time::Instant::now());

                            // Adjust selection if needed
                            if !self.jobs_state.jobs.is_empty() {
                                if self.jobs_state.selected_index.is_none() {
                                    self.jobs_state.selected_index = Some(0);
                                } else if let Some(idx) = self.jobs_state.selected_index {
                                    if idx >= self.jobs_state.jobs.len() {
                                        self.jobs_state.selected_index =
                                            Some(self.jobs_state.jobs.len() - 1);
                                    }
                                }
                            } else {
                                self.jobs_state.selected_index = None;
                            }
                            self.clear_error();
                        }
                        Err(e) => {
                            self.set_error(format!("Failed to fetch jobs: {}", e));
                        }
                    }
                }
                BridgeResponse::JobDetails { result, .. } => match result {
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
                },
                BridgeResponse::JobSubmitted { result, .. } => {
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
                BridgeResponse::JobCancelled { result, .. } => {
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
                BridgeResponse::JobLog { result, .. } => match result {
                    Ok(log) => {
                        let was_at_bottom = self.log_scroll >= self.log_max_scroll();
                        self.log_lines = log.stdout;

                        // In follow mode or if we were already at bottom, scroll to bottom
                        if self.log_follow_mode || was_at_bottom {
                            // Recalculate max scroll with new content
                            let max = self.log_max_scroll();
                            self.log_scroll = max;
                        } else {
                            // Keep current scroll position, but clamp to valid range
                            let max = self.log_max_scroll();
                            self.log_scroll = self.log_scroll.min(max);
                        }
                        self.clear_error();
                    }
                    Err(e) => {
                        self.set_error(format!("Failed to fetch job log: {}", e));
                    }
                },
                // Materials Project API responses
                BridgeResponse::MaterialsFound { request_id, result } => {
                    // Only process if this is the current request (ignore stale responses)
                    if request_id == self.materials.request_id && self.materials.active {
                        self.materials.loading = false;
                        match result {
                            Ok(results) => {
                                let count = results.len();
                                self.materials.results = results;
                                if count > 0 {
                                    self.materials.table_state.select(Some(0));
                                    self.materials
                                        .set_status(&format!("Found {} structures", count), false);
                                    // Trigger preview for the first result
                                    self.request_structure_preview();
                                } else {
                                    self.materials.set_status("No structures found", true);
                                    self.materials.clear_preview();
                                }
                            }
                            Err(e) => {
                                self.materials.results.clear();
                                self.materials
                                    .set_status(&format!("Search failed: {}", e), true);
                            }
                        }
                    } else {
                        debug!(
                            "Ignoring stale materials response (request_id={}, current={})",
                            request_id, self.materials.request_id
                        );
                    }
                }
                BridgeResponse::D12Generated { request_id, result } => {
                    // Only process if this is the current request
                    if request_id == self.materials.request_id && self.materials.active {
                        self.materials.loading = false;
                        match result {
                            Ok(d12_content) => {
                                // Generate filename from material ID
                                let filename = self
                                    .materials
                                    .selected_for_import
                                    .as_ref()
                                    .map(|mp_id| format!("{}.d12", mp_id.replace('-', "_")))
                                    .unwrap_or_else(|| "imported.d12".to_string());

                                // Use open_file to properly set up editor with LSP support
                                // This sets editor_file_path, editor_file_uri, editor_dft_code,
                                // editor_version, and notifies LSP via did_open.
                                self.open_file(&filename, &d12_content);

                                self.materials.close();
                                self.current_tab = AppTab::Editor;
                                info!("Imported .d12 content ({} bytes)", d12_content.len());
                            }
                            Err(e) => {
                                self.materials
                                    .set_status(&format!("Generation failed: {}", e), true);
                                self.materials.selected_for_import = None;
                            }
                        }
                    } else {
                        debug!(
                            "Ignoring stale D12 response (request_id={}, current={})",
                            request_id, self.materials.request_id
                        );
                    }
                }
                // SLURM queue response
                BridgeResponse::SlurmQueue { request_id, result } => {
                    // Handle both old slurm_request_id and new modal state
                    if request_id == self.slurm_request_id
                        || request_id == self.slurm_queue_state.request_id
                    {
                        // Update modal state before consuming result
                        self.slurm_queue_state.loading = false;
                        if request_id == self.slurm_queue_state.request_id {
                            match &result {
                                Ok(entries) => {
                                    if entries.is_empty() {
                                        self.slurm_queue_state.error =
                                            Some("No jobs in queue".to_string());
                                    } else {
                                        self.slurm_queue_state.error = None;
                                    }
                                }
                                Err(e) => {
                                    self.slurm_queue_state.error = Some(format!("Error: {}", e));
                                }
                            }
                        }

                        // Now consume result for the old handler
                        self.handle_slurm_queue_response(result);
                    } else {
                        // Ignore stale response
                        debug!(
                            "Ignoring stale SLURM queue response (request_id={}, current={}, modal={})",
                            request_id, self.slurm_request_id, self.slurm_queue_state.request_id
                        );
                    }
                }
                BridgeResponse::SlurmJobCancelled { request_id, result } => {
                    if request_id == self.slurm_request_id
                        || request_id == self.slurm_queue_state.request_id
                    {
                        self.slurm_queue_state.loading = false;
                        match result {
                            Ok(cancel_result) => {
                                if cancel_result.success {
                                    let msg = cancel_result
                                        .message
                                        .unwrap_or_else(|| "Job cancelled".to_string());
                                    info!("SLURM job cancelled: {}", msg);
                                    self.slurm_queue_state.error =
                                        Some(format!("Success: {}", msg));
                                    // Refresh the queue to reflect the cancellation
                                    if self.slurm_queue_state.active {
                                        self.refresh_slurm_queue();
                                    } else {
                                        self.request_fetch_slurm_queue();
                                    }
                                } else {
                                    let msg = cancel_result
                                        .message
                                        .unwrap_or_else(|| "Unknown error".to_string());
                                    let error_msg = format!("Cancel failed: {}", msg);
                                    self.set_error(&error_msg);
                                    self.slurm_queue_state.error = Some(error_msg);
                                }
                            }
                            Err(e) => {
                                let error_msg = format!("Cancel error: {}", e);
                                self.set_error(&error_msg);
                                self.slurm_queue_state.error = Some(error_msg);
                            }
                        }
                    } else {
                        debug!(
                            "Ignoring stale SLURM cancel response (request_id={}, current={}, modal={})",
                            request_id, self.slurm_request_id, self.slurm_queue_state.request_id
                        );
                    }
                }
                BridgeResponse::SlurmJobAdopted { request_id, result } => {
                    if request_id == self.slurm_queue_state.request_id {
                        self.slurm_queue_state.loading = false;
                        match result {
                            Ok(pk) => {
                                let msg = format!("Job adopted successfully (ID: {})", pk);
                                info!("{}", msg);
                                self.slurm_queue_state.error = Some(msg);
                                // Refresh local job list to show the new job
                                self.request_refresh_jobs();
                            }
                            Err(e) => {
                                let error_msg = format!("Adoption failed: {}", e);
                                self.set_error(&error_msg);
                                self.slurm_queue_state.error = Some(error_msg);
                            }
                        }
                    }
                }
                // Cluster management responses
                BridgeResponse::Clusters { request_id, result } => {
                    if request_id == self.cluster_manager.request_id {
                        self.cluster_manager.loading = false;
                        match result {
                            Ok(clusters) => {
                                let count = clusters.len();
                                self.cluster_manager.clusters = clusters;
                                if count > 0 && self.cluster_manager.selected_index.is_none() {
                                    self.cluster_manager.selected_index = Some(0);
                                }
                                self.cluster_manager
                                    .set_status(&format!("Loaded {} clusters", count), false);
                            }
                            Err(e) => {
                                self.cluster_manager
                                    .set_status(&format!("Failed to load clusters: {}", e), true);
                            }
                        }
                    }
                }
                BridgeResponse::Cluster { request_id, result } => {
                    debug!(
                        "Cluster response (request_id={}): {:?}",
                        request_id,
                        result.is_ok()
                    );
                }
                BridgeResponse::ClusterCreated { request_id, result } => {
                    if request_id == self.cluster_manager.request_id {
                        self.cluster_manager.loading = false;
                        match result {
                            Ok(cluster) => {
                                self.cluster_manager.set_status(
                                    &format!("Created cluster '{}'", cluster.name),
                                    false,
                                );
                                self.cluster_manager.cancel(); // Return to list view
                                self.request_fetch_clusters(); // Refresh the list
                            }
                            Err(e) => {
                                self.cluster_manager
                                    .set_status(&format!("Failed to create cluster: {}", e), true);
                            }
                        }
                    }
                }
                BridgeResponse::ClusterUpdated { request_id, result } => {
                    if request_id == self.cluster_manager.request_id {
                        self.cluster_manager.loading = false;
                        match result {
                            Ok(cluster) => {
                                self.cluster_manager.set_status(
                                    &format!("Updated cluster '{}'", cluster.name),
                                    false,
                                );
                                self.cluster_manager.cancel(); // Return to list view
                                self.request_fetch_clusters(); // Refresh the list
                            }
                            Err(e) => {
                                self.cluster_manager
                                    .set_status(&format!("Failed to update cluster: {}", e), true);
                            }
                        }
                    }
                }
                BridgeResponse::ClusterDeleted { request_id, result } => {
                    if request_id == self.cluster_manager.request_id {
                        self.cluster_manager.loading = false;
                        match result {
                            Ok(success) => {
                                if success {
                                    self.cluster_manager.set_status("Cluster deleted", false);
                                    self.cluster_manager.cancel(); // Return to list view
                                    self.cluster_manager.selected_index = None;
                                    self.request_fetch_clusters(); // Refresh the list
                                } else {
                                    self.cluster_manager
                                        .set_status("Failed to delete cluster", true);
                                }
                            }
                            Err(e) => {
                                self.cluster_manager
                                    .set_status(&format!("Failed to delete cluster: {}", e), true);
                            }
                        }
                    }
                }
                BridgeResponse::ClusterConnectionTested { request_id, result } => {
                    if request_id == self.cluster_manager.request_id {
                        self.cluster_manager.loading = false;
                        match result {
                            Ok(conn_result) => {
                                use crate::ui::ConnectionTestResult;
                                self.cluster_manager.connection_result =
                                    Some(ConnectionTestResult {
                                        success: conn_result.success,
                                        system_info: conn_result.system_info,
                                        error: conn_result.error,
                                    });
                            }
                            Err(e) => {
                                self.cluster_manager
                                    .set_status(&format!("Connection test failed: {}", e), true);
                            }
                        }
                    }
                }
                BridgeResponse::Templates { request_id, result } => {
                    if request_id == self.template_browser.request_id && self.template_browser.active
                    {
                        self.template_browser.loading = false;
                        match result {
                            Ok(templates) => {
                                let count = templates.len();
                                self.template_browser.templates = templates;
                                if count > 0 {
                                    self.template_browser.selected_index = Some(0);
                                }
                                info!("Loaded {} templates", count);
                            }
                            Err(e) => {
                                self.template_browser.error = Some(format!("Error: {}", e));
                            }
                        }
                    }
                }
                BridgeResponse::TemplateRendered { request_id, result } => match result {
                    Ok(rendered) => {
                        debug!(
                            "Template rendered ({} bytes, request_id={})",
                            rendered.len(),
                            request_id
                        );
                    }
                    Err(e) => {
                        self.set_error(format!("Failed to render template: {}", e));
                    }
                },
                // Workflow responses
                BridgeResponse::WorkflowsAvailable { request_id, result } => {
                    if Some(request_id) == self.workflow_state.request_id {
                        self.workflow_state.set_loading(false);
                        match result {
                            Ok(availability) => {
                                self.workflow_state.set_availability(
                                    availability.available,
                                    availability.aiida_available,
                                );
                                if availability.available {
                                    self.workflow_state
                                        .set_status("Workflows ready".to_string(), false);
                                } else {
                                    self.workflow_state.set_status(
                                        "Workflow module not available".to_string(),
                                        true,
                                    );
                                }
                            }
                            Err(e) => {
                                self.workflow_state
                                    .set_status(format!("Failed to check workflows: {}", e), true);
                            }
                        }
                    }
                }
                BridgeResponse::WorkflowCreated { request_id, result } => {
                    if Some(request_id) == self.workflow_state.request_id {
                        self.workflow_state.set_loading(false);
                        match result {
                            Ok(_workflow_json) => {
                                self.workflow_state
                                    .set_status("Workflow created successfully".to_string(), false);
                                // TODO: Parse workflow JSON and show in results or trigger next step
                                info!("Workflow created successfully");
                            }
                            Err(e) => {
                                self.workflow_state
                                    .set_status(format!("Failed to create workflow: {}", e), true);
                            }
                        }
                    }
                }
                // JSON-RPC generic response (thin IPC pattern)
                //
                // As methods migrate from legacy variants to JSON-RPC, we route
                // responses based on request_id matching known pending operations.
                BridgeResponse::RpcResult { request_id, result } => {
                    // Check if this is a recipe list response
                    if request_id == self.recipe_request_id && self.recipe_browser.loading {
                        self.recipe_browser.loading = false;
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        // DEBUG: Log the raw response
                                        debug!("recipes.list raw response: {}", serde_json::to_string(&value).unwrap_or_default());
                                        // Deserialize the JSON value into RecipesListResponse
                                        match serde_json::from_value::<
                                            crate::models::RecipesListResponse,
                                        >(value)
                                        {
                                            Ok(response) => {
                                                let count = response.recipes.len();
                                                let quacc_ver = response.quacc_version.clone();
                                                let quacc_installed = quacc_ver.is_some();
                                                info!("recipes.list response: {} recipes, quacc_version={:?}, error={:?}",
                                                    count, quacc_ver, response.error);
                                                // Build WorkflowEngineStatus from response
                                                let engine_status =
                                                    crate::models::WorkflowEngineStatus {
                                                        configured: None,
                                                        installed: Vec::new(),
                                                        quacc_installed,
                                                    };
                                                self.recipe_browser.set_data(
                                                    response.recipes,
                                                    engine_status,
                                                    response.error,
                                                );
                                                info!("Recipe browser updated: quacc_installed={}", quacc_installed);
                                            }
                                            Err(e) => {
                                                self.recipe_browser.error =
                                                    Some(format!("Parse error: {}", e));
                                                error!("Failed to deserialize recipes: {}", e);
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        self.recipe_browser.error =
                                            Some(format!("RPC error: {}", e));
                                        warn!("JSON-RPC error for recipes: {}", e);
                                    }
                                }
                            }
                            Err(e) => {
                                self.recipe_browser.error = Some(format!("Bridge error: {}", e));
                                error!("Bridge dispatch failed for recipes: {}", e);
                            }
                        }
                    }
                    // Check if this is a cluster fetch response
                    else if request_id == self.cluster_manager.request_id {
                        self.cluster_manager.loading = false;
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        // Deserialize the JSON value into ApiResponse<Vec<ClusterConfig>>
                                        // Python API returns {"ok": true, "data": [...]} wrapper
                                        match serde_json::from_value::<
                                            ApiResponse<Vec<crate::models::ClusterConfig>>,
                                        >(value)
                                        {
                                            Ok(api_response) => match api_response.into_result() {
                                                Ok(clusters) => {
                                                    let count = clusters.len();
                                                    self.cluster_manager.clusters = clusters;
                                                    if count > 0
                                                        && self
                                                            .cluster_manager
                                                            .selected_index
                                                            .is_none()
                                                    {
                                                        self.cluster_manager.selected_index =
                                                            Some(0);
                                                    }
                                                    self.cluster_manager.set_status(
                                                        &format!("Loaded {} clusters", count),
                                                        false,
                                                    );
                                                    debug!(
                                                        "Loaded {} clusters via JSON-RPC",
                                                        count
                                                    );
                                                }
                                                Err(e) => {
                                                    self.cluster_manager.set_status(
                                                        &format!("API error: {}", e),
                                                        true,
                                                    );
                                                    error!("API error for clusters: {}", e);
                                                }
                                            },
                                            Err(e) => {
                                                self.cluster_manager.set_status(
                                                    &format!("Parse error: {}", e),
                                                    true,
                                                );
                                                error!("Failed to deserialize clusters: {}", e);
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        self.cluster_manager
                                            .set_status(&format!("RPC error: {}", e), true);
                                        warn!("JSON-RPC error for clusters: {}", e);
                                    }
                                }
                            }
                            Err(e) => {
                                self.cluster_manager
                                    .set_status(&format!("Bridge error: {}", e), true);
                                error!("Bridge dispatch failed for clusters: {}", e);
                            }
                        }
                    }
                    // Check if this is a workflow availability response
                    else if request_id == self.workflow_request_id && self.workflow_state.loading
                    {
                        self.workflow_state.set_loading(false);
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        // Parse the availability response
                                        // Python returns {"ok": true, "data": {...}} wrapper
                                        #[derive(serde::Deserialize)]
                                        struct WorkflowAvailabilityResponse {
                                            #[serde(default)]
                                            available: bool,
                                            #[serde(default)]
                                            workflows: Vec<String>,
                                            #[serde(default)]
                                            aiida_available: bool,
                                            #[serde(default)]
                                            quacc_available: bool,
                                            error: Option<String>,
                                        }

                                        // First unwrap the ApiResponse wrapper
                                        let inner_value = match serde_json::from_value::<
                                            ApiResponse<serde_json::Value>,
                                        >(value.clone())
                                        {
                                            Ok(api_response) => match api_response.into_result() {
                                                Ok(data) => data,
                                                Err(e) => {
                                                    self.workflow_state.set_status(
                                                        format!("API error: {}", e),
                                                        true,
                                                    );
                                                    continue;
                                                }
                                            },
                                            Err(_) => value, // Not wrapped, use as-is
                                        };

                                        match serde_json::from_value::<WorkflowAvailabilityResponse>(
                                            inner_value,
                                        ) {
                                            Ok(response) => {
                                                self.workflow_state.set_availability(
                                                    response.available || response.quacc_available,
                                                    response.aiida_available,
                                                );
                                                if let Some(err) = response.error {
                                                    self.workflow_state.set_status(err, true);
                                                } else if response.workflows.is_empty() {
                                                    self.workflow_state.set_status(
                                                        "No workflows available".to_string(),
                                                        true,
                                                    );
                                                }
                                                debug!(
                                                    "Workflow availability: {} workflows, aiida={}, quacc={}",
                                                    response.workflows.len(),
                                                    response.aiida_available,
                                                    response.quacc_available
                                                );
                                            }
                                            Err(e) => {
                                                self.workflow_state.set_status(
                                                    format!("Parse error: {}", e),
                                                    true,
                                                );
                                                error!(
                                                    "Failed to deserialize workflow availability: {}",
                                                    e
                                                );
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        self.workflow_state
                                            .set_status(format!("RPC error: {}", e), true);
                                        warn!("JSON-RPC error for workflow availability: {}", e);
                                    }
                                }
                            }
                            Err(e) => {
                                self.workflow_state
                                    .set_status(format!("Bridge error: {}", e), true);
                                error!("Bridge dispatch failed for workflow availability: {}", e);
                            }
                        }
                    } else if self.pending_request_id == Some(request_id)
                        && matches!(
                            self.pending_bridge_request,
                            Some(BridgeRequestKind::FetchJobs)
                                | Some(BridgeRequestKind::SyncRemoteJobs)
                        )
                    {
                        // Route jobs fetch response
                        self.pending_bridge_request = None;
                        self.pending_request_id = None;
                        self.pending_bridge_request_time = None;
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        match serde_json::from_value::<Vec<crate::models::JobStatus>>(
                                            value,
                                        ) {
                                            Ok(new_jobs) => {
                                                // Track which jobs changed state since last refresh
                                                self.jobs_state.changed_pks.clear();
                                                let old_states: std::collections::HashMap<i32, _> =
                                                    self.jobs_state
                                                        .jobs
                                                        .iter()
                                                        .map(|j| (j.pk, j.state))
                                                        .collect();

                                                for job in &new_jobs {
                                                    if let Some(old_state) = old_states.get(&job.pk)
                                                    {
                                                        if old_state != &job.state {
                                                            self.jobs_state
                                                                .changed_pks
                                                                .insert(job.pk);
                                                        }
                                                    } else {
                                                        // New job - highlight it
                                                        self.jobs_state.changed_pks.insert(job.pk);
                                                    }
                                                }

                                                let count = new_jobs.len();
                                                self.jobs_state.jobs = new_jobs;
                                                self.jobs_state.last_refresh =
                                                    Some(std::time::Instant::now());

                                                // Adjust selection if needed
                                                if !self.jobs_state.jobs.is_empty() {
                                                    if self.jobs_state.selected_index.is_none() {
                                                        self.jobs_state.selected_index = Some(0);
                                                    } else if let Some(idx) =
                                                        self.jobs_state.selected_index
                                                    {
                                                        if idx >= self.jobs_state.jobs.len() {
                                                            self.jobs_state.selected_index = Some(
                                                                self.jobs_state
                                                                    .jobs
                                                                    .len()
                                                                    .saturating_sub(1),
                                                            );
                                                        }
                                                    }
                                                } else {
                                                    self.jobs_state.selected_index = None;
                                                }
                                                debug!("Loaded {} jobs via JSON-RPC", count);
                                            }
                                            Err(e) => {
                                                error!("Failed to deserialize jobs: {}", e);
                                                self.set_error(format!("Parse error: {}", e));
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        warn!("JSON-RPC error for jobs: {}", e);
                                        self.set_error(format!("RPC error: {}", e));
                                    }
                                }
                            }
                            Err(e) => {
                                error!("Bridge dispatch failed for jobs: {}", e);
                                self.set_error(format!("Bridge error: {}", e));
                            }
                        }
                    }
                    // Check if this is a VASP generation response
                    else if request_id == self.vasp_request_id && self.materials.active {
                        self.materials.loading = false;
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        // Parse the VASP inputs response (wrapped in ApiResponse)
                                        match serde_json::from_value::<
                                            ApiResponse<crate::models::GeneratedVaspInputs>,
                                        >(value)
                                        {
                                            Ok(api_response) => match api_response.into_result() {
                                                Ok(vasp_inputs) => {
                                                    // Generate filename from material ID
                                                    let filename = self
                                                        .materials
                                                        .selected_for_import
                                                        .as_ref()
                                                        .map(|mp_id| {
                                                            format!("{}_vasp.txt", mp_id.replace('-', "_"))
                                                        })
                                                        .unwrap_or_else(|| "vasp_inputs.txt".to_string());

                                                    // Store POSCAR for potential quacc job submission
                                                    self.materials.generated_poscar =
                                                        Some(vasp_inputs.poscar.clone());

                                                    // Combine all VASP files into a single view
                                                    // POSCAR is the primary file for structure
                                                    let combined_content = format!(
                                                        "# ===== POSCAR =====\n{}\n\n# ===== INCAR =====\n{}\n\n# ===== KPOINTS =====\n{}\n\n# ===== POTCAR Required =====\n# Elements: {}\n# Note: POTCAR files must be obtained separately (VASP license required)",
                                                        vasp_inputs.poscar,
                                                        vasp_inputs.incar,
                                                        vasp_inputs.kpoints,
                                                        vasp_inputs.potcar_symbols.join(", ")
                                                    );

                                                    // Load into editor
                                                    self.open_file(&filename, &combined_content);

                                                    self.materials.close();
                                                    self.current_tab = AppTab::Editor;
                                                    info!(
                                                        "Imported VASP inputs ({} bytes)",
                                                        combined_content.len()
                                                    );
                                                }
                                                Err(e) => {
                                                    self.materials.set_status(
                                                        &format!("API error: {}", e),
                                                        true,
                                                    );
                                                    self.materials.selected_for_import = None;
                                                    error!("VASP generation API error: {}", e);
                                                }
                                            },
                                            Err(e) => {
                                                self.materials.set_status(
                                                    &format!("Parse error: {}", e),
                                                    true,
                                                );
                                                self.materials.selected_for_import = None;
                                                error!("Failed to deserialize VASP inputs: {}", e);
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        self.materials
                                            .set_status(&format!("RPC error: {}", e), true);
                                        self.materials.selected_for_import = None;
                                        warn!("JSON-RPC error for VASP generation: {}", e);
                                    }
                                }
                            }
                            Err(e) => {
                                self.materials
                                    .set_status(&format!("Bridge error: {}", e), true);
                                self.materials.selected_for_import = None;
                                error!("Bridge dispatch failed for VASP generation: {}", e);
                            }
                        }
                    }
                    // Check if this is a VASP validation response
                    else if request_id == self.vasp_input_state.validation_request_id
                        && self.vasp_input_state.active
                    {
                        self.vasp_input_state.status = None;
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        match serde_json::from_value::<
                                            ApiResponse<crate::models::ValidationResult>,
                                        >(value)
                                        {
                                            Ok(api_response) => match api_response.into_result() {
                                                Ok(val_result) => {
                                                    if val_result.valid {
                                                        self.vasp_input_state.status =
                                                            Some("Validation passed!".to_string());
                                                    } else {
                                                        self.vasp_input_state.set_error(
                                                            "Validation failed. See details."
                                                                .to_string(),
                                                        );
                                                    }
                                                    self.vasp_input_state.validation =
                                                        Some(val_result);
                                                }
                                                Err(e) => {
                                                    self.vasp_input_state.set_error(e);
                                                }
                                            },
                                            Err(e) => {
                                                self.vasp_input_state.set_error(format!(
                                                    "Failed to parse validation result: {}",
                                                    e
                                                ));
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        self.vasp_input_state
                                            .set_error(format!("RPC error: {}", e));
                                    }
                                }
                            }
                            Err(e) => {
                                self.vasp_input_state
                                    .set_error(format!("Bridge error: {}", e));
                            }
                        }
                    }
                    // Check if this is a quacc job submission response
                    else if request_id == self.submit_request_id && self.materials.submitting {
                        self.materials.submitting = false;
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        // Parse the submit response (wrapped in ApiResponse)
                                        match serde_json::from_value::<
                                            ApiResponse<crate::models::QuaccJobSubmitResponse>,
                                        >(value)
                                        {
                                            Ok(api_response) => match api_response.into_result() {
                                                Ok(submit_response) => {
                                                    if submit_response.status == "pending" {
                                                        let job_id = submit_response
                                                            .job_id
                                                            .unwrap_or_else(|| "unknown".to_string());
                                                        self.materials.submit_success(job_id.clone());
                                                        self.materials.set_status(
                                                            &format!("Job submitted: {}", job_id),
                                                            false,
                                                        );
                                                        info!("Job submitted successfully: {}", job_id);
                                                    } else {
                                                        let error = submit_response
                                                            .error
                                                            .unwrap_or_else(|| "Unknown error".to_string());
                                                        self.materials.submit_failure(error.clone());
                                                        self.materials
                                                            .set_status(&format!("Submit error: {}", error), true);
                                                        warn!("Job submission failed: {}", error);
                                                    }
                                                }
                                                Err(e) => {
                                                    self.materials.submit_failure(format!("API error: {}", e));
                                                    self.materials
                                                        .set_status(&format!("API error: {}", e), true);
                                                    error!("Job submit API error: {}", e);
                                                }
                                            },
                                            Err(e) => {
                                                self.materials
                                                    .submit_failure(format!("Parse error: {}", e));
                                                self.materials
                                                    .set_status(&format!("Parse error: {}", e), true);
                                                error!("Failed to deserialize submit response: {}", e);
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        self.materials.submit_failure(format!("RPC error: {}", e));
                                        self.materials.set_status(&format!("RPC error: {}", e), true);
                                        warn!("JSON-RPC error for job submission: {}", e);
                                    }
                                }
                            }
                            Err(e) => {
                                self.materials.submit_failure(format!("Bridge error: {}", e));
                                self.materials
                                    .set_status(&format!("Bridge error: {}", e), true);
                                error!("Bridge dispatch failed for job submission: {}", e);
                            }
                        }
                    }
                    // Check if this is a structure preview response
                    else if request_id == self.materials.preview_request_id
                        && self.materials.preview_loading
                    {
                        self.materials.preview_loading = false;
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        // Parse the preview response (wrapped in ApiResponse)
                                        match serde_json::from_value::<
                                            ApiResponse<crate::models::StructurePreview>,
                                        >(value)
                                        {
                                            Ok(api_response) => match api_response.into_result() {
                                                Ok(preview) => {
                                                    debug!(
                                                        "Structure preview loaded: {} ({} sites)",
                                                        preview.formula, preview.num_sites
                                                    );
                                                    self.materials.set_preview(preview);
                                                }
                                                Err(e) => {
                                                    // API error - not critical, just clear preview
                                                    debug!("Structure preview API error: {}", e);
                                                    self.materials.preview = None;
                                                }
                                            },
                                            Err(e) => {
                                                debug!("Failed to deserialize structure preview: {}", e);
                                                self.materials.preview = None;
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        debug!("JSON-RPC error for structure preview: {}", e);
                                        self.materials.preview = None;
                                    }
                                }
                            }
                            Err(e) => {
                                debug!("Bridge dispatch failed for structure preview: {}", e);
                                self.materials.preview = None;
                            }
                        }
                    }
                    // Check if this is a job status poll response
                    else if let Some(job_id) = self
                        .pending_status_requests
                        .iter()
                        .find(|(_, &rid)| rid == request_id)
                        .map(|(jid, _)| jid.clone())
                    {
                        self.pending_status_requests.remove(&job_id);
                        match result {
                            Ok(rpc_response) => {
                                match rpc_response.into_result() {
                                    Ok(value) => {
                                        // Parse the status response
                                        // Expected format: {"job_id": "123", "status": "running", "error": null}
                                        if let Some(status_str) = value.get("status").and_then(|v| v.as_str()) {
                                            let new_state = match status_str {
                                                "created" => crate::models::JobState::Created,
                                                "submitted" => crate::models::JobState::Submitted,
                                                "queued" => crate::models::JobState::Queued,
                                                "running" => crate::models::JobState::Running,
                                                "completed" => crate::models::JobState::Completed,
                                                "failed" => crate::models::JobState::Failed,
                                                "cancelled" => crate::models::JobState::Cancelled,
                                                _ => crate::models::JobState::Unknown,
                                            };
                                            if let Ok(pk) = job_id.parse::<i32>() {
                                                if let Some(job) = self.jobs_state.jobs.iter_mut().find(|j| j.pk == pk) {
                                                    let old_state = job.state;
                                                    if old_state != new_state {
                                                        job.state = new_state;
                                                        self.jobs_state.changed_pks.insert(pk);
                                                        info!("Job {} status: {:?} -> {:?}", pk, old_state, new_state);
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        debug!("JSON-RPC error for job status {}: {}", job_id, e);
                                    }
                                }
                            }
                            Err(e) => {
                                debug!("Bridge dispatch failed for job status {}: {}", job_id, e);
                            }
                        }
                    } else {
                        // Fallback: log unhandled RPC responses
                        match result {
                            Ok(rpc_response) => {
                                if rpc_response.is_error() {
                                    warn!(
                                        "Unhandled JSON-RPC error for request {}: {:?}",
                                        request_id, rpc_response.error
                                    );
                                } else {
                                    debug!(
                                        "Unhandled JSON-RPC success for request {}: {:?}",
                                        request_id, rpc_response.result
                                    );
                                }
                            }
                            Err(e) => {
                                error!(
                                    "Unhandled JSON-RPC dispatch error for request {}: {}",
                                    request_id, e
                                );
                            }
                        }
                    }
                }
            }
            self.mark_dirty();
        }
    }

    /// Poll for job status updates (non-blocking, time-gated).
    ///
    /// Sends status requests for active (non-terminal) jobs every 30 seconds.
    /// This keeps the TUI synchronized with actual job states on the workflow engine.
    pub fn poll_job_statuses(&mut self) {
        use crate::bridge::JsonRpcRequest;
        use crate::models::JobState;

        // Only poll if enough time has passed
        if self.last_job_poll.elapsed() < self.poll_interval {
            return;
        }

        // Get jobs in non-terminal states (active jobs)
        let active_jobs: Vec<String> = self
            .jobs_state
            .jobs
            .iter()
            .filter(|j| {
                matches!(
                    j.state,
                    JobState::Created | JobState::Submitted | JobState::Queued | JobState::Running
                )
            })
            .map(|j| j.pk.to_string())
            .collect();

        if active_jobs.is_empty() {
            // Reset poll timer even when no active jobs, to avoid immediate poll when a new job starts
            self.last_job_poll = std::time::Instant::now();
            return;
        }

        // Send status request for each active job
        for job_id in active_jobs {
            // Skip if we already have a pending request for this job
            if self.pending_status_requests.contains_key(&job_id) {
                continue;
            }

            self.status_request_counter += 1;
            let request_id = self.status_request_counter;

            // Send JSON-RPC request: jobs.status with {"job_id": job_id}
            let params = serde_json::json!({"job_id": job_id.clone()});
            let rpc_request = JsonRpcRequest::new("jobs.status", params, request_id as u64);
            if let Err(e) = self.bridge.request_rpc(rpc_request, request_id) {
                warn!("Failed to send status request for job {}: {}", job_id, e);
                continue;
            }
            self.pending_status_requests.insert(job_id.clone(), request_id);
            debug!("Sent status request for job {} (request_id: {})", job_id, request_id);
        }

        self.last_job_poll = std::time::Instant::now();
    }

    /// Update a job from a status poll response.
    ///
    /// Called when a jobs.status RPC response is received. Updates the job's
    /// state and clears the pending request tracker.
    #[allow(dead_code)]
    fn update_job_from_status(&mut self, job_id: &str, status: crate::models::JobState) {
        // Remove from pending requests
        self.pending_status_requests.remove(job_id);

        // Find and update the job
        if let Ok(pk) = job_id.parse::<i32>() {
            if let Some(job) = self.jobs_state.jobs.iter_mut().find(|j| j.pk == pk) {
                let old_state = job.state;
                if old_state != status {
                    job.state = status;
                    self.jobs_state.changed_pks.insert(pk);
                    info!("Job {} status: {:?} -> {:?}", pk, old_state, status);
                    self.mark_dirty();
                }
            }
        }
    }

    /// Convenience method that triggers an async job refresh.
    /// Kept for backwards compatibility with existing call sites.
    pub fn try_refresh_jobs(&mut self) {
        self.request_refresh_jobs();
    }

    /// Convenience method that triggers an async cluster list refresh.
    /// Called at startup to populate the cluster list for SLURM access.
    pub fn try_refresh_clusters(&mut self) {
        self.request_fetch_clusters();
    }

    /// Get the currently selected job.
    pub fn selected_job(&self) -> Option<&JobStatus> {
        self.jobs_state
            .selected_index
            .and_then(|idx| self.jobs_state.jobs.get(idx))
    }

    /// Select the previous job in the list.
    pub fn select_prev_job(&mut self) {
        if let Some(idx) = self.jobs_state.selected_index {
            if idx > 0 {
                self.jobs_state.selected_index = Some(idx - 1);
                self.mark_dirty();
            }
        }
    }

    /// Select the next job in the list.
    pub fn select_next_job(&mut self) {
        if let Some(idx) = self.jobs_state.selected_index {
            if idx + 1 < self.jobs_state.jobs.len() {
                self.jobs_state.selected_index = Some(idx + 1);
                self.mark_dirty();
            }
        }
    }

    /// Select the first job.
    pub fn select_first_job(&mut self) {
        if !self.jobs_state.jobs.is_empty() && self.jobs_state.selected_index != Some(0) {
            self.jobs_state.selected_index = Some(0);
            self.mark_dirty();
        }
    }

    /// Select the last job.
    pub fn select_last_job(&mut self) {
        let last = self.jobs_state.jobs.len().saturating_sub(1);
        if !self.jobs_state.jobs.is_empty() && self.jobs_state.selected_index != Some(last) {
            self.jobs_state.selected_index = Some(last);
            self.mark_dirty();
        }
    }

    // ===== Job Cancel Confirmation =====

    /// Cancel confirmation timeout (3 seconds).
    const CANCEL_CONFIRM_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(3);

    /// Request to cancel the selected job.
    ///
    /// Two-key confirmation flow:
    /// - First press: sets pending_cancel_pk and shows confirmation prompt
    /// - Second press within 3s: actually cancels the job
    /// - Different job or timeout: resets confirmation state
    pub fn request_cancel_selected_job(&mut self) {
        let Some(job) = self.selected_job() else {
            return;
        };

        let pk = job.pk;
        let job_name = job.name.clone();

        // Check if this is a confirmation of the same job
        if let Some(pending_pk) = self.jobs_state.pending_cancel_pk {
            if pending_pk == pk {
                // Second press - actually cancel
                self.confirm_cancel_job(pk);
                return;
            }
        }

        // First press or different job - set up confirmation
        self.jobs_state.pending_cancel_pk = Some(pk);
        self.jobs_state.pending_cancel_time = Some(std::time::Instant::now());
        self.set_error(format!(
            "Press 'c' again to cancel job {} ({})",
            pk, job_name
        ));
        self.mark_dirty();
    }

    /// Actually cancel the job after confirmation.
    fn confirm_cancel_job(&mut self, pk: i32) {
        // Clear confirmation state
        self.jobs_state.pending_cancel_pk = None;
        self.jobs_state.pending_cancel_time = None;

        // Don't request if another request is pending
        if self.pending_bridge_request.is_some() {
            self.set_error("Please wait for pending operation to complete");
            return;
        }

        let request_id = self.next_request_id();
        match self.bridge.request_cancel_job(pk, request_id) {
            Ok(()) => {
                self.pending_bridge_request = Some(BridgeRequestKind::CancelJob);
                self.pending_request_id = Some(request_id);
                self.pending_bridge_request_time = Some(std::time::Instant::now());
                info!("Cancel request sent for job {}", pk);
            }
            Err(e) => {
                self.set_error(format!("Failed to cancel job: {}", e));
            }
        }
        self.mark_dirty();
    }

    /// Clear pending cancel confirmation (on timeout or explicit clear).
    fn clear_cancel_confirmation(&mut self) {
        if self.jobs_state.pending_cancel_pk.is_some() {
            self.jobs_state.pending_cancel_pk = None;
            self.jobs_state.pending_cancel_time = None;
            self.clear_error();
            self.mark_dirty();
        }
    }

    /// Check if cancel confirmation has expired.
    fn maybe_clear_cancel_confirmation(&mut self) {
        if let Some(cancel_time) = self.jobs_state.pending_cancel_time {
            if cancel_time.elapsed() > Self::CANCEL_CONFIRM_TIMEOUT {
                self.clear_cancel_confirmation();
            }
        }
    }

    // ===== Job Submit from Editor =====

    /// Submit confirmation timeout (3 seconds).
    const SUBMIT_CONFIRM_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(3);

    /// Request to submit job from editor content.
    ///
    /// Two-key confirmation flow:
    /// - First Ctrl+Enter: sets pending_submit and shows confirmation prompt
    /// - Second Ctrl+Enter within 3s: actually submits the job
    /// - Timeout: resets confirmation state
    pub fn request_submit_from_editor(&mut self) {
        // Check if editor has content
        let content = self.editor.lines().join("\n");
        if content.trim().is_empty() {
            self.set_error("Editor is empty - nothing to submit");
            return;
        }

        // Check if this is a confirmation
        if self.jobs_state.pending_submit {
            // Second press - actually submit
            self.confirm_submit_job();
            return;
        }

        // First press - set up confirmation
        self.jobs_state.pending_submit = true;
        self.jobs_state.pending_submit_time = Some(std::time::Instant::now());

        // Generate job name from file path or content
        let job_name = self
            .editor_file_path
            .as_ref()
            .map(|p| {
                std::path::Path::new(p)
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or("untitled")
                    .to_string()
            })
            .unwrap_or_else(|| "untitled".to_string());

        self.set_error(format!(
            "Press Ctrl+Enter again to submit '{}' ({} chars)",
            job_name,
            content.len()
        ));
        self.mark_dirty();
    }

    /// Actually submit the job after confirmation.
    fn confirm_submit_job(&mut self) {
        use crate::models::{DftCode, JobSubmission};

        // Clear confirmation state
        self.jobs_state.pending_submit = false;
        self.jobs_state.pending_submit_time = None;

        // Don't request if another request is pending
        if self.pending_bridge_request.is_some() {
            self.set_error("Please wait for pending operation to complete");
            return;
        }

        // Build job submission
        let content = self.editor.lines().join("\n");
        let job_name = self
            .editor_file_path
            .as_ref()
            .map(|p| {
                std::path::Path::new(p)
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or("untitled")
                    .to_string()
            })
            .unwrap_or_else(|| format!("job_{}", chrono::Utc::now().format("%Y%m%d_%H%M%S")));

        // Determine DFT code from file extension or editor_dft_code
        let dft_code = self
            .editor_dft_code
            .as_ref()
            .map(|code| match code {
                DftCodeType::Crystal => DftCode::Crystal,
                DftCodeType::Vasp => DftCode::Vasp,
            })
            .unwrap_or(DftCode::Crystal); // Default to Crystal

        let submission = JobSubmission::new(&job_name, dft_code).with_input_content(&content);

        let request_id = self.next_request_id();
        match self.bridge.request_submit_job(&submission, request_id) {
            Ok(()) => {
                self.pending_bridge_request = Some(BridgeRequestKind::SubmitJob);
                self.pending_request_id = Some(request_id);
                self.pending_bridge_request_time = Some(std::time::Instant::now());
                info!("Submit request sent for job '{}'", job_name);
                self.clear_error();
            }
            Err(e) => {
                self.set_error(format!("Failed to submit job: {}", e));
            }
        }
        self.mark_dirty();
    }

    /// Clear pending submit confirmation (on timeout or explicit clear).
    fn clear_submit_confirmation(&mut self) {
        if self.jobs_state.pending_submit {
            self.jobs_state.pending_submit = false;
            self.jobs_state.pending_submit_time = None;
            self.clear_error();
            self.mark_dirty();
        }
    }

    /// Check if submit confirmation has expired.
    fn maybe_clear_submit_confirmation(&mut self) {
        if let Some(submit_time) = self.jobs_state.pending_submit_time {
            if submit_time.elapsed() > Self::SUBMIT_CONFIRM_TIMEOUT {
                self.clear_submit_confirmation();
            }
        }
    }

    // ===== Job Diff View =====

    /// Handle 'd' key press for job diff comparison.
    ///
    /// Two-step flow:
    /// - First 'd': Select current job as diff base
    /// - Second 'd' on different job: Show diff between base and current
    pub fn request_diff_job(&mut self) {
        let Some(job) = self.selected_job() else {
            return;
        };

        let pk = job.pk;
        let job_name = job.name.clone();

        // Check if we already have a base selected
        if let Some(base_pk) = self.jobs_state.diff_base_pk {
            if base_pk == pk {
                // Same job - clear selection
                self.jobs_state.diff_base_pk = None;
                self.clear_error();
                self.set_error("Diff selection cleared");
            } else {
                // Different job - show diff
                // For now, show a placeholder since we'd need input_content from both jobs
                self.set_error(format!(
                    "Diff: Job {} vs Job {} (requires input_content)",
                    base_pk, pk
                ));
                // TODO: Fetch input_content for both jobs and compute diff
                // This would require adding a request_job_input_content method to bridge
                self.jobs_state.diff_base_pk = None;
            }
        } else {
            // First selection - mark as base
            self.jobs_state.diff_base_pk = Some(pk);
            self.set_error(format!(
                "Diff base: {} (pk={}). Press 'd' on another job to compare",
                job_name, pk
            ));
        }
        self.mark_dirty();
    }

    /// Close the diff view modal.
    #[allow(dead_code)] // Planned for job diff feature
    pub fn close_diff_view(&mut self) {
        self.jobs_state.diff_view_active = false;
        self.jobs_state.diff_lines.clear();
        self.jobs_state.diff_scroll = 0;
        self.mark_dirty();
    }

    /// Scroll diff view up.
    #[allow(dead_code)] // Planned for job diff feature
    pub fn scroll_diff_up(&mut self) {
        if self.jobs_state.diff_scroll > 0 {
            self.jobs_state.diff_scroll -= 1;
            self.mark_dirty();
        }
    }

    /// Scroll diff view down.
    #[allow(dead_code)] // Planned for job diff feature
    pub fn scroll_diff_down(&mut self) {
        let max = self.jobs_state.diff_lines.len().saturating_sub(20);
        if self.jobs_state.diff_scroll < max {
            self.jobs_state.diff_scroll += 1;
            self.mark_dirty();
        }
    }

    // ===== SLURM Queue Management =====

    /// Toggle SLURM queue view visibility.
    ///
    /// Opens the SLURM queue modal if clusters are configured.
    /// Prefers the last-used SLURM cluster, or the first available one.
    pub fn toggle_slurm_view(&mut self) {
        tracing::info!("toggle_slurm_view() called");
        tracing::info!(
            "  slurm_queue_state.active = {}",
            self.slurm_queue_state.active
        );
        tracing::info!(
            "  cluster_manager.clusters.len() = {}",
            self.cluster_manager.clusters.len()
        );

        // If modal is already open, close it
        if self.slurm_queue_state.active {
            tracing::info!("  Closing SLURM modal");
            self.close_slurm_queue_modal();
            return;
        }

        // Find SLURM clusters
        let slurm_clusters: Vec<i32> = self
            .cluster_manager
            .clusters
            .iter()
            .filter(|c| {
                tracing::debug!("  Cluster: {:?}, type: {:?}", c.name, c.cluster_type);
                c.cluster_type == crate::models::ClusterType::Slurm
            })
            .filter_map(|c| c.id)
            .collect();

        tracing::info!(
            "  Found {} SLURM clusters: {:?}",
            slurm_clusters.len(),
            slurm_clusters
        );

        if slurm_clusters.is_empty() {
            tracing::warn!("  No SLURM clusters found!");
            self.set_error("No SLURM clusters configured. Press 'c' to open Cluster Manager.");
            return;
        }

        // Prefer last-used cluster if valid, otherwise use first
        let cluster_id = if let Some(last_id) = self.last_slurm_cluster_id {
            if slurm_clusters.contains(&last_id) {
                last_id
            } else {
                slurm_clusters[0]
            }
        } else {
            slurm_clusters[0]
        };

        tracing::info!("  Opening SLURM modal for cluster_id={}", cluster_id);
        self.open_slurm_queue_modal(cluster_id);
        self.mark_dirty();
    }

    /// Request SLURM queue fetch from bridge.
    pub fn request_fetch_slurm_queue(&mut self) {
        // Use the cluster ID from new_job state if selected, otherwise default to 1
        let cluster_id = self.new_job.cluster_id.unwrap_or(1);

        let request_id = self.next_request_id();
        self.slurm_request_id = request_id;

        if let Err(e) = self
            .bridge
            .request_fetch_slurm_queue(cluster_id, request_id)
        {
            self.set_error(format!("Failed to request SLURM queue: {}", e));
        }
    }

    /// Request to adopt a SLURM job.
    pub fn request_adopt_slurm_job(&mut self, cluster_id: i32, job_id: String) {
        let request_id = self.next_request_id();
        // We track this request ID in the modal state to handle the response
        self.slurm_queue_state.request_id = request_id;
        self.slurm_queue_state.loading = true;

        if let Err(e) = self
            .bridge
            .request_adopt_slurm_job(cluster_id, &job_id, request_id)
        {
            self.set_error(format!("Failed to request job adoption: {}", e));
            self.slurm_queue_state.loading = false;
        }
    }

    /// Handle SLURM queue response from bridge.
    pub fn handle_slurm_queue_response(&mut self, result: anyhow::Result<Vec<SlurmQueueEntry>>) {
        match result {
            Ok(entries) => {
                self.slurm_queue = entries;
                if self.slurm_queue.is_empty() {
                    self.set_error("SLURM queue: No jobs in queue");
                } else {
                    self.set_error(format!("SLURM queue: {} jobs", self.slurm_queue.len()));
                }
            }
            Err(e) => {
                self.set_error(format!("SLURM queue error: {}", e));
            }
        }
        self.mark_dirty();
    }

    /// Close the SLURM queue view.
    #[allow(dead_code)] // Planned for SLURM integration
    pub fn close_slurm_view(&mut self) {
        self.slurm_view_active = false;
        self.mark_dirty();
    }

    /// Select previous entry in SLURM queue.
    #[allow(dead_code)] // Planned for SLURM integration
    pub fn select_prev_slurm(&mut self) {
        if let Some(idx) = self.slurm_selected {
            if idx > 0 {
                self.slurm_selected = Some(idx - 1);
                self.mark_dirty();
            }
        }
    }

    /// Select next entry in SLURM queue.
    #[allow(dead_code)] // Planned for SLURM integration
    pub fn select_next_slurm(&mut self) {
        if let Some(idx) = self.slurm_selected {
            if idx + 1 < self.slurm_queue.len() {
                self.slurm_selected = Some(idx + 1);
                self.mark_dirty();
            }
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
    ///
    /// Delegates to `JobDetails::display_line_count()` which is the single source
    /// of truth for content height, matching src/ui/results.rs rendering.
    fn results_content_length(&self) -> usize {
        self.current_job_details
            .as_ref()
            .map(|details| details.display_line_count())
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
        self.log_lines
            .len()
            .saturating_sub(ESTIMATED_VISIBLE_HEIGHT)
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

    // ===== Log Streaming =====

    /// Request log refresh for a specific job (non-blocking).
    ///
    /// Loads the last 100 lines of the job's output log.
    /// If follow mode is active, this is called automatically every 2s.
    pub fn request_log_refresh(&mut self, pk: i32) {
        // Don't request if another request is pending
        if self.pending_bridge_request.is_some() {
            return;
        }

        let request_id = self.next_request_id();
        match self.bridge.request_fetch_job_log(pk, 100, request_id) {
            Ok(()) => {
                self.pending_bridge_request = Some(BridgeRequestKind::FetchJobLog);
                self.pending_request_id = Some(request_id);
                self.pending_bridge_request_time = Some(std::time::Instant::now());
                self.log_job_pk = Some(pk);
                self.last_log_refresh = Some(std::time::Instant::now());
            }
            Err(e) => {
                self.set_error(format!("Failed to request log: {}", e));
            }
        }
    }

    /// Toggle log follow mode on/off.
    ///
    /// When enabled, the log view auto-refreshes every 2 seconds
    /// and auto-scrolls to the bottom to show new output.
    pub fn toggle_log_follow(&mut self) {
        self.log_follow_mode = !self.log_follow_mode;
        if self.log_follow_mode {
            // Start following - immediately refresh and scroll to bottom
            if let Some(pk) = self.log_job_pk {
                self.request_log_refresh(pk);
            }
            self.scroll_log_bottom();
            info!("Log follow mode enabled");
        } else {
            info!("Log follow mode disabled");
        }
        self.mark_dirty();
    }

    /// Check if log follow mode should trigger a refresh.
    ///
    /// Called by tick() to handle follow mode timing.
    fn maybe_refresh_log(&mut self) {
        const LOG_FOLLOW_INTERVAL: std::time::Duration = std::time::Duration::from_secs(2);

        if !self.log_follow_mode {
            return;
        }

        // Only refresh if we're on the Log tab
        if self.current_tab != AppTab::Log {
            return;
        }

        // Only refresh if we have a job to monitor
        let Some(pk) = self.log_job_pk else {
            return;
        };

        // Check if enough time has passed since last refresh
        if let Some(last_refresh) = self.last_log_refresh {
            if last_refresh.elapsed() < LOG_FOLLOW_INTERVAL {
                return;
            }
        }

        // Trigger refresh
        self.request_log_refresh(pk);
    }

    /// Load log for the selected job and switch to Log tab.
    ///
    /// Called when user presses a key to view logs.
    pub fn view_job_log(&mut self) {
        if let Some(job) = self.selected_job() {
            let pk = job.pk;
            let name = job.name.clone();
            self.log_job_pk = Some(pk);
            self.log_job_name = Some(name);
            self.log_lines.clear();
            self.log_scroll = 0;
            self.request_log_refresh(pk);
            self.set_tab(AppTab::Log);
        }
    }

    // ===== Editor =====

    /// Open a file in the editor with LSP support.
    #[allow(dead_code)] // Planned for file browser feature
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
    /// Handles LSP debounce, log follow mode auto-refresh, and cancel confirmation timeout.
    pub fn tick(&mut self) {
        const LSP_DEBOUNCE_MS: u128 = 200;

        // LSP change debounce
        if self.pending_lsp_change {
            if let Some(change_time) = self.last_editor_change {
                if change_time.elapsed().as_millis() >= LSP_DEBOUNCE_MS {
                    self.flush_lsp_change();
                }
            }
        }

        // Log follow mode auto-refresh
        self.maybe_refresh_log();

        // Cancel confirmation timeout
        self.maybe_clear_cancel_confirmation();

        // Submit confirmation timeout
        self.maybe_clear_submit_confirmation();
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
    #[allow(dead_code)] // Planned for file save feature
    pub fn editor_content(&self) -> String {
        self.editor.lines().join("\n")
    }

    // ===== Materials Project Modal =====

    /// Open the Materials Project search modal.
    pub fn open_materials_modal(&mut self) {
        self.materials.open();
        self.mark_dirty();
    }

    /// Close the Materials Project search modal.
    pub fn close_materials_modal(&mut self) {
        self.materials.close();
        self.mark_dirty();
    }

    /// Request a materials search by formula (non-blocking).
    ///
    /// The search runs asynchronously via the Python bridge.
    /// Results are delivered via `poll_bridge_responses()`.
    pub fn request_materials_search(&mut self) {
        let formula = self.materials.query();
        if formula.is_empty() {
            self.materials.set_status("Please enter a formula", true);
            self.mark_dirty();
            return;
        }

        // Increment request ID to track this search
        self.materials.request_id += 1;
        self.materials.loading = true;
        self.materials
            .set_status(&format!("Searching for {}...", formula), false);
        self.mark_dirty();

        match self.bridge.request_search_materials(
            &formula,
            20, // limit
            self.materials.request_id,
        ) {
            Ok(()) => {
                debug!("Materials search requested: {}", formula);
            }
            Err(e) => {
                self.materials.loading = false;
                self.materials
                    .set_status(&format!("Search failed: {}", e), true);
            }
        }
    }

    /// Request D12 generation for the selected material (non-blocking).
    ///
    /// Generates a CRYSTAL23 .d12 input file from the selected Materials Project structure.
    /// The result is delivered via `poll_bridge_responses()`.
    pub fn request_generate_d12(&mut self) {
        let Some(material) = self.materials.selected_material() else {
            self.materials
                .set_status("Please select a structure first", true);
            self.mark_dirty();
            return;
        };

        let mp_id = material.material_id.clone();
        let formula = material
            .formula
            .clone()
            .or_else(|| material.formula_pretty.clone())
            .unwrap_or_else(|| "unknown".to_string());

        // Increment request ID to track this generation
        self.materials.request_id += 1;
        self.materials.loading = true;
        self.materials.selected_for_import = Some(mp_id.clone());
        self.materials.set_status(
            &format!("Generating CRYSTAL23 input for {}...", formula),
            false,
        );
        self.mark_dirty();

        // Serialize config to JSON
        let config_json = match serde_json::to_string(&self.materials.d12_config) {
            Ok(json) => json,
            Err(e) => {
                self.materials.loading = false;
                self.materials.selected_for_import = None;
                self.materials
                    .set_status(&format!("Config error: {}", e), true);
                return;
            }
        };

        match self
            .bridge
            .request_generate_d12(&mp_id, &config_json, self.materials.request_id)
        {
            Ok(()) => {
                info!("D12 generation requested for {}", mp_id);
            }
            Err(e) => {
                self.materials.loading = false;
                self.materials.selected_for_import = None;
                self.materials
                    .set_status(&format!("Generation failed: {}", e), true);
            }
        }
    }

    /// Request VASP input generation for the selected material (non-blocking).
    ///
    /// Generates VASP input files (POSCAR, INCAR, KPOINTS) from the selected
    /// Materials Project structure. The result is delivered via `poll_bridge_responses()`.
    pub fn request_generate_vasp_from_mp(&mut self) {
        use crate::bridge::JsonRpcRequest;

        let Some(material) = self.materials.selected_material() else {
            self.materials
                .set_status("Please select a structure first", true);
            self.mark_dirty();
            return;
        };

        let mp_id = material.material_id.clone();
        let formula = material
            .formula
            .clone()
            .or_else(|| material.formula_pretty.clone())
            .unwrap_or_else(|| "unknown".to_string());

        // Use VASP-specific request ID
        self.vasp_request_id = self.next_request_id();
        self.materials.loading = true;
        self.materials.selected_for_import = Some(mp_id.clone());
        self.materials.set_status(
            &format!("Generating VASP inputs for {}...", formula),
            false,
        );
        self.mark_dirty();

        // Serialize config to JSON
        let config_json = match serde_json::to_string(&self.materials.vasp_config) {
            Ok(json) => json,
            Err(e) => {
                self.materials.loading = false;
                self.materials.selected_for_import = None;
                self.materials
                    .set_status(&format!("Config error: {}", e), true);
                return;
            }
        };

        // Build JSON-RPC request params
        let params = serde_json::json!({
            "mp_id": mp_id,
            "config_json": config_json
        });

        let rpc_request = JsonRpcRequest::new(
            "vasp.generate_from_mp",
            params,
            self.vasp_request_id as u64,
        );

        match self.bridge.request_rpc(rpc_request, self.vasp_request_id) {
            Ok(()) => {
                info!("VASP generation requested for {} (id={})", mp_id, self.vasp_request_id);
            }
            Err(e) => {
                self.materials.loading = false;
                self.materials.selected_for_import = None;
                self.materials
                    .set_status(&format!("Generation failed: {}", e), true);
            }
        }
    }

    /// Request quacc job submission for the selected VASP input (non-blocking).
    ///
    /// Submits the generated POSCAR to quacc's jobs.submit endpoint.
    /// The result is delivered via `poll_bridge_responses()`.
    pub fn request_submit_quacc_job(&mut self) {
        use crate::bridge::JsonRpcRequest;
        use crate::models::QuaccJobSubmitRequest;

        // Check we have generated POSCAR content
        let poscar = match &self.materials.generated_poscar {
            Some(p) => p.clone(),
            None => {
                self.materials.submit_failure("No structure available. Generate VASP inputs first.".to_string());
                self.mark_dirty();
                return;
            }
        };

        // Get selected cluster name (or default to "local")
        let cluster_name = if self.quacc_clusters.is_empty() {
            None
        } else {
            let idx = self.materials.selected_cluster_idx % self.quacc_clusters.len();
            Some(self.quacc_clusters[idx].name.clone())
        };

        // Set up submit request
        self.submit_request_id = self.next_request_id();
        self.materials.submit_request_id = self.submit_request_id;
        self.materials.start_submit();
        self.materials.set_status("Submitting job to quacc...", false);
        self.mark_dirty();

        // Build submit request
        let submit_request = QuaccJobSubmitRequest {
            recipe: "quacc.recipes.vasp.core.static_job".to_string(), // Default recipe
            structure: poscar,
            cluster: cluster_name,
            params: serde_json::json!({}),
        };

        // Serialize and send
        let params = match serde_json::to_value(&submit_request) {
            Ok(v) => v,
            Err(e) => {
                self.materials.submit_failure(format!("Serialization error: {}", e));
                return;
            }
        };

        let rpc_request = JsonRpcRequest::new(
            "jobs.submit",
            params,
            self.submit_request_id as u64,
        );

        match self.bridge.request_rpc(rpc_request, self.submit_request_id) {
            Ok(()) => {
                info!("Job submission requested (id={})", self.submit_request_id);
            }
            Err(e) => {
                self.materials.submit_failure(format!("Submission failed: {}", e));
            }
        }
    }

    /// Request structure preview for the selected material (non-blocking).
    ///
    /// Fetches detailed structure information (formula, lattice, symmetry) for display
    /// in the materials modal preview panel.
    pub fn request_structure_preview(&mut self) {
        use crate::bridge::JsonRpcRequest;

        let Some(material) = self.materials.selected_material() else {
            // No selection, clear any existing preview
            self.materials.clear_preview();
            self.mark_dirty();
            return;
        };

        let mp_id = material.material_id.clone();

        // Set up preview request
        self.materials.preview_request_id = self.next_request_id();
        self.materials.set_preview_loading(true);
        self.mark_dirty();

        // Build JSON-RPC request params
        let params = serde_json::json!({
            "source_type": "mp_id",
            "source_data": mp_id
        });

        let rpc_request = JsonRpcRequest::new(
            "structures.preview",
            params,
            self.materials.preview_request_id as u64,
        );

        if let Err(e) = self
            .bridge
            .request_rpc(rpc_request, self.materials.preview_request_id)
        {
            self.materials.preview_loading = false;
            debug!("Structure preview request failed: {}", e);
        } else {
            debug!(
                "Structure preview requested for {} (id={})",
                mp_id, self.materials.preview_request_id
            );
        }
    }

    /// Check if the materials modal is active.
    pub fn is_materials_modal_active(&self) -> bool {
        self.materials.active
    }

    // ===== New Job Modal =====

    /// Check if the new job modal is active.
    pub fn is_new_job_modal_active(&self) -> bool {
        self.new_job.active
    }

    /// Open the new job modal.
    pub fn open_new_job_modal(&mut self) {
        self.new_job.open();
        self.mark_dirty();
    }

    /// Close the new job modal.
    pub fn close_new_job_modal(&mut self) {
        self.new_job.close();
        self.mark_dirty();
    }

    /// Submit the new job from the modal.
    ///
    /// Uses the editor content as input and metadata from the modal form.
    pub fn submit_new_job(&mut self) {
        // Validate the form
        if let Err(e) = self.new_job.validate_name() {
            self.new_job.set_error(e);
            self.mark_dirty();
            return;
        }

        // Get editor content
        let content = self.editor.lines().join("\n");
        if content.trim().is_empty() {
            self.new_job
                .set_error("Editor is empty - add input content first");
            self.mark_dirty();
            return;
        }

        // Build submission
        let mut submission =
            crate::models::JobSubmission::new(&self.new_job.job_name, self.new_job.dft_code)
                .with_input_content(&content)
                .with_runner_type(self.new_job.runner_type);

        if let Some(cluster_id) = self.new_job.cluster_id {
            submission = submission.with_cluster_id(cluster_id);
        }

        // Add parallelism settings
        if self.new_job.is_parallel {
            submission = submission.with_parallel_mode("parallel");
            if let Ok(ranks) = self.new_job.mpi_ranks.parse::<i32>() {
                submission = submission.with_mpi_ranks(ranks);
            }
        } else {
            submission = submission.with_parallel_mode("serial");
        }

        // Add scheduler settings if SLURM
        if self.new_job.runner_type == crate::models::RunnerType::Slurm {
            let options = crate::models::SchedulerOptions {
                walltime: self.new_job.walltime.clone(),
                memory_gb: self.new_job.memory_gb.clone(),
                cpus_per_task: self.new_job.cpus_per_task.parse().unwrap_or(4),
                nodes: self.new_job.nodes.parse().unwrap_or(1),
                partition: if self.new_job.partition.is_empty() {
                    None
                } else {
                    Some(self.new_job.partition.clone())
                },
            };
            submission = submission.with_scheduler_options(options);
        }

        // Add aux files if Crystal
        if self.new_job.dft_code == crate::models::DftCode::Crystal {
            let mut aux = std::collections::HashMap::new();
            if self.new_job.aux_gui_enabled && !self.new_job.aux_gui_path.is_empty() {
                aux.insert("gui".to_string(), self.new_job.aux_gui_path.clone());
            }
            if self.new_job.aux_f9_enabled && !self.new_job.aux_f9_path.is_empty() {
                aux.insert("f9".to_string(), self.new_job.aux_f9_path.clone());
            }
            if self.new_job.aux_hessopt_enabled && !self.new_job.aux_hessopt_path.is_empty() {
                aux.insert("hessopt".to_string(), self.new_job.aux_hessopt_path.clone());
            }

            if !aux.is_empty() {
                submission = submission.with_auxiliary_files(aux);
            }
        }

        // Submit via bridge
        let request_id = self.next_request_id();
        if let Err(e) = self.bridge.request_submit_job(&submission, request_id) {
            self.new_job.set_error(&format!("Failed to submit: {}", e));
            self.mark_dirty();
            return;
        }

        // Mark as submitting
        self.new_job.submitting = true;
        self.pending_bridge_request = Some(BridgeRequestKind::SubmitJob);
        self.pending_request_id = Some(request_id);
        self.pending_bridge_request_time = Some(std::time::Instant::now());
        self.mark_dirty();

        // Close modal (response will be handled in poll_bridge_responses)
        self.new_job.close();
    }

    // ===== Cluster Manager Modal =====

    /// Check if the cluster manager modal is active.
    pub fn is_cluster_manager_modal_active(&self) -> bool {
        self.cluster_manager.active
    }

    /// Open the cluster manager modal and request cluster list.
    pub fn open_cluster_manager_modal(&mut self) {
        self.cluster_manager.open();
        self.request_fetch_clusters();
        self.mark_dirty();
    }

    /// Close the cluster manager modal.
    pub fn close_cluster_manager_modal(&mut self) {
        self.cluster_manager.close();
        self.mark_dirty();
    }

    /// Request the list of clusters from the backend.
    pub fn request_fetch_clusters(&mut self) {
        let request_id = self.next_request_id();
        self.cluster_manager.request_id = request_id;
        self.cluster_manager.loading = true;
        if let Err(e) = self.bridge.request_fetch_clusters(request_id) {
            self.cluster_manager
                .set_status(&format!("Failed to fetch clusters: {}", e), true);
            self.cluster_manager.loading = false;
        }
        self.mark_dirty();
    }

    /// Request to create a new cluster from form data.
    pub fn create_cluster_from_form(&mut self) {
        match self.cluster_manager.build_config() {
            Ok(config) => {
                let request_id = self.next_request_id();
                self.cluster_manager.request_id = request_id;
                self.cluster_manager.loading = true;
                if let Err(e) = self.bridge.request_create_cluster(&config, request_id) {
                    self.cluster_manager
                        .set_status(&format!("Failed to create cluster: {}", e), true);
                    self.cluster_manager.loading = false;
                }
                self.mark_dirty();
            }
            Err(e) => {
                self.cluster_manager.set_status(&e, true);
                self.mark_dirty();
            }
        }
    }

    /// Request to update an existing cluster from form data.
    pub fn update_cluster_from_form(&mut self) {
        let cluster_id = match self.cluster_manager.editing_cluster_id {
            Some(id) => id,
            None => {
                self.cluster_manager
                    .set_status("No cluster selected for editing", true);
                self.mark_dirty();
                return;
            }
        };

        match self.cluster_manager.build_config() {
            Ok(config) => {
                let request_id = self.next_request_id();
                self.cluster_manager.request_id = request_id;
                self.cluster_manager.loading = true;
                if let Err(e) = self
                    .bridge
                    .request_update_cluster(cluster_id, &config, request_id)
                {
                    self.cluster_manager
                        .set_status(&format!("Failed to update cluster: {}", e), true);
                    self.cluster_manager.loading = false;
                }
                self.mark_dirty();
            }
            Err(e) => {
                self.cluster_manager.set_status(&e, true);
                self.mark_dirty();
            }
        }
    }

    /// Request to delete the selected cluster.
    pub fn delete_selected_cluster(&mut self) {
        let cluster_id = match self.cluster_manager.selected_cluster() {
            Some(c) => match c.id {
                Some(id) => id,
                None => {
                    self.cluster_manager.set_status("Cluster has no ID", true);
                    self.mark_dirty();
                    return;
                }
            },
            None => {
                self.cluster_manager.set_status("No cluster selected", true);
                self.mark_dirty();
                return;
            }
        };

        let request_id = self.next_request_id();
        self.cluster_manager.request_id = request_id;
        self.cluster_manager.loading = true;
        if let Err(e) = self.bridge.request_delete_cluster(cluster_id, request_id) {
            self.cluster_manager
                .set_status(&format!("Failed to delete cluster: {}", e), true);
            self.cluster_manager.loading = false;
        }
        self.mark_dirty();
    }

    /// Request to test SSH connection to the selected cluster.
    pub fn test_selected_cluster_connection(&mut self) {
        let cluster_id = match self.cluster_manager.selected_cluster() {
            Some(c) => match c.id {
                Some(id) => id,
                None => {
                    self.cluster_manager.set_status("Cluster has no ID", true);
                    self.mark_dirty();
                    return;
                }
            },
            None => {
                self.cluster_manager.set_status("No cluster selected", true);
                self.mark_dirty();
                return;
            }
        };

        let request_id = self.next_request_id();
        self.cluster_manager.request_id = request_id;
        self.cluster_manager.loading = true;
        self.cluster_manager.connection_result = None;
        self.cluster_manager
            .set_status("Testing connection...", false);
        if let Err(e) = self
            .bridge
            .request_test_cluster_connection(cluster_id, request_id)
        {
            self.cluster_manager
                .set_status(&format!("Failed to test connection: {}", e), true);
            self.cluster_manager.loading = false;
        }
        self.mark_dirty();
    }

    // ===== SLURM Queue Modal =====

    /// Check if the SLURM queue modal is active.
    pub fn is_slurm_queue_modal_active(&self) -> bool {
        self.slurm_queue_state.active
    }

    /// Open the SLURM queue modal for a given cluster and request queue fetch.
    pub fn open_slurm_queue_modal(&mut self, cluster_id: i32) {
        self.slurm_queue_state.open(cluster_id);
        self.last_slurm_cluster_id = Some(cluster_id); // Remember for 's' hotkey preference
        self.request_fetch_slurm_queue_for_cluster(cluster_id);
        self.mark_dirty();
    }

    /// Close the SLURM queue modal.
    pub fn close_slurm_queue_modal(&mut self) {
        self.slurm_queue_state.close();
        self.mark_dirty();
    }

    /// Request SLURM queue for a specific cluster.
    fn request_fetch_slurm_queue_for_cluster(&mut self, cluster_id: i32) {
        let request_id = self.next_request_id();
        self.slurm_queue_state.request_id = request_id;
        self.slurm_queue_state.loading = true;
        self.slurm_queue_state.error = None;

        if let Err(e) = self
            .bridge
            .request_fetch_slurm_queue(cluster_id, request_id)
        {
            self.slurm_queue_state.error = Some(format!("Failed to fetch SLURM queue: {}", e));
            self.slurm_queue_state.loading = false;
        }
        self.mark_dirty();
    }

    /// Refresh the SLURM queue for the currently selected cluster.
    pub fn refresh_slurm_queue(&mut self) {
        if let Some(cluster_id) = self.slurm_queue_state.cluster_id {
            self.request_fetch_slurm_queue_for_cluster(cluster_id);
        }
    }

    /// Cancel the selected SLURM job.
    pub fn cancel_selected_slurm_job_from_modal(&mut self) {
        if let Some(cluster_id) = self.slurm_queue_state.cluster_id {
            if let Some(entry) = self.slurm_queue_state.selected_entry(&self.slurm_queue) {
                let job_id = entry.job_id.clone();
                let request_id = self.next_request_id();

                self.slurm_queue_state.loading = true;
                self.slurm_queue_state.error = Some(format!("Cancelling job {}...", job_id));

                if let Err(e) = self
                    .bridge
                    .request_cancel_slurm_job(cluster_id, &job_id, request_id)
                {
                    self.slurm_queue_state.error = Some(format!("Failed to cancel job: {}", e));
                    self.slurm_queue_state.loading = false;
                }
                self.mark_dirty();
            }
        }
    }

    /// Adopt the selected SLURM job.
    pub fn adopt_selected_slurm_job(&mut self) {
        if let Some(entry) = self.slurm_queue_state.selected_entry(&self.slurm_queue) {
            if let Some(cluster_id) = self.slurm_queue_state.cluster_id {
                self.request_adopt_slurm_job(cluster_id, entry.job_id.clone());
            } else {
                self.set_error("No cluster selected");
            }
        }
    }

    // ===== VASP Input Modal =====

    /// Check if the VASP input modal is active.
    pub fn is_vasp_input_modal_active(&self) -> bool {
        self.vasp_input_state.active
    }

    /// Open the VASP input modal.
    pub fn open_vasp_input_modal(&mut self) {
        self.vasp_input_state.open();
        self.mark_dirty();
    }

    /// Close the VASP input modal.
    pub fn close_vasp_input_modal(&mut self) {
        self.vasp_input_state.close();
        self.mark_dirty();
    }

    /// Request VASP input validation (async).
    pub fn request_validate_vasp_inputs(&mut self) {
        use crate::bridge::JsonRpcRequest;

        // Get content from editors
        let files = self.vasp_input_state.get_contents();
        let inputs_json = match serde_json::to_string(&files) {
            Ok(json) => json,
            Err(e) => {
                self.vasp_input_state
                    .set_error(format!("Failed to serialize inputs: {}", e));
                self.mark_dirty();
                return;
            }
        };

        // Set up validation request
        self.vasp_input_state.validation_request_id = self.next_request_id();
        self.vasp_input_state.status = Some("Validating...".to_string());
        self.mark_dirty();

        let params = serde_json::json!({
            "inputs_json": inputs_json
        });

        let rpc_request = JsonRpcRequest::new(
            "vasp.validate_inputs",
            params,
            self.vasp_input_state.validation_request_id as u64,
        );

        if let Err(e) = self
            .bridge
            .request_rpc(rpc_request, self.vasp_input_state.validation_request_id)
        {
            self.vasp_input_state
                .set_error(format!("Validation request failed: {}", e));
        }
    }

    /// Submit VASP job from the modal.
    pub fn submit_vasp_job(&mut self) {
        // Validate input files
        if let Err(e) = self.vasp_input_state.validate() {
            self.vasp_input_state.set_error(e);
            self.mark_dirty();
            return;
        }

        // Extract content from all editors
        let files = self.vasp_input_state.get_contents();

        // Log the submission for now (TODO: integrate with Python backend)
        info!("Submitting VASP job:");
        info!("  POSCAR: {} lines", files.poscar.lines().count());
        info!("  INCAR: {} lines", files.incar.lines().count());
        info!("  KPOINTS: {} lines", files.kpoints.lines().count());
        info!("  POTCAR config: {}", files.potcar_config);

        // Convert VaspInputFiles to models::VaspInputFiles for JobSubmission
        let vasp_files = crate::models::VaspInputFiles {
            poscar: files.poscar.clone(),
            incar: files.incar.clone(),
            kpoints: files.kpoints.clone(),
            potcar_config: files.potcar_config.clone(),
        };

        // Serialize to JSON for parameters field
        let params = match serde_json::to_value(&vasp_files) {
            Ok(v) => v,
            Err(e) => {
                self.vasp_input_state
                    .set_error(format!("Failed to serialize VASP files: {}", e));
                self.mark_dirty();
                return;
            }
        };

        // Build JobSubmission with VASP files in parameters
        let job_name = format!("vasp-calc-{}", chrono::Utc::now().format("%Y%m%d-%H%M%S"));
        let submission = crate::models::JobSubmission::new(&job_name, crate::models::DftCode::Vasp)
            .with_parameters(params)
            .with_runner_type(crate::models::RunnerType::Local);

        // Submit via bridge
        let request_id = self.next_request_id();
        if let Err(e) = self.bridge.request_submit_job(&submission, request_id) {
            self.vasp_input_state
                .set_error(format!("Failed to submit: {}", e));
            self.mark_dirty();
            return;
        }

        self.pending_bridge_request = Some(BridgeRequestKind::SubmitJob);
        self.pending_request_id = Some(request_id);
        self.pending_bridge_request_time = Some(std::time::Instant::now());
        self.mark_dirty();

        // Close modal
        self.vasp_input_state.close();
    }

    // ===== LSP Events =====

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
                    // Show user-visible error
                    self.set_error(format!(
                        "Language server error: {}. Code validation disabled.",
                        err
                    ));
                    // Disable LSP client and clear diagnostics
                    self.lsp_client = None;
                    self.lsp_diagnostics.clear();
                    self.mark_dirty();
                }
            }
        }
    }

    // ===== Recipe Browser Modal =====

    /// Open the recipe browser modal and request recipes.
    pub fn open_recipe_browser(&mut self) {
        self.recipe_browser.open();
        self.request_load_recipes();
        self.mark_dirty();
    }

    /// Close the recipe browser modal.
    pub fn close_recipe_browser(&mut self) {
        self.recipe_browser.close();
        self.mark_dirty();
    }

    /// Check if the recipe browser modal is active.
    pub fn is_recipe_browser_active(&self) -> bool {
        self.recipe_browser.active
    }

    /// Request recipe list load via IPC (non-blocking).
    ///
    /// Sends recipes.list RPC call to fetch available quacc recipes.
    /// Also sends clusters.list to get workflow engine status.
    /// Results delivered via poll_bridge_responses().
    pub fn request_load_recipes(&mut self) {
        // Skip if not loading (open() sets loading = true)
        if !self.recipe_browser.loading {
            return;
        }

        // Increment request ID for this recipe fetch
        self.recipe_request_id = self.next_request_id();

        // Use the JSON-RPC bridge pattern
        let rpc_request = crate::bridge::JsonRpcRequest::new(
            "recipes.list",
            serde_json::json!({}),
            self.recipe_request_id as u64,
        );

        info!("Sending recipes.list RPC request (id={})", self.recipe_request_id);
        if let Err(e) = self.bridge.request_rpc(rpc_request, self.recipe_request_id) {
            self.recipe_browser.loading = false;
            self.recipe_browser.error = Some(format!("Failed to request recipes: {}", e));
            error!("Failed to send recipes.list request: {}", e);
        } else {
            info!("recipes.list request sent successfully");
        }

        self.mark_dirty();
    }

    /// Refresh recipes (force reload).
    pub fn refresh_recipes(&mut self) {
        self.recipe_browser.loading = true;
        self.request_load_recipes();
    }

    /// Select previous recipe in the list.
    pub fn select_prev_recipe(&mut self) {
        self.recipe_browser.previous();
        self.mark_dirty();
    }

    /// Select next recipe in the list.
    pub fn select_next_recipe(&mut self) {
        self.recipe_browser.next();
        self.mark_dirty();
    }

    // ===== Workflow Launcher Modal =====

    /// Check if the workflow launcher modal is active.
    pub fn is_workflow_modal_active(&self) -> bool {
        self.workflow_state.active
    }

    /// Open the workflow launcher modal and request availability check.
    pub fn open_workflow_modal(&mut self) {
        self.workflow_state.open();
        self.workflow_state.set_loading(true);
        self.request_check_workflows();
        self.mark_dirty();
    }

    /// Close the workflow launcher modal.
    pub fn close_workflow_modal(&mut self) {
        self.workflow_state.close();
        self.mark_dirty();
    }

    /// Select previous workflow in the list.
    pub fn select_prev_workflow(&mut self) {
        self.workflow_state.select_previous();
        self.mark_dirty();
    }

    /// Select next workflow in the list.
    pub fn select_next_workflow(&mut self) {
        self.workflow_state.select_next();
        self.mark_dirty();
    }

    // ===== Template Browser Modal =====

    /// Open the template browser modal and request templates.
    pub fn open_template_browser(&mut self) {
        self.template_browser.open();
        self.request_load_templates();
        self.mark_dirty();
    }

    /// Close the template browser modal.
    pub fn close_template_browser(&mut self) {
        self.template_browser.close();
        self.mark_dirty();
    }

    /// Check if the template browser modal is active.
    pub fn is_template_browser_active(&self) -> bool {
        self.template_browser.active
    }

    /// Request template list load (async).
    pub fn request_load_templates(&mut self) {
        let request_id = self.next_request_id();
        self.template_browser.request_id = request_id;
        self.template_browser.loading = true;

        if let Err(e) = self.bridge.request_fetch_templates(request_id) {
            self.template_browser.loading = false;
            self.template_browser.error = Some(format!("Failed to request templates: {}", e));
        }
        self.mark_dirty();
    }

    /// Select previous template in the list.
    pub fn select_prev_template(&mut self) {
        self.template_browser.select_prev();
        self.mark_dirty();
    }

    /// Select next template in the list.
    pub fn select_next_template(&mut self) {
        self.template_browser.select_next();
        self.mark_dirty();
    }

    // ===== Batch Submission Modal =====

    /// Open the batch submission modal.
    pub fn open_batch_submission(&mut self) {
        self.batch_submission.open();
        self.mark_dirty();
    }

    /// Close the batch submission modal.
    pub fn close_batch_submission(&mut self) {
        self.batch_submission.close();
        self.mark_dirty();
    }

    /// Check if the batch submission modal is active.
    pub fn is_batch_submission_active(&self) -> bool {
        self.batch_submission.active
    }

    /// Add current editor content as a job to the batch.
    pub fn add_current_editor_to_batch(&mut self) {
        let content = self.editor.lines().join("\n");
        if content.trim().is_empty() {
            self.batch_submission.error = Some("Editor is empty".to_string());
            self.mark_dirty();
            return;
        }

        // Generate name from file path or timestamp
        let job_name = self
            .editor_file_path
            .as_ref()
            .map(|p| {
                std::path::Path::new(p)
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or("untitled")
                    .to_string()
            })
            .unwrap_or_else(|| format!("batch_{}", chrono::Utc::now().format("%H%M%S")));

        self.batch_submission.add_job(job_name, content);
        self.mark_dirty();
    }

    /// Submit all jobs in the batch.
    pub fn submit_batch(&mut self) {
        if self.batch_submission.jobs.is_empty() {
            self.batch_submission.error = Some("No jobs to submit".to_string());
            self.mark_dirty();
            return;
        }

        self.batch_submission.submitting = true;
        self.batch_submission.error = None;

        // Clone jobs to avoid borrow checker issues with self.next_request_id()
        let jobs = self.batch_submission.jobs.clone();
        let runner_type = self.batch_submission.common_runner_type;

        for job in jobs {
            let submission =
                crate::models::JobSubmission::new(&job.name, crate::models::DftCode::Crystal)
                    .with_input_content(&job.input_content)
                    .with_runner_type(runner_type);

            let request_id = self.next_request_id();
            let _ = self.bridge.request_submit_job(&submission, request_id);
        }

        self.batch_submission.close();
        self.set_error(format!(
            "Submitted {} jobs in batch",
            self.batch_submission.jobs.len()
        ));
        self.mark_dirty();
    }

    /// Request workflow availability check via RPC.
    fn request_check_workflows(&mut self) {
        self.workflow_request_id = self.next_request_id();

        let rpc_request = crate::bridge::JsonRpcRequest::new(
            "check_workflows_available",
            serde_json::json!({}),
            self.workflow_request_id as u64,
        );

        if let Err(e) = self
            .bridge
            .request_rpc(rpc_request, self.workflow_request_id)
        {
            self.workflow_state.set_loading(false);
            self.workflow_state
                .set_status(format!("Failed to check availability: {}", e), true);
            error!("Failed to send check_workflows_available request: {}", e);
        } else {
            debug!(
                "Sent check_workflows_available request (id={})",
                self.workflow_request_id
            );
        }
    }
}

// =============================================================================
// Unit Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::MaterialResult;
    use anyhow::Result;
    use std::collections::VecDeque;
    use std::sync::{Arc, Mutex};

    // Mock Bridge Service
    struct MockBridgeService {
        requests: Arc<Mutex<Vec<String>>>,
        responses: Arc<Mutex<VecDeque<BridgeResponse>>>,
    }

    impl MockBridgeService {
        fn new() -> Self {
            Self {
                requests: Arc::new(Mutex::new(Vec::new())),
                responses: Arc::new(Mutex::new(VecDeque::new())),
            }
        }
    }

    impl BridgeService for MockBridgeService {
        fn request_fetch_jobs(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("FetchJobs(request_id={})", request_id));
            Ok(())
        }

        fn request_fetch_job_details(&self, pk: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "FetchJobDetails(pk={}, request_id={})",
                pk, request_id
            ));
            Ok(())
        }

        fn request_submit_job(
            &self,
            _submission: &crate::models::JobSubmission,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("SubmitJob(request_id={})", request_id));
            Ok(())
        }

        fn request_cancel_job(&self, pk: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("CancelJob(pk={}, request_id={})", pk, request_id));
            Ok(())
        }

        fn request_fetch_job_log(&self, pk: i32, tail_lines: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "FetchJobLog(pk={}, tail_lines={}, request_id={})",
                pk, tail_lines, request_id
            ));
            Ok(())
        }

        fn request_search_materials(
            &self,
            formula: &str,
            limit: usize,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "SearchMaterials(formula={}, limit={}, request_id={})",
                formula, limit, request_id
            ));
            Ok(())
        }

        fn request_generate_d12(
            &self,
            mp_id: &str,
            config_json: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "GenerateD12(mp_id={}, config_json={}, request_id={})",
                mp_id, config_json, request_id
            ));
            Ok(())
        }

        fn request_fetch_slurm_queue(&self, cluster_id: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "FetchSlurmQueue(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_cancel_slurm_job(
            &self,
            cluster_id: i32,
            slurm_job_id: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "CancelSlurmJob(cluster_id={}, slurm_job_id={}, request_id={})",
                cluster_id, slurm_job_id, request_id
            ));
            Ok(())
        }

        fn request_adopt_slurm_job(
            &self,
            cluster_id: i32,
            slurm_job_id: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "AdoptSlurmJob(cluster_id={}, slurm_job_id={}, request_id={})",
                cluster_id, slurm_job_id, request_id
            ));
            Ok(())
        }

        fn request_sync_remote_jobs(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("SyncRemoteJobs(request_id={})", request_id));
            Ok(())
        }

        fn request_fetch_clusters(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("FetchClusters(request_id={})", request_id));
            Ok(())
        }

        fn request_create_cluster(
            &self,
            _config: &crate::models::ClusterConfig,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("CreateCluster(request_id={})", request_id));
            Ok(())
        }

        fn request_update_cluster(
            &self,
            cluster_id: i32,
            _config: &crate::models::ClusterConfig,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "UpdateCluster(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_delete_cluster(&self, cluster_id: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "DeleteCluster(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_test_cluster_connection(
            &self,
            cluster_id: i32,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "TestClusterConnection(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_check_workflows_available(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "CheckWorkflowsAvailable(request_id={})",
                request_id
            ));
            Ok(())
        }

        fn request_create_convergence_study(
            &self,
            config_json: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "CreateConvergenceStudy(config_json={}, request_id={})",
                config_json, request_id
            ));
            Ok(())
        }

        fn request_create_band_structure_workflow(
            &self,
            config_json: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "CreateBandStructureWorkflow(config_json={}, request_id={})",
                config_json, request_id
            ));
            Ok(())
        }

        fn request_create_phonon_workflow(
            &self,
            config_json: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "CreatePhononWorkflow(config_json={}, request_id={})",
                config_json, request_id
            ));
            Ok(())
        }

        fn request_create_eos_workflow(&self, config_json: &str, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "CreateEosWorkflow(config_json={}, request_id={})",
                config_json, request_id
            ));
            Ok(())
        }

        fn request_launch_aiida_geopt(&self, config_json: &str, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "LaunchAiidaGeopt(config_json={}, request_id={})",
                config_json, request_id
            ));
            Ok(())
        }

        fn request_fetch_templates(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("FetchTemplates(request_id={})", request_id));
            Ok(())
        }

        fn request_render_template(
            &self,
            template_name: &str,
            params_json: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "RenderTemplate(name={}, params={}, request_id={})",
                template_name, params_json, request_id
            ));
            Ok(())
        }

        fn request_rpc(
            &self,
            rpc_request: crate::bridge::JsonRpcRequest,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "Rpc(method={}, request_id={})",
                rpc_request.method, request_id
            ));
            Ok(())
        }

        fn poll_response(&self) -> Option<BridgeResponse> {
            let mut resps = self.responses.lock().unwrap();
            resps.pop_front()
        }
    }

    // Mock LSP Service
    struct MockLspService {
        calls: Arc<Mutex<Vec<String>>>,
    }

    impl MockLspService {
        fn new() -> Self {
            Self {
                calls: Arc::new(Mutex::new(Vec::new())),
            }
        }
    }

    impl LspService for MockLspService {
        fn send_initialized(&mut self) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push("send_initialized".to_string());
            Ok(())
        }

        fn did_open(&mut self, path: &str, _content: &str) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("did_open:{}", path));
            Ok(())
        }

        fn did_change(&mut self, path: &str, _version: i32, _content: &str) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("did_change:{}", path));
            Ok(())
        }

        fn did_close(&mut self, path: &str) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("did_close:{}", path));
            Ok(())
        }
    }

    // Helper to create app with mocks
    fn create_test_app<'a>() -> App<'a> {
        let (_, lsp_rx) = mpsc::channel();

        let mut editor = TextArea::default();
        editor.set_line_number_style(
            ratatui::style::Style::default().fg(ratatui::style::Color::DarkGray),
        );

        App {
            should_quit: false,
            current_tab: AppTab::Jobs,
            last_error: None,
            last_error_time: None,
            needs_redraw: false,
            jobs_state: JobsState::default(),
            slurm_queue: Vec::new(),
            slurm_view_active: false,
            slurm_request_id: 0,
            slurm_selected: None,
            last_slurm_refresh: None,
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
            log_job_pk: None,
            log_job_name: None,
            log_follow_mode: false,
            last_log_refresh: None,
            bridge: Box::new(MockBridgeService::new()), // Use mock bridge
            next_request_id: 0,
            pending_bridge_request: None,
            pending_request_id: None,
            pending_bridge_request_time: None,
            lsp_client: Some(Box::new(MockLspService::new())), // Use mock LSP
            lsp_receiver: lsp_rx,
            last_editor_change: None,
            pending_lsp_change: false,
            materials: MaterialsSearchState::default(),
            new_job: NewJobState::default(),
            cluster_manager: ClusterManagerState::default(),
            slurm_queue_state: SlurmQueueState::default(),
            last_slurm_cluster_id: None,
            vasp_input_state: crate::ui::VaspInputState::default(),
            workflow_state: crate::ui::WorkflowState::default(),
            recipe_browser: RecipeBrowserState::default(),
            template_browser: TemplateBrowserState::default(),
            batch_submission: BatchSubmissionState::default(),
            recipe_request_id: 0,
            workflow_request_id: 0,
            vasp_request_id: 0,
            quacc_clusters: Vec::new(),
            submit_request_id: 0,
            last_job_poll: std::time::Instant::now(),
            poll_interval: std::time::Duration::from_secs(30),
            pending_status_requests: std::collections::HashMap::new(),
            status_request_counter: 0,
            startup_effect: None, // No effect in tests
        }
    }

    // Test Helper for JobStatus
    fn test_job(pk: i32, name: &str) -> JobStatus {
        JobStatus {
            pk,
            uuid: format!("test-uuid-{}", pk),
            name: name.to_string(),
            dft_code: Some(crate::models::DftCode::Crystal),
            state: crate::models::JobState::Completed,
            runner_type: Some(crate::models::RunnerType::Local),
            progress_percent: 100.0,
            wall_time_seconds: Some(123.45),
            created_at: Some("2023-01-01T00:00:00".to_string()),
            error_snippet: None,
        }
    }

    // =========================================================================
    // General State Tests
    // =========================================================================

    #[test]
    fn test_app_tab_name() {
        assert_eq!(AppTab::Jobs.name(), "Jobs");
        assert_eq!(AppTab::Editor.name(), "Editor");
        assert_eq!(AppTab::Results.name(), "Results");
        assert_eq!(AppTab::Log.name(), "Log");
    }

    #[test]
    fn test_app_tab_all() {
        let tabs = AppTab::all();
        assert_eq!(tabs.len(), 4);
        assert_eq!(tabs[0], AppTab::Jobs);
        assert_eq!(tabs[1], AppTab::Editor);
        assert_eq!(tabs[2], AppTab::Results);
        assert_eq!(tabs[3], AppTab::Log);
    }

    // =========================================================================
    // Jobs State Tests
    // =========================================================================

    #[test]
    fn test_jobs_state_default() {
        let state = JobsState::default();
        assert!(state.jobs.is_empty());
        assert!(state.selected_index.is_none());
        assert!(state.last_refresh.is_none());
        assert!(state.changed_pks.is_empty());
        assert!(state.pending_cancel_pk.is_none());
        assert!(!state.pending_submit);
    }

    #[test]
    fn test_jobs_state_select_next_empty() {
        let mut state = JobsState::default();
        state.select_next();
        assert!(state.selected_index.is_none());
    }

    #[test]
    fn test_jobs_state_select_prev_empty() {
        let mut state = JobsState::default();
        state.select_prev();
        assert!(state.selected_index.is_none());
    }

    #[test]
    fn test_jobs_state_clear_pending_cancel() {
        let mut state = JobsState {
            pending_cancel_pk: Some(123),
            pending_cancel_time: Some(std::time::Instant::now()),
            ..Default::default()
        };

        state.clear_pending_cancel();
        assert!(state.pending_cancel_pk.is_none());
    }

    #[test]
    fn test_jobs_state_clear_pending_submit() {
        let mut state = JobsState {
            pending_submit: true,
            pending_submit_time: Some(std::time::Instant::now()),
            ..Default::default()
        };

        state.clear_pending_submit();
        assert!(!state.pending_submit);
    }

    // =========================================================================
    // Materials Search State Tests
    // =========================================================================

    #[test]
    fn test_materials_search_state_default() {
        let state = MaterialsSearchState::default();
        assert!(!state.active);
        assert!(state.results.is_empty());
        assert!(state.selected_for_import.is_none());
        assert!(!state.loading);
        assert!(!state.status_is_error);
    }

    // Helper for materials tests
    fn test_material(id: &str, formula: &str) -> MaterialResult {
        MaterialResult {
            material_id: id.to_string(),
            formula: Some(formula.to_string()),
            formula_pretty: None,
            source: Some("mp".to_string()),
            properties: Default::default(),
            metadata: Default::default(),
            structure: None,
        }
    }

    #[test]
    fn test_materials_search_state_open() {
        let mut state = MaterialsSearchState::default();
        state.results.push(test_material("mp-1234", "MoS2"));
        state.loading = true;
        state.status = Some("Searching...".to_string());

        state.open();

        assert!(state.active);
        assert!(state.results.is_empty()); // Cleared on open
        assert!(state.status.is_some()); // Reset on open
        assert!(!state.loading); // Reset on open
    }

    #[test]
    fn test_materials_search_state_close_increments_request_id() {
        let mut state = MaterialsSearchState::default();
        let initial_id = state.request_id;

        state.active = true;
        state.close();

        // close() sets closing=true and starts animation; active becomes false when animation completes
        assert!(state.closing);
        assert_eq!(state.request_id, initial_id + 1);
    }

    #[test]
    fn test_materials_search_state_select_next() {
        let mut state = MaterialsSearchState::default();
        state.results = vec![test_material("mp-1", "A"), test_material("mp-2", "B")];
        state.table_state.select(Some(0));

        state.select_next();
        assert_eq!(state.table_state.selected(), Some(1));

        // Wrap around
        state.select_next();
        assert_eq!(state.table_state.selected(), Some(0));
    }

    #[test]
    fn test_materials_search_state_select_prev() {
        let mut state = MaterialsSearchState::default();
        state.results = vec![test_material("mp-1", "A"), test_material("mp-2", "B")];
        state.table_state.select(Some(0));

        // Wrap around
        state.select_prev();
        assert_eq!(state.table_state.selected(), Some(1));

        state.select_prev();
        assert_eq!(state.table_state.selected(), Some(0));
    }

    #[test]
    fn test_materials_search_state_set_status() {
        let mut state = MaterialsSearchState::default();

        state.set_status("Test error", true);
        assert_eq!(state.status, Some("Test error".to_string()));
        assert!(state.status_is_error);

        state.set_status("Success", false);
        assert_eq!(state.status, Some("Success".to_string()));
        assert!(!state.status_is_error);
    }

    // =========================================================================
    // Action Tests
    // =========================================================================

    #[test]
    fn test_action_debug_format() {
        let action = Action::TabNext;
        let debug_str = format!("{:?}", action);
        assert_eq!(debug_str, "TabNext");
    }

    #[test]
    fn test_action_clone() {
        let action = Action::TabSet(AppTab::Editor);
        let cloned = action.clone();
        assert_eq!(action, cloned);
    }

    #[test]
    fn test_action_equality() {
        assert_eq!(Action::TabNext, Action::TabNext);
        assert_ne!(Action::TabNext, Action::TabPrev);
        assert_eq!(Action::TabSet(AppTab::Jobs), Action::TabSet(AppTab::Jobs));
        assert_ne!(Action::TabSet(AppTab::Jobs), Action::TabSet(AppTab::Editor));
    }

    // =========================================================================
    // Mock Service Tests
    // =========================================================================

    #[test]
    fn test_mock_bridge_service_captures_requests() {
        let mock = MockBridgeService::new();

        mock.request_fetch_jobs(1).unwrap();
        mock.request_fetch_job_details(42, 2).unwrap();
        mock.request_fetch_templates(3).unwrap();
        mock.request_render_template("test", "{}", 4).unwrap();
        mock.request_check_workflows_available(5).unwrap();
        mock.request_create_convergence_study("{}", 6).unwrap();
        mock.request_create_band_structure_workflow("{}", 7)
            .unwrap();
        mock.request_create_phonon_workflow("{}", 8).unwrap();
        mock.request_create_eos_workflow("{}", 9).unwrap();
        mock.request_launch_aiida_geopt("{}", 10).unwrap();

        let requests = mock.requests.lock().unwrap();
        assert_eq!(requests.len(), 10);
        assert_eq!(requests[0], "FetchJobs(request_id=1)");
        assert_eq!(requests[1], "FetchJobDetails(pk=42, request_id=2)");
        assert_eq!(requests[2], "FetchTemplates(request_id=3)");
        assert_eq!(
            requests[3],
            "RenderTemplate(name=test, params={}, request_id=4)"
        );
        assert_eq!(requests[4], "CheckWorkflowsAvailable(request_id=5)");
        assert_eq!(
            requests[5],
            "CreateConvergenceStudy(config_json={}, request_id=6)"
        );
        assert_eq!(
            requests[6],
            "CreateBandStructureWorkflow(config_json={}, request_id=7)"
        );
        assert_eq!(
            requests[7],
            "CreatePhononWorkflow(config_json={}, request_id=8)"
        );
        assert_eq!(
            requests[8],
            "CreateEosWorkflow(config_json={}, request_id=9)"
        );
        assert_eq!(
            requests[9],
            "LaunchAiidaGeopt(config_json={}, request_id=10)"
        );
    }

    #[test]
    fn test_mock_bridge_service_returns_responses() {
        let mock = MockBridgeService::new();

        // Initially empty
        assert!(mock.poll_response().is_none());

        // Add response
        {
            let mut resps = mock.responses.lock().unwrap();
            resps.push_back(BridgeResponse::Jobs {
                request_id: 1,
                result: Ok(Vec::new()),
            });
        }

        // Should pop one
        let resp = mock.poll_response();
        assert!(resp.is_some());
        if let Some(BridgeResponse::Jobs { request_id, .. }) = resp {
            assert_eq!(request_id, 1);
        } else {
            panic!("Wrong response type");
        }

        // Should be empty again
        assert!(mock.poll_response().is_none());
    }

    #[test]
    fn test_mock_lsp_service_captures_calls() {
        let mut mock = MockLspService::new();

        mock.send_initialized().unwrap();
        mock.did_open("test.d12", "content").unwrap();
        mock.did_change("test.d12", 2, "new content").unwrap();
        mock.did_close("test.d12").unwrap();

        let calls = mock.calls.lock().unwrap();
        assert_eq!(calls.len(), 4);
        assert_eq!(calls[0], "send_initialized");
        assert_eq!(calls[1], "did_open:test.d12");
        assert_eq!(calls[2], "did_change:test.d12");
        assert_eq!(calls[3], "did_close:test.d12");
    }

    // =========================================================================
    // App Logic Tests
    // =========================================================================

    #[test]
    fn test_tab_navigation_wraps_forward() {
        let mut app = create_test_app();
        assert_eq!(app.current_tab, AppTab::Jobs);

        app.next_tab();
        assert_eq!(app.current_tab, AppTab::Editor);

        app.next_tab();
        assert_eq!(app.current_tab, AppTab::Results);

        app.next_tab();
        assert_eq!(app.current_tab, AppTab::Log);

        app.next_tab();
        assert_eq!(app.current_tab, AppTab::Jobs);
    }

    #[test]
    fn test_tab_navigation_wraps_backward() {
        let mut app = create_test_app();
        assert_eq!(app.current_tab, AppTab::Jobs);

        app.prev_tab();
        assert_eq!(app.current_tab, AppTab::Log);

        app.prev_tab();
        assert_eq!(app.current_tab, AppTab::Results);

        app.prev_tab();
        assert_eq!(app.current_tab, AppTab::Editor);

        app.prev_tab();
        assert_eq!(app.current_tab, AppTab::Jobs);
    }

    #[test]
    fn test_tab_navigation_by_number() {
        let mut app = create_test_app();

        app.set_tab(AppTab::Jobs);
        assert_eq!(app.current_tab, AppTab::Jobs);

        app.set_tab(AppTab::Editor);
        assert_eq!(app.current_tab, AppTab::Editor);

        app.set_tab(AppTab::Results);
        assert_eq!(app.current_tab, AppTab::Results);

        app.set_tab(AppTab::Log);
        assert_eq!(app.current_tab, AppTab::Log);

        // Test setting same tab
        app.set_tab(AppTab::Log);
        assert_eq!(app.current_tab, AppTab::Log);

        app.set_tab(AppTab::Jobs);
        assert_eq!(app.current_tab, AppTab::Jobs);
    }

    #[test]
    fn test_set_tab_same_tab_does_not_mark_dirty() {
        let mut app = create_test_app();
        app.needs_redraw = false; // Reset initial dirty

        app.set_tab(AppTab::Jobs);
        assert!(!app.needs_redraw());

        app.set_tab(AppTab::Editor);
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_needs_redraw_after_tab_change() {
        let mut app = create_test_app();
        app.take_needs_redraw(); // Clear initial

        app.next_tab();
        assert!(app.needs_redraw());

        app.take_needs_redraw();
        app.prev_tab();
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_needs_redraw_after_job_selection_change() {
        let mut app = create_test_app();
        app.jobs_state.jobs = vec![test_job(1, "job1"), test_job(2, "job2")];
        app.jobs_state.selected_index = Some(0);
        app.take_needs_redraw();

        app.select_next_job();
        assert!(app.needs_redraw());

        app.take_needs_redraw();
        app.select_prev_job();
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_update_action_tab_next() {
        let mut app = create_test_app();
        assert_eq!(app.current_tab, AppTab::Jobs);

        app.update(Action::TabNext);
        assert_eq!(app.current_tab, AppTab::Editor);
    }

    #[test]
    fn test_update_action_tab_prev() {
        let mut app = create_test_app();
        app.current_tab = AppTab::Editor;

        app.update(Action::TabPrev);
        assert_eq!(app.current_tab, AppTab::Jobs);
    }

    #[test]
    fn test_update_action_tab_set() {
        let mut app = create_test_app();

        app.update(Action::TabSet(AppTab::Log));
        assert_eq!(app.current_tab, AppTab::Log);
    }

    #[test]
    fn test_update_action_quit() {
        let mut app = create_test_app();
        assert!(!app.should_quit);

        app.update(Action::Quit);
        assert!(app.should_quit);
    }

    #[test]
    fn test_update_action_error_clear() {
        let mut app = create_test_app();
        app.set_error("Test error");
        assert!(app.last_error.is_some());

        app.update(Action::ErrorClear);
        assert!(app.last_error.is_none());
    }

    #[test]
    fn test_log_scroll_bounds() {
        let mut app = create_test_app();
        app.log_lines = vec!["line1".to_string(), "line2".to_string()];

        // Scroll down within bounds
        app.scroll_log_down(); // max is 0 (2 lines - 20 height clamped to 0)
        assert_eq!(app.log_scroll, 0);

        // Scroll up at top
        app.scroll_log_up();
        assert_eq!(app.log_scroll, 0);

        // Add more lines to allow scrolling
        for i in 0..30 {
            app.log_lines.push(format!("line{}", i + 3));
        }
        // Now 32 lines, max scroll = 12

        app.scroll_log_down();
        assert_eq!(app.log_scroll, 1);

        app.scroll_log_up();
        assert_eq!(app.log_scroll, 0);
    }

    #[test]
    fn test_log_scroll_top_and_bottom() {
        let mut app = create_test_app();
        for i in 0..30 {
            app.log_lines.push(format!("line{}", i));
        }
        // 30 lines, 20 visible -> max scroll 10

        app.scroll_log_bottom();
        assert_eq!(app.log_scroll, 10);

        app.scroll_log_top();
        assert_eq!(app.log_scroll, 0);

        // Test page scrolling
        app.scroll_log_page_down(); // +10
        assert_eq!(app.log_scroll, 10);

        app.scroll_log_page_up(); // -10
        assert_eq!(app.log_scroll, 0);
    }

    #[test]
    fn test_log_follow_mode_toggle() {
        let mut app = create_test_app();
        assert!(!app.log_follow_mode);

        app.toggle_log_follow();
        assert!(app.log_follow_mode);

        app.toggle_log_follow();
        assert!(!app.log_follow_mode);
    }

    #[test]
    fn test_results_scroll_bounds() {
        let mut app = create_test_app();
        // No details loaded
        app.scroll_results_down();
        assert_eq!(app.results_scroll, 0);

        // Add details
        use crate::models::JobDetails;
        app.current_job_details = Some(JobDetails {
            pk: 1,
            uuid: Some("uuid".to_string()),
            name: "job".to_string(),
            state: crate::models::JobState::Completed,
            dft_code: Some(crate::models::DftCode::Crystal),
            input_file: Some("input.d12".to_string()),
            final_energy: None,
            bandgap_ev: None,
            convergence_met: false,
            scf_cycles: None,
            cpu_time_seconds: None,
            wall_time_seconds: None,
            warnings: vec![],
            errors: vec![],
            stdout_tail: vec!["line".to_string(); 30], // 30 lines
            key_results: None,
            work_dir: None,
        });

        // Display line count will be header (assume 10 lines) + 30 log lines = 40
        // Scroll down
        app.scroll_results_down();
        assert_eq!(app.results_scroll, 1);

        app.scroll_results_up();
        assert_eq!(app.results_scroll, 0);
    }

    #[test]
    fn test_job_selection_bounds_upper() {
        let mut app = create_test_app();
        app.jobs_state.jobs = vec![test_job(1, "j1"), test_job(2, "j2"), test_job(3, "j3")];
        app.jobs_state.selected_index = Some(0);

        app.select_next_job();
        assert_eq!(app.jobs_state.selected_index, Some(1));

        app.select_next_job();
        assert_eq!(app.jobs_state.selected_index, Some(2));

        // Should not go past end
        app.select_next_job();
        assert_eq!(app.jobs_state.selected_index, Some(2));
    }

    #[test]
    fn test_job_selection_bounds_lower() {
        let mut app = create_test_app();
        app.jobs_state.jobs = vec![test_job(1, "j1"), test_job(2, "j2"), test_job(3, "j3")];
        app.jobs_state.selected_index = Some(2);

        app.select_prev_job();
        assert_eq!(app.jobs_state.selected_index, Some(1));

        app.select_prev_job();
        assert_eq!(app.jobs_state.selected_index, Some(0));

        // Should not go past 0
        app.select_prev_job();
        assert_eq!(app.jobs_state.selected_index, Some(0));
    }

    #[test]
    fn test_job_selection_empty_list_select_next() {
        let mut app = create_test_app();
        assert!(app.jobs_state.jobs.is_empty());
        assert!(app.jobs_state.selected_index.is_none());

        app.select_next_job();
        assert!(app.jobs_state.selected_index.is_none());
    }

    #[test]
    fn test_job_selection_empty_list_select_prev() {
        let mut app = create_test_app();
        assert!(app.jobs_state.jobs.is_empty());
        assert!(app.jobs_state.selected_index.is_none());

        app.select_prev_job();
        assert!(app.jobs_state.selected_index.is_none());
    }

    #[test]
    fn test_job_selection_first_and_last() {
        let mut app = create_test_app();
        // 5 jobs
        for i in 0..5 {
            app.jobs_state.jobs.push(test_job(i, &format!("j{}", i)));
        }
        app.jobs_state.selected_index = Some(2);

        app.select_first_job();
        assert_eq!(app.jobs_state.selected_index, Some(0));

        app.select_last_job();
        assert_eq!(app.jobs_state.selected_index, Some(4));
    }

    #[test]
    fn test_job_selection_first_on_empty_list() {
        let mut app = create_test_app();
        assert!(app.jobs_state.jobs.is_empty());

        app.select_first_job();
        assert!(app.jobs_state.selected_index.is_none());
    }

    #[test]
    fn test_job_selection_last_on_empty_list() {
        let mut app = create_test_app();
        assert!(app.jobs_state.jobs.is_empty());

        app.select_last_job();
        assert!(app.jobs_state.selected_index.is_none());
    }

    #[test]
    fn test_set_error_and_clear() {
        let mut app = create_test_app();
        assert!(app.last_error.is_none());

        app.set_error("Something went wrong");
        assert_eq!(app.last_error, Some("Something went wrong".to_string()));
        assert!(app.last_error_time.is_some());

        app.clear_error();
        assert!(app.last_error.is_none());
        assert!(app.last_error_time.is_none());
    }

    #[test]
    fn test_set_error_marks_dirty() {
        let mut app = create_test_app();
        app.take_needs_redraw();

        app.set_error("Error");
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_clear_error_marks_dirty_only_if_error_exists() {
        let mut app = create_test_app();
        app.take_needs_redraw();

        // No error to clear
        app.clear_error();
        assert!(!app.needs_redraw());

        // Set error
        app.set_error("Error");
        app.take_needs_redraw();

        // Clear error
        app.clear_error();
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_error_message_long_string() {
        let mut app = create_test_app();
        let long_message = "a".repeat(1000);
        app.set_error(long_message.clone());
        assert_eq!(app.last_error, Some(long_message));
    }

    #[test]
    fn test_error_message_special_characters() {
        let mut app = create_test_app();
        let special_msg = "Error: <script>alert('xss')</script> & other chars";
        app.set_error(special_msg);
        assert_eq!(app.last_error, Some(special_msg.to_string()));
    }

    #[test]
    fn test_last_slurm_cluster_remembered() {
        let mut app = create_test_app();
        assert!(app.last_slurm_cluster_id.is_none());

        app.last_slurm_cluster_id = Some(99);
        assert_eq!(app.last_slurm_cluster_id, Some(99));
    }

    #[test]
    fn test_last_slurm_cluster_cleared() {
        let mut app = create_test_app();
        app.last_slurm_cluster_id = Some(1);

        app.last_slurm_cluster_id = None;
        assert!(app.last_slurm_cluster_id.is_none());
    }

    #[test]
    fn test_mark_dirty_and_clear() {
        let mut app = create_test_app();
        // Initially created with needs_redraw = true (or not, depends on constructor logic)
        // But let's force it
        app.needs_redraw = false;

        app.mark_dirty();
        assert!(app.needs_redraw());

        // Check without clearing
        assert!(app.needs_redraw());

        // Take and clear
        assert!(app.take_needs_redraw());
        assert!(!app.needs_redraw());
    }

    #[test]
    fn test_take_needs_redraw_returns_and_clears() {
        let mut app = create_test_app();
        app.mark_dirty();

        let dirty = app.take_needs_redraw();
        assert!(dirty);
        assert!(!app.needs_redraw());
    }

    #[test]
    fn test_selected_job_returns_correct_job() {
        let mut app = create_test_app();

        app.jobs_state.jobs = vec![
            test_job(1, "first"),
            test_job(2, "second"),
            test_job(3, "third"),
        ];
        app.jobs_state.selected_index = Some(1); // "second"

        let selected = app.selected_job();
        assert!(selected.is_some());
        assert_eq!(selected.unwrap().name, "second");
    }

    #[test]
    fn test_selected_job_returns_none_when_no_selection() {
        let mut app = create_test_app();

        app.jobs_state.jobs = vec![test_job(1, "job")];
        app.jobs_state.selected_index = None;

        assert!(app.selected_job().is_none());
    }

    #[test]
    fn test_selected_job_returns_none_when_empty_list() {
        let app = create_test_app();

        assert!(app.jobs_state.jobs.is_empty());
        assert!(app.selected_job().is_none());
    }

    #[test]
    fn test_materials_modal_open_close() {
        let mut app = create_test_app();

        // Initially closed
        assert!(!app.materials.active);

        // Open
        app.open_materials_modal();
        assert!(app.materials.active);
        assert!(app.needs_redraw());

        // Clear dirty and close
        app.take_needs_redraw();
        app.close_materials_modal();
        // close() sets closing=true and starts animation; active becomes false when animation completes
        assert!(app.materials.closing);
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_request_id_increments() {
        let mut app = create_test_app();

        let id1 = app.next_request_id();
        let id2 = app.next_request_id();
        let id3 = app.next_request_id();

        assert_eq!(id1, 0);
        assert_eq!(id2, 1);
        assert_eq!(id3, 2);
    }
}
