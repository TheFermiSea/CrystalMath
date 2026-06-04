# ADR-008: Standardize Structure and Input/Output on pymatgen + ASE; `CodeDeckGenerator` Becomes a Thin Adapter

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-007](adr-007-redesign-overview-adopt-ecosystem.md)

## Context

CrystalMath maintains **four overlapping per-DFT-code seams** that all answer the same
question — "turn a structure + a workflow type into input files, then parse the output" — and
none is authoritative:

- `python/crystalmath/decks/__init__.py` — the **new** `CodeDeckGenerator` ABC (`:40`) producing
  a pure-data `InputDeck` (`:26`, `files: dict[str,str]`, `potcar_symbols`, `metadata`). This is
  the seam `CONTEXT.md` locks as canonical. But its `CrystalDeckGenerator` (`:85`) still wraps a
  hand-rolled `crystal_d12` writer, and its `VaspDeckGenerator` (`:63`) merely re-dispatches to —
- `python/crystalmath/vasp/generator.py` (`VaspInputGenerator`, `:130`) plus its own
  `vasp/incar.py` and `vasp/kpoints.py` — a standalone INCAR/KPOINTS/POSCAR builder, still called
  **directly** by `api.py` as `vasp.generate_inputs`, in parallel with the deck seam above.
- `python/crystalmath/_vendor/core/codes/` — a **fork-copy** code abstraction (`crystal.py`,
  `vasp.py` (8.7k), `quantum_espresso.py`, `yambo.py` (20k), `registry.py`) carried under the
  no-hand-edit `_vendor/` rule, duplicating exactly the codes the `decks` seam now owns.
- `python/crystalmath/quacc/potcar.py` — a **fourth** POTCAR-assembly/validation path, separate
  from both the deck-staging POTCAR logic and the VASP generator.

The result is hand-written POSCAR/d12/pw.in emitters, a hand-coded
`SHRINK`/`TOLDEE`/`TOLINTEG`/INCAR-defaults dictionary, and three POTCAR code paths — all
reinventing I/O that the materials ecosystem solved a decade ago. `integrations/pymatgen_bridge.py`
(1,277 LOC) and the vendored `materials_api/clients/optimade.py` (25k) already pull pymatgen and an
OPTIMADE client into the tree, so the heavy dependencies are *already present* — they are simply
not the substrate the writers stand on. With zero users, this is the moment to stop maintaining a
parallel multi-code I/O universe.

**Ecosystem state of the art.** The field has converged on a layered division of labor:

- **ASE** (Larsen et al. 2017) provides a uniform `Calculator`/`FileIOCalculator` interface — a
  per-code input writer + output parser to a common (energy/forces/stress/`Atoms`) API — for ~40
  engines including VASP, Quantum ESPRESSO, and CRYSTAL14, with `SocketIOCalculator` (i-PI
  protocol) as the escape hatch for codes lacking a native wrapper. `Atoms` is the universal
  structure object; phonopy consumes ASE/QE/CRYSTAL force sets natively.
- **pymatgen** (Ong et al. 2013) adds the richer `InputSet`/`InputGenerator` pattern — opinionated,
  *validated* presets (`MPRelaxSet`, `MPStaticSet`) that map `(Structure, calc-type)` to a complete,
  sanity-checked deck — plus robust output parsers (`Vasprun`, `Outcar`). `Structure` is `MSONable`
  and round-trips with ASE `Atoms`.
- **atomate2** (Ganose et al. 2025) formalizes precisely the abstraction CrystalMath is hand-coding:
  JSONable `InputGenerator` classes (wrapping pymatgen sets) emit standardized `TaskDocument`
  schemas, with every code uniformly termed a "Calculator" so heterogeneous workflows compose.
- **OPTIMADE** (Andersen et al. 2021) is the stable (v1.2) federated query/exchange schema spanning
  20+ providers and 30M+ structures — the right boundary for sourcing and exporting structures.

The 2025 interoperability literature underlines the lesson: standardizing the I/O *schema* across
engines is the hard, valuable part, and per-code idiosyncrasies are exactly where a small team
bleeds maintenance cost (Steensen et al. 2025).

## Decision

**Standardize on a single in-memory structure object and re-implement the locked `CodeDeckGenerator`
/ `InputDeck` seam as thin per-code adapters over ASE and pymatgen, retiring all hand-rolled writers
and the three duplicate code seams.**

1. **One structure object: pymatgen `Structure` (interconverting with ASE `Atoms`).** All internal
   APIs, IPC payloads, and stored documents carry `Structure` (`MSONable`, free stable JSON).
   `Atoms` is used at the ASE-calculator boundary via `pymatgen.io.ase.AseAtomsAdaptor`. No bespoke
   structure type survives.

2. **Keep the locked vocabulary, replace the implementation.** `CodeDeckGenerator`,
   `InputDeck` (pure data: `files`, `potcar_symbols`, `metadata`), and `stage()` (CONTEXT.md) remain
   the named seam — this ADR does **not** rename them. Each concrete generator becomes a **~50-line
   adapter** that *delegates*:
   - `VaspDeckGenerator` → pymatgen `VaspInputGenerator`/`VaspInputSet` (the reference for INCAR
     correctness and POTCAR assembly). Deletes `vasp/generator.py`, `vasp/incar.py`,
     `vasp/kpoints.py`, and `quacc/potcar.py`; POTCAR comes from one pymatgen path keyed by
     `PMG_VASP_PSP_DIR`/`VASP_PP_PATH`.
   - `QeDeckGenerator` → ASE `Espresso` `FileIOCalculator` (input writing) + pymatgen
     `io.pwscf`/ASE parsers (output). Deletes the hand-built pw.in path in `_vendor/core/codes/`.
   - `CrystalDeckGenerator` → ASE `crystal` `FileIOCalculator` as the substrate, with a thin
     code-specific layer for the CRYSTAL23-only keywords (`OPTGEOM`, `SHRINK`, `TOLDEE`,
     `TOLINTEG`, `GUESSP`) that ASE's CRYSTAL14 calculator does not cover. Contribute the
     CRYSTAL23 delta upstream where feasible rather than maintaining a fork.
   - `YamboDeckGenerator` / `YamboNlDeckGenerator` → ASE `SocketIOCalculator`/`FileIOCalculator`
     extension points plus a thin code-specific generator+parser (YAMBO has no first-class ASE or
     pymatgen support; this is the one place hand-written I/O is justified, and it should be the
     *only* one).

3. **Presets are pymatgen `InputSet` subclasses, not a parameters dict.** The workflow-type →
   validated-preset mapping that `decks` currently hand-codes (`_VASP_WORKFLOW_PRESET`, `:54`)
   becomes `InputGenerator` subclassing in the VASP/QE adapters, inheriting pymatgen's validation
   instead of an untyped `parameters` dict.

4. **OPTIMADE is the external structure-interchange boundary.** Sourcing inputs (MP/COD/OQMD/NOMAD)
   and exporting results go through the OPTIMADE client; the bespoke `materials_api` wrapper layer
   that re-implements OPTIMADE/`mp_api` access (`_vendor/core/materials_api/`, ~100k across
   `service.py`/`cache.py`/`clients/`) is deleted in favor of the OPTIMADE client and `mp_api` that
   pymatgen/quacc already depend on.

5. **Retire the duplicates.** Delete `_vendor/core/codes/`, `vasp/generator.py` (+ `incar.py`,
   `kpoints.py`), and `quacc/potcar.py`. `api.py`'s `vasp.generate_inputs` and all runners route
   through the one `get_deck_generator(code)` seam. The result schema for parsed output is the typed
   per-code `TaskDocument` defined by ADR-009 (this ADR provides the I/O; ADR-009 owns the document
   schema and ADR-010 owns the store).

## Alternatives Considered

**A. Keep hand-rolling per-code writers (the status quo, consolidated under `decks`).**
*Why not:* The 2025 interoperability work shows the recurring cost of multi-code DFT is precisely
the per-code idiosyncrasy that maintained libraries already absorb; a small team cannot track
INCAR/d12/pw.in tag evolution across five codes (Steensen et al. 2025). ASE and pymatgen exist for
exactly this and are *already dependencies* in the tree. Reinvention here is unjustified.

**B. Adopt atomate2's `InputGenerator` + `TaskDocument` as a dependency wholesale.**
atomate2 is the most direct precedent for CrystalMath's design goal (Ganose et al. 2025).
*Why not as the dependency:* atomate2 does not support CRYSTAL23 or YAMBO — two of CrystalMath's five
codes. We therefore adopt the **pattern** (per-code `InputGenerator` seam + a typed
`TaskDocument`-style schema) and the pymatgen substrate beneath it, but keep our own thin seam so the
unsupported codes have a home. (Borrowing the pattern, not the package, is the same call ADR-011
makes for the workflow layer, under the general "adopt, don't reinvent" rule of ADR-007.)

**C. AiiDA plugins/parsers (`aiida-quantumespresso`, `aiida-crystal-dft`) as the I/O layer.**
AiiDA provides per-code `CalcJob` input generators and `Parser` classes with gold-standard
provenance (Huber et al. 2020). *Why not as the foundation:* it forces the full AiiDA ORM
(PostgreSQL/RabbitMQ) onto the laptop-first TUI just to write an INCAR. AiiDA remains the opt-in
heavyweight backend (ADR-012); its plugin/parser separation is the reference design, not the default
substrate.

**D. ASE only, skipping pymatgen `InputSets`.**
ASE alone covers the codes but is lowest-common-denominator (energy/forces/stress) with **no
opinionated, validated presets** — every INCAR/SHRINK tag would still be chosen by hand (Larsen et
al. 2017). *Why not:* that re-creates today's hand-coded defaults dict. We take ASE for breadth of
code coverage and the socket/file escape hatches, and pymatgen `InputSets` for validated presets and
rich output parsing — they are complementary, not substitutes.

**E. signac directory-as-statepoint model for staging.**
*Why not:* signac is a data-management/statepoint layer, not an input/output writer; it does not
solve per-code deck generation and would add a parallel model. Out of scope for this seam.

## Consequences

### Positive
- One structure object (`Structure`/`Atoms`) and one per-code seam (`CodeDeckGenerator` adapters)
  replace four overlapping implementations; the `decks` seam shrinks from an *invention* to a
  ~per-code-50-line adapter.
- POTCAR assembly collapses from three code paths to one pymatgen path; INCAR/KPOINTS/POSCAR
  correctness inherits the Materials Project reference implementation.
- Output parsing becomes structured (`Vasprun`/`Outcar`/ASE parsers) feeding the ADR-009
  `TaskDocument`, killing the untyped result blob at the I/O source.
- OPTIMADE gives federated structure sourcing/export for free and future-proofs data sharing.
- `MSONable` `Structure` serializes into the ADR-010 maggma store with no custom codec.

### Negative / Tradeoffs
- CRYSTAL23 and YAMBO remain partially hand-maintained: ASE covers CRYSTAL14 and lacks CRYSTAL23-only
  keywords; YAMBO (GW/BSE) has no ASE calculator at all. These stay thin code-specific layers
  (ideally contributed upstream), so the "adopt, don't reinvent" rule is *narrowed* to these two
  gaps, not abandoned.
- pymatgen `InputSet` presets encode Materials Project opinions; CrystalMath must subclass to
  override where its conventions differ.
- New, harder dependency surface (pymatgen pulls native libs); this is mitigated by the pixi-based
  dev/HPC environment chosen elsewhere in the redesign.

### Migration impact
- **Delete:** `_vendor/core/codes/`, `vasp/generator.py`, `vasp/incar.py`, `vasp/kpoints.py`,
  `quacc/potcar.py`, and the bespoke `materials_api` wrapper stack — together a large fraction of the
  duplicate-I/O LOC. This also removes a chunk of the load-bearing `_vendor/` fork (advancing the
  `tui/`+`_vendor/` deletion the redesign targets).
- **Keep and re-point:** the `CodeDeckGenerator`/`InputDeck`/`stage()` names and `DeckStagingError`
  fail-fast semantics; `api.py` `vasp.generate_inputs` rewires onto `get_deck_generator("vasp")`.
- **Tests:** add synthetic-POTCAR fixtures (dummy files under a temp `PMG_VASP_PSP_DIR`) so deck
  generation is CI-tested without redistributing VASP-licensed pseudopotentials; round-trip
  `Structure`↔`Atoms` in unit tests; assert each adapter delegates rather than hand-writes.

## References

- Ask Hjorth Larsen et al., "The atomic simulation environment — a Python library for working with
  atoms," *J. Phys.: Condens. Matter* **29**, 273002 (2017). DOI:10.1088/1361-648X/aa680e
- Shyue Ping Ong et al., "Python Materials Genomics (pymatgen): A robust, open-source Python library
  for materials analysis," *Comput. Mater. Sci.* **68**, 314 (2013).
  DOI:10.1016/j.commatsci.2012.10.028
- Alex M. Ganose et al., "Atomate2: modular workflows for materials science," *Digital Discovery*
  (2025). DOI:10.1039/d5dd00019j
- Casper W. Andersen et al., "OPTIMADE, an API for exchanging materials data," *Sci. Data* **8**, 217
  (2021). DOI:10.1038/s41597-021-00974-z (arXiv:2103.02068)
- Sebastiaan P. Huber et al., "AiiDA 1.0, a scalable computational infrastructure for automated
  reproducible workflows and data provenance," *Sci. Data* **7**, 300 (2020).
  DOI:10.1038/s41597-020-00638-4 (arXiv:2003.12476)
- S. K. Steensen et al., "The Interoperability Challenge in DFT Workflows Across Implementations,"
  arXiv:2511.11524 (2025).
- ASE Calculators documentation (CRYSTAL14, Espresso, VASP, `FileIOCalculator`/`SocketIOCalculator`):
  https://ase-lib.org/ase/calculators/calculators.html
- Phonopy native code interfaces (VASP/QE/CRYSTAL/ABINIT/…):
  https://phonopy.github.io/phonopy/interfaces.html
