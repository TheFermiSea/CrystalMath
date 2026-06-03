"""Deck generation: a structure + workflow type become an :class:`InputDeck`.

A ``CodeDeckGenerator`` adapter exists per DFT code; ``stage()`` (later) writes a
deck to a work directory. See ``CONTEXT.md`` for the vocabulary (InputDeck,
CodeDeckGenerator, stage). Extracted from the SLURM runner (crystalmath-pvo).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


def _workflow_value(workflow_type: Any) -> str:
    """Normalize a ``WorkflowType`` enum (or a plain string) to its string value."""
    return str(getattr(workflow_type, "value", workflow_type)).lower()


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


class CodeDeckGenerator(ABC):
    """The per-DFT-code seam: ``(structure, workflow type, parameters) -> InputDeck``.

    One adapter per DFT code, resolved via :func:`get_deck_generator`.
    """

    code: str

    @abstractmethod
    def generate(self, structure: Any, workflow_type: Any, parameters: dict) -> InputDeck:
        """Build the input deck for ``structure`` and ``workflow_type``."""


# Workflow type -> VASP INCAR preset.
_VASP_WORKFLOW_PRESET = {
    "scf": "static",
    "static": "static",
    "relax": "relax",
    "bands": "bands",
    "dos": "dos",
}


class VaspDeckGenerator(CodeDeckGenerator):
    """``CodeDeckGenerator`` for VASP. Absorbs ``crystalmath.vasp.generator``."""

    code = "vasp"

    def generate(self, structure, workflow_type, parameters) -> InputDeck:
        from crystalmath.vasp.generator import VaspInputGenerator
        from crystalmath.vasp.incar import IncarPreset

        preset = IncarPreset(_VASP_WORKFLOW_PRESET.get(_workflow_value(workflow_type), "static"))
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


class CrystalDeckGenerator(CodeDeckGenerator):
    """``CodeDeckGenerator`` for CRYSTAL23. Wraps the symmetry-aware d12 generator."""

    code = "crystal23"

    def generate(self, structure, workflow_type, parameters) -> InputDeck:
        from crystalmath._vendor.core.materials_api.transforms.crystal_d12 import (
            CrystalD12Generator,
            OptimizationConfig,
        )

        functional = parameters.get("functional", "PBE")

        # k-point mesh -> SHRINK (IS, ISP): accept an (IS, ISP) pair, a single int,
        # or fall back to a sensible default.
        shrink_param = parameters.get("shrink", parameters.get("kpoints"))
        if shrink_param is None:
            shrink = (8, 8)
        elif isinstance(shrink_param, (int, float)):
            shrink = (int(shrink_param), int(shrink_param))
        else:
            shrink = (int(shrink_param[0]), int(shrink_param[-1]))

        # energy_convergence -> positive TOLDEE exponent (10^-N Hartree).
        energy_convergence = parameters.get("energy_convergence", 1e-7)
        try:
            toldee = int(round(-math.log10(abs(float(energy_convergence)))))
        except (ValueError, ZeroDivisionError):
            toldee = 7
        if toldee < 1:
            toldee = 7

        tolinteg_param = parameters.get("tolinteg")
        tolinteg = tuple(tolinteg_param) if tolinteg_param else (7, 7, 7, 7, 14)
        basis_set = parameters.get("basis_set", "POB-TZVP-REV2")

        optimization = None
        if _workflow_value(workflow_type) == "relax":
            optimization = OptimizationConfig(enabled=True, opt_type="FULLOPTG")

        # generate_full_input only writes TOLDEE inside an OPTGEOM block, so inject
        # it explicitly to guarantee a positive SCF threshold in every deck.
        d12 = CrystalD12Generator.generate_full_input(
            structure,
            title=parameters.get("title", "crystalmath SLURM job"),
            basis_set=basis_set,
            functional=functional,
            shrink=shrink,
            tolinteg=tolinteg,
            toldee=toldee,
            optimization=optimization,
            extra_keywords=["TOLDEE", str(toldee)],
        )
        return InputDeck(code=self.code, files={"INPUT": d12})


# DFT code -> deck generator. The seam: callers resolve a generator by code.
_REGISTRY: dict[str, type[CodeDeckGenerator]] = {
    "vasp": VaspDeckGenerator,
    "crystal23": CrystalDeckGenerator,
}


def get_deck_generator(code: str) -> CodeDeckGenerator:
    """Return the deck generator for ``code``; raise ``ValueError`` if unknown."""
    try:
        factory = _REGISTRY[code]
    except KeyError:
        raise ValueError(
            f"No deck generator for code {code!r}. Known codes: {sorted(_REGISTRY)}"
        ) from None
    return factory()
