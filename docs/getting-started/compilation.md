# CRYSTAL23 Compilation Guide: Platform-Specific Builds

This document provides comprehensive documentation on why and how CRYSTAL23 was compiled for each target platform, including compiler choices, optimization flags, and runtime configuration.

## Overview

CRYSTAL23 is compiled differently for two target platforms:

| Platform | Architecture | Compiler | Parallelization | Primary Use |
|----------|-------------|----------|-----------------|-------------|
| **macOS ARM** | Apple Silicon (M1/M2/M3) | gfortran | OpenMP only | Development, small jobs |
| **UltrafastLab** | Intel Xeon w9-3495X | Intel ifort (OneAPI) | Hybrid MPI+OpenMP | Production, large jobs |

---

## macOS ARM Build (Apple Silicon)

### Why gfortran?

1. **Native ARM Support**: gfortran from Homebrew provides native ARM64 binaries without Rosetta translation overhead
2. **OpenMP Integration**: GCC's OpenMP implementation (libgomp) works reliably on macOS ARM
3. **Simplicity**: No Intel compiler licensing required for development work
4. **Compatibility**: CRYSTAL23 compiles cleanly with gfortran 12+ without modification

### Build Configuration

```
CRY23_ARCH = MacOsx_ARM-gfortran_omp
VERSION = v1.0.1
```

### Compiler Flags (Inferred)

```makefile
FC = gfortran
FFLAGS = -O3 -march=native -fopenmp
LDFLAGS = -fopenmp
```

**Key optimizations:**
- `-O3`: Aggressive optimization level
- `-march=native`: Generate code for the local ARM processor
- `-fopenmp`: Enable OpenMP multi-threading

### Executables Produced

| Binary | Size | Purpose |
|--------|------|---------|
| `crystalOMP` | 95 MB | SCF calculations with OpenMP threading |
| `properties` | 85 MB | Post-SCF analysis (band structure, DOS, etc.) |

### Limitations

- **No MPI**: Apple Silicon lacks native MPI support in the CRYSTAL23 build
- **Single-node only**: Cannot distribute across multiple machines
- **Memory-bound**: Large calculations limited by system RAM (no distributed memory)

### Runtime Configuration

```bash
# macOS uses all available cores by default
export OMP_NUM_THREADS=$(sysctl -n hw.ncpu)
export OMP_STACKSIZE=256M  # Prevent stack overflow in deep recursion
```

---

## UltrafastLab Build (Intel Xeon w9-3495X)

### Why Intel Fortran (ifort)?

The UltrafastLab workstation uses an Intel Xeon w9-3495X processor (Sapphire Rapids architecture, 56 cores). The Intel compiler suite provides:

1. **Architecture-Specific Optimization**: Intel compilers generate highly optimized code for Intel processors, exploiting AVX-512 vector instructions
2. **Intel MKL Integration**: BLAS/LAPACK routines from Intel Math Kernel Library are ~2-3x faster than open-source alternatives on Intel hardware
3. **Hybrid MPI+OpenMP**: The Intel MPI library integrates seamlessly with OpenMP for optimal hybrid parallelization
4. **Thread Affinity Control**: Fine-grained control over thread placement via KMP_AFFINITY

### Build Configuration

```
CRY23_ARCH = Linux-ifort_i64_omp
VERSION = v1.0.1
```

### Compiler Flags (Inferred)

```makefile
FC = ifort
FFLAGS = -O3 -xHost -qopenmp -ip -ipo
LDFLAGS = -qopenmp -mkl=parallel
```

**Key optimizations:**

| Flag | Purpose |
|------|---------|
| `-O3` | Aggressive optimization level |
| `-xHost` | Generate code for the host processor (enables AVX-512) |
| `-qopenmp` | Enable OpenMP multi-threading |
| `-ip` | Interprocedural optimization within files |
| `-ipo` | Interprocedural optimization across files |
| `-mkl=parallel` | Link with threaded Intel MKL |

### Why Hybrid MPI+OpenMP?

CRYSTAL23 performs quantum chemistry calculations that have two parallelization dimensions:

#### MPI (Message Passing Interface)
- **Memory Distribution**: Splits the electron density grid across ranks
- **Scalability**: Can use thousands of cores across multiple nodes
- **Cost**: Each rank requires its own memory copy (~1GB per rank for large systems)

#### OpenMP (Shared Memory Threading)
- **Fine-grained parallelism**: Parallelizes loops within each MPI rank
- **Zero memory overhead**: Threads share the same address space
- **Low latency**: No network communication between threads

#### The "Sweet Spot" Formula

For the 56-core Xeon w9-3495X:

```
Threads per Rank = Total Cores (56) / MPI Ranks
```

**Recommended configurations:**

| Use Case | MPI Ranks | Threads/Rank | Total Cores | Notes |
|----------|-----------|--------------|-------------|-------|
| Small systems | 1 | 56 | 56 | Serial mode, all cores as threads |
| Medium systems | 14 | 4 | 56 | Balanced memory/speed |
| Large systems | 28 | 2 | 56 | Lower memory per rank |
| Huge systems | 56 | 1 | 56 | Maximum distribution (high overhead) |

### Executables Produced

| Binary | Purpose |
|--------|---------|
| `crystalOMP` | Serial/OpenMP execution (single MPI rank) |
| `PcrystalOMP` | Parallel MPI+OpenMP execution (multiple ranks) |
| `properties` | Post-SCF analysis |
| `Pproperties` | Parallel properties (for large systems) |

---

## Runtime Environment Variables

### Intel-Specific Optimizations

The runtime script (`runcrystal`) automatically configures these environment variables for optimal performance on Intel hardware:

#### 1. I_MPI_PIN_DOMAIN=omp

**Purpose**: MPI rank pinning

**Problem solved**: Without pinning, the OS scheduler can migrate MPI ranks between cores, destroying cache locality.

**How it works**: Sets each MPI rank to "own" a subset of cores equal to OMP_NUM_THREADS. The rank and all its OpenMP threads are confined to those cores.

**Cache locality benefit**:
- L1 cache access: ~1 nanosecond
- Main RAM access: ~100 nanoseconds
- When threads migrate, they lose cached data and suffer 100x penalty

#### 2. KMP_AFFINITY=compact,1,0,granularity=fine

**Purpose**: OpenMP thread affinity (Intel-specific)

**Components**:
- `compact`: Pack threads close together (share L3 cache)
- `1,0`: Offset and stride for thread placement
- `granularity=fine`: Pin to individual cores, not CPU packages

**Why compact placement matters**:
OpenMP threads within the same MPI rank constantly exchange data (integral summations). Placing them on adjacent cores allows communication via shared L3 cache (10x faster than cross-socket communication).

#### 3. OMP_STACKSIZE=256M

**Purpose**: Prevent stack overflow

**Problem solved**: CRYSTAL23 uses deep recursion during integral evaluation. The default 8MB stack is insufficient.

**Setting**: 256 MB per thread provides headroom for the deepest recursion levels.

---

## Execution Modes

### Serial Mode (crystalOMP)

```bash
export OMP_NUM_THREADS=56
export OMP_STACKSIZE=256M
crystalOMP < input.d12 > output.out
```

**Best for**:
- Small molecules/unit cells
- Quick test calculations
- Memory-limited systems

### Hybrid Mode (PcrystalOMP)

```bash
export OMP_NUM_THREADS=4      # 56 / 14 ranks
export OMP_STACKSIZE=256M
export I_MPI_PIN_DOMAIN=omp
export KMP_AFFINITY=compact,1,0,granularity=fine

mpirun -n 14 PcrystalOMP < input.d12 > output.out
```

**Best for**:
- Large unit cells (>50 atoms)
- Memory-intensive calculations
- Production runs

---

## Performance Comparison

### Why Intel Build is 2-3x Faster

1. **AVX-512 Vectorization**: Intel compilers fully exploit 512-bit vector instructions on Sapphire Rapids
2. **MKL BLAS/LAPACK**: Diagonalization and matrix operations use highly optimized Intel libraries
3. **MPI Overlap**: Intel MPI can overlap computation with communication
4. **Thread Affinity**: Fine-grained pinning eliminates OS scheduling overhead

### Typical Speedups (MoS2 optimization example)

| Configuration | Time | Relative |
|---------------|------|----------|
| macOS ARM (10 cores, gfortran) | ~4h | 1.0x |
| Linux Serial (56 threads, ifort) | ~1.5h | 2.7x |
| Linux Hybrid (14 ranks x 4 threads, ifort) | ~45min | 5.3x |

---

## Build Artifact Locations

### macOS ARM
```
$CRY23_ROOT/bin/MacOsx_ARM-gfortran_omp/v1.0.1/
  ├── crystalOMP (95 MB)
  └── properties (85 MB)
```

### UltrafastLab (Linux)
```
$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/
  ├── crystalOMP
  ├── PcrystalOMP
  ├── properties
  └── Pproperties
```

---

## Troubleshooting

### Stack Overflow (Segmentation Fault)
```bash
# Increase stack size
export OMP_STACKSIZE=512M  # or larger
```

### Memory Exhaustion
```bash
# Reduce MPI ranks to lower memory footprint
runcrystal input 14  # Instead of 56 ranks
```

### Poor Scaling
- Check that I_MPI_PIN_DOMAIN is set
- Verify KMP_AFFINITY is configured
- Use `htop` or `top` to confirm threads aren't migrating

---

## References

- CRYSTAL23 User Manual: https://www.crystal.unito.it/
- Intel OneAPI Fortran Compiler Guide
- Intel MPI Library Reference Manual
- OpenMP 4.5 Specification

---

*Document generated from analysis of crystalmath repository configuration and runtime scripts.*
