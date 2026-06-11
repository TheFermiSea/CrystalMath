#!/bin/bash
set -e

echo "=== 1. Surgically Patching Cargo.toml Dependency Alignment ==="
# Restore the optional flag to the pyo3 declaration while preserving extension features
python3 -c "
with open('Cargo.toml', 'r') as f:
    content = f.read()

bad_line = 'pyo3 = { version = \"0.27.2\", features = [\"extension-module\", \"abi3-py312\"] }'
good_line = 'pyo3 = { version = \"0.27.2\", features = [\"extension-module\", \"abi3-py312\"], optional = true }'

if bad_line in content:
    content = content.replace(bad_line, good_line)
    with open('Cargo.toml', 'w') as f:
        f.write(content)
    print('✅ Cargo.toml pyo3 dependency marked optional.')
else:
    print('⚠️ Target line not found or already patched.')
"

echo "=== 2. Re-verifying Environment Packages ==="
uv sync

echo "=== 3. Executing High-Performance Build Pipeline ==="
cargo run --release
