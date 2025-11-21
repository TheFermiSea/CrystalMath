# Explain Mode (Educational Dry Run)

**Feature:** `--explain` / `--dry-run` flag for runcrystal

## Overview

The explain mode provides an educational breakdown of what runcrystal will do **without actually executing** the calculation. This is perfect for:
- Learning how parallelism is configured
- Understanding resource allocation decisions
- Debugging execution issues
- Teaching CRYSTAL23 workflow best practices

## Usage

```bash
# Show what a serial run would do
runcrystal --explain my_calculation

# Show what a parallel run would do
runcrystal --dry-run my_calculation 14

# Both flags are equivalent
runcrystal --explain my_calculation 14
runcrystal --dry-run my_calculation 14
```

## What Explain Mode Shows

Explain mode displays a 5-section educational breakdown:

### 1. Hardware Detection
- Physical CPU cores detected on the system
- Number of MPI ranks requested
- How the script interprets your parallelism choice

**Example Output:**
```
1. Hardware Detection
   - Physical Cores: 56
   - Requested Ranks: 14 (1 = Serial/OpenMP)
```

### 2. Parallel Strategy
- Execution mode (Serial/OpenMP vs Hybrid MPI/OpenMP)
- Threads per MPI rank calculation
- **Educational WHY:** Explains the balance between memory (MPI) and speed (OpenMP)

**Example Output:**
```
2. Parallel Strategy
   - Mode: Hybrid MPI/OpenMP
   - Threads per Rank: 4
   - Why? This balances memory usage (MPI) with raw speed (OpenMP)
```

**Calculation:** 56 cores ÷ 14 ranks = 4 threads/rank

### 3. Intel Optimizations
- Thread pinning configuration (`I_MPI_PIN_DOMAIN`)
- Thread affinity settings (`KMP_AFFINITY`)
- Stack size configuration (prevents stack overflow)

**Example Output:**
```
3. Intel Optimizations
   - Pinning: omp
   - Affinity: compact,1,0,granularity=fine
   - Stack Size: 256M (Prevents stack overflow)
```

**Notes:**
- `I_MPI_PIN_DOMAIN=omp` ensures MPI ranks leave space for OpenMP threads
- `KMP_AFFINITY=compact` packs threads together for cache locality
- `OMP_STACKSIZE=256M` prevents CRYSTAL23 segmentation faults

### 4. File Staging
- Scratch directory path (with job name and PID)
- List of files that will be copied to scratch
- Auxiliary file auto-detection (.gui, .f9, .hessopt, .born)

**Example Output:**
```
4. File Staging
   - Scratch Directory: ~/tmp_crystal/cry_my_calc_12345/
   - Files to copy: my_calc.d12 + auxiliary files (.gui, .f9, .hessopt, .born)
```

### 5. Execution Command
- Exact command that would be executed
- Shows whether serial or parallel execution is used
- Displays full path to CRYSTAL23 binary

**Example Output (Serial):**
```
5. Execution Command
   - /opt/CRYSTAL23/bin/crystalOMP < INPUT > my_calc.out
```

**Example Output (Parallel):**
```
5. Execution Command
   - mpirun -np 14 /opt/CRYSTAL23/bin/PcrystalOMP < INPUT > my_calc.out
```

## When to Use Explain Mode

### 🎓 Learning
**Use Case:** You're new to CRYSTAL23 and want to understand how parallelism works.

```bash
# Compare serial vs parallel
runcrystal --explain water 1
runcrystal --explain water 14
```

**What You Learn:**
- How thread distribution changes with MPI ranks
- Why different binaries are used (crystalOMP vs PcrystalOMP)
- How Intel optimizations are applied

### 🐛 Debugging
**Use Case:** Your calculation isn't using resources correctly.

```bash
# Check if parallelism is configured as expected
runcrystal --dry-run my_job 8
```

**What You Check:**
- Are threads being distributed correctly?
- Is the right binary being selected?
- Are environment variables set properly?

### 📚 Documentation
**Use Case:** Writing documentation or tutorials for your research group.

```bash
# Generate example outputs for documentation
runcrystal --explain example_small 1 > serial_example.txt
runcrystal --explain example_large 14 > parallel_example.txt
```

### ✅ Verification
**Use Case:** Verify configuration on a new system before running expensive calculations.

```bash
# Test on new cluster node
runcrystal --dry-run test_job 28
```

**What You Verify:**
- CRYSTAL23 installation is detected correctly
- MPI binaries are available
- Thread distribution is optimal for the hardware

## Safety Features

Explain mode is **completely safe**:
- ✅ **No scratch directory created** - No file operations performed
- ✅ **No CRYSTAL23 execution** - Binary is never invoked
- ✅ **No state changes** - System is left unchanged
- ✅ **Fast execution** - Returns instantly (< 1 second)

## Integration with Help System

The explain mode is documented in the interactive help menu:

```bash
runcrystal --help
# Select "1. Quick Start Guide"
# Section 3 describes explain mode
```

## Educational Philosophy

The explain mode follows the V2/CrystalRun design principle:

> **"Show the math, explain the why."**

Every decision the script makes is:
1. **Displayed** - You see what will happen
2. **Explained** - You understand why it happens
3. **Educational** - You learn the underlying concepts

This transforms runcrystal from a "black box" into a teaching tool.

## Examples

### Example 1: Serial Execution
```bash
$ runcrystal --explain benzene

   ____________  ________________    __   ___  _____
  / ____/ __ \ \/ / ___/_  __/   |  / /  |__ \|__  /
 / /   / /_/ /\  /\__ \ / / / /| | / /   __/ / /_ <
/ /___/ _, _/ / /___/ // / / ___ |/ /___/ __/___/ /
\____/_/ |_| /_//____//_/ /_/  |_/_____/____/____/

╭─────────────────────────────────────────────────────╮
│  Dry Run / Explanation Mode                         │
│                                                     │
│  1. Hardware Detection                              │
│     - Physical Cores: 56                            │
│     - Requested Ranks: 1 (1 = Serial/OpenMP)        │
│                                                     │
│  2. Parallel Strategy                               │
│     - Mode: Serial/OpenMP                           │
│     - Threads per Rank: 56                          │
│     - Why? This balances memory usage (MPI) with... │
│                                                     │
│  3. Intel Optimizations                             │
│     - Pinning: Disabled (Serial)                    │
│     - Affinity: Default                             │
│     - Stack Size: 256M (Prevents stack overflow)    │
│                                                     │
│  4. File Staging                                    │
│     - Scratch Directory: ~/tmp_crystal/cry_benzene_123│
│     - Files to copy: benzene.d12 + auxiliary files... │
│                                                     │
│  5. Execution Command                               │
│     - /opt/CRYSTAL23/bin/crystalOMP < INPUT > ...   │
╰─────────────────────────────────────────────────────╯
```

### Example 2: Hybrid MPI/OpenMP Execution
```bash
$ runcrystal --dry-run graphene 14

   ____________  ________________    __   ___  _____
  / ____/ __ \ \/ / ___/_  __/   |  / /  |__ \|__  /
 / /   / /_/ /\  /\__ \ / / / /| | / /   __/ / /_ <
/ /___/ _, _/ / /___/ // / / ___ |/ /___/ __/___/ /
\____/_/ |_| /_//____//_/ /_/  |_/_____/____/____/

╭─────────────────────────────────────────────────────╮
│  Dry Run / Explanation Mode                         │
│                                                     │
│  1. Hardware Detection                              │
│     - Physical Cores: 56                            │
│     - Requested Ranks: 14 (1 = Serial/OpenMP)       │
│                                                     │
│  2. Parallel Strategy                               │
│     - Mode: Hybrid MPI/OpenMP                       │
│     - Threads per Rank: 4                           │
│     - Why? This balances memory usage (MPI) with... │
│                                                     │
│  3. Intel Optimizations                             │
│     - Pinning: omp                                  │
│     - Affinity: compact,1,0,granularity=fine        │
│     - Stack Size: 256M (Prevents stack overflow)    │
│                                                     │
│  4. File Staging                                    │
│     - Scratch Directory: ~/tmp_crystal/cry_graphene_456│
│     - Files to copy: graphene.d12 + auxiliary files...│
│                                                     │
│  5. Execution Command                               │
│     - mpirun -np 14 /opt/CRYSTAL23/bin/PcrystalOMP ..│
╰─────────────────────────────────────────────────────╯
```

## Comparison with Normal Execution

| Aspect | Normal Execution | Explain Mode |
|--------|------------------|--------------|
| File Operations | ✅ Creates scratch, copies files | ❌ No operations |
| CRYSTAL23 Execution | ✅ Runs calculation | ❌ Shows command only |
| Duration | Hours (depending on job) | < 1 second |
| Output | .out, .f9, .f98 files | Educational text |
| Safety | Requires valid input | Safe with any input |
| Use Case | Production runs | Learning, debugging, verification |

## Technical Implementation

### Architecture
- **Parsing:** Flag checked EARLY (before input validation)
- **Execution:** AFTER parallel_setup (requires CRY_JOB state)
- **Exit:** Clean exit before any file operations
- **Graceful Degradation:** Works without gum (fallback to plain text)

### Code Flow
```
1. Parse --explain/--dry-run flag
2. Validate input file exists
3. Run parallel_setup (populates CRY_JOB)
4. Build execution command preview
5. Display 5-section breakdown
6. Exit 0 (before scratch creation)
```

### Testing
Comprehensive integration tests ensure:
- Both flags (`--explain` and `--dry-run`) work identically
- No file operations occur (scratch directory not created)
- All 5 sections are displayed
- Educational "Why?" text is included
- Execution command is shown correctly
- Works for both serial and parallel modes

Test suite: `tests/integration/explain_mode_test.bats`

## See Also
- [ARCHITECTURE.md](../ARCHITECTURE.md) - Module design
- [Quick Start Guide](usage.md) - Basic runcrystal usage
- [Understanding Parallelism](parallelism.md) - Hybrid MPI/OpenMP concepts
- [Scratch Management](scratch.md) - File staging workflow
