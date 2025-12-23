"""Quantum Espresso code configuration and registration (stub).

This is a stub implementation. Full QE support will be added in a future phase.
"""

from __future__ import annotations

from .base import DFTCode, DFTCodeConfig, InvocationStyle
from .registry import register_code


QE_CONFIG = DFTCodeConfig(
    name="quantum_espresso",
    display_name="Quantum Espresso",
    # Input/Output files
    input_extensions=[".in", ".pwi"],
    output_extension=".out",
    # Auxiliary file mappings (pseudopotentials handled separately)
    auxiliary_inputs={
        # Pseudopotential files are typically in a separate directory
        # and referenced in the input file
    },
    # Output file mappings
    auxiliary_outputs={
        # QE outputs various files depending on calculation type
        # xml output, wavefunctions, charge density, etc.
    },
    # Executables
    serial_executable="pw.x",
    parallel_executable="mpirun pw.x",
    invocation_style=InvocationStyle.FLAG,  # pw.x -in input.in > output.out
    # Environment
    root_env_var="ESPRESSO_ROOT",
    bashrc_pattern="qe.bashrc",
    # Parsing
    energy_unit="Ry",  # Rydberg
    convergence_patterns=[
        "convergence has been achieved",
        "End of self-consistent calculation",
        "JOB DONE",
    ],
    error_patterns=[
        "Error",
        "convergence NOT achieved",
        "stopping ...",
        "CRASH",
    ],
)


# Auto-register when module is imported
register_code(DFTCode.QUANTUM_ESPRESSO, QE_CONFIG)


__all__ = ["QE_CONFIG"]
