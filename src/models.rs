//! Data models for CrystalMath.
//!
//! These Rust structs match the Pydantic models in `python/crystalmath/models.py`.
//! They use serde for JSON deserialization from the Python backend.

use ratatui::style::Color;
use serde::{Deserialize, Serialize};

/// Job execution state enum.
///
/// Matches Python's `JobState` enum exactly for serde compatibility.
/// Includes `Unknown` variant for forward-compatibility with new states.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum JobState {
    #[default]
    Created,
    Submitted,
    Queued,
    Running,
    Completed,
    Failed,
    Cancelled,
    /// Forward-compatible fallback for unknown states
    #[serde(other)]
    Unknown,
}

impl JobState {
    /// Get the display color for this state.
    ///
    /// Color scheme designed for quick visual scanning:
    /// - Green = Running (active, needs attention)
    /// - Blue = Completed (success, done)
    /// - Red = Failed (error, needs investigation)
    /// - Yellow = Queued/Submitted (waiting)
    pub fn color(&self) -> Color {
        match self {
            JobState::Created => Color::Gray,
            JobState::Submitted => Color::Yellow,
            JobState::Queued => Color::Yellow,
            JobState::Running => Color::Green,  // Green = active
            JobState::Completed => Color::Blue, // Blue = success/done
            JobState::Failed => Color::Red,
            JobState::Cancelled => Color::DarkGray,
            JobState::Unknown => Color::Magenta,
        }
    }

    /// Get a short display string.
    pub fn as_str(&self) -> &'static str {
        match self {
            JobState::Created => "Created",
            JobState::Submitted => "Submitted",
            JobState::Queued => "Queued",
            JobState::Running => "Running",
            JobState::Completed => "Completed",
            JobState::Failed => "Failed",
            JobState::Cancelled => "Cancelled",
            JobState::Unknown => "Unknown",
        }
    }

    /// Check if job is in a terminal state.
    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            JobState::Completed | JobState::Failed | JobState::Cancelled
        )
    }
}

/// DFT code type enum.
///
/// Represents the density functional theory software package used for calculations.
/// Includes `Unknown` variant for forward-compatibility with new codes.
///
/// # Serialization
///
/// Uses snake_case for JSON: `"crystal"`, `"vasp"`, `"quantum_espresso"`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DftCode {
    /// CRYSTAL23 - Solid-state DFT with Gaussian basis sets
    Crystal,
    /// VASP - Plane-wave pseudopotential DFT
    Vasp,
    /// Quantum ESPRESSO - Plane-wave DFT suite
    QuantumEspresso,
    /// Forward-compatible fallback for unknown codes
    #[serde(other)]
    Unknown,
}

impl DftCode {
    /// Get human-readable display name for the DFT code.
    ///
    /// Returns short uppercase abbreviations suitable for UI display:
    /// - `Crystal` → `"CRYSTAL"`
    /// - `Vasp` → `"VASP"`
    /// - `QuantumEspresso` → `"QE"`
    /// - `Unknown` → `"Unknown"`
    pub fn as_str(&self) -> &'static str {
        match self {
            DftCode::Crystal => "CRYSTAL",
            DftCode::Vasp => "VASP",
            DftCode::QuantumEspresso => "QE",
            DftCode::Unknown => "Unknown",
        }
    }
}

/// Template parameter definition.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParameterDefinition {
    pub name: String,
    #[serde(rename = "type")]
    pub param_type: String,
    pub default: Option<serde_json::Value>,
    pub description: String,
    pub min: Option<f64>,
    pub max: Option<f64>,
    pub options: Option<Vec<String>>,
    #[serde(default)]
    pub required: bool,
    pub depends_on: Option<std::collections::HashMap<String, serde_json::Value>>,
}

/// Calculation template.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Template {
    pub name: String,
    pub version: String,
    pub description: String,
    pub author: String,
    pub tags: Vec<String>,
    pub parameters: std::collections::HashMap<String, ParameterDefinition>,
    pub input_template: String,
    pub extends: Option<String>,
    #[serde(default)]
    pub includes: Vec<String>,
    #[serde(default)]
    pub metadata: serde_json::Map<String, serde_json::Value>,
}

/// SLURM queue entry for remote cluster monitoring.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SlurmQueueEntry {
    #[serde(default)]
    pub job_id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub user: String,
    #[serde(default)]
    pub partition: String,
    #[serde(default)]
    pub state: String,
    #[serde(default)]
    pub nodes: Option<i32>,
    #[serde(default)]
    pub gpus: Option<i32>,
    #[serde(default)]
    pub time_used: Option<String>,
    #[serde(default)]
    pub time_limit: Option<String>,
    #[serde(default)]
    pub node_list: Option<String>,
    #[serde(default)]
    pub state_reason: Option<String>,
}

/// Job execution backend type.
///
/// Determines where and how DFT calculations are executed.
/// Includes `Unknown` variant for forward-compatibility with new runners.
///
/// # Serialization
///
/// Uses snake_case for JSON: `"local"`, `"ssh"`, `"slurm"`, `"aiida"`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunnerType {
    /// Local execution via subprocess on the same machine
    Local,
    /// Remote execution via SSH to a cluster headnode
    Ssh,
    /// HPC batch scheduling via SLURM workload manager
    Slurm,
    /// Workflow automation via AiiDA provenance framework
    Aiida,
    /// Forward-compatible fallback for unknown runners
    #[serde(other)]
    Unknown,
}

impl RunnerType {
    /// Get human-readable display name for the runner type.
    ///
    /// Returns properly-cased names suitable for UI display:
    /// - `Local` → `"Local"`
    /// - `Ssh` → `"SSH"`
    /// - `Slurm` → `"SLURM"`
    /// - `Aiida` → `"AiiDA"`
    /// - `Unknown` → `"Unknown"`
    pub fn as_str(&self) -> &'static str {
        match self {
            RunnerType::Local => "Local",
            RunnerType::Ssh => "SSH",
            RunnerType::Slurm => "SLURM",
            RunnerType::Aiida => "AiiDA",
            RunnerType::Unknown => "Unknown",
        }
    }
}

/// Cluster execution type.
///
/// Determines the type of remote cluster for job execution.
///
/// # Serialization
///
/// Uses lowercase for JSON: `"ssh"`, `"slurm"`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum ClusterType {
    /// SSH-based remote execution
    #[default]
    Ssh,
    /// SLURM workload manager
    Slurm,
}

impl ClusterType {
    /// Get human-readable display name for the cluster type.
    ///
    /// Returns properly-cased names suitable for UI display:
    /// - `Ssh` → `"SSH"`
    /// - `Slurm` → `"SLURM"`
    pub fn as_str(&self) -> &'static str {
        match self {
            ClusterType::Ssh => "SSH",
            ClusterType::Slurm => "SLURM",
        }
    }

    /// Cycle to the next cluster type (for UI navigation).
    ///
    /// Returns:
    /// - `Ssh` → `Slurm`
    /// - `Slurm` → `Ssh`
    pub fn cycle(self) -> Self {
        match self {
            ClusterType::Ssh => ClusterType::Slurm,
            ClusterType::Slurm => ClusterType::Ssh,
        }
    }
}

/// Cluster connection status.
///
/// Represents the operational state of a remote cluster for job execution.
/// Includes `Unknown` variant for forward-compatibility with new statuses.
///
/// # Serialization
///
/// Uses snake_case for JSON: `"active"`, `"offline"`, `"testing"`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ClusterStatus {
    /// Cluster is online and accepting jobs
    #[default]
    Active,
    /// Cluster is offline or unreachable
    Offline,
    /// Cluster is being tested for connectivity
    Testing,
    /// Forward-compatible fallback for unknown statuses
    #[serde(other)]
    Unknown,
}

impl ClusterStatus {
    /// Get human-readable display string for the status.
    ///
    /// Returns properly-cased names suitable for UI display:
    /// - `Active` → `"Active"`
    /// - `Offline` → `"Offline"`
    /// - `Testing` → `"Testing"`
    /// - `Unknown` → `"Unknown"`
    pub fn as_str(&self) -> &'static str {
        match self {
            ClusterStatus::Active => "Active",
            ClusterStatus::Offline => "Offline",
            ClusterStatus::Testing => "Testing",
            ClusterStatus::Unknown => "Unknown",
        }
    }

    /// Check if the cluster is available for job submission.
    ///
    /// Returns `true` only if the cluster is in `Active` state.
    pub fn is_available(&self) -> bool {
        matches!(self, ClusterStatus::Active)
    }

    /// Get the display color for this status.
    ///
    /// Color scheme designed for quick visual scanning:
    /// - Green = Active (ready for jobs)
    /// - Red = Offline (unavailable)
    /// - Yellow = Testing (in progress)
    /// - Gray = Unknown (unknown state)
    pub fn color(&self) -> Color {
        match self {
            ClusterStatus::Active => Color::Green,
            ClusterStatus::Offline => Color::Red,
            ClusterStatus::Testing => Color::Yellow,
            ClusterStatus::Unknown => Color::Gray,
        }
    }
}

/// Lightweight job status for the sidebar list.
///
/// Matches Python's `JobStatus` model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobStatus {
    pub pk: i32,
    pub uuid: String,
    pub name: String,
    pub state: JobState,
    #[serde(default)]
    pub dft_code: Option<DftCode>,
    #[serde(default)]
    pub runner_type: Option<RunnerType>,
    #[serde(default)]
    pub progress_percent: f64,
    #[serde(default)]
    pub wall_time_seconds: Option<f64>,
    #[serde(default)]
    pub created_at: Option<String>,
    /// Error snippet for failed jobs (human-readable message).
    /// Examples: "SCF not converged", "Walltime exceeded", "Disk quota"
    #[serde(default)]
    pub error_snippet: Option<String>,
}

impl JobStatus {
    /// Format wall time for display.
    pub fn wall_time_display(&self) -> String {
        match self.wall_time_seconds {
            Some(secs) if secs >= 3600.0 => {
                let hours = (secs / 3600.0).floor();
                let mins = ((secs % 3600.0) / 60.0).floor();
                format!("{:.0}h {:.0}m", hours, mins)
            }
            Some(secs) if secs >= 60.0 => {
                let mins = (secs / 60.0).floor();
                let remaining = secs % 60.0;
                format!("{:.0}m {:.0}s", mins, remaining)
            }
            Some(secs) => format!("{:.1}s", secs),
            None => "-".to_string(),
        }
    }
}

/// Full job details for the Results view.
///
/// Contains computed results, timing information, and diagnostics for a completed job.
/// Matches Python's `JobDetails` model.
///
/// # Units
///
/// - `final_energy`: Total energy in **Hartree (Ha)**. 1 Ha ≈ 27.211 eV.
/// - `bandgap_ev`: Electronic bandgap in **electronvolts (eV)**.
/// - `cpu_time_seconds`: CPU time in **seconds**.
/// - `wall_time_seconds`: Wall-clock time in **seconds**.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct JobDetails {
    /// Database primary key
    pub pk: i32,
    /// Unique identifier (UUID4 format)
    #[serde(default)]
    pub uuid: Option<String>,
    /// User-provided job name
    pub name: String,
    /// Current execution state
    pub state: JobState,
    /// DFT software used for this calculation
    #[serde(default)]
    pub dft_code: Option<DftCode>,

    // Computed results
    /// Total energy in Hartree (Ha). 1 Ha ≈ 27.211 eV.
    #[serde(default)]
    pub final_energy: Option<f64>,
    /// Electronic bandgap in electronvolts (eV). 0.0 = metallic.
    #[serde(default)]
    pub bandgap_ev: Option<f64>,
    /// Whether SCF convergence criteria were satisfied
    #[serde(default)]
    pub convergence_met: bool,
    /// Number of SCF iterations performed
    #[serde(default)]
    pub scf_cycles: Option<i32>,

    // Timing
    /// CPU time consumed in seconds (may exceed wall time for parallel jobs)
    #[serde(default)]
    pub cpu_time_seconds: Option<f64>,
    /// Wall-clock elapsed time in seconds
    #[serde(default)]
    pub wall_time_seconds: Option<f64>,

    // Diagnostics
    /// Non-fatal warning messages from the calculation
    #[serde(default)]
    pub warnings: Vec<String>,
    /// Error messages (populated if job failed)
    #[serde(default)]
    pub errors: Vec<String>,
    /// Last N lines of stdout for debugging
    #[serde(default)]
    pub stdout_tail: Vec<String>,

    // Full results
    /// Arbitrary parsed results as JSON (code-specific)
    #[serde(default)]
    pub key_results: Option<serde_json::Value>,

    // Paths
    /// Working directory containing output files
    #[serde(default)]
    pub work_dir: Option<String>,
    /// Path to the input file used
    #[serde(default)]
    pub input_file: Option<String>,
}

impl JobDetails {
    /// Format final energy for display.
    pub fn energy_display(&self) -> String {
        match self.final_energy {
            Some(e) => format!("{:.6} Ha", e),
            None => "-".to_string(),
        }
    }

    /// Format bandgap for display.
    pub fn bandgap_display(&self) -> String {
        match self.bandgap_ev {
            Some(bg) => format!("{:.3} eV", bg),
            None => "-".to_string(),
        }
    }

    /// Calculate the number of lines in the results display.
    ///
    /// This is the single source of truth for content height,
    /// used by both the render function and scroll calculations.
    ///
    /// **LAYOUT SYNC WARNING**: This logic MUST match the actual line count
    /// in `src/ui/results.rs::render()`. If the render function changes its
    /// layout, update this method or scrolling will break.
    pub fn display_line_count(&self) -> usize {
        let mut lines = 7; // Base: Job, Status, empty, header, Energy, Gap, Convergence

        // Optional fields
        if self.scf_cycles.is_some() {
            lines += 1;
        }
        if self.wall_time_seconds.is_some() {
            lines += 1;
        }

        // Warnings section
        if !self.warnings.is_empty() {
            lines += 2; // Empty separator + header
            lines += self.warnings.len();
        }

        // Errors section
        if !self.errors.is_empty() {
            lines += 2; // Empty separator + header
            lines += self.errors.len();
        }

        lines
    }
}

/// Job submission request.
///
/// Used when creating a new job from the UI. Sent to Python backend as JSON.
///
/// # Required Fields
///
/// - `name`: Human-readable job name (appears in job list)
/// - `dft_code`: DFT code enum (serializes as snake_case: `"crystal"`, `"vasp"`, etc.)
/// - `parameters`: Code-specific parameters as JSON object
///
/// # Optional Fields
///
/// - `cluster_id`: Remote cluster for SSH/SLURM execution (None = local)
/// - `runner_type`: Execution backend enum (serializes as snake_case: `"local"`, `"ssh"`, etc.)
/// - `input_content`: Raw input file content (for editor submissions)
/// - `structure_path`: Path to structure file (for template-based submissions)
///
/// # Example
///
/// ```ignore
/// let job = JobSubmission::new("MgO relaxation", DftCode::Crystal)
///     .with_runner_type(RunnerType::Local)
///     .with_input_content(&d12_content);
/// ```
#[derive(Debug, Serialize)]
pub struct JobSubmission {
    /// Human-readable job name (displayed in job list)
    pub name: String,
    /// DFT code for the calculation (serializes as snake_case)
    pub dft_code: DftCode,
    /// Cluster ID for remote execution (None = local execution)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cluster_id: Option<i32>,
    /// Code-specific parameters (basis set, k-points, etc.)
    pub parameters: serde_json::Value,
    /// Path to structure file for template-based input generation
    #[serde(skip_serializing_if = "Option::is_none")]
    pub structure_path: Option<String>,
    /// Raw input file content (mutually exclusive with structure_path)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_content: Option<String>,
    /// Execution backend (serializes as snake_case)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub runner_type: Option<RunnerType>,
    /// Auxiliary files to copy (type -> path)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auxiliary_files: Option<std::collections::HashMap<String, String>>,
    /// SLURM scheduler options
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scheduler_options: Option<SchedulerOptions>,
    /// MPI ranks for parallel execution
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mpi_ranks: Option<i32>,
    /// Parallel mode ("serial" or "parallel")
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parallel_mode: Option<String>,
}

impl JobSubmission {
    /// Create a new job submission.
    pub fn new(name: &str, dft_code: DftCode) -> Self {
        Self {
            name: name.to_string(),
            dft_code,
            cluster_id: None,
            parameters: serde_json::json!({}),
            structure_path: None,
            input_content: None,
            runner_type: None,
            auxiliary_files: None,
            scheduler_options: None,
            mpi_ranks: None,
            parallel_mode: None,
        }
    }

    /// Set the input file content.
    pub fn with_input_content(mut self, content: &str) -> Self {
        self.input_content = Some(content.to_string());
        self
    }

    /// Set the parameters.
    pub fn with_parameters(mut self, params: serde_json::Value) -> Self {
        self.parameters = params;
        self
    }

    /// Set the runner type for job execution.
    pub fn with_runner_type(mut self, runner: RunnerType) -> Self {
        self.runner_type = Some(runner);
        self
    }

    /// Set the cluster ID for remote execution.
    pub fn with_cluster_id(mut self, id: i32) -> Self {
        self.cluster_id = Some(id);
        self
    }

    /// Set auxiliary files (type -> path).
    pub fn with_auxiliary_files(
        mut self,
        files: std::collections::HashMap<String, String>,
    ) -> Self {
        self.auxiliary_files = Some(files);
        self
    }

    /// Set scheduler options.
    pub fn with_scheduler_options(mut self, options: SchedulerOptions) -> Self {
        self.scheduler_options = Some(options);
        self
    }

    /// Set MPI ranks.
    pub fn with_mpi_ranks(mut self, ranks: i32) -> Self {
        self.mpi_ranks = Some(ranks);
        self
    }

    /// Set parallel mode.
    pub fn with_parallel_mode(mut self, mode: &str) -> Self {
        self.parallel_mode = Some(mode.to_string());
        self
    }
}

/// Scheduler resource configuration (SLURM).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SchedulerOptions {
    pub walltime: String,
    pub memory_gb: String,
    pub cpus_per_task: i32,
    pub nodes: i32,
    pub partition: Option<String>,
}

/// Cluster configuration for remote execution.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ClusterConfig {
    #[serde(default)]
    pub id: Option<i32>,
    pub name: String,
    pub cluster_type: ClusterType,
    pub hostname: String,
    #[serde(default = "default_port")]
    pub port: i32,
    pub username: String,
    #[serde(default)]
    pub key_file: Option<String>,
    #[serde(default)]
    pub remote_workdir: Option<String>,
    #[serde(default)]
    pub queue_name: Option<String>,
    #[serde(default = "default_max_concurrent")]
    pub max_concurrent: i32,
    #[serde(default)]
    pub status: ClusterStatus,
}

fn default_port() -> i32 {
    22
}

fn default_max_concurrent() -> i32 {
    4
}

/// Result of testing a cluster SSH connection.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ClusterConnectionResult {
    #[serde(default)]
    pub success: bool,
    #[serde(default)]
    pub hostname: Option<String>,
    #[serde(default)]
    pub system_info: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
}

// ==================== SLURM Cancel Result ====================

/// Result of a SLURM job cancellation request.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SlurmCancelResult {
    #[serde(default)]
    pub success: bool,
    #[serde(default)]
    pub message: Option<String>,
}

// ==================== VASP Multi-File Input ====================

/// VASP input file contents for multi-file submissions.
///
/// When `JobSubmission.dft_code == "vasp"`, the `parameters` field should
/// contain a serialized `VaspInputFiles` struct for type-safe handling of
/// VASP's four required input files.
///
/// # Example
///
/// ```ignore
/// let vasp_files = VaspInputFiles {
///     poscar: "Placeholder\n1.0\n5.0 0.0 0.0\n...".to_string(),
///     incar: "ENCUT = 520\nEDIFF = 1E-6\n...".to_string(),
///     kpoints: "Automatic\n0\nMonkhorst-Pack\n3 3 1\n...".to_string(),
///     potcar_config: "Elements: Si O".to_string(),
/// };
/// let params = serde_json::to_value(&vasp_files)?;
/// let job = JobSubmission::new("vasp-calc", DftCode::Vasp)
///     .with_parameters(params);
/// ```
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct VaspInputFiles {
    /// POSCAR: Atomic structure and lattice vectors
    pub poscar: String,
    /// INCAR: Calculation parameters (ENCUT, EDIFF, ISMEAR, etc.)
    pub incar: String,
    /// KPOINTS: k-point mesh for Brillouin zone sampling
    pub kpoints: String,
    /// POTCAR configuration: Space-separated element symbols (e.g., "Elements: Si O")
    pub potcar_config: String,
}

// ==================== Materials Project API Models ====================

/// Material search result from Materials Project.
///
/// Matches the JSON returned by Python's MaterialRecord.to_dict().
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MaterialResult {
    pub material_id: String,
    #[serde(default)]
    pub formula: Option<String>,
    #[serde(default)]
    pub formula_pretty: Option<String>,
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub properties: MaterialProperties,
    #[serde(default)]
    pub metadata: serde_json::Value,
    /// Raw structure data (kept as JSON for flexibility)
    #[serde(default)]
    pub structure: Option<serde_json::Value>,
}

impl MaterialResult {
    /// Get the display formula (pretty if available, otherwise standard).
    pub fn display_formula(&self) -> &str {
        self.formula_pretty
            .as_deref()
            .or(self.formula.as_deref())
            .unwrap_or("-")
    }

    /// Get band gap display string.
    pub fn band_gap_display(&self) -> String {
        match self.properties.band_gap {
            Some(bg) => format!("{:.2}", bg),
            None => "-".to_string(),
        }
    }

    /// Get space group from metadata.
    pub fn space_group(&self) -> String {
        if let Some(sg) = self.metadata.get("space_group") {
            if let Some(symbol) = sg.get("symbol").and_then(|s| s.as_str()) {
                return symbol.to_string();
            }
            if let Some(s) = sg.as_str() {
                return s.to_string();
            }
        }
        "-".to_string()
    }

    /// Check if material is thermodynamically stable.
    pub fn is_stable(&self) -> bool {
        self.properties
            .energy_above_hull
            .map(|e| e < 0.025)
            .unwrap_or(false)
    }

    /// Get stability display string.
    pub fn stability_display(&self) -> String {
        match self.properties.energy_above_hull {
            Some(e) if e < 0.025 => "Stable".to_string(),
            Some(e) => format!("+{:.3} eV", e),
            None => "-".to_string(),
        }
    }
}

/// Material properties from Materials Project.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct MaterialProperties {
    #[serde(default)]
    pub band_gap: Option<f64>,
    #[serde(default)]
    pub energy_above_hull: Option<f64>,
    #[serde(default)]
    pub formation_energy_per_atom: Option<f64>,
    #[serde(default)]
    pub energy_per_atom: Option<f64>,
    #[serde(default)]
    pub total_magnetization: Option<f64>,
    #[serde(default)]
    pub is_metal: Option<bool>,
}

/// Configuration for .d12 generation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct D12GenerationConfig {
    #[serde(default = "default_functional")]
    pub functional: String,
    #[serde(default = "default_basis_set")]
    pub basis_set: String,
    #[serde(default = "default_shrink")]
    pub shrink: (i32, i32),
    #[serde(default)]
    pub optimize: bool,
}

fn default_functional() -> String {
    "PBE".to_string()
}

fn default_basis_set() -> String {
    "POB-TZVP-REV2".to_string()
}

fn default_shrink() -> (i32, i32) {
    (8, 8)
}

impl Default for D12GenerationConfig {
    fn default() -> Self {
        Self {
            functional: default_functional(),
            basis_set: default_basis_set(),
            shrink: default_shrink(),
            optimize: false,
        }
    }
}

/// API response wrapper matching Python's `_ok_response` / `_error_response`.
///
/// All Python API endpoints return this envelope structure for consistent
/// error handling between the Rust TUI and Python backend.
///
/// # JSON Format
///
/// Success:
/// ```json
/// {"ok": true, "data": {...}}
/// ```
///
/// Error:
/// ```json
/// {"ok": false, "error": {"code": "NOT_FOUND", "message": "Job 42 not found"}}
/// ```
///
/// # Invariants
///
/// - If `ok == true`, `data` MUST be `Some(T)` (enforced by Python backend)
/// - If `ok == false`, `error` SHOULD be `Some(ApiError)` (may be None for edge cases)
#[derive(Debug, Clone, Deserialize)]
pub struct ApiResponse<T> {
    /// Success flag - determines which field contains the payload
    pub ok: bool,
    /// Response payload (present when `ok == true`)
    #[serde(default)]
    pub data: Option<T>,
    /// Error details (present when `ok == false`)
    #[serde(default)]
    pub error: Option<ApiError>,
}

impl<T> ApiResponse<T> {
    /// Convert to `Result`, extracting data or error message.
    ///
    /// # Returns
    ///
    /// - `Ok(T)` if `ok == true` and `data` is present
    /// - `Err(String)` if `ok == false` or data is missing
    ///
    /// # Example
    ///
    /// ```ignore
    /// let json = r#"{"ok": true, "data": ["job1", "job2"]}"#;
    /// let response: ApiResponse<Vec<String>> = serde_json::from_str(json)?;
    /// let jobs = response.into_result()?;  // Vec<String>
    /// ```
    pub fn into_result(self) -> Result<T, String> {
        if self.ok {
            self.data
                .ok_or_else(|| "Response ok but no data".to_string())
        } else {
            Err(self
                .error
                .map(|e| format!("{}: {}", e.code, e.message))
                .unwrap_or_else(|| "Unknown error".to_string()))
        }
    }
}

/// API error structure.
#[derive(Debug, Clone, Deserialize)]
pub struct ApiError {
    pub code: String,
    pub message: String,
}

// ==================== Workflow Models ====================

/// Available workflow types.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowType {
    /// Parameter convergence testing (SHRINK, k-points, ENCUT)
    Convergence,
    /// Band structure calculation with k-path
    BandStructure,
    /// Phonon calculation via finite displacements
    Phonon,
    /// Equation of state with Birch-Murnaghan fitting
    Eos,
    /// Geometry optimization (via AiiDA)
    GeometryOptimization,
}

impl WorkflowType {
    /// Get human-readable display name.
    pub fn as_str(&self) -> &'static str {
        match self {
            WorkflowType::Convergence => "Convergence Study",
            WorkflowType::BandStructure => "Band Structure",
            WorkflowType::Phonon => "Phonon Calculation",
            WorkflowType::Eos => "Equation of State",
            WorkflowType::GeometryOptimization => "Geometry Optimization",
        }
    }

    /// Get a short description.
    pub fn description(&self) -> &'static str {
        match self {
            WorkflowType::Convergence => "Test parameter convergence (k-points, cutoff, etc.)",
            WorkflowType::BandStructure => "Calculate band structure along high-symmetry k-path",
            WorkflowType::Phonon => "Compute phonon dispersion via finite displacements",
            WorkflowType::Eos => "Fit Birch-Murnaghan equation of state",
            WorkflowType::GeometryOptimization => "Optimize atomic positions and cell parameters",
        }
    }

    /// Get all workflow types.
    pub fn all() -> &'static [WorkflowType] {
        &[
            WorkflowType::Convergence,
            WorkflowType::BandStructure,
            WorkflowType::Phonon,
            WorkflowType::Eos,
            WorkflowType::GeometryOptimization,
        ]
    }
}

/// Workflow availability info from Python backend.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct WorkflowAvailability {
    /// Whether workflow module is available
    #[serde(default)]
    pub available: bool,
    /// Available workflow types
    #[serde(default)]
    pub workflow_types: Vec<String>,
    /// Whether AiiDA launcher is available
    #[serde(default)]
    pub aiida_available: bool,
}

/// Workflow status from Python backend.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowStatus {
    Pending,
    Running,
    Completed,
    Failed,
    Cancelled,
}

impl Default for WorkflowStatus {
    fn default() -> Self {
        WorkflowStatus::Pending
    }
}

impl WorkflowStatus {
    /// Get display color.
    pub fn color(&self) -> Color {
        match self {
            WorkflowStatus::Pending => Color::Yellow,
            WorkflowStatus::Running => Color::Green,
            WorkflowStatus::Completed => Color::Blue,
            WorkflowStatus::Failed => Color::Red,
            WorkflowStatus::Cancelled => Color::DarkGray,
        }
    }

    /// Get display string.
    pub fn as_str(&self) -> &'static str {
        match self {
            WorkflowStatus::Pending => "Pending",
            WorkflowStatus::Running => "Running",
            WorkflowStatus::Completed => "Completed",
            WorkflowStatus::Failed => "Failed",
            WorkflowStatus::Cancelled => "Cancelled",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_job_state_deserialize() {
        let json = r#""RUNNING""#;
        let state: JobState = serde_json::from_str(json).unwrap();
        assert_eq!(state, JobState::Running);
    }

    #[test]
    fn test_job_status_deserialize() {
        let json = r#"{
            "pk": 1,
            "uuid": "test-uuid",
            "name": "test-job",
            "state": "COMPLETED",
            "progress_percent": 100.0
        }"#;
        let status: JobStatus = serde_json::from_str(json).unwrap();
        assert_eq!(status.pk, 1);
        assert_eq!(status.state, JobState::Completed);
        assert_eq!(status.progress_percent, 100.0);
    }

    #[test]
    fn test_workflow_status_helpers() {
        assert_eq!(WorkflowStatus::Pending.as_str(), "Pending");
        assert_eq!(WorkflowStatus::Running.as_str(), "Running");
        assert_eq!(WorkflowStatus::Completed.as_str(), "Completed");
        assert_eq!(WorkflowStatus::Failed.as_str(), "Failed");
        assert_eq!(WorkflowStatus::Cancelled.as_str(), "Cancelled");
        assert_eq!(WorkflowStatus::Failed.color(), Color::Red);
    }

    #[test]
    fn test_job_details_deserialize() {
        let json = r#"{
            "pk": 42,
            "name": "mgo-scf",
            "state": "COMPLETED",
            "final_energy": -275.123,
            "convergence_met": true,
            "stdout_tail": ["line1", "line2"]
        }"#;
        let details: JobDetails = serde_json::from_str(json).unwrap();
        assert_eq!(details.pk, 42);
        assert!(details.convergence_met);
        assert_eq!(details.stdout_tail.len(), 2);
    }

    #[test]
    fn test_job_submission_serialize() {
        let submission =
            JobSubmission::new("test", DftCode::Crystal).with_input_content("CRYSTAL\n0 0 0\n225");

        let json = serde_json::to_string(&submission).unwrap();
        assert!(json.contains("\"name\":\"test\""));
        assert!(json.contains("\"dft_code\":\"crystal\""));
        assert!(json.contains("input_content"));
    }

    #[test]
    fn test_wall_time_display() {
        let mut status = JobStatus {
            pk: 1,
            uuid: "x".into(),
            name: "test".into(),
            state: JobState::Running,
            dft_code: None,
            runner_type: None,
            progress_percent: 0.0,
            wall_time_seconds: None,
            created_at: None,
            error_snippet: None,
        };

        assert_eq!(status.wall_time_display(), "-");

        status.wall_time_seconds = Some(45.5);
        assert_eq!(status.wall_time_display(), "45.5s");

        status.wall_time_seconds = Some(125.0);
        assert_eq!(status.wall_time_display(), "2m 5s");

        status.wall_time_seconds = Some(3725.0);
        assert_eq!(status.wall_time_display(), "1h 2m");
    }

    #[test]
    fn test_all_job_states() {
        let states = [
            ("\"CREATED\"", JobState::Created),
            ("\"SUBMITTED\"", JobState::Submitted),
            ("\"QUEUED\"", JobState::Queued),
            ("\"RUNNING\"", JobState::Running),
            ("\"COMPLETED\"", JobState::Completed),
            ("\"FAILED\"", JobState::Failed),
            ("\"CANCELLED\"", JobState::Cancelled),
        ];

        for (json, expected) in states {
            let state: JobState = serde_json::from_str(json).unwrap();
            assert_eq!(state, expected);
        }
    }

    #[test]
    fn test_job_state_unknown_fallback() {
        // Unknown states should deserialize to Unknown variant
        let state: JobState = serde_json::from_str("\"SOME_NEW_STATE\"").unwrap();
        assert_eq!(state, JobState::Unknown);
    }

    #[test]
    fn test_job_state_display() {
        assert_eq!(JobState::Created.as_str(), "Created");
        assert_eq!(JobState::Submitted.as_str(), "Submitted");
        assert_eq!(JobState::Queued.as_str(), "Queued");
        assert_eq!(JobState::Running.as_str(), "Running");
        assert_eq!(JobState::Completed.as_str(), "Completed");
        assert_eq!(JobState::Failed.as_str(), "Failed");
        assert_eq!(JobState::Cancelled.as_str(), "Cancelled");
        assert_eq!(JobState::Unknown.as_str(), "Unknown");
    }

    #[test]
    fn test_job_state_is_terminal() {
        assert!(!JobState::Created.is_terminal());
        assert!(!JobState::Submitted.is_terminal());
        assert!(!JobState::Queued.is_terminal());
        assert!(!JobState::Running.is_terminal());
        assert!(JobState::Completed.is_terminal());
        assert!(JobState::Failed.is_terminal());
        assert!(JobState::Cancelled.is_terminal());
    }

    #[test]
    fn test_dft_code_deserialize() {
        assert_eq!(
            serde_json::from_str::<DftCode>("\"crystal\"").unwrap(),
            DftCode::Crystal
        );
        assert_eq!(
            serde_json::from_str::<DftCode>("\"vasp\"").unwrap(),
            DftCode::Vasp
        );
    }

    #[test]
    fn test_runner_type_deserialize() {
        assert_eq!(
            serde_json::from_str::<RunnerType>("\"local\"").unwrap(),
            RunnerType::Local
        );
        assert_eq!(
            serde_json::from_str::<RunnerType>("\"ssh\"").unwrap(),
            RunnerType::Ssh
        );
        assert_eq!(
            serde_json::from_str::<RunnerType>("\"slurm\"").unwrap(),
            RunnerType::Slurm
        );
    }

    #[test]
    fn test_cluster_type_deserialize() {
        // Test lowercase JSON deserialization
        assert_eq!(
            serde_json::from_str::<ClusterType>("\"ssh\"").unwrap(),
            ClusterType::Ssh
        );
        assert_eq!(
            serde_json::from_str::<ClusterType>("\"slurm\"").unwrap(),
            ClusterType::Slurm
        );
    }

    #[test]
    fn test_cluster_type_serialize() {
        // Test lowercase JSON serialization
        assert_eq!(serde_json::to_string(&ClusterType::Ssh).unwrap(), "\"ssh\"");
        assert_eq!(
            serde_json::to_string(&ClusterType::Slurm).unwrap(),
            "\"slurm\""
        );
    }

    #[test]
    fn test_cluster_type_display() {
        assert_eq!(ClusterType::Ssh.as_str(), "SSH");
        assert_eq!(ClusterType::Slurm.as_str(), "SLURM");
    }

    #[test]
    fn test_cluster_type_cycle() {
        assert_eq!(ClusterType::Ssh.cycle(), ClusterType::Slurm);
        assert_eq!(ClusterType::Slurm.cycle(), ClusterType::Ssh);
    }

    #[test]
    fn test_cluster_type_default() {
        assert_eq!(ClusterType::default(), ClusterType::Ssh);
    }

    #[test]
    fn test_cluster_config_with_enum() {
        // Test that ClusterConfig serializes/deserializes properly with ClusterType enum
        let config = ClusterConfig {
            id: Some(1),
            name: "test-cluster".to_string(),
            cluster_type: ClusterType::Slurm,
            hostname: "hpc.example.com".to_string(),
            port: 22,
            username: "user".to_string(),
            key_file: None,
            remote_workdir: Some("/scratch/user".to_string()),
            queue_name: Some("compute".to_string()),
            max_concurrent: 4,
            status: ClusterStatus::Active,
        };

        // Serialize to JSON
        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("\"cluster_type\":\"slurm\""));
        assert!(json.contains("\"status\":\"active\""));

        // Deserialize back
        let deserialized: ClusterConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.cluster_type, ClusterType::Slurm);
        assert_eq!(deserialized.status, ClusterStatus::Active);
        assert_eq!(deserialized.name, "test-cluster");
    }

    #[test]
    fn test_job_details_with_none_values() {
        let json = r#"{
            "pk": 1,
            "name": "test",
            "state": "RUNNING",
            "stdout_tail": []
        }"#;
        let details: JobDetails = serde_json::from_str(json).unwrap();
        assert_eq!(details.final_energy, None);
        assert_eq!(details.bandgap_ev, None);
        assert!(!details.convergence_met);
        assert!(details.stdout_tail.is_empty());
    }

    #[test]
    fn test_job_submission_builder() {
        let submission =
            JobSubmission::new("my-job", DftCode::Vasp).with_input_content("ENCUT = 400");

        assert_eq!(submission.name, "my-job");
        assert_eq!(submission.dft_code, DftCode::Vasp);
        assert_eq!(submission.input_content, Some("ENCUT = 400".to_string()));

        // Verify serialization produces snake_case
        let json = serde_json::to_string(&submission).unwrap();
        assert!(json.contains("\"dft_code\":\"vasp\""));
    }

    #[test]
    fn test_job_submission_crystal() {
        let submission = JobSubmission::new("crystal-calc", DftCode::Crystal);
        assert_eq!(submission.dft_code, DftCode::Crystal);
        assert_eq!(submission.cluster_id, None);
        assert_eq!(submission.structure_path, None);

        // Verify serialization
        let json = serde_json::to_string(&submission).unwrap();
        assert!(json.contains("\"dft_code\":\"crystal\""));
    }

    #[test]
    fn test_job_submission_with_runner_type() {
        let submission =
            JobSubmission::new("test-job", DftCode::Crystal).with_runner_type(RunnerType::Slurm);

        assert_eq!(submission.runner_type, Some(RunnerType::Slurm));

        // Verify serialization includes runner_type as snake_case
        let json = serde_json::to_string(&submission).unwrap();
        assert!(json.contains("\"runner_type\":\"slurm\""));

        // Verify None runner_type is skipped in serialization
        let submission_no_runner = JobSubmission::new("test", DftCode::Vasp);
        let json_no_runner = serde_json::to_string(&submission_no_runner).unwrap();
        assert!(!json_no_runner.contains("runner_type"));
    }

    // ==================== Materials API Tests ====================

    #[test]
    fn test_material_result_deserialize() {
        let json = r#"{
            "material_id": "mp-2815",
            "formula": "MoS2",
            "formula_pretty": "MoS₂",
            "source": "materials_project",
            "properties": {
                "band_gap": 1.23,
                "energy_above_hull": 0.0
            },
            "metadata": {
                "space_group": {"symbol": "P6_3/mmc"}
            }
        }"#;
        let result: MaterialResult = serde_json::from_str(json).unwrap();
        assert_eq!(result.material_id, "mp-2815");
        assert_eq!(result.display_formula(), "MoS₂");
        assert_eq!(result.band_gap_display(), "1.23");
        assert_eq!(result.space_group(), "P6_3/mmc");
        assert!(result.is_stable());
        assert_eq!(result.stability_display(), "Stable");
    }

    #[test]
    fn test_material_result_unstable() {
        let json = r#"{
            "material_id": "mp-1234",
            "formula": "LiCoO2",
            "properties": {
                "energy_above_hull": 0.15
            },
            "metadata": {}
        }"#;
        let result: MaterialResult = serde_json::from_str(json).unwrap();
        assert!(!result.is_stable());
        assert_eq!(result.stability_display(), "+0.150 eV");
    }

    #[test]
    fn test_material_result_minimal() {
        let json = r#"{
            "material_id": "mp-999",
            "properties": {},
            "metadata": {}
        }"#;
        let result: MaterialResult = serde_json::from_str(json).unwrap();
        assert_eq!(result.material_id, "mp-999");
        assert_eq!(result.display_formula(), "-");
        assert_eq!(result.band_gap_display(), "-");
        assert_eq!(result.space_group(), "-");
        assert!(!result.is_stable());
    }

    #[test]
    fn test_d12_generation_config_default() {
        let config = D12GenerationConfig::default();
        assert_eq!(config.functional, "PBE");
        assert_eq!(config.basis_set, "POB-TZVP-REV2");
        assert_eq!(config.shrink, (8, 8));
        assert!(!config.optimize);
    }

    #[test]
    fn test_api_response_success() {
        let json = r#"{"ok": true, "data": ["item1", "item2"]}"#;
        let response: ApiResponse<Vec<String>> = serde_json::from_str(json).unwrap();
        assert!(response.ok);
        let data = response.into_result().unwrap();
        assert_eq!(data, vec!["item1", "item2"]);
    }

    #[test]
    fn test_api_response_error() {
        let json =
            r#"{"ok": false, "error": {"code": "NOT_FOUND", "message": "Material not found"}}"#;
        let response: ApiResponse<String> = serde_json::from_str(json).unwrap();
        assert!(!response.ok);
        let err = response.into_result().unwrap_err();
        assert!(err.contains("NOT_FOUND"));
        assert!(err.contains("Material not found"));
    }

    #[test]
    fn test_vasp_input_files_serialize() {
        let files = VaspInputFiles {
            poscar: "Si\n1.0\n5.0 0.0 0.0\n".to_string(),
            incar: "ENCUT = 520\n".to_string(),
            kpoints: "Automatic\n0\n".to_string(),
            potcar_config: "Elements: Si".to_string(),
        };

        let json = serde_json::to_value(&files).unwrap();
        assert_eq!(json["poscar"], "Si\n1.0\n5.0 0.0 0.0\n");
        assert_eq!(json["incar"], "ENCUT = 520\n");
        assert_eq!(json["kpoints"], "Automatic\n0\n");
        assert_eq!(json["potcar_config"], "Elements: Si");
    }

    #[test]
    fn test_vasp_input_files_deserialize() {
        let json = r#"{
            "poscar": "Si\n1.0\n",
            "incar": "ENCUT = 520\n",
            "kpoints": "Automatic\n0\n",
            "potcar_config": "Elements: Si"
        }"#;
        let files: VaspInputFiles = serde_json::from_str(json).unwrap();
        assert_eq!(files.poscar, "Si\n1.0\n");
        assert_eq!(files.incar, "ENCUT = 520\n");
        assert_eq!(files.kpoints, "Automatic\n0\n");
        assert_eq!(files.potcar_config, "Elements: Si");
    }

    #[test]
    fn test_job_submission_with_vasp_files() {
        let vasp_files = VaspInputFiles {
            poscar: "Si structure".to_string(),
            incar: "ENCUT = 520".to_string(),
            kpoints: "3 3 3".to_string(),
            potcar_config: "Elements: Si".to_string(),
        };

        let params = serde_json::to_value(&vasp_files).unwrap();
        let submission = JobSubmission::new("vasp-test", DftCode::Vasp).with_parameters(params);

        assert_eq!(submission.dft_code, DftCode::Vasp);
        assert_eq!(
            submission.parameters["poscar"],
            serde_json::Value::String("Si structure".to_string())
        );
        assert_eq!(
            submission.parameters["incar"],
            serde_json::Value::String("ENCUT = 520".to_string())
        );
    }

    // ==================== ClusterStatus Tests ====================

    #[test]
    fn test_cluster_status_deserialize() {
        assert_eq!(
            serde_json::from_str::<ClusterStatus>("\"active\"").unwrap(),
            ClusterStatus::Active
        );
        assert_eq!(
            serde_json::from_str::<ClusterStatus>("\"offline\"").unwrap(),
            ClusterStatus::Offline
        );
        assert_eq!(
            serde_json::from_str::<ClusterStatus>("\"testing\"").unwrap(),
            ClusterStatus::Testing
        );
    }

    #[test]
    fn test_cluster_status_serialize() {
        assert_eq!(
            serde_json::to_string(&ClusterStatus::Active).unwrap(),
            "\"active\""
        );
        assert_eq!(
            serde_json::to_string(&ClusterStatus::Offline).unwrap(),
            "\"offline\""
        );
        assert_eq!(
            serde_json::to_string(&ClusterStatus::Testing).unwrap(),
            "\"testing\""
        );
    }

    #[test]
    fn test_cluster_status_unknown_fallback() {
        // Unknown status values should deserialize to Unknown variant
        let status: ClusterStatus = serde_json::from_str("\"maintenance\"").unwrap();
        assert_eq!(status, ClusterStatus::Unknown);

        let status: ClusterStatus = serde_json::from_str("\"some_new_status\"").unwrap();
        assert_eq!(status, ClusterStatus::Unknown);
    }

    #[test]
    fn test_cluster_status_display() {
        assert_eq!(ClusterStatus::Active.as_str(), "Active");
        assert_eq!(ClusterStatus::Offline.as_str(), "Offline");
        assert_eq!(ClusterStatus::Testing.as_str(), "Testing");
        assert_eq!(ClusterStatus::Unknown.as_str(), "Unknown");
    }

    #[test]
    fn test_cluster_status_is_available() {
        assert!(ClusterStatus::Active.is_available());
        assert!(!ClusterStatus::Offline.is_available());
        assert!(!ClusterStatus::Testing.is_available());
        assert!(!ClusterStatus::Unknown.is_available());
    }

    #[test]
    fn test_cluster_status_default() {
        assert_eq!(ClusterStatus::default(), ClusterStatus::Active);
    }

    #[test]
    fn test_cluster_status_color() {
        use ratatui::style::Color;
        assert_eq!(ClusterStatus::Active.color(), Color::Green);
        assert_eq!(ClusterStatus::Offline.color(), Color::Red);
        assert_eq!(ClusterStatus::Testing.color(), Color::Yellow);
        assert_eq!(ClusterStatus::Unknown.color(), Color::Gray);
    }
}
