//! Content-Length message framing for JSON-RPC over Unix sockets.
//!
//! This module implements HTTP-style Content-Length framing, the same protocol
//! used by the Language Server Protocol (LSP). This enables reliable message
//! boundaries over stream-oriented sockets.
//!
//! # Wire Format
//!
//! ```text
//! Content-Length: <length>\r\n
//! \r\n
//! <message-body>
//! ```
//!
//! The header parsing is case-insensitive and handles both CRLF and LF line endings.

use anyhow::{anyhow, Context, Result};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::unix::{OwnedReadHalf, OwnedWriteHalf};

/// Maximum message size (100MB) to prevent OOM from malicious/buggy servers.
const MAX_MESSAGE_SIZE: usize = 100 * 1024 * 1024;

/// Read a Content-Length framed message from the stream.
///
/// # Protocol
///
/// 1. Read headers until an empty line (handles both CRLF and LF)
/// 2. Extract Content-Length header (case-insensitive)
/// 3. Read exactly that many bytes for the body
///
/// # Errors
///
/// Returns an error if:
/// - The stream is closed (EOF)
/// - No Content-Length header is found
/// - Content-Length exceeds MAX_MESSAGE_SIZE (100MB)
/// - The body cannot be read completely
/// - The body is not valid UTF-8
///
/// # Example
///
/// ```ignore
/// let message = read_message(&mut reader).await?;
/// let response: JsonRpcResponse = serde_json::from_str(&message)?;
/// ```
pub async fn read_message(reader: &mut BufReader<OwnedReadHalf>) -> Result<String> {
    // Read headers until blank line
    let mut content_length: Option<usize> = None;

    loop {
        let mut line = String::new();
        let bytes_read = reader
            .read_line(&mut line)
            .await
            .context("Failed to read header line")?;

        // EOF - connection closed
        if bytes_read == 0 {
            return Err(anyhow!("Connection closed by server"));
        }

        // Trim both CRLF and LF line endings
        let trimmed = line.trim();

        // Empty line signals end of headers
        if trimmed.is_empty() {
            break;
        }

        // Parse Content-Length header (case-insensitive per HTTP spec)
        if let Some(colon_pos) = trimmed.find(':') {
            let key = trimmed[..colon_pos].trim();
            let value = trimmed[colon_pos + 1..].trim();

            if key.eq_ignore_ascii_case("Content-Length") {
                content_length = Some(
                    value
                        .parse()
                        .with_context(|| format!("Invalid Content-Length value: {}", value))?,
                );
            }
            // Ignore other headers (e.g., Content-Type)
        }
    }

    // Validate Content-Length was present
    let size = content_length.ok_or_else(|| anyhow!("Missing Content-Length header"))?;

    // Validate size is within bounds
    if size > MAX_MESSAGE_SIZE {
        return Err(anyhow!(
            "Message size {} exceeds maximum {} bytes",
            size,
            MAX_MESSAGE_SIZE
        ));
    }

    // Read message body
    let mut body = vec![0u8; size];
    reader
        .read_exact(&mut body)
        .await
        .context("Failed to read message body")?;

    // Convert to UTF-8
    String::from_utf8(body).context("Message body is not valid UTF-8")
}

/// Write a Content-Length framed message to the stream.
///
/// # Protocol
///
/// Writes the message in the format:
/// ```text
/// Content-Length: <length>\r\n
/// \r\n
/// <body>
/// ```
///
/// # Errors
///
/// Returns an error if the write or flush fails.
///
/// # Example
///
/// ```ignore
/// let request = serde_json::to_string(&json_rpc_request)?;
/// write_message(&mut writer, &request).await?;
/// ```
pub async fn write_message(writer: &mut OwnedWriteHalf, body: &str) -> Result<()> {
    let body_bytes = body.as_bytes();
    let header = format!("Content-Length: {}\r\n\r\n", body_bytes.len());

    writer
        .write_all(header.as_bytes())
        .await
        .context("Failed to write message header")?;

    writer
        .write_all(body_bytes)
        .await
        .context("Failed to write message body")?;

    writer.flush().await.context("Failed to flush message")?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::UnixStream;

    /// Create a connected pair of Unix sockets for testing.
    async fn socket_pair() -> (OwnedReadHalf, OwnedWriteHalf, OwnedReadHalf, OwnedWriteHalf) {
        let (client, server) = UnixStream::pair().expect("Failed to create socket pair");
        let (client_read, client_write) = client.into_split();
        let (server_read, server_write) = server.into_split();
        (client_read, client_write, server_read, server_write)
    }

    #[tokio::test]
    async fn test_write_read_roundtrip() {
        let (client_read, mut client_write, _server_read, _server_write) = socket_pair().await;

        let message = r#"{"jsonrpc":"2.0","method":"test","id":1}"#;

        // Write message from client
        write_message(&mut client_write, message)
            .await
            .expect("Write failed");

        // Read message on server side
        let mut reader = BufReader::new(client_read);
        let received = read_message(&mut reader).await.expect("Read failed");

        assert_eq!(received, message);
    }

    #[tokio::test]
    async fn test_read_missing_content_length() {
        let (client_read, mut client_write, _server_read, _server_write) = socket_pair().await;

        // Write raw data without Content-Length header
        client_write
            .write_all(b"\r\n{}\r\n")
            .await
            .expect("Write failed");

        // Need to close the write end so reader sees the headers are complete
        drop(client_write);

        let mut reader = BufReader::new(client_read);
        let result = read_message(&mut reader).await;

        assert!(result.is_err());
        let err_msg = result.unwrap_err().to_string();
        assert!(
            err_msg.contains("Missing Content-Length"),
            "Expected 'Missing Content-Length' error, got: {}",
            err_msg
        );
    }

    #[tokio::test]
    async fn test_read_handles_crlf_and_lf() {
        let (client_read, mut client_write, _server_read, _server_write) = socket_pair().await;

        // Write with mixed line endings (CRLF in header, body follows)
        let body = r#"{"test":true}"#;
        let raw = format!("Content-Length: {}\r\n\r\n{}", body.len(), body);
        client_write
            .write_all(raw.as_bytes())
            .await
            .expect("Write failed");

        let mut reader = BufReader::new(client_read);
        let received = read_message(&mut reader).await.expect("Read failed");

        assert_eq!(received, body);
    }

    #[tokio::test]
    async fn test_read_case_insensitive_header() {
        let (client_read, mut client_write, _server_read, _server_write) = socket_pair().await;

        // Write with lowercase header name
        let body = r#"{"test":true}"#;
        let raw = format!("content-length: {}\r\n\r\n{}", body.len(), body);
        client_write
            .write_all(raw.as_bytes())
            .await
            .expect("Write failed");

        let mut reader = BufReader::new(client_read);
        let received = read_message(&mut reader).await.expect("Read failed");

        assert_eq!(received, body);
    }

    #[tokio::test]
    async fn test_read_rejects_oversized_message() {
        let (client_read, mut client_write, _server_read, _server_write) = socket_pair().await;

        // Claim a huge Content-Length (larger than MAX_MESSAGE_SIZE)
        let raw = format!("Content-Length: {}\r\n\r\n", MAX_MESSAGE_SIZE + 1);
        client_write
            .write_all(raw.as_bytes())
            .await
            .expect("Write failed");

        let mut reader = BufReader::new(client_read);
        let result = read_message(&mut reader).await;

        assert!(result.is_err());
        let err_msg = result.unwrap_err().to_string();
        assert!(
            err_msg.contains("exceeds maximum"),
            "Expected size error, got: {}",
            err_msg
        );
    }
}
