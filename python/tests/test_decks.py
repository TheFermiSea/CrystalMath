"""Tests for the deck-generation seam (crystalmath-pvo).

These assert InputDeck *content* through the CodeDeckGenerator interface — no work
directory, no cluster. Tests that build a pymatgen Structure (VASP/CRYSTAL/QE) are
guarded with @requires_pymatgen; the YAMBO and staging tests run without it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_HAS_PYMATGEN = importlib.util.find_spec("pymatgen") is not None
requires_pymatgen = pytest.mark.skipif(
    not _HAS_PYMATGEN, reason="needs pymatgen (crystalmath[vasp]/[quacc] extra)"
)


def _mgo():
    """A simple two-element cell. Symmetry is irrelevant for VASP deck content;
    explicit species order makes POTCAR-symbol ordering deterministic."""
    from pymatgen.core import Lattice, Structure

    return Structure(Lattice.cubic(4.21), ["Mg", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])


@requires_pymatgen
def test_vasp_deck_generator_produces_input_deck():
    """VaspDeckGenerator returns an InputDeck carrying the VASP file contents."""
    from crystalmath.decks import VaspDeckGenerator

    deck = VaspDeckGenerator().generate(_mgo(), "scf", {})

    assert deck.code == "vasp"
    assert deck.files["POSCAR"].strip()
    assert deck.files["INCAR"].strip()
    assert deck.files["KPOINTS"].strip()
    assert deck.potcar_symbols == ["Mg", "O"]  # first-seen, deduped


@requires_pymatgen
def test_vasp_relax_adds_ionic_relaxation_keywords_absent_from_scf():
    """Each adapter owns its workflow_type -> keyword mapping: relax adds ionic
    relaxation directives (IBRION/NSW) that an scf single-point omits."""
    from crystalmath.decks import VaspDeckGenerator

    gen = VaspDeckGenerator()
    relax_incar = gen.generate(_mgo(), "relax", {}).files["INCAR"]
    scf_incar = gen.generate(_mgo(), "scf", {}).files["INCAR"]

    assert "IBRION" in relax_incar
    assert "NSW" in relax_incar
    assert "NSW" not in scf_incar


def test_stage_writes_deck_files_to_work_dir(tmp_path):
    from crystalmath.decks import InputDeck, stage

    deck = InputDeck(code="crystal23", files={"INPUT": "TITLE\nCRYSTAL\nEND\n"})
    stage(deck, tmp_path)

    assert (tmp_path / "INPUT").read_text() == "TITLE\nCRYSTAL\nEND\n"


def test_stage_vasp_fails_fast_without_pp_path(tmp_path, monkeypatch):
    """No VASP_PP_PATH -> a clear error before submission, and NO placeholder file."""
    from crystalmath.decks import DeckStagingError, InputDeck, stage

    monkeypatch.delenv("VASP_PP_PATH", raising=False)
    deck = InputDeck(
        code="vasp",
        files={"POSCAR": "p", "INCAR": "i", "KPOINTS": "k"},
        potcar_symbols=["Mg", "O"],
    )
    with pytest.raises(DeckStagingError, match="VASP_PP_PATH"):
        stage(deck, tmp_path)
    assert not (tmp_path / "POTCAR_NEEDED").exists()


def test_stage_vasp_fails_fast_when_potcars_missing(tmp_path, monkeypatch):
    """Library configured but incomplete -> fail fast, no placeholder."""
    from crystalmath.decks import DeckStagingError, InputDeck, stage

    monkeypatch.setattr("crystalmath.quacc.potcar.get_potcar_path", lambda: tmp_path)
    monkeypatch.setattr(
        "crystalmath.quacc.potcar.validate_potcars",
        lambda elems: (False, "Missing POTCARs for: Mg"),
    )
    deck = InputDeck(
        code="vasp",
        files={"POSCAR": "p", "INCAR": "i", "KPOINTS": "k"},
        potcar_symbols=["Mg", "O"],
    )
    with pytest.raises(DeckStagingError, match="POTCAR"):
        stage(deck, tmp_path)
    assert not (tmp_path / "POTCAR_NEEDED").exists()


@requires_pymatgen
def test_stage_vasp_assembles_potcar_when_library_available(tmp_path, monkeypatch):
    """With a usable library, a real POTCAR is staged for the deck's symbols."""
    from crystalmath.decks import InputDeck, stage

    monkeypatch.setattr("crystalmath.quacc.potcar.get_potcar_path", lambda: tmp_path)
    monkeypatch.setattr("crystalmath.quacc.potcar.validate_potcars", lambda elems: (True, None))

    captured = {}

    class _FakePotcar:
        def __init__(self, symbols, functional):
            captured["symbols"] = symbols
            captured["functional"] = functional

        def write_file(self, path):
            Path(path).write_text("POTCAR-CONTENT")

    import pymatgen.io.vasp as vasp_io

    monkeypatch.setattr(vasp_io, "Potcar", _FakePotcar)

    deck = InputDeck(
        code="vasp",
        files={"POSCAR": "p", "INCAR": "i", "KPOINTS": "k"},
        potcar_symbols=["Mg", "O"],
        metadata={"potcar_functional": "PBE"},
    )
    stage(deck, tmp_path)

    assert (tmp_path / "POTCAR").read_text() == "POTCAR-CONTENT"
    assert captured == {"symbols": ["Mg", "O"], "functional": "PBE"}


def _rocksalt_mgo():
    """A genuine Fm-3m (#225) rocksalt cell, so symmetry detection is exercised."""
    from pymatgen.core import Lattice, Structure

    return Structure.from_spacegroup(
        225, Lattice.cubic(4.21), ["Mg", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )


@requires_pymatgen
def test_crystal_deck_generator_produces_valid_d12():
    """CrystalDeckGenerator emits a real .d12: true space group, basis set, +TOLDEE."""
    from crystalmath.decks import get_deck_generator

    deck = get_deck_generator("crystal23").generate(_rocksalt_mgo(), "scf", {})

    assert deck.code == "crystal23"
    d12 = deck.files["INPUT"]
    assert "BASISSET" in d12
    assert "TOLDEE" in d12
    lines = d12.splitlines()
    space_group = int(lines[lines.index("CRYSTAL") + 2].strip())
    assert space_group == 225  # not the old hardcoded P1


@requires_pymatgen
def test_crystal_deck_maps_runner_parameters():
    """Runner config (functional, k-points, tolerances) maps onto the d12."""
    from crystalmath.decks import get_deck_generator

    deck = get_deck_generator("crystal23").generate(
        _rocksalt_mgo(),
        "scf",
        {"functional": "B3LYP", "shrink": (12, 24), "energy_convergence": 1e-9},
    )
    d12 = deck.files["INPUT"]
    lines = d12.splitlines()
    assert "B3LYP" in d12
    assert lines[lines.index("SHRINK") + 1].strip() == "12 24"
    assert int(lines[lines.index("TOLDEE") + 1].strip()) == 9  # 1e-9 -> 9


@requires_pymatgen
def test_crystal_deck_relax_enables_optgeom():
    """A relax workflow enables geometry optimization (OPTGEOM)."""
    from crystalmath.decks import get_deck_generator

    deck = get_deck_generator("crystal23").generate(_rocksalt_mgo(), "relax", {})
    assert "OPTGEOM" in deck.files["INPUT"]


@requires_pymatgen
def test_qe_deck_generator_produces_pw_in():
    """QeDeckGenerator emits a pw.in carrying the QE namelists."""
    from crystalmath.decks import get_deck_generator

    deck = get_deck_generator("quantum_espresso").generate(_mgo(), "scf", {})

    assert deck.code == "quantum_espresso"
    pw = deck.files["pw.in"]
    assert "calculation" in pw
    assert "ecutwfc" in pw


def test_yambo_deck_generator_maps_workflow_to_response():
    """YAMBO post-processes a prior run, so it takes no structure; the workflow
    type selects the nonlinear response (SHG/THG)."""
    from crystalmath.decks import get_deck_generator

    gen = get_deck_generator("yambo")
    shg = gen.generate(None, "shg", {}).files["yambo_nl.in"]
    thg = gen.generate(None, "thg", {}).files["yambo_nl.in"]

    assert 'NL_Response = "SHG"' in shg
    assert 'NL_Response = "THG"' in thg


@requires_pymatgen
def test_registry_resolves_code_and_rejects_unknown():
    """The registry is the seam: callers ask for a deck generator by DFT code."""
    from crystalmath.decks import get_deck_generator

    deck = get_deck_generator("vasp").generate(_mgo(), "scf", {})
    assert deck.code == "vasp"

    with pytest.raises(ValueError) as exc:
        get_deck_generator("not-a-code")
    assert "not-a-code" in str(exc.value)
