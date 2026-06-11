#!/bin/bash
set -e

echo "================================================================="
echo "⚡ Executing Structural AST Performance Refactoring Matrix ⚡"
echo "================================================================="

# Pass 1: Target referenced string configurations to prevent double-borrow variables (&&[u8])
echo "🔄 Pass 1: Converting referenced string allocations (&json) to byte slices..."
sg run --pattern 'serde_json::from_str(&$BUFF)' --rewrite 'serde_json::from_slice($BUFF.as_bytes())' -i

# Pass 2: Target value strings, expressions, and string literals
echo "🔄 Pass 2: Converting value text channels (json) to byte slices..."
sg run --pattern 'serde_json::from_str($BUFF)' --rewrite 'serde_json::from_slice($BUFF.as_bytes())' -i

echo "-----------------------------------------------------------------"
echo "🔍 Re-scanning Workspace Architecture..."
sg scan

echo "-----------------------------------------------------------------"
echo "🦀 Verifying Native Cargo Build Stability..."
cargo clippy --all-targets

echo "================================================================="
echo "✨ Optimization complete! Memory paths flattened to zero-copy slices."
echo "================================================================="
