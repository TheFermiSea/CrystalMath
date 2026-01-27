//! State management module.
//!
//! This module contains types related to application state management,
//! including the MVU/Reducer action types, tab definitions, and
//! supporting state structs for modals and domain-specific views.

use std::collections::HashSet;

use ratatui::widgets::TableState;
use tui_textarea::TextArea;

use crate::models::{D12GenerationConfig, DftCode, JobStatus, MaterialResult, RunnerType};

pub mod actions;

pub use actions::*;

// =============================================================================
// Materials Project Search Modal State
// =============================================================================

/// State for the Materials Project search modal.
#[derive(Debug)]
pub struct MaterialsSearchState<'a> {
    /// Whether the modal is currently active/visible.
    pub active: bool,

    /// Search input widget.
    pub input: TextArea<'a>,

    /// Search results from Materials Project.
    pub results: Vec<MaterialResult>,

    /// Table state for result selection.
    pub table_state: TableState,

    /// Whether a search is currently in progress.
    pub loading: bool,

    /// Status message to display (info or error).
    pub status: Option<String>,

    /// Whether the status is an error.
    pub status_is_error: bool,

    /// Current request ID for cancellation handling.
    /// Incremented on each new search to ignore stale responses.
    pub request_id: usize,

    /// Material ID selected for D12 generation (while loading).
    pub selected_for_import: Option<String>,

    /// D12 generation config.
    pub d12_config: D12GenerationConfig,
}

impl<'a> Default for MaterialsSearchState<'a> {
    fn default() -> Self {
        let mut input = TextArea::default();
        input.set_placeholder_text("Enter formula (e.g., MoS2, Si, LiFePO4)");

        Self {
            active: false,
            input,
            results: Vec::new(),
            table_state: TableState::default(),
            loading: false,
            status: Some("Enter a formula and press Enter to search".to_string()),
            status_is_error: false,
            request_id: 0,
            selected_for_import: None,
            d12_config: D12GenerationConfig::default(),
        }
    }
}

impl<'a> MaterialsSearchState<'a> {
    /// Open the modal.
    pub fn open(&mut self) {
        self.active = true;
        self.results.clear();
        self.table_state = TableState::default();
        self.loading = false;
        self.status = Some("Enter a formula and press Enter to search".to_string());
        self.status_is_error = false;
        self.selected_for_import = None;
        // Clear input for fresh search
        self.input = TextArea::default();
        self.input
            .set_placeholder_text("Enter formula (e.g., MoS2, Si, LiFePO4)");
    }

    /// Close the modal and reset state.
    pub fn close(&mut self) {
        self.active = false;
        // Increment request_id to ignore any pending responses
        self.request_id += 1;
    }

    /// Get the current search query.
    pub fn query(&self) -> String {
        self.input.lines().join("")
    }

    /// Select the next result in the table.
    pub fn select_next(&mut self) {
        if self.results.is_empty() {
            return;
        }
        let i = match self.table_state.selected() {
            Some(i) if i >= self.results.len() - 1 => 0,
            Some(i) => i + 1,
            None => 0,
        };
        self.table_state.select(Some(i));
    }

    /// Select the previous result in the table.
    pub fn select_prev(&mut self) {
        if self.results.is_empty() {
            return;
        }
        let i = match self.table_state.selected() {
            Some(0) => self.results.len() - 1,
            Some(i) => i - 1,
            None => 0,
        };
        self.table_state.select(Some(i));
    }

    /// Get the currently selected material, if any.
    pub fn selected_material(&self) -> Option<&MaterialResult> {
        self.table_state
            .selected()
            .and_then(|i| self.results.get(i))
    }

    /// Set a status message.
    pub fn set_status(&mut self, message: &str, is_error: bool) {
        self.status = Some(message.to_string());
        self.status_is_error = is_error;
    }
}

// =============================================================================
// New Job Modal State
// =============================================================================

/// Fields in the new job form that can be focused.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum NewJobField {
    #[default]
    Name,
    DftCode,
    RunnerType,
    Cluster,
    // Parallelism
    ParallelMode,
    MpiRanks,
    // Scheduler (SLURM)
    Walltime,
    Memory,
    Cpus,
    Nodes,
    Partition,
    // Aux Files (CRYSTAL)
    AuxGui,
    AuxF9,
    AuxHessopt,
}

impl NewJobField {
    /// Move to the next field.
    pub fn next(self) -> Self {
        match self {
            Self::Name => Self::DftCode,
            Self::DftCode => Self::RunnerType,
            Self::RunnerType => Self::Cluster,
            Self::Cluster => Self::ParallelMode,
            Self::ParallelMode => Self::MpiRanks,
            Self::MpiRanks => Self::Walltime,
            Self::Walltime => Self::Memory,
            Self::Memory => Self::Cpus,
            Self::Cpus => Self::Nodes,
            Self::Nodes => Self::Partition,
            Self::Partition => Self::AuxGui,
            Self::AuxGui => Self::AuxF9,
            Self::AuxF9 => Self::AuxHessopt,
            Self::AuxHessopt => Self::Name,
        }
    }

    /// Move to the previous field.
    pub fn prev(self) -> Self {
        match self {
            Self::Name => Self::AuxHessopt,
            Self::DftCode => Self::Name,
            Self::RunnerType => Self::DftCode,
            Self::Cluster => Self::RunnerType,
            Self::ParallelMode => Self::Cluster,
            Self::MpiRanks => Self::ParallelMode,
            Self::Walltime => Self::MpiRanks,
            Self::Memory => Self::Walltime,
            Self::Cpus => Self::Memory,
            Self::Nodes => Self::Cpus,
            Self::Partition => Self::Nodes,
            Self::AuxGui => Self::Partition,
            Self::AuxF9 => Self::AuxGui,
            Self::AuxHessopt => Self::AuxF9,
        }
    }
}

/// State for the New Job creation modal.
#[derive(Debug)]
pub struct NewJobState {
    /// Whether the modal is currently active/visible.
    pub active: bool,

    /// Currently focused field.
    pub focused_field: NewJobField,

    /// Job name input.
    pub job_name: String,

    /// Selected DFT code.
    pub dft_code: DftCode,

    /// Selected runner type for job execution.
    pub runner_type: RunnerType,

    /// Selected cluster ID (for remote runners).
    pub cluster_id: Option<i32>,

    /// Available cluster IDs (fetched from backend).
    #[allow(dead_code)]
    pub available_clusters: Vec<i32>,

    /// Error message to display.
    pub error: Option<String>,

    /// Whether a submission is in progress.
    pub submitting: bool,

    // ===== Extended Configuration =====
    /// Parallel mode (false=serial, true=parallel).
    pub is_parallel: bool,

    /// MPI ranks input (for parallel mode).
    pub mpi_ranks: String,

    /// Scheduler: Walltime (HH:MM:SS).
    pub walltime: String,

    /// Scheduler: Memory (GB).
    pub memory_gb: String,

    /// Scheduler: CPUs per task.
    pub cpus_per_task: String,

    /// Scheduler: Nodes.
    pub nodes: String,

    /// Scheduler: Partition.
    pub partition: String,

    // Aux Files inputs (path strings)
    pub aux_gui_path: String,
    pub aux_f9_path: String,
    pub aux_hessopt_path: String,

    // Aux Files enabled states
    pub aux_gui_enabled: bool,
    pub aux_f9_enabled: bool,
    pub aux_hessopt_enabled: bool,
}

impl Default for NewJobState {
    fn default() -> Self {
        Self {
            active: false,
            focused_field: NewJobField::Name,
            job_name: String::new(),
            dft_code: DftCode::Crystal,
            runner_type: RunnerType::Local,
            cluster_id: None,
            available_clusters: Vec::new(),
            error: None,
            submitting: false,

            // Defaults
            is_parallel: false,
            mpi_ranks: "4".to_string(),
            walltime: "24:00:00".to_string(),
            memory_gb: "32".to_string(),
            cpus_per_task: "4".to_string(),
            nodes: "1".to_string(),
            partition: "".to_string(),

            aux_gui_path: "".to_string(),
            aux_f9_path: "".to_string(),
            aux_hessopt_path: "".to_string(),
            aux_gui_enabled: false,
            aux_f9_enabled: false,
            aux_hessopt_enabled: false,
        }
    }
}

impl NewJobState {
    /// Open the new job modal.
    pub fn open(&mut self) {
        self.active = true;
        self.focused_field = NewJobField::Name;
        self.job_name.clear();
        self.dft_code = DftCode::Crystal;
        self.runner_type = RunnerType::Local;
        self.cluster_id = None;
        self.error = None;
        self.submitting = false;
        // Reset extended fields
        self.is_parallel = false;
        self.mpi_ranks = "4".to_string();
        self.walltime = "24:00:00".to_string();
        self.memory_gb = "32".to_string();
        self.cpus_per_task = "4".to_string();
        self.nodes = "1".to_string();
        self.partition.clear();
        self.aux_gui_enabled = false;
        self.aux_f9_enabled = false;
        self.aux_hessopt_enabled = false;
        self.aux_gui_path.clear();
        self.aux_f9_path.clear();
        self.aux_hessopt_path.clear();
    }

    /// Close the new job modal.
    pub fn close(&mut self) {
        self.active = false;
    }

    /// Check if the form has an error.
    pub fn has_error(&self) -> bool {
        self.error.is_some()
    }

    /// Check if the form can be submitted.
    pub fn can_submit(&self) -> bool {
        !self.job_name.is_empty()
            && !self.submitting
            && (self.runner_type == RunnerType::Local || self.cluster_id.is_some())
    }

    /// Cycle to the next DFT code.
    pub fn cycle_dft_code(&mut self) {
        self.dft_code = match self.dft_code {
            DftCode::Crystal => DftCode::Vasp,
            DftCode::Vasp => DftCode::QuantumEspresso,
            DftCode::QuantumEspresso => DftCode::Crystal,
            DftCode::Unknown => DftCode::Crystal,
        };
    }

    /// Cycle to the next runner type.
    pub fn cycle_runner_type(&mut self) {
        self.runner_type = match self.runner_type {
            RunnerType::Local => RunnerType::Ssh,
            RunnerType::Ssh => RunnerType::Slurm,
            RunnerType::Slurm => RunnerType::Local,
            RunnerType::Aiida | RunnerType::Unknown => RunnerType::Local,
        };
        // Clear cluster if switching to local
        if self.runner_type == RunnerType::Local {
            self.cluster_id = None;
        }
    }

    /// Set an error message.
    pub fn set_error(&mut self, error: &str) {
        self.error = Some(error.to_string());
    }

    /// Clear the error message.
    pub fn clear_error(&mut self) {
        self.error = None;
    }

    /// Validate the job name.
    pub fn validate_name(&self) -> Result<(), &'static str> {
        if self.job_name.is_empty() {
            return Err("Job name is required");
        }
        // Check for valid characters (alphanumeric, hyphens, underscores)
        if !self
            .job_name
            .chars()
            .all(|c| c.is_alphanumeric() || c == '-' || c == '_')
        {
            return Err("Job name can only contain letters, numbers, hyphens, and underscores");
        }
        Ok(())
    }
}

// =============================================================================
// Jobs Tab State
// =============================================================================

/// State for the Jobs tab.
#[derive(Debug, Default)]
pub struct JobsState {
    /// List of jobs from backend.
    pub jobs: Vec<JobStatus>,

    /// Currently selected job index.
    pub selected_index: Option<usize>,

    /// Job PKs that changed state since last refresh (for highlighting).
    pub changed_pks: HashSet<i32>,

    /// Timestamp of last successful job refresh.
    pub last_refresh: Option<std::time::Instant>,

    /// Job PK pending cancel confirmation (press 'c' again to confirm).
    pub pending_cancel_pk: Option<i32>,

    /// Timestamp when cancel confirmation was requested (expires after 3s).
    pub pending_cancel_time: Option<std::time::Instant>,

    /// Whether job submit is pending confirmation (press Ctrl+Enter again to confirm).
    pub pending_submit: bool,

    /// Timestamp when submit confirmation was requested (expires after 3s).
    pub pending_submit_time: Option<std::time::Instant>,

    /// Job PK selected as base for diff comparison (press 'd' to select).
    pub diff_base_pk: Option<i32>,

    /// Whether diff view modal is active.
    #[allow(dead_code)] // Planned for job diff feature
    pub diff_view_active: bool,

    /// Diff content lines (left = base job, right = compare job).
    #[allow(dead_code)] // Planned for job diff feature
    pub diff_lines: Vec<(String, String, DiffLineType)>,

    /// Scroll offset for diff view.
    #[allow(dead_code)] // Planned for job diff feature
    pub diff_scroll: usize,
}

#[allow(dead_code)] // Methods for incremental migration
impl JobsState {
    /// Get the currently selected job.
    pub fn selected_job(&self) -> Option<&JobStatus> {
        self.selected_index.and_then(|idx| self.jobs.get(idx))
    }

    /// Select the next job in the list.
    pub fn select_next(&mut self) {
        if self.jobs.is_empty() {
            return;
        }
        let i = match self.selected_index {
            Some(i) if i >= self.jobs.len() - 1 => 0,
            Some(i) => i + 1,
            None => 0,
        };
        self.selected_index = Some(i);
    }

    /// Select the previous job in the list.
    pub fn select_prev(&mut self) {
        if self.jobs.is_empty() {
            return;
        }
        let i = match self.selected_index {
            Some(0) => self.jobs.len() - 1,
            Some(i) => i - 1,
            None => 0,
        };
        self.selected_index = Some(i);
    }

    /// Clear pending cancel confirmation.
    pub fn clear_pending_cancel(&mut self) {
        self.pending_cancel_pk = None;
        self.pending_cancel_time = None;
    }

    /// Clear pending submit confirmation.
    pub fn clear_pending_submit(&mut self) {
        self.pending_submit = false;
        self.pending_submit_time = None;
    }

    /// Check if cancel confirmation has expired (3 seconds).
    pub fn is_cancel_expired(&self) -> bool {
        const CANCEL_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(3);
        self.pending_cancel_time
            .map(|t| t.elapsed() > CANCEL_TIMEOUT)
            .unwrap_or(false)
    }

    /// Check if submit confirmation has expired (3 seconds).
    pub fn is_submit_expired(&self) -> bool {
        const SUBMIT_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(3);
        self.pending_submit_time
            .map(|t| t.elapsed() > SUBMIT_TIMEOUT)
            .unwrap_or(false)
    }
}
