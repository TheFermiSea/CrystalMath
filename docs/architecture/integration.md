# Integration Guide: CLI + TUI

This guide explains how the CRYSTAL CLI and TUI tools work together, their complementary roles, and integration patterns.

## Design Philosophy

**CLI for Execution, TUI for Management**

The CLI and TUI are designed as complementary tools with distinct responsibilities:

| Feature | CLI | TUI |
|---------|-----|-----|
| **Primary Role** | Execute calculations | Manage job lifecycle |
| **Interface** | Command-line (scriptable) | Interactive terminal UI |
| **Persistence** | Stateless (one-shot) | Database-backed history |
| **Parallelism** | Built-in (MPI/OpenMP) | Delegates to CLI |
| **Monitoring** | Real-time stdout | Async log streaming |
| **Target Users** | Scripts, HPC workflows | Interactive researchers |
| **Dependencies** | Bash, gum (optional) | Python, Textual, SQLite |

## Usage Patterns

### Pattern 1: Independent Usage

Use each tool independently for different workflows:

**CLI: Quick Calculations**
```bash
# Run a single calculation
runcrystal optimization 14

# Batch script for parameter sweep
for temp in 100 200 300; do
    sed "s/TEMP/$temp/" template.d12 > calc_${temp}K.d12
    runcrystal calc_${temp}K 14
done
```

**TUI: Interactive Exploration**
```bash
# Launch TUI for interactive job management
crystal-tui

# Create jobs interactively (n key)
# Monitor progress in real-time
# Browse job history
# Inspect results
```

### Pattern 2: TUI as Frontend, CLI as Backend

The TUI can use the CLI as its execution engine:

**TUI Configuration** (planned feature):
```python
# tui/src/core/config.py
EXECUTION_BACKEND = "cli"  # or "direct"
CLI_PATH = "/path/to/runcrystal"
```

**Benefits:**
- TUI inherits all CLI parallelism logic
- Consistent execution environment
- Reuse CLI's scratch management
- CLI's gum output visible in TUI log pane

**Workflow:**
1. User presses `r` (run) in TUI
2. TUI calls: `subprocess.run([CLI_PATH, job_name, str(nprocs)])`
3. CLI executes calculation (parallel, scratch, staging)
4. TUI streams stdout to Log pane
5. TUI parses results when complete

### Pattern 3: Shared Environment

Both tools read the same environment configuration:

**Shared File:** `~/CRYSTAL23/cry23.bashrc`
```bash
# CRYSTAL23 Environment (shared by CLI and TUI)
export CRY23_ROOT=~/CRYSTAL23
export CRY23_EXEDIR=$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1
export CRY23_SCRDIR=~/tmp_crystal
export CRY23_UTILS=$CRY23_ROOT/utils
```

**CLI Integration:**
```bash
# lib/cry-config.sh sources this file
if [[ -f "$HOME/CRYSTAL23/cry23.bashrc" ]]; then
    source "$HOME/CRYSTAL23/cry23.bashrc"
fi
```

**TUI Integration** (planned):
```python
# src/core/environment.py
import os
from pathlib import Path

bashrc = Path.home() / "CRYSTAL23" / "cry23.bashrc"
if bashrc.exists():
    # Parse bash env vars (using python-dotenv or bash subprocess)
    os.environ.update(parse_bashrc(bashrc))
```

## Integration Points

### 1. Scratch Directory Sharing

Both tools use the same scratch space structure:

```
~/tmp_crystal/
├── cry_job1_12345/         # CLI calculation
│   ├── INPUT
│   ├── fort.9
│   └── OUTPUT
│
└── crystal_tui_job2_67890/ # TUI calculation
    ├── INPUT
    ├── fort.9
    └── OUTPUT
```

**Cleanup Strategy:**
- CLI: Automatic cleanup via `trap 'scratch_cleanup' EXIT`
- TUI: Cleanup after result retrieval, or on job deletion

### 2. File Staging Protocol

Both tools follow the same file staging pattern:

**Input Staging (before calculation):**
1. Create scratch directory: `~/tmp_crystal/cry_<job>_<pid>/`
2. Copy input file: `job.d12` → `scratch/INPUT`
3. Stage auxiliary files if present:
   - `job.gui` → `scratch/fort.34`
   - `job.f9` → `scratch/fort.9`
   - `job.hessopt` → `scratch/HESSOPT.DAT`
   - `job.born` → `scratch/BORN.DAT`

**Output Retrieval (after calculation):**
1. Copy results: `scratch/OUTPUT` → `job.out`
2. Copy wavefunctions: `scratch/fort.9` → `job.f9`
3. Copy formatted wfn: `scratch/fort.98` → `job.f98`
4. Copy optimized geometry: `scratch/HESSOPT.DAT` → `job.hessopt`
5. Clean scratch directory

### 3. Result Parsing

Both tools can use **CRYSTALpytools** for parsing:

**CLI Approach** (future enhancement):
```bash
# lib/cry-results.sh (planned)
parse_output() {
    local output_file="$1"

    # Use CRYSTALpytools via Python
    python3 << EOF
from CRYSTALpytools import Crystal_output
output = Crystal_output("$output_file")
print(f"Energy: {output.get_final_energy()}")
print(f"Status: {output.get_status()}")
EOF
}
```

**TUI Approach** (implemented):
```python
# src/core/crystal_io.py
from CRYSTALpytools import Crystal_output

def parse_crystal_output(output_path: Path) -> dict:
    """Parse CRYSTAL output using CRYSTALpytools"""
    output = Crystal_output(str(output_path))
    return {
        "final_energy": output.get_final_energy(),
        "status": output.get_status(),
        "warnings": output.get_warnings(),
        "geometry": output.get_geometry()
    }
```

## Communication Patterns

### Option 1: Direct Process Invocation (Current)

TUI spawns CLI as subprocess:

```python
# src/runners/cli_backend.py (planned)
import subprocess
from pathlib import Path

class CLIBackend:
    def __init__(self, cli_path: Path):
        self.cli_path = cli_path

    async def run_job(self, input_file: Path, nprocs: int = 1):
        """Execute calculation via CLI"""
        proc = await asyncio.create_subprocess_exec(
            str(self.cli_path),
            str(input_file.stem),
            str(nprocs),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=input_file.parent
        )

        # Stream output in real-time
        async for line in proc.stdout:
            yield line.decode('utf-8')

        await proc.wait()
        return proc.returncode
```

**Pros:**
- Simple, direct
- No shared state
- CLI remains independent

**Cons:**
- Less control over execution
- Parsing CLI's visual output

### Option 2: Shared Library (Future)

Extract core logic to shared Python module:

```python
# shared/crystal_core.py
class CrystalRunner:
    """Shared execution logic for CLI and TUI"""

    def __init__(self, crystal_root: Path, scratch_base: Path):
        self.crystal_root = crystal_root
        self.scratch_base = scratch_base

    def setup_scratch(self, job_name: str) -> Path:
        """Create scratch directory"""
        ...

    def stage_inputs(self, input_file: Path, scratch_dir: Path):
        """Stage input and auxiliary files"""
        ...

    def execute(self, scratch_dir: Path, nprocs: int):
        """Run CRYSTAL calculation"""
        ...

    def retrieve_results(self, scratch_dir: Path, output_dir: Path):
        """Copy results back"""
        ...
```

**Usage:**
```bash
# CLI: bin/runcrystal calls shared library
python3 -m shared.crystal_core run "$INPUT" "$NPROCS"
```

```python
# TUI: Direct import
from shared.crystal_core import CrystalRunner
runner = CrystalRunner(crystal_root, scratch_base)
await runner.execute(scratch_dir, nprocs)
```

**Pros:**
- Single source of truth
- No code duplication
- Easier testing

**Cons:**
- CLI now requires Python
- More coupling between tools

### Option 3: REST API (Advanced)

TUI runs as daemon with REST API:

```python
# tui/src/api/server.py (future)
from fastapi import FastAPI
app = FastAPI()

@app.post("/jobs/")
async def create_job(input_content: str, name: str):
    """Create new job"""
    ...

@app.post("/jobs/{job_id}/run")
async def run_job(job_id: int, nprocs: int = 1):
    """Execute job"""
    ...

@app.get("/jobs/{job_id}/status")
async def get_status(job_id: int):
    """Get job status"""
    ...
```

**CLI Integration:**
```bash
# bin/runcrystal (enhanced mode)
if [[ -n "$CRYSTAL_TUI_API" ]]; then
    # Register with TUI
    curl -X POST "$CRYSTAL_TUI_API/jobs/" \
         -H "Content-Type: application/json" \
         -d '{"name":"'$FILE_PREFIX'","input":"'$(cat $INPUT)'"}'
fi

# Execute calculation
exec_crystal_run ...
```

**Pros:**
- Full separation of concerns
- Remote execution support
- Language-agnostic

**Cons:**
- Significant complexity
- Network overhead
- Daemon management

## Recommended Integration Strategy

### Current (Phase 1): Independent Tools

- ✅ CLI and TUI work independently
- ✅ Shared environment via cry23.bashrc
- ✅ Common scratch directory structure
- ✅ CRYSTALpytools for parsing in TUI
- No direct integration code

### Phase 2: TUI Uses CLI Backend

- ⏳ TUI spawns CLI for execution
- ⏳ Parse CLI output for progress
- ⏳ CLI provides `--json` output mode for machine reading
- Benefits: Reuse CLI parallelism, simple integration

### Phase 3: Shared Core Library

- 📋 Extract common logic to Python module
- 📋 Both tools import from shared module
- 📋 CLI becomes thin Python wrapper
- Benefits: Code reuse, easier testing, unified behavior

### Phase 4: API-Driven Architecture

- 📋 TUI provides REST API
- 📋 CLI can register jobs via API
- 📋 Remote execution support
- Benefits: Maximum flexibility, cluster integration

## Example Workflows

### Workflow 1: Batch CLI + TUI Monitoring

```bash
# Terminal 1: Run batch calculations with CLI
for i in {1..10}; do
    runcrystal calc_$i 14
done

# Terminal 2: Monitor in TUI
crystal-tui
# Browse completed jobs
# Check for errors
# Export results
```

### Workflow 2: TUI Job Creation + CLI Execution

```bash
# Create job in TUI
crystal-tui
# Press 'n' for new job
# Enter input via modal
# Job saved to database

# Execute via CLI (for better control)
cd calculations/1_my_job/
runcrystal input 14

# Return to TUI to view results
crystal-tui
# Results automatically detected
# Parsed and displayed
```

### Workflow 3: Educational Workflow

```bash
# Student explores in TUI
crystal-tui
# Browse example jobs
# Read documentation
# Create new job

# Learn about execution plan
runcrystal student_job --explain
# Educational output shows:
# - Hardware detection
# - Parallel strategy
# - File staging plan
# - Environment setup

# Execute with understanding
runcrystal student_job 4
```

## Future Enhancements

1. **CLI → TUI Notification**
   - CLI sends completion notification to TUI
   - TUI auto-refreshes job list
   - Integration via filesystem watch or IPC

2. **Shared Configuration File**
   - Single `crystal-tools.toml` config
   - Both tools read same settings
   - Environment, paths, preferences

3. **Job Import/Export**
   - TUI exports jobs as CLI scripts
   - CLI can import to TUI database
   - Portable calculation packages

4. **Remote Execution**
   - TUI submits to remote CLI via SSH
   - CLI runs on HPC cluster
   - TUI monitors remotely

5. **Workflow Templates**
   - TUI defines multi-step workflows
   - CLI executes each step
   - Results feed back to TUI

---

**Current Status:** Independent tools with shared environment ✅
**Next Phase:** TUI subprocess integration ⏳
**Long-term Vision:** Unified core library with API 📋
