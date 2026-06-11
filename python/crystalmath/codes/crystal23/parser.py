import contextlib
from typing import Any

from pydantic import BaseModel, Field


class CrystalTaskDoc(BaseModel):
    """
    Structured emmet-pattern documentation parser schema for CRYSTAL23 output files.
    Resolves crystalmath-u94.2.
    """

    energy: float | None = Field(None, description="Total final electronic energy in Hartree")
    spin_density: float | None = Field(None, description="Calculated spin density value")
    is_converged: bool = Field(
        False, description="True if self-consistent field cycle converged successfully"
    )
    geometry_history: list[dict[str, Any]] = Field(
        default_factory=list, description="List of intermediate geometric configurations"
    )

    @classmethod
    def from_output_string(cls, output_text: str) -> "CrystalTaskDoc":
        """Parses a raw CRYSTAL23 text block stream into a structured TaskDoc framework."""
        doc = cls(energy=None, spin_density=None, is_converged=False, geometry_history=[])

        for line in output_text.splitlines():
            if "TOTAL ENERGY" in line or "FINAL ENERGY" in line:
                with contextlib.suppress(ValueError, IndexError):
                    doc.energy = float(line.split()[-1])
            if "SCF ENDED - CONVERGENCE ACHIEVED" in line:
                doc.is_converged = True

        return doc
