"""CRYSTAL23 output parser implementation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..base import DFTCode
from .base import OutputParser, ParsingResult, register_parser


class CrystalOutputParser(OutputParser):
    """Parser for CRYSTAL23 output files.

    Attempts to use CRYSTALpytools if available, falling back to
    lightweight regex extraction to avoid hard dependency failures.
    """

    def get_energy_unit(self) -> str:
        return "Hartree"

    async def parse(self, output_file: Path) -> ParsingResult:
        """Parse CRYSTAL output file.

        Tries CRYSTALpytools first, falls back to regex parsing.
        """

        # Try CRYSTALpytools first
        try:
            return await self._parse_with_crystalpytools(output_file)
        except ImportError:
            pass
        except Exception:
            # Fall through to regex parsing on any library error
            pass

        # Fallback to regex parsing
        return await self._parse_with_regex(output_file)

    async def _parse_with_crystalpytools(self, output_file: Path) -> ParsingResult:
        """Parse using CRYSTALpytools library."""

        from CRYSTALpytools.crystal_io import Crystal_output

        output = Crystal_output(str(output_file))

        return ParsingResult(
            success=True,
            final_energy=output.get_final_energy()
            if hasattr(output, "get_final_energy")
            else None,
            energy_unit="Hartree",
            convergence_status="CONVERGED"
            if output.is_converged()
            else "NOT_CONVERGED",
            scf_cycles=output.get_scf_convergence()[-1]
            if hasattr(output, "get_scf_convergence")
            else None,
            geometry_converged=None,
            errors=output.get_errors() if hasattr(output, "get_errors") else [],
            warnings=output.get_warnings()
            if hasattr(output, "get_warnings")
            else [],
            metadata={"parser": "CRYSTALpytools"},
        )

    async def _parse_with_regex(self, output_file: Path) -> ParsingResult:
        """Parse using regex patterns (fallback)."""

        content = output_file.read_text()

        # Extract energy
        energy: Optional[float] = None
        energy_match = re.search(r"TOTAL ENERGY\(.*?\)\s+([-\d.E+]+)", content)
        if energy_match:
            try:
                energy = float(energy_match.group(1))
            except ValueError:
                energy = None

        # Check convergence
        converged = any(
            marker in content for marker in ["CONVERGENCE", "SCF ENDED", "TTTTTT END"]
        )

        # Check for errors
        errors: list[str] = []
        for pattern in ["DIVERGENCE", "SCF NOT CONVERGED", "ERROR", "ABORT"]:
            if pattern in content:
                for line in content.split("\n"):
                    if pattern in line:
                        errors.append(line.strip())
                        break

        # Extract SCF cycles
        scf_cycles: Optional[int] = None
        cycle_matches = re.findall(r"CYC\s+(\d+)", content)
        if cycle_matches:
            try:
                scf_cycles = int(cycle_matches[-1])
            except ValueError:
                scf_cycles = None

        return ParsingResult(
            success=not errors and converged,
            final_energy=energy,
            energy_unit="Hartree",
            convergence_status="CONVERGED" if converged else "NOT_CONVERGED",
            scf_cycles=scf_cycles,
            geometry_converged=None,
            errors=errors[:5],
            warnings=[],
            metadata={"parser": "regex_fallback"},
        )


# Create singleton and register
_crystal_parser = CrystalOutputParser()
register_parser(DFTCode.CRYSTAL, _crystal_parser)


__all__ = ["CrystalOutputParser"]
