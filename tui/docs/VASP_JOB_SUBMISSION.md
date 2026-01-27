# VASP Job Submission Guide

This guide covers the complete workflow for submitting, monitoring, and retrieving VASP calculations using CRYSTAL-TUI.

---

## Table of Contents

1. [Input File Preparation](#input-file-preparation)
2. [Using the VASP Input Manager](#using-the-vasp-input-manager)
3. [Job Submission Workflow](#job-submission-workflow)
4. [Monitoring Job Progress](#monitoring-job-progress)
5. [Retrieving Results](#retrieving-results)
6. [Input File Reference](#input-file-reference)

---

## Input File Preparation

VASP requires four input files for every calculation:

| File | Purpose | Required |
|------|---------|----------|
| **POSCAR** | Crystal structure (lattice + atomic positions) | Yes |
| **INCAR** | Calculation parameters | Yes |
| **KPOINTS** | k-point mesh specification | Yes |
| **POTCAR** | Pseudopotential data | Yes (auto-retrieved) |

### POSCAR: Crystal Structure

The POSCAR file defines the unit cell and atomic positions.

**Format:**
```
Comment line (system name)
Scaling factor (lattice constant multiplier)
a1_x a1_y a1_z     # First lattice vector
a2_x a2_y a2_z     # Second lattice vector
a3_x a3_y a3_z     # Third lattice vector
Element1 Element2  # Element symbols (VASP 5+)
N1 N2              # Number of atoms per element
Selective dynamics # Optional: enable selective dynamics
Direct | Cartesian # Coordinate type
x1 y1 z1           # Position of atom 1
x2 y2 z2           # Position of atom 2
...
```

**Example (Silicon FCC):**
```
Silicon bulk structure
5.43
 0.0 0.5 0.5
 0.5 0.0 0.5
 0.5 0.5 0.0
Si
2
Direct
 0.0 0.0 0.0
 0.25 0.25 0.25
```

### INCAR: Calculation Parameters

The INCAR file controls all aspects of the calculation.

**Essential Parameters:**

| Parameter | Purpose | Common Values |
|-----------|---------|---------------|
| `SYSTEM` | Job description | Any string |
| `ENCUT` | Plane-wave cutoff (eV) | 400-600 |
| `PREC` | Precision level | `Accurate`, `Normal` |
| `EDIFF` | SCF convergence threshold | `1E-6` |
| `ALGO` | Electronic minimization | `Normal`, `Fast`, `All` |
| `ISMEAR` | Smearing method | `0` (Gaussian), `1` (MP) |
| `SIGMA` | Smearing width (eV) | `0.05-0.2` |

**Example (SCF calculation):**
```
# INCAR - SCF calculation
SYSTEM = Silicon SCF

# Electronic settings
PREC = Accurate
ENCUT = 400
EDIFF = 1E-6
ALGO = Normal
NELM = 100

# Smearing
ISMEAR = 0
SIGMA = 0.1

# Output
LWAVE = .TRUE.
LCHARG = .TRUE.
```

**Example (Geometry optimization):**
```
# INCAR - Geometry optimization
SYSTEM = Silicon relaxation

# Electronic settings
PREC = Accurate
ENCUT = 400
EDIFF = 1E-6

# Ionic relaxation
IBRION = 2      # Conjugate gradient
NSW = 50        # Max ionic steps
POTIM = 0.5     # Step size
EDIFFG = -0.01  # Force convergence (eV/Angstrom)

# Smearing
ISMEAR = 0
SIGMA = 0.1
```

### KPOINTS: k-point Mesh

The KPOINTS file specifies the Brillouin zone sampling.

**Format (automatic mesh):**
```
Comment line
0              # 0 = automatic generation
Gamma|Monkhorst-Pack
N1 N2 N3       # Grid dimensions
s1 s2 s3       # Shift (usually 0 0 0)
```

**Example (4x4x4 Gamma-centered):**
```
Automatic mesh
0
Gamma
4 4 4
0. 0. 0.
```

**Example (6x6x6 Monkhorst-Pack):**
```
Automatic mesh
0
Monkhorst-Pack
6 6 6
0. 0. 0.
```

### POTCAR: Pseudopotentials

POTCAR files contain pseudopotential data for each element. The TUI handles POTCAR retrieval automatically from the cluster's `VASP_PP_PATH`.

**Supported elements in TUI:**
- Silicon (Si)
- Carbon (C)
- Oxygen (O)
- Titanium (Ti)
- Nitrogen (N)
- Hydrogen (H)

For multi-element structures, POTCAR files are concatenated in the order elements appear in POSCAR.

---

## Using the VASP Input Manager

The VASPInputManagerScreen provides a tabbed interface for creating VASP jobs.

### Opening the Input Manager

1. Launch CRYSTAL-TUI: `crystal-tui`
2. Press `n` to open New Job screen
3. Select "VASP" from the DFT Code dropdown
4. Click "Create Job" to open VASP Input Manager

### Interface Overview

The VASP Input Manager has four tabs:

```
+----------+----------+----------+----------+
| POSCAR   | INCAR    | KPOINTS  | POTCAR   |
+----------+----------+----------+----------+
|                                            |
|  [Text area for file content]              |
|                                            |
+--------------------------------------------+
| Job Name: [_______________]                |
| [Validate]  [Create Job]  [Cancel]         |
+--------------------------------------------+
```

### Tab 1: POSCAR

**Purpose:** Enter crystal structure

**Features:**
- Paste content directly from file
- Syntax highlighting
- Automatic validation (minimum 8 lines, valid scaling factor)

**Workflow:**
1. Click POSCAR tab
2. Paste or type POSCAR content
3. Content auto-validates on change

**Validation checks:**
- Minimum 8 lines present
- Line 2 is a valid number (scaling factor)

### Tab 2: INCAR

**Purpose:** Configure calculation parameters

**Features:**
- Default template provided
- Common parameters pre-filled
- Comment support with `#`

**Default template includes:**
- PREC = Accurate
- ENCUT = 400
- EDIFF = 1E-6
- ALGO = Normal
- ISMEAR = 0, SIGMA = 0.1
- NELM = 100
- LWAVE/LCHARG = .TRUE.

**Validation checks:**
- At least one `KEY = VALUE` pair present

### Tab 3: KPOINTS

**Purpose:** Define k-point sampling

**Features:**
- Default 4x4x4 Gamma mesh provided
- Supports automatic and explicit meshes

**Default template:**
```
Automatic mesh
0
Gamma
4 4 4
0. 0. 0.
```

**Validation checks:**
- Minimum 4 lines present

### Tab 4: POTCAR

**Purpose:** Select pseudopotential element

**Features:**
- Dropdown selection for element
- POTCAR retrieved from cluster automatically
- No file upload required

**How it works:**
1. Select element from dropdown (e.g., "Silicon (Si)")
2. When job runs, TUI retrieves POTCAR from cluster's `VASP_PP_PATH`
3. POTCAR copied to job work directory

**Current limitation:** Single-element POTCAR only. Multi-element support planned.

### Creating the Job

1. Fill in all four tabs
2. Enter a **Job Name** (letters, numbers, hyphens, underscores)
3. Click **Validate** to check all files
4. Click **Create Job** to finalize

**On success:**
- Work directory created: `calculations/XXXX_jobname/`
- POSCAR, INCAR, KPOINTS written to disk
- Metadata saved (`vasp_metadata.json`)
- Job added to database (status: "pending")
- Screen closes automatically

---

## Job Submission Workflow

### Selecting a Job

From the main TUI screen:
1. Use arrow keys to navigate job list
2. Select your VASP job (shows `vasp` in DFT Code column)

### Running a Job

Press `r` to run the selected job.

**Submission process:**
1. **SSH Connection:** Connects to configured cluster
2. **Remote Directory:** Creates `~/dft_jobs/job_<id>_<timestamp>/`
3. **File Upload:** Uploads POSCAR, INCAR, KPOINTS via SFTP
4. **POTCAR Retrieval:** Fetches from cluster's `VASP_PP_PATH`
5. **Execution Script:** Creates `run_job.sh`
6. **Launch:** Runs job with `nohup`
7. **PID Capture:** Stores process ID for monitoring

### Generated Execution Script

The TUI creates a `run_job.sh` script:

```bash
#!/bin/bash

# Source VASP environment (if exists)
if [ -f ~/vasp/vasp.bashrc ]; then
    source ~/vasp/vasp.bashrc
fi

# Set OpenMP threads
export OMP_NUM_THREADS=8

# Execute VASP
/opt/vasp/bin/vasp_std

# Capture exit code
echo $? > .exit_code

exit $?
```

### Job States

| Status | Description |
|--------|-------------|
| `pending` | Job created, not yet submitted |
| `queued` | Job submitted to cluster |
| `running` | Job executing on cluster |
| `completed` | Job finished successfully |
| `failed` | Job encountered an error |
| `cancelled` | Job manually cancelled |

---

## Monitoring Job Progress

### TUI Progress Display

The TUI provides real-time progress tracking by parsing OUTCAR:

```
Job: silicon_scf
Status: Running
Progress: Ionic step 5/50, SCF 12, E=-123.456789 eV
```

### Progress Information Extracted

| Metric | Source | Description |
|--------|--------|-------------|
| Ionic step | OUTCAR | Current geometry optimization step |
| SCF iteration | OUTCAR | Current electronic iteration |
| Current energy | OUTCAR | Latest free energy (eV) |
| Energy change | OUTCAR | Energy difference from previous step |
| Convergence status | OUTCAR | Whether SCF converged |

### Progress Parser Details

The `VASPProgressParser` class extracts:

```python
# Example progress output
VASPProgress(
    ionic_step=5,
    scf_iteration=12,
    current_energy=-123.456789,
    energy_change=-0.000123,
    scf_converged=True,
    ionic_converged=False,
    total_ionic_steps=50,
    max_scf_iterations=100,
    calculation_complete=False,
    error_detected=False,
    progress_percentage=10.0
)
```

### Viewing Job Details

1. Select job in list
2. Press `Enter` or `v` to view details
3. Progress updates automatically while job runs

### Manual Progress Check

SSH to cluster and inspect OUTCAR:

```bash
# View last 50 lines of OUTCAR
ssh cluster "tail -50 ~/dft_jobs/job_123_*/OUTCAR"

# Watch progress in real-time
ssh cluster "tail -f ~/dft_jobs/job_123_*/OUTCAR | grep -E 'F=|DAV:|RMM:'"
```

---

## Retrieving Results

### Automatic Output Retrieval

When a job completes, the TUI retrieves these files:

| File | Content |
|------|---------|
| `OUTCAR` | Main text output (energies, forces, timing) |
| `CONTCAR` | Final optimized structure |
| `OSZICAR` | SCF convergence summary |
| `vasprun.xml` | XML output for parsing |
| `EIGENVAL` | Eigenvalues at k-points |
| `DOSCAR` | Density of states |
| `CHGCAR` | Charge density (for restart) |
| `WAVECAR` | Wavefunctions (for restart) |

### Local Output Location

Retrieved files stored in:
```
calculations/XXXX_jobname/
├── POSCAR           # Input structure
├── INCAR            # Input parameters
├── KPOINTS          # Input k-points
├── OUTCAR           # Main output
├── CONTCAR          # Final structure
├── OSZICAR          # SCF summary
├── vasprun.xml      # XML output
├── vasp_metadata.json
└── job_metadata.json
```

### Parsing Results

The TUI automatically parses OUTCAR for key results:

| Result | Location | Unit |
|--------|----------|------|
| Final energy | OUTCAR, "free energy TOTEN" | eV |
| Convergence status | OUTCAR, "reached required accuracy" | - |
| Max force | OUTCAR, TOTAL-FORCE section | eV/Angstrom |
| Timing | OUTCAR, "General timing" section | seconds |

### Viewing Results in TUI

1. Select completed job
2. Press `v` to view details
3. Results panel shows:
   - Final energy
   - Convergence status
   - Calculation time
   - Any errors/warnings

### Extracting Results Manually

```bash
# Final energy
grep "free  energy   TOTEN" calculations/0001_silicon/OUTCAR | tail -1

# Convergence check
grep "reached required accuracy" calculations/0001_silicon/OUTCAR

# Forces
grep -A 10 "TOTAL-FORCE" calculations/0001_silicon/OUTCAR | tail -10
```

---

## Input File Reference

### INCAR Parameter Categories

#### Electronic Relaxation

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ENCUT` | POTCAR | Plane-wave cutoff (eV) |
| `PREC` | Normal | Precision: Low, Normal, Accurate, High |
| `EDIFF` | 1E-4 | SCF convergence (eV) |
| `NELM` | 60 | Max SCF iterations |
| `ALGO` | Normal | Algorithm: Normal, Fast, VeryFast, All, Damped |

#### Ionic Relaxation

| Parameter | Default | Description |
|-----------|---------|-------------|
| `IBRION` | -1 | Optimizer: -1 (none), 1 (quasi-Newton), 2 (CG), 3 (damped) |
| `NSW` | 0 | Max ionic steps |
| `POTIM` | 0.5 | Ionic step size |
| `EDIFFG` | EDIFF*10 | Ionic convergence (negative = force-based) |

#### Smearing

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ISMEAR` | 1 | Smearing: -5 (tetrahedron), 0 (Gaussian), 1,2 (MP) |
| `SIGMA` | 0.2 | Smearing width (eV) |

#### Output Control

| Parameter | Default | Description |
|-----------|---------|-------------|
| `LWAVE` | .TRUE. | Write WAVECAR |
| `LCHARG` | .TRUE. | Write CHGCAR |
| `LORBIT` | 0 | Write PROCAR: 10, 11, 12 |
| `LAECHG` | .FALSE. | Write AECCAR for Bader analysis |

### KPOINTS Density Guidelines

| System Type | Recommended Grid | Notes |
|-------------|------------------|-------|
| Bulk metal | 12x12x12+ | Dense for accurate Fermi surface |
| Bulk semiconductor | 6x6x6 - 8x8x8 | Band gap materials |
| Surface slab | NxNx1 | Single k-point in vacuum direction |
| Molecule | 1x1x1 (Gamma) | Isolated system |

### Common POSCAR Formats

**Direct coordinates (fractional):**
```
Si bulk
5.43
...
Direct
0.00 0.00 0.00
0.25 0.25 0.25
```

**Cartesian coordinates (Angstrom):**
```
Si bulk
5.43
...
Cartesian
0.00 0.00 0.00
1.36 1.36 1.36
```

**Selective dynamics:**
```
Si slab
5.43
...
Selective dynamics
Direct
0.0 0.0 0.0 F F F
0.5 0.5 0.1 T T T
```

---

## Quick Start Checklist

- [ ] Cluster configured in Cluster Manager
- [ ] POSCAR prepared with correct format
- [ ] INCAR has appropriate parameters for calculation type
- [ ] KPOINTS grid adequate for system size
- [ ] POTCAR element selected
- [ ] Job name entered
- [ ] All files validated
- [ ] Job created and appears in job list
- [ ] Job submitted (press `r`)
- [ ] Monitor progress until completion
- [ ] Review results

---

## See Also

- [VASP Cluster Setup](VASP_CLUSTER_SETUP.md)
- [VASP Troubleshooting](VASP_TROUBLESHOOTING.md)
- [Silicon Example](../examples/vasp/Si_bulk/README.md)
- [VASP Wiki: INCAR](https://www.vasp.at/wiki/index.php/INCAR)
- [VASP Wiki: POSCAR](https://www.vasp.at/wiki/index.php/POSCAR)
