#!/usr/bin/env bash
# Install composite pre-push hook
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOK_TARGET="$PROJECT_ROOT/.git/hooks/pre-push"
HOOK_SOURCE="$SCRIPT_DIR/pre-push-quality.sh"

if [[ ! -f "$HOOK_SOURCE" ]]; then
    echo "Error: $HOOK_SOURCE not found"
    exit 1
fi

# Back up existing hook if it exists and isn't ours
if [[ -f "$HOOK_TARGET" ]] && ! grep -q "quality checks" "$HOOK_TARGET"; then
    echo "Backing up existing pre-push hook to $HOOK_TARGET.bak"
    cp "$HOOK_TARGET" "$HOOK_TARGET.bak"
fi

cp "$HOOK_SOURCE" "$HOOK_TARGET"
chmod +x "$HOOK_TARGET"
echo "✓ Installed composite pre-push hook to .git/hooks/pre-push"
echo "  Includes: quality checks + beads sync"
