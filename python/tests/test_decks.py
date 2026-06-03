"""Tests for the deck-generation seam (crystalmath-pvo).

These assert InputDeck *content* through the CodeDeckGenerator interface — no work
directory, no cluster. pymatgen-guarded (the VASP adapter needs it).
"""

from __future__ import annotations

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


def test_registry_resolves_code_and_rejects_unknown():
    """The registry is the seam: callers ask for a deck generator by DFT code."""
    from crystalmath.decks import get_deck_generator

    deck = get_deck_generator("vasp").generate(_mgo(), "scf", {})
    assert deck.code == "vasp"

    with pytest.raises(ValueError) as exc:
        get_deck_generator("not-a-code")
    assert "not-a-code" in str(exc.value)
