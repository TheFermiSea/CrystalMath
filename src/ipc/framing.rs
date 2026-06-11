#![allow(dead_code)]
use serde::{Deserialize, Serialize};
use std::io::{Error as IoError, ErrorKind, Result as IoResult};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

/// Header defining the payload length to allow predictable buffer allocations.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[repr(C)]
#[allow(dead_code)]
pub struct FrameHeader {
    pub magic: [u8; 4], // b"CMAT"
    pub payload_len: u32,
    pub message_type: u16,
}

/// Zero-copy data frame that borrows directly from the network/stream buffer.
#[derive(Deserialize, Serialize, Debug, Clone, PartialEq)]
#[allow(dead_code)]
pub struct ZeroCopyFrame<'a> {
    pub job_id: u64,
    #[serde(borrow)]
    pub code_engine: &'a str,
    #[serde(borrow)]
    pub stream_channel: &'a str,
    #[serde(borrow)]
    pub payload: &'a str,
}

impl<'a> ZeroCopyFrame<'a> {
    #[inline]
    pub fn from_slice(slice: &'a [u8]) -> Result<Self, serde_json::Error> {
        serde_json::from_slice(slice)
    }
}

/// Reads a fixed message frame asynchronously from a Tokio stream.
pub async fn read_message<R: AsyncRead + Unpin>(mut stream: R) -> IoResult<Vec<u8>> {
    let mut header_buf = [0u8; 10]; // 4 (magic) + 4 (u32 len) + 2 (u16 type)
    stream.read_exact(&mut header_buf).await?;

    if &header_buf[0..4] != b"CMAT" {
        return Err(IoError::new(
            ErrorKind::InvalidData,
            "Invalid CMAT magic header",
        ));
    }

    let payload_len =
        u32::from_be_bytes([header_buf[4], header_buf[5], header_buf[6], header_buf[7]]) as usize;

    let mut payload_buf = vec![0u8; payload_len];
    stream.read_exact(&mut payload_buf).await?;

    Ok(payload_buf)
}

/// Writes a fixed message frame asynchronously over a Tokio stream.
pub async fn write_message<W: AsyncWrite + Unpin>(
    mut stream: W,
    payload: &[u8],
    message_type: u16,
) -> IoResult<()> {
    let payload_len = payload.len() as u32;

    stream.write_all(b"CMAT").await?;
    stream.write_all(&payload_len.to_be_bytes()).await?;
    stream.write_all(&message_type.to_be_bytes()).await?;

    stream.write_all(payload).await?;
    stream.flush().await?;

    Ok(())
}

/// A structure to handle incoming packet boundaries without allocating intermediate vectors
#[allow(dead_code)]
pub struct ZeroCopyRingBuffer {
    buffer: Vec<u8>,
    head: usize,
    tail: usize,
}

impl ZeroCopyRingBuffer {
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            buffer: vec![0; capacity],
            head: 0,
            tail: 0,
        }
    }

    #[inline]
    pub fn as_slice(&self) -> &[u8] {
        &self.buffer[self.head..self.tail]
    }

    #[inline]
    pub fn consume(&mut self, amt: usize) {
        self.head = std::cmp::min(self.head + amt, self.tail);
        if self.head == self.tail {
            self.head = 0;
            self.tail = 0;
        }
    }
}
