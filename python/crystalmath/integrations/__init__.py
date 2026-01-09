"""
CrystalMath Integration Layer.

This package provides adapters and bridges for integrating external workflow
frameworks with CrystalMath's unified workflow architecture.

Supported Integrations:
-----------------------

**Materials Project (mp-api)**:
    Access to the Materials Project database for structure retrieval
    and property lookup:
    - MPClient: Full-featured API client
    - mp_id_to_structure: Quick structure retrieval
    - search_structures: Material search by formula/elements

**atomate2 (via jobflow)**:
    Pre-built materials science workflows for VASP, QE, and other codes.
    Enables access to atomate2's extensive Maker library:
    - RelaxFlowMaker: Geometry optimization
    - StaticFlowMaker: SCF calculations
    - BandStructureFlowMaker: Band structure + DOS
    - ElasticFlowMaker: Elastic tensor calculations
    - PhononFlowMaker: Phonon properties

**jobflow Store Bridge**:
    Connects atomate2's JobStore to CrystalMath's storage backends:
    - MemoryStore -> Local development
    - MongoStore -> Production with MongoDB
    - SQLite bridge -> Integration with .crystal_tui.db

**Multi-code Workflow Adapters**:
    Bridges for code handoffs in complex workflows:
    - VASP -> YAMBO (GW/BSE)
    - QE -> BerkeleyGW
    - CRYSTAL23 -> Wannier90

**PWD (Python Workflow Definition) Bridge**:
    Machine-readable workflow exchange format for interoperability:
    - PWDConverter: Bidirectional conversion to/from PWD format
    - export_to_pwd: Export workflows to PWD JSON
    - import_from_pwd: Import workflows from PWD files
    - Enables sharing with AiiDA/jobflow/pyiron users

**pymatgen Bridge**:
    Structure conversion and analysis functions:
    - structure_from_cif: Load structures from CIF files
    - structure_from_poscar: Load structures from VASP POSCAR
    - structure_from_mp: Load structures from Materials Project
    - structure_from_cod: Load structures from Crystallography Open Database
    - to_aiida_structure: Convert pymatgen to AiiDA StructureData
    - from_aiida_structure: Convert AiiDA StructureData to pymatgen
    - to_ase_atoms: Convert pymatgen to ASE Atoms
    - from_ase_atoms: Convert ASE Atoms to pymatgen
    - get_symmetry_info: Analyze structure symmetry
    - get_dimensionality: Determine 0D/1D/2D/3D dimensionality
    - validate_for_dft: Pre-calculation validation

Design Notes:
-------------
All integrations implement the Protocol interfaces defined in
`crystalmath.protocols`, ensuring consistent behavior regardless
of the underlying execution engine.

Example Usage:
--------------
>>> from crystalmath.integrations import MPClient, mp_id_to_structure
>>>
>>> # Quick structure retrieval
>>> structure = mp_id_to_structure("mp-149")  # Silicon
>>>
>>> # Full client for searches
>>> client = MPClient()
>>> materials = client.search_structures(formula="MoS2", is_stable=True)

>>> from crystalmath.integrations import Atomate2Bridge
>>> from crystalmath.protocols import WorkflowType
>>>
>>> # Create bridge with default store
>>> bridge = Atomate2Bridge()
>>>
>>> # Run a VASP relaxation using atomate2
>>> result = bridge.run_flow(
...     workflow_type=WorkflowType.RELAX,
...     structure=structure,
...     code="vasp",
... )

See Also:
---------
- `crystalmath.protocols` - Interface definitions
- `crystalmath.runners` - WorkflowRunner implementations (Phase 3)
- `docs/architecture/ATOMATE2-INTEGRATION.md` - Design documentation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Version of the integrations package
__version__ = "0.1.0"

# Lazy imports to avoid requiring all dependencies at import time
if TYPE_CHECKING:
    from crystalmath.integrations.atomate2_bridge import (
        Atomate2Bridge,
        Atomate2FlowAdapter,
        FlowMakerRegistry,
        MultiCodeFlowBuilder,
    )
    from crystalmath.integrations.jobflow_store import (
        CrystalMathJobStore,
        JobStoreBridge,
        SQLiteJobStore,
    )
    from crystalmath.integrations.materials_project import (
        MPClient,
        MPMaterial,
        MPProperties,
        mp_id_to_structure,
        validate_mp_id,
        search_by_formula,
    )
    from crystalmath.integrations.pwd_bridge import (
        PWDConverter,
        PWDNode,
        PWDEdge,
        CrystalMathExtensions,
        export_to_pwd,
        import_from_pwd,
    )
    from crystalmath.integrations.pymatgen_bridge import (
        SymmetryInfo,
        StructureMetadata,
        CrystalSystem,
        Dimensionality,
        structure_from_cif,
        structure_from_poscar,
        structure_from_mp,
        structure_from_cod,
        structure_from_file,
        to_aiida_structure,
        from_aiida_structure,
        to_ase_atoms,
        from_ase_atoms,
        convert_structure,
        get_symmetry_info,
        get_dimensionality,
        validate_for_dft,
        get_structure_metadata,
    )
    from crystalmath.integrations.aiida_enhanced import (
        AIIDA_AVAILABLE,
        ProfileInfo,
        CalculationInfo,
        AiiDAProfileManager,
        AiiDAQueryHelper,
        aiida_to_atomate2_job,
        atomate2_to_aiida_inputs,
        workflow_result_from_aiida,
    )
    from crystalmath.integrations.slurm_runner import (
        SLURMConfig,
        SLURMJobInfo,
        SLURMWorkflowError,
        SLURMWorkflowRunner,
        create_slurm_runner,
    )


def __getattr__(name: str):
    """Lazy import of integration modules."""
    # Materials Project integration
    if name in (
        "MPClient",
        "MPMaterial",
        "MPProperties",
        "mp_id_to_structure",
        "validate_mp_id",
        "search_by_formula",
    ):
        from crystalmath.integrations.materials_project import (
            MPClient,
            MPMaterial,
            MPProperties,
            mp_id_to_structure,
            validate_mp_id,
            search_by_formula,
        )

        return {
            "MPClient": MPClient,
            "MPMaterial": MPMaterial,
            "MPProperties": MPProperties,
            "mp_id_to_structure": mp_id_to_structure,
            "validate_mp_id": validate_mp_id,
            "search_by_formula": search_by_formula,
        }[name]

    # atomate2 bridge
    if name in (
        "Atomate2Bridge",
        "Atomate2FlowAdapter",
        "FlowMakerRegistry",
        "MultiCodeFlowBuilder",
    ):
        from crystalmath.integrations.atomate2_bridge import (
            Atomate2Bridge,
            Atomate2FlowAdapter,
            FlowMakerRegistry,
            MultiCodeFlowBuilder,
        )

        return {
            "Atomate2Bridge": Atomate2Bridge,
            "Atomate2FlowAdapter": Atomate2FlowAdapter,
            "FlowMakerRegistry": FlowMakerRegistry,
            "MultiCodeFlowBuilder": MultiCodeFlowBuilder,
        }[name]

    # jobflow store
    if name in ("CrystalMathJobStore", "JobStoreBridge", "SQLiteJobStore"):
        from crystalmath.integrations.jobflow_store import (
            CrystalMathJobStore,
            JobStoreBridge,
            SQLiteJobStore,
        )

        return {
            "CrystalMathJobStore": CrystalMathJobStore,
            "JobStoreBridge": JobStoreBridge,
            "SQLiteJobStore": SQLiteJobStore,
        }[name]

    # PWD bridge
    if name in (
        "PWDConverter",
        "PWDNode",
        "PWDEdge",
        "CrystalMathExtensions",
        "export_to_pwd",
        "import_from_pwd",
    ):
        from crystalmath.integrations.pwd_bridge import (
            PWDConverter,
            PWDNode,
            PWDEdge,
            CrystalMathExtensions,
            export_to_pwd,
            import_from_pwd,
        )

        return {
            "PWDConverter": PWDConverter,
            "PWDNode": PWDNode,
            "PWDEdge": PWDEdge,
            "CrystalMathExtensions": CrystalMathExtensions,
            "export_to_pwd": export_to_pwd,
            "import_from_pwd": import_from_pwd,
        }[name]

    # pymatgen bridge
    if name in (
        "SymmetryInfo",
        "StructureMetadata",
        "CrystalSystem",
        "Dimensionality",
        "structure_from_cif",
        "structure_from_poscar",
        "structure_from_mp",
        "structure_from_cod",
        "structure_from_file",
        "to_aiida_structure",
        "from_aiida_structure",
        "to_ase_atoms",
        "from_ase_atoms",
        "convert_structure",
        "get_symmetry_info",
        "get_dimensionality",
        "validate_for_dft",
        "get_structure_metadata",
    ):
        from crystalmath.integrations.pymatgen_bridge import (
            SymmetryInfo,
            StructureMetadata,
            CrystalSystem,
            Dimensionality,
            structure_from_cif,
            structure_from_poscar,
            structure_from_mp,
            structure_from_cod,
            structure_from_file,
            to_aiida_structure,
            from_aiida_structure,
            to_ase_atoms,
            from_ase_atoms,
            convert_structure,
            get_symmetry_info,
            get_dimensionality,
            validate_for_dft,
            get_structure_metadata,
        )

        return {
            "SymmetryInfo": SymmetryInfo,
            "StructureMetadata": StructureMetadata,
            "CrystalSystem": CrystalSystem,
            "Dimensionality": Dimensionality,
            "structure_from_cif": structure_from_cif,
            "structure_from_poscar": structure_from_poscar,
            "structure_from_mp": structure_from_mp,
            "structure_from_cod": structure_from_cod,
            "structure_from_file": structure_from_file,
            "to_aiida_structure": to_aiida_structure,
            "from_aiida_structure": from_aiida_structure,
            "to_ase_atoms": to_ase_atoms,
            "from_ase_atoms": from_ase_atoms,
            "convert_structure": convert_structure,
            "get_symmetry_info": get_symmetry_info,
            "get_dimensionality": get_dimensionality,
            "validate_for_dft": validate_for_dft,
            "get_structure_metadata": get_structure_metadata,
        }[name]

    # AiiDA enhanced integration
    if name in (
        "AIIDA_AVAILABLE",
        "ProfileInfo",
        "CalculationInfo",
        "AiiDAProfileManager",
        "AiiDAQueryHelper",
        "aiida_to_atomate2_job",
        "atomate2_to_aiida_inputs",
        "workflow_result_from_aiida",
    ):
        from crystalmath.integrations.aiida_enhanced import (
            AIIDA_AVAILABLE,
            ProfileInfo,
            CalculationInfo,
            AiiDAProfileManager,
            AiiDAQueryHelper,
            aiida_to_atomate2_job,
            atomate2_to_aiida_inputs,
            workflow_result_from_aiida,
        )

        return {
            "AIIDA_AVAILABLE": AIIDA_AVAILABLE,
            "ProfileInfo": ProfileInfo,
            "CalculationInfo": CalculationInfo,
            "AiiDAProfileManager": AiiDAProfileManager,
            "AiiDAQueryHelper": AiiDAQueryHelper,
            "aiida_to_atomate2_job": aiida_to_atomate2_job,
            "atomate2_to_aiida_inputs": atomate2_to_aiida_inputs,
            "workflow_result_from_aiida": workflow_result_from_aiida,
        }[name]

    # SLURM workflow runner
    if name in (
        "SLURMConfig",
        "SLURMJobInfo",
        "SLURMWorkflowError",
        "SLURMWorkflowRunner",
        "create_slurm_runner",
    ):
        from crystalmath.integrations.slurm_runner import (
            SLURMConfig,
            SLURMJobInfo,
            SLURMWorkflowError,
            SLURMWorkflowRunner,
            create_slurm_runner,
        )

        return {
            "SLURMConfig": SLURMConfig,
            "SLURMJobInfo": SLURMJobInfo,
            "SLURMWorkflowError": SLURMWorkflowError,
            "SLURMWorkflowRunner": SLURMWorkflowRunner,
            "create_slurm_runner": create_slurm_runner,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Materials Project integration
    "MPClient",
    "MPMaterial",
    "MPProperties",
    "mp_id_to_structure",
    "validate_mp_id",
    "search_by_formula",
    # atomate2 bridge classes
    "Atomate2Bridge",
    "Atomate2FlowAdapter",
    "FlowMakerRegistry",
    "MultiCodeFlowBuilder",
    # jobflow store classes
    "CrystalMathJobStore",
    "JobStoreBridge",
    "SQLiteJobStore",
    # PWD bridge classes
    "PWDConverter",
    "PWDNode",
    "PWDEdge",
    "CrystalMathExtensions",
    "export_to_pwd",
    "import_from_pwd",
    # pymatgen bridge classes and functions
    "SymmetryInfo",
    "StructureMetadata",
    "CrystalSystem",
    "Dimensionality",
    "structure_from_cif",
    "structure_from_poscar",
    "structure_from_mp",
    "structure_from_cod",
    "structure_from_file",
    "to_aiida_structure",
    "from_aiida_structure",
    "to_ase_atoms",
    "from_ase_atoms",
    "convert_structure",
    "get_symmetry_info",
    "get_dimensionality",
    "validate_for_dft",
    "get_structure_metadata",
    # AiiDA enhanced integration
    "AIIDA_AVAILABLE",
    "ProfileInfo",
    "CalculationInfo",
    "AiiDAProfileManager",
    "AiiDAQueryHelper",
    "aiida_to_atomate2_job",
    "atomate2_to_aiida_inputs",
    "workflow_result_from_aiida",
    # SLURM workflow runner
    "SLURMConfig",
    "SLURMJobInfo",
    "SLURMWorkflowError",
    "SLURMWorkflowRunner",
    "create_slurm_runner",
]
