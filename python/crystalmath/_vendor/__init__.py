"""Vendored backend code from the deprecated ``tui/src`` package (ADR-006).

This subpackage contains a *copy* of the pure-backend transitive closure that the
``crystalmath`` Python core needs (DFT code abstractions, the SLURM runner,
the materials API client, templates, the SQLite database layer, and the SSH
connection manager). It exists so that ``crystalmath-server`` can provide
cluster / SLURM / materials / template methods **without** the deprecated
``crystal-tui`` package being installed.

Provenance / rules (issue ``crystalmath-xi1``):

* The originals live under ``tui/src/`` which is **deprecated** per ADR-006.
* These files are **vendored by copy** and must NOT be hand-edited here. If a
  fix is needed, update the upstream source and re-vendor — never modify
  ``tui/`` itself either; vendoring is one-directional (copy out of ``tui/``).
* The internal imports are relative (``from .base``, ``from ..core.codes``),
  so mirroring the original ``core/`` and ``runners/`` directory layout under
  this single parent package keeps every import resolving unchanged.
"""
