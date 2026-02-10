#!/usr/bin/env bash
# CrystalMath Workflow Integration - Development Session Initializer
# Per Anthropic's "Effective Harnesses for Long-Running Agents" patterns

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== CrystalMath Development Session Initializer ==="
echo ""

# 1. Verify working directory
echo "[1/8] Verifying working directory..."
cd "$PROJECT_ROOT"
pwd
echo ""

# 2. Check git status
echo "[2/8] Checking git status..."
git status --short || true
echo ""

# 3. Sync beads from main (if on ephemeral branch)
echo "[3/8] Syncing beads..."
if command -v bd &> /dev/null; then
    bd sync --from-main 2>/dev/null || echo "  (Beads sync skipped or not needed)"
else
    echo "  Warning: 'bd' command not found. Install beads for issue tracking."
fi
echo ""

# 4. Ensure pre-push hook is installed
echo "[4/8] Checking pre-push quality hook..."
if [[ -f "$PROJECT_ROOT/.git/hooks/pre-push" ]] && grep -q "quality checks" "$PROJECT_ROOT/.git/hooks/pre-push"; then
    echo "  ✓ Composite pre-push hook installed"
else
    echo "  Installing composite pre-push hook..."
    bash "$SCRIPT_DIR/install-hooks.sh"
fi
echo ""

# 5. Read progress state
echo "[5/8] Reading progress state..."
if [[ -f "PROGRESS.json" ]]; then
    current_phase=$(jq -r '.current_phase // "1"' PROGRESS.json)
    current_task=$(jq -r '.current_task // "none"' PROGRESS.json)
    echo "  Current Phase: $current_phase"
    echo "  Current Task: $current_task"
else
    echo "  Warning: PROGRESS.json not found. Creating default..."
    echo '{"current_phase": 1, "current_task": null}' > PROGRESS.json
fi
echo ""

# 6. Check ready work in beads
echo "[6/8] Checking ready work..."
if command -v bd &> /dev/null; then
    bd ready 2>/dev/null | grep crystalmath | head -5 || echo "  No crystalmath tasks ready"
else
    echo "  (Beads not available)"
fi
echo ""

# 7. Verify Python environment
echo "[7/8] Verifying Python environment..."
if [[ -d ".venv" ]]; then
    source .venv/bin/activate 2>/dev/null || true
    echo "  Python: $(python --version 2>&1)"
    echo "  uv: $(uv --version 2>&1 || echo 'not installed')"
else
    echo "  Warning: No .venv found. Run 'uv venv && uv sync' to create."
fi
echo ""

# 8. Run sanity tests (optional, quick)
echo "[8/8] Running sanity tests..."
if [[ -d "python/tests" ]]; then
    uv run pytest python/tests/ -x -q --tb=no 2>/dev/null || echo "  Tests skipped or failed"
else
    echo "  No tests directory found"
fi
echo ""

echo "=== Session Initialized ==="
echo ""
echo "Next steps:"
echo "  1. Run '/next-task' to select and claim a task"
echo "  2. Read the meta-prompt: prompts/META-PROMPT-WORKFLOW-INTEGRATION.md"
echo "  3. Use the appropriate agent for your phase:"
echo "     - Phase 1: research-agent"
echo "     - Phase 2: architect-agent"
echo "     - Phase 3: implement-agent"
echo "     - Phase 4: docs-agent"
echo ""
