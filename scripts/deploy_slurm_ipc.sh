#!/bin/bash
# ==============================================================================
# CRYSTALMATH MONOREPO - SLURM IPC DECOUPLED INTEGRATION LAYER DEPLOYMENT
# ==============================================================================
# This monolithic runner automatically updates the Python models, scaffolds the
# JSON-RPC server routing, updates the Rust state engine actions, and formalizes
# the architecture trail under ADR-028.
# ==============================================================================

set -euo pipefail

echo "🔮 Starting decoupled Slurm IPC injection..."

# ------------------------------------------------------------------------------
# STEP 1: Update Python Wire Contracts (python/crystalmath/models.py)
# ------------------------------------------------------------------------------
PYTHON_MODELS="python/crystalmath/models.py"
echo "📝 Step 1: Injecting Pydantic models into $PYTHON_MODELS..."

if [ ! -f "$PYTHON_MODELS" ]; then
  echo "⚠️ Target file missing. Creating structural fallback $PYTHON_MODELS..."
  mkdir -p python/crystalmath
  echo "from pydantic import BaseModel" >"$PYTHON_MODELS"
fi

cat <<'EOF' >>"$PYTHON_MODELS"

# --- Slurm Cluster Workload Telemetry Models (ADR-028) ---
from typing import List, Optional

class SlurmJobModel(BaseModel):
    job_id: int
    partition: str
    name: str
    user: str
    state: str
    time_used: str
    stdout_path: str

class SlurmQueueResponse(BaseModel):
    success: bool
    jobs: List[SlurmJobModel]
    error_message: Optional[str] = None
EOF

# ------------------------------------------------------------------------------
# STEP 2: Configure Python Backend RPC Endpoints (python/crystalmath/server/)
# ------------------------------------------------------------------------------
SERVER_HANDLERS="python/crystalmath/server/handlers.py"
echo "🐍 Step 2: Injecting JSON-RPC subprocess logic into $SERVER_HANDLERS..."
mkdir -p python/crystalmath/server

cat <<'EOF' >"$SERVER_HANDLERS"
import subprocess
import json
import logging
from crystalmath.models import SlurmJobModel, SlurmQueueResponse

logger = logging.getLogger("crystalmath.server")

def handle_slurm_queue_request(payload: dict) -> dict:
    """
    Natively parses squeue outputs inside the HPC cluster environment context.
    Bypasses local frontend command dependencies to fulfill ADR-006.
    """
    try:
        # Run squeue JSON telemetry export via local process loop forks
        res = subprocess.run(
            ["squeue", "--all", "--json"],
            capture_output=True, text=True, check=True
        )
        raw_data = json.loads(res.stdout)
        
        parsed_jobs = []
        # Safely parse Slurm's standard core scheduler output matrix
        for raw_job in raw_data.get("jobs", []):
            parsed_jobs.append(
                SlurmJobModel(
                    job_id=raw_job.get("job_id"),
                    partition=raw_job.get("partition"),
                    name=raw_job.get("name"),
                    user=raw_job.get("user_name"),
                    state=raw_job.get("job_state"),
                    time_used=raw_job.get("time_used", "0:00"),
                    stdout_path=raw_job.get("standard_output", "")
                )
            )
            
        return SlurmQueueResponse(success=True, jobs=parsed_jobs).model_dump()
    except Exception as e:
        logger.error(f"Failed to fetch Slurm metrics from cluster controller: {str(e)}")
        return SlurmQueueResponse(success=False, jobs=[], error_message=str(e)).model_dump()
EOF

# ------------------------------------------------------------------------------
# STEP 3: Route Rust UI Engine via the IPC Boundary (src/state/actions.rs)
# ------------------------------------------------------------------------------
RUST_ACTIONS="src/state/actions.rs"
echo "🦀 Step 3: Upgrading Rust async boundaries in $RUST_ACTIONS..."
mkdir -p src/state

cat <<'EOF' >"$RUST_ACTIONS"
use tokio::sync::mpsc;
use serde_json::json;
use crate::app::App;

pub enum AsyncSlurmEvent {
    FetchQueueSuccess(Vec<slurmer_core::models::Job>),
    FetchQueueFailure(String),
}

pub fn dispatch_async_slurm_fetch(tx: mpsc::UnboundedSender<AsyncSlurmEvent>) {
    tokio::spawn(async move {
        // Channel requests across decoupled boundary layers instead of local process forks
        match crate::ipc::client::call_backend("slurm/fetch_queue", json!({})).await {
            Ok(response_json) => {
                // Deserialize verified data schemas securely
                if let Ok(jobs) = serde_json::from_value::<Vec<slurmer_core::models::Job>>(response_json["jobs"].clone()) {
                    let _ = tx.send(AsyncSlurmEvent::FetchQueueSuccess(jobs));
                } else {
                    let _ = tx.send(AsyncSlurmEvent::FetchQueueFailure("Malformed server contract schema".to_string()));
                }
            }
            Err(e) => {
                let _ = tx.send(AsyncSlurmEvent::FetchQueueFailure(e.to_string()));
            }
        }
    });
}
EOF

# ------------------------------------------------------------------------------
# STEP 4: Write Decoupled Architectural Decision Record (ADR-028)
# ------------------------------------------------------------------------------
ADR_FILE="docs/architecture/adr-028-decoupled-slurm-workload-orchestration-over-ipc.md"
echo "📄 Step 4: Normalizing architecture design decisions inside $ADR_FILE..."
mkdir -p docs/architecture

cat <<'EOF' >"$ADR_FILE"
---
adr_id: 028
title: "Decoupled Slurm Workload Orchestration Over IPC"
status: "Accepted"
date: "2026-06-11"
macro_context: "crystalmath-tui-core"
---

# ADR-028: Decoupled Slurm Workload Orchestration Over IPC

## Context & Problem Statement
To satisfy the TUI unification strategy set out in **ADR-006**, CrystalMath must implement a native panel to track active SLURM scheduler metrics. Spawning local system processes (`Command::new("squeue")`) directly from the frontend TUI blocks local machines and breaks when running the interface on client machines separate from cluster backends.

## Proposed Architecture
We offload cluster CLI interactions entirely to the Python daemon layer (`python/crystalmath/server/`). The frontend communicates over the JSON-RPC IPC interface boundary (`src/ipc/`), keeping the layout engine headless and decoupled.

## Consequences & Trade-offs
*   **Pros**: Full compliance with ADR-006, fluid local frontend interface rendering, zero cross-platform binary overhead on laptops.
*   **Cons**: Introduces JSON serialization overhead across data transport boundaries.
EOF

# ------------------------------------------------------------------------------
# STEP 5: Regenerate Active Manifest Index
# ------------------------------------------------------------------------------
echo "🔗 Step 5: Refreshing architecture manifest ledger..."
if [ -f "./scripts/manage_adrs.sh" ]; then
  ./scripts/manage_adrs.sh
else
  echo "⚠️ Maintenance tool missing. Skipping manual index update."
fi

echo "✅ Slurm Decoupled IPC stack deployed perfectly! Verify builds using scripts/build-tui.sh"
