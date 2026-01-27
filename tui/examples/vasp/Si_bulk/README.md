# Silicon Bulk Example

This directory contains a complete VASP input set for a simple silicon bulk SCF calculation. Use this example to test the CRYSTAL-TUI VASP integration.

## Files

| File | Description |
|------|-------------|
| `POSCAR` | Silicon FCC unit cell (2 atoms) |
| `INCAR` | SCF calculation parameters |
| `KPOINTS` | 8x8x8 Gamma-centered k-mesh |

## Structure Details

- **Material:** Silicon (Si)
- **Structure:** Diamond cubic (FCC with 2-atom basis)
- **Lattice constant:** 5.43 Angstrom
- **Atoms:** 2 Si atoms at (0,0,0) and (0.25,0.25,0.25) fractional

## Calculation Setup

### INCAR Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| PREC | Accurate | High precision |
| ENCUT | 400 eV | Plane-wave cutoff |
| EDIFF | 1E-6 eV | Tight SCF convergence |
| ISMEAR | 0 | Gaussian smearing (semiconductor) |
| SIGMA | 0.1 eV | Smearing width |

### Expected Results

After a successful run, you should see:

- **Total energy:** approximately -10.8 to -10.9 eV (depends on POTCAR)
- **Band gap:** ~0.6-0.7 eV (DFT underestimate)
- **SCF cycles:** typically 10-20 iterations
- **Runtime:** 1-5 minutes on a typical workstation

## Using with CRYSTAL-TUI

### Step 1: Open New Job Screen

1. Launch CRYSTAL-TUI: `crystal-tui`
2. Press `n` for new job
3. Select "VASP" from DFT Code dropdown
4. Click "Create Job"

### Step 2: Enter Input Files

In the VASP Input Manager:

1. **POSCAR tab:** Copy contents of `POSCAR` file
2. **INCAR tab:** Copy contents of `INCAR` file (or use default)
3. **KPOINTS tab:** Copy contents of `KPOINTS` file (or use default 4x4x4)
4. **POTCAR tab:** Select "Silicon (Si)"

### Step 3: Create and Run

1. Enter job name: `silicon_test`
2. Click "Validate" to check files
3. Click "Create Job"
4. From main screen, select job and press `r` to run

### Step 4: Check Results

After job completes:

1. Select job and press `v` to view details
2. Check final energy in results panel
3. Output files in `calculations/XXXX_silicon_test/`

## Manual VASP Run

To run directly with VASP (without TUI):

```bash
# Create work directory
mkdir -p ~/vasp_test/silicon
cd ~/vasp_test/silicon

# Copy input files
cp /path/to/examples/vasp/Si_bulk/{POSCAR,INCAR,KPOINTS} .

# Link or copy POTCAR
cat $VASP_PP_PATH/potpaw_PBE/Si/POTCAR > POTCAR

# Run VASP
vasp_std > vasp.log 2>&1

# Check results
grep "free  energy   TOTEN" OUTCAR
```

## Modifications

### Testing Different k-meshes

Edit KPOINTS to test convergence:

```
# Coarse (fast)
4 4 4

# Medium
8 8 8

# Fine (accurate)
12 12 12
```

### Testing Geometry Optimization

Add to INCAR:

```
IBRION = 2      # Conjugate gradient
NSW = 10        # Max ionic steps
POTIM = 0.5     # Step size
EDIFFG = -0.01  # Force convergence (eV/Angstrom)
```

### Testing Band Structure

After SCF, create a separate job with:

```
ICHARG = 11     # Read CHGCAR, non-SCF
LORBIT = 11     # Project onto atoms
```

And use a k-path KPOINTS file.

## Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| "POTCAR not found" | Check VASP_PP_PATH on cluster |
| "SCF not converging" | Increase NELM to 200 |
| "Slow convergence" | Reduce AMIX to 0.2 |
| "Memory error" | Reduce NCORE or k-points |

### Expected Warnings

These warnings are normal:

```
# Normal for small systems:
"... symmetry operations are too inaccurate"
"... check if cartesian coordinates are very large"
```

## Files Not Included

POTCAR is not included due to VASP licensing restrictions. The TUI retrieves POTCAR automatically from your cluster's `VASP_PP_PATH`.

## Reference

- Silicon lattice constant: 5.431 Angstrom (experimental)
- Space group: Fd-3m (227)
- Point group: Oh
- Atoms per cell: 2

## See Also

- [VASP Cluster Setup](../../../docs/VASP_CLUSTER_SETUP.md)
- [VASP Job Submission](../../../docs/VASP_JOB_SUBMISSION.md)
- [VASP Troubleshooting](../../../docs/VASP_TROUBLESHOOTING.md)
