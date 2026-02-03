//! State management module.
//!
//! This module contains types related to application state management,
//! including the MVU/Reducer action types, tab definitions, and
//! supporting state structs for modals and domain-specific views.

use std::collections::HashSet;

use ratatui::widgets::TableState;
use tui_textarea::TextArea;
use tachyonfx::{fx, Effect, Motion};
use ratatui::style::Color;

use crate::models::{
    D12GenerationConfig, DftCode, JobStatus, MaterialResult, RunnerType, StructurePreview, Template,
    VaspGenerationConfig, WorkflowType,
};

pub mod actions;

pub use actions::*;

/// Configuration for a single job in a batch.
#[derive(Debug, Clone)]
pub struct BatchJobConfig {
    pub name: String,
    pub input_content: String,
    pub status: String, // "READY", "SUBMITTING", "SUCCESS", "ERROR"
}

/// State for the Batch Job Submission modal.
pub struct BatchSubmissionState {
    /// Whether the modal is active.
    pub active: bool,

    /// Common settings for all jobs in the batch.
    pub common_runner_type: RunnerType,
    pub common_cluster_id: Option<i32>,
    pub common_mpi_ranks: String,
    pub common_walltime: String,
    pub common_memory_gb: String,
    pub common_partition: String,

    /// List of job configurations.
    pub jobs: Vec<BatchJobConfig>,

    /// Currently selected job index.
    pub selected_job_index: Option<usize>,

    /// Currently focused field (can be settings or buttons).
    pub focused_field: BatchSubmissionField,

    /// Error message.
    pub error: Option<String>,

    /// Whether submission is in progress.
    pub submitting: bool,

    /// Request ID for async operations.
    pub request_id: usize,

    /// Animation effect.
    pub effect: Option<Effect>,

    /// Whether modal is closing.
    pub closing: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum BatchSubmissionField {
    #[default]
    Cluster,
    MpiRanks,
    Walltime,
    Memory,
    Partition,
    JobList,
    BtnAdd,
    BtnRemove,
    BtnSubmit,
    BtnCancel,
}

impl BatchSubmissionField {
    pub fn next(self) -> Self {
        match self {
            Self::Cluster => Self::MpiRanks,
            Self::MpiRanks => Self::Walltime,
            Self::Walltime => Self::Memory,
            Self::Memory => Self::Partition,
            Self::Partition => Self::JobList,
            Self::JobList => Self::BtnAdd,
            Self::BtnAdd => Self::BtnRemove,
            Self::BtnRemove => Self::BtnSubmit,
            Self::BtnSubmit => Self::BtnCancel,
            Self::BtnCancel => Self::Cluster,
        }
    }

    pub fn prev(self) -> Self {
        match self {
            Self::Cluster => Self::BtnCancel,
            Self::MpiRanks => Self::Cluster,
            Self::Walltime => Self::MpiRanks,
            Self::Memory => Self::Walltime,
            Self::Partition => Self::Memory,
            Self::JobList => Self::Partition,
            Self::BtnAdd => Self::JobList,
            Self::BtnRemove => Self::BtnAdd,
            Self::BtnSubmit => Self::BtnRemove,
            Self::BtnCancel => Self::BtnSubmit,
        }
    }
}

impl Default for BatchSubmissionState {
    fn default() -> Self {
        Self {
            active: false,
            common_runner_type: RunnerType::Local,
            common_cluster_id: None,
            common_mpi_ranks: "4".to_string(),
            common_walltime: "24:00:00".to_string(),
            common_memory_gb: "32".to_string(),
            common_partition: "".to_string(),
            jobs: Vec::new(),
            selected_job_index: None,
            focused_field: BatchSubmissionField::default(),
            error: None,
            submitting: false,
            request_id: 0,
            effect: None,
            closing: false,
        }
    }
}

impl std::fmt::Debug for BatchSubmissionState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BatchSubmissionState")
            .field("active", &self.active)
            .field("jobs_count", &self.jobs.len())
            .field("submitting", &self.submitting)
            .finish()
    }
}

impl BatchSubmissionState {
    pub fn open(&mut self) {
        self.active = true;
        self.closing = false;
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));
        
        self.jobs.clear();
        self.selected_job_index = None;
        self.focused_field = BatchSubmissionField::default();
        self.error = None;
        self.submitting = false;
    }

    pub fn close(&mut self) {
        self.closing = true;
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
        self.request_id += 1;
    }

    pub fn add_job(&mut self, name: String, content: String) {
        self.jobs.push(BatchJobConfig {
            name,
            input_content: content,
            status: "READY".to_string(),
        });
        if self.selected_job_index.is_none() {
            self.selected_job_index = Some(0);
        }
    }

    pub fn remove_selected(&mut self) {
        if let Some(idx) = self.selected_job_index {
            self.jobs.remove(idx);
            if self.jobs.is_empty() {
                self.selected_job_index = None;
            } else if idx >= self.jobs.len() {
                self.selected_job_index = Some(self.jobs.len() - 1);
            }
        }
    }
}

// =============================================================================
// Materials Project Search Modal State
// =============================================================================

/// State for the Materials Project search modal.
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

    /// VASP generation config.
    pub vasp_config: VaspGenerationConfig,

    /// Structure preview data for selected material.
    pub preview: Option<StructurePreview>,

    /// Whether a preview is being fetched.
    pub preview_loading: bool,

    /// Request ID for the current preview fetch.
    pub preview_request_id: usize,

    /// Animation effect for open/close.
    pub effect: Option<Effect>,

    /// Whether the modal is closing.
    pub closing: bool,

    // ===== Job Submission State (quacc) =====
    /// Selected cluster index for job submission.
    pub selected_cluster_idx: usize,

    /// Whether a job submission is in progress.
    pub submitting: bool,

    /// Request ID for the current job submission.
    pub submit_request_id: usize,

    /// Last submission error message.
    pub submit_error: Option<String>,

    /// Last submitted job ID (for success feedback).
    pub last_submitted_job_id: Option<String>,

    /// Generated POSCAR content (from VASP generation).
    pub generated_poscar: Option<String>,
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
            vasp_config: VaspGenerationConfig::default(),
            preview: None,
            preview_loading: false,
            preview_request_id: 0,
            effect: None,
            closing: false,
            // Job submission state
            selected_cluster_idx: 0,
            submitting: false,
            submit_request_id: 0,
            submit_error: None,
            last_submitted_job_id: None,
            generated_poscar: None,
        }
    }
}

impl<'a> std::fmt::Debug for MaterialsSearchState<'a> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MaterialsSearchState")
            .field("active", &self.active)
            .field("closing", &self.closing)
            .field("loading", &self.loading)
            .field("status", &self.status)
            // Skip effect and TextArea
            .finish()
    }
}

impl<'a> MaterialsSearchState<'a> {
    /// Open the modal.
    pub fn open(&mut self) {
        self.active = true;
        self.closing = false;
        // Slide in from bottom
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));

        self.results.clear();
        self.table_state = TableState::default();
        self.loading = false;
        self.status = Some("Enter a formula and press Enter to search".to_string());
        self.status_is_error = false;
        self.selected_for_import = None;
        self.preview = None;
        self.preview_loading = false;
        // Clear input for fresh search
        self.input = TextArea::default();
        self.input
            .set_placeholder_text("Enter formula (e.g., MoS2, Si, LiFePO4)");
        // Reset submission state
        self.submitting = false;
        self.submit_error = None;
        self.last_submitted_job_id = None;
        self.generated_poscar = None;
    }

    /// Close the modal and reset state.
    pub fn close(&mut self) {
        self.closing = true;
        // Slide out to bottom
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
        
        // Increment request_id to ignore any pending responses
        self.request_id += 1;
        self.preview_request_id += 1;
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

    /// Clear the structure preview (call when selection changes).
    pub fn clear_preview(&mut self) {
        self.preview = None;
        self.preview_loading = false;
    }

    /// Set preview loading state.
    pub fn set_preview_loading(&mut self, loading: bool) {
        self.preview_loading = loading;
        if loading {
            self.preview = None;
        }
    }

    /// Set the preview data.
    pub fn set_preview(&mut self, preview: StructurePreview) {
        self.preview = Some(preview);
        self.preview_loading = false;
    }

    /// Cycle to the next VASP preset.
    pub fn cycle_vasp_preset(&mut self) {
        self.vasp_config.preset = self.vasp_config.preset.next();
    }

    /// Cycle through k-point density options: 500 → 1000 → 2000 → 500
    pub fn cycle_kppra(&mut self) {
        self.vasp_config.kppra = match self.vasp_config.kppra {
            500 => 1000,
            1000 => 2000,
            2000 => 4000,
            _ => 500,
        };
    }

    // ===== Job Submission Methods =====

    /// Cycle to the next cluster in the list.
    pub fn cycle_cluster(&mut self, max: usize) {
        if max == 0 {
            return;
        }
        self.selected_cluster_idx = (self.selected_cluster_idx + 1) % max;
    }

    /// Start job submission (set loading state).
    pub fn start_submit(&mut self) {
        self.submitting = true;
        self.submit_error = None;
    }

    /// Handle successful job submission.
    pub fn submit_success(&mut self, job_id: String) {
        self.submitting = false;
        self.last_submitted_job_id = Some(job_id);
        self.submit_error = None;
    }

    /// Handle failed job submission.
    pub fn submit_failure(&mut self, error: String) {
        self.submitting = false;
        self.submit_error = Some(error);
        self.last_submitted_job_id = None;
    }

    /// Check if we have the necessary data for job submission.
    pub fn can_submit(&self) -> bool {
        self.generated_poscar.is_some() && !self.submitting
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
pub struct NewJobState {
    /// Whether the modal is currently active/visible.
    pub active: bool,

    /// Animation effect for open/close.
    pub effect: Option<Effect>,

    /// Whether the modal is closing.
    pub closing: bool,

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
            effect: None,
            closing: false,
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

impl std::fmt::Debug for NewJobState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("NewJobState")
            .field("active", &self.active)
            .field("closing", &self.closing)
            .field("focused_field", &self.focused_field)
            .field("job_name", &self.job_name)
            // Skip effect
            .finish()
    }
}

impl NewJobState {
    /// Open the new job modal.
    pub fn open(&mut self) {
        self.active = true;
        self.closing = false;
        // Slide in from bottom (Motion::DownToUp)
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));
        
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
        self.closing = true;
        // Slide out to bottom (Motion::UpToDown)
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
        // Don't set active = false here; wait for animation to finish
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
// Template Browser Modal State
// =============================================================================

/// State for the calculation template browser modal.
pub struct TemplateBrowserState {
    /// Whether the modal is currently active/visible.
    pub active: bool,

    /// Loaded templates from the backend.
    pub templates: Vec<Template>,

    /// Currently selected template index.
    pub selected_index: Option<usize>,

    /// Whether templates are being loaded.
    pub loading: bool,

    /// Error message to display.
    pub error: Option<String>,

    /// Request ID for async operations.
    pub request_id: usize,

    /// Animation effect for open/close.
    pub effect: Option<Effect>,

    /// Whether the modal is closing.
    pub closing: bool,
}

impl Default for TemplateBrowserState {
    fn default() -> Self {
        Self {
            active: false,
            templates: Vec::new(),
            selected_index: None,
            loading: false,
            error: None,
            request_id: 0,
            effect: None,
            closing: false,
        }
    }
}

impl std::fmt::Debug for TemplateBrowserState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("TemplateBrowserState")
            .field("active", &self.active)
            .field("closing", &self.closing)
            .field("loading", &self.loading)
            .field("templates_count", &self.templates.len())
            .finish()
    }
}

impl TemplateBrowserState {
    /// Open the modal.
    pub fn open(&mut self) {
        self.active = true;
        self.closing = false;
        // Slide in from bottom
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));
        
        self.templates.clear();
        self.selected_index = None;
        self.loading = true;
        self.error = None;
    }

    /// Close the modal.
    pub fn close(&mut self) {
        self.closing = true;
        // Slide out to bottom
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
        self.request_id += 1;
    }

    /// Select the next template.
    pub fn select_next(&mut self) {
        if self.templates.is_empty() {
            return;
        }
        let i = match self.selected_index {
            Some(i) if i >= self.templates.len() - 1 => 0,
            Some(i) => i + 1,
            None => 0,
        };
        self.selected_index = Some(i);
    }

    /// Select the previous template.
    pub fn select_prev(&mut self) {
        if self.templates.is_empty() {
            return;
        }
        let i = match self.selected_index {
            Some(0) => self.templates.len() - 1,
            Some(i) => i - 1,
            None => 0,
        };
        self.selected_index = Some(i);
    }

    /// Get the currently selected template.
    pub fn selected_template(&self) -> Option<&Template> {
        self.selected_index.and_then(|i| self.templates.get(i))
    }
}

// =============================================================================
// Workflow Configuration Modal State
// =============================================================================

/// Workflow config form fields (union across workflows).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkflowConfigField {
    // Convergence
    ConvergenceParameter,
    ConvergenceValues,
    ConvergenceBaseInput,
    // Band Structure
    BandSourceJob,
    BandPathPreset,
    BandCustomPath,
    // Phonon
    PhononSupercellA,
    PhononSupercellB,
    PhononSupercellC,
    PhononDisplacement,
    // EOS
    EosStrainMin,
    EosStrainMax,
    EosStrainSteps,
    // Geometry Optimization
    GeomFmax,
    GeomMaxSteps,
    // Buttons
    BtnLaunch,
    BtnCancel,
}

/// Convergence study parameter options.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConvergenceParameter {
    Kpoints,
    Shrink,
    Basis,
    Encut,
    Ecutwfc,
}

impl ConvergenceParameter {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Kpoints => "kpoints",
            Self::Shrink => "shrink",
            Self::Basis => "basis",
            Self::Encut => "encut",
            Self::Ecutwfc => "ecutwfc",
        }
    }

    pub fn next(self) -> Self {
        match self {
            Self::Kpoints => Self::Shrink,
            Self::Shrink => Self::Basis,
            Self::Basis => Self::Encut,
            Self::Encut => Self::Ecutwfc,
            Self::Ecutwfc => Self::Kpoints,
        }
    }

    pub fn prev(self) -> Self {
        match self {
            Self::Kpoints => Self::Ecutwfc,
            Self::Shrink => Self::Kpoints,
            Self::Basis => Self::Shrink,
            Self::Encut => Self::Basis,
            Self::Ecutwfc => Self::Encut,
        }
    }
}

/// Band structure k-path presets.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BandPathPreset {
    Auto,
    Cubic,
    Fcc,
    Bcc,
    Hexagonal,
    Tetragonal,
    Custom,
}

impl BandPathPreset {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Cubic => "cubic",
            Self::Fcc => "fcc",
            Self::Bcc => "bcc",
            Self::Hexagonal => "hexagonal",
            Self::Tetragonal => "tetragonal",
            Self::Custom => "custom",
        }
    }

    pub fn next(self) -> Self {
        match self {
            Self::Auto => Self::Cubic,
            Self::Cubic => Self::Fcc,
            Self::Fcc => Self::Bcc,
            Self::Bcc => Self::Hexagonal,
            Self::Hexagonal => Self::Tetragonal,
            Self::Tetragonal => Self::Custom,
            Self::Custom => Self::Auto,
        }
    }

    pub fn prev(self) -> Self {
        match self {
            Self::Auto => Self::Custom,
            Self::Cubic => Self::Auto,
            Self::Fcc => Self::Cubic,
            Self::Bcc => Self::Fcc,
            Self::Hexagonal => Self::Bcc,
            Self::Tetragonal => Self::Hexagonal,
            Self::Custom => Self::Tetragonal,
        }
    }
}

impl Default for BandPathPreset {
    fn default() -> Self {
        Self::Auto
    }
}

/// Convergence workflow config state.
#[derive(Debug)]
pub struct ConvergenceConfigState {
    pub parameter: ConvergenceParameter,
    pub values: String,
    pub base_input: TextArea<'static>,
}

impl Default for ConvergenceConfigState {
    fn default() -> Self {
        let mut base_input = TextArea::default();
        base_input.set_placeholder_text("Paste base .d12 input here");
        Self {
            parameter: ConvergenceParameter::Shrink,
            values: "4,6,8,10,12".to_string(),
            base_input,
        }
    }
}

impl ConvergenceConfigState {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
}

/// Band structure workflow config state.
#[derive(Debug, Default)]
pub struct BandStructureConfigState {
    pub source_job_pk: String,
    pub path_preset: BandPathPreset,
    pub custom_path: String,
}

/// Phonon workflow config state.
#[derive(Debug, Default)]
pub struct PhononConfigState {
    pub supercell_a: String,
    pub supercell_b: String,
    pub supercell_c: String,
    pub displacement: String,
}

/// Equation of state workflow config state.
#[derive(Debug, Default)]
pub struct EosConfigState {
    pub strain_min: String,
    pub strain_max: String,
    pub strain_steps: String,
}

/// Geometry optimization workflow config state.
#[derive(Debug, Default)]
pub struct GeometryOptConfigState {
    pub fmax: String,
    pub max_steps: String,
}

/// State for the workflow configuration modal.
#[derive(Debug)]
pub struct WorkflowConfigState {
    /// Whether the modal is active.
    pub active: bool,
    /// Selected workflow type for configuration.
    pub workflow_type: WorkflowType,
    /// Currently focused field.
    pub focused_field: WorkflowConfigField,
    /// Error message (validation).
    pub error: Option<String>,
    /// Status message (info/success).
    pub status: Option<String>,
    /// Whether submission is in progress.
    pub submitting: bool,
    /// Request ID for async operations.
    pub request_id: usize,
    /// Animation effect for open/close.
    pub effect: Option<Effect>,
    /// Whether the modal is closing.
    pub closing: bool,
    /// Convergence config.
    pub convergence: ConvergenceConfigState,
    /// Band structure config.
    pub band_structure: BandStructureConfigState,
    /// Phonon config.
    pub phonon: PhononConfigState,
    /// EOS config.
    pub eos: EosConfigState,
    /// Geometry optimization config.
    pub geometry_opt: GeometryOptConfigState,
}

impl Default for WorkflowConfigState {
    fn default() -> Self {
        Self {
            active: false,
            workflow_type: WorkflowType::Convergence,
            focused_field: WorkflowConfigField::ConvergenceParameter,
            error: None,
            status: None,
            submitting: false,
            request_id: 0,
            effect: None,
            closing: false,
            convergence: ConvergenceConfigState::default(),
            band_structure: BandStructureConfigState::default(),
            phonon: PhononConfigState::default(),
            eos: EosConfigState::default(),
            geometry_opt: GeometryOptConfigState::default(),
        }
    }
}

impl WorkflowConfigState {
    /// Open the workflow config modal for the given workflow type.
    pub fn open(&mut self, workflow_type: WorkflowType) {
        self.active = true;
        self.closing = false;
        self.workflow_type = workflow_type;
        self.focused_field = Self::default_field(workflow_type);
        self.error = None;
        self.status = None;
        self.submitting = false;
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));
        self.reset_for(workflow_type);
    }

    /// Close the workflow config modal.
    pub fn close(&mut self) {
        self.closing = true;
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
        self.request_id += 1;
    }

    /// Reset the config for the specified workflow type.
    pub fn reset_for(&mut self, workflow_type: WorkflowType) {
        match workflow_type {
            WorkflowType::Convergence => self.convergence.reset(),
            WorkflowType::BandStructure => self.band_structure = BandStructureConfigState::default(),
            WorkflowType::Phonon => self.phonon = PhononConfigState::default(),
            WorkflowType::Eos => self.eos = EosConfigState::default(),
            WorkflowType::GeometryOptimization => {
                self.geometry_opt = GeometryOptConfigState::default();
            }
        }
    }

    /// Move focus to the next field (workflow-specific order).
    pub fn focus_next(&mut self) {
        self.focused_field = self.next_field(self.focused_field);
    }

    /// Move focus to the previous field (workflow-specific order).
    pub fn focus_prev(&mut self) {
        self.focused_field = self.prev_field(self.focused_field);
    }

    fn next_field(&self, current: WorkflowConfigField) -> WorkflowConfigField {
        match self.workflow_type {
            WorkflowType::Convergence => match current {
                WorkflowConfigField::ConvergenceParameter => WorkflowConfigField::ConvergenceValues,
                WorkflowConfigField::ConvergenceValues => WorkflowConfigField::ConvergenceBaseInput,
                WorkflowConfigField::ConvergenceBaseInput => WorkflowConfigField::BtnLaunch,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::ConvergenceParameter,
                _ => WorkflowConfigField::ConvergenceParameter,
            },
            WorkflowType::BandStructure => match current {
                WorkflowConfigField::BandSourceJob => WorkflowConfigField::BandPathPreset,
                WorkflowConfigField::BandPathPreset => WorkflowConfigField::BandCustomPath,
                WorkflowConfigField::BandCustomPath => WorkflowConfigField::BtnLaunch,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::BandSourceJob,
                _ => WorkflowConfigField::BandSourceJob,
            },
            WorkflowType::Phonon => match current {
                WorkflowConfigField::PhononSupercellA => WorkflowConfigField::PhononSupercellB,
                WorkflowConfigField::PhononSupercellB => WorkflowConfigField::PhononSupercellC,
                WorkflowConfigField::PhononSupercellC => WorkflowConfigField::PhononDisplacement,
                WorkflowConfigField::PhononDisplacement => WorkflowConfigField::BtnLaunch,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::PhononSupercellA,
                _ => WorkflowConfigField::PhononSupercellA,
            },
            WorkflowType::Eos => match current {
                WorkflowConfigField::EosStrainMin => WorkflowConfigField::EosStrainMax,
                WorkflowConfigField::EosStrainMax => WorkflowConfigField::EosStrainSteps,
                WorkflowConfigField::EosStrainSteps => WorkflowConfigField::BtnLaunch,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::EosStrainMin,
                _ => WorkflowConfigField::EosStrainMin,
            },
            WorkflowType::GeometryOptimization => match current {
                WorkflowConfigField::GeomFmax => WorkflowConfigField::GeomMaxSteps,
                WorkflowConfigField::GeomMaxSteps => WorkflowConfigField::BtnLaunch,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::GeomFmax,
                _ => WorkflowConfigField::GeomFmax,
            },
        }
    }

    fn prev_field(&self, current: WorkflowConfigField) -> WorkflowConfigField {
        match self.workflow_type {
            WorkflowType::Convergence => match current {
                WorkflowConfigField::ConvergenceParameter => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::ConvergenceValues => WorkflowConfigField::ConvergenceParameter,
                WorkflowConfigField::ConvergenceBaseInput => WorkflowConfigField::ConvergenceValues,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::ConvergenceBaseInput,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::BtnLaunch,
                _ => WorkflowConfigField::ConvergenceParameter,
            },
            WorkflowType::BandStructure => match current {
                WorkflowConfigField::BandSourceJob => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::BandPathPreset => WorkflowConfigField::BandSourceJob,
                WorkflowConfigField::BandCustomPath => WorkflowConfigField::BandPathPreset,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::BandCustomPath,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::BtnLaunch,
                _ => WorkflowConfigField::BandSourceJob,
            },
            WorkflowType::Phonon => match current {
                WorkflowConfigField::PhononSupercellA => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::PhononSupercellB => WorkflowConfigField::PhononSupercellA,
                WorkflowConfigField::PhononSupercellC => WorkflowConfigField::PhononSupercellB,
                WorkflowConfigField::PhononDisplacement => WorkflowConfigField::PhononSupercellC,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::PhononDisplacement,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::BtnLaunch,
                _ => WorkflowConfigField::PhononSupercellA,
            },
            WorkflowType::Eos => match current {
                WorkflowConfigField::EosStrainMin => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::EosStrainMax => WorkflowConfigField::EosStrainMin,
                WorkflowConfigField::EosStrainSteps => WorkflowConfigField::EosStrainMax,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::EosStrainSteps,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::BtnLaunch,
                _ => WorkflowConfigField::EosStrainMin,
            },
            WorkflowType::GeometryOptimization => match current {
                WorkflowConfigField::GeomFmax => WorkflowConfigField::BtnCancel,
                WorkflowConfigField::GeomMaxSteps => WorkflowConfigField::GeomFmax,
                WorkflowConfigField::BtnLaunch => WorkflowConfigField::GeomMaxSteps,
                WorkflowConfigField::BtnCancel => WorkflowConfigField::BtnLaunch,
                _ => WorkflowConfigField::GeomFmax,
            },
        }
    }

    fn default_field(workflow_type: WorkflowType) -> WorkflowConfigField {
        match workflow_type {
            WorkflowType::Convergence => WorkflowConfigField::ConvergenceParameter,
            WorkflowType::BandStructure => WorkflowConfigField::BandSourceJob,
            WorkflowType::Phonon => WorkflowConfigField::PhononSupercellA,
            WorkflowType::Eos => WorkflowConfigField::EosStrainMin,
            WorkflowType::GeometryOptimization => WorkflowConfigField::GeomFmax,
        }
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
