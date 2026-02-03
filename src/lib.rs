//! CrystalMath TUI Library
//!
//! This library provides the core components for the CrystalMath TUI:
//!
//! - `ipc` - IPC client for communication with crystalmath-server
//! - `bridge` - JSON-RPC types and utilities for IPC communication
//! - `models` - Data models shared between Rust and Python
//!
//! # IPC Module
//!
//! The `ipc` module is the recommended way to communicate with the
//! Python backend:
//!
//! ```ignore
//! use crystalmath_tui::ipc::{IpcClient, ensure_server_running, default_socket_path};
//!
//! let socket = default_socket_path();
//! ensure_server_running(&socket)?;
//! let mut client = IpcClient::connect(&socket).await?;
//! let result = client.call("system.ping", serde_json::json!({})).await?;
//! ```

pub mod bridge;
pub mod ipc;
pub mod models;
