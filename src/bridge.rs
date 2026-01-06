//! Python bridge module using PyO3.
//!
//! This module handles all communication with the Python backend.
//! It uses JSON strings over FFI for simplicity and robustness.
//!
//! The async bridge (BridgeHandle) spawns a dedicated worker thread that
//! owns the Py<PyAny>, allowing the main UI thread to remain responsive
//! at 60fps while Python operations execute in the background.

use std::sync::mpsc::{self, Receiver, SyncSender, TrySendError};
use std::thread;

use anyhow::{Context, Result};
use pyo3::prelude::*;
use pyo3::types::PyAnyMethods;

use crate::models::{
    ApiResponse, ClusterConfig, ClusterConnectionResult, JobDetails, JobStatus, JobSubmission,
    MaterialResult, SlurmCancelResult, SlurmQueueEntry, WorkflowAvailability,
};

// =============================================================================
// Service Trait for Dependency Injection
// =============================================================================

/// Trait for Python bridge operations.
///
/// This trait abstracts the Python bridge to enable:
/// - Dependency injection for testing with mock implementations
/// - Separation of interface from implementation
/// - Easier testing without requiring a Python runtime
pub trait BridgeService {
    /// Send a request to fetch jobs (non-blocking).
    fn request_fetch_jobs(&self, request_id: usize) -> Result<()>;

    /// Send a request to fetch job details (non-blocking).
    fn request_fetch_job_details(&self, pk: i32, request_id: usize) -> Result<()>;

    /// Send a request to submit a job (non-blocking).
    fn request_submit_job(&self, submission: &JobSubmission, request_id: usize) -> Result<()>;

    /// Send a request to cancel a job (non-blocking).
    fn request_cancel_job(&self, pk: i32, request_id: usize) -> Result<()>;

    /// Send a request to fetch job log (non-blocking).
    fn request_fetch_job_log(&self, pk: i32, tail_lines: i32, request_id: usize) -> Result<()>;

    /// Send a request to search materials (non-blocking).
    fn request_search_materials(
        &self,
        formula: &str,
        limit: usize,
        request_id: usize,
    ) -> Result<()>;

    /// Send a request to generate a .d12 file (non-blocking).
    fn request_generate_d12(&self, mp_id: &str, config_json: &str, request_id: usize)
        -> Result<()>;

    /// Send a request to fetch SLURM queue (non-blocking).
    fn request_fetch_slurm_queue(&self, cluster_id: i32, request_id: usize) -> Result<()>;

    /// Send a request to cancel a SLURM job (non-blocking).
    fn request_cancel_slurm_job(
        &self,
        cluster_id: i32,
        slurm_job_id: &str,
        request_id: usize,
    ) -> Result<()>;

    /// Send a request to adopt a SLURM job (non-blocking).
    fn request_adopt_slurm_job(
        &self,
        cluster_id: i32,
        slurm_job_id: &str,
        request_id: usize,
    ) -> Result<()>;

    /// Send a request to sync remote job status (non-blocking).
    fn request_sync_remote_jobs(&self, request_id: usize) -> Result<()>;

    /// Send a request to fetch templates (non-blocking).
    fn request_fetch_templates(&self, request_id: usize) -> Result<()>;

    /// Send a request to render a template (non-blocking).
    fn request_render_template(
        &self,
        template_name: &str,
        params_json: &str,
        request_id: usize,
    ) -> Result<()>;

    // Cluster management operations
    /// Send a request to fetch all clusters (non-blocking).
    fn request_fetch_clusters(&self, request_id: usize) -> Result<()>;

    /// Send a request to create a new cluster (non-blocking).
    fn request_create_cluster(&self, config: &ClusterConfig, request_id: usize) -> Result<()>;

    /// Send a request to update a cluster (non-blocking).
    fn request_update_cluster(
        &self,
        cluster_id: i32,
        config: &ClusterConfig,
        request_id: usize,
    ) -> Result<()>;

    /// Send a request to delete a cluster (non-blocking).
    fn request_delete_cluster(&self, cluster_id: i32, request_id: usize) -> Result<()>;

    /// Send a request to test cluster connection (non-blocking).
    fn request_test_cluster_connection(&self, cluster_id: i32, request_id: usize) -> Result<()>;

    // Workflow operations
    /// Send a request to check workflow availability (non-blocking).
    fn request_check_workflows_available(&self, request_id: usize) -> Result<()>;

    /// Send a request to create a convergence study (non-blocking).
    fn request_create_convergence_study(&self, config_json: &str, request_id: usize) -> Result<()>;

    /// Send a request to create a band structure workflow (non-blocking).
    fn request_create_band_structure_workflow(
        &self,
        config_json: &str,
        request_id: usize,
    ) -> Result<()>;

    /// Send a request to create a phonon workflow (non-blocking).
    fn request_create_phonon_workflow(&self, config_json: &str, request_id: usize) -> Result<()>;

    /// Send a request to create an EOS workflow (non-blocking).
    fn request_create_eos_workflow(&self, config_json: &str, request_id: usize) -> Result<()>;

    /// Send a request to launch AiiDA geometry optimization (non-blocking).
    fn request_launch_aiida_geopt(&self, config_json: &str, request_id: usize) -> Result<()>;

    /// Poll for a response (non-blocking).
    fn poll_response(&self) -> Option<BridgeResponse>;
}

/// Initialize the Python backend and return the controller object.
///
/// Searches for database in order:
///
/// 1. CRYSTAL_TUI_DB environment variable
/// 2. ~/.local/share/crystal-tui/jobs.db
/// 3. ./tui/jobs.db (development)
///
/// Falls back to demo mode if no database found.
pub fn init_python_backend() -> Result<Py<PyAny>> {
    Python::attach(|py| {
        // Import the crystalmath.api module
        let api_module = py
            .import("crystalmath.api")
            .context("Failed to import crystalmath.api - is the Python package installed?")?;

        // Try to find a database path
        let db_path = find_database_path();

        // Call create_controller() factory function
        let controller = api_module
            .call_method1(
                "create_controller",
                (
                    "default", // profile_name
                    false,     // use_aiida
                    db_path,   // db_path (Some or None)
                ),
            )
            .context("Failed to create CrystalController")?;

        Ok(controller.into())
    })
}

/// Find the database path from environment or default locations.
fn find_database_path() -> Option<String> {
    use std::path::PathBuf;

    // 1. Environment variable (highest priority)
    if let Ok(path) = std::env::var("CRYSTAL_TUI_DB") {
        let p = PathBuf::from(&path);
        if p.exists() {
            tracing::info!("Using database from CRYSTAL_TUI_DB: {}", path);
            return Some(path);
        }
        // If specified but doesn't exist, create it
        if let Some(parent) = p.parent() {
            if parent.exists() || std::fs::create_dir_all(parent).is_ok() {
                tracing::info!("Creating database at CRYSTAL_TUI_DB: {}", path);
                return Some(path);
            }
        }
    }

    // 2. Python Textual TUI database (.crystal_tui.db) - SHARED DATABASE
    // Check project root first (found via Cargo.toml), then CWD
    let textual_db_name = ".crystal_tui.db";

    // Check project root (where Cargo.toml is)
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent();
        for _ in 0..5 {
            if let Some(d) = dir {
                if d.join("Cargo.toml").exists() {
                    // Found project root - check for .crystal_tui.db
                    let project_db = d.join(textual_db_name);
                    if project_db.exists() {
                        tracing::info!(
                            "Using shared Textual TUI database: {}",
                            project_db.display()
                        );
                        return Some(project_db.to_string_lossy().to_string());
                    }
                    // Also check tui/ subdirectory
                    let tui_db = d.join("tui").join(textual_db_name);
                    if tui_db.exists() {
                        tracing::info!("Using shared Textual TUI database: {}", tui_db.display());
                        return Some(tui_db.to_string_lossy().to_string());
                    }
                    break;
                }
                dir = d.parent();
            } else {
                break;
            }
        }
    }

    // Check CWD for .crystal_tui.db
    if let Ok(cwd) = std::env::current_dir() {
        let cwd_db = cwd.join(textual_db_name);
        if cwd_db.exists() {
            tracing::info!("Using shared Textual TUI database: {}", cwd_db.display());
            return Some(cwd_db.to_string_lossy().to_string());
        }
        // Check tui/ subdirectory of CWD
        let tui_db = cwd.join("tui").join(textual_db_name);
        if tui_db.exists() {
            tracing::info!("Using shared Textual TUI database: {}", tui_db.display());
            return Some(tui_db.to_string_lossy().to_string());
        }
    }

    // 3. XDG/Linux location (~/.local/share/crystal-tui/)
    if let Some(home) = dirs::home_dir() {
        let xdg_db = home.join(".local/share/crystal-tui/jobs.db");
        if xdg_db.exists() {
            tracing::info!("Using database: {}", xdg_db.display());
            return Some(xdg_db.to_string_lossy().to_string());
        }
    }

    // 4. Platform data directory (macOS: ~/Library/Application Support/)
    if let Some(data_dir) = dirs::data_dir() {
        let platform_db = data_dir.join("crystal-tui").join("jobs.db");
        if platform_db.exists() {
            tracing::info!("Using database: {}", platform_db.display());
            return Some(platform_db.to_string_lossy().to_string());
        }
        // Create if doesn't exist (only for platform location)
        if let Some(parent) = platform_db.parent() {
            if std::fs::create_dir_all(parent).is_ok() {
                tracing::info!("Creating database: {}", platform_db.display());
                return Some(platform_db.to_string_lossy().to_string());
            }
        }
    }

    // 5. Legacy development location
    if let Ok(cwd) = std::env::current_dir() {
        let dev_db = cwd.join("tui").join("jobs.db");
        if dev_db.exists() {
            tracing::info!("Using development database: {}", dev_db.display());
            return Some(dev_db.to_string_lossy().to_string());
        }
    }

    tracing::warn!("No database found - running in demo mode");
    tracing::warn!("Set CRYSTAL_TUI_DB=/path/to/jobs.db or run the Textual TUI first to create .crystal_tui.db");
    None
}

/// Fetch the list of jobs from the Python backend.
pub fn fetch_jobs(py_controller: &Py<PyAny>) -> Result<Vec<JobStatus>> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let bridge = py
            .import("crystalmath.rust_bridge")
            .context("Failed to import crystalmath.rust_bridge")?;

        // Call rust_bridge.get_jobs_json(controller)
        let json_str: String = bridge
            .call_method1("get_jobs_json", (controller,))
            .context("Failed to call rust_bridge.get_jobs_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Deserialize in Rust
        let jobs: Vec<JobStatus> =
            serde_json::from_str(&json_str).context("Failed to parse jobs JSON")?;

        Ok(jobs)
    })
}

/// Fetch detailed job information.
pub fn fetch_job_details(py_controller: &Py<PyAny>, pk: i32) -> Result<Option<JobDetails>> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let bridge = py
            .import("crystalmath.rust_bridge")
            .context("Failed to import crystalmath.rust_bridge")?;

        // Call rust_bridge.get_job_details_json(controller, pk)
        let json_str: String = bridge
            .call_method1("get_job_details_json", (controller, pk))
            .context("Failed to call rust_bridge.get_job_details_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Parse structured API response
        let response: ApiResponse<JobDetails> =
            serde_json::from_str(&json_str).context("Failed to parse job details response")?;

        // Handle NOT_FOUND as None, other errors as Error
        match response.into_result() {
            Ok(details) => Ok(Some(details)),
            Err(msg) if msg.contains("NOT_FOUND") => Ok(None),
            Err(msg) => Err(anyhow::anyhow!("Job details error: {}", msg)),
        }
    })
}

/// Submit a new job to the Python backend.
#[allow(dead_code)] // Planned for job submission feature
pub fn submit_job(py_controller: &Py<PyAny>, submission: &JobSubmission) -> Result<i32> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        // Serialize submission to JSON
        let json_payload = serde_json::to_string(submission).context("Failed to serialize job")?;

        // Call submit_job_json(payload)
        let pk: i32 = controller
            .call_method1("submit_job_json", (json_payload,))
            .context("Failed to call submit_job_json")?
            .extract()
            .context("Failed to extract job pk")?;

        Ok(pk)
    })
}

/// Cancel a running job.
pub fn cancel_job(py_controller: &Py<PyAny>, pk: i32) -> Result<bool> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let success: bool = controller
            .call_method1("cancel_job", (pk,))
            .context("Failed to call cancel_job")?
            .extract()
            .context("Failed to extract result")?;

        Ok(success)
    })
}

/// Get job logs.
pub fn fetch_job_log(py_controller: &Py<PyAny>, pk: i32, tail_lines: i32) -> Result<JobLog> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let bridge = py
            .import("crystalmath.rust_bridge")
            .context("Failed to import crystalmath.rust_bridge")?;

        let json_str: String = bridge
            .call_method1("get_job_log_json", (controller, pk, tail_lines))
            .context("Failed to call rust_bridge.get_job_log_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let log: JobLog = serde_json::from_str(&json_str).context("Failed to parse log JSON")?;

        Ok(log)
    })
}

/// Job log output.
#[derive(Debug, serde::Deserialize)]
pub struct JobLog {
    pub stdout: Vec<String>,
    #[allow(dead_code)] // Populated by Python but not yet displayed in UI
    pub stderr: Vec<String>,
}

// =============================================================================
// Async Bridge Types
// =============================================================================

/// Request types for the Python bridge worker thread.
///
/// All requests include a `request_id` to correlate with responses and prevent
/// race conditions where a stale response clears the pending state for a newer request.
#[derive(Debug)]
#[allow(dead_code)] // Variants used by worker thread, some planned for future
pub enum BridgeRequest {
    /// Graceful shutdown signal - worker exits after receiving this.
    Shutdown,
    FetchJobs {
        request_id: usize,
    },
    FetchJobDetails {
        pk: i32,
        request_id: usize,
    },
    SubmitJob {
        submission_json: String,
        request_id: usize,
    },
    CancelJob {
        pk: i32,
        request_id: usize,
    },
    FetchJobLog {
        pk: i32,
        tail_lines: i32,
        request_id: usize,
    },
    // Materials Project API requests
    SearchMaterials {
        formula: String,
        limit: usize,
        request_id: usize,
    },
    GenerateD12 {
        mp_id: String,
        config_json: String,
        request_id: usize,
    },
    // SLURM queue requests
    FetchSlurmQueue {
        cluster_id: i32,
        request_id: usize,
    },
    CancelSlurmJob {
        cluster_id: i32,
        slurm_job_id: String,
        request_id: usize,
    },
    AdoptSlurmJob {
        cluster_id: i32,
        slurm_job_id: String,
        request_id: usize,
    },
    SyncRemoteJobs {
        request_id: usize,
    },
    // Template requests
    FetchTemplates {
        request_id: usize,
    },
    RenderTemplate {
        template_name: String,
        params_json: String,
        request_id: usize,
    },
    // Cluster management requests
    FetchClusters {
        request_id: usize,
    },
    FetchCluster {
        cluster_id: i32,
        request_id: usize,
    },
    CreateCluster {
        config_json: String,
        request_id: usize,
    },
    UpdateCluster {
        cluster_id: i32,
        config_json: String,
        request_id: usize,
    },
    DeleteCluster {
        cluster_id: i32,
        request_id: usize,
    },
    TestClusterConnection {
        cluster_id: i32,
        request_id: usize,
    },
    // Workflow requests
    CheckWorkflowsAvailable {
        request_id: usize,
    },
    CreateConvergenceStudy {
        config_json: String,
        request_id: usize,
    },
    CreateBandStructureWorkflow {
        config_json: String,
        request_id: usize,
    },
    CreatePhononWorkflow {
        config_json: String,
        request_id: usize,
    },
    CreateEosWorkflow {
        config_json: String,
        request_id: usize,
    },
    LaunchAiidaGeopt {
        config_json: String,
        request_id: usize,
    },
}

/// Response types from the Python bridge worker thread.
///
/// All responses include a `request_id` that matches the corresponding request,
/// enabling the caller to detect and discard stale responses.
#[derive(Debug)]
#[allow(clippy::large_enum_variant)]
pub enum BridgeResponse {
    Jobs {
        request_id: usize,
        result: Result<Vec<JobStatus>>,
    },
    JobDetails {
        request_id: usize,
        result: Result<Option<JobDetails>>,
    },
    JobSubmitted {
        request_id: usize,
        result: Result<i32>,
    },
    JobCancelled {
        request_id: usize,
        result: Result<bool>,
    },
    JobLog {
        request_id: usize,
        result: Result<JobLog>,
    },
    // Materials Project API responses
    MaterialsFound {
        request_id: usize,
        result: Result<Vec<MaterialResult>>,
    },
    D12Generated {
        request_id: usize,
        result: Result<String>,
    },
    // SLURM queue responses
    SlurmQueue {
        request_id: usize,
        result: Result<Vec<SlurmQueueEntry>>,
    },
    SlurmJobCancelled {
        request_id: usize,
        result: Result<SlurmCancelResult>,
    },
    SlurmJobAdopted {
        request_id: usize,
        result: Result<i32>, // Returns PK of new job
    },
    // Template responses
    Templates {
        request_id: usize,
        result: Result<Vec<crate::models::Template>>,
    },
    TemplateRendered {
        request_id: usize,
        result: Result<String>,
    },
    // Cluster management responses
    Clusters {
        request_id: usize,
        result: Result<Vec<ClusterConfig>>,
    },
    Cluster {
        request_id: usize,
        result: Result<Option<ClusterConfig>>,
    },
    ClusterCreated {
        request_id: usize,
        result: Result<ClusterConfig>,
    },
    ClusterUpdated {
        request_id: usize,
        result: Result<ClusterConfig>,
    },
    ClusterDeleted {
        request_id: usize,
        result: Result<bool>,
    },
    ClusterConnectionTested {
        request_id: usize,
        result: Result<ClusterConnectionResult>,
    },
    // Workflow responses
    WorkflowsAvailable {
        request_id: usize,
        result: Result<WorkflowAvailability>,
    },
    WorkflowCreated {
        request_id: usize,
        /// JSON string of the created workflow
        result: Result<String>,
    },
}

/// Kind of pending bridge request (for UI feedback).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[allow(dead_code)] // Some variants planned for future features
pub enum BridgeRequestKind {
    FetchJobs,
    FetchJobDetails,
    SubmitJob,
    CancelJob,
    FetchJobLog,
    AdoptSlurmJob,
    // Materials Project API
    SearchMaterials,
    GenerateD12,
    SyncRemoteJobs,
    FetchTemplates,
    RenderTemplate,
    // Workflows
    CheckWorkflowsAvailable,
    CreateWorkflow,
}

/// Maximum number of pending requests/responses before backpressure.
/// This prevents unbounded memory growth if requests pile up faster than
/// the Python worker can process them.
const CHANNEL_BOUND: usize = 64;

/// Handle to the Python bridge worker thread.
///
/// This provides a non-blocking interface to Python operations.
/// Requests are sent via a bounded channel to a dedicated worker thread,
/// and responses are polled from another bounded channel.
///
/// The bounded channels provide backpressure to prevent unbounded memory
/// growth if the UI sends requests faster than Python can process them.
///
/// When dropped, sends a Shutdown request and waits for the worker to exit.
pub struct BridgeHandle {
    request_tx: SyncSender<BridgeRequest>,
    response_rx: Receiver<BridgeResponse>,
    /// Handle to the worker thread for graceful shutdown.
    worker_handle: Option<thread::JoinHandle<()>>,
}

#[allow(dead_code)] // Inherent methods kept for direct use; trait methods used via Box<dyn>
impl BridgeHandle {
    /// Create a new bridge handle by spawning a worker thread.
    ///
    /// The worker thread owns the Py<PyAny> and processes requests
    /// via channels, keeping the GIL off the main UI thread.
    pub fn spawn(py_controller: Py<PyAny>) -> Result<Self> {
        let (request_tx, request_rx) = mpsc::sync_channel::<BridgeRequest>(CHANNEL_BOUND);
        let (response_tx, response_rx) = mpsc::sync_channel::<BridgeResponse>(CHANNEL_BOUND);

        let worker_handle = thread::spawn(move || {
            bridge_worker_loop(py_controller, request_rx, response_tx);
        });

        Ok(Self {
            request_tx,
            response_rx,
            worker_handle: Some(worker_handle),
        })
    }

    /// Send a request to the bridge worker using try_send (non-blocking).
    ///
    /// Uses try_send to avoid blocking the UI thread if the channel is full.
    /// Returns an error if the channel is full (backend busy) or disconnected.
    fn try_send_request(&self, request: BridgeRequest) -> Result<()> {
        match self.request_tx.try_send(request) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => {
                Err(anyhow::anyhow!("Backend busy - try again in a moment"))
            }
            Err(TrySendError::Disconnected(_)) => {
                Err(anyhow::anyhow!("Bridge worker disconnected"))
            }
        }
    }

    /// Send a request to fetch jobs (non-blocking).
    ///
    /// The `request_id` is returned in the response to detect stale responses.
    pub fn request_fetch_jobs(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchJobs { request_id })
    }

    /// Send a request to fetch job details (non-blocking).
    ///
    /// The `request_id` is returned in the response to detect stale responses.
    pub fn request_fetch_job_details(&self, pk: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchJobDetails { pk, request_id })
    }

    /// Send a request to submit a job (non-blocking).
    ///
    /// The `request_id` is returned in the response to detect stale responses.
    #[allow(dead_code)] // Planned for job submission feature
    pub fn request_submit_job(&self, submission: &JobSubmission, request_id: usize) -> Result<()> {
        let json = serde_json::to_string(submission)?;
        self.try_send_request(BridgeRequest::SubmitJob {
            submission_json: json,
            request_id,
        })
    }

    /// Send a request to cancel a job (non-blocking).
    ///
    /// The `request_id` is returned in the response to detect stale responses.
    #[allow(dead_code)] // Planned for job cancellation feature
    pub fn request_cancel_job(&self, pk: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::CancelJob { pk, request_id })
    }

    /// Send a request to fetch job log (non-blocking).
    ///
    /// The `request_id` is returned in the response to detect stale responses.
    #[allow(dead_code)] // Used by log tab feature
    pub fn request_fetch_job_log(&self, pk: i32, tail_lines: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchJobLog {
            pk,
            tail_lines,
            request_id,
        })
    }

    /// Send a request to search materials (non-blocking).
    ///
    /// The request_id is used to correlate responses and handle cancellation.
    /// If the user dismisses the modal before a response arrives, the UI
    /// should check the request_id and ignore stale responses.
    pub fn request_search_materials(
        &self,
        formula: &str,
        limit: usize,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::SearchMaterials {
            formula: formula.to_string(),
            limit,
            request_id,
        })
    }

    /// Send a request to generate a .d12 file (non-blocking).
    ///
    /// The config_json should match D12GenerationConfig serialization.
    pub fn request_generate_d12(
        &self,
        mp_id: &str,
        config_json: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::GenerateD12 {
            mp_id: mp_id.to_string(),
            config_json: config_json.to_string(),
            request_id,
        })
    }

    /// Send a request to fetch SLURM queue status (non-blocking).
    ///
    /// Queries the SLURM controller on the specified cluster.
    pub fn request_fetch_slurm_queue(&self, cluster_id: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchSlurmQueue {
            cluster_id,
            request_id,
        })
    }

    /// Send a request to cancel a SLURM job (non-blocking).
    ///
    /// Calls scancel on the specified cluster to cancel the job.
    pub fn request_cancel_slurm_job(
        &self,
        cluster_id: i32,
        slurm_job_id: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::CancelSlurmJob {
            cluster_id,
            slurm_job_id: slurm_job_id.to_string(),
            request_id,
        })
    }

    /// Send a request to adopt a SLURM job (non-blocking).
    ///
    /// Creates a local tracking record for an existing remote job.
    pub fn request_adopt_slurm_job(
        &self,
        cluster_id: i32,
        slurm_job_id: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::AdoptSlurmJob {
            cluster_id,
            slurm_job_id: slurm_job_id.to_string(),
            request_id,
        })
    }

    /// Send a request to sync remote job status (non-blocking).
    ///
    /// Checks active remote jobs against squeue/sacct and updates DB.
    pub fn request_sync_remote_jobs(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::SyncRemoteJobs { request_id })
    }

    fn request_fetch_templates(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchTemplates { request_id })
    }

    fn request_render_template(
        &self,
        template_name: &str,
        params_json: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::RenderTemplate {
            template_name: template_name.to_string(),
            params_json: params_json.to_string(),
            request_id,
        })
    }

    // =========================================================================
    // Cluster Management Methods
    // =========================================================================

    /// Send a request to fetch all clusters (non-blocking).
    pub fn request_fetch_clusters(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchClusters { request_id })
    }

    /// Send a request to create a new cluster (non-blocking).
    pub fn request_create_cluster(&self, config: &ClusterConfig, request_id: usize) -> Result<()> {
        let json = serde_json::to_string(config)?;
        self.try_send_request(BridgeRequest::CreateCluster {
            config_json: json,
            request_id,
        })
    }

    /// Send a request to update a cluster (non-blocking).
    pub fn request_update_cluster(
        &self,
        cluster_id: i32,
        config: &ClusterConfig,
        request_id: usize,
    ) -> Result<()> {
        let json = serde_json::to_string(config)?;
        self.try_send_request(BridgeRequest::UpdateCluster {
            cluster_id,
            config_json: json,
            request_id,
        })
    }

    /// Send a request to delete a cluster (non-blocking).
    pub fn request_delete_cluster(&self, cluster_id: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::DeleteCluster {
            cluster_id,
            request_id,
        })
    }

    /// Send a request to test cluster connection (non-blocking).
    pub fn request_test_cluster_connection(
        &self,
        cluster_id: i32,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::TestClusterConnection {
            cluster_id,
            request_id,
        })
    }

    /// Poll for a response (non-blocking).
    ///
    /// Returns `Some(response)` if a response is available,
    /// `None` if no response is ready yet.
    pub fn poll_response(&self) -> Option<BridgeResponse> {
        self.response_rx.try_recv().ok()
    }
}

impl Drop for BridgeHandle {
    fn drop(&mut self) {
        // Send shutdown signal to the worker thread.
        // Ignore errors - the worker may have already exited.
        let _ = self.request_tx.send(BridgeRequest::Shutdown);

        // Brief wait for quick shutdown, then detach if worker is slow.
        // We don't want to block the main thread for a long timeout during Drop.
        // Python interpreter shutdown can hang due to GIL/C-extension deadlocks.
        if let Some(handle) = self.worker_handle.take() {
            // Quick check iterations - try a few times with short sleeps
            const QUICK_CHECK_INTERVAL: std::time::Duration = std::time::Duration::from_millis(10);
            const MAX_QUICK_CHECKS: u32 = 10; // 100ms total for quick shutdown

            for _ in 0..MAX_QUICK_CHECKS {
                if handle.is_finished() {
                    // Worker finished quickly - join to get the result
                    if let Err(e) = handle.join() {
                        tracing::warn!("Bridge worker thread panicked during shutdown: {:?}", e);
                    } else {
                        tracing::debug!("Bridge worker thread shut down gracefully");
                    }
                    return;
                }
                std::thread::sleep(QUICK_CHECK_INTERVAL);
            }

            // Worker didn't finish quickly - detach and let it continue in background.
            // The thread will clean up when Python finishes processing or when
            // the process exits.
            tracing::debug!(
                "Bridge worker still running after {}ms - detaching for background cleanup",
                QUICK_CHECK_INTERVAL.as_millis() * MAX_QUICK_CHECKS as u128
            );
            // Dropping the handle detaches the thread (it continues running independently)
        }
    }
}

/// Implementation of `BridgeService` for `BridgeHandle`.
///
/// This allows `BridgeHandle` to be used anywhere a `BridgeService` is expected,
/// enabling dependency injection and mock implementations for testing.
impl BridgeService for BridgeHandle {
    fn request_fetch_jobs(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchJobs { request_id })
    }

    fn request_fetch_job_details(&self, pk: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchJobDetails { pk, request_id })
    }

    fn request_submit_job(&self, submission: &JobSubmission, request_id: usize) -> Result<()> {
        let json = serde_json::to_string(submission)?;
        self.try_send_request(BridgeRequest::SubmitJob {
            submission_json: json,
            request_id,
        })
    }

    fn request_cancel_job(&self, pk: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::CancelJob { pk, request_id })
    }

    fn request_fetch_job_log(&self, pk: i32, tail_lines: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchJobLog {
            pk,
            tail_lines,
            request_id,
        })
    }

    fn request_search_materials(
        &self,
        formula: &str,
        limit: usize,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::SearchMaterials {
            formula: formula.to_string(),
            limit,
            request_id,
        })
    }

    fn request_generate_d12(
        &self,
        mp_id: &str,
        config_json: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::GenerateD12 {
            mp_id: mp_id.to_string(),
            config_json: config_json.to_string(),
            request_id,
        })
    }

    fn request_fetch_slurm_queue(&self, cluster_id: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchSlurmQueue {
            cluster_id,
            request_id,
        })
    }

    fn request_cancel_slurm_job(
        &self,
        cluster_id: i32,
        slurm_job_id: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::CancelSlurmJob {
            cluster_id,
            slurm_job_id: slurm_job_id.to_string(),
            request_id,
        })
    }

    fn request_adopt_slurm_job(
        &self,
        cluster_id: i32,
        slurm_job_id: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::AdoptSlurmJob {
            cluster_id,
            slurm_job_id: slurm_job_id.to_string(),
            request_id,
        })
    }

    fn request_sync_remote_jobs(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::SyncRemoteJobs { request_id })
    }

    fn request_fetch_templates(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchTemplates { request_id })
    }

    fn request_render_template(
        &self,
        template_name: &str,
        params_json: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::RenderTemplate {
            template_name: template_name.to_string(),
            params_json: params_json.to_string(),
            request_id,
        })
    }

    fn request_fetch_clusters(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::FetchClusters { request_id })
    }

    fn request_create_cluster(&self, config: &ClusterConfig, request_id: usize) -> Result<()> {
        let json = serde_json::to_string(config)?;
        self.try_send_request(BridgeRequest::CreateCluster {
            config_json: json,
            request_id,
        })
    }

    fn request_update_cluster(
        &self,
        cluster_id: i32,
        config: &ClusterConfig,
        request_id: usize,
    ) -> Result<()> {
        let json = serde_json::to_string(config)?;
        self.try_send_request(BridgeRequest::UpdateCluster {
            cluster_id,
            config_json: json,
            request_id,
        })
    }

    fn request_delete_cluster(&self, cluster_id: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::DeleteCluster {
            cluster_id,
            request_id,
        })
    }

    fn request_test_cluster_connection(&self, cluster_id: i32, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::TestClusterConnection {
            cluster_id,
            request_id,
        })
    }

    fn request_check_workflows_available(&self, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::CheckWorkflowsAvailable { request_id })
    }

    fn request_create_convergence_study(&self, config_json: &str, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::CreateConvergenceStudy {
            config_json: config_json.to_string(),
            request_id,
        })
    }

    fn request_create_band_structure_workflow(
        &self,
        config_json: &str,
        request_id: usize,
    ) -> Result<()> {
        self.try_send_request(BridgeRequest::CreateBandStructureWorkflow {
            config_json: config_json.to_string(),
            request_id,
        })
    }

    fn request_create_phonon_workflow(&self, config_json: &str, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::CreatePhononWorkflow {
            config_json: config_json.to_string(),
            request_id,
        })
    }

    fn request_create_eos_workflow(&self, config_json: &str, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::CreateEosWorkflow {
            config_json: config_json.to_string(),
            request_id,
        })
    }

    fn request_launch_aiida_geopt(&self, config_json: &str, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::LaunchAiidaGeopt {
            config_json: config_json.to_string(),
            request_id,
        })
    }

    fn poll_response(&self) -> Option<BridgeResponse> {
        self.response_rx.try_recv().ok()
    }
}

/// Worker loop that processes Python requests.
///
/// This runs on a dedicated thread and owns the Py<PyAny>.
/// It blocks waiting for requests and sends responses back via channel.
///
/// The loop is protected by `catch_unwind` to prevent the worker thread from
/// dying if Python code panics (e.g., during GC traversal or interpreter shutdown).
/// Panics are caught and the worker continues processing subsequent requests.
fn bridge_worker_loop(
    py_controller: Py<PyAny>,
    request_rx: Receiver<BridgeRequest>,
    response_tx: SyncSender<BridgeResponse>,
) {
    while let Ok(request) = request_rx.recv() {
        // Handle shutdown request - exit the loop cleanly.
        if matches!(request, BridgeRequest::Shutdown) {
            tracing::info!("Bridge worker received shutdown signal, exiting");
            break;
        }

        // Wrap request processing in catch_unwind to survive panics.
        // This prevents the worker thread from dying if Python::attach panics
        // (which can happen during interpreter shutdown or GC traversal).
        //
        // We use AssertUnwindSafe because:
        // 1. py_controller is Send (required for Py<T>)
        // 2. We're careful not to observe partially-mutated state after a panic
        // 3. The worst case is we skip one response, which the timeout handles
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            process_bridge_request(&py_controller, request)
        }));

        let response = match result {
            Ok(response) => response,
            Err(panic_info) => {
                // Worker panicked - log and continue processing other requests.
                // Try to extract panic message for debugging.
                let panic_msg = if let Some(s) = panic_info.downcast_ref::<&str>() {
                    (*s).to_string()
                } else if let Some(s) = panic_info.downcast_ref::<String>() {
                    s.clone()
                } else {
                    "Unknown panic in bridge worker".to_string()
                };

                tracing::error!("Bridge worker caught panic: {}", panic_msg);

                // Don't send a response - the main thread's timeout mechanism
                // will clear pending state after BRIDGE_REQUEST_TIMEOUT (30s).
                // This is safer than trying to guess what response type to send.
                continue;
            }
        };

        if response_tx.send(response).is_err() {
            // Main thread disconnected, exit worker
            break;
        }
    }
}

/// Process a single bridge request and return the response.
///
/// Extracted from the worker loop to enable catch_unwind wrapping.
/// Each response includes the `request_id` from the corresponding request.
fn process_bridge_request(py_controller: &Py<PyAny>, request: BridgeRequest) -> BridgeResponse {
    match request {
        BridgeRequest::FetchJobs { request_id } => BridgeResponse::Jobs {
            request_id,
            result: fetch_jobs(py_controller),
        },
        BridgeRequest::FetchJobDetails { pk, request_id } => BridgeResponse::JobDetails {
            request_id,
            result: fetch_job_details(py_controller, pk),
        },
        BridgeRequest::SubmitJob {
            submission_json,
            request_id,
        } => BridgeResponse::JobSubmitted {
            request_id,
            result: submit_job_json(py_controller, &submission_json),
        },
        BridgeRequest::CancelJob { pk, request_id } => BridgeResponse::JobCancelled {
            request_id,
            result: cancel_job(py_controller, pk),
        },
        BridgeRequest::FetchJobLog {
            pk,
            tail_lines,
            request_id,
        } => BridgeResponse::JobLog {
            request_id,
            result: fetch_job_log(py_controller, pk, tail_lines),
        },
        // Materials Project API
        BridgeRequest::SearchMaterials {
            formula,
            limit,
            request_id,
        } => BridgeResponse::MaterialsFound {
            request_id,
            result: search_materials(py_controller, &formula, limit),
        },
        BridgeRequest::GenerateD12 {
            mp_id,
            config_json,
            request_id,
        } => BridgeResponse::D12Generated {
            request_id,
            result: generate_d12(py_controller, &mp_id, &config_json),
        },
        // SLURM queue
        BridgeRequest::FetchSlurmQueue {
            cluster_id,
            request_id,
        } => BridgeResponse::SlurmQueue {
            request_id,
            result: fetch_slurm_queue(py_controller, cluster_id),
        },
        BridgeRequest::CancelSlurmJob {
            cluster_id,
            slurm_job_id,
            request_id,
        } => BridgeResponse::SlurmJobCancelled {
            request_id,
            result: cancel_slurm_job(py_controller, cluster_id, &slurm_job_id),
        },
        BridgeRequest::AdoptSlurmJob {
            cluster_id,
            slurm_job_id,
            request_id,
        } => BridgeResponse::SlurmJobAdopted {
            request_id,
            result: adopt_slurm_job(py_controller, cluster_id, &slurm_job_id),
        },
        BridgeRequest::SyncRemoteJobs { request_id } => BridgeResponse::Jobs {
            request_id,
            result: sync_remote_jobs(py_controller),
        },
        // Templates
        BridgeRequest::FetchTemplates { request_id } => BridgeResponse::Templates {
            request_id,
            result: fetch_templates(py_controller),
        },
        BridgeRequest::RenderTemplate {
            template_name,
            params_json,
            request_id,
        } => BridgeResponse::TemplateRendered {
            request_id,
            result: render_template(py_controller, &template_name, &params_json),
        },
        // Cluster management
        BridgeRequest::FetchClusters { request_id } => BridgeResponse::Clusters {
            request_id,
            result: fetch_clusters(py_controller),
        },
        BridgeRequest::FetchCluster {
            cluster_id,
            request_id,
        } => BridgeResponse::Cluster {
            request_id,
            result: fetch_cluster(py_controller, cluster_id),
        },
        BridgeRequest::CreateCluster {
            config_json,
            request_id,
        } => BridgeResponse::ClusterCreated {
            request_id,
            result: create_cluster(py_controller, &config_json),
        },
        BridgeRequest::UpdateCluster {
            cluster_id,
            config_json,
            request_id,
        } => BridgeResponse::ClusterUpdated {
            request_id,
            result: update_cluster(py_controller, cluster_id, &config_json),
        },
        BridgeRequest::DeleteCluster {
            cluster_id,
            request_id,
        } => BridgeResponse::ClusterDeleted {
            request_id,
            result: delete_cluster(py_controller, cluster_id),
        },
        BridgeRequest::TestClusterConnection {
            cluster_id,
            request_id,
        } => BridgeResponse::ClusterConnectionTested {
            request_id,
            result: test_cluster_connection(py_controller, cluster_id),
        },
        // Workflow requests
        BridgeRequest::CheckWorkflowsAvailable { request_id } => {
            BridgeResponse::WorkflowsAvailable {
                request_id,
                result: check_workflows_available(py_controller),
            }
        }
        BridgeRequest::CreateConvergenceStudy {
            config_json,
            request_id,
        } => BridgeResponse::WorkflowCreated {
            request_id,
            result: create_convergence_study(py_controller, &config_json),
        },
        BridgeRequest::CreateBandStructureWorkflow {
            config_json,
            request_id,
        } => BridgeResponse::WorkflowCreated {
            request_id,
            result: create_band_structure_workflow(py_controller, &config_json),
        },
        BridgeRequest::CreatePhononWorkflow {
            config_json,
            request_id,
        } => BridgeResponse::WorkflowCreated {
            request_id,
            result: create_phonon_workflow(py_controller, &config_json),
        },
        BridgeRequest::CreateEosWorkflow {
            config_json,
            request_id,
        } => BridgeResponse::WorkflowCreated {
            request_id,
            result: create_eos_workflow(py_controller, &config_json),
        },
        BridgeRequest::LaunchAiidaGeopt {
            config_json,
            request_id,
        } => BridgeResponse::WorkflowCreated {
            request_id,
            result: launch_aiida_geopt(py_controller, &config_json),
        },
        // Shutdown is handled in the worker loop before calling this function.
        BridgeRequest::Shutdown => unreachable!("Shutdown handled in worker loop"),
    }
}

/// Helper for submitting job from JSON string.
///
/// Used by the worker thread to avoid re-serializing the JobSubmission.
fn submit_job_json(py_controller: &Py<PyAny>, json_payload: &str) -> Result<i32> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);
        let pk: i32 = controller
            .call_method1("submit_job_json", (json_payload,))
            .context("Failed to call submit_job_json")?
            .extract()
            .context("Failed to extract job pk")?;
        Ok(pk)
    })
}

// =============================================================================
// Materials Project API Helpers
// =============================================================================

/// Search Materials Project by formula.
///
/// Calls Python's search_materials_json() and parses the response.
fn search_materials(
    py_controller: &Py<PyAny>,
    formula: &str,
    limit: usize,
) -> Result<Vec<MaterialResult>> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("search_materials_json", (formula, limit as i32))
            .context("Failed to call search_materials_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Parse the structured response
        let response: ApiResponse<Vec<MaterialResult>> =
            serde_json::from_str(&json_str).context("Failed to parse materials search response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Generate a CRYSTAL23 .d12 input file from a Materials Project structure.
///
/// Calls Python's generate_d12_json() and returns the file content.
fn generate_d12(py_controller: &Py<PyAny>, mp_id: &str, config_json: &str) -> Result<String> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("generate_d12_json", (mp_id, config_json))
            .context("Failed to call generate_d12_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Parse the structured response
        let response: ApiResponse<String> =
            serde_json::from_str(&json_str).context("Failed to parse D12 generation response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Fetch SLURM queue status from remote cluster.
///
/// Calls Python's get_slurm_queue_json() and returns the queue entries.
fn fetch_slurm_queue(py_controller: &Py<PyAny>, cluster_id: i32) -> Result<Vec<SlurmQueueEntry>> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("get_slurm_queue_json", (cluster_id,))
            .context("Failed to call get_slurm_queue_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Parse the structured response
        let response: ApiResponse<Vec<SlurmQueueEntry>> =
            serde_json::from_str(&json_str).context("Failed to parse SLURM queue response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Cancel a SLURM job on a remote cluster.
///
/// Calls Python's cancel_slurm_job_json() and returns the result.
fn cancel_slurm_job(
    py_controller: &Py<PyAny>,
    cluster_id: i32,
    slurm_job_id: &str,
) -> Result<SlurmCancelResult> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("cancel_slurm_job_json", (cluster_id, slurm_job_id))
            .context("Failed to call cancel_slurm_job_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Parse the structured response
        let response: ApiResponse<SlurmCancelResult> =
            serde_json::from_str(&json_str).context("Failed to parse SLURM cancel response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Adopt a SLURM job.
///
/// Calls Python's adopt_slurm_job_json() and returns the new job PK.
fn adopt_slurm_job(py_controller: &Py<PyAny>, cluster_id: i32, slurm_job_id: &str) -> Result<i32> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("adopt_slurm_job_json", (cluster_id, slurm_job_id))
            .context("Failed to call adopt_slurm_job_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Parse the structured response
        #[derive(serde::Deserialize, Default)]
        struct AdoptResponse {
            pk: i32,
        }
        let response: ApiResponse<AdoptResponse> =
            serde_json::from_str(&json_str).context("Failed to parse adopt response")?;

        Ok(response.into_result().map_err(|e| anyhow::anyhow!(e))?.pk)
    })
}

/// Sync remote job status with SLURM.
///
/// Calls Python's sync_remote_jobs_json() and returns the updated job list.
fn sync_remote_jobs(py_controller: &Py<PyAny>) -> Result<Vec<JobStatus>> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method0("sync_remote_jobs_json")
            .context("Failed to call sync_remote_jobs_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Deserialize in Rust
        let jobs: Vec<JobStatus> =
            serde_json::from_str(&json_str).context("Failed to parse jobs JSON")?;

        Ok(jobs)
    })
}

// =============================================================================
// Cluster Management Helpers
// =============================================================================

/// Fetch all configured clusters.
fn fetch_clusters(py_controller: &Py<PyAny>) -> Result<Vec<ClusterConfig>> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method0("get_clusters_json")
            .context("Failed to call get_clusters_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<Vec<ClusterConfig>> =
            serde_json::from_str(&json_str).context("Failed to parse clusters response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Fetch a single cluster by ID.
fn fetch_cluster(py_controller: &Py<PyAny>, cluster_id: i32) -> Result<Option<ClusterConfig>> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("get_cluster_json", (cluster_id,))
            .context("Failed to call get_cluster_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<Option<ClusterConfig>> =
            serde_json::from_str(&json_str).context("Failed to parse cluster response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Create a new cluster configuration.
fn create_cluster(py_controller: &Py<PyAny>, config_json: &str) -> Result<ClusterConfig> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("create_cluster_json", (config_json,))
            .context("Failed to call create_cluster_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<ClusterConfig> =
            serde_json::from_str(&json_str).context("Failed to parse cluster creation response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Update an existing cluster configuration.
fn update_cluster(
    py_controller: &Py<PyAny>,
    cluster_id: i32,
    config_json: &str,
) -> Result<ClusterConfig> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("update_cluster_json", (cluster_id, config_json))
            .context("Failed to call update_cluster_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<ClusterConfig> =
            serde_json::from_str(&json_str).context("Failed to parse cluster update response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Delete a cluster configuration.
fn delete_cluster(py_controller: &Py<PyAny>, cluster_id: i32) -> Result<bool> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("delete_cluster", (cluster_id,))
            .context("Failed to call delete_cluster")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<bool> =
            serde_json::from_str(&json_str).context("Failed to parse cluster deletion response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Test SSH connection to a cluster.
fn test_cluster_connection(
    py_controller: &Py<PyAny>,
    cluster_id: i32,
) -> Result<ClusterConnectionResult> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("test_cluster_connection_json", (cluster_id,))
            .context("Failed to call test_cluster_connection_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<ClusterConnectionResult> =
            serde_json::from_str(&json_str).context("Failed to parse connection test response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Fetch all available templates.
fn fetch_templates(py_controller: &Py<PyAny>) -> Result<Vec<crate::models::Template>> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method0("list_templates_json")
            .context("Failed to call list_templates_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<Vec<crate::models::Template>> =
            serde_json::from_str(&json_str).context("Failed to parse templates response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Render a template with parameters.
fn render_template(
    py_controller: &Py<PyAny>,
    template_name: &str,
    params_json: &str,
) -> Result<String> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("render_template_json", (template_name, params_json))
            .context("Failed to call render_template_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<String> =
            serde_json::from_str(&json_str).context("Failed to parse template render response")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

// =============================================================================
// Workflow Helpers
// =============================================================================

/// Check if workflow module is available.
fn check_workflows_available(py_controller: &Py<PyAny>) -> Result<WorkflowAvailability> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method0("check_workflows_available_json")
            .context("Failed to call check_workflows_available_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let response: ApiResponse<WorkflowAvailability> =
            serde_json::from_str(&json_str).context("Failed to parse workflow availability")?;

        response.into_result().map_err(|e| anyhow::anyhow!(e))
    })
}

/// Create a convergence study workflow.
fn create_convergence_study(py_controller: &Py<PyAny>, config_json: &str) -> Result<String> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("create_convergence_study_json", (config_json,))
            .context("Failed to call create_convergence_study_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Return raw JSON for workflow state
        Ok(json_str)
    })
}

/// Create a band structure workflow.
fn create_band_structure_workflow(py_controller: &Py<PyAny>, config_json: &str) -> Result<String> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("create_band_structure_workflow_json", (config_json,))
            .context("Failed to call create_band_structure_workflow_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        Ok(json_str)
    })
}

/// Create a phonon workflow.
fn create_phonon_workflow(py_controller: &Py<PyAny>, config_json: &str) -> Result<String> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("create_phonon_workflow_json", (config_json,))
            .context("Failed to call create_phonon_workflow_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        Ok(json_str)
    })
}

/// Create an EOS workflow.
fn create_eos_workflow(py_controller: &Py<PyAny>, config_json: &str) -> Result<String> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("create_eos_workflow_json", (config_json,))
            .context("Failed to call create_eos_workflow_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        Ok(json_str)
    })
}

/// Launch an AiiDA geometry optimization workflow.
fn launch_aiida_geopt(py_controller: &Py<PyAny>, config_json: &str) -> Result<String> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("launch_aiida_geopt_json", (config_json,))
            .context("Failed to call launch_aiida_geopt_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        Ok(json_str)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore] // Requires Python environment
    fn test_init_python_backend() {
        pyo3::Python::initialize();
        let result = init_python_backend();
        assert!(result.is_ok());
    }
}
