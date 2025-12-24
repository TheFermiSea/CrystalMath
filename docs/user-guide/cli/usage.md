# CRYSTAL23 Run Script: Usage Guide

## The Basics

The script accepts two arguments: the input file name and (optionally) the number of MPI ranks.

### Syntax

```bash
./runcrystal <input_name> [mpi_ranks]
```

### Examples

#### 1. Serial Execution (The Default)

```bash
./runcrystal mgo
```

**Target:** Single node, Shared Memory.

**Logic:** Uses 1 Process, but spawns threads equal to your CPU core count.

**Use Case:** Geometry optimizations, small unit cells, frequency calculations on standard molecules.

#### 2. Hybrid Parallel Execution

```bash
./runcrystal mgo 14
```

**Target:** Distributed Memory (MPI) + Shared Memory (OpenMP).

**Logic:** Launches 14 distinct processes. Each process manages its own chunk of memory.

**Use Case:** Large unit cells (>100 atoms), large basis sets, or when you encounter memory limits.

## Auto-Magic File Handling

You do not need to manually copy auxiliary files. If the script sees `mgo.d12`, it also looks for and stages:

- `mgo.gui` (External Geometry)
- `mgo.f9` (Wavefunction Restart)
- `mgo.hessopt` (Hessian Restart)
- `mgo.born` (Born Charges)
