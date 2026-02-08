//! Python bridge module using PyO3.
//!
//! This module handles all communication with the Python backend.
//! It uses JSON-RPC over FFI for thin IPC without thick enum variants.
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
// JSON-RPC 2.0 Protocol Types (for thin IPC bridge pattern)
// =============================================================================

/// JSON-RPC 2.0 request structure.
///
/// This enables the thin IPC pattern where we send generic JSON-RPC requests
/// to Python's `dispatch` method instead of calling individual methods directly.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct JsonRpcRequest {
    /// JSON-RPC version (always "2.0")
    pub jsonrpc: String,
    /// Method name to invoke
    pub method: String,
    /// Method parameters (object or array)
    pub params: serde_json::Value,
    /// Request identifier (correlates request/response)
    pub id: u64,
}

impl JsonRpcRequest {
    /// Create a new JSON-RPC 2.0 request.
    pub fn new(method: impl Into<String>, params: serde_json::Value, id: u64) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            method: method.into(),
            params,
            id,
        }
    }
}

/// JSON-RPC 2.0 error object.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct JsonRpcError {
    /// Error code (negative for standard errors, positive for application errors)
    pub code: i32,
    /// Short error message
    pub message: String,
    /// Optional additional data
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,
}

/// JSON-RPC 2.0 response structure.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct JsonRpcResponse {
    /// JSON-RPC version (always "2.0")
    pub jsonrpc: String,
    /// Result on success (mutually exclusive with error)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    /// Error on failure (mutually exclusive with result)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<JsonRpcError>,
    /// Request identifier (matches the request)
    pub id: Option<u64>,
}

impl JsonRpcResponse {
    /// Check if the response is an error.
    pub fn is_error(&self) -> bool {
        self.error.is_some()
    }

    /// Extract the result, converting JSON-RPC error to anyhow::Error.
    pub fn into_result(self) -> Result<serde_json::Value> {
        if let Some(err) = self.error {
            Err(anyhow::anyhow!(
                "JSON-RPC error {}: {}",
                err.code,
                err.message
            ))
        } else {
            self.result
                .ok_or_else(|| anyhow::anyhow!("JSON-RPC response missing both result and error"))
        }
    }
}

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

    /// Send a generic JSON-RPC request (thin IPC pattern).
    ///
    /// This method enables incremental migration from thick bridge variants
    /// to thin JSON-RPC calls. Use for new operations without adding new
    /// `BridgeRequest` variants.
    fn request_rpc(&self, rpc_request: JsonRpcRequest, request_id: usize) -> Result<()>;

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
        // Debug: Check what Python environment PyO3 sees
        if let Ok(sys) = py.import("sys") {
            if let Ok(path) = sys.getattr("path") {
                if let Ok(path_list) = path.extract::<Vec<String>>() {
                    tracing::info!("PyO3 sys.path (first 5 entries):");
                    for (i, p) in path_list.iter().take(5).enumerate() {
                        tracing::info!("  [{}] {}", i, p);
                    }
                    // Check for venv site-packages (any path containing .venv/lib)
                    let has_venv_sp = path_list.iter().any(|p| p.contains(".venv/lib"));
                    tracing::info!("Venv site-packages in sys.path: {}", has_venv_sp);
                }
            }
        }

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

/// Locate a jobs database file from environment variables or well-known locations.
///
/// The search follows this priority:
/// 1. The `CRYSTAL_TUI_DB` environment variable (will be created if its parent directory can be made).
/// 2. A shared Textual TUI database named `.crystal_tui.db` found in the project root (detected via `Cargo.toml`) or in the current working directory (including a `tui/` subdirectory).
/// 3. The XDG user data location `~/.local/share/crystal-tui/jobs.db`.
/// 4. The platform data directory (`dirs::data_dir()`) under `crystal-tui/jobs.db` (created if the parent directory can be made).
/// 5. A legacy development location `tui/jobs.db` in the current working directory.
///
/// If none of the locations exist (and no platform location could be created), the function returns `None` and the caller should treat the application as running in demo mode.
///
/// # Returns
///
/// `Some(String)` containing the filesystem path to the selected jobs database, or `None` if no suitable database path was found or created.
///
/// # Examples
///
/// ```
/// // Try to find an existing or creatable database path.
/// if let Some(db_path) = find_database_path() {
///     println!("Using database at: {}", db_path);
/// } else {
///     println!("No database found; running in demo mode.");
/// }
/// ```
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
/// All requests are now routed through JSON-RPC except for Shutdown.
#[derive(Debug)]
pub enum BridgeRequest {
    /// Graceful shutdown signal - worker exits after receiving this.
    Shutdown,
    /// Generic JSON-RPC request (thin IPC pattern).
    ///
    /// This enables incremental migration from the thick bridge pattern.
    /// The request is serialized to JSON and sent to Python's `dispatch` method.
    Rpc {
        /// The JSON-RPC request to send
        rpc_request: JsonRpcRequest,
        /// Caller's request ID for correlation
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
    /// Generic JSON-RPC response (thin IPC pattern).
    ///
    /// This is used as a fallback for operations that don't have dedicated
    /// typed response variants (e.g., recipes.list, vasp.validate, output.get_file).
    RpcResult {
        request_id: usize,
        /// The JSON-RPC response (may contain result or error)
        result: Result<JsonRpcResponse>,
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

    /// Attempt to send a request to the bridge worker without blocking.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was enqueued successfully. `Err` with context
    /// "Backend busy - try again in a moment" if the request channel is full,
    /// or "Bridge worker disconnected" if the worker has already exited.
    ///
    /// # Examples
    ///
    /// ```
    /// // given a `bridge` of type `BridgeHandle` and a `req` of type `BridgeRequest`:
    /// let _ = bridge.try_send_request(req)?;
    /// ```
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

    /// Send a generic JSON-RPC request (thin IPC pattern).
    ///
    /// This method enables incremental migration from the thick bridge pattern.
    /// Instead of adding a new `BridgeRequest` variant for each new operation,
    /// you can construct a `JsonRpcRequest` and send it through this method.
    ///
    /// # Example
    ///
    /// ```ignore
    /// let request = JsonRpcRequest::new(
    ///     "fetch_jobs",
    ///     serde_json::json!({"limit": 100}),
    ///     request_id as u64,
    /// );
    /// bridge.request_rpc(request, request_id)?;
    /// ```
    pub fn request_rpc(&self, rpc_request: JsonRpcRequest, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::Rpc {
            rpc_request,
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
    /// Send a request to fetch the list of jobs via the bridge worker.
    ///
    /// The supplied `request_id` is echoed back on the corresponding response so callers can
    /// correlate the background reply with the original request.
    ///
    /// # Parameters
    ///
    /// - `request_id`: opaque identifier used to match the eventual response to this request.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was accepted for delivery to the worker; an `Err` if the bridge
    /// is currently busy or disconnected.
    ///
    /// # Examples
    ///
    /// ```no_run
    /// // `bridge` represents a BridgeHandle connected to the worker thread.
    /// let bridge = unimplemented!(); // BridgeHandle
    /// let _ = bridge.request_fetch_jobs(42);
    /// ```
    fn request_fetch_jobs(&self, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "fetch_jobs",
            serde_json::Value::Null,
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request job details for the job with the given primary key through the bridge.
    ///
    /// Sends a JSON-RPC request with method `"fetch_job_details"` and params `{"pk": pk}`
    /// and tags it with `request_id` for matching the async response.
    ///
    /// # Parameters
    ///
    /// - `pk`: Primary key of the job to fetch details for.
    /// - `request_id`: Opaque identifier used to correlate the eventual response with this request.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was successfully queued for the bridge, `Err` if the request could not be sent.
    ///
    /// # Examples
    ///
    /// ```no_run
    /// // `handle` is a bridge handle obtained from the bridge spawner.
    /// # let handle: &crate::BridgeHandle = todo!();
    /// handle.request_fetch_job_details(123, 42).unwrap();
    /// ```
    fn request_fetch_job_details(&self, pk: i32, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "fetch_job_details",
            serde_json::json!({"pk": pk}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Enqueue a job submission request to the Python backend using the `submit_job` JSON-RPC method.
    ///
    /// The `submission` payload is serialized to JSON and sent as the RPC `params` under the key
    /// `"json_payload"`. The provided `request_id` is used to correlate the eventual response.
    ///
    /// # Parameters
    ///
    /// - `submission`: The job submission data to send to the backend.
    /// - `request_id`: A client-side identifier used to correlate this request with its response.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was successfully queued, `Err` if serialization or channel send failed.
    ///
    /// # Examples
    ///
    /// ```
    /// // assume `handle` is a BridgeHandle and `submission` is a JobSubmission
    /// handle.request_submit_job(&submission, 42).unwrap();
    /// ```
    fn request_submit_job(&self, submission: &JobSubmission, request_id: usize) -> Result<()> {
        let json = serde_json::to_string(submission)?;
        let rpc_request = JsonRpcRequest::new(
            "submit_job",
            serde_json::json!({"json_payload": json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request cancellation of a job by primary key.
    ///
    /// Sends a JSON-RPC `"cancel_job"` request to the bridge with the job primary key.
    ///
    /// # Parameters
    ///
    /// - `pk`: Primary key of the job to cancel.
    /// - `request_id`: Local request identifier used to correlate responses.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the cancellation request was accepted for delivery, `Err` if the bridge is busy or disconnected.
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` is a BridgeHandle; request_id should be unique per outstanding request.
    /// let _ = handle.request_cancel_job(123, 42).unwrap();
    /// ```
    fn request_cancel_job(&self, pk: i32, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "cancel_job",
            serde_json::json!({"pk": pk}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request the tail of a job's log from the Python backend.
    ///
    /// Sends a JSON-RPC `fetch_job_log` request containing the job primary key (`pk`)
    /// and the number of tail lines to retrieve. `request_id` is used to correlate
    /// the eventual response with the original request.
    ///
    /// # Errors
    ///
    /// Returns `Err` if the bridge cannot accept the request (for example, if the
    /// worker is busy or disconnected).
    ///
    /// # Examples
    ///
    /// ```
    /// // `bridge` implements BridgeService (e.g., BridgeHandle)
    /// let _ = bridge.request_fetch_job_log(42, 200, 1)?;
    /// ```
    fn request_fetch_job_log(&self, pk: i32, tail_lines: i32, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "fetch_job_log",
            serde_json::json!({"pk": pk, "tail_lines": tail_lines}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request a materials search from the Python backend using a chemical formula and result limit.
    ///
    /// Sends a JSON-RPC `search_materials` request with parameters `formula` and `limit` and associates it with `request_id`.
    ///
    /// # Parameters
    ///
    /// * `request_id` - Client-provided identifier used to correlate the eventual response with this request.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was queued successfully; `Err(_)` if the request could not be sent (for example, because the bridge is busy or the worker has disconnected).
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` is a BridgeHandle previously created by the application.
    /// handle.request_search_materials("Fe2O3", 10, 42).expect("failed to queue search");
    /// ```
    fn request_search_materials(
        &self,
        formula: &str,
        limit: usize,
        request_id: usize,
    ) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "search_materials",
            serde_json::json!({"formula": formula, "limit": limit}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Requests generation of a D12 string for the given material ID using the bridge.
    ///
    /// `mp_id` is the material identifier to generate the D12 for. `config_json` is a
    /// JSON-encoded configuration object for the generator. `request_id` is the caller's
    /// identifier used to correlate the asynchronous response.
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` implements the bridge service (e.g., BridgeHandle)
    /// handle.request_generate_d12("mp-123", r#"{"option": true}"#, 42).unwrap();
    /// ```
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was accepted and queued, `Err(_)` if the request could not be sent.
    fn request_generate_d12(
        &self,
        mp_id: &str,
        config_json: &str,
        request_id: usize,
    ) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "generate_d12",
            serde_json::json!({"mp_id": mp_id, "config_json": config_json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request the SLURM queue for the given cluster from the Python backend.
    ///
    /// Sends a JSON-RPC `fetch_slurm_queue` request with `cluster_id` and associates it with `request_id`.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was queued successfully, `Err` if the bridge is busy or disconnected.
    ///
    /// # Examples
    ///
    /// ```
    /// // Assume `bridge` implements the BridgeService (e.g., a BridgeHandle).
    /// let res = bridge.request_fetch_slurm_queue(7, 123);
    /// assert!(res.is_ok());
    /// ```
    fn request_fetch_slurm_queue(&self, cluster_id: i32, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "fetch_slurm_queue",
            serde_json::json!({"cluster_id": cluster_id}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Sends a JSON-RPC request to cancel a SLURM job on the specified cluster.
    ///
    /// The request is enqueued for the bridge worker and routed to the Python backend
    /// under the `"cancel_slurm_job"` method with `cluster_id` and `slurm_job_id` as parameters.
    ///
    /// # Parameters
    ///
    /// - `cluster_id`: Identifier of the cluster that manages the SLURM job.
    /// - `slurm_job_id`: SLURM job identifier string.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was successfully queued for dispatch, `Err` if the bridge
    /// is busy or disconnected and the request could not be sent.
    ///
    /// # Examples
    ///
    /// ```
    /// // `bridge` implements the BridgeService/BridgeHandle interface.
    /// let result = bridge.request_cancel_slurm_job(1, "12345", 42);
    /// assert!(result.is_ok());
    /// ```
    fn request_cancel_slurm_job(
        &self,
        cluster_id: i32,
        slurm_job_id: &str,
        request_id: usize,
    ) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "cancel_slurm_job",
            serde_json::json!({"cluster_id": cluster_id, "slurm_job_id": slurm_job_id}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request that the backend adopt an existing SLURM job into the TUI-managed job list.
    ///
    /// Sends a JSON-RPC `adopt_slurm_job` request containing `cluster_id` and `slurm_job_id`.
    ///
    /// # Examples
    ///
    /// ```
    /// # use serde_json::json;
    /// // Construct the JSON-RPC payload this method will send
    /// let expected = serde_json::json!({
    ///     "jsonrpc": "2.0",
    ///     "method": "adopt_slurm_job",
    ///     "params": { "cluster_id": 1, "slurm_job_id": "12345" },
    ///     "id": 42u64
    /// });
    /// let rpc = crate::bridge::JsonRpcRequest::new("adopt_slurm_job", json!({"cluster_id": 1, "slurm_job_id": "12345"}), 42);
    /// assert_eq!(rpc.method, "adopt_slurm_job");
    /// assert_eq!(rpc.id, 42u64);
    /// ```
    ///
    /// # Returns
    ///
    /// `Ok(())` on success; an `Err` if the bridge cannot accept the request (for example, if the bridge is busy or disconnected).
    fn request_adopt_slurm_job(
        &self,
        cluster_id: i32,
        slurm_job_id: &str,
        request_id: usize,
    ) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "adopt_slurm_job",
            serde_json::json!({"cluster_id": cluster_id, "slurm_job_id": slurm_job_id}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request a remote job synchronization through the Python backend.
    ///
    /// Sends a `"sync_remote_jobs"` JSON-RPC request with the given `request_id` so the worker can enqueue
    /// a background synchronization of remote jobs.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was queued successfully, `Err` if the bridge is busy or disconnected.
    ///
    /// # Examples
    ///
    /// ```
    /// // assume `handle` is a `BridgeHandle`
    /// let request_id = 1usize;
    /// handle.request_sync_remote_jobs(request_id).unwrap();
    /// ```
    fn request_sync_remote_jobs(&self, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "sync_remote_jobs",
            serde_json::Value::Null,
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request a list of available templates from the Python backend.
    ///
    /// Sends a JSON-RPC `list_templates` request and associates it with `request_id` so the
    /// corresponding response can be correlated when polled.
    ///
    /// # Parameters
    ///
    /// - `request_id`: Identifier used to correlate the sent request with a later response.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was successfully queued for the bridge worker, `Err` if the bridge
    /// is currently full or disconnected.
    ///
    /// # Examples
    ///
    /// ```
    /// // `bridge` is a BridgeHandle obtained from BridgeHandle::spawn(...)
    /// bridge.request_fetch_templates(42).unwrap();
    /// ```
    fn request_fetch_templates(&self, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "list_templates",
            serde_json::Value::Null,
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Queue a request to render a named template with the given JSON parameters.
    ///
    /// Sends a JSON-RPC `render_template` request to the backend containing the
    /// template name and a JSON-encoded parameters string, tagged with `request_id`.
    ///
    /// # Parameters
    ///
    /// - `template_name`: Name of the template to render.
    /// - `params_json`: A JSON string containing the template parameters.
    /// - `request_id`: Local identifier used to correlate the backend response.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was successfully queued, `Err(...)` if the request could
    /// not be sent (for example, if the backend is busy or the bridge is disconnected).
    ///
    /// # Examples
    ///
    /// ```no_run
    /// // `handle` is a BridgeHandle connected to the Python backend.
    /// let handle: &crate::BridgeHandle = &unimplemented!();
    /// handle.request_render_template("my_template", r#"{"name":"Alice"}"#, 42).unwrap();
    /// ```
    fn request_render_template(
        &self,
        template_name: &str,
        params_json: &str,
        request_id: usize,
    ) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "render_template",
            serde_json::json!({"template_name": template_name, "params_json": params_json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Requests the list of clusters from the Python backend using a JSON-RPC `fetch_clusters` call.
    ///
    /// `request_id` is an opaque identifier used to correlate the eventual `BridgeResponse` with this request.
    ///
    /// # Examples
    ///
    /// ```no_run
    /// # // `handle` is a previously created BridgeHandle connected to the Python backend.
    /// # let handle: crate::bridge::BridgeHandle = unimplemented!();
    /// let request_id = 42;
    /// handle.request_fetch_clusters(request_id).unwrap();
    /// ```
    fn request_fetch_clusters(&self, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "fetch_clusters",
            serde_json::Value::Null,
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request creation of a new cluster on the Python backend.
    ///
    /// Serializes `config` and enqueues a JSON-RPC `"create_cluster"` request correlated with `request_id`.
    ///
    /// # Parameters
    ///
    /// - `request_id`: Identifier used to correlate the created request with its eventual response.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was queued successfully, `Err` if serialization or sending the request failed.
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` is a BridgeHandle connected to the Python backend.
    /// // `cfg` is a ClusterConfig to create.
    /// // This example demonstrates the call pattern; actual BridgeHandle construction is omitted.
    /// let _ = handle.request_create_cluster(&cfg, 42).unwrap();
    /// ```
    fn request_create_cluster(&self, config: &ClusterConfig, request_id: usize) -> Result<()> {
        let json = serde_json::to_string(config)?;
        let rpc_request = JsonRpcRequest::new(
            "create_cluster",
            serde_json::json!({"json_payload": json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request an update to an existing cluster's configuration through the Python bridge.
    ///
    /// Sends a JSON-RPC `update_cluster` request containing the cluster id and a JSON-serialized
    /// cluster configuration. The provided `request_id` is used to correlate the eventual bridge response.
    ///
    /// # Errors
    ///
    /// Returns an error if serializing `config` to JSON fails or if sending the request to the bridge fails.
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` is a BridgeHandle or other type implementing this method.
    /// let cluster_id = 42;
    /// let config = ClusterConfig { /* fields */ };
    /// let request_id = 1;
    /// handle.request_update_cluster(cluster_id, &config, request_id)?;
    /// ```
    fn request_update_cluster(
        &self,
        cluster_id: i32,
        config: &ClusterConfig,
        request_id: usize,
    ) -> Result<()> {
        let json = serde_json::to_string(config)?;
        let rpc_request = JsonRpcRequest::new(
            "update_cluster",
            serde_json::json!({"cluster_id": cluster_id, "json_payload": json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request deletion of a cluster on the Python backend.
    ///
    /// Sends a JSON-RPC `delete_cluster` request carrying the cluster primary key to the bridge worker.
    ///
    /// # Parameters
    ///
    /// - `cluster_id`: Primary key of the cluster to delete.
    /// - `request_id`: Client-visible identifier used to correlate the eventual response with this request.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the delete request was accepted for dispatch, `Err` if the bridge could not enqueue the request (for example, because it is busy or disconnected).
    ///
    /// # Examples
    ///
    /// ```
    /// #[test]
    /// fn send_delete_cluster_request() {
    ///     // `handle` must implement the bridge service (e.g., BridgeHandle).
    ///     // This example demonstrates the simplest usage; in real code `handle` is obtained from BridgeHandle::spawn(...).
    ///     let handle = get_test_bridge_handle();
    ///     handle.request_delete_cluster(42, 1).unwrap();
    /// }
    /// ```
    fn request_delete_cluster(&self, cluster_id: i32, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "delete_cluster",
            serde_json::json!({"cluster_id": cluster_id}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Queues a JSON-RPC request to test the connection for the specified cluster.
    ///
    /// Sends a `test_cluster_connection` JSON-RPC request with the given `cluster_id` and
    /// associates it with `request_id` so the bridge can correlate the eventual response.
    ///
    /// # Examples
    ///
    /// ```no_run
    /// // `svc` should implement `BridgeService` (for example, a `BridgeHandle`).
    /// svc.request_test_cluster_connection(1, 42).unwrap();
    /// ```
    ///
    /// Returns `Ok(())` if the request was queued successfully, `Err` with context otherwise.
    fn request_test_cluster_connection(&self, cluster_id: i32, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "test_cluster_connection",
            serde_json::json!({"cluster_id": cluster_id}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Requests a check for which workflows are available from the backend.
    ///
    /// Sends a JSON-RPC `check_workflows_available` request to the Python bridge using the provided
    /// `request_id`.
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` is a BridgeHandle obtained from BridgeHandle::spawn(...).
    /// // The call queues a non-blocking request; use `poll_response` to receive the result.
    /// let _ = handle.request_check_workflows_available(42);
    /// ```
    fn request_check_workflows_available(&self, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "check_workflows_available",
            serde_json::Value::Null,
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Requests creation of a convergence study on the Python backend using the given JSON configuration.
    ///
    /// `config_json` is a JSON string describing the convergence study parameters. `request_id` is an
    /// opaque identifier used to correlate the asynchronous response produced by the bridge.
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was queued successfully, `Err` if the bridge is busy or disconnected.
    ///
    /// # Examples
    ///
    /// ```
    /// let cfg = r#"{"kpoints": {"start": 1, "end": 5}, "tolerance": 1e-3}"#;
    /// handle.request_create_convergence_study(cfg, 42).unwrap();
    /// ```
    fn request_create_convergence_study(&self, config_json: &str, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "create_convergence_study",
            serde_json::json!({"config_json": config_json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request creation of a band structure workflow using the provided workflow configuration JSON.
    
    ///
    
    /// The function wraps `config_json` into a JSON-RPC `create_band_structure_workflow` request and
    
    /// enqueues it for the Python backend using the provided `request_id`.
    
    ///
    
    /// # Examples
    
    ///
    
    /// ```
    
    /// // `handle` is an instance implementing the bridge service (e.g. BridgeHandle).
    
    /// let config = r#"{"kpoints": 100, "parameters": {"ecut": 50}}"#;
    
    /// handle.request_create_band_structure_workflow(config, 42).unwrap();
    
    /// ```
    fn request_create_band_structure_workflow(
        &self,
        config_json: &str,
        request_id: usize,
    ) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "create_band_structure_workflow",
            serde_json::json!({"config_json": config_json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Request creation of a phonon workflow using the provided configuration JSON.
    ///
    /// Sends a JSON-RPC `create_phonon_workflow` request with `config_json` as the payload and enqueues it under `request_id`.
    ///
    /// # Returns
    /// `Ok(())` if the request was enqueued successfully, `Err` with context if sending fails.
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` is a BridgeHandle (or any type implementing the same method)
    /// let config = r#"{"structure": {"atoms": []}, "parameters": {}}"#;
    /// handle.request_create_phonon_workflow(config, 7).unwrap();
    /// ```
    fn request_create_phonon_workflow(&self, config_json: &str, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "create_phonon_workflow",
            serde_json::json!({"config_json": config_json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Creates an equation-of-state (EOS) workflow on the Python backend by sending a JSON-RPC request.
    ///
    /// `config_json` must be a JSON string containing the workflow configuration. `request_id` is an
    /// opaque identifier used to correlate the request with a later response from the bridge.
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` is a BridgeHandle implementing this method.
    /// let config = r#"{"structure": "C", "parameters": {"kpoints": 4}}"#;
    /// let request_id = 42usize;
    /// handle.request_create_eos_workflow(config, request_id).unwrap();
    /// ```
    fn request_create_eos_workflow(&self, config_json: &str, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "create_eos_workflow",
            serde_json::json!({"config_json": config_json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Queues a JSON-RPC request to launch an AiiDA ge-opt workflow using the given JSON configuration.
    ///
    /// The `config_json` string should contain the workflow configuration expected by the Python backend; `request_id` is used to correlate the backend response with this request.
    ///
    /// # Examples
    ///
    /// ```
    /// // `handle` is a BridgeHandle connected to the Python backend.
    /// handle.request_launch_aiida_geopt(r#"{"structure": {"atoms": []}, "settings": {}}"#, 42).unwrap();
    /// ```
    ///
    /// # Returns
    ///
    /// `Ok(())` if the request was queued successfully, `Err` with context otherwise.
    fn request_launch_aiida_geopt(&self, config_json: &str, request_id: usize) -> Result<()> {
        let rpc_request = JsonRpcRequest::new(
            "launch_aiida_geopt",
            serde_json::json!({"config_json": config_json}),
            request_id as u64,
        );
        self.request_rpc(rpc_request, request_id)
    }

    /// Enqueues a JSON-RPC request for the bridge worker to process and associates it with a client-side request id.
    ///
    /// The `rpc_request` is the JSON-RPC 2.0 payload to dispatch to the Python backend. The `request_id` is an
    /// application-level identifier used to correlate the eventual `BridgeResponse` with the original request.
    ///
    /// # Examples
    ///
    /// ```no_run
    /// // `handle` is a BridgeHandle; `req` is a JsonRpcRequest built for the desired method.
    /// let _ = handle.request_rpc(req, 42);
    /// ```
    fn request_rpc(&self, rpc_request: JsonRpcRequest, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::Rpc {
            rpc_request,
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

/// Process a single bridge request and produce the corresponding typed BridgeResponse.
///
/// This converts a received `BridgeRequest::Rpc` into a routed `BridgeResponse` by dispatching
/// the contained JSON-RPC request through the Python controller and mapping the result back
/// to the appropriate response variant. The `Shutdown` variant is not expected here and must
/// be handled by the worker loop.
///
/// # Examples
///
/// ```no_run
/// use crate::{process_bridge_request, BridgeRequest, JsonRpcRequest};
/// // Build a JsonRpcRequest and a Py controller, then:
/// // let resp = process_bridge_request(&py_controller, BridgeRequest::Rpc { rpc_request, request_id: 1 });
/// ```
/* no outer attributes */
fn process_bridge_request(py_controller: &Py<PyAny>, request: BridgeRequest) -> BridgeResponse {
    match request {
        BridgeRequest::Shutdown => unreachable!("Shutdown handled in worker loop"),
        BridgeRequest::Rpc {
            rpc_request,
            request_id,
        } => {
            let method = rpc_request.method.clone();
            let rpc_result = dispatch_rpc(py_controller, &rpc_request);
            route_rpc_response(&method, request_id, rpc_result)
        }
    }
}

/// Map a JSON-RPC reply into the typed BridgeResponse variant expected by the caller.
///
/// Converts a generic `JsonRpcResponse` (success or error) for `method` into the
/// corresponding `BridgeResponse` variant using `request_id`. For methods that
/// return an `ApiResponse<T>` the inner result is extracted; for method-specific
/// error conditions (for example a `NOT_FOUND` marker for job details) the
/// behaviour follows the original API semantics. Unknown methods are returned
/// as `BridgeResponse::RpcResult` so callers can handle them generically.
///
/// # Parameters
///
/// - `method`: the JSON-RPC method name that produced `rpc_result`.
/// - `request_id`: caller-provided identifier associated with the original request.
/// - `rpc_result`: the deserialized `JsonRpcResponse` or an error describing why
///   dispatch/transport failed.
///
/// # Returns
///
/// A `BridgeResponse` variant containing `request_id` and either the parsed
/// typed result or an `Err` describing the failure.
///
/// # Examples
///
/// ```no_run
/// // Example (non-executable) showing the high-level intent:
/// // let resp = route_rpc_response("fetch_jobs", 42, rpc_result);
/// // match resp {
/// //     BridgeResponse::Jobs { request_id, result } => { /* handle jobs */ }
/// //     BridgeResponse::RpcResult { request_id, result } => { /* fallback */ }
/// //     _ => {}
/// // }
/// ```
fn route_rpc_response(
    method: &str,
    request_id: usize,
    rpc_result: Result<JsonRpcResponse>,
) -> BridgeResponse {
    match method {
        "fetch_jobs" | "sync_remote_jobs" => BridgeResponse::Jobs {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                Ok(serde_json::from_value(value)?)
            }),
        },
        "fetch_job_details" => BridgeResponse::JobDetails {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<JobDetails> = serde_json::from_value(value)?;
                match api_resp.into_result() {
                    Ok(details) => Ok(Some(details)),
                    Err(msg) if msg.contains("NOT_FOUND") => Ok(None),
                    Err(msg) => Err(anyhow::anyhow!("Job details error: {}", msg)),
                }
            }),
        },
        "submit_job" => BridgeResponse::JobSubmitted {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                Ok(serde_json::from_value(value)?)
            }),
        },
        "cancel_job" => BridgeResponse::JobCancelled {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                Ok(serde_json::from_value(value)?)
            }),
        },
        "fetch_job_log" => BridgeResponse::JobLog {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                Ok(serde_json::from_value(value)?)
            }),
        },
        "search_materials" => BridgeResponse::MaterialsFound {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<Vec<MaterialResult>> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "generate_d12" => BridgeResponse::D12Generated {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<String> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "fetch_slurm_queue" => BridgeResponse::SlurmQueue {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<Vec<SlurmQueueEntry>> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "cancel_slurm_job" => BridgeResponse::SlurmJobCancelled {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<SlurmCancelResult> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "adopt_slurm_job" => BridgeResponse::SlurmJobAdopted {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                #[derive(serde::Deserialize, Default)]
                struct AdoptResponse {
                    pk: i32,
                }
                let api_resp: ApiResponse<AdoptResponse> = serde_json::from_value(value)?;
                Ok(api_resp.into_result().map_err(|e| anyhow::anyhow!(e))?.pk)
            }),
        },
        "list_templates" => BridgeResponse::Templates {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<Vec<crate::models::Template>> =
                    serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "render_template" => BridgeResponse::TemplateRendered {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<String> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "fetch_clusters" => BridgeResponse::Clusters {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<Vec<ClusterConfig>> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "create_cluster" => BridgeResponse::ClusterCreated {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<ClusterConfig> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "update_cluster" => BridgeResponse::ClusterUpdated {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<ClusterConfig> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "delete_cluster" => BridgeResponse::ClusterDeleted {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<bool> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "test_cluster_connection" => BridgeResponse::ClusterConnectionTested {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<ClusterConnectionResult> =
                    serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "check_workflows_available" => BridgeResponse::WorkflowsAvailable {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                let api_resp: ApiResponse<WorkflowAvailability> = serde_json::from_value(value)?;
                api_resp.into_result().map_err(|e| anyhow::anyhow!(e))
            }),
        },
        "create_convergence_study"
        | "create_band_structure_workflow"
        | "create_phonon_workflow"
        | "create_eos_workflow"
        | "launch_aiida_geopt" => BridgeResponse::WorkflowCreated {
            request_id,
            result: rpc_result.and_then(|resp| {
                let value = resp.into_result()?;
                // The dispatch already parsed the JSON string to a Value. Re-serialize it.
                Ok(serde_json::to_string(&value).unwrap_or_default())
            }),
        },
        _ => {
            // Unknown method - return as generic RpcResult for app.rs to handle
            BridgeResponse::RpcResult {
                request_id,
                result: rpc_result,
            }
        }
    }
}

/// Dispatch a JSON-RPC request to Python's generic dispatcher.
///
/// This is the core of the thin IPC pattern - instead of calling individual
/// Python methods, we serialize the request to JSON and call `dispatch`.
fn dispatch_rpc(
    py_controller: &Py<PyAny>,
    rpc_request: &JsonRpcRequest,
) -> Result<JsonRpcResponse> {
    Python::attach(|py| {
        let controller = py_controller.bind(py);

        // Serialize the request to JSON
        let request_json =
            serde_json::to_string(rpc_request).context("Failed to serialize JSON-RPC request")?;

        // Call Python's dispatch method
        let response_json: String = controller
            .call_method1("dispatch", (request_json,))
            .context("Failed to call Python dispatch")?
            .extract()
            .context("Failed to extract response JSON")?;

        // Deserialize the response
        let response: JsonRpcResponse =
            serde_json::from_str(&response_json).context("Failed to parse JSON-RPC response")?;

        Ok(response)
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