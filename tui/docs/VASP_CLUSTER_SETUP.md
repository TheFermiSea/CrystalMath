# VASP Cluster Setup Guide

**Epic**: crystalmath-ct3 (VASP Job Submission & Cluster Integration)
**Status**: In Progress (45% Complete)
**Last Updated**: 2025-12-25

---

## Overview

This guide explains how to configure CRYSTAL-TUI for submitting VASP jobs to remote clusters. The VASP integration supports multi-file input (POSCAR, INCAR, KPOINTS, POTCAR), automatic POTCAR retrieval from cluster libraries, and remote job monitoring.

## Prerequisites

### Local System
- CRYSTAL-TUI installed (`uv pip install -e ".[dev]"`)
- SSH key-based authentication to cluster (recommended)
- Python 3.10+

### Remote Cluster
- VASP installed and accessible
- SSH access configured
- VASP pseudopotential library (POTCAR files) installed
- Environment variable `VASP_PP_PATH` set (recommended)

---

## Quick Start

### 1. Launch CRYSTAL-TUI

```bash
cd tui/
crystal-tui
```

### 2. Open Cluster Manager

Press `c` to open the Cluster Manager screen.

### 3. Configure VASP Cluster

Fill in the cluster configuration form:

**Basic Info:**
- **Cluster Name**: `vasp-vm-cluster` (or any descriptive name)
- **DFT Code**: Select "VASP"

**SSH Connection:**
- **Hostname**: IP address or domain (e.g., `192.168.1.100`)
- **Port**: `22` (default SSH port)
- **Username**: Your cluster username
- **SSH Key File**: Path to private key (e.g., `~/.ssh/id_rsa`)
- **Use SSH Agent**: Enable if using ssh-agent
- **Strict Host Key Checking**: Enable for production (recommended)

**VASP Configuration:**
- **DFT Root Directory**: `/home/username/vasp` (VASP installation directory)
- **Executable Path**: `/opt/vasp/bin/vasp_std` (full path to VASP binary)
- **VASP_PP_PATH**: `/opt/vasp/potentials` (pseudopotential library path)
- **VASP Variant**: Select `Standard (vasp_std)`, `Gamma-point (vasp_gam)`, or `Non-collinear (vasp_ncl)`
- **Scratch Directory**: `~/dft_jobs` (where jobs will run)

### 4. Test Connection

Click **Test Connection** to verify:
- ✅ SSH connection succeeds
- ✅ VASP executable is accessible
- ✅ Cluster responds correctly

### 5. Save Cluster

Click **Save Cluster** to store the configuration.

---

## VASP Job Submission Workflow

### Creating a VASP Job

1. **Open New Job Screen**: Press `n`
2. **Select DFT Code**: Choose "VASP" from dropdown
3. **Click "Create Job"**: Opens VASP Input Manager

### VASP Input Manager

The VASP Input Manager provides a tabbed interface for all 4 required input files:

#### Tab 1: POSCAR
Paste or upload atomic positions and lattice vectors.

**Example POSCAR** (Silicon):
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

**Validation**: Checks for minimum 8 lines, valid scaling factor.

#### Tab 2: INCAR
Calculation parameters (default template provided).

**Default INCAR**:
```
# INCAR - VASP calculation parameters
# General
SYSTEM = VASP Calculation
PREC = Accurate
ENCUT = 400
EDIFF = 1E-6
ALGO = Normal
ISMEAR = 0
SIGMA = 0.1

# Electronic relaxation
NELM = 100

# Output
LWAVE = .TRUE.
LCHARG = .TRUE.
```

**Validation**: Checks for at least one `KEY = VALUE` parameter.

#### Tab 3: KPOINTS
K-point mesh specification (default Gamma-centered 4×4×4 provided).

**Default KPOINTS**:
```
Automatic mesh
0
Gamma
4 4 4
0. 0. 0.
```

**Validation**: Checks for minimum 4 lines.

#### Tab 4: POTCAR
Select element for pseudopotential (e.g., Si, C, O, Ti).

**IMPORTANT**: POTCAR files are **not uploaded**. Instead, they are:
1. Selected from the dropdown (element)
2. Retrieved from cluster's `VASP_PP_PATH` during job submission
3. Automatically copied to work directory

**Supported Elements**: Si, C, O, Ti, N, H (more can be added in cluster setup)

### Job Name & Validation

- **Job Name**: Enter descriptive name (e.g., `silicon_scf`)
- **Validate**: Click to check all files before submission
- **Create Job**: Creates job and adds to database

### What Happens Next

When you click **Create Job**:

1. ✅ All 4 files validated
2. ✅ Work directory created (`calculations/0001_job_name/`)
3. ✅ POSCAR, INCAR, KPOINTS written to disk
4. ✅ Metadata saved (`vasp_metadata.json` with POTCAR element)
5. ✅ Job added to database with `dft_code="vasp"`
6. ✅ Job appears in job list (status: "pending")

---

## Job Execution on Cluster

### Submission Process

When you run a VASP job (press `r` with job selected):

1. **SSH Connection**: Connects to configured cluster
2. **Remote Directory**: Creates `~/dft_jobs/job_<id>_<timestamp>/`
3. **File Upload**: Uploads POSCAR, INCAR, KPOINTS via SFTP
4. **POTCAR Retrieval**: Automatically retrieves POTCAR from cluster:
   ```bash
   # Tries in order:
   $VASP_PP_PATH/potpaw_PBE/<element>/POTCAR
   $VASP_PP_PATH/<element>/POTCAR
   $VASP_PP_PATH/PAW_PBE/<element>/POTCAR
   ```
5. **Job Script**: Creates execution script (`run_job.sh`)
6. **Execution**: Runs `nohup bash run_job.sh > output.log 2>&1 &`
7. **PID Capture**: Stores process ID for monitoring

### Execution Script

The generated `run_job.sh` script:

```bash
#!/bin/bash

# Source VASP environment (if cry23.bashrc exists)
if [ -f ~/VASP/vasp.bashrc ]; then
    source ~/VASP/vasp.bashrc
fi

# Set OpenMP threads (if configured)
export OMP_NUM_THREADS=4

# Execute VASP
/opt/vasp/bin/vasp_std

# Capture exit code
echo $? > .exit_code

exit $?
```

---

## Cluster Environment Requirements

### VASP Installation

Ensure VASP is properly installed and accessible:

```bash
# Test VASP executable
/opt/vasp/bin/vasp_std --version

# Check VASP environment
echo $VASP_PP_PATH
# Should output: /opt/vasp/potentials (or similar)
```

### Pseudopotential Library Structure

POTCAR files should be organized as:

```
$VASP_PP_PATH/
├── potpaw_PBE/
│   ├── Si/
│   │   └── POTCAR
│   ├── C/
│   │   └── POTCAR
│   ├── O/
│   │   └── POTCAR
│   └── ...
├── potpaw_LDA/
│   └── ...
└── ...
```

**Alternate structures supported**:
- `$VASP_PP_PATH/<element>/POTCAR`
- `$VASP_PP_PATH/PAW_PBE/<element>/POTCAR`

### Environment Setup

Create `~/vasp/vasp.bashrc` on cluster:

```bash
# VASP environment configuration
export VASP_ROOT=/opt/vasp
export VASP_PP_PATH=$VASP_ROOT/potentials
export PATH=$VASP_ROOT/bin:$PATH

# OpenMP settings (adjust for your system)
export OMP_NUM_THREADS=8
export OMP_STACKSIZE=512m
```

---

## Troubleshooting

### Connection Issues

**Problem**: "Connection refused" or "SSH connection failed"

**Solutions**:
1. Verify hostname and port are correct
2. Ensure SSH key is added to cluster's `~/.ssh/authorized_keys`
3. Test SSH manually: `ssh -i ~/.ssh/id_rsa username@hostname`
4. Check firewall settings on cluster

### POTCAR Retrieval Fails

**Problem**: "POTCAR not found for element 'Si'"

**Solutions**:
1. Verify `VASP_PP_PATH` is set on cluster:
   ```bash
   ssh username@cluster "echo \$VASP_PP_PATH"
   ```
2. Check POTCAR file exists:
   ```bash
   ssh username@cluster "ls \$VASP_PP_PATH/potpaw_PBE/Si/POTCAR"
   ```
3. Ensure element name matches directory name (case-sensitive)
4. Update cluster configuration with correct `VASP_PP_PATH`

### Job Submission Fails

**Problem**: Job doesn't start on cluster

**Solutions**:
1. Check VASP executable path is correct
2. Verify scratch directory permissions:
   ```bash
   ssh username@cluster "mkdir -p ~/dft_jobs && echo OK"
   ```
3. Review job logs in work directory
4. Ensure VASP license is valid on cluster

### File Validation Errors

**Problem**: "POSCAR invalid: file too short"

**Solutions**:
1. Check POSCAR has minimum required lines (8+)
2. Verify scaling factor on line 2 is numeric
3. Ensure lattice vectors are present (lines 3-5)
4. Verify atomic positions section is complete

**Problem**: "INCAR invalid: must contain at least one parameter"

**Solutions**:
1. Ensure INCAR has at least one `KEY = VALUE` line
2. Check for typos in parameter names
3. Avoid empty INCAR files

---

## Advanced Configuration

### Multiple Element POTCAR

For structures with multiple elements (e.g., SiO₂):

**Currently**: Only single-element POTCAR supported
**Workaround**: Create POTCAR manually on cluster and upload

**Future Enhancement** (ct3.2 improvements):
- Multi-element POTCAR selection in UI
- Automatic POTCAR concatenation for mixed structures

### Custom VASP Variants

To add custom VASP executables (e.g., vasp_gpu):

1. Open Cluster Manager (`c`)
2. Edit cluster configuration
3. Update **Executable Path**: `/opt/vasp/bin/vasp_gpu`
4. Save cluster

### Parallel Execution

**OpenMP Threads** (default):
- Configured in cluster setup
- Set via `OMP_NUM_THREADS` in job script

**MPI Parallelism** (future):
- Not yet implemented
- Planned for ct3.3 enhancement

---

## Implementation Status

### ✅ Completed Features (45%)

- **ct3.1**: SSH Runner Configuration ✅
  - Cluster manager UI
  - VASP-specific configuration fields
  - Connection testing
  - ConnectionManager integration

- **ct3.2**: Multi-File VASP Input Staging ✅
  - VASP Input Manager screen
  - Tabbed interface (POSCAR, INCAR, KPOINTS, POTCAR)
  - File validators
  - Default templates

- **ct3.3**: VASP Job Submission Workflow ✅
  - Integration with new job screen
  - Job creation from VASP files
  - POTCAR retrieval from cluster
  - Work directory creation

### 🔄 In Progress

- **ct3.4**: Job Monitoring & Status Tracking (pending)
- **ct3.5**: Output Retrieval System (pending)
- **ct3.6**: Benchmarking Integration (pending)
- **ct3.7**: Error Handling & Recovery (pending)
- **ct3.8**: Documentation (in progress - this file!)

---

## FAQ

**Q: Can I use VASP on multiple clusters?**
A: Yes! Configure each cluster separately in Cluster Manager. Each can have different VASP versions and POTCAR libraries.

**Q: What VASP versions are supported?**
A: Any VASP version that uses POSCAR/INCAR/KPOINTS/POTCAR format (VASP 5.x and 6.x).

**Q: Can I mix CRYSTAL and VASP jobs?**
A: Yes! CRYSTAL-TUI supports multiple DFT codes. Select the code when creating each job.

**Q: Where are VASP output files stored?**
A: Locally in `calculations/<job_name>/` and remotely in `~/dft_jobs/job_<id>_<timestamp>/`.

**Q: How do I benchmark VASP performance?**
A: Feature coming in ct3.6! Will extract timing data from OUTCAR automatically.

---

## Next Steps

1. **Complete ct3.4-3.7**: Finish monitoring, output retrieval, benchmarking, error handling
2. **Test on Production Cluster**: Validate with real VASP installation
3. **Multi-Element POTCAR**: Support mixed structures (SiO₂, TiO₂, etc.)
4. **MPI Support**: Add parallel execution options
5. **GUI Enhancements**: Improve POSCAR editor, visualization

---

## Resources

- **VASP Manual**: https://www.vasp.at/wiki/
- **POTCAR Format**: https://www.vasp.at/wiki/index.php/POTCAR
- **CRYSTAL-TUI Docs**: `../docs/`
- **Issue Tracker**: Use `bd` commands to track VASP-related issues

---

**Contributors**: Claude Sonnet 4.5
**Epic**: crystalmath-ct3 (VASP Job Submission & Cluster Integration)
**Progress**: 45% Complete (3/8 tasks done)
