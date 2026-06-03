"""Tests for the deck-generation seam (crystalmath-pvo).

These assert InputDeck *content* through the CodeDeckGenerator interface — no work
directory, no cluster. pymatgen-guarded (the VASP adapter needs it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pymatgen", reason="deck generation needs pymatgen")


def _mgo():
    """A simple two-element cell. Symmetry is irrelevant for VASP deck content;
    explicit species order makes POTCAR-symbol ordering deterministic."""
    from pymatgen.core import Lattice, Structure

    return Structure(Lattice.cubic(4.21), ["Mg", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def test_vasp_deck_generator_produces_input_deck():
    """VaspDeckGenerator returns an InputDeck carrying the VASP file contents."""
    from crystalmath.decks import VaspDeckGenerator

    deck = VaspDeckGenerator().generate(_mgo(), "scf", {})

    assert deck.code == "vasp"
    assert deck.files["POSCAR"].strip()
    assert deck.files["INCAR"].strip()
    assert deck.files["KPOINTS"].strip()
    assert deck.potcar_symbols == ["Mg", "O"]  # first-seen, deduped


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


def test_registry_resolves_code_and_rejects_unknown():
    """The registry is the seam: callers ask for a deck generator by DFT code."""
    from crystalmath.decks import get_deck_generator

    deck = get_deck_generator("vasp").generate(_mgo(), "scf", {})
    assert deck.code == "vasp"

    with pytest.raises(ValueError) as exc:
        get_deck_generator("not-a-code")
    assert "not-a-code" in str(exc.value)
