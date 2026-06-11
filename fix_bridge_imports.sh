#!/bin/bash
set -e

echo "=== 1. Restoring the Module Declaration Baseline ==="
# Restore src/lib.rs and src/main.rs to make crate::bridge discoverable again
git checkout src/lib.rs src/main.rs 2>/dev/null || true

# Re-apply Step 1 cleanly to ensure pyo3-bridge feature is disabled by default
python3 -c "
with open('Cargo.toml', 'r') as f:
    content = f.read()
content = content.replace('default = [\"pyo3-bridge\"]', 'default = []')
with open('Cargo.toml', 'w') as f:
    f.write(content)
"

echo "=== 2. Conditioning src/bridge.rs for Pure IPC Execution ==="
# We will inject feature gates at the top of src/bridge.rs so that its PyO3 hooks
# are compiled out completely when running native IPC mode, while leaving the generic
# JSON-RPC definitions visible for the client channels.
python3 -c "
with open('src/bridge.rs', 'r') as f:
    content = f.read()

# If not already gated, wrap the pyo3 use statements
if 'use pyo3::prelude::*;' in content and '#[cfg(feature = \"pyo3-bridge\")]' not in content:
    content = content.replace('use pyo3::prelude::*;', '#[cfg(feature = \"pyo3-bridge\")]\nuse pyo3::prelude::*;')
    content = content.replace('use pyo3::types::PyAnyMethods;', '#[cfg(feature = \"pyo3-bridge\")]\nuse pyo3::types::PyAnyMethods;')

with open('src/bridge.rs', 'w') as f:
    f.write(content)
print('✅ Python runtime imports inside src/bridge.rs feature-gated.')
"

echo "=== 3. Re-running Compilation Quality Gate ==="
cargo check --all-targets
