# Troubleshooting Common Errors

## SCF Divergence

### Symptoms
- Output shows "DIVERGENCE" error
- SCF cycle fails to converge

### Analysis
The calculation is unstable. This usually indicates:
1. Atoms are too close together in the geometry
2. Poor initial guess for the wavefunction
3. Inappropriate mixing parameters

### Solutions
1. **Check your geometry** - Are atoms too close? Use visualization tools to verify structure.
2. **Use a better initial guess** - Add `GUESSP` keyword to use superposition of atomic densities
3. **Increase FMIXING** - Try `FMIXING 30` to use more conservative density mixing

## Memory Errors

### Symptoms
- "Insufficient memory" messages
- Segmentation fault (SIGSEGV)
- Process terminated unexpectedly

### Analysis
The job ran out of available memory. CRYSTAL23 stores large integral and density matrices in RAM.

### Solutions
1. **Increase MPI ranks** - Distribute memory across more processes:
   ```bash
   ./runcrystal input 14
   ```
   This spreads the memory load across 14 separate processes.

2. **Check stack size** - The script automatically sets `OMP_STACKSIZE=256M`. If issues persist, try using more MPI ranks to reduce per-process memory requirements.

## Slow Performance

### Symptoms
- Calculation runs much slower than expected
- High CPU usage but low throughput

### Diagnosis & Solutions

1. **Are you using pure MPI?**
   - Running with 56 ranks (one per core) causes high communication overhead
   - **Solution:** Use hybrid parallelism instead (e.g., 14 ranks × 4 threads)

2. **Is SCRATCH_BASE on an SSD?**
   - CRYSTAL23 writes gigabytes of temporary files
   - Network filesystems or slow HDDs will bottleneck I/O
   - **Solution:** Ensure `$SCRATCH_BASE` points to local NVMe/SSD storage

3. **Check thermal throttling**
   - Monitor CPU temperatures during calculation
   - Ensure adequate cooling for sustained workloads

## Missing Restart Files

### Symptoms
- "Cannot open fort.9" or "Missing .f9 file"
- Geometry optimization fails to restart

### Analysis
The calculation expects a wavefunction restart file that doesn't exist.

### Solutions
1. **Remove GUESSP keyword** if this is the first run (no previous wavefunction exists)
2. **Check file staging** - Ensure `.f9` file is in the same directory as `.d12` input
3. **Verify file permissions** - Script must be able to read auxiliary files

## Process Terminated Without Error

### Symptoms
- Calculation stops without clear error message
- Output file ends abruptly

### Investigation Steps
1. **Check the bottom of `.out` file** - Look for the last operation performed
2. **Review scratch directory** - Check if `~/tmp_crystal/` shows disk space issues
3. **Examine system logs** - Use `dmesg` to check for OOM killer or hardware errors

### Common Causes
- Out of memory (kernel killed the process)
- Disk space exhausted in scratch directory
- Network interruption (if using NFS)
- Hardware errors (check system logs)
