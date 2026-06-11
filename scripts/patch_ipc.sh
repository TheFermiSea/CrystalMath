#!/bin/bash
set -e

echo "=== Injecting Zero-Copy IPC Framing Architecture ==="

# 1. Create/Overwrite the Rust IPC framing module
mkdir -p src/ipc
cat <<'EOF' >src/ipc/framing.rs
use serde::{Deserialize, Serialize};
use std::borrow::Cow;

/// Header defining the payload length to allow predictable buffer allocations.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[repr(C)]
pub struct FrameHeader {
    pub magic: [u8; 4], // b"CMAT"
    pub payload_len: u32,
    pub message_type: u16,
}

/// Zero-copy data frame that borrows directly from the network/stream ring buffer.
/// Enforces zero allocations during high-throughput log streaming from VASP/CRYSTAL23.
#[derive(Deserialize, Serialize, Debug, Clone, PartialEq)]
pub struct ZeroCopyFrame<'a> {
    pub job_id: u64,
    #[serde(borrow)]
    pub code_engine: &'a str,    // e.g., "crystal23", "vasp", "qe"
    #[serde(borrow)]
    pub stream_channel: &'a str, // e.g., "stdout", "stderr", "slurm_evt"
    #[serde(borrow)]
    pub payload: &'a str,        // Direct slice from the ring buffer
}

impl<'a> ZeroCopyFrame<'a> {
    /// Safe deserialization interface bounded to the input buffer lifetime
    #[inline]
    pub fn from_slice(slice: &'a [u8]) -> Result<Self, bincode::Error> {
        // Using bincode or json depending on your protocol format config.
        // For zero-copy text string fields, JSON or Postcard/Bincode borrowed configs work natively.
        serde_json::from_slice(slice)
    }
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

# 2. Update the Python side to support matching zero-allocation payloads
mkdir -p python/crystalmath/server
cat <<'EOF' >python/crystalmath/server/framing.py
import struct
import json
from typing import Dict, Any

class IPCFrameEncoder:
    """
    High-performance frame encoder matching the Rust layout.
    Prefixes payloads with binary headers to prevent text scanning over sockets.
    """
    MAGIC = b"CMAT"
    HEADER_FORMAT = "!4sIH" # Magic, Payload Len, Msg Type

    @classmethod
    def encode_frame(cls, job_id: int, code_engine: str, stream_channel: str, payload: str, msg_type: int = 1) -> bytes:
        frame_dict = {
            "job_id": job_id,
            "code_engine": code_engine,
            "stream_channel": stream_channel,
            "payload": payload
        }
        serialized = json.dumps(frame_dict, separators=(',', ':')).encode('utf-8')
        header = struct.pack(cls.HEADER_FORMAT, cls.MAGIC, len(serialized), msg_type)
        return header + serialized
EOF

echo "✅ Zero-copy framing logic injected successfully."
