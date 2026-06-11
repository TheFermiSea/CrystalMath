#!/bin/bash
set -e

echo "=== 1. Restoring PyO3 Embedding Features in Cargo.toml ==="
# Swap extension-module out for auto-initialize so the binary links correctly
python3 -c "
with open('Cargo.toml', 'r') as f:
    content = f.read()

bad_line = 'pyo3 = { version = \"0.27.2\", features = [\"extension-module\", \"abi3-py312\"], optional = true }'
good_line = 'pyo3 = { version = \"0.27.2\", features = [\"auto-initialize\"], optional = true }'

if bad_line in content:
    content = content.replace(bad_line, good_line)
    with open('Cargo.toml', 'w') as f:
        f.write(content)
    print('✅ Cargo.toml updated for standalone binary embedding.')
else:
    print('⚠️ Target feature line not found or already changed.')
"

echo "=== 2. Resolving Python Environment Pointer ==="
# Query uv to get the precise interpreter path for PyO3 compile time linkage
export PYO3_PYTHON=$(uv python find)
echo "🐍 Linking against: $PYO3_PYTHON"

echo "=== 3. Re-running High-Performance Release Build ==="
cargo run --release
