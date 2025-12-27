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

impl LspClient {
    /// Spawn the LSP server and start the reader thread.
    ///
    /// # Arguments
    /// * `server_path` - Path to the server.js file
    /// * `event_tx` - Channel to send LSP events to the main thread
    ///
    /// # Process Cleanup Safety
    /// The `LspClient` is created early to take ownership of the child process.
    /// If `initialize()` fails, the `Drop` implementation will clean up the
    /// spawned process, preventing orphaned node processes.
    pub fn start(server_path: &str, event_tx: Sender<LspEvent>) -> Result<Self> {
        info!("Starting LSP server: {}", server_path);

        let mut child = Command::new("node")
            .arg(server_path)
            .arg("--stdio")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .context("Failed to spawn node process for LSP server")?;

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
                        debug!("LSP server stdout closed");
                        return; // EOF - exit thread
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
        let notification = json!({
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {}
        });
        self.send(&notification)
    }

    /// Notify the server that a document was opened.
    pub fn did_open(&mut self, file_path: &str, text: &str) -> Result<()> {
        let lang_id = DftCodeType::from_filename(file_path)
            .map(|t| t.language_id())
            .unwrap_or("plaintext");

        let uri = Self::path_to_uri(file_path);

        debug!("LSP didOpen: {} (language: {})", uri, lang_id);

        let notification = json!({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": lang_id,
                    "version": 1,
                    "text": text
                }
            }
        });
        self.send(&notification)
    }

    /// Notify the server that a document changed.
    pub fn did_change(&mut self, file_path: &str, version: i32, text: &str) -> Result<()> {
        let uri = Self::path_to_uri(file_path);

        debug!("LSP didChange: {} (version: {})", uri, version);

        let notification = json!({
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "version": version
                },
                "contentChanges": [{"text": text}]
            }
        });
        self.send(&notification)
    }

    /// Notify the server that a document was closed.
    pub fn did_close(&mut self, file_path: &str) -> Result<()> {
        let uri = Self::path_to_uri(file_path);

        debug!("LSP didClose: {}", uri);

        let notification = json!({
            "jsonrpc": "2.0",
            "method": "textDocument/didClose",
            "params": {
                "textDocument": {
                    "uri": uri
                }
            }
        });
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
        let shutdown = json!({
            "jsonrpc": "2.0",
            "id": self.next_id(),
            "method": "shutdown",
            "params": null
        });
        let _ = self.send(&shutdown);

        let exit = json!({
            "jsonrpc": "2.0",
            "method": "exit",
            "params": null
        });
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
        assert_eq!(
            DftCodeType::from_filename("INCAR"),
            Some(DftCodeType::Vasp)
        );
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
        assert_eq!(
            DiagnosticSeverity::from_i32(1),
            DiagnosticSeverity::Error
        );
        assert_eq!(
            DiagnosticSeverity::from_i32(2),
            DiagnosticSeverity::Warning
        );
        assert_eq!(
            DiagnosticSeverity::from_i32(3),
            DiagnosticSeverity::Information
        );
        assert_eq!(
            DiagnosticSeverity::from_i32(4),
            DiagnosticSeverity::Hint
        );
        assert_eq!(
            DiagnosticSeverity::from_i32(99),
            DiagnosticSeverity::Error
        ); // Default
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
        assert_eq!(DftCodeType::from_filename("poscar"), Some(DftCodeType::Vasp));
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
}
