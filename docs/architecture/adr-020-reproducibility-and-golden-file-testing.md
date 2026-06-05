# ADR-020: Reproducibility Spine — Golden-File + Property Tests and Real-DFT Parser Fixtures

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) (structure + deck I/O on pymatgen/ASE), [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (canonical versioned `TaskDocument` schema), [ADR-017](adr-017-packaging-testing-two-artifacts-pixi.md) (packaging & testing — two artifacts, pixi, extras-matrix CI)
**Extends:** [ADR-017](adr-017-packaging-testing-two-artifacts-pixi.md) §testing — this ADR is the deeper reproducibility/golden-file/property-testing spine that ADR-017's testing section references; it does **not** supersede or contradict ADR-017's packaging decisions.

## Context

The bold-redesign mandate (zero users, no backward-compatibility constraint) collapses
CrystalMath's homegrown machinery onto mature ecosystem tools and reframes the project as a thin
conductor over the Materials-Project stack ([ADR-007](adr-007-redesign-overview-adopt-ecosystem.md)).
That redesign is only credible if **reproducibility is structural rather than aspirational**: a
redesign that deletes four orchestration paths, replaces the deck/persistence/IPC seams, and routes
all per-code I/O through the ASE/pymatgen seam of
[ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) must be defended by tests that prove the
rewrite did not change physics.

[ADR-017](adr-017-packaging-testing-two-artifacts-pixi.md) already decides the *packaging* model
(two decoupled artifacts — a hatchling wheel and a `cargo-dist` native binary — once PyO3 is gone
per [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md), a versioned IPC handshake guarding
skew, **pixi** for the bit-reproducible conda-forge/HPC stack, and an extras-matrix CI). It also
sketches the testing posture (synthetic/real fixtures, no live DFT in CI). **This ADR deepens that
testing section into a concrete reproducibility spine** — the golden-file, property/metamorphic, and
real-output-fixture strategy — without re-deciding any packaging choice ADR-017 owns. Where ADR-017
says *what artifacts ship and how the environment is pinned*, this ADR says *how the redesigned
system is verified so the bytes it produces are trustworthy*.

Today the testing posture does not support that:

- **Decks are asserted by substring, not by file.** The `decks/` seam (ADR-008) produces
  deterministic text artifacts (the `InputDeck.files` dict — `.d12`, `INCAR`/`POSCAR`/`KPOINTS`,
  `pw.in`, YAMBO input), yet tests spot-check fragments. A full-file regression baseline would
  catch exactly the drift the redesign risks — e.g. POTCAR de-duplication changing
  `potcar_symbols` ordering, or a SHRINK/TOLDEE default shifting — that a substring assert sails
  past.
- **There are no physics invariants under test.** Nothing asserts that generation is
  deterministic, that a structure survives a round-trip, or that a symmetry operation on the input
  produces the expected relation on the output. These are precisely the properties that a "thin
  conductor" must guarantee when it stops owning the physics and starts orchestrating it.
- **Parsers are tested against hand-written stubs, not truth.** The output parsers in
  `_vendor/core/codes/` (CRYSTAL/VASP/QE/YAMBO `OutputParser` + `ParsingResult`) grep real
  multi-megabyte DFT logs for energies and convergence, but the test corpus does not contain real
  canned DFT outputs. A parser that drifts against the real format passes CI. These parsers are the
  source of the `TaskDocument` fields of
  [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md), so a parser drift is a silent
  schema-population bug.
- **`pytest-cov` is declared but unused.** Coverage is collectible but there is no measurement and
  no floor, so the large refactors this redesign demands can silently delete tested behavior.

This ADR specifies the verification spine: the golden-file deck regression, the property/metamorphic
invariants, the real-output parser fixtures, and the coverage ratchet — slotting *beneath* the
packaging/CI matrix that ADR-017 stands up.

## Decision

### 1. Golden-file deck regression with `pytest-regressions`

> **Scope (sharpened by the 2026-06-03 amendment):** byte-exact golden-file testing applies **only
> to deterministic deck/input generation** — a pure function of inputs. It is **never** applied to
> DFT/MLIP *outputs*, which are not bitwise reproducible across heterogeneous HPC (see Amendment).

Decks are deterministic, so test them by **full-file diff against a checked-in baseline**, not by
substring assertion. Adopt `pytest-regressions` and assert every file in
`InputDeck.files` plus the `potcar_symbols` list and `metadata` against a stored golden artifact,
per `(code, workflow_type, structure)` fixture.

- The baseline lives next to the deck tests as committed text (one file per generated artifact),
  so a diff in review *is* the semantic change — a reviewer sees the `.d12` or `INCAR` change
  line-by-line.
- Numeric fields embedded in decks (lattice vectors, fractional coordinates) are compared with
  float tolerances via `num_regression`/`dataframe_regression`; structural text is compared
  exactly.
- Regenerating baselines is an explicit, reviewable act (`--force-regen`), never silent.
- This is the regression net for the `decks/` consolidation of ADR-008: routing legacy
  `generate_d12` / `generate_vasp_inputs` and the SLURM runner through `get_deck_generator` (the
  redesign's canonical-deck-layer move) is safe only if the bytes produced are pinned.

### 2. Hypothesis property + metamorphic tests for physics invariants

Back the golden files with property-based tests (`hypothesis`) over generated `Structure`/
parameter inputs, asserting invariants that hold *by construction* and therefore sidestep the
oracle problem (there is no reference "correct deck" to compare against in general):

- **Determinism:** generating the same deck twice yields byte-identical `files` (no dict-ordering,
  timestamp, or set-iteration nondeterminism).
- **Round-trip:** a `Structure` written into a deck and parsed back out of that deck's geometry
  block recovers the same lattice and sites within tolerance.
- **Metamorphic / symmetry relations:** applying a symmetry-preserving transformation to the input
  (e.g. a supercell, a lattice-vector permutation, a rigid translation under PBC) produces the
  documented relation on the output (same space group / same reduced formula / energy-invariant
  fields unchanged). This is the metamorphic-testing answer to the oracle problem for scientific
  software (Segura 2016; Stevens 2025 for quantum-chemistry relations specifically).

Tolerances and shrinking strategies are tuned per relation; these tests are slower than the
golden-file suite and are allowed a separate, longer Hypothesis profile in CI.

### 3. Real canned DFT outputs as parser fixtures; NO DFT in CI

Parsers are tested against **real DFT output files**, committed as fixtures, not against
hand-written stubs:

- For each supported code (CRYSTAL23, VASP, QE, YAMBO) commit a small set of real, truncated-but-
  representative output files (success, SCF-non-convergence, OOM/timeout signatures) under a
  fixtures tree, and assert the `_vendor/core/codes/` `OutputParser` → `ParsingResult` against the
  known-true values extracted from them. This mirrors atomate2's real-output fixture corpus
  (Ganose 2025), and these same canned failure outputs double as the golden-file `check()` inputs
  for the custodian-style error handlers of
  [ADR-018](adr-018-error-recovery-custodian-handlers.md).
- **CI runs zero DFT.** No quantum-chemistry binary is invoked in the GitHub Actions matrix;
  parser correctness comes entirely from the canned fixtures, and runner behavior is exercised with
  a **fake runner** that replays a fixture as if it were a completed job (the redesign already
  requires an explicit fake-runner path now that silent simulated success is forbidden —
  `allow_stub_execution`, commit crystalmath-b0d). This is consistent with ADR-017's "no live DFT
  in CI" testing posture; this ADR specifies the fixtures that make it true.
- A **single live smoke test**, gated behind an opt-in marker / environment flag and **excluded
  from the default CI matrix**, runs one tiny real CRYSTAL23 SCF (the `TESTBED/mgo_test1` MgO deck)
  end-to-end on a self-hosted/macOS-arm64 runner to catch binary/toolchain rot that fixtures
  cannot. It is informational, not a required check, and rides the pixi-pinned compiled prefix that
  ADR-017 stands up. **The 2026-06-03 amendment moves this opt-in live-DFT layer onto ReFrame** (the
  scheduler-agnostic HPC regression framework) so the same test can sweep MPI-rank / thread counts
  and assert *per-property scientific tolerances* rather than ad-hoc pytest plumbing — see the
  Amendment for the seam between pytest (§1–§2, deterministic) and ReFrame (live numerics).

### 4. Ratchet coverage on the matrix ADR-017 defines

[ADR-017](adr-017-packaging-testing-two-artifacts-pixi.md) owns the OS × Python / extras CI matrix
(including the macOS-arm64 row that exercises the documented primary target and the pixi compiled
prefix). This ADR adds the coverage discipline that runs *on* that matrix:

- **Coverage ratchet:** wire the already-declared `pytest-cov` into the pytest invocation, publish
  the number, and enforce a floor that **only moves up** (`--cov-fail-under`, raised as the suite
  grows). This turns the unused dependency into a guard against the redesign silently shedding
  tested behavior.
- The golden-file suite (§1), the property/metamorphic suite (§2), and the parser-fixture suite
  (§3) all run inside that matrix; the arm64 row is where the deck bytes and parser truth are
  verified on the platform the CRYSTAL23 binaries actually target.

### 5. Reproducibility is content-pinned, not hoped

> **Corrected by the 2026-06-03 amendment.** The original framing below conflated two distinct
> reproducibility regimes by calling the *entire* deck→run→parse path "content-addressable" as one
> byte-exact test property. That holds only for the **deterministic ends** — deck generation and the
> parse function — and **not** for the run in the middle, whose DFT/MLIP numerics are not bitwise
> reproducible across compilers/MPI/BLAS/GPU/FMA. The amendment splits these into (a) byte-exact
> golden tests on the deterministic ends and (b) **per-property scientific tolerances** plus an
> **environment fingerprint** on the run. Read the two paragraphs below through that lens.

Determinism (§2) plus golden files (§1) make the **deterministic ends** of the pipeline —
deck generation (a pure function of inputs) and the parser (a pure function of an output file) —
**content-addressable**: the same structure and parameters always yield the same deck bytes, and the
same output file always yields the same `TaskDocument` (ADR-009) fields. This is byte-exact and CI-
enforced.

The **run itself is not** byte-reproducible across heterogeneous HPC, so the deck→run→parse path as
a whole is reproducible only under **per-property scientific tolerances** (total energy, forces,
stresses, band gaps) gated on a matching **environment fingerprint** (ADR-009/022) — see the
Amendment. This is the test-side complement to ADR-009's first-class provenance fields (input hash,
code+version, content-addressed raw-file paths) and to the content-addressed execution identity that
[ADR-022](adr-022-content-addressed-execution-cache-replay.md) makes the default execution gate:
provenance *records* what ran; this spine *proves* that what ran is reproducible within the regime
appropriate to it. FAIR reproducibility (Wilkinson 2016) becomes a CI-enforced property, not a
README aspiration.

## Consequences

### Positive

- **The redesign becomes defensible.** Consolidating onto the `decks/` seam (ADR-008) and the
  `TaskDocument` schema (ADR-009) is guarded by byte-exact golden files plus invariant property
  tests, so "did this change the physics?" is answered by CI, not by hope.
- **Parsers are tested against reality**, and CI stays fast and dependency-light because no DFT
  binary runs in the matrix — the long-standing parser/truth gap closes without a toolchain in CI.
- **The error handlers get a fixture corpus for free.** The canned failure outputs of §3 are
  exactly the `check()` inputs ADR-018's CRYSTAL23/YAMBO handlers need.
- **Coverage stops being decorative** — the ratchet makes regression a visible, blocking event on
  the ADR-017 matrix.
- **Reproducibility is structural** — deterministic, content-pinned inputs and schema-pinned
  outputs realize the FAIR/provenance intent of ADR-009 as enforced tests.

### Negative / Tradeoffs

- **Golden files must be regenerated deliberately** whenever a deck *should* change; a sloppy
  `--force-regen` can rubber-stamp a real regression. Review discipline (the diff is the change)
  is the guard.
- **Property/metamorphic tests are slower and flakier to author** — tolerances and shrinking need
  tuning, and a too-loose relation tests nothing while a too-tight one fails on legitimate
  numerical noise.
- **Real DFT fixtures are bulky and code/version-specific**; they must be truncated and curated,
  and refreshed when a supported code's output format changes.
- **The coverage floor adds friction** to large deletions until tests catch up; this is intended —
  it is the point of the ratchet.
- **Per-property scientific tolerances are physics judgments, not constants** (Amendment): each
  curated tolerance (energy, forces, stresses, gaps) must be tight enough to catch a real regression
  yet loose enough to survive legitimate hardware/MPI/BLAS noise — real per-code domain work, and a
  second test framework (ReFrame) alongside pytest. The payoff is that the determinism critique is
  answered honestly rather than by a byte-equality assertion that cannot hold on real HPC.

## Alternatives Considered

- **Substring/spot-check deck assertions (status quo).** Rejected: decks are deterministic, so a
  full-file baseline is strictly more powerful and catches POTCAR-dedup/default-drift that
  fragment matching misses. The only cost (regeneration discipline) is acceptable.
- **Example-based unit tests only, no property/metamorphic layer.** Rejected: examples cannot
  cover the input space and cannot express symmetry/round-trip/determinism invariants, which are
  exactly the guarantees a thin conductor must make; metamorphic testing is the standard answer to
  the scientific-software oracle problem (Segura 2016).
- **Run real DFT in CI for end-to-end coverage.** Rejected (and consistent with ADR-017): DFT
  binaries are large, slow, license-encumbered (VASP), and platform-specific; canned real-output
  fixtures plus a fake runner give parser truth without a CI toolchain, and one opt-in live smoke
  test covers binary rot.
- **Mock/synthetic parser inputs.** Rejected: synthetic logs encode the parser author's
  assumptions, not the codes' real output, so they pass even when the parser has drifted from
  reality (the atomate2 lesson — Ganose 2025).
- **Fold this into ADR-017 rather than a standalone ADR.** Rejected: ADR-017 is the packaging +
  CI-matrix decision; the golden-file/property/metamorphic/parser-fixture spine is a distinct,
  deeper verification contract that ADR-018 (handler fixtures) and ADR-009 (schema truth) both
  depend on. Keeping it standalone lets those ADRs cite it directly while ADR-017 references it as
  the testing spine beneath its matrix.

## Amendment (2026-06-03): SOTA alignment — four reproducibility regimes, not one

The original Decision (§1, §5) called the whole `deck → run → parse` path "content-addressable" and
golden-file-tested as a single byte-exact property. A SOTA review flagged that this **conflates
bitwise reproducibility with scientific reproducibility** and does not confront the
nondeterminism of real HPC execution (compiler, MPI, BLAS/LAPACK, GPU/CUDA, FMA/reduction order,
thread/rank counts). This amendment splits the one claim into **four distinct regimes**, each with
its own test instrument, and connects the spine to the content-addressed execution contract of
[ADR-022](adr-022-content-addressed-execution-cache-replay.md).

1. **Byte-exact (deterministic ends).** Deck/input generation and the output parser are pure
   functions of their inputs and *are* bitwise reproducible. These keep the §1 golden-file
   (`pytest-regressions`) and §3 canned-output-fixture treatment. This is the only regime where
   `==`-on-bytes is a correct oracle.
2. **Schema-exact (typed structure).** Every `TaskDocument` (ADR-009) must validate against its
   pydantic schema and round-trip MSONable↔store losslessly. Tested by schema/round-trip property
   tests (§2), independent of the numerical values inside.
3. **Numerical (within-environment).** Given a **matching environment fingerprint** (ADR-009's new
   `environment_fingerprint`: executable hash, pseudopotential/POTCAR hash, MPI/BLAS/LAPACK +
   torch/CUDA versions, compiler+flags, thread/rank counts), a re-run reproduces scalar outputs to
   a **tight, regime-appropriate tolerance**. This is the regime ADR-022's cache-and-clone relies
   on: a content-hash hit asserts *the inputs and environment are identical*, so reuse is sound.
4. **Scientific (cross-environment).** Across *different* environments the same physics must agree
   only to **per-property scientific tolerances** (total energy, forces, stresses, band gaps — each
   a documented physics judgment, not a global constant). This is asserted by the opt-in live layer,
   now carried on **ReFrame** (the scheduler-agnostic HPC regression framework), which can sweep
   MPI-rank/thread counts and assert per-property tolerances that ad-hoc `pytest` plumbing cannot.

**Consequences of the split.** (a) Golden files are scoped to regimes 1–2 and never assert on raw
DFT/MLIP numerics. (b) The `environment_fingerprint` becomes a required field on every run document
(ADR-009 revision) and a component of the ADR-022 content hash — so "reproducible" is always
qualified by the fingerprint it was measured under. (c) The §3 live smoke test is promoted from an
informational `pytest` job to a ReFrame regression that is still off the default required matrix but
gives real cross-environment numbers. (d) MLIP/foundation-calculator stages (ADR-021) enter the
same four-regime discipline: their *deck-equivalent* inputs are byte-tested, their model checkpoint
is content-addressed (ADR-022), and their predicted energies/forces get per-property tolerances like
any other calculator.

This amendment changes no positive claim of the original ADR; it makes each claim **true in the
regime it actually holds**, and stops the spine from promising bitwise reproducibility of a quantity
(a parallel DFT run) that no honest HPC system delivers.

## References

### Papers

- D. R. MacIver, Z. Hatfield-Dodds et al., **"Hypothesis: A new approach to property-based
  testing"**, *Journal of Open Source Software* 4(43):1891 (2019); and Z. Hatfield-Dodds,
  **"Falsify your Software: validating scientific code with property-based testing"**, *Proc.
  SciPy* 2020 — basis for §2 (property-based testing for scientific Python).
- S. Segura, G. Fraser, A. B. Sánchez, A. Ruiz-Cortés, **"A Survey on Metamorphic Testing"**,
  *IEEE Transactions on Software Engineering* 42(9):805–824 (2016) — the metamorphic-testing answer
  to the oracle problem, basis for §2's metamorphic relations.
- R. Stevens et al., **"Metamorphic Relations for Scientific Software"** (quantum-chemistry
  metamorphic relations), ICSE NIER 2025 — domain-specific metamorphic relations for §2.
- A. M. Ganose, J. Sahasrabuddhe, … A. S. Rosen, A. Jain et al., **"Atomate2: modular workflows
  for materials science"**, *Digital Discovery* (2025) — model for real-DFT-output parser fixtures
  (§3).
- M. Uhrin, S. P. Huber, J. Yu, N. Marzari, G. Pizzi, S. Zoupanos, et al., **"AiiDA 1.0, a scalable computational infrastructure for automated reproducible workflows
  and data provenance"**, *Scientific Data* 7:300 (2020) — reproducibility-via-provenance context
  for why deterministic, content-pinned inputs matter (§1, §5).
- M. D. Wilkinson, M. Dumontier, IJ. Aalbersberg et al., **"The FAIR Guiding Principles for
  scientific data management and stewardship"**, *Scientific Data* 3:160018 (2016) — the normative
  why behind reproducible, pinned, content-addressed inputs (§5).

### Tools

- **pytest-regressions** — golden-file/regression-fixture plugin (`data_regression`,
  `num_regression`, `file_regression`, `--force-regen`); basis for §1.
- **Hypothesis** — property-based testing library for Python (`hypothesis.readthedocs.io`); §2.
- **pytest-cov** / `coverage.py` — coverage measurement and `--cov-fail-under` ratchet; §4.
- **pixi** (prefix.dev) — the bit-reproducible conda-forge/HPC environment that ADR-017 stands up
  and on which §3's live smoke test runs.
- **ReFrame** (`github.com/reframe-hpc/reframe`) — scheduler-agnostic HPC regression-testing
  framework; carries the amendment's cross-environment scientific-tolerance smoke layer (regime 4).

### In-repo

- `python/crystalmath/decks/__init__.py` — `InputDeck`, `CodeDeckGenerator`, `get_deck_generator`,
  `stage()`: the deterministic deck artifacts golden-file-tested in §1 (per ADR-008).
- `python/crystalmath/_vendor/core/codes/` — the `OutputParser`/`ParsingResult` parsers tested
  against real canned outputs in §3, whose values populate the ADR-009 `TaskDocument`.
- `TESTBED/mgo_test1` — the tiny real CRYSTAL23 MgO deck used by §3's opt-in live smoke test.
- [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md),
  [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md),
  [ADR-017](adr-017-packaging-testing-two-artifacts-pixi.md),
  [ADR-018](adr-018-error-recovery-custodian-handlers.md) — the deck seam, the schema, the
  packaging/CI matrix this spine sits beneath, and the error handlers whose fixtures it provides.
