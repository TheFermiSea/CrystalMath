#!/bin/bash
set -e

echo "=== Injecting Decoupled Event-Routing Architecture ==="

# 1. Generate the centralized event types and asynchronous thread coordinator
mkdir -p src/state
cat << 'EOF' > src/state/actions.rs
import serde::Deserialize;

/// Core events emitted from background workers, cluster processes, or LSP channels.
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

# 2. Re-architect src/app.rs to employ a strict non-blocking mpsc processing loop
cat << 'EOF' > src/app.rs
use std::sync::mpsc::{channel, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant};
use crate::state::actions::{AppBackendEvent, SystemInputEvent};

pub struct AppState {
    pub current_job_id: Option<u64>,
    pub live_log_buffer: Vec<String>,
    pub slurm_status: String,
    pub is_connected: bool,
    pub should_quit: bool,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            current_job_id: None,
            live_log_buffer: Vec::with_capacity(1000),
            slurm_status: String::from("No Data"),
            is_connected: false,
            should_quit: false,
        }
    }

    /// Mutates the main application state exclusively within the UI thread boundary.
    /// This removes internal resource contention and completely avoids locking bottlenecks.
    pub fn handle_backend_event(&mut self, event: AppBackendEvent) {
        match event {
            AppBackendEvent::LogChunkReceived { job_id, content } => {
                if self.current_job_id == Some(job_id) {
                    self.live_log_buffer.push(content);
                }
            }
            AppBackendEvent::SlurmQueueUpdated { raw_payload } => {
                self.slurm_status = raw_payload;
            }
            AppBackendEvent::ConnectionStatusChanged { connected } => {
                self.is_connected = connected;
            }
            AppBackendEvent::LspDiagnosticsReceived { .. } => {
                // Handle inbound code syntax diagnostics here
            }
        }
    }
}

pub struct CoreEngineRuntime {
    pub state: AppState,
    pub backend_rx: Receiver<AppBackendEvent>,
    pub input_rx: Receiver<SystemInputEvent>,
}

impl CoreEngineRuntime {
    pub fn new(backend_rx: Receiver<AppBackendEvent>, input_rx: Receiver<SystemInputEvent>) -> Self {
        Self {
            state: AppState::new(),
            backend_rx,
            input_rx,
        }
    }

    /// Drives the primary lifecycle loop. Consumes all queued background signals 
    /// completely prior to starting the next frame layout step.
    pub fn process_event_queues(&mut self) {
        // Drain all background events immediately ready for consumption
        while let Ok(backend_evt) = self.backend_rx.try_recv() {
            self.state.handle_backend_event(backend_evt);
        }
    }
}

/// Spawns a dedicated asynchronous runtime worker thread to manage raw background I/O operations.
/// Prevents disk access delays or TCP wait states from dropping frame rates.
pub fn spawn_background_worker(tx: Sender<AppBackendEvent>) {
    thread::spawn(move || {
        // Simulation of high-frequency cluster monitoring or network socket loop
        loop {
            thread::sleep(Duration::from_millis(250));
            
            // Example: Poll SLURM or read IPC stream safely outside UI space
            let mock_poll = String::from("JOBID PARTITION NAME USER STATE TIME");
            if tx.send(AppBackendEvent::SlurmQueueUpdated { raw_payload: mock_poll }).is_err() {
                break; // Exit loop if the main receiver dropped out
            }
        }
    });
}
EOF

echo "✅ Decoupled event-routing and app runtime layers generated."
