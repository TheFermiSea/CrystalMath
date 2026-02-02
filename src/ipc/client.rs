//! IPC client for JSON-RPC 2.0 communication with crystalmath-server.
//!
//! This module provides `IpcClient`, an async client that connects to the
//! Python crystalmath-server over Unix domain sockets and sends JSON-RPC 2.0
//! requests with automatic timeout handling.
//!
//! # Auto-start
//!
//! The module includes `ensure_server_running()` to automatically start
//! the Python server if it's not already running. This enables zero-config
//! user experience for the TUI.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use thiserror::Error;
use tokio::io::BufReader;
use tokio::net::unix::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::UnixStream;
use tokio::time::timeout;

use crate::bridge::{JsonRpcError, JsonRpcRequest, JsonRpcResponse};
use crate::ipc::framing::{read_message, write_message};

/// Default request timeout in seconds.
const DEFAULT_TIMEOUT_SECS: u64 = 30;

/// Maximum time to wait for server startup in seconds.
const SERVER_STARTUP_TIMEOUT_SECS: u64 = 5;

/// Polling interval when waiting for server socket.
const SERVER_POLL_INTERVAL_MS: u64 = 100;

/// IPC-specific error types.
///
/// These errors provide actionable messages for common failure modes
/// when communicating with the crystalmath-server.
#[derive(Debug, Error)]
pub enum IpcError {
    /// Failed to connect to the server socket.
    #[error("Connection failed: {0}")]
    ConnectionFailed(#[source] std::io::Error),

    /// Request timed out waiting for response.
    #[error("Request timed out after {0}s")]
    Timeout(u64),

    /// Protocol-level error (framing, encoding).
    #[error("Protocol error: {0}")]
    Protocol(String),

    /// Server returned a JSON-RPC error response.
    #[error("Server error {code}: {message}")]
    ServerError {
        /// JSON-RPC error code
        code: i32,
        /// Error message
        message: String,
        /// Optional additional data
        data: Option<serde_json::Value>,
    },

    /// I/O error during communication.
    #[error("I/O error: {0}")]
    Io(#[source] std::io::Error),
}

impl From<std::io::Error> for IpcError {
    fn from(err: std::io::Error) -> Self {
        match err.kind() {
            std::io::ErrorKind::NotFound | std::io::ErrorKind::ConnectionRefused => {
                IpcError::ConnectionFailed(err)
            }
            _ => IpcError::Io(err),
        }
    }
}

impl From<JsonRpcError> for IpcError {
    fn from(err: JsonRpcError) -> Self {
        IpcError::ServerError {
            code: err.code,
            message: err.message,
            data: err.data,
        }
    }
}

/// Resolve the default socket path for crystalmath-server.
///
/// Resolution order:
/// 1. `$XDG_RUNTIME_DIR/crystalmath.sock` (Linux standard)
/// 2. `~/Library/Caches/crystalmath.sock` (macOS)
/// 3. `/tmp/crystalmath.sock` (fallback)
///
/// # Example
///
/// ```ignore
/// let socket_path = default_socket_path();
/// let client = IpcClient::connect(&socket_path).await?;
/// ```
pub fn default_socket_path() -> PathBuf {
    // Try XDG_RUNTIME_DIR first (Linux standard, per-user)
    if let Ok(runtime_dir) = std::env::var("XDG_RUNTIME_DIR") {
        return PathBuf::from(runtime_dir).join("crystalmath.sock");
    }

    // macOS: Use ~/Library/Caches for user-specific socket
    if let Some(cache_dir) = dirs::cache_dir() {
        return cache_dir.join("crystalmath.sock");
    }

    // Fallback to /tmp (less secure, but works everywhere)
    PathBuf::from("/tmp/crystalmath.sock")
}

/// Ensures the crystalmath-server is running, starting it if necessary.
///
/// This function implements the zero-config experience for the TUI:
/// 1. If the server is already running (socket accepts connections), returns immediately
/// 2. If a stale socket exists (connection refused), removes it and starts the server
/// 3. If no socket exists, starts the server and waits for it to be ready
///
/// # Arguments
///
/// * `socket_path` - Path where the server socket should be created
///
/// # Errors
///
/// Returns an error if:
/// - The server process cannot be spawned (e.g., `crystalmath-server` not in PATH)
/// - The server fails to start within the timeout (5 seconds)
/// - An unexpected I/O error occurs
///
/// # Example
///
/// ```ignore
/// let socket_path = default_socket_path();
/// ensure_server_running(&socket_path)?;
/// let mut client = IpcClient::connect(&socket_path).await?;
/// ```
pub fn ensure_server_running(socket_path: &Path) -> Result<()> {
    // Fast path: try connecting first (server already running)
    match std::os::unix::net::UnixStream::connect(socket_path) {
        Ok(_) => {
            tracing::debug!("Server already running at {:?}", socket_path);
            return Ok(());
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            // Socket doesn't exist - server not running
            tracing::debug!("Socket not found, will start server");
        }
        Err(e) if e.kind() == std::io::ErrorKind::ConnectionRefused => {
            // Stale socket - server crashed, clean it up
            tracing::info!("Cleaning up stale socket at {:?}", socket_path);
            let _ = std::fs::remove_file(socket_path);
        }
        Err(e) => {
            return Err(anyhow!("Failed to check server status: {}", e));
        }
    }

    // Server not running - spawn it
    tracing::info!("Starting crystalmath-server...");
    let _child = Command::new("crystalmath-server")
        .arg("--socket")
        .arg(socket_path)
        .stdout(Stdio::null())
        .stderr(Stdio::piped()) // Pipe stderr for debugging if needed
        .spawn()
        .context("Failed to start crystalmath-server. Is it installed? (uv pip install -e python/)")?;

    // Wait for socket to appear (max 5 seconds)
    let max_polls = (SERVER_STARTUP_TIMEOUT_SECS * 1000) / SERVER_POLL_INTERVAL_MS;
    for i in 0..max_polls {
        if socket_path.exists() {
            // Socket exists - give server a moment to start accepting connections
            std::thread::sleep(Duration::from_millis(SERVER_POLL_INTERVAL_MS));
            tracing::info!(
                "Server started after {}ms",
                (i + 1) * SERVER_POLL_INTERVAL_MS
            );
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(SERVER_POLL_INTERVAL_MS));
    }

    Err(anyhow!(
        "Server failed to start within {} seconds. Check that crystalmath-server is installed.",
        SERVER_STARTUP_TIMEOUT_SECS
    ))
}

/// IPC client for communication with crystalmath-server.
///
/// The client maintains a persistent connection to the server and provides
/// async methods for sending JSON-RPC 2.0 requests. All requests include
/// automatic timeout handling to prevent the TUI from hanging.
///
/// # Connection Lifecycle
///
/// - `connect()` - Establish initial connection
/// - `connect_with_retry()` - Retry connection with exponential backoff
/// - `call()` - Send request and wait for response (with timeout)
///
/// # Example
///
/// ```ignore
/// use crystalmath_tui::ipc::IpcClient;
/// use serde_json::json;
///
/// let mut client = IpcClient::connect("/tmp/crystalmath.sock").await?;
///
/// // Simple request
/// let jobs = client.call("jobs.list", json!({})).await?;
///
/// // Request with parameters
/// let job = client.call("jobs.get", json!({"pk": 42})).await?;
/// ```
pub struct IpcClient {
    /// Buffered reader for incoming messages.
    reader: BufReader<OwnedReadHalf>,
    /// Writer for outgoing messages.
    writer: OwnedWriteHalf,
    /// Monotonically increasing request ID counter.
    request_id: AtomicU64,
    /// Request timeout duration.
    timeout: Duration,
}

impl IpcClient {
    /// Connect to the crystalmath-server at the given socket path.
    ///
    /// # Errors
    ///
    /// Returns `IpcError::ConnectionFailed` if:
    /// - The socket file does not exist
    /// - Connection is refused (server not running)
    /// - Permission denied
    ///
    /// # Example
    ///
    /// ```ignore
    /// let client = IpcClient::connect("/tmp/crystalmath.sock").await?;
    /// ```
    pub async fn connect(socket_path: &Path) -> Result<Self, IpcError> {
        let stream = UnixStream::connect(socket_path)
            .await
            .map_err(IpcError::ConnectionFailed)?;

        let (read_half, write_half) = stream.into_split();

        Ok(Self {
            reader: BufReader::new(read_half),
            writer: write_half,
            request_id: AtomicU64::new(1),
            timeout: Duration::from_secs(DEFAULT_TIMEOUT_SECS),
        })
    }

    /// Connect with automatic retry and exponential backoff.
    ///
    /// Useful for TUI startup when the server may need time to initialize.
    /// Retries with delays of 100ms, 200ms, 400ms, etc.
    ///
    /// # Arguments
    ///
    /// * `socket_path` - Path to the Unix domain socket
    /// * `max_attempts` - Maximum number of connection attempts
    ///
    /// # Errors
    ///
    /// Returns the last connection error if all attempts fail.
    ///
    /// # Example
    ///
    /// ```ignore
    /// // Try up to 5 times with backoff
    /// let client = IpcClient::connect_with_retry(&socket_path, 5).await?;
    /// ```
    pub async fn connect_with_retry(socket_path: &Path, max_attempts: u32) -> Result<Self, IpcError> {
        let mut last_error = None;

        for attempt in 1..=max_attempts {
            match Self::connect(socket_path).await {
                Ok(client) => return Ok(client),
                Err(e) => {
                    last_error = Some(e);
                    if attempt < max_attempts {
                        // Exponential backoff: 100ms, 200ms, 400ms, ...
                        let delay = Duration::from_millis(100 * (1 << (attempt - 1)));
                        tokio::time::sleep(delay).await;
                    }
                }
            }
        }

        Err(last_error.expect("max_attempts must be > 0"))
    }

    /// Connect to the server, starting it if necessary.
    ///
    /// This is the recommended entry point for TUI startup. It:
    /// 1. Ensures the server is running via `ensure_server_running()`
    /// 2. Connects with retry to handle race conditions during startup
    ///
    /// # Arguments
    ///
    /// * `socket_path` - Path to the Unix domain socket
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - The server cannot be started
    /// - Connection fails after server is started
    ///
    /// # Example
    ///
    /// ```ignore
    /// let socket_path = default_socket_path();
    /// let mut client = IpcClient::connect_or_start(&socket_path).await?;
    /// let latency = client.ping().await?;
    /// println!("Server is responsive, latency: {:?}", latency);
    /// ```
    pub async fn connect_or_start(socket_path: &Path) -> Result<Self, IpcError> {
        ensure_server_running(socket_path).map_err(|e| {
            IpcError::Protocol(format!("Failed to start server: {}", e))
        })?;
        Self::connect_with_retry(socket_path, 5).await
    }

    /// Set the request timeout duration.
    ///
    /// Default is 30 seconds.
    #[allow(dead_code)]
    pub fn set_timeout(&mut self, timeout: Duration) {
        self.timeout = timeout;
    }

    /// Check if the server is responsive via system.ping.
    ///
    /// This is useful for:
    /// - Health checks after connection
    /// - Verifying the server is processing requests
    /// - Measuring roundtrip latency
    ///
    /// # Returns
    ///
    /// Returns the roundtrip duration on success.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - The server doesn't respond within timeout
    /// - The response format is invalid
    ///
    /// # Example
    ///
    /// ```ignore
    /// let latency = client.ping().await?;
    /// if latency > Duration::from_millis(100) {
    ///     tracing::warn!("Server latency is high: {:?}", latency);
    /// }
    /// ```
    pub async fn ping(&mut self) -> Result<Duration, IpcError> {
        let start = std::time::Instant::now();
        let result = self.call("system.ping", serde_json::json!({})).await?;

        // Verify response structure
        if result.get("pong").and_then(|v| v.as_bool()) != Some(true) {
            return Err(IpcError::Protocol(format!(
                "Invalid ping response: expected {{\"pong\": true}}, got {:?}",
                result
            )));
        }

        Ok(start.elapsed())
    }

    /// Send a JSON-RPC 2.0 request and wait for the response.
    ///
    /// This method:
    /// 1. Builds a JSON-RPC 2.0 request with auto-incremented ID
    /// 2. Serializes and sends with Content-Length framing
    /// 3. Waits for response (with timeout)
    /// 4. Parses response and extracts result or error
    ///
    /// # Arguments
    ///
    /// * `method` - The RPC method name (e.g., "jobs.list")
    /// * `params` - Method parameters as JSON value
    ///
    /// # Errors
    ///
    /// Returns error if:
    /// - Request times out (`IpcError::Timeout`)
    /// - Connection is lost (`IpcError::Io`)
    /// - Server returns error (`IpcError::ServerError`)
    /// - Protocol error (`IpcError::Protocol`)
    ///
    /// # Example
    ///
    /// ```ignore
    /// let result = client.call("jobs.list", json!({"limit": 100})).await?;
    /// let jobs: Vec<JobStatus> = serde_json::from_value(result)?;
    /// ```
    pub async fn call(
        &mut self,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value, IpcError> {
        let id = self.next_id();
        let request = JsonRpcRequest::new(method, params, id);

        // Apply timeout to the entire send/receive operation
        let result = timeout(self.timeout, self.send_receive(&request)).await;

        match result {
            Ok(Ok(response)) => self.process_response(response),
            Ok(Err(e)) => Err(e),
            Err(_) => Err(IpcError::Timeout(self.timeout.as_secs())),
        }
    }

    /// Generate the next request ID.
    fn next_id(&self) -> u64 {
        self.request_id.fetch_add(1, Ordering::Relaxed)
    }

    /// Send a request and receive the response (internal, no timeout).
    async fn send_receive(&mut self, request: &JsonRpcRequest) -> Result<JsonRpcResponse, IpcError> {
        // Serialize request
        let request_json = serde_json::to_string(request)
            .map_err(|e| IpcError::Protocol(format!("Failed to serialize request: {}", e)))?;

        // Send with framing
        write_message(&mut self.writer, &request_json)
            .await
            .map_err(|e| IpcError::Protocol(format!("Failed to send request: {}", e)))?;

        // Read response
        let response_json = read_message(&mut self.reader)
            .await
            .map_err(|e| IpcError::Protocol(format!("Failed to read response: {}", e)))?;

        // Deserialize response
        let response: JsonRpcResponse = serde_json::from_str(&response_json)
            .map_err(|e| IpcError::Protocol(format!("Failed to parse response: {}", e)))?;

        Ok(response)
    }

    /// Process a JSON-RPC response, extracting result or error.
    fn process_response(
        &self,
        response: JsonRpcResponse,
    ) -> Result<serde_json::Value, IpcError> {
        // Check for JSON-RPC error
        if let Some(err) = response.error {
            return Err(IpcError::ServerError {
                code: err.code,
                message: err.message,
                data: err.data,
            });
        }

        // Extract result
        response
            .result
            .ok_or_else(|| IpcError::Protocol("Response missing both result and error".to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_socket_path_format() {
        let path = default_socket_path();

        // Should be a valid path
        assert!(path.is_absolute() || path.starts_with("/tmp"));

        // Should have the expected filename pattern
        let filename = path.file_name().unwrap().to_str().unwrap();
        assert!(
            filename == "crystalmath.sock" || filename.starts_with("crystalmath-"),
            "Unexpected socket filename: {}",
            filename
        );
    }

    #[test]
    fn test_ipc_error_display() {
        let timeout_err = IpcError::Timeout(30);
        assert_eq!(timeout_err.to_string(), "Request timed out after 30s");

        let server_err = IpcError::ServerError {
            code: -32000,
            message: "Database error".to_string(),
            data: None,
        };
        assert_eq!(server_err.to_string(), "Server error -32000: Database error");

        let protocol_err = IpcError::Protocol("Invalid JSON".to_string());
        assert_eq!(protocol_err.to_string(), "Protocol error: Invalid JSON");
    }

    #[test]
    fn test_ipc_error_from_io() {
        let not_found = std::io::Error::new(std::io::ErrorKind::NotFound, "not found");
        let ipc_err: IpcError = not_found.into();
        assert!(matches!(ipc_err, IpcError::ConnectionFailed(_)));

        let refused = std::io::Error::new(std::io::ErrorKind::ConnectionRefused, "refused");
        let ipc_err: IpcError = refused.into();
        assert!(matches!(ipc_err, IpcError::ConnectionFailed(_)));

        let other = std::io::Error::new(std::io::ErrorKind::Other, "other");
        let ipc_err: IpcError = other.into();
        assert!(matches!(ipc_err, IpcError::Io(_)));
    }

    #[test]
    fn test_ipc_error_from_json_rpc() {
        use crate::bridge::JsonRpcError;

        let json_err = JsonRpcError {
            code: -32601,
            message: "Method not found".to_string(),
            data: Some(serde_json::json!({"method": "unknown"})),
        };

        let ipc_err: IpcError = json_err.into();
        match ipc_err {
            IpcError::ServerError { code, message, data } => {
                assert_eq!(code, -32601);
                assert_eq!(message, "Method not found");
                assert!(data.is_some());
            }
            _ => panic!("Expected ServerError"),
        }
    }
}
