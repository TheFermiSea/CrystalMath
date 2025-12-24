# Intel Xeon Architecture Optimizations

Your code is compiled with the Intel OneAPI suite. To unlock the full speed of the Sapphire Rapids architecture, the script exports specific environment variables before running the binary.

## 1. Pinning (I_MPI_PIN_DOMAIN=omp)

### The Concept: "Cache Locality"

Modern CPUs have L1 and L2 caches physically attached to specific cores. Accessing L1 cache takes ~1 nanosecond. Accessing main RAM takes ~100 nanoseconds.

If the Operating System moves a thread from Core 1 to Core 5, that thread loses access to its "Hot" data in Core 1's cache. It has to fetch it all from RAM again.

### The Fix

We tell the MPI library to Pin (lock) every thread to a specific physical core. The OS is forbidden from moving them.

## 2. Affinity (KMP_AFFINITY=compact)

### The Concept: "Neighbor Chatter"

Threads within the same MPI rank need to talk to each other constantly to sum up integrals.

### The Fix

`granularity=fine,compact`

This tells the scheduler to place threads of the same rank on adjacent physical cores.

**Result:** They can communicate via the ultra-fast L3 Cache shared by those cores, rather than going over the slower chip interconnect mesh.

## 3. Stack Size (OMP_STACKSIZE)

Each OpenMP thread needs private stack space for local variables and function calls. CRYSTAL23 performs deep recursion during integral evaluation.

### The Fix

The script automatically sets `OMP_STACKSIZE=256M` to prevent stack overflow errors that would otherwise cause segmentation faults.
