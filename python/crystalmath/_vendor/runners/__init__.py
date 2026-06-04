"""Vendored ``runners`` namespace (ADR-006, crystalmath-xi1).

Intentionally empty: unlike the original ``tui/src/runners/__init__.py`` this
does not re-export submodules, to avoid eagerly importing runner backends that
are outside the vendored closure.
"""
