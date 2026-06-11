# CrystalMath Architectural Decision Records (ADRs)

This directory serves as the centralized repository log tracking foundational architecture decisions 
governing the CrystalMath platform ecosystem under our unified Rust/Ratatui strategy.

## 📋 Active Timeline Index

| Index | Architecture Decision Domain File | Status | Last Updated |
| :--- | :--- | :---: | :---: |
| **001** | [Python Textual As Primary Tui Rust Ratatui As Secondary](adr-001-python-textual-as-primary-tui-rust-ratatui-as-secondary.md) | `Accepted` | 2026-06-11 |
| **002** | [atomate2 integration design](adr-002-atomate2-integration-design.md) | `Accepted` | 2026-06-11 |
| **003** | [Rust Tui Secondaryexperimental Policy](adr-003-rust-tui-secondaryexperimental-policy.md) | `Accepted` | 2026-06-11 |
| **004** | [Ipc Boundary Design For Rust Tui](adr-004-ipc-boundary-design-for-rust-tui.md) | `Accepted` | 2026-06-11 |
| **005** | [Editorlsp Strategy Upstream Integration Only](adr-005-editorlsp-strategy-upstream-integration-only.md) | `Accepted` | 2026-06-11 |
| **006** | [Unified Configuration Across Cli And Python Core](adr-006-unified-configuration-across-cli-and-python-core.md) | `Accepted` | 2026-06-11 |
| **007** | [Unify On A Single Rust Tui Over An Ipc Backend](adr-007-unify-on-a-single-rust-tui-over-an-ipc-backend.md) | `Accepted` | 2026-06-11 |
| **008** | [Redesign Overview Adopt The Materials Project Ecosystem Collapse N Way Facades To One](adr-008-redesign-overview-adopt-the-materials-project-ecosystem-collapse-n-way-facades-to-one.md) | `Accepted` | 2026-06-11 |
| **009** | [Standardize Structure And Inputoutput On Pymatgen Ase Codedeckgenerator Becomes A Thin Adapter](adr-009-standardize-structure-and-inputoutput-on-pymatgen-ase-codedeckgenerator-becomes-a-thin-adapter.md) | `Accepted` | 2026-06-11 |
| **010** | [Canonical Result Schema Emmet Style Versioned Pydantic Taskdocuments With First Class Provenance Fields](adr-010-canonical-result-schema-emmet-style-versioned-pydantic-taskdocuments-with-first-class-provenance-fields.md) | `Accepted` | 2026-06-11 |
| **011** | [A Single Canonical Result Store Jobflow Jobstore Over Maggma](adr-011-a-single-canonical-result-store-jobflow-jobstore-over-maggma.md) | `Accepted` | 2026-06-11 |
| **012** | [Workflow Engine Jobflow Flows Atomate2quacc Recipes As The One Orchestration Model](adr-012-workflow-engine-jobflow-flows-atomate2quacc-recipes-as-the-one-orchestration-model.md) | `Accepted` | 2026-06-11 |
| **013** | [Hpc Execution Layer Jobflow Remote Outbound Ssh Polling Daemon As Default Aiida Opt In Delete The Bespoke Slurmssh Stack](adr-013-hpc-execution-layer-jobflow-remote-outbound-ssh-polling-daemon-as-default-aiida-opt-in-delete-the-bespoke-slurmssh-stack.md) | `Accepted` | 2026-06-11 |
| **014** | [Multi Code Handoff Contract Typed Document Edges With Mandatory Restart File Validation](adr-014-multi-code-handoff-contract-typed-document-edges-with-mandatory-restart-file-validation.md) | `Accepted` | 2026-06-11 |
| **015** | [Rustpython Boundary Json Rpc 20 Over Spawned Child Stdio Lspmcp Pattern Delete Pyo3 And Unify Dispatch](adr-015-rustpython-boundary-json-rpc-20-over-spawned-child-stdio-lspmcp-pattern-delete-pyo3-and-unify-dispatch.md) | `Accepted` | 2026-06-11 |
| **016** | [Unified Configuration Pydantic Settings As The Single Resolver](adr-016-unified-configuration-pydantic-settings-as-the-single-resolver.md) | `Accepted` | 2026-06-11 |
| **017** | [Wire Contract Pydantic Models As Source Of Truth Generate Rust Serde Types](adr-017-wire-contract-pydantic-models-as-source-of-truth-generate-rust-serde-types.md) | `Accepted` | 2026-06-11 |
| **018** | [Packaging Testing Two Decoupled Artifacts Pixi For Hpc An Extras Matrix Ci](adr-018-packaging-testing-two-decoupled-artifacts-pixi-for-hpc-an-extras-matrix-ci.md) | `Accepted` | 2026-06-11 |
| **019** | [Replace The Bespoke Adaptive Recovery With Custodian Style Code Specific Error Handlers](adr-019-replace-the-bespoke-adaptive-recovery-with-custodian-style-code-specific-error-handlers.md) | `Accepted` | 2026-06-11 |
| **020** | [Delete The Unimplemented Protocolspy High_level Phase 3 Aspiration Layer Keep Only The Type Aliases](adr-020-delete-the-unimplemented-protocolspy-high_level-phase-3-aspiration-layer-keep-only-the-type-aliases.md) | `Accepted` | 2026-06-11 |
| **021** | [Reproducibility Spine Golden File Property Tests And Real Dft Parser Fixtures](adr-021-reproducibility-spine-golden-file-property-tests-and-real-dft-parser-fixtures.md) | `Accepted` | 2026-06-11 |
| **022** | [Generalize The Calculation Layer To Calculatorstage Mlipfoundation Calculators As First Class Peers Of Dft](adr-022-generalize-the-calculation-layer-to-calculatorstage-mlipfoundation-calculators-as-first-class-peers-of-dft.md) | `Accepted` | 2026-06-11 |
| **023** | [Content Addressed Execution Identity Hash Hit Caching And The Replay Contract As The Default Execution Gate](adr-023-content-addressed-execution-identity-hash-hit-caching-and-the-replay-contract-as-the-default-execution-gate.md) | `Accepted` | 2026-06-11 |
| **024** | [Agenticllm Control Plane A Guarded Mcp Tool Server Above Jobflow A Generative Candidatesource And First Class Ai Provenance](adr-024-agenticllm-control-plane-a-guarded-mcp-tool-server-above-jobflow-a-generative-candidatesource-and-first-class-ai-provenance.md) | `Accepted` | 2026-06-11 |
| **025** | [Static Typed Workflowdag Validation Crystalmath Validate Before Any Submission](adr-025-static-typed-workflowdag-validation-crystalmath-validate-before-any-submission.md) | `Accepted` | 2026-06-11 |
| **026** | [Campaign Acquisition Strategy The Pluggable Scientific Brain Typed Acquisitionstrategy Campaignstrategy With Budgetconvergencestopping And Dft Budget Control](adr-026-campaign-acquisition-strategy-the-pluggable-scientific-brain-typed-acquisitionstrategy-campaignstrategy-with-budgetconvergencestopping-and-dft-budget-control.md) | `Accepted` | 2026-06-11 |
| **027** | [Trustworthy Mlip Evaluation Applicability Domain Measured Not Asserted Surrogate Trust Benchmark Harness Calibrated Uncertainty Oodapplicability Domain Gate Escalation Thresholds](adr-027-trustworthy-mlip-evaluation-applicability-domain-measured-not-asserted-surrogate-trust-benchmark-harness-calibrated-uncertainty-oodapplicability-domain-gate-escalation-thresholds.md) | `Accepted` | 2026-06-11 |
| **028** | [Model Dataset Registry Lineage Navigable Registries Over The Adr 022 Cas The Single Unified Modelidentifier](adr-028-model-dataset-registry-lineage-navigable-registries-over-the-adr-022-cas-the-single-unified-modelidentifier.md) | `Accepted` | 2026-06-11 |
| **029** | [crystalmath redesign master index adr 007 adr 027](adr-029-crystalmath-redesign-master-index-adr-007-adr-027.md) | `Accepted` | 2026-06-11 |
| **030** | [ecosystem consolidation validated refactor plan](adr-030-ecosystem-consolidation-validated-refactor-plan.md) | `Accepted` | 2026-06-11 |
| **031** | [high level api design](adr-031-high-level-api-design.md) | `Accepted` | 2026-06-11 |
| **032** | [unified workflow architecture](adr-032-unified-workflow-architecture.md) | `Accepted` | 2026-06-11 |
