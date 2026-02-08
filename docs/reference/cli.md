# CLI Reference

The `crystal` CLI provides command-line access to CrystalMath job management functionality.

## Installation

The CLI is installed as part of the `crystalmath` package:

```bash
# From the crystalmath repository root
uv sync
```

This makes the `crystal` command available in your environment.

## Global Options

All commands support the following global option:

```
--db-path PATH    Path to SQLite database file (default: .crystal_tui.db)
```

**Example:**
```bash
crystal list --db-path /path/to/custom.db
```

## Commands

### crystal run

Submit a calculation job.

```bash
crystal run INPUT_FILE [RANKS] [OPTIONS]
```

**Arguments:**
- `INPUT_FILE` - Input file name without extension (e.g., `mgo` for `mgo.d12`)
- `RANKS` - Number of MPI ranks (optional, uses serial/OpenMP if not specified)

**Options:**
- `--explain` - Show execution plan without running
- `--dft-code CODE` - DFT code to use: crystal (default), vasp, quantum_espresso
- `--runner RUNNER` - Execution backend: local (default), ssh, slurm
- `--db-path PATH` - Path to database file

**Examples:**

```bash
# Run MgO calculation (serial mode with OpenMP threading)
crystal run mgo

# Run with 4 MPI ranks
crystal run mgo 4

# Show execution plan without running
crystal run mgo --explain

# Run VASP calculation
crystal run POSCAR --dft-code vasp

# Submit to SLURM cluster (requires cluster configuration)
crystal run mgo --runner slurm
```

**Explain Mode Output:**

The `--explain` flag shows the execution plan without submitting:

```
Execution Plan:
  Input file:   /home/user/calcs/mgo.d12
  Job name:     mgo
  DFT code:     crystal
  Runner:       local
  Parallelism:  serial
  Binary:       crystalOMP
  Scratch base: /home/user/tmp_crystal
  Work dir:     /home/user/tmp_crystal/crystal_tui_mgo_<pid>

Note: Use without --explain to submit the job
```

**Success Output:**

```
Job submitted successfully!
  Job ID: 42
  Name:   mgo

Use 'crystal status 42' to check progress
```

### crystal list

List all jobs.

```bash
crystal list [OPTIONS]
```

**Options:**
- `--limit N` - Maximum number of jobs to show (default: 100)
- `--db-path PATH` - Path to database file

**Example:**

```bash
# Show last 100 jobs
crystal list

# Show last 10 jobs
crystal list --limit 10
```

**Output:**

```
                          Jobs (showing 10)
┏━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ ID ┃ Name         ┃ State     ┃ Code     ┃ Runner ┃ Progress ┃ Created         ┃
┡━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ 42 │ mgo_scf      │ COMPLETED │ crystal  │ local  │ 100%     │ 2026-02-08 10:30│
│ 41 │ mgo_opt      │ RUNNING   │ crystal  │ local  │ 67%      │ 2026-02-08 10:15│
│ 40 │ mgo_test     │ FAILED    │ crystal  │ local  │ 0%       │ 2026-02-08 09:45│
└────┴──────────────┴───────────┴──────────┴────────┴──────────┴─────────────────┘
```

**State Colors:**
- `COMPLETED` - Green
- `RUNNING` - Blue
- `FAILED` - Red
- `CANCELLED` - Yellow
- `QUEUED` - Cyan

### crystal status

Show detailed job status.

```bash
crystal status PK [OPTIONS]
```

**Arguments:**
- `PK` - Job ID (primary key)

**Options:**
- `--db-path PATH` - Path to database file

**Example:**

```bash
crystal status 42
```

**Output:**

```
Job Status: mgo_scf (ID: 42)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

State:        COMPLETED
DFT Code:     crystal
Runner:       local
Progress:     100%
Wall Time:    245.3 seconds

Results:
  Final Energy:   -274.123456 Ha
  Bandgap:        7.83 eV
  Converged:      Yes
  SCF Cycles:     12

Working Directory: /home/user/tmp_crystal/crystal_tui_mgo_42_12345

Use 'crystal log 42' to view output logs
```

### crystal log

View job output logs.

```bash
crystal log PK [OPTIONS]
```

**Arguments:**
- `PK` - Job ID (primary key)

**Options:**
- `--lines N` - Number of lines to show from end of log (default: 100)
- `--db-path PATH` - Path to database file

**Example:**

```bash
# Show last 100 lines
crystal log 42

# Show last 50 lines
crystal log 42 --lines 50
```

**Output:**

```
=== STDOUT (last 100 lines) ===

 SCF CONVERGENCE REACHED AFTER 12 CYCLES

 TOTAL ENERGY:                        -274.123456 AU
                                      -7456.789012 eV

 BAND GAP:                              7.8342 eV

 TIMING INFORMATION:
   SCF CYCLES:   234.5 seconds
   TOTAL TIME:   245.3 seconds

 CALCULATION COMPLETED SUCCESSFULLY

=== STDERR (last 100 lines) ===

[No stderr output]
```

### crystal cancel

Cancel a running or queued job.

```bash
crystal cancel PK [OPTIONS]
```

**Arguments:**
- `PK` - Job ID (primary key)

**Options:**
- `--db-path PATH` - Path to database file

**Example:**

```bash
crystal cancel 42
```

**Success Output:**

```
Job 42 cancelled successfully
```

**Failure Output:**

```
Failed to cancel job 42: Job not found
```

## Configuration

### Database Location

By default, the CLI uses `.crystal_tui.db` in the current directory. You can override this:

```bash
# Use custom database
export CRYSTAL_TUI_DB=/path/to/jobs.db
crystal list

# Or use --db-path flag
crystal list --db-path /path/to/jobs.db
```

### Input File Conventions

The CLI expects input files to follow these conventions:

**CRYSTAL:**
- Input file: `<name>.d12`
- Example: `crystal run mgo` looks for `mgo.d12`

**VASP:**
- Input files: `POSCAR`, `INCAR`, `KPOINTS`, `POTCAR`
- Example: `crystal run POSCAR --dft-code vasp`

**Quantum Espresso:**
- Input file: `<name>.in`
- Example: `crystal run mgo.in --dft-code quantum_espresso`

### Binary Selection

The CLI automatically selects the appropriate binary based on parallelism:

**CRYSTAL:**
- Serial/OpenMP: `crystalOMP` (uses all available cores)
- MPI: `crystal23` with specified ranks

**Environment Variables:**
```bash
export CRY23_ROOT=/path/to/crystal23
export CRY23_EXEDIR=$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1
```

**VASP:**
```bash
export VASP_ROOT=/path/to/vasp
export VASP_BIN=$VASP_ROOT/bin/vasp_std
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (input file not found, validation failed, job submission failed) |

## Integration with Python API

The CLI is a thin wrapper around the Python API. For programmatic access, use:

```python
from crystalmath.api import CrystalController
from crystalmath.models import JobSubmission, DftCode

ctrl = CrystalController(db_path="jobs.db")

submission = JobSubmission(
    name="mgo_scf",
    dft_code=DftCode.CRYSTAL,
    input_content=Path("mgo.d12").read_text(),
)

pk = ctrl.submit_job(submission)
jobs = ctrl.get_jobs(limit=10)
details = ctrl.get_job_details(pk)
```

## Troubleshooting

### Input file not found

```
Error: Input file not found: mgo.d12
```

**Solution:** Ensure the input file exists in the current directory with the correct extension.

### Binary not found

```
Error: crystalOMP: command not found
```

**Solution:** Set the `CRY23_EXEDIR` environment variable:

```bash
export CRY23_ROOT=~/CRYSTAL23
export CRY23_EXEDIR=$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1
export PATH=$CRY23_EXEDIR:$PATH
```

### Database not found

```
Error: No such file or directory: '.crystal_tui.db'
```

**Solution:** The database is created automatically. If you see this error, check file permissions or specify a custom path:

```bash
crystal run mgo --db-path ~/crystalmath/jobs.db
```

## See Also

- [API Reference](api.md) - Python API for programmatic access
- [Models Reference](models.md) - Data structures
- [Templates](templates.md) - Input file templates
