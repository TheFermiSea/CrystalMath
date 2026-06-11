#!/bin/bash
set -e

echo "=== Updating Client JSON Deserialization to Direct Slice Parsing ==="

# Patch client.rs line 616 to use from_slice instead of from_str on the raw byte vector
sed -i '' 's/serde_json::from_str(&response_json)/serde_json::from_slice(\&response_json)/g' src/ipc/client.rs

echo "=== Verifying Build State ==="
cargo clippy --all-targets

echo "🚀 Codebase unified and fully compiled!"
