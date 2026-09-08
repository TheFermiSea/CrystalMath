use std::io::{Error as IoError, ErrorKind, Result as IoResult};
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncReadExt, AsyncWrite, AsyncWriteExt};

/// Reads one Content-Length-framed message (HTTP-style headers, same as LSP)
/// asynchronously from a Tokio stream.
///
/// This must match the wire format `crystalmath-server` actually implements
/// (`python/crystalmath/server/__init__.py`). An earlier version of this
/// function spoke a bespoke binary `CMAT`-magic-header format that no
/// consumer (Rust or Python) ever implemented on the other end — every
/// `IpcClient::call_rpc` request timed out because the server was waiting for
/// `Content-Length` headers that never arrived. See ADR-034.
pub async fn read_message<R: AsyncBufRead + Unpin>(mut stream: R) -> IoResult<Vec<u8>> {
    let mut content_length: Option<usize> = None;

    loop {
        let mut header = String::new();
        let n = stream.read_line(&mut header).await?;
        if n == 0 {
            return Err(IoError::new(
                ErrorKind::UnexpectedEof,
                "Connection closed while reading message headers",
            ));
        }

        let trimmed = header.trim();
        if trimmed.is_empty() {
            break; // blank line ends the header block
        }

        if let Some(colon_pos) = trimmed.find(':') {
            let key = trimmed[..colon_pos].trim();
            let value = trimmed[colon_pos + 1..].trim();
            if key.eq_ignore_ascii_case("Content-Length") {
                content_length = value.parse::<usize>().ok();
            }
        }
        // Other headers (e.g. Content-Type) are ignored, same as the LSP client.
    }

    let size = content_length
        .ok_or_else(|| IoError::new(ErrorKind::InvalidData, "Missing Content-Length header"))?;

    // Mirrors the LSP client's cap (src/lsp.rs) against a malicious/buggy peer.
    const MAX_MESSAGE_SIZE: usize = 100 * 1024 * 1024;
    if size > MAX_MESSAGE_SIZE {
        return Err(IoError::new(
            ErrorKind::InvalidData,
            format!("Message exceeds size limit: {size} bytes"),
        ));
    }

    let mut payload = vec![0u8; size];
    stream.read_exact(&mut payload).await?;
    Ok(payload)
}

/// Writes one Content-Length-framed message asynchronously over a Tokio stream.
pub async fn write_message<W: AsyncWrite + Unpin>(mut stream: W, payload: &[u8]) -> IoResult<()> {
    let header = format!("Content-Length: {}\r\n\r\n", payload.len());
    stream.write_all(header.as_bytes()).await?;
    stream.write_all(payload).await?;
    stream.flush().await?;
    Ok(())
}
