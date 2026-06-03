"""CRYSTAL23 code configuration and registration."""

from __future__ import annotations

from .base import DFTCode, DFTCodeConfig, InvocationStyle
from .registry import register_code


CRYSTAL_CONFIG = DFTCodeConfig(
    name="crystal",
    display_name="CRYSTAL23",
    # Input/Output files
    input_extensions=[".d12"],
    output_extension=".out",
    # Auxiliary file mappings (from cry-config.sh STAGE_MAP)
    auxiliary_inputs={
        ".gui": "fort.34",  # External geometry (EXTERNAL keyword)
        ".f9": "fort.20",  # SCF guess/wave function
        ".f98": "fort.98",  # Formatted wave function
        ".hessopt": "HESSOPT.DAT",  # Hessian for optimization
        ".born": "BORN.DAT",  # Born effective charge tensor
        ".optinfo": "OPTINFO.DAT",  # Optimization state
        ".freqinfo": "FREQINFO.DAT",  # Frequency calculation state
    },
    # Output file mappings (from cry-config.sh RETRIEVE_MAP)
    auxiliary_outputs={
        "fort.9": ".f9",  # Binary wave function
        "fort.98": ".f98",  # Formatted wave function
        "HESSOPT.DAT": ".hessopt",
        "OPTINFO.DAT": ".optinfo",
        "FREQINFO.DAT": ".freqinfo",
        "fort.25": ".f25",  # Properties output
    },
    # Executables
    serial_executable="crystalOMP",
    parallel_executable="PcrystalOMP",
    invocation_style=InvocationStyle.STDIN,
    # Environment
    root_env_var="CRY23_ROOT",
    bashrc_pattern="cry23.bashrc",
    # Parsing
    energy_unit="Hartree",
    convergence_patterns=[
        "CONVERGENCE",
        "SCF ENDED",
        "TTTTTT END",
    ],
    error_patterns=[
        "DIVERGENCE",
        "SCF NOT CONVERGED",
        "ERROR",
        "ABORT",
        "FATAL",
    ],
)


# Auto-register when module is imported
register_code(DFTCode.CRYSTAL, CRYSTAL_CONFIG)


__all__ = ["CRYSTAL_CONFIG"]
