//! LSP Client for dft-language-server integration.
//!
//! Provides real-time validation for CRYSTAL23 and VASP input files
//! by communicating with the dft-language-server via JSON-RPC over stdio.

use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicI32, Ordering};
use std::sync::mpsc::Sender;
use std::sync::Arc;
use std::thread;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;
use tracing::{debug, error, info, warn};
use url::Url;

// =============================================================================
// Helper Functions
// =============================================================================

/// Construct an LSP JSON-RPC notification (no id field).
///
/// This helper centralizes notification construction to avoid duplication
/// across inherent methods and trait implementations.
fn make_notification(method: &str, params: serde_json::Value) -> serde_json::Value {
    json!({
        "jsonrpc": "2.0",
        "method": method,
        "params": params
    })
}

// =============================================================================
// Service Trait for Dependency Injection
// =============================================================================

/// Trait for LSP client operations.
///
/// This trait abstracts the LSP client to enable:
/// - Dependency injection for testing with mock implementations
/// - Separation of interface from implementation
/// - Easier testing without spawning a real LSP server
pub trait LspService {
    /// Send the initialized notification (required after initialize response).
    fn send_initialized(&mut self) -> anyhow::Result<()>;

    /// Notify the server that a document was opened.
    fn did_open(&mut self, file_path: &str, text: &str) -> anyhow::Result<()>;

    /// Notify the server that a document changed.
    fn did_change(&mut self, file_path: &str, version: i32, text: &str) -> anyhow::Result<()>;

    /// Notify the server that a document was closed.
    fn did_close(&mut self, file_path: &str) -> anyhow::Result<()>;
}

/// Supported DFT code types for language detection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DftCodeType {
    Crystal, // .d12 files
    Vasp,    // INCAR, POSCAR, KPOINTS, POTCAR
}

impl DftCodeType {
    /// Get the LSP language ID for this code type.
    pub fn language_id(&self) -> &'static str {
        match self {
            DftCodeType::Crystal => "crystal",
            DftCodeType::Vasp => "vasp",
        }
    }

    /// Detect DFT code type from filename.
    pub fn from_filename(name: &str) -> Option<Self> {
        let name_lower = name.to_lowercase();
        if name_lower.ends_with(".d12") {
            Some(DftCodeType::Crystal)
        } else {
            // Check for VASP files (case-insensitive base name)
            let base = std::path::Path::new(name)
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or(name);
            match base.to_uppercase().as_str() {
                "INCAR" | "POSCAR" | "KPOINTS" | "POTCAR" => Some(DftCodeType::Vasp),
                _ => None,
            }
        }
    }

    /// Get display name for this code type.
    #[allow(dead_code)] // Planned for status bar display
    pub fn display_name(&self) -> &'static str {
        match self {
            DftCodeType::Crystal => "CRYSTAL23",
            DftCodeType::Vasp => "VASP",
        }
    }
}

/// Events from the LSP server.
#[derive(Debug)]
pub enum LspEvent {
    /// Diagnostics received for a document.
    Diagnostics(String, Vec<Diagnostic>),
    /// Server is ready (initialized response received).
    ServerReady,
    /// Server error or disconnection.
    ServerError(String),
}

/// LSP Diagnostic with position and severity.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Diagnostic {
    pub range: Range,
    pub message: String,
    #[serde(default)]
    pub severity: Option<i32>,
    #[serde(default)]
    pub source: Option<String>,
}

/// LSP Range (start and end positions).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Range {
    pub start: Position,
    pub end: Position,
}

/// LSP Position (line and character).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Position {
    pub line: u32,
    pub character: u32,
}

/// Diagnostic severity levels (LSP spec).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DiagnosticSeverity {
    Error = 1,
    Warning = 2,
    Information = 3,
    Hint = 4,
}

impl DiagnosticSeverity {
    pub fn from_i32(value: i32) -> Self {
        match value {
            1 => DiagnosticSeverity::Error,
            2 => DiagnosticSeverity::Warning,
            3 => DiagnosticSeverity::Information,
            4 => DiagnosticSeverity::Hint,
            _ => DiagnosticSeverity::Error,
        }
    }
}

/// LSP Client for communicating with dft-language-server.
///
/// # Process Cleanup Safety
/// The `LspClient` owns the child process and ensures cleanup via RAII.
/// If `initialize()` fails during `start()`, the `Drop` implementation
/// will send shutdown/exit messages and kill the process if necessary,
/// preventing orphaned node processes.
pub struct LspClient {
    stdin: ChildStdin,
    request_id: i32,
    /// The request ID used for the initialize request.
    /// Shared with reader thread via Arc<AtomicI32>.
    initialize_id: Arc<AtomicI32>,
    /// Child process handle - used by Drop for cleanup.
    child: Child,
}

#[allow(dead_code)] // Inherent methods kept for direct use; trait methods used via Box<dyn>
impl LspClient {
    /// Spawn the LSP server and start the reader thread.
    ///
    /// # Arguments
    /// * `server_path` - Path/command for the LSP server
    /// * `event_tx` - Channel to send LSP events to the main thread
    ///
    /// # Process Cleanup Safety
    /// The `LspClient` is created early to take ownership of the child process.
    /// If `initialize()` fails, the `Drop` implementation will clean up the
    /// spawned process, preventing orphaned node processes.
    pub fn start(server_path: &str, event_tx: Sender<LspEvent>) -> Result<Self> {
        info!("Starting LSP server: {}", server_path);

        let server_path = server_path.trim();
        let ext = std::path::Path::new(server_path)
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("");
        let is_js = matches!(ext, "js" | "mjs" | "cjs");

        let mut child = if is_js {
            let node_binary =
                std::env::var("CRYSTAL_NODE_PATH").unwrap_or_else(|_| "node".to_string());
            info!("Using node binary: {}", node_binary);
            Command::new(&node_binary)
                .arg(server_path)
                .arg("--stdio")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .context("Failed to spawn node process for LSP server")?
        } else {
            Command::new(server_path)
                .arg("--stdio")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .context("Failed to spawn LSP server process")?
        };

        let stdin = child
            .stdin
            .take()
            .context("Failed to get stdin handle for LSP server")?;
        let stdout = child
            .stdout
            .take()
            .context("Failed to get stdout handle for LSP server")?;

        // Initialize ID will be set after we send the initialize request
        let initialize_id = Arc::new(AtomicI32::new(0));
        let initialize_id_clone = Arc::clone(&initialize_id);

        // Spawn reader thread for LSP responses
        thread::spawn(move || {
            Self::reader_thread(stdout, event_tx, initialize_id_clone);
        });

        // Create client early so it owns the child process.
        // If initialize() fails, Drop will clean up the process.
        let mut client = LspClient {
            stdin,
            request_id: 0,
            initialize_id,
            child,
        };

        // Send initialize request - if this fails, client's Drop will
        // handle graceful shutdown of the spawned node process
        client.initialize()?;

        Ok(client)
    }

    /// Reader thread that processes LSP server output.
    fn reader_thread(
        stdout: std::process::ChildStdout,
        event_tx: Sender<LspEvent>,
        initialize_id: Arc<AtomicI32>,
    ) {
        let mut reader = BufReader::new(stdout);

        loop {
            // Read all headers until empty line (LSP spec allows multiple headers)
            let mut content_length: Option<usize> = None;

            loop {
                let mut header = String::new();
                match reader.read_line(&mut header) {
                    Ok(0) => {
                        // EOF - server process has exited. Notify App so it can
                        // disable LSP and show a user-visible error.
                        warn!("LSP server stdout closed (server exited)");
                        let _ = event_tx.send(LspEvent::ServerError(
                            "LSP server exited unexpectedly".to_string(),
                        ));
                        return;
                    }
                    Ok(_) => {}
                    Err(e) => {
                        error!("Failed to read LSP header: {}", e);
                        let _ = event_tx.send(LspEvent::ServerError(e.to_string()));
                        return;
                    }
                }

                let trimmed = header.trim();

                // Empty line signals end of headers
                if trimmed.is_empty() {
                    break;
                }

                // Parse Content-Length header (case-insensitive per HTTP spec)
                // Split on first ':' and trim both key and value
                if let Some(colon_pos) = trimmed.find(':') {
                    let key = trimmed[..colon_pos].trim();
                    let value = trimmed[colon_pos + 1..].trim();

                    if key.eq_ignore_ascii_case("Content-Length") {
                        if let Ok(len) = value.parse::<usize>() {
                            content_length = Some(len);
                        }
                    }
                }
                // Ignore other headers (e.g., Content-Type)
            }

            // Validate we got Content-Length
            let size = match content_length {
                Some(s) if s > 0 => s,
                _ => {
                    warn!("LSP message missing valid Content-Length");
                    continue;
                }
            };

            // Cap message size to prevent OOM from malicious/buggy servers (100MB)
            const MAX_LSP_MESSAGE_SIZE: usize = 100 * 1024 * 1024;
            if size > MAX_LSP_MESSAGE_SIZE {
                error!(
                    "LSP message too large: {} bytes (max {})",
                    size, MAX_LSP_MESSAGE_SIZE
                );
                let _ = event_tx.send(LspEvent::ServerError(format!(
                    "LSP message exceeded size limit: {} bytes",
                    size
                )));
                return;
            }

            // Read message body
            let mut body_buf = vec![0u8; size];
            if let Err(e) = reader.read_exact(&mut body_buf) {
                error!("Failed to read LSP message body: {}", e);
                let _ = event_tx.send(LspEvent::ServerError(e.to_string()));
                break;
            }

            let body_str = match String::from_utf8(body_buf) {
                Ok(s) => s,
                Err(e) => {
                    warn!("Invalid UTF-8 in LSP message: {}", e);
                    continue;
                }
            };

            // Parse JSON and dispatch events
            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&body_str) {
                Self::handle_message(&json, &event_tx, &initialize_id);
            }
        }
    }

    /// Handle a parsed LSP message.
    fn handle_message(
        json: &serde_json::Value,
        event_tx: &Sender<LspEvent>,
        initialize_id: &Arc<AtomicI32>,
    ) {
        // Check for method field (notifications)
        if let Some(method) = json.get("method").and_then(|m| m.as_str()) {
            match method {
                "textDocument/publishDiagnostics" => {
                    if let Some(params) = json.get("params") {
                        let uri = params
                            .get("uri")
                            .and_then(|u| u.as_str())
                            .unwrap_or("")
                            .to_string();

                        if let Ok(diags) = serde_json::from_value::<Vec<Diagnostic>>(
                            params.get("diagnostics").cloned().unwrap_or_default(),
                        ) {
                            debug!("Received {} diagnostics for {}", diags.len(), uri);
                            let _ = event_tx.send(LspEvent::Diagnostics(uri, diags));
                        }
                    }
                }
                _ => {
                    debug!("Unhandled LSP method: {}", method);
                }
            }
        }
        // Check for id field (responses)
        else if let Some(id_value) = json.get("id") {
            let response_id = id_value.as_i64().unwrap_or(-1) as i32;
            let expected_init_id = initialize_id.load(Ordering::SeqCst);

            // Check for error response first
            if let Some(error) = json.get("error") {
                let message = error
                    .get("message")
                    .and_then(|m| m.as_str())
                    .unwrap_or("Unknown LSP error");
                let code = error.get("code").and_then(|c| c.as_i64()).unwrap_or(-1);
                error!("LSP error response: {} (code: {})", message, code);

                // If this is an error response to the initialize request, report it
                if response_id == expected_init_id {
                    let _ = event_tx.send(LspEvent::ServerError(format!(
                        "Initialize failed: {} (code: {})",
                        message, code
                    )));
                } else {
                    let _ = event_tx.send(LspEvent::ServerError(format!(
                        "LSP error {}: {}",
                        code, message
                    )));
                }
            }
            // Success response - only emit ServerReady for initialize response
            else if json.get("result").is_some() {
                if response_id == expected_init_id {
                    debug!("LSP server initialized (id: {})", response_id);
                    let _ = event_tx.send(LspEvent::ServerReady);
                } else {
                    debug!(
                        "Received response for request {} (initialize was {})",
                        response_id, expected_init_id
                    );
                }
            }
        }
    }

    /// Get next request ID.
    fn next_id(&mut self) -> i32 {
        self.request_id += 1;
        self.request_id
    }

    /// Send the initialize request to the LSP server.
    fn initialize(&mut self) -> Result<()> {
        let id = self.next_id();
        // Store the initialize request ID for the reader thread to check
        self.initialize_id.store(id, Ordering::SeqCst);

        let req = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": "initialize",
            "params": {
                "processId": std::process::id(),
                "rootUri": null,
                "capabilities": {
                    "textDocument": {
                        "publishDiagnostics": {
                            "relatedInformation": true
                        },
                        "completion": {
                            "completionItem": {
                                "snippetSupport": true
                            }
                        },
                        "hover": {
                            "contentFormat": ["markdown", "plaintext"]
                        }
                    }
                }
            }
        });
        self.send(&req)
    }

    /// Send the initialized notification (required after initialize response).
    /// This tells the server we're ready to receive notifications.
    pub fn send_initialized(&mut self) -> Result<()> {
        debug!("Sending LSP initialized notification");
        let notification = make_notification("initialized", json!({}));
        self.send(&notification)
    }

    /// Notify the server that a document was opened.
    pub fn did_open(&mut self, file_path: &str, text: &str) -> Result<()> {
        let lang_id = DftCodeType::from_filename(file_path)
            .map(|t| t.language_id())
            .unwrap_or("plaintext");

        let uri = Self::path_to_uri(file_path);

        debug!("LSP didOpen: {} (language: {})", uri, lang_id);

        let notification = make_notification(
            "textDocument/didOpen",
            json!({
                "textDocument": {
                    "uri": uri,
                    "languageId": lang_id,
                    "version": 1,
                    "text": text
                }
            }),
        );
        self.send(&notification)
    }

    /// Notify the server that a document changed.
    pub fn did_change(&mut self, file_path: &str, version: i32, text: &str) -> Result<()> {
        let uri = Self::path_to_uri(file_path);

        debug!("LSP didChange: {} (version: {})", uri, version);

        let notification = make_notification(
            "textDocument/didChange",
            json!({
                "textDocument": {
                    "uri": uri,
                    "version": version
                },
                "contentChanges": [{"text": text}]
            }),
        );
        self.send(&notification)
    }

    /// Notify the server that a document was closed.
    #[allow(dead_code)] // Called by open_file which is planned feature
    pub fn did_close(&mut self, file_path: &str) -> Result<()> {
        let uri = Self::path_to_uri(file_path);

        debug!("LSP didClose: {}", uri);

        let notification = make_notification(
            "textDocument/didClose",
            json!({
                "textDocument": {
                    "uri": uri
                }
            }),
        );
        self.send(&notification)
    }

    /// Convert a file path to a file:// URI with proper percent-encoding.
    ///
    /// Uses the `url` crate to properly encode special characters like spaces,
    /// non-ASCII characters, and other reserved URI characters.
    pub fn path_to_uri(path: &str) -> String {
        use std::path::Path;

        // Handle both absolute and relative paths
        let abs_path = if Path::new(path).is_absolute() {
            std::path::PathBuf::from(path)
        } else {
            std::env::current_dir()
                .map(|p| p.join(path))
                .unwrap_or_else(|_| std::path::PathBuf::from(path))
        };

        // Use the url crate for proper percent-encoding
        match Url::from_file_path(&abs_path) {
            Ok(url) => url.to_string(),
            Err(_) => {
                // Fallback for edge cases (e.g., relative paths that couldn't be resolved)
                // Manual percent-encoding for common characters
                let path_str = abs_path.to_string_lossy();
                let encoded = path_str
                    .replace('%', "%25") // Must be first
                    .replace(' ', "%20")
                    .replace('#', "%23")
                    .replace('?', "%3F")
                    .replace('[', "%5B")
                    .replace(']', "%5D");

                if cfg!(windows) {
                    format!("file:///{}", encoded.replace('\\', "/"))
                } else {
                    format!("file://{}", encoded)
                }
            }
        }
    }

    /// Send a JSON-RPC message to the LSP server.
    fn send(&mut self, json: &serde_json::Value) -> Result<()> {
        let msg = json.to_string();
        let req = format!("Content-Length: {}\r\n\r\n{}", msg.len(), msg);

        self.stdin
            .write_all(req.as_bytes())
            .context("Failed to write to LSP stdin")?;
        self.stdin.flush().context("Failed to flush LSP stdin")?;

        Ok(())
    }
}

impl Drop for LspClient {
    fn drop(&mut self) {
        // Try to gracefully shut down the server
        // Note: shutdown is a request (has id), not a notification
        let shutdown = json!({
            "jsonrpc": "2.0",
            "id": self.next_id(),
            "method": "shutdown",
            "params": null
        });
        let _ = self.send(&shutdown);

        let exit = make_notification("exit", serde_json::Value::Null);
        let _ = self.send(&exit);

        // Wait for child process to prevent zombie
        // Use try_wait in a loop with short timeout to avoid blocking forever
        use std::thread;
        use std::time::Duration;

        for _ in 0..10 {
            match self.child.try_wait() {
                Ok(Some(_status)) => {
                    debug!("LSP server process exited cleanly");
                    return;
                }
                Ok(None) => {
                    // Still running, wait a bit
                    thread::sleep(Duration::from_millis(50));
                }
                Err(e) => {
                    warn!("Error waiting for LSP server: {}", e);
                    return;
                }
            }
        }

        // If still running after 500ms, kill it
        warn!("LSP server didn't exit gracefully, killing");
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Implementation of `LspService` for `LspClient`.
///
/// This allows `LspClient` to be used anywhere an `LspService` is expected,
/// enabling dependency injection and mock implementations for testing.
///
/// The trait methods delegate to the inherent methods to avoid code duplication.
impl LspService for LspClient {
    fn send_initialized(&mut self) -> anyhow::Result<()> {
        LspClient::send_initialized(self)
    }

    fn did_open(&mut self, file_path: &str, text: &str) -> anyhow::Result<()> {
        LspClient::did_open(self, file_path, text)
    }

    fn did_change(&mut self, file_path: &str, version: i32, text: &str) -> anyhow::Result<()> {
        LspClient::did_change(self, file_path, version, text)
    }

    fn did_close(&mut self, file_path: &str) -> anyhow::Result<()> {
        LspClient::did_close(self, file_path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dft_code_type_from_filename() {
        assert_eq!(
            DftCodeType::from_filename("mgo.d12"),
            Some(DftCodeType::Crystal)
        );
        assert_eq!(
            DftCodeType::from_filename("test.D12"),
            Some(DftCodeType::Crystal)
        );
        assert_eq!(DftCodeType::from_filename("INCAR"), Some(DftCodeType::Vasp));
        assert_eq!(
            DftCodeType::from_filename("POSCAR"),
            Some(DftCodeType::Vasp)
        );
        assert_eq!(
            DftCodeType::from_filename("/path/to/KPOINTS"),
            Some(DftCodeType::Vasp)
        );
        assert_eq!(DftCodeType::from_filename("random.txt"), None);
    }

    #[test]
    fn test_language_id() {
        assert_eq!(DftCodeType::Crystal.language_id(), "crystal");
        assert_eq!(DftCodeType::Vasp.language_id(), "vasp");
    }

    #[test]
    fn test_path_to_uri() {
        // Test absolute path
        let uri = LspClient::path_to_uri("/home/user/test.d12");
        assert!(uri.starts_with("file://"));
        assert!(uri.contains("test.d12"));
    }

    #[test]
    fn test_diagnostic_severity() {
        assert_eq!(DiagnosticSeverity::from_i32(1), DiagnosticSeverity::Error);
        assert_eq!(DiagnosticSeverity::from_i32(2), DiagnosticSeverity::Warning);
        assert_eq!(
            DiagnosticSeverity::from_i32(3),
            DiagnosticSeverity::Information
        );
        assert_eq!(DiagnosticSeverity::from_i32(4), DiagnosticSeverity::Hint);
        assert_eq!(DiagnosticSeverity::from_i32(99), DiagnosticSeverity::Error);
        // Default
    }

    #[test]
    fn test_dft_code_display_name() {
        assert_eq!(DftCodeType::Crystal.display_name(), "CRYSTAL23");
        assert_eq!(DftCodeType::Vasp.display_name(), "VASP");
    }

    #[test]
    fn test_path_to_uri_relative() {
        // Test relative path gets resolved
        let uri = LspClient::path_to_uri("test.d12");
        assert!(uri.starts_with("file://"));
        assert!(uri.ends_with("test.d12"));
    }

    #[test]
    fn test_diagnostic_deserialize() {
        let json = r#"{
            "range": {
                "start": {"line": 5, "character": 10},
                "end": {"line": 5, "character": 20}
            },
            "message": "Unknown keyword",
            "severity": 1,
            "source": "dft-language-server"
        }"#;

        let diag: Diagnostic = serde_json::from_str(json).unwrap();
        assert_eq!(diag.range.start.line, 5);
        assert_eq!(diag.range.start.character, 10);
        assert_eq!(diag.message, "Unknown keyword");
        assert_eq!(diag.severity, Some(1));
        assert_eq!(diag.source, Some("dft-language-server".to_string()));
    }

    #[test]
    fn test_diagnostic_without_optional_fields() {
        let json = r#"{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 5}
            },
            "message": "Error"
        }"#;

        let diag: Diagnostic = serde_json::from_str(json).unwrap();
        assert_eq!(diag.message, "Error");
        assert_eq!(diag.severity, None);
        assert_eq!(diag.source, None);
    }

    #[test]
    fn test_vasp_file_detection_case_insensitive() {
        // VASP files should match case-insensitively
        assert_eq!(DftCodeType::from_filename("incar"), Some(DftCodeType::Vasp));
        assert_eq!(DftCodeType::from_filename("Incar"), Some(DftCodeType::Vasp));
        assert_eq!(
            DftCodeType::from_filename("poscar"),
            Some(DftCodeType::Vasp)
        );
        assert_eq!(
            DftCodeType::from_filename("/some/path/potcar"),
            Some(DftCodeType::Vasp)
        );
    }

    #[test]
    fn test_crystal_file_extensions() {
        assert_eq!(
            DftCodeType::from_filename("mgo.d12"),
            Some(DftCodeType::Crystal)
        );
        assert_eq!(
            DftCodeType::from_filename("MgO.D12"),
            Some(DftCodeType::Crystal)
        );
        assert_eq!(
            DftCodeType::from_filename("/path/to/calculation.d12"),
            Some(DftCodeType::Crystal)
        );
    }

    #[test]
    fn test_non_dft_files() {
        assert_eq!(DftCodeType::from_filename("README.md"), None);
        assert_eq!(DftCodeType::from_filename("Cargo.toml"), None);
        assert_eq!(DftCodeType::from_filename("script.py"), None);
        assert_eq!(DftCodeType::from_filename(".gitignore"), None);
    }

    // ==================== Protocol Fix Tests ====================

    /// Helper to parse Content-Length header with case-insensitive matching.
    /// This mirrors the logic in reader_thread for testing purposes.
    fn parse_content_length(header: &str) -> Option<usize> {
        let trimmed = header.trim();
        if let Some(colon_pos) = trimmed.find(':') {
            let key = trimmed[..colon_pos].trim();
            let value = trimmed[colon_pos + 1..].trim();

            if key.eq_ignore_ascii_case("Content-Length") {
                return value.parse::<usize>().ok();
            }
        }
        None
    }

    #[test]
    fn test_header_parsing_case_variations() {
        // Standard case
        assert_eq!(parse_content_length("Content-Length: 100"), Some(100));

        // All lowercase
        assert_eq!(parse_content_length("content-length: 200"), Some(200));

        // All uppercase
        assert_eq!(parse_content_length("CONTENT-LENGTH: 300"), Some(300));

        // Mixed case
        assert_eq!(parse_content_length("content-Length: 400"), Some(400));
        assert_eq!(parse_content_length("Content-length: 500"), Some(500));
    }

    #[test]
    fn test_header_parsing_whitespace_variations() {
        // Extra spaces after colon
        assert_eq!(parse_content_length("Content-Length:  100"), Some(100));

        // Space before colon
        assert_eq!(parse_content_length("Content-Length : 100"), Some(100));

        // Spaces on both sides
        assert_eq!(parse_content_length("Content-Length :  100"), Some(100));

        // Leading/trailing whitespace on value
        assert_eq!(parse_content_length("Content-Length:   100   "), Some(100));

        // Tab characters
        assert_eq!(parse_content_length("Content-Length:\t100"), Some(100));
    }

    #[test]
    fn test_header_parsing_invalid_cases() {
        // No colon
        assert_eq!(parse_content_length("Content-Length 100"), None);

        // Wrong header name
        assert_eq!(parse_content_length("Content-Type: text/plain"), None);

        // Non-numeric value
        assert_eq!(parse_content_length("Content-Length: abc"), None);

        // Empty value
        assert_eq!(parse_content_length("Content-Length:"), None);

        // Empty string
        assert_eq!(parse_content_length(""), None);
    }

    #[test]
    fn test_uri_encoding_with_spaces() {
        let uri = LspClient::path_to_uri("/home/user/my calculations/test.d12");
        assert!(uri.starts_with("file://"));
        // The space should be percent-encoded
        assert!(
            uri.contains("%20") || uri.contains("my%20calculations"),
            "URI should contain percent-encoded space: {}",
            uri
        );
        assert!(!uri.contains(' '), "URI should not contain literal space");
    }

    #[test]
    fn test_uri_encoding_with_special_chars() {
        // Test with hash character (reserved in URIs)
        let uri = LspClient::path_to_uri("/home/user/file#1.d12");
        assert!(uri.starts_with("file://"));
        assert!(
            uri.contains("%23"),
            "Hash should be percent-encoded: {}",
            uri
        );

        // Test with question mark (reserved in URIs)
        let uri2 = LspClient::path_to_uri("/home/user/file?.d12");
        assert!(
            uri2.contains("%3F"),
            "Question mark should be percent-encoded: {}",
            uri2
        );
    }

    #[test]
    fn test_uri_encoding_preserves_slashes() {
        let uri = LspClient::path_to_uri("/home/user/subdir/file.d12");
        // Path separators should not be encoded in the path part
        assert!(uri.contains("/home/user/subdir/file.d12"));
    }

    #[test]
    fn test_handle_message_init_response_matching() {
        use std::sync::mpsc::channel;

        let (tx, rx) = channel();
        let init_id = Arc::new(AtomicI32::new(1));

        // Test: Response with matching initialize ID triggers ServerReady
        let init_response = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "capabilities": {}
            }
        });
        LspClient::handle_message(&init_response, &tx, &init_id);

        match rx.try_recv() {
            Ok(LspEvent::ServerReady) => {} // Expected
            other => panic!("Expected ServerReady, got: {:?}", other),
        }
    }

    #[test]
    fn test_handle_message_non_init_response_ignored() {
        use std::sync::mpsc::channel;

        let (tx, rx) = channel();
        let init_id = Arc::new(AtomicI32::new(1));

        // Test: Response with non-matching ID does NOT trigger ServerReady
        let other_response = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 99,
            "result": {
                "someData": true
            }
        });
        LspClient::handle_message(&other_response, &tx, &init_id);

        // Should not receive any event
        match rx.try_recv() {
            Err(std::sync::mpsc::TryRecvError::Empty) => {} // Expected
            other => panic!("Expected no event, got: {:?}", other),
        }
    }

    #[test]
    fn test_handle_message_init_error_response() {
        use std::sync::mpsc::channel;

        let (tx, rx) = channel();
        let init_id = Arc::new(AtomicI32::new(1));

        // Test: Error response for initialize request
        let error_response = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32600,
                "message": "Invalid Request"
            }
        });
        LspClient::handle_message(&error_response, &tx, &init_id);

        match rx.try_recv() {
            Ok(LspEvent::ServerError(msg)) => {
                assert!(
                    msg.contains("Initialize failed"),
                    "Error message should indicate initialize failure: {}",
                    msg
                );
            }
            other => panic!("Expected ServerError, got: {:?}", other),
        }
    }

    #[test]
    fn test_handle_message_diagnostics_notification() {
        use std::sync::mpsc::channel;

        let (tx, rx) = channel();
        let init_id = Arc::new(AtomicI32::new(1));

        // Test: Diagnostics notification is processed correctly
        let diag_notification = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": "file:///test.d12",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 5}
                        },
                        "message": "Test error"
                    }
                ]
            }
        });
        LspClient::handle_message(&diag_notification, &tx, &init_id);

        match rx.try_recv() {
            Ok(LspEvent::Diagnostics(uri, diags)) => {
                assert_eq!(uri, "file:///test.d12");
                assert_eq!(diags.len(), 1);
                assert_eq!(diags[0].message, "Test error");
            }
            other => panic!("Expected Diagnostics, got: {:?}", other),
        }
    }

    // ==================== Reader Thread Framing Tests ====================
    //
    // These tests verify the LSP message framing logic in reader_thread.
    // The LSP protocol uses HTTP-style headers with Content-Length to frame messages.

    /// Parse headers from a reader until empty line, extracting Content-Length.
    /// This mirrors the header parsing loop in reader_thread (lines 247-287).
    ///
    /// Returns:
    /// - `Ok(Some(length))` if Content-Length header was found
    /// - `Ok(None)` if no Content-Length header (message should be skipped)
    /// - `Err(reason)` for IO errors or protocol violations
    fn parse_headers_from_reader<R: BufRead>(reader: &mut R) -> Result<Option<usize>, String> {
        let mut content_length: Option<usize> = None;

        loop {
            let mut header = String::new();
            match reader.read_line(&mut header) {
                Ok(0) => return Err("EOF".to_string()),
                Ok(_) => {}
                Err(e) => return Err(format!("IO error: {}", e)),
            }

            let trimmed = header.trim();

            // Empty line signals end of headers
            if trimmed.is_empty() {
                break;
            }

            // Parse Content-Length header (case-insensitive per HTTP spec)
            if let Some(colon_pos) = trimmed.find(':') {
                let key = trimmed[..colon_pos].trim();
                let value = trimmed[colon_pos + 1..].trim();

                if key.eq_ignore_ascii_case("Content-Length") {
                    if let Ok(len) = value.parse::<usize>() {
                        content_length = Some(len);
                    }
                }
            }
        }

        Ok(content_length)
    }

    /// Validate Content-Length against size limits (mirrors lines 298-310).
    fn validate_content_length(size: Option<usize>) -> Result<usize, String> {
        const MAX_LSP_MESSAGE_SIZE: usize = 100 * 1024 * 1024; // 100MB

        match size {
            Some(0) => Err("Content-Length is zero".to_string()),
            Some(s) if s > MAX_LSP_MESSAGE_SIZE => Err(format!(
                "Message too large: {} bytes (max {})",
                s, MAX_LSP_MESSAGE_SIZE
            )),
            Some(s) => Ok(s),
            None => Err("Missing Content-Length".to_string()),
        }
    }

    #[test]
    fn test_framing_multi_header_with_content_type() {
        // LSP spec allows multiple headers; Content-Type is common
        let input = "Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n\
                     Content-Length: 42\r\n\
                     \r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());

        let result = parse_headers_from_reader(&mut reader);
        assert_eq!(result, Ok(Some(42)));
    }

    #[test]
    fn test_framing_content_length_only() {
        // Minimal valid header set
        let input = "Content-Length: 100\r\n\r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());

        let result = parse_headers_from_reader(&mut reader);
        assert_eq!(result, Ok(Some(100)));
    }

    #[test]
    fn test_framing_missing_content_length() {
        // Only Content-Type, no Content-Length - should return None
        let input = "Content-Type: text/plain\r\n\r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());

        let result = parse_headers_from_reader(&mut reader);
        assert_eq!(result, Ok(None));

        // Validation should fail for missing Content-Length
        let validation = validate_content_length(None);
        assert!(validation.is_err());
        assert!(validation.unwrap_err().contains("Missing"));
    }

    #[test]
    fn test_framing_oversized_content_length() {
        // 200MB - exceeds 100MB limit
        let size = 200 * 1024 * 1024;
        let input = format!("Content-Length: {}\r\n\r\n", size);
        let mut reader = std::io::BufReader::new(input.as_bytes());

        let result = parse_headers_from_reader(&mut reader);
        assert_eq!(result, Ok(Some(size)));

        // Validation should fail for oversized message
        let validation = validate_content_length(Some(size));
        assert!(validation.is_err());
        assert!(validation.unwrap_err().contains("too large"));
    }

    #[test]
    fn test_framing_exactly_at_size_limit() {
        // Exactly 100MB - should be valid
        let size = 100 * 1024 * 1024;
        let validation = validate_content_length(Some(size));
        assert_eq!(validation, Ok(size));
    }

    #[test]
    fn test_framing_just_over_size_limit() {
        // 100MB + 1 byte - should fail
        let size = 100 * 1024 * 1024 + 1;
        let validation = validate_content_length(Some(size));
        assert!(validation.is_err());
    }

    #[test]
    fn test_framing_case_insensitive_content_length() {
        // All lowercase
        let input1 = "content-length: 50\r\n\r\n";
        let mut reader1 = std::io::BufReader::new(input1.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader1), Ok(Some(50)));

        // All uppercase
        let input2 = "CONTENT-LENGTH: 60\r\n\r\n";
        let mut reader2 = std::io::BufReader::new(input2.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader2), Ok(Some(60)));

        // Mixed case variations
        let input3 = "Content-length: 70\r\n\r\n";
        let mut reader3 = std::io::BufReader::new(input3.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader3), Ok(Some(70)));

        let input4 = "content-Length: 80\r\n\r\n";
        let mut reader4 = std::io::BufReader::new(input4.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader4), Ok(Some(80)));

        let input5 = "CONTENT-length: 90\r\n\r\n";
        let mut reader5 = std::io::BufReader::new(input5.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader5), Ok(Some(90)));
    }

    #[test]
    fn test_framing_whitespace_after_colon() {
        // Multiple spaces after colon
        let input1 = "Content-Length:    123\r\n\r\n";
        let mut reader1 = std::io::BufReader::new(input1.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader1), Ok(Some(123)));

        // Tab after colon
        let input2 = "Content-Length:\t456\r\n\r\n";
        let mut reader2 = std::io::BufReader::new(input2.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader2), Ok(Some(456)));

        // No space after colon
        let input3 = "Content-Length:789\r\n\r\n";
        let mut reader3 = std::io::BufReader::new(input3.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader3), Ok(Some(789)));
    }

    #[test]
    fn test_framing_whitespace_before_colon() {
        // Space before colon (unusual but should work due to trim)
        let input = "Content-Length : 100\r\n\r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(Some(100)));
    }

    #[test]
    fn test_framing_trailing_whitespace_on_value() {
        // Trailing spaces on value
        let input = "Content-Length: 200   \r\n\r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(Some(200)));
    }

    #[test]
    fn test_framing_headers_in_different_order() {
        // Content-Length before Content-Type
        let input1 = "Content-Length: 30\r\n\
                      Content-Type: application/json\r\n\
                      \r\n";
        let mut reader1 = std::io::BufReader::new(input1.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader1), Ok(Some(30)));

        // Content-Type before Content-Length
        let input2 = "Content-Type: application/json\r\n\
                      Content-Length: 40\r\n\
                      \r\n";
        let mut reader2 = std::io::BufReader::new(input2.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader2), Ok(Some(40)));
    }

    #[test]
    fn test_framing_unknown_headers_ignored() {
        // Extra unknown headers should be ignored
        let input = "X-Custom-Header: some-value\r\n\
                     Content-Length: 55\r\n\
                     X-Another-Header: another-value\r\n\
                     \r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(Some(55)));
    }

    #[test]
    fn test_framing_duplicate_content_length() {
        // Last Content-Length wins (implementation detail)
        let input = "Content-Length: 100\r\n\
                     Content-Length: 200\r\n\
                     \r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        let result = parse_headers_from_reader(&mut reader);
        // The implementation uses the last valid Content-Length
        assert_eq!(result, Ok(Some(200)));
    }

    #[test]
    fn test_framing_non_numeric_content_length() {
        // Non-numeric value should be ignored (no Content-Length parsed)
        let input = "Content-Length: abc\r\n\r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(None));
    }

    #[test]
    fn test_framing_negative_content_length() {
        // Negative value - parse fails, treated as missing
        let input = "Content-Length: -100\r\n\r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        // parse::<usize> fails for negative, so None
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(None));
    }

    #[test]
    fn test_framing_zero_content_length() {
        // Zero is parsed but validation should reject it
        let input = "Content-Length: 0\r\n\r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(Some(0)));

        // Validation should fail for zero
        let validation = validate_content_length(Some(0));
        assert!(validation.is_err());
    }

    #[test]
    fn test_framing_eof_during_headers() {
        // EOF before empty line
        let input = "Content-Length: 100";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        let result = parse_headers_from_reader(&mut reader);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("EOF"));
    }

    #[test]
    fn test_framing_lf_line_endings() {
        // Unix-style LF only (not CRLF) - should still work
        let input = "Content-Length: 100\n\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(Some(100)));
    }

    #[test]
    fn test_framing_mixed_line_endings() {
        // Mix of CRLF and LF
        let input = "Content-Type: text/plain\r\n\
                     Content-Length: 75\n\
                     \r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(Some(75)));
    }

    #[test]
    fn test_framing_header_without_colon() {
        // Malformed header without colon - ignored
        let input = "InvalidHeaderNoColon\r\n\
                     Content-Length: 50\r\n\
                     \r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(Some(50)));
    }

    #[test]
    fn test_framing_empty_header_name() {
        // Colon at start - empty header name
        let input = ": some-value\r\n\
                     Content-Length: 60\r\n\
                     \r\n";
        let mut reader = std::io::BufReader::new(input.as_bytes());
        assert_eq!(parse_headers_from_reader(&mut reader), Ok(Some(60)));
    }

    #[test]
    fn test_framing_large_valid_content_length() {
        // 50MB - valid large message
        let size = 50 * 1024 * 1024;
        let validation = validate_content_length(Some(size));
        assert_eq!(validation, Ok(size));
    }

    #[test]
    fn test_framing_small_content_length() {
        // Minimum valid size (1 byte)
        let validation = validate_content_length(Some(1));
        assert_eq!(validation, Ok(1));
    }

    // ==================== Integration Tests for LspClient Lifecycle ====================
    //
    // These tests verify LspClient::start() subprocess spawning and Drop cleanup behavior
    // using mock server scripts that simulate various LSP server behaviors.

    /// Create a mock LSP server script that responds to initialize and exits cleanly.
    ///
    /// Returns the path to the temporary script file.
    fn create_mock_lsp_server_script(behavior: MockServerBehavior) -> std::path::PathBuf {
        use std::fs;
        use std::os::unix::fs::PermissionsExt;

        let temp_dir = std::env::temp_dir();
        let script_path = temp_dir.join(format!(
            "mock_lsp_server_{}_{}.sh",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));

        let script_content = match behavior {
            MockServerBehavior::RespondAndExit => {
                // Responds to initialize request with valid LSP response, then exits
                r#"#!/bin/bash
# Mock LSP server that responds to initialize and exits cleanly

# Read the Content-Length header
read -r header
# Skip any additional headers until empty line
while IFS= read -r line && [ -n "${line//$'\r'/}" ]; do
    :
done

# Extract content length (simple parsing)
content_length=$(echo "$header" | grep -oE '[0-9]+')

# Read the JSON body
if [ -n "$content_length" ]; then
    body=$(head -c "$content_length")
fi

# Send initialize response
response='{"jsonrpc":"2.0","id":1,"result":{"capabilities":{}}}'
content_length=${#response}
printf "Content-Length: %d\r\n\r\n%s" "$content_length" "$response"

# Exit cleanly after a short delay to allow response to be read
sleep 0.1
exit 0
"#
            }
            MockServerBehavior::ExitImmediately => {
                // Exits immediately without responding (simulates crash)
                r#"#!/bin/bash
# Mock LSP server that exits immediately without responding
exit 0
"#
            }
            MockServerBehavior::HangForever => {
                // Reads input but never responds (simulates unresponsive server)
                r#"#!/bin/bash
# Mock LSP server that hangs forever (for testing kill behavior)
# Use trap to ignore SIGTERM to test SIGKILL fallback
trap '' TERM

# Read input forever without responding
while true; do
    read -r line 2>/dev/null || sleep 0.1
done
"#
            }
            MockServerBehavior::RespondThenHang => {
                // Responds to initialize, then hangs (simulates server that stops responding)
                r#"#!/bin/bash
# Mock LSP server that responds to initialize then hangs
trap '' TERM

# Read the Content-Length header
read -r header
while IFS= read -r line && [ -n "${line//$'\r'/}" ]; do
    :
done

content_length=$(echo "$header" | grep -oE '[0-9]+')
if [ -n "$content_length" ]; then
    body=$(head -c "$content_length")
fi

# Send initialize response
response='{"jsonrpc":"2.0","id":1,"result":{"capabilities":{}}}'
content_length=${#response}
printf "Content-Length: %d\r\n\r\n%s" "$content_length" "$response"

# Then hang forever
while true; do
    sleep 1
done
"#
            }
        };

        fs::write(&script_path, script_content).expect("Failed to write mock script");

        // Make script executable
        let mut perms = fs::metadata(&script_path)
            .expect("Failed to get script metadata")
            .permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&script_path, perms).expect("Failed to set script permissions");

        script_path
    }

    /// Different mock server behaviors for testing.
    #[derive(Debug, Clone, Copy)]
    enum MockServerBehavior {
        /// Responds to initialize request and exits cleanly
        RespondAndExit,
        /// Exits immediately without responding (simulates crash on startup)
        ExitImmediately,
        /// Never responds, ignores SIGTERM (tests SIGKILL fallback)
        HangForever,
        /// Responds to initialize, then hangs (tests Drop with unresponsive server)
        RespondThenHang,
    }

    /// Clean up a mock script file.
    fn cleanup_mock_script(path: &std::path::Path) {
        let _ = std::fs::remove_file(path);
    }

    /// Helper to spawn LspClient with a mock bash script instead of node.
    ///
    /// Sets CRYSTAL_NODE_PATH to bash so we can use shell scripts as mock servers.
    fn start_client_with_mock_script(
        script_path: &std::path::Path,
        event_tx: Sender<LspEvent>,
    ) -> Result<LspClient> {
        // Temporarily set CRYSTAL_NODE_PATH to bash
        std::env::set_var("CRYSTAL_NODE_PATH", "bash");

        let result = LspClient::start(
            script_path
                .to_str()
                .expect("Mock script path must be valid UTF-8"),
            event_tx,
        );

        // Reset environment variable
        std::env::remove_var("CRYSTAL_NODE_PATH");

        result
    }

    #[test]
    fn test_lsp_client_start_spawns_subprocess() {
        // Test that LspClient::start() successfully spawns a subprocess
        // and the subprocess receives the initialize request

        let script_path = create_mock_lsp_server_script(MockServerBehavior::RespondAndExit);
        let (tx, rx) = std::sync::mpsc::channel();

        let client_result = start_client_with_mock_script(&script_path, tx);

        match client_result {
            Ok(client) => {
                // Wait for ServerReady event (initialize response received)
                let timeout = std::time::Duration::from_secs(5);
                let start = std::time::Instant::now();

                let mut got_ready = false;
                while start.elapsed() < timeout {
                    match rx.try_recv() {
                        Ok(LspEvent::ServerReady) => {
                            got_ready = true;
                            break;
                        }
                        Ok(LspEvent::ServerError(e)) => {
                            // Server may exit after responding, which is fine
                            if !got_ready {
                                panic!("Unexpected server error before ready: {}", e);
                            }
                            break;
                        }
                        Ok(_) => continue,
                        Err(std::sync::mpsc::TryRecvError::Empty) => {
                            std::thread::sleep(std::time::Duration::from_millis(10));
                        }
                        Err(std::sync::mpsc::TryRecvError::Disconnected) => break,
                    }
                }

                assert!(got_ready, "Should have received ServerReady event");

                // Drop client to trigger cleanup
                drop(client);
            }
            Err(e) => {
                panic!("Failed to start LspClient: {}", e);
            }
        }

        cleanup_mock_script(&script_path);
    }

    #[test]
    fn test_lsp_client_start_handles_immediate_exit() {
        // Test that LspClient::start() handles a server that exits immediately
        // The initialize request will fail because the server exits before responding

        let script_path = create_mock_lsp_server_script(MockServerBehavior::ExitImmediately);
        let (tx, rx) = std::sync::mpsc::channel();

        let client_result = start_client_with_mock_script(&script_path, tx);

        // The client may or may not succeed in starting depending on timing.
        // What matters is:
        // 1. We don't panic or hang
        // 2. If client was created, Drop cleans up properly
        // 3. We eventually get a ServerError or the client fails to start

        match client_result {
            Ok(client) => {
                // Server exited immediately, reader thread should detect EOF
                let timeout = std::time::Duration::from_secs(2);
                let start = std::time::Instant::now();

                while start.elapsed() < timeout {
                    match rx.try_recv() {
                        Ok(LspEvent::ServerError(_)) => break, // Expected
                        Ok(LspEvent::ServerReady) => {
                            // Unlikely but possible if server output was buffered
                            break;
                        }
                        Ok(_) => continue,
                        Err(std::sync::mpsc::TryRecvError::Empty) => {
                            std::thread::sleep(std::time::Duration::from_millis(10));
                        }
                        Err(std::sync::mpsc::TryRecvError::Disconnected) => break,
                    }
                }

                // Drop should not hang even though server already exited
                drop(client);
            }
            Err(_) => {
                // This is also acceptable - server exited before we could communicate
            }
        }

        cleanup_mock_script(&script_path);
    }

    #[test]
    fn test_lsp_client_drop_graceful_shutdown() {
        // Test that Drop sends shutdown/exit messages and waits for clean exit

        let script_path = create_mock_lsp_server_script(MockServerBehavior::RespondAndExit);
        let (tx, rx) = std::sync::mpsc::channel();

        let client_result = start_client_with_mock_script(&script_path, tx);

        if let Ok(client) = client_result {
            // Wait for initialization
            let timeout = std::time::Duration::from_secs(5);
            let start = std::time::Instant::now();

            while start.elapsed() < timeout {
                match rx.try_recv() {
                    Ok(LspEvent::ServerReady) => break,
                    Ok(_) => continue,
                    Err(std::sync::mpsc::TryRecvError::Empty) => {
                        std::thread::sleep(std::time::Duration::from_millis(10));
                    }
                    Err(std::sync::mpsc::TryRecvError::Disconnected) => break,
                }
            }

            // Measure Drop time - should be fast for a well-behaved server
            let drop_start = std::time::Instant::now();
            drop(client);
            let drop_duration = drop_start.elapsed();

            // Drop should complete quickly (< 1 second) for a server that exits cleanly
            // The Drop implementation waits up to 500ms in 50ms increments
            assert!(
                drop_duration < std::time::Duration::from_secs(2),
                "Drop took too long: {:?}",
                drop_duration
            );
        }

        cleanup_mock_script(&script_path);
    }

    #[test]
    fn test_lsp_client_drop_kills_unresponsive_server() {
        // Test that Drop kills a server that ignores SIGTERM

        let script_path = create_mock_lsp_server_script(MockServerBehavior::RespondThenHang);
        let (tx, rx) = std::sync::mpsc::channel();

        let client_result = start_client_with_mock_script(&script_path, tx);

        if let Ok(client) = client_result {
            // Wait for initialization
            let timeout = std::time::Duration::from_secs(5);
            let start = std::time::Instant::now();

            let mut initialized = false;
            while start.elapsed() < timeout {
                match rx.try_recv() {
                    Ok(LspEvent::ServerReady) => {
                        initialized = true;
                        break;
                    }
                    Ok(_) => continue,
                    Err(std::sync::mpsc::TryRecvError::Empty) => {
                        std::thread::sleep(std::time::Duration::from_millis(10));
                    }
                    Err(std::sync::mpsc::TryRecvError::Disconnected) => break,
                }
            }

            assert!(initialized, "Server should have initialized");

            // Drop should eventually kill the unresponsive server
            // Drop waits 500ms (10 * 50ms), then kills
            let drop_start = std::time::Instant::now();
            drop(client);
            let drop_duration = drop_start.elapsed();

            // Should complete within reasonable time even for unresponsive server
            // Drop waits 500ms then kills, so total should be < 2s
            assert!(
                drop_duration < std::time::Duration::from_secs(3),
                "Drop hung on unresponsive server: {:?}",
                drop_duration
            );
        }

        cleanup_mock_script(&script_path);
    }

    #[test]
    fn test_lsp_client_drop_handles_already_dead_process() {
        // Test that Drop handles a process that has already exited

        let script_path = create_mock_lsp_server_script(MockServerBehavior::RespondAndExit);
        let (tx, rx) = std::sync::mpsc::channel();

        let client_result = start_client_with_mock_script(&script_path, tx);

        if let Ok(client) = client_result {
            // Wait for server to exit naturally
            std::thread::sleep(std::time::Duration::from_millis(500));

            // Drain any events
            while rx.try_recv().is_ok() {}

            // Drop should handle already-dead process gracefully
            let drop_start = std::time::Instant::now();
            drop(client);
            let drop_duration = drop_start.elapsed();

            // Should be very fast since process is already dead
            assert!(
                drop_duration < std::time::Duration::from_secs(1),
                "Drop took too long for dead process: {:?}",
                drop_duration
            );
        }

        cleanup_mock_script(&script_path);
    }

    #[test]
    fn test_lsp_client_raii_cleanup_on_init_failure() {
        // Test that RAII Drop cleans up the process even if initialize() would fail
        // We use a server that hangs forever without responding

        let script_path = create_mock_lsp_server_script(MockServerBehavior::HangForever);
        let (tx, _rx) = std::sync::mpsc::channel::<LspEvent>();

        // Note: LspClient::start() calls initialize() which sends a message.
        // The HangForever server never responds, but the message is sent.
        // The test verifies that if we get a client, dropping it cleans up.

        std::env::set_var("CRYSTAL_NODE_PATH", "bash");

        // Spawn the child process manually to simulate partial initialization
        let mut child = std::process::Command::new("bash")
            .arg(
                script_path
                    .to_str()
                    .expect("Mock script path must be valid UTF-8"),
            )
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
            .expect("Failed to spawn process");

        let pid = child.id();

        // Create a minimal LspClient struct for testing Drop
        let stdin = child
            .stdin
            .take()
            .expect("stdin pipe should be available after spawn with Stdio::piped()");
        let _stdout = child
            .stdout
            .take()
            .expect("stdout pipe should be available after spawn with Stdio::piped()");

        let client = LspClient {
            stdin,
            request_id: 0,
            initialize_id: Arc::new(AtomicI32::new(0)),
            child,
        };

        // Verify process is running
        #[cfg(unix)]
        {
            use std::process::Command;
            let status = Command::new("kill").args(["-0", &pid.to_string()]).status();
            assert!(
                status.map(|s| s.success()).unwrap_or(false),
                "Process should be running before drop"
            );
        }

        // Drop should kill the hanging process
        let drop_start = std::time::Instant::now();
        drop(client);
        let drop_duration = drop_start.elapsed();

        // Verify process is dead
        #[cfg(unix)]
        {
            use std::process::Command;
            // Small delay to allow process to fully terminate
            std::thread::sleep(std::time::Duration::from_millis(100));
            let status = Command::new("kill").args(["-0", &pid.to_string()]).status();
            assert!(
                !status.map(|s| s.success()).unwrap_or(true),
                "Process should be dead after drop"
            );
        }

        assert!(
            drop_duration < std::time::Duration::from_secs(3),
            "Drop should complete within timeout: {:?}",
            drop_duration
        );

        std::env::remove_var("CRYSTAL_NODE_PATH");
        drop(tx);
        cleanup_mock_script(&script_path);
    }

    #[test]
    fn test_lsp_client_start_nonexistent_node_binary() {
        // Test that start() returns error when the node binary doesn't exist
        // Note: We can't test nonexistent server.js because node spawns successfully
        // and only fails after loading - that's handled by the reader thread.

        let (tx, _rx) = std::sync::mpsc::channel::<LspEvent>();

        // Set CRYSTAL_NODE_PATH to a nonexistent binary
        std::env::set_var(
            "CRYSTAL_NODE_PATH",
            "/nonexistent/binary/that/does/not/exist",
        );

        let result = LspClient::start("server.js", tx);

        std::env::remove_var("CRYSTAL_NODE_PATH");

        assert!(result.is_err(), "Should fail for nonexistent node binary");
        let err = result.err().unwrap();
        let err_msg = err.to_string();
        assert!(
            err_msg.contains("Failed to spawn") || err_msg.contains("No such file"),
            "Error should mention spawn failure: {}",
            err_msg
        );
    }

    #[test]
    fn test_lsp_client_multiple_lifecycle_cycles() {
        // Test that we can create and drop multiple LspClients without resource leaks

        for i in 0..3 {
            let script_path = create_mock_lsp_server_script(MockServerBehavior::RespondAndExit);
            let (tx, rx) = std::sync::mpsc::channel();

            let client_result = start_client_with_mock_script(&script_path, tx);

            if let Ok(client) = client_result {
                // Wait briefly for initialization
                let timeout = std::time::Duration::from_secs(2);
                let start = std::time::Instant::now();

                while start.elapsed() < timeout {
                    match rx.try_recv() {
                        Ok(LspEvent::ServerReady) => break,
                        Ok(_) => continue,
                        Err(std::sync::mpsc::TryRecvError::Empty) => {
                            std::thread::sleep(std::time::Duration::from_millis(10));
                        }
                        Err(std::sync::mpsc::TryRecvError::Disconnected) => break,
                    }
                }

                drop(client);
            }

            cleanup_mock_script(&script_path);

            // Small delay between cycles
            if i < 2 {
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
        }

        // If we get here without panics or hangs, the test passes
    }
}
