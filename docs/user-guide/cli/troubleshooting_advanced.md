# Troubleshooting Guide - CRYSTAL23 Calculations

This guide explains common errors in CRYSTAL23 calculations and how to resolve them. The `runcrystal` tool includes automatic error analysis that detects these issues and provides helpful suggestions.

## Automatic Error Analysis

When a calculation fails, `runcrystal` automatically analyzes the output file and provides:

1. **Error Detection** - Identifies the type of error (SCF divergence, memory issues, basis set problems)
2. **Explanation** - Explains what the error means in student-friendly language
3. **Solutions** - Provides numbered steps to resolve the issue
4. **Error Log** - Shows the last 20 lines of the output file for detailed debugging

## Common Errors and Solutions

### 1. SCF Divergence

**Symptoms:**
- Output contains "DIVERGENCE DETECTED"
- Output contains "SCF NOT CONVERGED"
- Self-consistent field procedure fails after many iterations

**What it means:**
The calculation is numerically unstable. The SCF procedure is not converging to a stable electronic structure.

**Solutions:**

1. **Check your geometry**
   - Are atoms too close together? (typical bond lengths: C-C ~1.4 Å, C-H ~1.1 Å)
   - Run `EXTERNAL` keyword to optimize geometry first
   - Verify coordinates are in correct units (Angstroms vs. Bohr)

2. **Use a better initial guess**
   ```crystal
   GUESSP  # Read guess from previous calculation
   ```
   - Run a simpler calculation first (smaller basis, higher symmetry)
   - Use the wavefunction (.f9 file) as a starting point

3. **Adjust mixing parameters**
   ```crystal
   FMIXING
   30      # Increase mixing parameter (default: 40)
   END
   ```
   - Lower values = slower but more stable convergence
   - Try values between 20-50

4. **Enable level shifting**
   ```crystal
   LEVSHIFT
   2  0.3  # Enable level shifting with barrier 0.3 Ha
   END
   ```
   - Helps with difficult convergence cases

**Example:**
```bash
$ runcrystal my_calculation

⚠️  Detected SCF Divergence
The calculation is unstable. Try:
1. Check your geometry (atoms too close?)
2. Use a better initial guess (GUESSP)
3. Increase FMIXING (e.g., FMIXING 30)

--- Error Log (Last 20 lines) ---
...
```

---

### 2. Memory Errors

**Symptoms:**
- Output contains "insufficient memory"
- Output contains "SIGSEGV"
- Output contains "Segmentation fault"
- Calculation crashes during integral calculation

**What it means:**
The job requires more memory than available on a single process or node.

**Solutions:**

1. **Increase MPI parallelism** (most effective)
   ```bash
   # Instead of serial:
   runcrystal input

   # Use parallel with 14 ranks:
   runcrystal input 14
   ```
   - Distributes memory across multiple processes
   - Each process needs less memory
   - Recommended for large systems (>100 atoms, large basis sets)

2. **Reduce basis set size**
   ```crystal
   # Instead of:
   BS
   6 7         # 6-31G(d,p) - larger
   ...
   END

   # Try:
   BS
   6 2         # STO-3G - smaller
   ...
   END
   ```

3. **Use memory-efficient settings**
   ```crystal
   BIPOSIZE
   100000000   # Increase bipolar integral buffer (bytes)
   EXCHSIZE
   100000000   # Increase exchange integral buffer (bytes)
   ```

4. **Monitor memory usage**
   ```bash
   # On Linux:
   free -h

   # During calculation:
   top  # Watch memory usage of crystal processes
   ```

**Example:**
```bash
$ runcrystal large_system

⚠️  Memory Error Detected
The job ran out of memory.
Try increasing the number of MPI ranks (e.g., runcrystal input 14)
This spreads the memory load across more processes.

--- Error Log (Last 20 lines) ---
...
```

---

### 3. Basis Set Errors

**Symptoms:**
- Output contains "BASIS SET" and "ERROR"
- Missing or incorrect basis set definition
- Atomic number mismatch

**What it means:**
The basis set definition in your input file is incorrect or incomplete.

**Solutions:**

1. **Check BS keyword syntax**
   ```crystal
   BS
   # Atom type  Library code
   6 2         # Carbon: STO-3G
   1 2         # Hydrogen: STO-3G
   END
   ```
   - Ensure format is: `<atomic_number> <basis_code>`
   - One line per unique atom type
   - Must match atoms in geometry section

2. **Verify atomic numbers**
   - C=6, H=1, O=8, N=7, etc.
   - Check periodic table if unsure
   - Ensure consistency with CRYSTAL23 basis library

3. **Use standard basis sets** (safest)
   ```crystal
   # Small systems or testing:
   BS
   ALL 2       # STO-3G for all atoms
   END

   # Production calculations:
   BS
   ALL 7       # 6-31G(d,p) for all atoms
   END
   ```

4. **Check basis set library**
   ```bash
   # Location:
   $CRY23_ROOT/basis_sets/

   # Verify code numbers in:
   $CRY23_ROOT/doc/basis_sets.pdf
   ```

**Example:**
```bash
$ runcrystal my_calculation

⚠️  Basis Set Error
Problem with basis set definition.
1. Check BS keyword syntax in your .d12 file
2. Verify atomic numbers match basis set library
3. Try using a standard basis set (e.g., STO-3G)

--- Error Log (Last 20 lines) ---
...
```

---

## Advanced Troubleshooting

### Enabling Debug Output

For difficult-to-diagnose issues:

```crystal
PRINTOUT
99          # Maximum verbosity
END
```

Or use CRYSTAL23 test mode:
```bash
# Create test input with more diagnostics
crystalOMP < input.d12 > output.out 2>&1
```

### Common Workflow

1. **Start simple** - Use small basis set, tight convergence criteria
2. **Check output** - Always inspect `.out` file for errors
3. **Iterate** - Gradually increase complexity once stable
4. **Save wavefunction** - Use `.f9` files to restart calculations

### File Staging

The `runcrystal` tool automatically stages auxiliary files:
- `.gui` - Wavefunction guess
- `.f9` - Converged wavefunction (for restarts)
- `.hessopt` - Hessian matrix (for optimizations)
- `.born` - Born effective charges (for phonons)

Ensure these files are present if using GUESSP or restarting calculations.

---

## Getting Help

If automatic error analysis doesn't identify the issue:

1. **Check the full output file**
   ```bash
   less my_calculation.out
   ```
   - Look for ERROR, WARNING, ABNORMAL messages
   - Check for convergence history

2. **Consult CRYSTAL23 documentation**
   ```bash
   cry-docs search "your topic"
   ```

3. **Verify input file syntax**
   - Use provided examples as templates
   - Check keyword spelling (case-sensitive)

4. **Test with minimal example**
   - Reduce system size
   - Simplify calculation type
   - Use known-working input as reference

---

## Error Analysis Implementation

The automatic error analysis system:

- **Location**: `lib/cry-exec.sh`
- **Function**: `analyze_failure()`
- **Triggered**: Automatically when `exec_crystal_run()` returns non-zero exit code
- **Output**: Student-friendly error messages with numbered solutions
- **Fallback**: Works without `gum` (plain text mode)

This system uses pattern matching on the output file to detect:
1. SCF convergence issues (DIVERGENCE, SCF NOT CONVERGED)
2. Memory problems (insufficient memory, SIGSEGV, Segmentation fault)
3. Basis set errors (BASIS SET + ERROR)

If no pattern matches, it shows the last 20 lines of the log file for manual inspection.
