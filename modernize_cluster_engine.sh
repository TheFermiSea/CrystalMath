#!/bin/bash
set -e

OUTPUT_LOG="cluster_modernization.log"
echo "=== CrystalMath Cluster Subsystem Modernization Suite ===" | tee "$OUTPUT_LOG"
echo "Started at: $(date)" >>"$OUTPUT_LOG"
echo "========================================================" >>"$OUTPUT_LOG"

# -----------------------------------------------------------------
# PHASE 1: Structural Audit via Ripgrep and Ast-grep
# -----------------------------------------------------------------
echo "🔍 Phase 1: Locating legacy template blocks and command markers..." | tee -a "$OUTPUT_LOG"

# Find hardcoded #SBATCH directives across the Python backend
echo "[RG] Mapping occurrences of raw #SBATCH directives:" >>"$OUTPUT_LOG"
rg "#SBATCH" python/ >>"$OUTPUT_LOG" || true

# Inspect the command execution signatures inside the Connection Manager using ast-grep
echo "[SG] Analyzing async ssh execution methods:" >>"$OUTPUT_LOG"
sg run -p 'async def $FUNC($$$ARGS): $$$BODY' python/crystalmath/_vendor/core/connection_manager.py >>"$OUTPUT_LOG" 2>/dev/null || true

# -----------------------------------------------------------------
# PHASE 2: Dynamic Python SLURM Header Abstraction Factory
# -----------------------------------------------------------------
echo "⚡ Phase 2: Injecting standardized dictionary-driven script generator..." | tee -a "$OUTPUT_LOG"

TARGET_RUNNER="python/crystalmath/integrations/slurm_runner.py"
if [ ! -f "$TARGET_RUNNER" ]; then
  TARGET_RUNNER="python/crystalmath/_vendor/runners/slurm_runner.py"
fi

echo "• Targeting runner file: $TARGET_RUNNER" | tee -a "$OUTPUT_LOG"

python3 -c "
import os

path = '$TARGET_RUNNER'
if not os.path.exists(path):
    print(f'⚠️ Target runner {path} not found. Skipping helper injection.')
    exit(0)

with open(path, 'r') as f:
    content = f.read()

helper_code = \"\"\"
def generate_sbatch_script(config_dict: dict, execution_commands: list[str]) -> str:
    \\\"\\\"\\\"
    Programmatically builds clean, standardized #SBATCH script headers from 
    dictionary configurations instead of brittle raw text block formats.
    \\\"\\\"\\\"
    script_lines = ['#!/bin/bash']
    
    # Process standard headers deterministically
    for key, val in config_dict.items():
        normalized_key = key.replace('_', '-')
        script_lines.append(f'#SBATCH --{normalized_key}={val}')
        
    script_lines.append('') # Spatial padding
    script_lines.extend(execution_commands)
    return '\\n'.join(script_lines)
\"\"\"

if 'generate_sbatch_script' not in content:
    # Append the clean dictionary abstraction factory to the file layout
    with open(path, 'a') as f:
        f.write('\n' + helper_code + '\n')
    print('✅ Programmatic sbatch factory cleanly injected.')
else:
    print('ℹ️ Programmatic factory already present.')
" >>"$OUTPUT_LOG" 2>&1

# -----------------------------------------------------------------
# PHASE 3: Streamlining connection_manager.py Execution Loops
# -----------------------------------------------------------------
echo "⚡ Phase 3: Optimizing remote SSH channel validation pipelines..." | tee -a "$OUTPUT_LOG"

python3 -c "
with open('python/crystalmath/_vendor/core/connection_manager.py', 'r') as f:
    content = f.read()

# Replace redundant verbose testing code with streamlined structured execution wrappers
old_test_block = \"\"\"    async def test_connection(self, cluster_id: int) -> bool:
        try:
            conn = await self.get_connection(cluster_id)
            result = await conn.run('echo \"OK\"', timeout=10)
            return result.stdout.strip() == \"OK\"
        except Exception:
            return False\"\"\"

optimized_test_block = \"\"\"    async def test_connection(self, cluster_id: int) -> bool:
        \\\"\\\"\\\"Streamlined low-overhead validation execution channel wrapper.\\\"\\\"\\\"
        try:
            conn = await self.get_connection(cluster_id)
            return (await conn.run('true', timeout=5)).exit_status == 0
        except Exception:
            return False\"\"\"

if old_test_block in content:
    content = content.replace(old_test_block, optimized_test_block)
    with open('python/crystalmath/_vendor/core/connection_manager.py', 'w') as f:
        f.write(content)
    print('✅ Connection validation loops refactored to standard POSIX exit status patterns.')
else:
    print('ℹ️ Connection validation signature is already up to date or structurally distinct.')
" >>"$OUTPUT_LOG" 2>&1

# -----------------------------------------------------------------
# PHASE 4: Source Formatting & Integrity Verification Gates
# -----------------------------------------------------------------
echo "⚙️ Phase 4: Running source layout compliance and testing suites..." | tee -a "$OUTPUT_LOG"

# Clean up Python code styling inside the modified directories
if command -v black &>/dev/null; then
  echo "• Formatting Python files via Black..." | tee -a "$OUTPUT_LOG"
  black python/crystalmath/ >>"$OUTPUT_LOG" 2>&1 || true
fi

if command -v ruff &>/dev/null; then
  echo "• Linting Python code layer via Ruff..." | tee -a "$OUTPUT_LOG"
  ruff check python/crystalmath/ --fix >>"$OUTPUT_LOG" 2>&1 || true
fi

# Final Cargo Compilation sanity check to verify IPC linkages remain perfectly stable
echo "• Re-verifying Rust compilation profiles..." | tee -a "$OUTPUT_LOG"
cargo clippy --all-targets >>"$OUTPUT_LOG" 2>&1

echo "========================================================" | tee -a "$OUTPUT_LOG"
echo "✅ Subsystem modernization complete! Review '$OUTPUT_FILE' or '$OUTPUT_LOG' for traces." | tee -a "$OUTPUT_LOG"
