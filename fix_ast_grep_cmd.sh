#!/bin/bash
set -e

echo "=== 1. Repairing ast-grep Subcommands ==="
# Swap out the legacy lint command for scan inside the setup configuration script
sed -i '' 's/sg lint/sg scan/g' setup_ast_grep.sh

# Fix the routing strings inside CLAUDE.md
if [ -f CLAUDE.md ]; then
  sed -i '' 's/sg lint/sg scan/g' CLAUDE.md
fi

echo "=== 2. Re-executing Workspace Code Quality Sweep ==="
sg scan

echo "🚀 Rule matrix fully synchronized with ast-grep 0.43.0 syntax!"
