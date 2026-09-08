---
adr_id: 034
title: "Ecosystem Library Verification: CRYSTALpytools, jobflow-remote, yambopy, and the AiiDA plugin ecosystem (2026-09-07)"
status: "Proposed"
date: "2026-09-07"
macro_context: "crystalmath-tui-core"
---

# ADR-034: Ecosystem Library Verification — CRYSTALpytools, jobflow-remote, yambopy, and AiiDA

**Status:** Proposed
**Date:** 2026-09-07
**Deciders:** Project maintainers
**Supersedes:** none
**Amends:** [ADR-012](adr-012-workflow-engine-jobflow-flows-atomate2quacc-recipes-as-the-one-orchestration-model.md), [ADR-013](adr-013-hpc-execution-layer-jobflow-remote-outbound-ssh-polling-daemon-as-default-aiida-opt-in-delete-the-bespoke-slurmssh-stack.md), [ADR-031](adr-031-ecosystem-consolidation-validated-refactor-plan.md)
**Context:** Project currently has zero active users — full freedom to choose direction. This ADR
is a targeted verification pass (live web + GitHub-API research, current as of 2026-09-07) on
libraries ADR-031 named as "evaluate further," done at the maintainer's explicit request before
committing engineering time to the CRYSTAL23/YAMBO verticals. It surfaces one finding — the AiiDA
plugin ecosystem — that is materially more relevant than ADR-012/013's "opt-in, secondary" framing
suggested, and recommends a bake-off before treating jobflow/jobflow-remote as settled defaults.

**Methodology note:** every activity claim below is from GitHub's REST API (`pushed_at` = last real
code push; more reliable than a repo's `updated_at`, which also changes on stars/issue comments/wiki
edits with no code activity) or a primary docs/PyPI source, fetched today. Where a claim could not
be directly verified, it's marked as such rather than asserted.

## 1. CRYSTALpytools undersold for CRYSTAL parsing *and* deck generation

ADR-031 §3 states *"YAMBO=yambopy, CRYSTAL=bespoke"* — no adopted tool covers CRYSTAL23 parsing,
so plan on hand-authoring a `CrystalTaskDoc` parser plus promoting the vendored 824-LOC
`_vendor/.../crystal_d12.py` deck generator.

**This is incomplete.** This project's own pre-redesign AiiDA integration plan
(`docs/architecture/aiida-integration.md` + `integration.md`/`overview.md`/`runners.md`/
`tui-ssh-runner.md`, all marked historical/superseded) already specified and wrote working example
code against CRYSTALpytools for exactly this purpose. `grep -i crystalpytools` across `adr-*.md`
returns zero hits in ADR-031 — nothing there indicates a deliberate rejection, so this looks like a
re-discovery gap in the "2026 OSS-landscape web research" pass, not a considered decision.

### Verified

- **Repo:** [`crystal-code-tools/CRYSTALpytools`](https://github.com/crystal-code-tools/CRYSTALpytools)
  — **MIT license** (no GPL-isolation burden, unlike yambopy). `pushed_at: 2025-05-03`, 3 open
  issues, 25 stars. Maintained by the CRYSTAL developer community (Turin); published alongside a
  peer-reviewed paper ([Computer Physics
  Communications](https://www.sciencedirect.com/science/article/pii/S0010465523001984)).
  **16 months since the last code push — not abandoned, but confirm there's been movement since
  before relying on it as a dependency.**
- **Output parsing:** `crystal_io.Crystal_output` reads standard `crystal`/`properties` output
  files — confirms the historical usage snippet still matches the current API.
  ([API docs](https://crystal-code-tools.github.io/CRYSTALpytools/crystalpytools.crystal_io.html))
- **Input generation (net-new vs. ADR-031, which doesn't credit this at all):**
  `crystal_io.Crystal_input` is a full programmatic `.d12` builder:

  ```python
  from CRYSTALpytools.crystal_io import Crystal_input

  mgo_input = Crystal_input()
  mgo_input.geom.title('MGO BULK - GEOMETRY TEST')
  mgo_input.geom.crystal(225, [4.217], [[12, 0., 0., 0.], [8, 0.5, 0.5, 0.5]])
  mgo_input.basisset.basisset('POB-DZVP')
  mgo_input.scf.dft.xcfunc('B3LYP')
  mgo_input.scf.shrink(12, 24)
  # .data -> rendered .d12 text; .write_file() to save
  ```
  Also imports geometry from CIF or **pymatgen Structure** objects directly — lines up with
  ADR-009's pymatgen/ASE standardization.
  ([Docs](https://crystal-code-tools.github.io/CRYSTALpytools/examples/input_and_basisset/input_and_basisset.html))

### Recommendation

Revise ADR-031 §3's parsing row to **`CRYSTAL=CRYSTALpytools (primary)`**, and credit it against
the deck-generator work item too, not just parsing — this directly shrinks the "~4× the work"
estimate ADR-031 gives for the CRYSTAL vertical. Before committing:
- Confirm `Crystal_input`'s `BASISSET` shortcut resolves against a bundled or fetchable basis
  library — CRYSTAL23's own native `BASISSET` keyword needs a `BASISSETS.DAT` file that is **not**
  bundled with the vendored object-file distribution this project builds against (found firsthand
  tonight while building CRYSTAL23 on `ultrafastlab-1` — see the install script work). Verify
  CRYSTALpytools doesn't inherit the same gap.
- Confirm ECP/pseudopotential handling for heavy elements (needed for e.g. the W-ECP `STUTSC`
  shells in the WS2 SOC/DFT benchmark used tonight), not just light-element all-electron basis
  sets.
- Check for CRYSTALpytools activity since 2025-05-03 before finalizing.

## 2. AiiDA plugin ecosystem: more relevant than ADR-012/013's "opt-in" framing suggests

ADR-012/013 treat AiiDA as a heavyweight, secondary, opt-in `ExecutionBackend` alongside
jobflow-remote as the default. That framing deserves a second look: **ADR-013 itself already names
`aiida-crystal-dft` and `aiida-yambo` as the *only* maintained ecosystem tools covering any layer of
CRYSTAL/YAMBO support at all** — the jobflow/atomate2/quacc side has *nothing* for either code. If
CRYSTAL and YAMBO are genuinely this project's flagship differentiators (ADR-031 §2 says exactly
this), the ecosystem built around them, not the ecosystem built around VASP, is the one worth taking
most seriously as a default — not just an opt-in escape hatch.

### What's actually there, verified today

| Plugin | Org | Official? | Last code push | Open issues | License | Notes |
|---|---|---|---|---|---|---|
| [`aiida-quantumespresso`](https://github.com/aiidateam/aiida-quantumespresso) | `aiidateam` (AiiDA core team) | **Yes** | active | — | — | Production-ready relax/bands/phonon workflows; QE is AiiDA's "home" code |
| [`aiida-vasp`](https://github.com/DropD/aiida-vasp) | personal account (`DropD`), not `aiidateam` | **No** | — | — | — | Community-maintained, not core-team-official — weaker than jobflow/atomate2's native VASP support |
| [`aiida-crystal-dft`](https://github.com/tilde-lab/aiida-crystal-dft) | `tilde-lab` (Turin-affiliated, MPDS) | No (community) | **2026-07-15** (recent) | 19, not archived | not yet checked | Spin-off of `aiida-crystal17`. Description: "mainly intended for use with cloud infrastructures, currently MPDS" — **verify this doesn't bake in deployment assumptions that conflict with a plain SLURM/SSH cluster.** CRYSTAL23-specific keyword coverage still not directly confirmed (matches ADR-013's own "unconfirmed" flag) |
| [`aiida-yambo`](https://github.com/yambo-code/aiida-yambo) | `yambo-code` (the YAMBO code team itself) | Yes, for YAMBO | **2024-02-28 — 2.5 years stale** | 17, 8 stars | `Other`/`NOASSERTION` (verify actual terms) | Feature-complete per docs — G0W0/COHSEX/HF quasiparticle + IP-RPA/BSE optical workflows, i.e. exactly ADR-031's GW/BSE target. **Correction: an AiiDA blog post from 2025-05-15 calls this a "success story," which reads as active — the code itself hasn't been pushed to since Feb 2024.** Endorsed and feature-rich, but verify it still runs against current YAMBO/AiiDA versions before depending on it. |

**AiiDA core itself:** actively maintained (stable releases in the 2.7.x/2.8.x line), but
architecturally heavier than jobflow-remote alone — a full provenance-graph database requires
**PostgreSQL + RabbitMQ + a persistent `verdi daemon`**, not swappable to a lighter store the way
jobflow's `MontyStore` is. This is a real, ongoing operational cost, not a one-time setup detail.

### The actual strategic tension this creates

The two ecosystems' strengths map almost exactly onto opposite halves of what CrystalMath cares
about:

- **jobflow/atomate2/quacc**: strong for VASP/CP2K (their home turf), nothing for CRYSTAL or YAMBO.
- **AiiDA**: official-grade for Quantum ESPRESSO, actively-maintained community support for CRYSTAL,
  feature-rich (if stale) support for YAMBO — but only community-grade for VASP, and a heavier
  operational footprint than jobflow-remote.

Running both stacks side-by-side to get "the best tool per code" would reintroduce exactly the
N-way-facade duplication ADR-008 set out to eliminate — two workflow engines, two provenance models,
two execution backends to maintain. That's a real cost, not a free lunch, even though each
individual pick would be locally optimal.

### Recommendation

Don't settle ADR-012/013's default via literature review alone — **run a short, time-boxed
bake-off** before committing: build the same small real calculation (e.g. reuse tonight's MgO/WS2
benchmark inputs) two ways — (a) AiiDA + `aiida-crystal-dft`, (b) jobflow + a hand-written
CRYSTALpytools-based `Maker` — and compare actual friction, not just feature lists. Given
`aiida-yambo`'s multi-year commit gap, budget time to potentially patch it rather than assuming
drop-in readiness. If CRYSTAL/YAMBO really are the differentiators, weight the bake-off's CRYSTAL/
YAMBO experience more heavily than its VASP/QE experience — this project doesn't need to compete on
VASP support.

## 3. Correction: verify jobflow-remote's actual daemon requirement for the SSH/SLURM use case

ADR-013's 2026-06-07 amendment states jobflow-remote reached "v1.0.0 (stable, **daemon-free
workstation mode**)." The current official quickstart docs
([Matgenix/jobflow-remote](https://matgenix.github.io/jobflow-remote/user/quickstart.html))
describe the opposite for the remote-execution path CrystalMath actually needs: the `Runner`
(file transfer, queue-manager polling, DB updates) **must run continuously** (`jf runner start`);
no daemon-free mode is documented on that page. This may just mean "daemon-free" refers to a
separate, local-only mode irrelevant to remote HPC — but don't take the operational assumption at
face value. Before finalizing: confirm whether a genuinely daemon-free remote-SSH mode exists, and
who/what supervises the Runner in production (systemd unit? survives reboots?).

**Verified current and real:** [`Matgenix/jobflow-remote`](https://github.com/Matgenix/jobflow-remote)
— `pushed_at: 2026-09-07` (today, genuinely active), 54 open issues, 40 stars. This is the most
actively-developed of everything checked in this ADR.

## 4. Confirmed accurate: yambopy (the standalone pip package, distinct from aiida-yambo)

[`yambo-code/yambopy`](https://github.com/yambo-code/yambopy) — **GPL-2.0 confirmed.** ADR-031's
plan to isolate it behind an optional `[yambo]` extra, never linked into the main MIT package, is
correct and should stay a hard requirement. Active (`pushed_at` in the last month). Covers netCDF
`ndb.QP`/exciton parsing as claimed. No correction needed — proceed with ADR-031's plan for the
standalone-parsing path; note this is orthogonal to the `aiida-yambo` question in §2, which wraps a
full workflow engine around similar functionality rather than being a parsing library alone.

## 5. Remaining open questions

- Actual license terms of `aiida-yambo` (GitHub reports `NOASSERTION`, meaning no auto-detectable
  SPDX license — check the repo's `LICENSE` file directly, don't assume).
- `aiida-crystal-dft`'s real CRYSTAL23 keyword coverage — described only as a CRYSTAL17 spin-off;
  needs hands-on testing, not just doc-reading.
- CRYSTALpytools's handling of the CRYSTAL23-specific quirks hit firsthand tonight (`99 0`
  basis-set terminator; `BASISSET`-needs-`BASISSETS.DAT`; the `-diag-error` vs. Intel `mpif.h`
  conflict) — these are compiler/build-time issues so shouldn't affect a Python parser/writer, but
  worth having in mind for whoever wires this up end-to-end first.

## Sources

- CRYSTALpytools: [GitHub](https://github.com/crystal-code-tools/CRYSTALpytools) · [PyPI](https://pypi.org/project/CRYSTALpytools/) · [crystal_io API docs](https://crystal-code-tools.github.io/CRYSTALpytools/crystalpytools.crystal_io.html) · [input/basis-set docs](https://crystal-code-tools.github.io/CRYSTALpytools/examples/input_and_basisset/input_and_basisset.html) · [paper](https://www.sciencedirect.com/science/article/pii/S0010465523001984) · GitHub API metadata fetched 2026-09-07
- jobflow-remote: [GitHub](https://github.com/Matgenix/jobflow-remote) · [quickstart (v1.0.0 manual)](https://matgenix.github.io/jobflow-remote/user/quickstart.html) · GitHub API metadata fetched 2026-09-07
- yambopy: [GitHub](https://github.com/yambo-code/yambopy) · [wiki: first steps](https://wiki.yambo-code.eu/wiki/index.php/First_steps_in_Yambopy)
- aiida-quantumespresso: [GitHub](https://github.com/aiidateam/aiida-quantumespresso) · [docs](https://aiida-quantumespresso.readthedocs.io/)
- aiida-vasp: [GitHub](https://github.com/DropD/aiida-vasp)
- aiida-crystal-dft: [GitHub](https://github.com/tilde-lab/aiida-crystal-dft) · GitHub API metadata fetched 2026-09-07
- aiida-yambo: [GitHub](https://github.com/yambo-code/aiida-yambo) · [docs](https://aiida-yambo.readthedocs.io/en/master/) · [AiiDA blog "success story" post, 2025-05-15](https://aiida.net/blog/2025-05-15-aiida-yambo/) · GitHub API metadata fetched 2026-09-07
- AiiDA core: [aiida.net](https://aiida.net/) · [installation/troubleshooting docs](https://aiida.readthedocs.io/projects/aiida-core/en/stable/installation/troubleshooting.html)
- This project's own `docs/architecture/aiida-integration.md` (historical/superseded — source of the CRYSTALpytools finding in §1)
