"""Deck generation: a structure + workflow type become an :class:`InputDeck`.

A ``CodeDeckGenerator`` adapter exists per DFT code; ``stage()`` (later) writes a
deck to a work directory. See ``CONTEXT.md`` for the vocabulary (InputDeck,
CodeDeckGenerator, stage). Extracted from the SLURM runner (crystalmath-pvo).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class DeckStagingError(Exception):
    """Raised when an InputDeck cannot be staged (e.g. POTCAR library missing)."""


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
        elif isinstance(shrink_param, bool):
            # bool is an int subclass; coercing it to a 1x1x1 (Gamma-only) mesh
            # would silently destroy k-point sampling. Reject it.
            raise TypeError(f"shrink must be an int or (IS, ISP) pair, not bool: {shrink_param!r}")
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
        if tolinteg_param:
            tolinteg = tuple(tolinteg_param)
            # CRYSTAL's TOLINTEG keyword takes EXACTLY 5 integers (ITOL1..ITOL5);
            # a wrong-length tuple writes a deck CRYSTAL mis-parses. Fail fast.
            if len(tolinteg) != 5:
                raise ValueError(
                    f"TOLINTEG requires exactly 5 integers, got {len(tolinteg)}: {tolinteg!r}"
                )
        else:
            tolinteg = (7, 7, 7, 7, 14)
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


class QeDeckGenerator(CodeDeckGenerator):
    """``CodeDeckGenerator`` for Quantum ESPRESSO (pw.x)."""

    code = "quantum_espresso"

    def generate(self, structure, workflow_type, parameters) -> InputDeck:
        from pymatgen.io.pwscf import PWInput

        wf = _workflow_value(workflow_type)
        pseudo = {str(el): f"{el}.UPF" for el in structure.composition.elements}
        control = {
            "calculation": wf if wf in ("scf", "relax") else "scf",
            "pseudo_dir": parameters.get("pseudo_dir", "/opt/qe/pseudo"),
            "outdir": "./tmp",
            "prefix": "pwscf",
        }
        system = {
            "ecutwfc": parameters.get("ecutwfc", 60),
            "ecutrho": parameters.get("ecutrho", 480),
        }
        electrons = {"conv_thr": parameters.get("energy_convergence", 1e-6)}
        pwinput = PWInput(
            structure=structure,
            pseudo=pseudo,
            control=control,
            system=system,
            electrons=electrons,
        )
        return InputDeck(code=self.code, files={"pw.in": str(pwinput)})


class YamboNlDeckGenerator(CodeDeckGenerator):
    """``CodeDeckGenerator`` for YAMBO nonlinear optics (``yambo_nl``).

    YAMBO post-processes a prior DFT run, so it takes no structure (the argument
    is accepted for interface uniformity and ignored); the workflow type selects
    the nonlinear response (SHG/THG/SHIFT).

    The staged filename is ``yambo_nl.in`` to match the ``yambo_nl`` SLURM
    command (``mpirun yambo_nl -F yambo_nl.in``).
    """

    code = "yambo_nl"
    input_filename = "yambo_nl.in"

    def generate(self, structure, workflow_type, parameters) -> InputDeck:
        wf = _workflow_value(workflow_type)
        energy_range = parameters.get("energy_range", (0.5, 3.5))
        energy_steps = parameters.get("energy_steps", 500)
        damping = parameters.get("damping", 0.1)
        response_type = parameters.get("response_type", "SHG")
        nl_response = {
            "shg": "SHG",
            "nonlinear": "SHG",
            "thg": "THG",
            "shift": "SHIFT",
        }.get(wf, response_type)

        input_lines = [
            "# yambo_nl input for nonlinear optical response",
            "# Generated by CrystalMath",
            "",
            "nonlinear",
            "",
            "# Parallelization strategy",
            'NL_Threads = "e"',
            "",
            f"# Response type: {nl_response}",
            f'NL_Response = "{nl_response}"',
            "",
            "# Time integration parameters",
            "NL_nSteps = 10",
            "NL_ETStpsScale = 1.0",
            'NL_etStps = "0.001 Ha"',
            "",
            "# Damping/broadening",
            'NL_DampMode = "LORENTZIAN"',
            f'NL_Damping = "{damping} eV"',
            "",
            "# Long-range correction (0 for IPA)",
            "NL_LRC_alpha = 0.0",
            "",
            "# Energy range for response spectrum",
            f'NL_EnRange = "{energy_range[0]} {energy_range[1]} eV"',
            f"NL_EnSteps = {energy_steps}",
        ]
        return InputDeck(code=self.code, files={self.input_filename: "\n".join(input_lines)})


class YamboDeckGenerator(CodeDeckGenerator):
    """``CodeDeckGenerator`` for standard (linear) YAMBO — GW/BSE.

    The standard ``yambo`` SLURM command runs ``mpirun yambo -F yambo.in``, so a
    standard job MUST stage ``yambo.in`` (not ``yambo_nl.in``). Generating correct
    linear GW/BSE input content is not yet implemented here; rather than silently
    stage a nonlinear deck under the wrong filename (which the executable would
    mis-run), we fail fast so the gap is visible at submission time.

    For nonlinear optics use the ``yambo_nl`` code (:class:`YamboNlDeckGenerator`).
    """

    code = "yambo"

    def generate(self, structure, workflow_type, parameters) -> InputDeck:
        raise NotImplementedError(
            "Standard (linear) 'yambo' GW/BSE input generation is not implemented. "
            "The 'yambo' SLURM script runs `yambo -F yambo.in`, which requires a "
            "linear yambo input deck that this generator does not yet produce. "
            "For nonlinear optics (SHG/THG/SHIFT) use code='yambo_nl', which stages "
            "yambo_nl.in for `yambo_nl -F yambo_nl.in`."
        )


# DFT code -> deck generator. The seam: callers resolve a generator by code.
_REGISTRY: dict[str, type[CodeDeckGenerator]] = {
    "vasp": VaspDeckGenerator,
    "crystal23": CrystalDeckGenerator,
    "quantum_espresso": QeDeckGenerator,
    "yambo": YamboDeckGenerator,
    "yambo_nl": YamboNlDeckGenerator,
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


def stage(deck: InputDeck, work_dir: Any) -> None:
    """Write ``deck`` to ``work_dir`` — the only I/O step in deck generation.

    For VASP decks the POTCAR is assembled from the pseudopotential library
    (``VASP_PP_PATH``); a missing library fails fast (no placeholder is written).
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    for name, content in deck.files.items():
        (work_dir / name).write_text(content)
    if deck.code == "vasp" and deck.potcar_symbols:
        _stage_vasp_potcar(deck, work_dir)


def _stage_vasp_potcar(deck: InputDeck, work_dir: Path) -> None:
    """Assemble a real VASP POTCAR for ``deck.potcar_symbols`` from VASP_PP_PATH.

    Fails fast (``DeckStagingError``) when the library is unset/incomplete — VASP
    aborts on a missing POTCAR, so we surface it before the job is ever submitted.
    """
    from crystalmath.quacc.potcar import get_potcar_path, validate_potcars

    symbols = list(deck.potcar_symbols)
    potcar_path = get_potcar_path()
    if potcar_path is None:
        raise DeckStagingError(
            "Cannot stage VASP POTCAR: VASP_PP_PATH is not configured. Set the "
            "VASP_PP_PATH environment variable (or configure it in ~/.quacc.yaml) "
            f"before submitting VASP jobs. Required elements: {', '.join(symbols)}."
        )
    valid, error = validate_potcars(set(symbols))
    if not valid:
        raise DeckStagingError(f"Cannot stage VASP POTCAR (VASP_PP_PATH={potcar_path}): {error}")

    try:
        from pymatgen.io.vasp import Potcar
    except ImportError as exc:  # pragma: no cover - defensive
        raise DeckStagingError(
            "Cannot stage VASP POTCAR: pymatgen is required to build POTCAR files."
        ) from exc

    functional = deck.metadata.get("potcar_functional", "PBE")
    try:
        Potcar(symbols=symbols, functional=functional).write_file(str(work_dir / "POTCAR"))
    except Exception as exc:
        raise DeckStagingError(f"Failed to build VASP POTCAR for {symbols}: {exc}") from exc
