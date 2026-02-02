//! IPC client for JSON-RPC 2.0 communication with crystalmath-server.
//!
//! This module provides `IpcClient`, an async client that connects to the
//! Python crystalmath-server over Unix domain sockets and sends JSON-RPC 2.0
//! requests with automatic timeout handling.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use anyhow::Result;
use thiserror::Error;
use tokio::io::BufReader;
use tokio::net::unix::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::UnixStream;
use tokio::time::timeout;

use crate::bridge::{JsonRpcError, JsonRpcRequest, JsonRpcResponse};
use crate::ipc::framing::{read_message, write_message};

/// Default request timeout in seconds.
const DEFAULT_TIMEOUT_SECS: u64 = 30;

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

    /// Set the request timeout duration.
    ///
    /// Default is 30 seconds.
    #[allow(dead_code)]
    pub fn set_timeout(&mut self, timeout: Duration) {
        self.timeout = timeout;
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
