# Meta-Prompt: CrystalMath Advanced Workflow Integration

## Objective
Deeply integrate the crystalmath library with AiiDA, pymatgen, atomate2, and other advanced computational materials science libraries to enable high-level computational workflows with minimal effort.

---

## Phase 1: Research Phase

### Prompt 1.1: Current State Analysis
```
Research the current integration state of the crystalmath library at /Users/briansquires/CRYSTAL23/crystalmath/

Analyze:
1. Existing AiiDA integration in tui/src/aiida/ (29 files) - assess completeness
2. Current pymatgen usage patterns and gaps
3. Missing atomate2 integration opportunities
4. Backend abstraction layer in python/crystalmath/backends/
5. Workflow capabilities in python/crystalmath/workflows/

Output a structured assessment of:
- What works well today
- What's partially implemented
- What's completely missing
- Integration friction points
```

### Prompt 1.2: Library Compatibility Research
```
Research the latest versions and compatibility of:
1. AiiDA 2.x API changes and best practices
2. atomate2 workflow patterns and integration with AiiDA
3. pymatgen structure manipulation and analysis APIs
4. emmet-core for MongoDB/data schemas
5. fireworks vs AiiDA workflow engines
6. jobflow as an alternative workflow manager

For each library, document:
- Version requirements
- Key APIs for DFT workflow automation
- Integration patterns with existing crystalmath architecture
- Potential breaking changes or conflicts
```

### Prompt 1.3: Beefcake2 Cluster Integration Points
```
Analyze the beefcake2 HPC cluster configuration at /Users/briansquires/beefcake2/

Map integration requirements:
1. SLURM scheduler configuration for AiiDA
2. GPU offload patterns for VASP/QE/CRYSTAL
3. NFS shared storage for AiiDA repository
4. SSH/remote execution via asyncssh
5. InfiniBand networking for multi-node MPI

Output cluster-specific configuration templates for:
- AiiDA computer setup (vasp-01, vasp-02, vasp-03, qe-node1)
- Code configurations (VASP 6.4.3, QE 7.3.1, CRYSTAL23, YAMBO 5.3.0)
- Scheduler options and resource allocation
```

---

## Phase 2: Architecture Planning Phase

### Prompt 2.1: Unified Workflow Architecture
```
Design a unified workflow architecture that integrates:
1. crystalmath's existing CrystalController API
2. AiiDA workchains for robust job management
3. atomate2 flows for pre-built materials science workflows
4. pymatgen for structure manipulation and analysis

Requirements:
- Preserve backward compatibility with existing crystalmath APIs
- Support both local and AiiDA backends
- Enable workflow composition (e.g., relax → SCF → bands → DOS → BSE)
- Provide high-level entry points for common tasks

Output:
- UML class diagram or architectural diagram
- Interface definitions (Python Protocol classes)
- Data flow for a complete workflow pipeline
```

### Prompt 2.2: Atomate2 Integration Design
```
Design the atomate2 integration layer for crystalmath:

1. Map atomate2 Flows to crystalmath workflows:
   - RelaxFlowMaker → geometry optimization
   - StaticFlowMaker → SCF calculations
   - BandStructureFlowMaker → band structure
   - ElasticFlowMaker → elastic properties

2. Bridge atomate2 job stores with crystalmath database:
   - JobStore → SQLite/.crystal_tui.db
   - AiiDA backend → AiiDA archive

3. Handle multi-code workflows:
   - VASP → YAMBO (GW/BSE)
   - QE → BerkeleyGW
   - CRYSTAL23 → phonon/transport

Output Python module structure and key class definitions.
```

### Prompt 2.3: High-Level API Design
```
Design a high-level "batteries included" API for crystalmath:

Target user experience:
```python
from crystalmath import HighThroughput

# One-liner workflow from CIF to publication-quality results
results = HighThroughput.run_standard_analysis(
    structure="NbOCl2.cif",
    properties=["bands", "dos", "phonon", "bse"],
    codes={"dft": "vasp", "gw": "yambo"},
    cluster="beefcake2"
)

# Or from Materials Project ID
results = HighThroughput.from_mp("mp-1234", properties=["elastic", "transport"])
```

Design:
1. Fluent builder pattern for workflow construction
2. Automatic code selection based on property type
3. Smart defaults with protocol overrides
4. Progress tracking and intermediate result access
5. Export to publication formats (pandas, matplotlib, plotly)
```

---

## Phase 3: Implementation Phase

### Prompt 3.1: Core Integration Module
```
Implement the core integration module at:
/Users/briansquires/CRYSTAL23/crystalmath/python/crystalmath/integrations/

Create:
1. integrations/__init__.py - Package exports
2. integrations/pymatgen_bridge.py - Structure conversion, analysis
3. integrations/atomate2_bridge.py - Flow adapters
4. integrations/aiida_enhanced.py - Extended AiiDA utilities
5. integrations/materials_project.py - MP API wrapper

Key functions:
- structure_from_* (CIF, POSCAR, MP, COD)
- run_atomate2_flow(flow, backend)
- aiida_to_atomate2_job(aiida_node)
- export_to_publication(results, format)

Include comprehensive type hints and docstrings.
```

### Prompt 3.2: High-Level Workflow Runners
```
Implement high-level workflow runners at:
/Users/briansquires/CRYSTAL23/crystalmath/python/crystalmath/workflows/high_level.py

Workflows to implement:
1. StandardAnalysis - relax → SCF → bands → DOS
2. OpticalAnalysis - SCF → GW → BSE
3. PhononAnalysis - relax → phonon → thermal properties
4. ElasticAnalysis - relax → elastic tensor → mechanical properties
5. TransportAnalysis - SCF → BoltzTraP2 → conductivity

Each workflow should:
- Accept structure as input (file path, pymatgen Structure, or MP ID)
- Auto-configure based on structure chemistry
- Support progress callbacks
- Return structured results object
- Handle restarts and error recovery
```

### Prompt 3.3: Beefcake2 Cluster Configuration
```
Create cluster configuration module at:
/Users/briansquires/CRYSTAL23/crystalmath/python/crystalmath/clusters/beefcake2.py

Implement:
1. Computer definitions (vasp-01/02/03, qe-node1/2/3)
2. Code configurations (VASP 6.4.3, QE 7.3.1, CRYSTAL23, YAMBO 5.3.0)
3. Resource presets (small, medium, large, gpu-single, gpu-multi)
4. Auto-setup function for AiiDA profile

Use the verified cluster specs from /Users/briansquires/beefcake2/CLAUDE.md:
- 40 cores per node (2x Xeon Gold 6248)
- Tesla V100S-PCIE-32GB GPU per node
- InfiniBand HDR100 networking
- NFS shared storage at 10.0.0.5:/home
```

### Prompt 3.4: Testing Suite
```
Create comprehensive test suite at:
/Users/briansquires/CRYSTAL23/crystalmath/python/tests/test_integrations/

Tests to implement:
1. test_pymatgen_bridge.py - Structure conversion, symmetry analysis
2. test_atomate2_bridge.py - Flow creation, job translation
3. test_workflows.py - End-to-end workflow execution (mocked backends)
4. test_cluster_config.py - Computer/code setup validation
5. test_high_level_api.py - HighThroughput interface tests

Use pytest with fixtures for:
- Sample structures (Si, NbOCl2, MoS2)
- Mock AiiDA profile
- Mock SLURM responses
```

---

## Phase 4: Documentation & Examples

### Prompt 4.1: User Documentation
```
Create user documentation at:
/Users/briansquires/CRYSTAL23/crystalmath/docs/workflows/

Documents to create:
1. getting-started.md - Installation, first workflow
2. high-level-api.md - HighThroughput interface guide
3. atomate2-integration.md - Using atomate2 flows
4. cluster-setup.md - Beefcake2 configuration
5. advanced-workflows.md - Custom workflow composition

Include:
- Code examples for every major feature
- Mermaid diagrams for workflow visualization
- Troubleshooting section
```

### Prompt 4.2: Example Notebooks
```
Create Jupyter notebooks at:
/Users/briansquires/CRYSTAL23/crystalmath/examples/

Notebooks to create:
1. 01_quick_start.ipynb - First DFT calculation
2. 02_materials_project.ipynb - MP structure import + analysis
3. 03_band_structure.ipynb - Complete band structure workflow
4. 04_optical_properties.ipynb - GW + BSE with YAMBO
5. 05_high_throughput.ipynb - Batch analysis of structures

Each notebook should be self-contained and executable on beefcake2 cluster.
```

---

## Execution Order

1. **Research Phase** (Prompts 1.1-1.3): Gather all necessary context
2. **Architecture Phase** (Prompts 2.1-2.3): Design before coding
3. **Implementation Phase** (Prompts 3.1-3.4): Build incrementally with tests
4. **Documentation Phase** (Prompts 4.1-4.2): Enable users

---

## Success Criteria

- [ ] pymatgen Structure objects flow seamlessly through workflows
- [ ] atomate2 Flows can be executed via crystalmath backends
- [ ] High-level API enables one-liner workflow execution
- [ ] Beefcake2 cluster is fully configured for all codes
- [ ] 80%+ test coverage on integration modules
- [ ] Documentation covers all major use cases
- [ ] Example notebooks run without modification

---

## Dependencies to Install

```bash
# Core dependencies
uv add pymatgen atomate2 emmet-core jobflow maggma

# AiiDA plugins (if not present)
uv add aiida-vasp aiida-quantumespresso aiida-crystal-main

# Analysis tools
uv add phonopy boltztrap2 sumo

# Visualization
uv add crystal-toolkit plotly matplotlib
```

---

## Notes

- Respect Rust TUI feature freeze (ADR-002)
- All new features go in Python TUI/backend
- Maintain backward compatibility with existing CLI
- Follow existing code style in CLAUDE.md
- Create beads issues for multi-session work
