//! Prometheus HTTP API client for querying cluster metrics.
//!
//! Queries node_exporter, all-smi GPU exporter, and slurm_exporter
//! metrics via Prometheus instant query API.

use std::collections::HashMap;

use serde::Deserialize;
use thiserror::Error;

use crate::monitor::{GpuMetrics, NodeMetrics, SlurmClusterMetrics};

#[derive(Error, Debug)]
pub enum PrometheusError {
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("Prometheus API error: {0}")]
    Api(String),
    #[error("Parse error: {0}")]
    Parse(String),
}

// ===== Prometheus JSON response types =====

#[derive(Deserialize)]
struct PrometheusResponse {
    status: String,
    data: Option<PrometheusData>,
    #[serde(default)]
    error: Option<String>,
}

#[derive(Deserialize)]
struct PrometheusData {
    #[serde(rename = "resultType")]
    #[allow(dead_code)]
    result_type: String,
    result: Vec<InstantResult>,
}

#[derive(Deserialize)]
struct InstantResult {
    metric: HashMap<String, String>,
    value: (f64, String),
}

/// Parsed instant sample from a Prometheus query.
pub struct InstantSample {
    pub labels: HashMap<String, String>,
    pub value: f64,
}

// ===== Prometheus Client =====

pub struct PrometheusClient {
    client: reqwest::Client,
    base_url: String,
}

impl PrometheusClient {
    pub fn try_new() -> Result<Self, PrometheusError> {
        let base_url =
            std::env::var("PROMETHEUS_URL").unwrap_or_else(|_| "http://localhost:9090".to_string());
        let allow_insecure_tls = std::env::var("PROMETHEUS_INSECURE_TLS")
            .map(|value| matches!(value.to_ascii_lowercase().as_str(), "1" | "true" | "yes"))
            .unwrap_or(false);
        let builder = reqwest::Client::builder().timeout(std::time::Duration::from_secs(10));
        let builder = if allow_insecure_tls {
            builder.danger_accept_invalid_certs(true)
        } else {
            builder
        };
        let client = builder.build()?;
        Ok(Self { client, base_url })
    }

    /// Execute a PromQL instant query.
    pub async fn query(&self, promql: &str) -> Result<Vec<InstantSample>, PrometheusError> {
        let url = format!("{}/api/v1/query", self.base_url);
        let resp: PrometheusResponse = self
            .client
            .get(&url)
            .query(&[("query", promql)])
            .send()
            .await?
            .json()
            .await?;

        if resp.status != "success" {
            return Err(PrometheusError::Api(
                resp.error.unwrap_or_else(|| "unknown error".into()),
            ));
        }

        let data = resp
            .data
            .ok_or_else(|| PrometheusError::Parse("missing data field".into()))?;

        data.result
            .into_iter()
            .map(|r| {
                let value =
                    r.value.1.parse::<f64>().map_err(|e| {
                        PrometheusError::Parse(format!("invalid metric value: {}", e))
                    })?;
                Ok(InstantSample {
                    labels: r.metric,
                    value,
                })
            })
            .collect()
    }

    // Helper: extract hostname from instance label (strip port).
    fn hostname(instance: &str) -> String {
        instance.split(':').next().unwrap_or(instance).to_string()
    }

    /// Fetch GPU metrics from all-smi exporter.
    pub async fn fetch_gpu_metrics(&self) -> Result<Vec<GpuMetrics>, PrometheusError> {
        // Query all GPU metrics in parallel
        let (util, temp, power, mem_used, mem_total, freq) = tokio::try_join!(
            self.query("gpu_utilization"),
            self.query("gpu_temperature"),
            self.query("gpu_power_usage"),
            self.query("gpu_memory_used"),
            self.query("gpu_memory_total"),
            self.query("gpu_clock_speed"),
        )?;

        // Build lookup: (instance, gpu_index) -> partial GpuMetrics
        let mut map: HashMap<(String, u32), GpuMetrics> = HashMap::new();

        for sample in &util {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            let idx: u32 = sample
                .labels
                .get("gpu")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            let key = (instance.clone(), idx);
            let entry = map.entry(key).or_insert_with(|| GpuMetrics {
                node: Self::hostname(&instance),
                gpu_index: idx,
                ..Default::default()
            });
            entry.utilization_pct = sample.value;
        }

        for sample in &temp {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            let idx: u32 = sample
                .labels
                .get("gpu")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            if let Some(entry) = map.get_mut(&(instance, idx)) {
                entry.temperature_c = sample.value;
            }
        }

        for sample in &power {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            let idx: u32 = sample
                .labels
                .get("gpu")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            if let Some(entry) = map.get_mut(&(instance, idx)) {
                entry.power_watts = sample.value;
            }
        }

        for sample in &mem_used {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            let idx: u32 = sample
                .labels
                .get("gpu")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            if let Some(entry) = map.get_mut(&(instance, idx)) {
                // all-smi reports in MiB, convert to GB
                entry.memory_used_gb = sample.value / 1024.0;
            }
        }

        for sample in &mem_total {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            let idx: u32 = sample
                .labels
                .get("gpu")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            if let Some(entry) = map.get_mut(&(instance, idx)) {
                entry.memory_total_gb = sample.value / 1024.0;
            }
        }

        for sample in &freq {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            let idx: u32 = sample
                .labels
                .get("gpu")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            if let Some(entry) = map.get_mut(&(instance, idx)) {
                entry.frequency_mhz = sample.value;
            }
        }

        let mut result: Vec<GpuMetrics> = map.into_values().collect();
        result.sort_by(|a, b| (&a.node, a.gpu_index).cmp(&(&b.node, b.gpu_index)));
        Ok(result)
    }

    /// Fetch node metrics from node_exporter.
    pub async fn fetch_node_metrics(&self) -> Result<Vec<NodeMetrics>, PrometheusError> {
        let (
            cpu,
            load1,
            load5,
            load15,
            mem_avail,
            mem_total,
            disk_avail,
            disk_size,
            boot_time,
            time_now,
        ) = tokio::try_join!(
            self.query(
                r#"100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)"#
            ),
            self.query("node_load1"),
            self.query("node_load5"),
            self.query("node_load15"),
            self.query("node_memory_MemAvailable_bytes"),
            self.query("node_memory_MemTotal_bytes"),
            self.query(r#"node_filesystem_avail_bytes{mountpoint="/"}"#),
            self.query(r#"node_filesystem_size_bytes{mountpoint="/"}"#),
            self.query("node_boot_time_seconds"),
            self.query("node_time_seconds"),
        )?;

        let mut map: HashMap<String, NodeMetrics> = HashMap::new();

        for sample in &cpu {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            let host = Self::hostname(&instance);
            let entry = map.entry(instance).or_insert_with(|| NodeMetrics {
                hostname: host,
                ..Default::default()
            });
            entry.cpu_usage_pct = sample.value;
        }

        // Helper macro for simple field assignment
        macro_rules! fill_field {
            ($samples:expr, $field:ident, $transform:expr) => {
                for sample in &$samples {
                    let instance = sample.labels.get("instance").cloned().unwrap_or_default();
                    if let Some(entry) = map.get_mut(&instance) {
                        entry.$field = $transform(sample.value);
                    }
                }
            };
        }

        fill_field!(load1, load_1m, |v: f64| v);
        fill_field!(load5, load_5m, |v: f64| v);
        fill_field!(load15, load_15m, |v: f64| v);

        // Memory: available and total in bytes → GB
        for sample in &mem_total {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            if let Some(entry) = map.get_mut(&instance) {
                entry.memory_total_gb = sample.value / (1024.0 * 1024.0 * 1024.0);
            }
        }
        for sample in &mem_avail {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            if let Some(entry) = map.get_mut(&instance) {
                let avail_gb = sample.value / (1024.0 * 1024.0 * 1024.0);
                entry.memory_used_gb = entry.memory_total_gb - avail_gb;
            }
        }

        // Disk: avail and size in bytes → GB
        for sample in &disk_size {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            if let Some(entry) = map.get_mut(&instance) {
                entry.disk_total_gb = sample.value / (1024.0 * 1024.0 * 1024.0);
            }
        }
        for sample in &disk_avail {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            if let Some(entry) = map.get_mut(&instance) {
                let avail_gb = sample.value / (1024.0 * 1024.0 * 1024.0);
                entry.disk_used_gb = entry.disk_total_gb - avail_gb;
            }
        }

        // Uptime: now - boot_time
        let now_map: HashMap<String, f64> = time_now
            .iter()
            .map(|s| {
                let instance = s.labels.get("instance").cloned().unwrap_or_default();
                (instance, s.value)
            })
            .collect();
        for sample in &boot_time {
            let instance = sample.labels.get("instance").cloned().unwrap_or_default();
            if let Some(entry) = map.get_mut(&instance) {
                if let Some(&now) = now_map.get(&instance) {
                    entry.uptime_seconds = now - sample.value;
                }
            }
        }

        let mut result: Vec<NodeMetrics> = map.into_values().collect();
        result.sort_by(|a, b| a.hostname.cmp(&b.hostname));
        Ok(result)
    }

    /// Fetch SLURM cluster metrics from slurm_exporter.
    pub async fn fetch_slurm_metrics(&self) -> Result<SlurmClusterMetrics, PrometheusError> {
        let (
            cpus_idle,
            cpus_total,
            nodes_idle,
            nodes_alloc,
            nodes_down,
            nodes_drain,
            jobs_running,
            jobs_pending,
            mem_alloc,
            mem_total,
        ) = tokio::try_join!(
            self.query("slurm_cpus_idle"),
            self.query("slurm_cpus_total"),
            self.query("slurm_nodes_idle"),
            self.query("slurm_nodes_alloc"),
            self.query("slurm_nodes_down"),
            self.query("slurm_nodes_drain"),
            self.query("slurm_queue_running"),
            self.query("slurm_queue_pending"),
            self.query("slurm_mem_alloc"),
            self.query("slurm_mem_total"),
        )?;

        fn first_val(samples: &[InstantSample]) -> f64 {
            samples.first().map(|s| s.value).unwrap_or(0.0)
        }

        Ok(SlurmClusterMetrics {
            cpus_idle: first_val(&cpus_idle) as u64,
            cpus_total: first_val(&cpus_total) as u64,
            nodes_idle: first_val(&nodes_idle) as u64,
            nodes_alloc: first_val(&nodes_alloc) as u64,
            nodes_down: first_val(&nodes_down) as u64,
            nodes_drain: first_val(&nodes_drain) as u64,
            jobs_running: first_val(&jobs_running) as u64,
            jobs_pending: first_val(&jobs_pending) as u64,
            mem_alloc_gb: first_val(&mem_alloc) / 1024.0,
            mem_total_gb: first_val(&mem_total) / 1024.0,
        })
    }
}
