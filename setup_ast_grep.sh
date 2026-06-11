#!/bin/bash
set -e

echo "================================================================="
echo "💥 Provisioning Ast-Grep Static Analysis Framework for CrystalMath 💥"
echo "================================================================="

# 1. Environment Verification & Tooling Check
if ! command -v sg &>/dev/null; then
  echo "⚠️  ast-grep (sg) not found in PATH."
  if command -v brew &>/dev/null; then
    echo "🍺 Installing ast-grep via Homebrew..."
    brew install ast-grep
  elif command -v cargo &>/dev/null; then
    echo "🦀 Installing ast-grep via Cargo..."
    cargo install ast-grep --locked
  else
    echo "❌ Error: Neither Homebrew nor Cargo found. Please install ast-grep manually."
    exit 1
  fi
fi

echo "✅ ast-grep version: $(sg --version)"

# 2. Establish Ast-Grep Configuration Directory Structure
echo "📁 Initializing .ast-grep/rules configuration layout..."
mkdir -p .ast-grep/rules

# 3. Create Global Configuration Router (sgconfig.yml)
cat <<'EOF' >sgconfig.yml
# CrystalMath ast-grep Global Project Settings
ruleDirs:
  - .ast-grep/rules
EOF

# 4. Generate Rule 1: Guarding Against Blocking I/O inside Async Contexts
cat <<'EOF' >.ast-grep/rules/no-blocking-async.yml
id: no-blocking-io-in-async
language: rust
rule:
  inside:
    pattern: async fn $$$() { $$$ }
  any:
    - pattern: std::fs::read_to_string($$$)
    - pattern: std::fs::read($$$)
    - pattern: std::fs::write($$$)
    - pattern: File::open($$$)
    - pattern: std::thread::sleep($$$)
message: >-
  [Architectural Boundary Violation] Found blocking synchronous operation inside an async function.
  This will hijack the Tokio worker threads and drop frame rendering below the strict 60 FPS target.
  Fix: Offload this task to tokio::task::spawn_blocking or utilize tokio::fs equivalents.
severity: error
EOF

# 5. Generate Rule 2: Tracking Legacies during PyO3 -> Native IPC Cutover
cat <<'EOF' >.ast-grep/rules/track-pyo3-bridge.yml
id: legacy-pyo3-bridge-tracker
language: rust
rule:
  any:
    - pattern: Python::with_gil($$$)
    - pattern: pyo3::$$$
message: >-
  [Migration Context] Legacy PyO3 direct Python interpreter dependency boundary detected.
  Ensure this code path is targeted for full extraction to the native IPC client-server
  framework (python/crystalmath/server/) mapped out in ADR-006.
severity: warning
EOF

# 6. Generate Rule 3: Identifying String Serialization Optimization Vectors
cat <<'EOF' >.ast-grep/rules/optimize-json-slice.yml
id: optimize-json-slice
language: rust
rule:
  pattern: serde_json::from_str($BUFF)
message: >-
  [Performance Optimization Opportunity] Deserializing JSON via raw string parsing vectors.
  To sustain allocation-free processing of high-throughput log streams from VASP/CRYSTAL23,
  pass direct read byte windows via serde_json::from_slice($BUFF) to utilize zero-copy reference state.
severity: hint
EOF

echo "✅ Global analysis matrix configurations written successfully."
echo "-----------------------------------------------------------------"

# 7. Add Automated Execution Commands to CLAUDE.md for Agent Synergy
if [ -f CLAUDE.md ]; then
  echo "📝 Backporting lint automation commands to CLAUDE.md..."
  if ! grep -q "sg scan" CLAUDE.md; then
    cat <<'EOF' >>CLAUDE.md

## Static Analysis & Quality Gates
- Check architectural rules: `sg scan`
- Auto-fix code format style regressions: `sg run --pattern 'serde_json::from_str($BUFF)' --rewrite 'serde_json::from_slice($BUFF)' -i`
EOF
  fi
fi

# 8. Execute Immediate Workspace Diagnostics
echo "🔍 Running workspace-wide syntax verification sweep..."
echo "================================================================="
sg scan || echo "💡 Review structural highlights tracked above to optimize codebase performance paths."

echo "================================================================="
echo "🚀 Ast-Grep framework fully configured! Run 'sg scan' any time to verify code quality."
echo "================================================================="
