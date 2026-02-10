#!/usr/bin/env bash
# Composite pre-push hook: quality checks + beads sync
# Installed by scripts/install-hooks.sh
# --- quality checks section ---

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If running from .git/hooks, resolve project root
if [[ "$SCRIPT_DIR" == *".git/hooks"* ]]; then
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
else
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# Save stdin for bd delegation (git passes ref info via stdin)
STDIN_DATA=$(cat)

# Determine changed files vs remote tracking branch
REMOTE=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null | sed 's|/| |' | awk '{print $1}') || REMOTE="origin"
MERGE_BASE=$(git merge-base HEAD "${REMOTE}/$(git rev-parse --abbrev-ref HEAD)" 2>/dev/null || echo "HEAD~1")
CHANGED_FILES=$(git diff --name-only "$MERGE_BASE" HEAD 2>/dev/null || git diff --name-only HEAD~1 HEAD 2>/dev/null || echo "")

# Detect which components changed
HAS_PYTHON=false
HAS_RUST=false
HAS_CLI=false

while IFS= read -r file; do
    case "$file" in
        python/*|tui/*) HAS_PYTHON=true ;;
        src/*|Cargo.toml|Cargo.lock) HAS_RUST=true ;;
        cli/*) HAS_CLI=true ;;
    esac
done <<< "$CHANGED_FILES"

FAILURES=0
WARNINGS=0

echo "=== Pre-push quality checks ==="
echo ""

# --- Python checks ---
if $HAS_PYTHON; then
    echo "▸ Python changes detected"

    # Format check (hard gate)
    echo "  Checking ruff format..."
    if ! uv run ruff format --check python/ tui/ > /dev/null 2>&1; then
        echo "  ✗ Ruff format check failed. Run: uv run ruff format python/ tui/"
        FAILURES=$((FAILURES + 1))
    else
        echo "  ✓ Format OK"
    fi

    # Lint (warning only)
    echo "  Checking ruff lint..."
    if ! uv run ruff check python/ tui/ > /dev/null 2>&1; then
        echo "  ⚠ Ruff lint warnings (non-blocking)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo "  ✓ Lint OK"
    fi

    # Tests (hard gate)
    echo "  Running Python tests..."
    if ! uv run pytest python/tests/ -x -q --tb=line 2>/dev/null; then
        echo "  ✗ Python tests failed"
        FAILURES=$((FAILURES + 1))
    else
        echo "  ✓ Tests passed"
    fi

    echo ""
fi

# --- Rust checks ---
if $HAS_RUST; then
    echo "▸ Rust changes detected"

    # Format check (hard gate)
    echo "  Checking cargo fmt..."
    if ! cargo fmt --check > /dev/null 2>&1; then
        echo "  ✗ cargo fmt check failed. Run: cargo fmt"
        FAILURES=$((FAILURES + 1))
    else
        echo "  ✓ Format OK"
    fi

    # Clippy (warning only)
    echo "  Running clippy..."
    if ! cargo clippy -- -D warnings > /dev/null 2>&1; then
        echo "  ⚠ Clippy warnings (non-blocking)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo "  ✓ Clippy OK"
    fi

    echo ""
fi

# --- CLI checks ---
if $HAS_CLI; then
    echo "▸ CLI changes detected"

    if command -v bats > /dev/null 2>&1; then
        echo "  Running CLI unit tests..."
        if ! bats cli/tests/unit/*.bats > /dev/null 2>&1; then
            echo "  ✗ CLI unit tests failed"
            FAILURES=$((FAILURES + 1))
        else
            echo "  ✓ Tests passed"
        fi
    else
        echo "  ⚠ bats not installed, skipping CLI tests"
        WARNINGS=$((WARNINGS + 1))
    fi

    echo ""
fi

# --- No changes detected ---
if ! $HAS_PYTHON && ! $HAS_RUST && ! $HAS_CLI; then
    echo "  No Python/Rust/CLI changes detected, skipping quality checks"
    echo ""
fi

# --- Summary ---
if [ "$FAILURES" -gt 0 ]; then
    echo "✗ $FAILURES check(s) failed, $WARNINGS warning(s). Push blocked."
    echo "  Fix issues and try again."
    exit 1
fi

if [ "$WARNINGS" -gt 0 ]; then
    echo "⚠ $WARNINGS warning(s), all hard gates passed."
fi

echo "✓ All quality checks passed"
echo ""

# --- Delegate to beads pre-push hook ---
if command -v bd > /dev/null 2>&1; then
    echo "=== Beads sync ==="
    echo "$STDIN_DATA" | bd hooks run pre-push "$@"
fi
