# Data Modeling: Pydantic ↔ Rust Serde

To ensure stability, we establish a "Shared Schema" contract. Python defines the schema via Pydantic (because AiiDA objects are Python), and Rust mirrors it via Serde.

## 1. Python Models (`python/crystalmath/models.py`)

These models replace your ad-hoc dictionaries in `database.py`.

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime
from enum import Enum


class JobState(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobSubmission(BaseModel):
    """Data required to start a new job."""
    name: str = Field(..., min_length=3, max_length=50)
    dft_code: Literal['crystal', 'vasp', 'qe']
    cluster_id: int
    parameters: Dict[str, Any]  # The d12/INCAR parameters
    structure_path: Optional[str] = None  # Path to .cif or .xyz


class JobStatus(BaseModel):
    """Lightweight status object for the Sidebar list."""
    pk: int
    uuid: str
    name: str
    state: JobState
    progress_percent: float = 0.0
    wall_time_seconds: Optional[float] = None
    
    @field_validator('state', mode='before')
    def map_aiida_state(cls, v):
        # AiiDA states -> UI states
        mapping = {
            'finished': JobState.COMPLETED,
            'excepted': JobState.FAILED,
            'killed': JobState.FAILED,
            'waiting': JobState.SUBMITTED,
        }
        return mapping.get(v, v)


class JobDetails(BaseModel):
    """Full details for the Results view."""
    pk: int
    final_energy: Optional[float]
    convergence_met: bool
    warnings: List[str] = []
    # Raw output for the log viewer
    stdout_tail: List[str] = []
```

## 2. Rust Models (`src/models.rs`)

Rust uses serde to safely deserialize the JSON strings coming from Python.

```rust
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub enum JobState {
    CREATED,
    SUBMITTED,
    RUNNING,
    COMPLETED,
    FAILED,
}

impl JobState {
    pub fn color(&self) -> ratatui::style::Color {
        use ratatui::style::Color;
        match self {
            JobState::RUNNING => Color::Blue,
            JobState::COMPLETED => Color::Green,
            JobState::FAILED => Color::Red,
            _ => Color::Yellow,
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct JobStatus {
    pub pk: i32,
    pub uuid: String,
    pub name: String,
    pub state: JobState,
    pub progress_percent: f64,
    pub wall_time_seconds: Option<f64>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct JobDetails {
    pub pk: i32,
    pub final_energy: Option<f64>,
    pub convergence_met: bool,
    pub warnings: Vec<String>,
    pub stdout_tail: Vec<String>,
}

// For sending data TO Python
#[derive(Serialize, Debug)]
pub struct JobSubmission {
    pub name: String,
    pub dft_code: String,
    pub cluster_id: i32,
    pub parameters: serde_json::Value,
}
```

## 3. The Serialization Bridge (`src/bridge.rs`)

Helper functions to handle the FFI boundary cleanly.

```rust
use pyo3::prelude::*;
use crate::models::{JobStatus, JobSubmission};

/// Fetches the list of active jobs from the Python backend.
pub fn fetch_jobs(py_controller: &PyObject) -> anyhow::Result<Vec<JobStatus>> {
    Python::with_gil(|py| {
        let controller = py_controller.as_ref(py);
        
        // 1. Call Python method: get_jobs_json()
        // We use JSON strings over FFI because PyO3 native conversion 
        // can be tricky with complex nested structs.
        let json_str: String = controller
            .call_method0("get_jobs_json")?
            .extract()?;
        
        // 2. Deserialize in Rust
        let jobs: Vec<JobStatus> = serde_json::from_str(&json_str)?;
        Ok(jobs)
    })
}

/// Submits a new job to AiiDA.
pub fn submit_job(py_controller: &PyObject, submission: &JobSubmission) -> anyhow::Result<i32> {
    Python::with_gil(|py| {
        let controller = py_controller.as_ref(py);
        
        // Serialize Rust struct to JSON string for Python
        let json_payload = serde_json::to_string(submission)?;
        
        // Call submit_job_json(payload)
        let pk: i32 = controller
            .call_method1("submit_job_json", (json_payload,))?
            .extract()?;
            
        Ok(pk)
    })
}
```
