"""Quantum Espresso code configuration and registration.

Full QE support for pw.x (SCF, relax, vc-relax), ph.x (phonon),
and other QE executables.
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
    # Auxiliary input file mappings for restart/continuation
    # QE uses outdir/ for save directory, but these are common restart files
    auxiliary_inputs={
        # Restart from previous calculation
        ".xml": "data-file-schema.xml",  # XML data file for restart
        # Charge density and wavefunctions (for restart/nscf)
        ".wfc1": "wfc1.dat",  # Wavefunction data
        ".wfc2": "wfc2.dat",  # Wavefunction data (spin polarized)
        # Mixing files for SCF restart
        ".mix1": "mix1.dat",  # Charge mixing history
        ".mix2": "mix2.dat",  # Charge mixing history
        # Phonon/DFPT restart
        ".dyn": "dyn.out",  # Dynamical matrix for phonon restart
        ".recover": "recover.dat",  # Recovery file for ph.x
    },
    # Output file mappings
    auxiliary_outputs={
        # Primary data output
        "data-file-schema.xml": ".xml",  # XML data file with full results
        "data-file.xml": ".xml",  # Older format (pre-6.x)
        # Wavefunctions
        "wfc1.dat": ".wfc1",  # Wavefunction data
        "wfc2.dat": ".wfc2",  # Spin-down wavefunction
        # Charge density
        "charge-density.dat": ".rho",  # Charge density
        "charge-density.hdf5": ".rho.h5",  # HDF5 charge density (newer)
        # Band structure / DOS
        "bands.dat": ".bands",  # Band structure data
        "filband.dat": ".bands",  # Band structure alternative
        "fildos.dat": ".dos",  # Density of states
        "pdos_tot": ".pdos",  # Projected DOS total
        # Phonon outputs
        "dyn.out": ".dyn",  # Dynamical matrix
        "matdyn.modes": ".modes",  # Phonon modes
        # Projections
        "projwfc.dat": ".projwfc",  # Projected wavefunctions
        # XYZ coordinates (from pw2xyz.x post-processing)
        "pwscf.xyz": ".xyz",  # Optimized structure
    },
    # Executables
    serial_executable="pw.x",
    parallel_executable="pw.x",  # pw.x handles MPI internally
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
        "BFGS converged",
    ],
    error_patterns=[
        "Error",
        "convergence NOT achieved",
        "stopping ...",
        "CRASH",
        "task #",  # MPI error marker
        "segmentation fault",
    ],
)


# Auto-register when module is imported
register_code(DFTCode.QUANTUM_ESPRESSO, QE_CONFIG)


__all__ = ["QE_CONFIG"]
