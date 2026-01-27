"""
Core abstractions for supported DFT codes.

This module defines the cross-code enums and configuration container used by
crystalmath to interact with multiple electronic-structure packages. The
`DFTCodeConfig` helper methods provide minimal, transportable command
construction that higher-level runners can adapt or override as needed.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class DFTCode(Enum):
    """Enumeration of supported density-functional theory codes."""

    CRYSTAL = "crystal"
    QUANTUM_ESPRESSO = "quantum_espresso"
    VASP = "vasp"
    YAMBO = "yambo"


class InvocationStyle(Enum):
    """How a code expects its primary input to be provided."""

    STDIN = "stdin"  # e.g., CRYSTAL: executable < input.d12
    FLAG = "flag"  # e.g., QE: pw.x -in input.in
    CWD = "cwd"  # e.g., VASP: run in directory containing POSCAR/INCAR


@dataclass
class DFTCodeConfig:
    """Static configuration describing how to run and parse a DFT code."""

    name: str
    display_name: str
    input_extensions: List[str] = field(default_factory=list)
    output_extension: str = ".out"
    auxiliary_inputs: Dict[str, str] = field(default_factory=dict)
    auxiliary_outputs: Dict[str, str] = field(default_factory=dict)
    serial_executable: str = ""
    parallel_executable: str = ""
    invocation_style: InvocationStyle = InvocationStyle.STDIN
    root_env_var: str = ""
    bashrc_pattern: Optional[str] = None
    energy_unit: str = ""
    convergence_patterns: List[str] = field(default_factory=list)
    error_patterns: List[str] = field(default_factory=list)

    def get_executable(self, parallel: bool = False) -> str:
        """Return the executable name for serial or parallel execution.

        Args:
            parallel: When True, prefer the parallel executable if defined.

        Raises:
            ValueError: If the requested executable is not configured.
        """

        candidate = self.parallel_executable if parallel else self.serial_executable
        if candidate:
            return candidate

        fallback = self.serial_executable or self.parallel_executable
        if fallback:
            return fallback

        raise ValueError(
            f"No executable configured for code '{self.display_name}'"
        )

    def build_command(
        self, input_file: Path, output_file: Path, parallel: bool = False
    ) -> List[str]:
        """Construct a best-effort command line for this code.

        The returned list is intended for execution with subprocess without
        invoking the shell directly. Redirections are expressed via a small
        `bash -lc` wrapper so that callers can remain agnostic to the
        invocation style while still supporting stdin/flag-based codes.

        Args:
            input_file: Path to the main input file.
            output_file: Path where standard output should be written.
            parallel: When True, prefer the parallel executable.

        Returns:
            A command list suitable for `subprocess.run`.
        """

        executable = self.get_executable(parallel)

        # Security: Quote paths to prevent shell injection via filenames with metacharacters
        quoted_input = shlex.quote(str(input_file))
        quoted_output = shlex.quote(str(output_file))

        if self.invocation_style is InvocationStyle.STDIN:
            cmd = f"{executable} < {quoted_input} > {quoted_output}"
            return ["bash", "-lc", cmd]

        if self.invocation_style is InvocationStyle.FLAG:
            cmd = f"{executable} -in {quoted_input} > {quoted_output}"
            return ["bash", "-lc", cmd]

        # InvocationStyle.CWD: assume caller sets cwd appropriately; we still
        # redirect stdout to the requested output file for consistency.
        cmd = f"{executable} > {quoted_output}"
        return ["bash", "-lc", cmd]


# Import at end to avoid circular dependencies during type checking
from .registry import DFT_CODE_REGISTRY  # noqa: E402  pylint: disable=wrong-import-position
from .parsers.base import OutputParser  # noqa: E402  pylint: disable=wrong-import-position

__all__ = [
    "DFTCode",
    "InvocationStyle",
    "DFTCodeConfig",
    "DFT_CODE_REGISTRY",
    "OutputParser",
]
