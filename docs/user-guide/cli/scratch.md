# Scratch Management System

CRYSTAL23 is an I/O Bound application. This means it spends a significant amount of time writing data to the hard drive. During the SCF cycle, it writes massive temporary files (Integrals, Fock matrices)—often exceeding 100GB for large systems.

## The Bottleneck

If you run a calculation directly in your Home directory (`/home/jens/project`):

- **Latency:** Writing to standard storage is slow. The CPU pauses calculation to wait for the disk to finish writing.
- **Risk:** If the filesystem is network-mounted (NFS), network lag can crash the job.
- **Clutter:** Failed jobs leave behind `fort.80`, `fort.2`, and `fort.98` files, filling up your drive.

## The Solution: Ephemeral Scratch

This script implements an Atomic Scratch Workflow:

### 1. Isolation

It creates a unique directory in `$SCRATCH_BASE` (usually local NVMe storage).

- **Format:** `cry_<InputName>_<ProcessID>`
- **Example:** `/tmp_crystal/cry_mgo_41992`

This guarantees that two jobs running at the same time never overwrite each other's files.

### 2. Staging

The script copies your input files (`.d12`, `.gui`, etc.) into this fast directory.

### 3. Execution

The `crystalOMP` or `PcrystalOMP` binary runs inside the scratch folder.

All junk files (`fort.2`, `fort.80`) are created here on the fast SSD. They never touch your Home directory.

### 4. Harvesting

Upon completion, the script checks for success and copies only the valuable results (`.out`, `.f9`, `.optinfo`) back to your Home folder.

### 5. Cleanup

The scratch folder is deleted instantly.

**Note:** If you force-kill a job (Ctrl+C), the script may not have time to delete the folder. Check `~/tmp_crystal/` periodically to clean up abandoned runs.
