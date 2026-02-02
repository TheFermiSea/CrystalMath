//! IPC client for communication with crystalmath-server.
//!
//! This module provides the Rust-side IPC boundary for communicating with
//! the Python crystalmath-server over Unix domain sockets using JSON-RPC 2.0.
//!
//! # Architecture
//!
//! The IPC layer replaces the PyO3 bridge with a cleaner process boundary:
//!
//! ```text
//! ┌─────────────────┐         Unix Socket          ┌─────────────────────┐
//! │   Rust TUI      │  ◄──────────────────────────►│ crystalmath-server  │
//! │   (IpcClient)   │    JSON-RPC 2.0 + framing    │     (Python)        │
//! └─────────────────┘                              └─────────────────────┘
//! ```
//!
//! # Protocol
//!
//! Messages use HTTP-style Content-Length framing (same as LSP):
//!
//! ```text
//! Content-Length: 47\r\n
//! \r\n
//! {"jsonrpc":"2.0","method":"system.ping","id":1}
//! ```
//!
//! # Usage
//!
//! ```ignore
//! use crystalmath_tui::ipc::IpcClient;
//! use serde_json::json;
//!
//! let mut client = IpcClient::connect("/tmp/crystalmath.sock").await?;
//! let result = client.call("jobs.list", json!({})).await?;
//! ```

mod client;
mod framing;

pub use client::{default_socket_path, ensure_server_running, IpcClient, IpcError};
pub use framing::{read_message, write_message};
