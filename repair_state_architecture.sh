#!/bin/bash
set -e

echo "=== 1. Restoring Original Application Architecture ==="
# Restore your native, full-featured App structures
git checkout src/app.rs

echo "=== 2. Patching Typo in Actions Layer ==="
# Fix the Python-style import typo
cat <<'EOF' >src/state/actions.rs
use serde::Deserialize;

/// Core events emitted from background workers, cluster processes, or IPC channels.
#[derive(Debug, Clone, PartialEq)]
pub enum AppBackendEvent {
    LogChunkReceived {
        job_id: u64,
        content: String,
    },
    SlurmQueueUpdated {
        raw_payload: String,
    },
    LspDiagnosticsReceived {
        uri: String,
        diagnostics: String,
    },
    ConnectionStatusChanged {
        connected: bool,
    },
}

/// High-frequency UI tick triggers to cleanly isolate user input checks from render events.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SystemInputEvent {
    Tick,
    KeyPress(crossterm::event::KeyEvent),
    Resize(u16, u16),
}
EOF

echo "=== 3. Resolving Workflow Results Borrow Mismatches ==="
# Fix the reference type mismatches in workflow results
sed -i '' 's/build_convergence_text(workflow_id, cache)/build_convergence_text(workflow_id, \&cache)/g' src/ui/workflow_results.rs
sed -i '' 's/build_eos_text(workflow_id, cache)/build_eos_text(workflow_id, \&cache)/g' src/ui/workflow_results.rs

echo "=== 4. Integrating Event Channel Handlers directly into your Native App Struct ==="
# Append safe event draining methods onto your genuine App struct in src/app.rs
cat <<'EOF' >>src/app.rs

// --- High-Performance Channel Extension ---
impl App {
    /// Non-blocking drain loop to process all available background tasks safely 
    /// within your native state cycle without blocking frame rendering.
    pub fn process_backend_queues(&mut self, rx: &std::sync::mpsc::Receiver<crate::state::actions::AppBackendEvent>) {
        while let Ok(event) = rx.try_recv() {
            match event {
                crate::state::actions::AppBackendEvent::LogChunkReceived { job_id, content } => {
                    // Update your log screen model natively
                    if self.log_view.current_job_id == Some(job_id) {
                        self.log_view.append_line(content);
                    }
                }
                crate::state::actions::AppBackendEvent::SlurmQueueUpdated { raw_payload } => {
                    // Inject updates straight into your active slurm tab view models
                    self.slurm_queue_state.raw_data = raw_payload;
                }
                crate::state::actions::AppBackendEvent::ConnectionStatusChanged { connected } => {
                    self.network_connected = connected;
                }
                crate::state::actions::AppBackendEvent::LspDiagnosticsReceived { .. } => {
                    // Hook into your editor diagnostic layer here
                }
            }
        }
    }
}
EOF

echo "=== 5. Verifying Clean Compilation State ==="
cargo clippy --all-targets
