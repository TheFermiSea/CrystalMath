"""Deck generation: a structure + workflow type become an :class:`InputDeck`.

A ``CodeDeckGenerator`` adapter exists per DFT code; ``stage()`` (later) writes a
deck to a work directory. See ``CONTEXT.md`` for the vocabulary (InputDeck,
CodeDeckGenerator, stage). Extracted from the SLURM runner (crystalmath-pvo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InputDeck:
    """A generated DFT input deck as content — pure data, no I/O.

    ``files`` maps filename -> text content. ``potcar_symbols`` carries the VASP
    POTCAR element symbols (the POTCAR file itself is assembled later by staging).
    """

    code: str
    files: dict[str, str]
    potcar_symbols: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# Workflow type -> VASP INCAR preset.
_VASP_WORKFLOW_PRESET = {
    "scf": "static",
    "static": "static",
    "relax": "relax",
    "bands": "bands",
    "dos": "dos",
}


class VaspDeckGenerator:
    """``CodeDeckGenerator`` for VASP. Absorbs ``crystalmath.vasp.generator``."""

    code = "vasp"

    def generate(self, structure, workflow_type, parameters) -> InputDeck:
        from crystalmath.vasp.generator import VaspInputGenerator
        from crystalmath.vasp.incar import IncarPreset

        preset = IncarPreset(_VASP_WORKFLOW_PRESET.get(workflow_type, "static"))
        inputs = VaspInputGenerator(structure, preset=preset).generate()
        return InputDeck(
            code=self.code,
            files={
                "POSCAR": inputs.poscar,
                "INCAR": inputs.incar,
                "KPOINTS": inputs.kpoints,
            },
            potcar_symbols=inputs.potcar_symbols,
        )


# DFT code -> deck generator. The seam: callers resolve a generator by code.
_REGISTRY: dict[str, type] = {
    "vasp": VaspDeckGenerator,
}


def get_deck_generator(code: str):
    """Return the deck generator for ``code``; raise ``ValueError`` if unknown."""
    try:
        factory = _REGISTRY[code]
    except KeyError:
        raise ValueError(
            f"No deck generator for code {code!r}. Known codes: {sorted(_REGISTRY)}"
        ) from None
    return factory()
