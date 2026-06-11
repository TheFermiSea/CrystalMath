---
adr_id: 028
title: "Decoupled Slurm Workload Orchestration Over IPC"
status: "Accepted"
date: "2026-06-11"
macro_context: "crystalmath-tui-core"
---

# ADR-028: Decoupled Slurm Workload Orchestration Over IPC

## Context & Problem Statement
To satisfy the TUI unification strategy set out in **ADR-006**, CrystalMath must implement a native panel to track active SLURM scheduler metrics. Spawning local system processes (`Command::new("squeue")`) directly from the frontend TUI blocks local machines and breaks when running the interface on client machines separate from cluster backends.

## Proposed Architecture
We offload cluster CLI interactions entirely to the Python daemon layer (`python/crystalmath/server/`). The frontend communicates over the JSON-RPC IPC interface boundary (`src/ipc/`), keeping the layout engine headless and decoupled.

## Consequences & Trade-offs
*   **Pros**: Full compliance with ADR-006, fluid local frontend interface rendering, zero cross-platform binary overhead on laptops.
*   **Cons**: Introduces JSON serialization overhead across data transport boundaries.
