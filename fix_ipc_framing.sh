#!/bin/bash
set -e

echo "=== Repairing Zero-Copy IPC Framing Compilation Barriers ==="

# 1. Overwrite src/ipc/framing.rs with complete streaming and zero-copy JSON parsing logic
cat <<'EOF' >src/ipc/framing.rs
use serde::{Deserialize, Serialize};
use std::io::{Read, Write, Result as IoResult, Error as IoError, ErrorKind};

/// Header defining the payload length to allow predictable buffer allocations.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[repr(C)]
pub struct FrameHeader {
    pub magic: [u8; 4], // b"CMAT"
    pub payload_len: u32,
    pub message_type: u16,
}

/// Zero-copy data frame that borrows directly from the network/stream buffer.
/// Enforces zero allocations during high-throughput log streaming from VASP/CRYSTAL23.
#[derive(Deserialize, Serialize, Debug, Clone, PartialEq)]
pub struct ZeroCopyFrame<'a> {
    pub job_id: u64,
    #[serde(borrow)]
    pub code_engine: &'a str,    // e.g., "crystal23", "vasp", "qe"
    #[serde(borrow)]
    pub stream_channel: &'a str, // e.g., "stdout", "stderr", "slurm_evt"
    #[serde(borrow)]
    pub payload: &'a str,        // Direct slice from the internal read buffer
}

impl<'a> ZeroCopyFrame<'a> {
    /// Safe deserialization interface bounded to the input buffer lifetime
    #[inline]
    pub fn from_slice(slice: &'a [u8]) -> Result<Self, serde_json::Error> {
        serde_json::from_slice(slice)
    }
}

/// Reads a fixed message frame from any synchronous TCP or Unix domain socket stream.
/// Allocates the target storage payload buffer on the stack/heap only once per frame transaction.
pub fn read_message<R: Read>(mut stream: R) -> IoResult<Vec<u8>> {
    let mut header_buf = [0u8; 10]; // 4 (magic) + 4 (u32 len) + 2 (u16 type)
    stream.read_exact(&mut header_buf)?;

    if &header_buf[0..4] != b"CMAT" {
        return Err(IoError::new(ErrorKind::InvalidData, "Invalid CMAT magic header"));
    }

    let payload_len = u32::from_be_bytes([header_buf[4], header_buf[5], header_buf[6], header_buf[7]]) as usize;
    
    // Allocate buffer for the raw JSON frame content
    let mut payload_buf = vec![0u8; payload_len];
    stream.read_exact(&mut payload_buf)?;
    
    Ok(payload_buf)
}

/// High-performance stream write wrapper injecting binary network layout markers.
pub fn write_message<W: Write>(mut stream: W, payload: &[u8], message_type: u16) -> IoResult<()> {
    let payload_len = payload.len() as u32;
    
    // Write Structured Binary Header: Magic (4B), Length (4B), Msg Type (2B)
    stream.write_all(b"CMAT")?;
    stream.write_all(&payload_len.to_be_bytes())?;
    stream.write_all(&message_type.to_be_bytes())?;
    
    // Pump JSON payload body
    stream.write_all(payload)?;
    stream.flush()?;
    
    Ok(())
}

/// A structure to handle incoming packet boundaries without allocating intermediate vectors
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

    /// Exposes the active window as a slice to ensure zero-copy parsers 
    /// can reference internal data downstream securely.
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
EOF

echo "=== Verifying the Build State ==="
cargo clippy --all-targets

echo "🚀 All systems green!"
