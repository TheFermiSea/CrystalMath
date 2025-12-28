//! Data models for CrystalMath.
//!
//! These Rust structs match the Pydantic models in `python/crystalmath/models.py`.
//! They use serde for JSON deserialization from the Python backend.
#![allow(dead_code)]

use ratatui::style::Color;
use serde::{Deserialize, Serialize};

/// Job execution state enum.
///
/// Matches Python's `JobState` enum exactly for serde compatibility.
/// Includes `Unknown` variant for forward-compatibility with new states.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum JobState {
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
    pub fn color(&self) -> Color {
        match self {
            JobState::Created => Color::Gray,
            JobState::Submitted => Color::Yellow,
            JobState::Queued => Color::Yellow,
            JobState::Running => Color::Blue,
            JobState::Completed => Color::Green,
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
/// Includes `Unknown` variant for forward-compatibility with new codes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DftCode {
    Crystal,
    Vasp,
    QuantumEspresso,
    /// Forward-compatible fallback for unknown codes
    #[serde(other)]
    Unknown,
}

impl DftCode {
    pub fn as_str(&self) -> &'static str {
        match self {
            DftCode::Crystal => "CRYSTAL",
            DftCode::Vasp => "VASP",
            DftCode::QuantumEspresso => "QE",
            DftCode::Unknown => "Unknown",
        }
    }
}

/// Job execution backend type.
/// Includes `Unknown` variant for forward-compatibility with new runners.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunnerType {
    Local,
    Ssh,
    Slurm,
    Aiida,
    /// Forward-compatible fallback for unknown runners
    #[serde(other)]
    Unknown,
}

impl RunnerType {
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
/// Matches Python's `JobDetails` model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobDetails {
    pub pk: i32,
    #[serde(default)]
    pub uuid: Option<String>,
    pub name: String,
    pub state: JobState,
    #[serde(default)]
    pub dft_code: Option<DftCode>,

    // Computed results
    #[serde(default)]
    pub final_energy: Option<f64>,
    #[serde(default)]
    pub bandgap_ev: Option<f64>,
    #[serde(default)]
    pub convergence_met: bool,
    #[serde(default)]
    pub scf_cycles: Option<i32>,

    // Timing
    #[serde(default)]
    pub cpu_time_seconds: Option<f64>,
    #[serde(default)]
    pub wall_time_seconds: Option<f64>,

    // Diagnostics
    #[serde(default)]
    pub warnings: Vec<String>,
    #[serde(default)]
    pub errors: Vec<String>,
    #[serde(default)]
    pub stdout_tail: Vec<String>,

    // Full results
    #[serde(default)]
    pub key_results: Option<serde_json::Value>,

    // Paths
    #[serde(default)]
    pub work_dir: Option<String>,
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
}

/// Job submission request.
///
/// Used when creating a new job from the UI.
#[derive(Debug, Serialize)]
pub struct JobSubmission {
    pub name: String,
    pub dft_code: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cluster_id: Option<i32>,
    pub parameters: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub structure_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub runner_type: Option<String>,
}

impl JobSubmission {
    /// Create a new job submission.
    pub fn new(name: &str, dft_code: DftCode) -> Self {
        Self {
            name: name.to_string(),
            dft_code: match dft_code {
                DftCode::Crystal => "crystal".to_string(),
                DftCode::Vasp => "vasp".to_string(),
                DftCode::QuantumEspresso => "quantum_espresso".to_string(),
                DftCode::Unknown => "unknown".to_string(),
            },
            cluster_id: None,
            parameters: serde_json::json!({}),
            structure_path: None,
            input_content: None,
            runner_type: None,
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
        self.runner_type = Some(match runner {
            RunnerType::Local => "local".to_string(),
            RunnerType::Ssh => "ssh".to_string(),
            RunnerType::Slurm => "slurm".to_string(),
            RunnerType::Aiida => "aiida".to_string(),
            RunnerType::Unknown => "unknown".to_string(),
        });
        self
    }
}

/// Cluster configuration for remote execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClusterConfig {
    #[serde(default)]
    pub id: Option<i32>,
    pub name: String,
    pub cluster_type: String,
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
    #[serde(default = "default_status")]
    pub status: String,
}

fn default_port() -> i32 {
    22
}

fn default_max_concurrent() -> i32 {
    4
}

fn default_status() -> String {
    "active".to_string()
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
        let submission = JobSubmission::new("test", DftCode::Crystal)
            .with_input_content("CRYSTAL\n0 0 0\n225");

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
        let submission = JobSubmission::new("my-job", DftCode::Vasp)
            .with_input_content("ENCUT = 400");

        assert_eq!(submission.name, "my-job");
        assert_eq!(submission.dft_code, "vasp"); // Stored as String
        assert_eq!(submission.input_content, Some("ENCUT = 400".to_string()));
    }

    #[test]
    fn test_job_submission_crystal() {
        let submission = JobSubmission::new("crystal-calc", DftCode::Crystal);
        assert_eq!(submission.dft_code, "crystal");
        assert_eq!(submission.cluster_id, None);
        assert_eq!(submission.structure_path, None);
    }

    #[test]
    fn test_job_submission_with_runner_type() {
        let submission = JobSubmission::new("test-job", DftCode::Crystal)
            .with_runner_type(RunnerType::Slurm);

        assert_eq!(submission.runner_type, Some("slurm".to_string()));

        // Verify serialization includes runner_type
        let json = serde_json::to_string(&submission).unwrap();
        assert!(json.contains("\"runner_type\":\"slurm\""));

        // Verify None runner_type is skipped in serialization
        let submission_no_runner = JobSubmission::new("test", DftCode::Vasp);
        let json_no_runner = serde_json::to_string(&submission_no_runner).unwrap();
        assert!(!json_no_runner.contains("runner_type"));
    }
}
