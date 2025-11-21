# Results Summary View

The Results Summary View is a comprehensive panel for displaying parsed results from completed CRYSTAL calculations.

## Features

### 1. Automatic Result Parsing

The widget automatically parses CRYSTAL output files (`output.out`) using:
- **CRYSTALpytools** (preferred): Full-featured parsing with comprehensive data extraction
- **Fallback parser**: Pattern-matching based parser when CRYSTALpytools is unavailable

### 2. Key Information Displayed

#### Core Results
- **Final Energy**: Total energy in Hartree (Ha) with 10 decimal precision
- **Convergence Status**: CONVERGED/NOT CONVERGED/UNKNOWN
- **SCF Cycles**: Number of self-consistent field iterations
- **Calculation Time**: Duration from job start to completion

#### Geometry Optimization (if applicable)
- Convergence status (YES/NO)
- Number of optimization cycles
- Final gradient magnitude

#### Lattice Parameters (for periodic systems)
- Cell parameters (a, b, c, α, β, γ)
- Volume and other structural data

#### Warnings and Errors
- Up to 5 warnings displayed inline
- Up to 5 errors displayed inline
- Indicator when more exist ("... and N more")

### 3. Status-Specific Views

The widget adapts its display based on job status:

#### PENDING Jobs
Shows a message indicating the job has not been run, with hint to press 'r' to run.

#### RUNNING/QUEUED Jobs
Shows a message indicating the job is currently running, with hint to check the Log tab.

#### COMPLETED/FAILED Jobs
Shows comprehensive results summary with all available information.

### 4. Export Capability

Press 'e' while viewing results to export a summary to a text file:
- Saved as `{job_name}_summary.txt` in the job's working directory
- Includes: status, energy, key results (JSON), timestamps
- Human-readable format with structured sections

## Usage

### In the TUI

1. **Select a Job**: Click or navigate to a job in the job list
2. **View Results**: Switch to the "Results" tab
3. **Export**: Press 'e' to export summary to file

### Parsing Behavior

#### With CRYSTALpytools (Recommended)

When CRYSTALpytools is available, the parser extracts:
- Final energy (`get_final_energy()`)
- SCF convergence data (`get_scf_convergence()`)
- Convergence status (`is_converged()`)
- Geometry optimization data (`get_geometry_optimization()`)
- Lattice parameters (`get_lattice_parameters()`)
- System information (`get_system_info()`)
- Timing data (`get_timing()`)
- Errors and warnings (`get_errors()`, `get_warnings()`)

#### Fallback Parser

When CRYSTALpytools is unavailable, a pattern-matching parser extracts:
- **Final Energy**: Searches for "TOTAL ENERGY" lines with "(AU)" marker
- **SCF Cycles**: Counts lines containing "CYC" and "ETOT"
- **Convergence**: Searches for "CONVERGENCE REACHED" or "SCF ENDED"
- **Timing**: Extracts "TOTAL CPU TIME" or "TTTTTTTT" lines
- **Errors**: Lines containing "ERROR", "FATAL", "ABNORMAL"
- **Warnings**: Lines containing "WARNING"

## Technical Details

### Widget Class: `ResultsSummary`

**Location**: `src/tui/widgets/results_summary.py`

**Key Methods**:

```python
def display_results(
    job_id: int,
    job_name: str,
    work_dir: Path,
    status: str,
    final_energy: Optional[float] = None,
    key_results: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> None:
    """Display results for a completed job."""

def display_pending(job_name: str) -> None:
    """Display a message for pending jobs."""

def display_running(job_name: str) -> None:
    """Display a message for running jobs."""

def display_no_results() -> None:
    """Display a message when no results are available."""

def display_error(error_message: str) -> None:
    """Display an error message."""

async def action_export_results() -> None:
    """Export results to a text file."""
```

### Integration with App

The widget is integrated into `CrystalTUI` app and automatically updates when:
1. User selects a different job in the job list (`on_data_table_row_highlighted`)
2. A job completes and results become available (`on_job_results`)

### Error Handling

The widget gracefully handles:
- Missing output files (displays "No results available")
- Corrupted or empty output files (displays what can be extracted)
- CRYSTALpytools import errors (falls back to pattern matching)
- Parsing exceptions (captures and displays as warnings)

## Display Format

Results are displayed using Rich text formatting:

```
Results for: mgo_optimization

● COMPLETED

Key Results
╭──────────────────╮
│ Final Energy     │ -274.8901234567 Ha
│ Convergence      │ CONVERGED
│ SCF Cycles       │ 12
│ Calculation Time │ 0:05:34
╰──────────────────╯

Geometry Optimization
╭────────────────────╮
│ Converged          │ YES
│ Optimization Cycles│ 8
│ Final Gradient     │ 1.234e-06
╰────────────────────╯

Warnings (2):
  ⚠ Basis set may be incomplete
  ⚠ High memory usage detected

Press e to export results to file
```

## Future Enhancements

Potential improvements for Phase 2:

1. **Interactive Plots**: Visualize convergence history
2. **Comparison Mode**: Compare results from multiple jobs
3. **Custom Filtering**: Filter which warnings/errors to show
4. **Rich Formatting**: More sophisticated tables and styling
5. **Export Formats**: Support JSON, CSV, or custom formats
6. **Deep Inspection**: Click on warnings/errors for full context

## Testing

Test suite location: `tests/test_results_summary.py`

**Test Coverage**:
- Widget instantiation
- Fallback parser with various content types
- Display methods (pending, running, completed, failed)
- Error handling for missing files
- Full data display with all available information

**Run Tests**:
```bash
cd tui/
source venv/bin/activate
pytest tests/test_results_summary.py -v
```

## Dependencies

**Required**:
- `textual>=0.50.0` - TUI framework
- `rich>=13.0.0` - Terminal formatting

**Optional (Recommended)**:
- `CRYSTALpytools>=2023.0.0` - Advanced output parsing
- `pymatgen>=2023.0.0` - Structural analysis (via CRYSTALpytools)

## Related Documentation

- [Project Status](PROJECT_STATUS.md) - Overall TUI roadmap
- [Architecture](../docs/architecture.md) - System design
- [Local Runner](../src/runners/local.py) - Job execution and initial parsing
