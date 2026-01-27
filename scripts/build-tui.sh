#!/usr/bin/env bash
# Build the Rust TUI with the correct Python version
#
# Usage: ./scripts/build-tui.sh [--clean]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Use the project's venv Python for PyO3 compilation
export PYO3_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -f "$PYO3_PYTHON" ]]; then
    echo "Error: Python venv not found at $PYO3_PYTHON"
    echo "Run: uv venv && uv pip install -e python/"
    exit 1
fi

PYTHON_VERSION=$("$PYO3_PYTHON" --version)
echo "Building with $PYTHON_VERSION"

if [[ "$1" == "--clean" ]]; then
    echo "Cleaning previous build..."
    cargo clean
fi

cargo build --release

echo ""
echo "Build complete! Run with:"
echo "  ./target/release/crystalmath"
echo ""
echo "Or from any directory:"
echo "  $PROJECT_ROOT/target/release/crystalmath"
