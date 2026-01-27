"""
AiiDA integration module for CRYSTAL-TOOLS TUI.

This module provides the adapter layer between the TUI and AiiDA's
workflow engine, replacing the custom SQLite + orchestrator backend.

Submodules:
    calcjobs: CRYSTAL23 CalcJob implementations
    workchains: Workflow logic (base, geometry optimization, self-healing)
    converters: Structure format converters (pymatgen, POSCAR, .d12)
    setup: Computer and Code configuration utilities
    query_adapter: QueryBuilder adapter for database compatibility
    migration: SQLite to AiiDA migration utilities

Quick Start:
    # 1. Setup infrastructure
    ./scripts/setup_aiida_infrastructure.sh

    # 2. Configure computers and codes
    python -m src.aiida.setup.computers --localhost
    python -m src.aiida.setup.codes --localhost

    # 3. Migrate existing data (optional)
    python -m src.aiida.migration --sqlite-db ~/.crystal_tui/jobs.db

    # 4. Use in TUI
    from src.aiida.query_adapter import AiiDAQueryAdapter as Database

Note:
    AiiDA is an optional dependency. Install with: pip install crystal-tui[aiida]
    The module will raise ImportError with helpful message if AiiDA is not installed.
"""

__version__ = "0.1.0"

# Check if AiiDA is available before importing components
AIIDA_AVAILABLE = False
_AIIDA_IMPORT_ERROR: str | None = None

try:
    import aiida  # noqa: F401

    AIIDA_AVAILABLE = True
except ImportError as e:
    _AIIDA_IMPORT_ERROR = str(e)


def _check_aiida_available() -> None:
    """Raise ImportError with helpful message if AiiDA not installed."""
    if not AIIDA_AVAILABLE:
        raise ImportError(
            "AiiDA is not installed. Install with: pip install crystal-tui[aiida]\n"
            f"Original error: {_AIIDA_IMPORT_ERROR}"
        )


# Lazy-load components to avoid import errors when AiiDA is not installed
def __getattr__(name: str):
    """Lazy load AiiDA components on first access."""
    if name == "AiiDAQueryAdapter":
        _check_aiida_available()
        from .query_adapter import AiiDAQueryAdapter

        return AiiDAQueryAdapter
    elif name == "AiiDASubmitter":
        _check_aiida_available()
        from .submitter import AiiDASubmitter

        return AiiDASubmitter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AiiDAQueryAdapter", "AiiDASubmitter", "AIIDA_AVAILABLE"]
