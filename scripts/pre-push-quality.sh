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

NULL_SHA="0000000000000000000000000000000000000000"
EMPTY_TREE="$(git hash-object -t tree /dev/null)"

resolve_changed_files_from_stdin() {
    local local_ref local_sha remote_ref remote_sha

    while read -r local_ref local_sha remote_ref remote_sha; do
        [[ -z "${local_ref:-}" ]] && continue

        if [[ "$local_sha" == "$NULL_SHA" ]]; then
            continue
        fi

        if [[ "$remote_sha" == "$NULL_SHA" ]]; then
            git diff --name-only "$EMPTY_TREE" "$local_sha" 2>/dev/null || true
        else
            git diff --name-only "$remote_sha" "$local_sha" 2>/dev/null || true
        fi
    done <<< "$STDIN_DATA"
}

resolve_changed_files_from_history() {
    local upstream_ref merge_base

    upstream_ref="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
    if [[ -n "$upstream_ref" ]]; then
        merge_base="$(git merge-base HEAD "$upstream_ref" 2>/dev/null || true)"
        if [[ -n "$merge_base" ]]; then
            git diff --name-only "$merge_base" HEAD 2>/dev/null || true
            return
        fi
    fi

    if git rev-parse --verify HEAD^ >/dev/null 2>&1; then
        git diff --name-only HEAD^ HEAD 2>/dev/null || true
    else
        git diff --name-only "$EMPTY_TREE" HEAD 2>/dev/null || true
    fi
}

# Determine changed files using pre-push refs when available, then fall back to history.
CHANGED_FILES="$(resolve_changed_files_from_stdin)"
if [[ -z "$CHANGED_FILES" ]]; then
    CHANGED_FILES="$(resolve_changed_files_from_history)"
fi
CHANGED_FILES="$(printf '%s\n' "$CHANGED_FILES" | sed '/^$/d' | sort -u)"

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

    # Format check (hard gate). Scoped to the crystalmath core (python/); the
    # Textual TUI (tui/) is deprecated (ADR-006) and carries pre-existing format
    # debt, so it is not a hard gate. Format it explicitly if you touch it.
    echo "  Checking ruff format..."
    if ! format_output=$(uv run ruff format --check python/ 2>&1); then
        printf '%s\n' "$format_output"
        echo "  ✗ Ruff format check failed. Run: uv run ruff format python/"
        FAILURES=$((FAILURES + 1))
    else
        echo "  ✓ Format OK"
    fi

    # Lint (warning only) — core only, same rationale as the format gate.
    echo "  Checking ruff lint..."
    if ! uv run ruff check python/ > /dev/null 2>&1; then
        echo "  ⚠ Ruff lint warnings (non-blocking)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo "  ✓ Lint OK"
    fi

    # Tests (hard gate) — core suite only; tui/ is deprecated (ADR-006) and its
    # tests need optional extras. Run them explicitly with `uv run --package
    # crystal-tui pytest` when working on the deprecated TUI.
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
