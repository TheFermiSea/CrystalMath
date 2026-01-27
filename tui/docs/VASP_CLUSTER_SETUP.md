# VASP Cluster Setup Guide

This guide explains how to configure CRYSTAL-TUI for submitting VASP jobs to remote clusters.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [SSH Key Setup](#ssh-key-setup)
3. [TUI Cluster Configuration](#tui-cluster-configuration)
4. [VASP Environment Variables](#vasp-environment-variables)
5. [Testing Connectivity](#testing-connectivity)
6. [Advanced Configuration](#advanced-configuration)

---

## Prerequisites

### Local System Requirements

| Requirement | Details |
|-------------|---------|
| CRYSTAL-TUI | Installed via `uv pip install -e ".[dev]"` |
| SSH Client | OpenSSH (comes with macOS/Linux) |
| Python | 3.10 or higher |

### Remote Cluster Requirements

| Requirement | Details |
|-------------|---------|
| VASP | Installed and accessible (5.x or 6.x) |
| SSH Server | Running and accepting connections |
| POTCAR Library | Pseudopotential files organized by element |
| Shell | Bash (for environment scripts) |

---

## SSH Key Setup

SSH key-based authentication is strongly recommended for secure, password-free connections.

### Step 1: Generate SSH Key (if needed)

```bash
# Generate a new SSH key pair
ssh-keygen -t ed25519 -C "your_email@example.com"

# Or use RSA if ed25519 is not supported
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
```

### Step 2: Copy Public Key to Cluster

```bash
# Copy public key to remote cluster
ssh-copy-id username@cluster.example.com

# Or manually append to authorized_keys
cat ~/.ssh/id_ed25519.pub | ssh username@cluster "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

### Step 3: Verify Key-Based Login

```bash
# Test connection (should not prompt for password)
ssh username@cluster.example.com "hostname && echo 'SSH key auth working'"
```

### Step 4: Configure SSH Agent (Optional)

For keys with passphrases, use ssh-agent:

```bash
# Start ssh-agent
eval "$(ssh-agent -s)"

# Add your key
ssh-add ~/.ssh/id_ed25519
```

---

## TUI Cluster Configuration

### Opening the Cluster Manager

1. Launch CRYSTAL-TUI:
   ```bash
   cd tui/
   crystal-tui
   ```

2. Press `c` to open the Cluster Manager screen

### Configuration Form Fields

The Cluster Manager provides a form with the following sections:

#### Basic Information

| Field | Description | Example |
|-------|-------------|---------|
| **Cluster Name** | Descriptive name for this cluster | `vasp-hpc-cluster` |
| **DFT Code** | Select "VASP" from dropdown | VASP |

#### SSH Connection Settings

| Field | Description | Example |
|-------|-------------|---------|
| **Hostname** | IP address or domain name | `192.168.1.100` or `cluster.uni.edu` |
| **Port** | SSH port (usually 22) | `22` |
| **Username** | Your cluster username | `jsmith` |
| **SSH Key File** | Path to private key | `~/.ssh/id_ed25519` |
| **Use SSH Agent** | Enable if using ssh-agent | Toggle ON |
| **Strict Host Key Checking** | Verify host keys (recommended for production) | Toggle ON |

#### VASP Software Configuration

| Field | Description | Example |
|-------|-------------|---------|
| **DFT Root Directory** | VASP installation base | `/opt/vasp` or `~/vasp` |
| **Executable Path** | Full path to VASP binary | `/opt/vasp/bin/vasp_std` |
| **VASP_PP_PATH** | Pseudopotential library path | `/opt/vasp/potentials` |
| **VASP Variant** | Executable variant | `Standard (vasp_std)` |
| **Scratch Directory** | Job execution directory | `~/dft_jobs` |

#### VASP Variants

| Variant | Use Case |
|---------|----------|
| `vasp_std` | Standard calculations (most common) |
| `vasp_gam` | Gamma-point only (faster for large cells) |
| `vasp_ncl` | Non-collinear magnetism and spin-orbit coupling |

### Saving the Configuration

1. Fill in all required fields
2. Click **Test Connection** to verify settings
3. Click **Save Cluster** to store configuration

The cluster will appear in the cluster list and be available for job submission.

---

## VASP Environment Variables

### Required Environment Setup on Cluster

Create `~/vasp/vasp.bashrc` on the remote cluster:

```bash
#!/bin/bash
# VASP Environment Configuration

# VASP installation paths
export VASP_ROOT=/opt/vasp/6.4.1
export VASP_PP_PATH=$VASP_ROOT/potentials

# Add VASP binaries to PATH
export PATH=$VASP_ROOT/bin:$PATH

# OpenMP settings (adjust for your system)
export OMP_NUM_THREADS=8
export OMP_STACKSIZE=512m

# Intel MKL settings (if using Intel compilers)
export MKL_NUM_THREADS=8

# VASP output settings
export VASP_NCORE=4
```

### Pseudopotential Library Structure

VASP POTCAR files should be organized as follows:

```
$VASP_PP_PATH/
├── potpaw_PBE/           # PBE pseudopotentials
│   ├── Si/
│   │   └── POTCAR
│   ├── Si_sv/            # Semi-core variant
│   │   └── POTCAR
│   ├── C/
│   │   └── POTCAR
│   ├── O/
│   │   └── POTCAR
│   └── ...
├── potpaw_LDA/           # LDA pseudopotentials
│   ├── Si/
│   │   └── POTCAR
│   └── ...
└── PAW_PBE/              # Alternative naming
    └── ...
```

The TUI searches for POTCAR files in this order:
1. `$VASP_PP_PATH/potpaw_PBE/<element>/POTCAR`
2. `$VASP_PP_PATH/<element>/POTCAR`
3. `$VASP_PP_PATH/PAW_PBE/<element>/POTCAR`

### Verifying Environment Setup

Test your VASP environment on the cluster:

```bash
# Check VASP_PP_PATH
echo $VASP_PP_PATH
# Expected: /opt/vasp/potentials

# Verify POTCAR files exist
ls $VASP_PP_PATH/potpaw_PBE/Si/POTCAR
# Expected: POTCAR file listed

# Test VASP executable
which vasp_std
# Expected: /opt/vasp/bin/vasp_std

# Check VASP version (may show help or error - that's okay)
vasp_std --help 2>&1 | head -5
```

---

## Testing Connectivity

### Using the TUI Test Connection Feature

1. Open Cluster Manager (`c` key)
2. Fill in connection details
3. Click **Test Connection**

The TUI performs these checks:
- SSH connection establishment
- Remote hostname verification
- VASP executable accessibility

Successful test shows:
```
Connection successful! Remote host: cluster-node-01
DFT executable found at /opt/vasp/bin/vasp_std
```

### Manual SSH Testing

If TUI connection fails, test manually:

```bash
# Basic SSH test
ssh -v username@hostname "hostname && uname -a"

# Test with specific key
ssh -i ~/.ssh/id_rsa username@hostname "echo 'Connected'"

# Test VASP environment
ssh username@hostname "source ~/vasp/vasp.bashrc && which vasp_std"

# Test POTCAR access
ssh username@hostname "ls \$VASP_PP_PATH/potpaw_PBE/Si/POTCAR"
```

### Common Connection Issues

| Issue | Solution |
|-------|----------|
| "Connection refused" | Check hostname, port, and firewall settings |
| "Permission denied (publickey)" | Verify SSH key is in `authorized_keys` |
| "Host key verification failed" | Add host to `known_hosts` manually |
| "Executable not found" | Verify VASP path in cluster config |

---

## Advanced Configuration

### Multiple VASP Clusters

Configure different clusters for different purposes:

| Cluster Name | Use Case | VASP Variant |
|--------------|----------|--------------|
| `vasp-std-hpc` | Standard calculations | `vasp_std` |
| `vasp-gamma-hpc` | Large supercells | `vasp_gam` |
| `vasp-ncl-hpc` | Spin-orbit calculations | `vasp_ncl` |

### Custom VASP Executables

To use custom VASP builds (e.g., with GPU support):

1. Open Cluster Manager
2. Edit cluster configuration
3. Update **Executable Path** to custom binary:
   - GPU: `/opt/vasp/bin/vasp_gpu`
   - Custom: `/home/user/vasp-custom/bin/vasp_std`
4. Save cluster

### Scratch Directory Best Practices

| Environment | Recommended Scratch |
|-------------|---------------------|
| Personal workstation | `~/dft_jobs` |
| HPC with local scratch | `/scratch/$USER/vasp_jobs` |
| HPC with shared scratch | `/work/$USER/vasp_jobs` |
| Temporary filesystem | `/tmp/vasp_jobs` |

Ensure scratch directory:
- Has sufficient disk space (10+ GB per job)
- Is accessible from compute nodes
- Has proper permissions

### Parallel Execution Settings

#### OpenMP Threading

Set in cluster environment (`vasp.bashrc`):
```bash
export OMP_NUM_THREADS=8
export OMP_STACKSIZE=512m
```

#### MPI Configuration (Future)

MPI support is planned for future releases. Currently, jobs run with OpenMP parallelism only.

### SSH Configuration Tips

Create `~/.ssh/config` for convenience:

```
Host vasp-cluster
    HostName cluster.example.com
    User username
    IdentityFile ~/.ssh/id_ed25519
    Port 22
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Then use `vasp-cluster` as hostname in TUI configuration.

---

## Quick Reference

### Cluster Configuration Checklist

- [ ] SSH key pair generated and copied to cluster
- [ ] Test SSH connection without password
- [ ] VASP installed and accessible on cluster
- [ ] VASP_PP_PATH set with POTCAR files
- [ ] Scratch directory exists and is writable
- [ ] TUI cluster configuration saved
- [ ] Test Connection successful

### Environment Variables Summary

| Variable | Purpose | Example |
|----------|---------|---------|
| `VASP_ROOT` | VASP installation directory | `/opt/vasp/6.4.1` |
| `VASP_PP_PATH` | Pseudopotential library | `/opt/vasp/potentials` |
| `OMP_NUM_THREADS` | OpenMP thread count | `8` |
| `OMP_STACKSIZE` | OpenMP stack size | `512m` |

---

## Next Steps

After completing cluster setup:

1. [Submit your first VASP job](VASP_JOB_SUBMISSION.md)
2. [Troubleshoot common errors](VASP_TROUBLESHOOTING.md)
3. [Try the silicon example](../examples/vasp/Si_bulk/README.md)

---

## See Also

- [VASP Job Submission Guide](VASP_JOB_SUBMISSION.md)
- [VASP Troubleshooting Guide](VASP_TROUBLESHOOTING.md)
- [TUI Project Status](PROJECT_STATUS.md)
- [VASP Official Wiki](https://www.vasp.at/wiki/)
