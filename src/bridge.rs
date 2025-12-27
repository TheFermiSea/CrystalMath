//! Python bridge module using PyO3.
//!
//! This module handles all communication with the Python backend.
//! It uses JSON strings over FFI for simplicity and robustness.
//!
//! The async bridge (BridgeHandle) spawns a dedicated worker thread that
//! owns the PyObject, allowing the main UI thread to remain responsive
//! at 60fps while Python operations execute in the background.

use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;

use anyhow::{Context, Result};
use pyo3::prelude::*;

use crate::models::{JobDetails, JobStatus, JobSubmission};

/// Initialize the Python backend and return the controller object.
pub fn init_python_backend() -> Result<PyObject> {
    Python::with_gil(|py| {
        // Import the crystalmath.api module
        let api_module = py
            .import("crystalmath.api")
            .context("Failed to import crystalmath.api - is the Python package installed?")?;

        // Call create_controller() factory function
        let controller = api_module
            .call_method1(
                "create_controller",
                (
                    "default",  // profile_name
                    false,      // use_aiida (use demo mode for now)
                    Option::<&str>::None,  // db_path
                ),
            )
            .context("Failed to create CrystalController")?;

        Ok(controller.into())
    })
}

/// Fetch the list of jobs from the Python backend.
pub fn fetch_jobs(py_controller: &PyObject) -> Result<Vec<JobStatus>> {
    Python::with_gil(|py| {
        let controller = py_controller.bind(py);

        // Call get_jobs_json() and extract the string
        let json_str: String = controller
            .call_method0("get_jobs_json")
            .context("Failed to call get_jobs_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Deserialize in Rust
        let jobs: Vec<JobStatus> =
            serde_json::from_str(&json_str).context("Failed to parse jobs JSON")?;

        Ok(jobs)
    })
}

/// Fetch detailed job information.
pub fn fetch_job_details(py_controller: &PyObject, pk: i32) -> Result<Option<JobDetails>> {
    Python::with_gil(|py| {
        let controller = py_controller.bind(py);

        // Call get_job_details_json(pk)
        let json_str: String = controller
            .call_method1("get_job_details_json", (pk,))
            .context("Failed to call get_job_details_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        // Empty object means not found
        if json_str == "{}" {
            return Ok(None);
        }

        // Deserialize
        let details: JobDetails =
            serde_json::from_str(&json_str).context("Failed to parse job details JSON")?;

        Ok(Some(details))
    })
}

/// Submit a new job to the Python backend.
pub fn submit_job(py_controller: &PyObject, submission: &JobSubmission) -> Result<i32> {
    Python::with_gil(|py| {
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
pub fn cancel_job(py_controller: &PyObject, pk: i32) -> Result<bool> {
    Python::with_gil(|py| {
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
pub fn fetch_job_log(py_controller: &PyObject, pk: i32, tail_lines: i32) -> Result<JobLog> {
    Python::with_gil(|py| {
        let controller = py_controller.bind(py);

        let json_str: String = controller
            .call_method1("get_job_log_json", (pk, tail_lines))
            .context("Failed to call get_job_log_json")?
            .extract()
            .context("Failed to extract JSON string")?;

        let log: JobLog =
            serde_json::from_str(&json_str).context("Failed to parse log JSON")?;

        Ok(log)
    })
}

/// Job log output.
#[derive(Debug, serde::Deserialize)]
pub struct JobLog {
    pub stdout: Vec<String>,
    pub stderr: Vec<String>,
}

// =============================================================================
// Async Bridge Types
// =============================================================================

/// Request types for the Python bridge worker thread.
#[derive(Debug)]
pub enum BridgeRequest {
    FetchJobs,
    FetchJobDetails { pk: i32 },
    SubmitJob { submission_json: String },
    CancelJob { pk: i32 },
    FetchJobLog { pk: i32, tail_lines: i32 },
}

/// Response types from the Python bridge worker thread.
#[derive(Debug)]
pub enum BridgeResponse {
    Jobs(Result<Vec<JobStatus>>),
    JobDetails(Result<Option<JobDetails>>),
    JobSubmitted(Result<i32>),
    JobCancelled(Result<bool>),
    JobLog(Result<JobLog>),
}

/// Kind of pending bridge request (for UI feedback).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BridgeRequestKind {
    FetchJobs,
    FetchJobDetails,
    SubmitJob,
    CancelJob,
    FetchJobLog,
}

/// Handle to the Python bridge worker thread.
///
/// This provides a non-blocking interface to Python operations.
/// Requests are sent via a channel to a dedicated worker thread,
/// and responses are polled from another channel.
pub struct BridgeHandle {
    request_tx: Sender<BridgeRequest>,
    response_rx: Receiver<BridgeResponse>,
}

impl BridgeHandle {
    /// Create a new bridge handle by spawning a worker thread.
    ///
    /// The worker thread owns the PyObject and processes requests
    /// via channels, keeping the GIL off the main UI thread.
    pub fn spawn(py_controller: PyObject) -> Result<Self> {
        let (request_tx, request_rx) = mpsc::channel::<BridgeRequest>();
        let (response_tx, response_rx) = mpsc::channel::<BridgeResponse>();

        thread::spawn(move || {
            bridge_worker_loop(py_controller, request_rx, response_tx);
        });

        Ok(Self {
            request_tx,
            response_rx,
        })
    }

    /// Send a request to fetch jobs (non-blocking).
    pub fn request_fetch_jobs(&self) -> Result<()> {
        self.request_tx
            .send(BridgeRequest::FetchJobs)
            .map_err(|e| anyhow::anyhow!("Bridge worker disconnected: {}", e))
    }

    /// Send a request to fetch job details (non-blocking).
    pub fn request_fetch_job_details(&self, pk: i32) -> Result<()> {
        self.request_tx
            .send(BridgeRequest::FetchJobDetails { pk })
            .map_err(|e| anyhow::anyhow!("Bridge worker disconnected: {}", e))
    }

    /// Send a request to submit a job (non-blocking).
    pub fn request_submit_job(&self, submission: &JobSubmission) -> Result<()> {
        let json = serde_json::to_string(submission)?;
        self.request_tx
            .send(BridgeRequest::SubmitJob {
                submission_json: json,
            })
            .map_err(|e| anyhow::anyhow!("Bridge worker disconnected: {}", e))
    }

    /// Send a request to cancel a job (non-blocking).
    pub fn request_cancel_job(&self, pk: i32) -> Result<()> {
        self.request_tx
            .send(BridgeRequest::CancelJob { pk })
            .map_err(|e| anyhow::anyhow!("Bridge worker disconnected: {}", e))
    }

    /// Send a request to fetch job log (non-blocking).
    pub fn request_fetch_job_log(&self, pk: i32, tail_lines: i32) -> Result<()> {
        self.request_tx
            .send(BridgeRequest::FetchJobLog { pk, tail_lines })
            .map_err(|e| anyhow::anyhow!("Bridge worker disconnected: {}", e))
    }

    /// Poll for a response (non-blocking).
    ///
    /// Returns `Some(response)` if a response is available,
    /// `None` if no response is ready yet.
    pub fn poll_response(&self) -> Option<BridgeResponse> {
        self.response_rx.try_recv().ok()
    }
}

/// Worker loop that processes Python requests.
///
/// This runs on a dedicated thread and owns the PyObject.
/// It blocks waiting for requests and sends responses back via channel.
fn bridge_worker_loop(
    py_controller: PyObject,
    request_rx: Receiver<BridgeRequest>,
    response_tx: Sender<BridgeResponse>,
) {
    while let Ok(request) = request_rx.recv() {
        let response = match request {
            BridgeRequest::FetchJobs => BridgeResponse::Jobs(fetch_jobs(&py_controller)),
            BridgeRequest::FetchJobDetails { pk } => {
                BridgeResponse::JobDetails(fetch_job_details(&py_controller, pk))
            }
            BridgeRequest::SubmitJob { submission_json } => {
                BridgeResponse::JobSubmitted(submit_job_json(&py_controller, &submission_json))
            }
            BridgeRequest::CancelJob { pk } => {
                BridgeResponse::JobCancelled(cancel_job(&py_controller, pk))
            }
            BridgeRequest::FetchJobLog { pk, tail_lines } => {
                BridgeResponse::JobLog(fetch_job_log(&py_controller, pk, tail_lines))
            }
        };

        if response_tx.send(response).is_err() {
            // Main thread disconnected, exit worker
            break;
        }
    }
}

/// Helper for submitting job from JSON string.
///
/// Used by the worker thread to avoid re-serializing the JobSubmission.
fn submit_job_json(py_controller: &PyObject, json_payload: &str) -> Result<i32> {
    Python::with_gil(|py| {
        let controller = py_controller.bind(py);
        let pk: i32 = controller
            .call_method1("submit_job_json", (json_payload,))
            .context("Failed to call submit_job_json")?
            .extract()
            .context("Failed to extract job pk")?;
        Ok(pk)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore] // Requires Python environment
    fn test_init_python_backend() {
        pyo3::prepare_freethreaded_python();
        let result = init_python_backend();
        assert!(result.is_ok());
    }
}
