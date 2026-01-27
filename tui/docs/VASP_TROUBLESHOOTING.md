# VASP Troubleshooting Guide

This guide covers common VASP errors, their causes, and recovery procedures using CRYSTAL-TUI.

---

## Table of Contents

1. [Using the Error Handler](#using-the-error-handler)
2. [Common VASP Errors](#common-vasp-errors)
3. [Error Recovery Procedures](#error-recovery-procedures)
4. [INCAR Parameter Fixes](#incar-parameter-fixes)
5. [Debugging Strategies](#debugging-strategies)

---

## Using the Error Handler

### Automatic Error Detection

The TUI includes a `VASPErrorHandler` that automatically analyzes OUTCAR files for errors.

When a job fails, the TUI:
1. Parses OUTCAR for known error patterns
2. Classifies error severity (fatal, recoverable, warning)
3. Provides specific recovery suggestions
4. Suggests INCAR parameter changes

### Error Severity Levels

| Level | Icon | Description |
|-------|------|-------------|
| **FATAL** | X | Job cannot continue; structural fix required |
| **RECOVERABLE** | ! | Can be fixed with INCAR changes and restart |
| **WARNING** | i | Non-fatal but should be addressed |

### Viewing Error Reports

1. Select failed job in TUI
2. Press `v` to view details
3. Error report shows:
   - Error code and message
   - Line from OUTCAR
   - Recovery suggestions
   - Recommended INCAR changes

### Programmatic Error Analysis

```python
from runners.vasp_errors import analyze_vasp_errors

with open("OUTCAR", "r") as f:
    content = f.read()

errors, report = analyze_vasp_errors(content)
print(report)

# Get INCAR fixes
from runners.vasp_errors import VASPErrorHandler
handler = VASPErrorHandler()
fixes = handler.get_recovery_incar(errors)
print("Suggested INCAR changes:", fixes)
```

---

## Common VASP Errors

### ZBRENT: Bracketing Error

**Error message:**
```
ZBRENT: fatal error in bracketing
```

**Severity:** RECOVERABLE

**Cause:**
The Brent algorithm failed to find a minimum during ionic line search. Common in geometry optimizations with large forces or unreasonable geometries.

**Suggestions:**
1. Reduce POTIM (ionic step size) from 0.5 to 0.1-0.2
2. Switch optimizer: try IBRION=1 (quasi-Newton) or IBRION=3 (damped MD)
3. Check for unreasonable starting geometry
4. Increase EDIFF for looser SCF convergence initially

**Recommended INCAR changes:**
```
POTIM = 0.1
IBRION = 1
```

---

### EDDDAV: SCF Convergence Failure

**Error message:**
```
Error EDDDAV: Call to ZHEGV failed
```

or

```
SCF did not converge
```

**Severity:** RECOVERABLE

**Cause:**
Electronic self-consistency (SCF) did not converge within NELM iterations. Often occurs with metallic systems, incorrect smearing, or challenging electronic structures.

**Suggestions:**
1. Increase NELM (max electronic iterations) to 200
2. Try different algorithm: ALGO=All or ALGO=Damped
3. Reduce EDIFF (looser convergence, e.g., 1E-5)
4. Check k-point mesh density
5. For metals: increase SIGMA or use ISMEAR=-5 (tetrahedron)

**Recommended INCAR changes:**
```
NELM = 200
ALGO = All
```

---

### POSMAP: Internal Position Error

**Error message:**
```
POSMAP internal error: symmetry equivalent atom not found
```

**Severity:** FATAL

**Cause:**
Internal error in position mapping. Usually indicates overlapping atoms or atoms too close together.

**Suggestions:**
1. Check POSCAR for overlapping or too-close atoms
2. Increase unit cell if atoms are too close to periodic images
3. Verify all atomic positions are within valid ranges:
   - Direct: 0.0-1.0
   - Cartesian: within cell bounds

**No automatic INCAR fix available - structural correction required.**

---

### RSPHER: Subspace Rotation Error

**Error message:**
```
RSPHER: internal error: increase/decrease RSPHER
```

**Severity:** RECOVERABLE

**Cause:**
Subspace rotation error during electronic minimization. Often occurs when atoms are too close together.

**Suggestions:**
1. Check for atoms too close together
2. Try adding ADDGRID=.TRUE. to INCAR
3. Reduce POTIM for geometry optimization

**Recommended INCAR changes:**
```
ADDGRID = .TRUE.
```

---

### VERY BAD NEWS

**Error message:**
```
VERY BAD NEWS! internal error in subroutine ...
```

**Severity:** FATAL

**Cause:**
Serious internal VASP error. Can have many causes including numerical instabilities, memory issues, or corrupted files.

**Suggestions:**
1. Check OUTCAR for details above this message
2. Review input structure for anomalies
3. Consider restarting from a known good CONTCAR
4. Try reducing system size or k-points to isolate issue

---

### SGRCON: Symmetry Group Error

**Error message:**
```
SGRCON: ERROR: space group could not be determined
```

**Severity:** RECOVERABLE

**Cause:**
Symmetry detection failed. Atoms may have moved asymmetrically during relaxation.

**Suggestions:**
1. Set ISYM=0 to disable symmetry
2. Or increase SYMPREC to be more tolerant
3. Check that input structure has correct symmetry

**Recommended INCAR changes:**
```
ISYM = 0
```

---

### RHOSYG: Charge Density Symmetrization

**Error message:**
```
RHOSYG internal error: stars are not compatible
```

**Severity:** RECOVERABLE

**Cause:**
Error symmetrizing charge density. Often related to symmetry issues or atoms at special positions.

**Suggestions:**
1. Set ISYM=0 to disable symmetry
2. Check for atoms at special positions

**Recommended INCAR changes:**
```
ISYM = 0
```

---

### BRIONS: Ionic Relaxation Problems

**Error message:**
```
BRIONS problems: POTIM should be increased
```

**Severity:** RECOVERABLE

**Cause:**
Ionic relaxation algorithm encountered problems. Forces may be too large or step size inappropriate.

**Suggestions:**
1. Reduce POTIM (smaller ionic steps)
2. Try different optimizer: IBRION=1, 2, or 3
3. Check that forces on atoms are reasonable
4. Consider starting from different initial geometry

**Recommended INCAR changes:**
```
POTIM = 0.1
IBRION = 1
```

---

### PRICEL: Primitive Cell Error

**Error message:**
```
PRICEL: internal error, SGRCON returns not primitive cell
```

**Severity:** RECOVERABLE

**Cause:**
Problem finding primitive cell, likely a symmetry issue.

**Suggestions:**
1. Set SYMPREC to a larger value (e.g., 1E-4)
2. Or disable symmetry with ISYM=0

**Recommended INCAR changes:**
```
SYMPREC = 1E-4
```

---

### MEMORY: Allocation Failed

**Error message:**
```
malloc: Out of memory
```
or
```
cannot allocate memory for ...
```

**Severity:** FATAL

**Cause:**
Job ran out of memory. System too large for available RAM.

**Suggestions:**
1. Reduce NCORE/NPAR to use less memory per node
2. Request more memory or fewer cores per node
3. Consider reducing ENCUT or NGX/NGY/NGZ
4. For very large systems: use LREAL=Auto

**Recommended INCAR changes:**
```
LREAL = Auto
```

---

### BRMIX: Mixing Failed

**Error message:**
```
BRMIX: very serious problems
```

**Severity:** RECOVERABLE

**Cause:**
Charge density mixing failed. Common in systems with challenging electronic structures.

**Suggestions:**
1. Reduce AMIX and/or BMIX (e.g., 0.1)
2. Try different mixing: IMIX=1 with smaller AMIX
3. For magnetic systems: reduce AMIX_MAG

**Recommended INCAR changes:**
```
AMIX = 0.1
BMIX = 0.0001
```

---

### DENTET: Tetrahedron Method Error

**Error message:**
```
DENTET: can't reach specified accuracy
```

**Severity:** RECOVERABLE

**Cause:**
Tetrahedron method (ISMEAR=-5) failed, often due to insufficient k-points.

**Suggestions:**
1. Use Gaussian smearing instead: ISMEAR=0, SIGMA=0.05
2. For metals: ISMEAR=1 or 2 with appropriate SIGMA
3. Increase k-point density

**Recommended INCAR changes:**
```
ISMEAR = 0
SIGMA = 0.05
```

---

### PSMAXN: Augmentation Charge Error

**Error message:**
```
WARNING: PSMAXN for non-local potential too small
```

**Severity:** RECOVERABLE

**Cause:**
Augmentation charge overflow. FFT grid is too coarse for the pseudopotential.

**Suggestions:**
1. Increase ENCUT (denser FFT grid)
2. Explicitly set larger NGX, NGY, NGZ
3. Check POTCAR files are appropriate for the calculation

**Recommended INCAR changes:**
```
PREC = Accurate
```

---

## Error Recovery Procedures

### General Recovery Workflow

1. **Identify the error**
   - Check job status in TUI
   - View error report (press `v`)
   - Note error code and suggestions

2. **Apply fixes**
   - Create new job with modified INCAR
   - Or edit INCAR in work directory
   - Apply recommended parameter changes

3. **Restart calculation**
   - Use CONTCAR as new POSCAR if available
   - Add ISTART=1 to continue from WAVECAR
   - Submit new job

### Restart from CONTCAR

If calculation made progress before failing:

```bash
# Copy optimized structure
cp calculations/0001_silicon/CONTCAR calculations/0002_silicon_restart/POSCAR

# Update INCAR with fixes
# (edit INCAR with recommended changes)

# Submit new job
```

### Restart from WAVECAR

For faster SCF convergence on restart:

```
# Add to INCAR:
ISTART = 1    # Read WAVECAR
ICHARG = 1    # Read CHGCAR (optional)
```

### Progressive INCAR Loosening

For stubborn convergence issues, try progressively looser settings:

**Stage 1: Initial run**
```
EDIFF = 1E-6
ALGO = Normal
```

**Stage 2: If SCF fails**
```
EDIFF = 1E-5
ALGO = All
NELM = 200
```

**Stage 3: If still failing**
```
EDIFF = 1E-4
ALGO = Damped
NELM = 400
AMIX = 0.1
BMIX = 0.0001
```

---

## INCAR Parameter Fixes

### Quick Reference: Error to INCAR Fix

| Error | Primary Fix | Secondary Fix |
|-------|-------------|---------------|
| ZBRENT | `POTIM = 0.1` | `IBRION = 1` |
| EDDDAV | `NELM = 200` | `ALGO = All` |
| POSMAP | Check structure | - |
| RSPHER | `ADDGRID = .TRUE.` | Reduce POTIM |
| SGRCON | `ISYM = 0` | `SYMPREC = 1E-4` |
| RHOSYG | `ISYM = 0` | - |
| BRIONS | `POTIM = 0.1` | `IBRION = 1` |
| PRICEL | `SYMPREC = 1E-4` | `ISYM = 0` |
| MEMORY | `LREAL = Auto` | Reduce NCORE |
| BRMIX | `AMIX = 0.1` | `BMIX = 0.0001` |
| DENTET | `ISMEAR = 0` | `SIGMA = 0.05` |
| PSMAXN | `PREC = Accurate` | Increase ENCUT |

### Calculation Type Templates

**Robust SCF (for troubleshooting)**
```
PREC = Accurate
ENCUT = 520
EDIFF = 1E-5
ALGO = All
NELM = 200
AMIX = 0.1
BMIX = 0.0001
ISMEAR = 0
SIGMA = 0.1
```

**Robust Relaxation**
```
PREC = Accurate
ENCUT = 520
EDIFF = 1E-5
EDIFFG = -0.02
IBRION = 1
NSW = 100
POTIM = 0.1
ISYM = 0
```

**Large System**
```
PREC = Accurate
LREAL = Auto
NCORE = 4
ALGO = Fast
```

---

## Debugging Strategies

### Check Input Files

**POSCAR issues:**
```bash
# Check for overlapping atoms
python -c "
import numpy as np
# Read POSCAR and check minimum distances
# (use pymatgen or ASE for production)
"

# Visualize structure
# Open in VESTA, Avogadro, or similar
```

**INCAR issues:**
```bash
# Check for typos
grep -E "^[A-Z]" INCAR | sort

# Verify no conflicting parameters
# (e.g., IBRION=-1 with NSW>0)
```

**KPOINTS issues:**
```bash
# Check k-point density
head -5 KPOINTS
```

### Monitor Resources

```bash
# Check memory usage during run
ssh cluster "ps aux | grep vasp"

# Check disk space
ssh cluster "df -h ~/dft_jobs"
```

### OUTCAR Analysis

```bash
# Last energy values
grep "free  energy   TOTEN" OUTCAR | tail -10

# SCF convergence
grep -E "DAV:|RMM:|CG:" OUTCAR | tail -20

# Timing breakdown
grep -A 20 "General timing" OUTCAR

# Force convergence
grep "TOTAL-FORCE" OUTCAR | tail -5
```

### Common Issues Checklist

- [ ] POSCAR has correct number of atoms matching element counts
- [ ] POSCAR coordinates are reasonable (no overlapping atoms)
- [ ] INCAR has appropriate ENCUT (check POTCAR ENMAX)
- [ ] KPOINTS density adequate for system size
- [ ] POTCAR matches elements in POSCAR
- [ ] Sufficient memory for job size
- [ ] Disk space available in scratch directory

---

## Error Patterns by Calculation Type

### SCF Calculations

| Common Issue | Likely Error | Fix |
|--------------|--------------|-----|
| Not converging | EDDDAV | Increase NELM, try ALGO=All |
| Slow convergence | - | Reduce AMIX/BMIX |
| Oscillating energy | BRMIX | Use damped mixing |

### Geometry Optimization

| Common Issue | Likely Error | Fix |
|--------------|--------------|-----|
| Large forces | ZBRENT | Reduce POTIM |
| Structure explodes | POSMAP | Check initial structure |
| Not converging | BRIONS | Try IBRION=1 or 3 |
| Symmetry broken | SGRCON | Set ISYM=0 |

### DOS/Band Structure

| Common Issue | Likely Error | Fix |
|--------------|--------------|-----|
| Tetrahedron fails | DENTET | Use ISMEAR=0 |
| Wrong band gap | - | Check k-path, increase NBANDS |

---

## Getting Help

### Log Files to Collect

When reporting issues, gather:
1. INCAR
2. POSCAR (first 50 lines)
3. KPOINTS
4. OUTCAR (last 500 lines)
5. stderr/stdout from job script

### Online Resources

- [VASP Forum](https://www.vasp.at/forum/)
- [VASP Wiki](https://www.vasp.at/wiki/)
- [Materials Modeling Forum](https://matsci.org/)

---

## See Also

- [VASP Cluster Setup](VASP_CLUSTER_SETUP.md)
- [VASP Job Submission](VASP_JOB_SUBMISSION.md)
- [VASP Wiki: Common Errors](https://www.vasp.at/wiki/index.php/Category:Error_messages)
