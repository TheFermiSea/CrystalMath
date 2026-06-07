# Ecosystem Consolidation — Validated Refactor Plan

**Status:** Proposed (validates & sharpens [ADR-007 … ADR-027](REDESIGN.md))
**Date:** 2026-06-07
**Method:** multi-agent investigation (reinvented-wheel codebase inventory + 2026 OSS-landscape
web research + ADR/epic reconciliation) → adversarial fit/risk + completeness verification →
synthesis. Literature grounding saved in NotebookLM (see [§9](#9-research-corpus)).

> **One sentence:** CrystalMath should stop being a half-built Materials-Project clone and become a
> thin, *physics-aware* **conductor** that composes mature OSS behind stable seams — owning only the
> Rust TUI, the CRYSTAL23/YAMBO physics the ecosystem does **not** cover, and one-liner ergonomics.

This plan **confirms 9 of 12** of the ADR-007..027 tool picks against the current landscape; the
revisions are small and evidence-based. The most important finding is that **delegation is partial
exactly where it matters**: for CRYSTAL23 and YAMBO, *no* adopted tool provides *any* layer (deck,
parser, error handler, recipe), so authoring those two verticals — plus a QE error handler — **is
the project**, roughly 4× the work the ADRs imply.

---

## 1. North Star

A thin conductor on the materials/HPC OSS stack: **jobflow** as the one workflow IR;
**atomate2/quacc** recipes where codes overlap; **jobflow-remote** (v1.0.0, daemon-free) for
outbound-SSH HPC; **custodian** for error recovery; a **jobflow JobStore over maggma** (serverless
MontyStore default) for results; **emmet-pattern pydantic TaskDocs** for the data model;
**pymatgen.io + ASE + OPTIMADE** for structure/deck IO; **pydantic-settings** for config; and a
**JSON-RPC-over-stdio (LSP/MCP)** UI/agent boundary with Rust types **code-generated** from the
pydantic schemas so drift is a build failure. The **keystone** is finishing the PyO3→JSON-RPC
cutover *before* expanding the dependency surface, so the typed IPC boundary is the firewall that
lets ~10 fast-moving MP libraries churn without breaking the Rust TUI.

## 2. What CrystalMath genuinely owns (the differentiators)

Everything else is delegated or deleted. CrystalMath builds/keeps only:

1. **The Rust/Ratatui TUI** (`src/`, ~29k LOC) — no materials tool ships a fast multi-code DFT
   terminal UX. Deepen via the `Handler` seam (epic `crystalmath-3y4`).
2. **CRYSTAL23 full vertical** — deck generator (promote `_vendor/.../crystal_d12.py`, 824 LOC),
   `CrystalTaskDoc` parser, custodian `ErrorHandler` (SCF DIVERGENCE/NOT CONVERGED — extract from
   `cli/lib/cry-exec.sh`), jobflow recipe, and the `.f9/.gui/.f98` staging/restart conventions.
3. **YAMBO full vertical** — deck generator (promote `_vendor/core/codes/yambo.py`, 633 LOC),
   `YamboTaskDoc` parser over **yambopy** (netCDF `ndb.QP`/exciton; GPL-isolated `[yambo]` extra),
   custodian `ErrorHandler` (GW/BSE memory), and the QE→p2y→YAMBO handoff recipe.
4. **A QE custodian `ErrorHandler`** — **net-new vs ADR-018: custodian has no QE handlers**, so the
   laptop-first default path gets zero QE recovery unless CrystalMath authors one.
5. **Multi-code recipe knowledge** (CRYSTAL/QE→YAMBO GW/BSE/NLO handoffs) — domain IP; the engine
   underneath becomes a jobflow `Flow`.
6. **Bash one-liner CLI** ergonomics, the **DFT-expert AI prompting**, and the **seams themselves**
   (the DeckGenerator registry + the `domain.verb` JSON-RPC boundary).
7. **Static multi-code DAG validation** (`crystalmath validate`, ADR-024) and the **content-addressed
   cache** contract (ADR-022) for VASP→YAMBO / CRYSTAL `.f9` GUESSP chains — genuinely novel.

## 3. The integrated framework (layer cake)

| Layer | Adopt (default) | Replaces (homegrown) | CrystalMath shim / what we still own |
|---|---|---|---|
| **UI (terminal)** | **ratatui** (keep) | deprecated Textual `tui/` (~85k LOC) | `App` thin coordinator over `Box<dyn Handler>` (epic 3y4) |
| **IPC boundary** | **JSON-RPC 2.0 / stdio** (`src/ipc/client.rs`) | PyO3 `bridge.rs` (~44k) + 2 dispatch registries | one `domain.verb` registry; **keystone**: flip Cargo default, delete PyO3 |
| **Wire codegen** | **typify** (JSON-Schema→Rust serde in `build.rs`) | hand-mirrored `models.rs` vs `models.py` (6+ `JobState`) | pydantic `model_json_schema()` is source of truth; one canonical `JobState` |
| **Config** | **pydantic-settings** (TOML+env+secrets) | `cry-config.sh` + 3 pydantic cfgs + 1793-LOC hardcoded topology | one `config.py`; beefcake2 becomes **user config**; `SecretStr` seam |
| **Workflow IR** | **jobflow** (`Flow`/`Job`/`Response(detour)`) | `BaseAnalysisRunner` + 6 subclasses (~2500), `_vendor` runners | author CRYSTAL/QE→YAMBO recipes as `@job`; engine delegated |
| **Recipes/Makers** | **atomate2 + quacc** (VASP/QE) | `EOSWorkflow`, `bands.py`, phonon/elastic/transport orchestrators | **author CRYSTAL23/YAMBO Makers — atomate2/quacc cover neither** |
| **Deck / calc IO** | **pymatgen.io.sets + ASE**; `HighSymmKpath` | `vasp/generator+incar+kpoints+ENMAX`, `quacc/potcar`, hardcoded k-paths | CRYSTAL/YAMBO decks = promoted `crystal_d12.py`/`yambo.py` |
| **Execution (HPC)** | **jobflow-remote v1.0.0** (daemon-free) | **3** SLURM-over-SSH stacks (~6300 LOC) + quacc Parsl/Covalent | one `ExecutionBackend` protocol; **delete `covalent_runner.py`** |
| **Error recovery** | **custodian** | substring "adaptive" recovery, bash SCF grep, `_vendor/vasp_errors` | **author CRYSTAL23 + YAMBO + QE `ErrorHandler`s** |
| **Result store** | **jobflow JobStore / maggma** (MontyStore default) | Backend ABC (sqlite/aiida/demo), quacc store, 984-LOC bridge | one config-key swap to Mongo+S3; we own only the schemas |
| **Data model** | **emmet-core pattern** (versioned pydantic TaskDoc) | untyped `key_results` blob, flat `AnalysisResults`, 6+ enums | author `Crystal/Yambo/Qe TaskDoc`; one `JobState` lifecycle |
| **Provenance** | ADR-009 fields + ADR-022 content hash over maggma CAS | none coherent | port AiiDA caching contract to the daemon-free path |
| **Materials data** | **mp-api** (`.summary.search`) + **optimade-python-tools** | vendored `materials_api` (~4800) + 2 MP clients + 1279-LOC bridge | trim `pymatgen_bridge` to ~150 LOC; **`OptimadeCandidateSource`** |
| **Parsing** | **pymatgen** `Vasprun/Outcar`, `io.pwscf` | scattered bespoke parsers | YAMBO=yambopy, CRYSTAL=bespoke; **exclude cclib** (molecular-only) |
| **Packaging** | **cargo-dist + hatchling + pixi** | ad-hoc build; missing pins | two artifacts; pin the MP stack to verified-stable lowers; extras-matrix CI |
| **Provenance (opt-in)** / **HPC (opt-in)** | **AiiDA** (`sqlite_dos`, no daemon) | — | opt-in `ExecutionBackend` + provenance; home of `aiida-yambo`/`aiida-crystal-dft` science |

**All-in-one verdict:** *build **on** jobflow, assemble the rest — do not adopt AiiDA/atomate2/pyiron
wholesale.* The decisive fact: no single framework covers CRYSTAL23 **and** YAMBO (atomate2/pyiron
cover neither; only AiiDA reaches both via separately-maintained plugins) — so sitting on a framework
still leaves us authoring the differentiator vertical *and* importing its UI/daemon/store opinions.
**PWD** (python-workflow-definition) is the federation seam to *export to / import from* AiiDA/pyiron
without subordinating to any; **aiida-workgraph** is the watch-item for dynamic/agentic DAGs.

## 4. Delete / adopt (by tier)

| Tier | Action | Homegrown → Adopt | Epic |
|---|---|---|---|
| **0** | replace | PyO3 bridge → JSON-RPC/stdio (`client.rs` ~80% built) | `oho` (P0) |
| **0** | replace | 2 dispatch registries → one `domain.verb` table | `oho` |
| **0** | replace | hand-mirrored `models.rs` → **typify** codegen | `ycz` *(revise: lock typify)* |
| **0** | replace | 3 config systems → pydantic-settings | `08o` |
| **1** | **keep/promote** | `crystal_d12.py`/`yambo.py`/`crystal.py` → first-class `codes/` **before** deleting `_vendor` | **NEW** |
| **1** | replace | `key_results` blob → emmet TaskDocs (`Crystal/Yambo/Qe/Vasp`) | `h67` |
| **1** | delete | `vasp/generator+incar+kpoints`, `quacc/potcar` → pymatgen sets | `7fs` |
| **1** | replace | `bands.py` hardcoded k-path → `HighSymmKpath`/seekpath **(correctness bug)** | `7fs` |
| **1** | replace | adaptive recovery + bash grep → custodian + authored CRYSTAL/YAMBO/QE handlers | `e0u` |
| **2** | replace | Backend ABC + quacc store + 984-LOC bridge → jobflow JobStore/maggma | `bwl` |
| **2** | replace | `BaseAnalysisRunner`+6 subclasses → jobflow Flow + recipes | `svc` |
| **2** | replace | 3 SLURM-over-SSH stacks (~6300) → jobflow-remote | `mls` |
| **2** | delete | `quacc/covalent_runner.py` → (none; Covalent stale) | `mls` |
| **2** | replace | vendored materials_api (~6700 LOC) → mp-api + optimade-python-tools | `7fs` |
| **3** | rule | `pwd_bridge.py` (1009 LOC, no ADR) → re-ground on upstream PWD **or** delete | **NEW** |
| **3** | replace | `results.py` plotters/LaTeX → pymatgen plotters + `pandas.to_latex` | **NEW** |
| **3** | delete | `tui/` Textual TUI (~85k) → Rust TUI | `3y4`/ADR-006 |
| **4** | net-new | CalculatorStage/MLIP, CAS, static DAG validate, MCP, campaign/trust/registry | `6ym`/`eqt`/… |

## 5. Build order (5 tiers)

- **Tier 0 — Keystone.** Finish PyO3→JSON-RPC (`oho`); stand up typify codegen + one `JobState`
  (fix the `_AIIDA_STATE_MAP` silent-default-to-`CREATED` bug); pydantic-settings (`08o`). *The IPC
  boundary is the firewall — make it stable before expanding deps.*
- **Tier 1 — Own the physics + define the contract.** **Promote `crystal_d12.py`/`yambo.py` out of
  `_vendor`** (golden-file + byte-identical guard) *before* any `_vendor` deletion; author the
  TaskDocs (`h67`); author CRYSTAL/YAMBO/QE custodian handlers (`e0u`); low-risk delete-and-delegate
  physics (`7fs`, incl. the k-path correctness fix).
- **Tier 2 — Collapse the shell.** jobflow IR (`svc`), maggma store (`bwl`), jobflow-remote (`mls`),
  mp-api/OPTIMADE data access (`7fs`); delegate phonon/elastic/transport to atomate2.
- **Tier 3 — Cleanup + governance + packaging.** Delete `tui/`; rule on PWD; write the missing ADRs
  (PWD, metrics, parser, credential seam); two-artifact packaging (`g7k`).
- **Tier 4 — SOTA backlog.** MLIP `CalculatorStage`, CAS, `crystalmath validate`, agentic MCP,
  campaign/trust/registry — refresh the dated MLIP roster (ORB v3 / GRACE / SevenNet / eSEN /
  MatterSim) and the CPS metric.

## 6. Reconciliation with ADR-007..027

**Confirms (validated against 2026):** ADR-008/009/010/011/012/014/015/017/018(framework)/020/022/023/024/025/027.

**Revises (evidence-based):**
1. **ADR-018 factual error** — custodian has **no Quantum ESPRESSO** handlers (vasp/cp2k/qchem/
   nwchem/feff/lobster only). Authored-handler load is **3 codes (CRYSTAL+YAMBO+QE)**, not 2.
2. **ADR-016 / epic `ycz`** — `ycz` re-opens the codegen tool ("typeshare/schemars/datamodel-codegen
   — decide") but ADR-016 already chose **typify**. *Lock typify* (schemars is the wrong direction;
   datamodel-code-generator is Python-only).
3. **ADR-012** — jobflow-remote is now **v1.0.0 stable** (daemon-free); the "beta/API-evolving"
   tradeoff is stale.
4. **ADR-021/026** — MLIP evidence is dated (MACE-MP-0/CHGNet, Matbench F1); refresh to the 2026
   roster + **CPS** multi-property metric; make single-model+conformal the cheap default (ensemble
   opt-in). *The trust architecture itself is ahead of the field.*
5. **Verify empirically:** the AiiDA CRYSTAL plugin status is contradicted across sources
   (`aiida-crystal17` stale/2020 vs `aiida-crystal-dft` v0.9.4/Mar-2026) — it changes whether the
   opt-in AiiDA backend gets CRYSTAL23 "for free". The fresh-authoring decision for the **default**
   (daemon-free) path stands regardless.

## 7. Net-new (beyond the ADRs)

- **Credential/secret seam** — no ADR owns SSH keys / Mongo URIs / S3 / HF tokens across
  jobflow-remote + JobStore + MCP. Decide: `SecretStr` + `file_secret_settings`; secrets **never** on
  the IPC wire (references only).
- **OPTIMADE → acquisition wiring** — add `OptimadeCandidateSource` as a peer of the generative
  source (ADR-025/023); the common "query MP/COD/OQMD → MLIP-screen → DFT-validate" loop is unwired.
- **PWD governance** — rule on the 1009-LOC `pwd_bridge.py` (re-ground on upstream PWD **or** delete).
- **Metrics-contract ADR** — `monitor.rs`/`prometheus.rs` exporters resolved via config; one job-state source.
- **Parser-strategy ADR** — name **yambopy** (GPL-isolated `[yambo]` extra); **exclude cclib**.
- **`pyiron` rejection** + **`aiida-workgraph` watch-item** on record; **in-allocation fan-out** =
  jobflow-remote batch mode first, Parsl/Dask only if insufficient.
- **Budget CRYSTAL23/YAMBO/QE physics as the core deliverable** — first-class epics distinct from the
  runner-deletion epic.

## 8. Top risks

1. **Differentiator regression on `_vendor` delete** (blocker if mis-sequenced) — promote
   `crystal_d12.py`/`yambo.py` with a byte-identical guard **before** deleting.
2. **QE recovery silently missing** — author a `QeErrorHandler` or explicitly relegate QE recovery to
   the opt-in AiiDA/quacc-ASE path.
3. **Version-coupling across ~10 fast-moving MP libs** — finish the IPC cutover first (firewall); pin
   verified-stable lowers; CI upgrade + golden-file job; typify codegen.
4. **YAMBO coverage vs daemon-free** — author YAMBO fresh on the default path; `aiida-yambo` as the
   validation oracle + opt-in backend; don't let it pressure the default toward AiiDA.
5. **Lossy/scattered state model** — one canonical lifecycle via typify; fix the `_AIIDA_STATE_MAP`
   silent default; confine foreign-state mapping to each backend edge.
6. **yambopy GPL reach** — isolate as an optional extra (or subprocess) so GPL never links the
   permissive core.

## 9. Research corpus

Saved + queryable in NotebookLM: **"CrystalMath — Ecosystem Consolidation Research (ADR-007..027)"**
(`c35e0397-f840-4d2f-8f02-30ec23037259`). Canonical grounding:

- **Code-agnostic workflow interfaces** — Huber *et al.*, "Common workflows…", *npj Comput. Mater.* 7, 136 (2021), [arXiv:2105.05063](https://arxiv.org/abs/2105.05063) — *the* thesis paper.
- **atomate2** — Ganose *et al.*, *Digital Discovery* (2025), [doi:10.1039/d5dd00019j](https://doi.org/10.1039/d5dd00019j).
- **AiiDA** — Pizzi *et al.* (2015), [arXiv:1504.01163](https://arxiv.org/abs/1504.01163); **AiiDA 1.0** — Huber *et al.*, *Sci. Data* (2020), [arXiv:2003.12476](https://arxiv.org/abs/2003.12476).
- **pymatgen** — Ong *et al.*, *Comput. Mater. Sci.* (2013), doi:10.1016/j.commatsci.2012.10.028.
- **ASE** — Larsen *et al.*, *J. Phys. Condens. Matter* (2017), doi:10.1088/1361-648X/aa680e.
- **FireWorks** (jobflow lineage) — Jain *et al.*, *Concurr. Comput.* (2015), doi:10.1002/cpe.3505.
- **MLIP layer** — MACE-MP-0 (Batatia 2023, [arXiv:2401.00096](https://arxiv.org/abs/2401.00096)),
  CHGNet (Deng 2023, [arXiv:2302.14231](https://arxiv.org/abs/2302.14231)), Matbench-Discovery
  (Riebesell 2023, [arXiv:2308.14920](https://arxiv.org/abs/2308.14920)).
- Plus the OSS docs for jobflow / atomate2 / quacc / maggma / custodian / jobflow-remote / emmet /
  pymatgen / ASE / pydantic-settings.
