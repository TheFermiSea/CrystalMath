# Deep Dive: Hybrid Parallelism on Xeon w9-3495X

Your workstation is powered by an Intel Xeon w9-3495X (Sapphire Rapids) processor. This is a massive chip with 56 physical cores. To get maximum performance, we must use a strategy called Hybrid Parallelism.

## The Concepts

### 1. MPI (Message Passing Interface) → "Distributed Memory"

Think of MPI Ranks as separate workers in separate rooms.

- They cannot see each other's notes (Memory).
- To share data, they must pick up a phone and call (Network Communication).

**Pros:** Extremely stable. Can scale to thousands of computers.

**Cons:** High Memory Usage. If the simulation requires a 1GB Grid, and you run 56 MPI Ranks, you consume 56 GB of RAM because every worker needs their own copy.

### 2. OpenMP (Multi-Threading) → "Shared Memory"

Think of OpenMP Threads as separate workers in the SAME room.

- They all look at the same whiteboard (Shared Memory).
- Communication is instant.

**Pros:** Zero memory duplication. Very fast for local math.

**Cons:** Bottlenecks. If 56 workers try to write to the whiteboard at once, they block each other (Synchronization Overhead).

## The "Sweet Spot" Strategy

- If we run Pure MPI (56 Ranks), we run out of RAM.
- If we run Pure OpenMP (56 Threads), we hit synchronization delays.

**Solution:** We create Teams.

- We launch a few MPI Ranks (Team Leaders).
- Each Leader manages a group of OpenMP Threads (Workers).

## The Script's Algorithm

The script automatically calculates the perfect balance for your hardware:

$$ThreadsPerRank = \frac{TotalCores (56)}{RequestedRanks}$$

### Examples

| Command | Ranks (Teams) | Threads/Rank (Workers) | Total Cores | Verdict |
|---------|---------------|------------------------|-------------|---------|
| `./runcrystal mgo` | 1 | 56 | 56 | Good for small jobs. |
| `./runcrystal mgo 14` | 14 | 4 | 56 | Excellent for large jobs. Low memory overhead, high speed. |
| `./runcrystal mgo 28` | 28 | 2 | 56 | Good for very sparse systems. |
| `./runcrystal mgo 56` | 56 | 1 | 56 | Bad. High memory usage, high communication overhead. |

**Recommendation:** Start with Serial. If it's slow or crashes on memory, switch to 14 Ranks.
