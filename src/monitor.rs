//! Monitor tab state and data types for Prometheus metrics display.
//!
//! Uses `std::sync::mpsc` channel pattern (same as LSP integration)
//! with a background `std::thread` owning a `tokio::Runtime` for async HTTP.

use std::collections::VecDeque;
use std::sync::mpsc::{self, Receiver, Sender};

use ratatui::style::Color;
use tokio::sync::watch;

use crate::prometheus::PrometheusClient;

// ===== Sub-View Navigation =====

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MonitorSubView {
    GpuOverview,
    NodeHealth,
    SlurmStatus,
}

impl MonitorSubView {
    pub fn next(&self) -> Self {
        match self {
            Self::GpuOverview => Self::NodeHealth,
            Self::NodeHealth => Self::SlurmStatus,
            Self::SlurmStatus => Self::GpuOverview,
        }
    }

    pub fn prev(&self) -> Self {
        match self {
            Self::GpuOverview => Self::SlurmStatus,
            Self::NodeHealth => Self::GpuOverview,
            Self::SlurmStatus => Self::NodeHealth,
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            Self::GpuOverview => "GPU",
            Self::NodeHealth => "Nodes",
            Self::SlurmStatus => "SLURM",
        }
    }

    pub fn all() -> &'static [Self] {
        &[Self::GpuOverview, Self::NodeHealth, Self::SlurmStatus]
    }
}

// ===== Metric Data Types =====

#[derive(Debug, Clone, Default)]
pub struct GpuMetrics {
    pub node: String,
    pub gpu_index: u32,
    pub utilization_pct: f64,
    pub temperature_c: f64,
    pub power_watts: f64,
    pub power_limit_watts: f64,
    pub memory_used_gb: f64,
    pub memory_total_gb: f64,
    pub frequency_mhz: f64,
    pub utilization_history: VecDeque<u64>,
}

#[derive(Debug, Clone, Default)]
pub struct NodeMetrics {
    pub hostname: String,
    pub cpu_usage_pct: f64,
    pub load_1m: f64,
    pub load_5m: f64,
    pub load_15m: f64,
    pub memory_used_gb: f64,
    pub memory_total_gb: f64,
    pub disk_used_gb: f64,
    pub disk_total_gb: f64,
    pub uptime_seconds: f64,
    pub cpu_history: VecDeque<u64>,
    pub memory_history: VecDeque<u64>,
}

#[derive(Debug, Clone, Default)]
pub struct SlurmClusterMetrics {
    pub cpus_idle: u64,
    pub cpus_total: u64,
    pub nodes_idle: u64,
    pub nodes_alloc: u64,
    pub nodes_down: u64,
    pub nodes_drain: u64,
    pub jobs_running: u64,
    pub jobs_pending: u64,
    pub mem_alloc_gb: f64,
    pub mem_total_gb: f64,
}

// ===== Channel Messages =====

pub enum MonitorMessage {
    GpuUpdate(Vec<GpuMetrics>),
    NodeUpdate(Vec<NodeMetrics>),
    SlurmUpdate(SlurmClusterMetrics),
    Error(String),
    Connected,
}

// ===== Monitor State =====

#[allow(dead_code)] // Used from app.rs in binary crate
pub(crate) const SPARKLINE_HISTORY_LEN: usize = 60;

pub struct MonitorState {
    pub sub_view: MonitorSubView,
    pub gpu_metrics: Vec<GpuMetrics>,
    pub node_metrics: Vec<NodeMetrics>,
    pub slurm_metrics: Option<SlurmClusterMetrics>,
    pub last_gpu_update: Option<std::time::Instant>,
    pub last_node_update: Option<std::time::Instant>,
    pub last_slurm_update: Option<std::time::Instant>,
    pub error: Option<String>,
    pub connected: bool,
    pub selected_index: usize,
    pub receiver: Option<Receiver<MonitorMessage>>,
    shutdown_tx: Option<watch::Sender<bool>>,
    polling_active: bool,
}

impl Default for MonitorState {
    fn default() -> Self {
        Self::new()
    }
}

impl MonitorState {
    pub fn new() -> Self {
        Self {
            sub_view: MonitorSubView::GpuOverview,
            gpu_metrics: Vec::new(),
            node_metrics: Vec::new(),
            slurm_metrics: None,
            last_gpu_update: None,
            last_node_update: None,
            last_slurm_update: None,
            error: None,
            connected: false,
            selected_index: 0,
            receiver: None,
            shutdown_tx: None,
            polling_active: false,
        }
    }

    pub fn select_next(&mut self) {
        let len = match self.sub_view {
            MonitorSubView::GpuOverview => self.gpu_metrics.len(),
            MonitorSubView::NodeHealth => self.node_metrics.len(),
            MonitorSubView::SlurmStatus => 1, // single view
        };
        if len > 0 {
            self.selected_index = (self.selected_index + 1).min(len - 1);
        }
    }

    pub fn select_prev(&mut self) {
        self.selected_index = self.selected_index.saturating_sub(1);
    }

    /// Start background polling thread. Returns Some(()) if newly started.
    pub fn start_polling(&mut self) -> Option<()> {
        if self.polling_active {
            return None;
        }
        let (tx, rx) = mpsc::channel();
        let (shutdown_tx, shutdown_rx) = watch::channel(false);
        self.receiver = Some(rx);
        self.shutdown_tx = Some(shutdown_tx);
        self.polling_active = true;

        std::thread::spawn(move || {
            let rt = tokio::runtime::Runtime::new().expect("Failed to create tokio runtime");
            rt.block_on(poll_loop(tx, shutdown_rx));
        });

        Some(())
    }

    /// Stop background polling and close the current receiver.
    pub fn stop_polling(&mut self) {
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(true);
        }
        self.polling_active = false;
        self.receiver = None;
    }

    /// Force refresh: stop old pollers and start new ones.
    pub fn force_refresh(&mut self) {
        self.stop_polling();
        self.error = None;
        self.connected = false;
        self.start_polling();
    }

    /// Returns time since last update for the current sub-view.
    pub fn last_update_age(&self) -> Option<std::time::Duration> {
        let instant = match self.sub_view {
            MonitorSubView::GpuOverview => self.last_gpu_update,
            MonitorSubView::NodeHealth => self.last_node_update,
            MonitorSubView::SlurmStatus => self.last_slurm_update,
        };
        instant.map(|t| t.elapsed())
    }
}

impl Drop for MonitorState {
    fn drop(&mut self) {
        self.stop_polling();
    }
}

// ===== Threshold Colors =====

pub fn threshold_color(value: f64, warn: f64, crit: f64) -> Color {
    if value >= crit {
        Color::Red
    } else if value >= warn {
        Color::Yellow
    } else {
        Color::Green
    }
}

/// Inverse threshold: low values are bad (e.g., free resources).
#[allow(dead_code)]
pub fn threshold_color_inverse(value: f64, warn: f64, crit: f64) -> Color {
    if value <= crit {
        Color::Red
    } else if value <= warn {
        Color::Yellow
    } else {
        Color::Green
    }
}

// ===== Background Polling =====

async fn poll_loop(tx: Sender<MonitorMessage>, shutdown: watch::Receiver<bool>) {
    use std::sync::Arc;

    let client = Arc::new(PrometheusClient::new());
    let connected = Arc::new(std::sync::atomic::AtomicBool::new(false));

    // GPU poll task (every 10s)
    let gpu_handle = {
        let tx = tx.clone();
        let client = Arc::clone(&client);
        let connected = Arc::clone(&connected);
        let mut shutdown = shutdown.clone();
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = shutdown.changed() => break,
                    result = client.fetch_gpu_metrics() => match result {
                    Ok(metrics) => {
                        if !connected.swap(true, std::sync::atomic::Ordering::Relaxed) {
                            let _ = tx.send(MonitorMessage::Connected);
                        }
                        let _ = tx.send(MonitorMessage::GpuUpdate(metrics));
                    }
                    Err(e) => {
                        let _ = tx.send(MonitorMessage::Error(format!("GPU: {}", e)));
                    }
                    }
                }
                tokio::select! {
                    _ = shutdown.changed() => break,
                    _ = tokio::time::sleep(std::time::Duration::from_secs(10)) => {}
                }
            }
        })
    };

    // Node poll task (every 30s)
    let node_handle = {
        let tx = tx.clone();
        let client = Arc::clone(&client);
        let connected = Arc::clone(&connected);
        let mut shutdown = shutdown.clone();
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = shutdown.changed() => break,
                    result = client.fetch_node_metrics() => match result {
                    Ok(metrics) => {
                        if !connected.swap(true, std::sync::atomic::Ordering::Relaxed) {
                            let _ = tx.send(MonitorMessage::Connected);
                        }
                        let _ = tx.send(MonitorMessage::NodeUpdate(metrics));
                    }
                    Err(e) => {
                        let _ = tx.send(MonitorMessage::Error(format!("Nodes: {}", e)));
                    }
                    }
                }
                tokio::select! {
                    _ = shutdown.changed() => break,
                    _ = tokio::time::sleep(std::time::Duration::from_secs(30)) => {}
                }
            }
        })
    };

    // SLURM poll task (every 30s)
    let slurm_handle = {
        let client = Arc::clone(&client);
        let connected = Arc::clone(&connected);
        let mut shutdown = shutdown.clone();
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = shutdown.changed() => break,
                    result = client.fetch_slurm_metrics() => match result {
                    Ok(metrics) => {
                        if !connected.swap(true, std::sync::atomic::Ordering::Relaxed) {
                            let _ = tx.send(MonitorMessage::Connected);
                        }
                        let _ = tx.send(MonitorMessage::SlurmUpdate(metrics));
                    }
                    Err(e) => {
                        let _ = tx.send(MonitorMessage::Error(format!("SLURM: {}", e)));
                    }
                    }
                }
                tokio::select! {
                    _ = shutdown.changed() => break,
                    _ = tokio::time::sleep(std::time::Duration::from_secs(30)) => {}
                }
            }
        })
    };

    // Wait for all (they loop forever, so this blocks indefinitely)
    let _ = tokio::join!(gpu_handle, node_handle, slurm_handle);
}

/// Push to sparkline history with bounded length.
#[allow(dead_code)] // Used from app.rs in binary crate
pub(crate) fn push_history(history: &mut VecDeque<u64>, value: u64) {
    history.push_back(value);
    if history.len() > SPARKLINE_HISTORY_LEN {
        history.pop_front();
    }
}
