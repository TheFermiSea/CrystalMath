"""HighThroughput API for one-liner materials analysis workflows.

This module provides the main entry point for the high-level API, enabling
complete workflows from structure input to publication-ready results with
a single function call.

Example:
    from crystalmath.high_level import HighThroughput

    # Complete analysis from CIF file
    results = HighThroughput.run_standard_analysis(
        structure="NbOCl2.cif",
        properties=["bands", "dos", "phonon", "bse"],
        codes={"dft": "vasp", "gw": "yambo"},
        cluster="beefcake2"
    )

    # From Materials Project
    results = HighThroughput.from_mp("mp-1234", properties=["elastic"])

Note:
    This is a STUB implementation for Phase 2.3 API design.
    Full implementation will be completed in Phase 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Union,
)

from crystalmath.protocols import (
    DFTCode,
    ErrorRecoveryStrategy,
    ProgressCallback,
    ResourceRequirements,
    WorkflowType,
)

if TYPE_CHECKING:
    from pymatgen.core import Structure

    from .results import AnalysisResults

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Classes
# =============================================================================


@dataclass
class HighThroughputConfig:
    """Configuration for high-throughput analysis.

    Attributes:
        properties: List of properties to calculate (bands, dos, phonon, etc.)
        protocol: Accuracy level (fast, moderate, precise)
        codes: Code selection override, e.g., {"dft": "vasp", "gw": "yambo"}
        cluster: Cluster profile name (None for local execution)
        resources: Custom resource requirements (overrides cluster defaults)
        progress_callback: Progress notification handler
        output_dir: Directory for output files
        checkpoint_interval: Checkpoint frequency (steps between saves)
        recovery_strategy: Error recovery strategy
    """

    properties: List[str]
    protocol: str = "moderate"
    codes: Optional[Dict[str, DFTCode]] = None
    cluster: Optional[str] = None
    resources: Optional[ResourceRequirements] = None
    progress_callback: Optional[ProgressCallback] = None
    output_dir: Optional[Path] = None
    checkpoint_interval: int = 1
    recovery_strategy: ErrorRecoveryStrategy = ErrorRecoveryStrategy.ADAPTIVE


# =============================================================================
# Supported Properties
# =============================================================================

# Property -> (WorkflowType, default_code, dependencies)
PROPERTY_DEFINITIONS: Dict[str, tuple[WorkflowType, DFTCode, List[str]]] = {
    "scf": (WorkflowType.SCF, "vasp", []),
    "relax": (WorkflowType.RELAX, "vasp", []),
    "bands": (WorkflowType.BANDS, "vasp", ["scf"]),
    "dos": (WorkflowType.DOS, "vasp", ["scf"]),
    "phonon": (WorkflowType.PHONON, "vasp", ["relax"]),
    "elastic": (WorkflowType.ELASTIC, "vasp", ["relax"]),
    "dielectric": (WorkflowType.DIELECTRIC, "vasp", ["scf"]),
    "gw": (WorkflowType.GW, "yambo", ["scf"]),
    "bse": (WorkflowType.BSE, "yambo", ["gw"]),
    "eos": (WorkflowType.EOS, "vasp", []),
    "neb": (WorkflowType.NEB, "vasp", ["relax"]),
}


# =============================================================================
# HighThroughput Class
# =============================================================================


class HighThroughput:
    """High-level API for automated materials analysis.

    Provides one-liner methods for complete workflows from structure
    to publication-ready results. Automatically selects appropriate
    DFT codes based on property type and handles all intermediate steps.

    Design:
        - Wraps protocol layer (protocols.py) without duplication
        - Auto-selects codes based on property requirements
        - Smart defaults with protocol-based overrides (fast/moderate/precise)
        - Progress tracking for interactive (Jupyter) and batch (CLI) usage

    Example:
        # One-liner analysis
        results = HighThroughput.run_standard_analysis(
            structure="NbOCl2.cif",
            properties=["bands", "dos", "phonon"],
            cluster="beefcake2"
        )

        # Access results
        print(f"Band gap: {results.band_gap_ev:.2f} eV")
        results.plot_bands().savefig("bands.png")
        results.to_latex_table("table.tex")

    Note:
        This is a STUB implementation. Methods raise NotImplementedError
        until Phase 3 implementation is complete.
    """

    @classmethod
    def run_standard_analysis(
        cls,
        structure: Union[str, Path, "Structure"],
        properties: List[str],
        codes: Optional[Dict[str, str]] = None,
        cluster: Optional[str] = None,
        protocol: str = "moderate",
        progress_callback: Optional[ProgressCallback] = None,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Run complete analysis workflow.

        This is the primary entry point for high-throughput analysis. Given a
        structure and list of properties, it:

        1. Loads and validates the structure
        2. Determines required workflow steps and dependencies
        3. Selects appropriate DFT codes for each step
        4. Generates parameters based on protocol level
        5. Submits and monitors the workflow
        6. Collects and returns unified results

        Args:
            structure: Input structure. Can be:
                - File path (str/Path) to CIF, POSCAR, XYZ, etc.
                - pymatgen Structure object
                - AiiDA StructureData node (by PK or UUID)
            properties: Properties to calculate. Supported:
                - "scf", "relax" - Ground state
                - "bands", "dos" - Electronic structure
                - "phonon" - Phonon dispersion
                - "elastic" - Elastic constants
                - "dielectric" - Dielectric tensor
                - "gw", "bse" - Many-body perturbation theory
            codes: Code selection override. Keys:
                - "dft": DFT code for ground state (vasp, crystal23, qe)
                - "gw": Many-body code (yambo, berkeleygw)
            cluster: Cluster profile name. Pre-configured:
                - "beefcake2": 6-node V100S cluster
                - "local": Local execution
                - None: Auto-select based on environment
            protocol: Accuracy level:
                - "fast": Quick screening (0.08 A^-1 k-density)
                - "moderate": Production (0.04 A^-1 k-density)
                - "precise": Publication quality (0.02 A^-1 k-density)
            progress_callback: Progress notification handler
            output_dir: Directory for output files
            **kwargs: Additional workflow options

        Returns:
            AnalysisResults with all computed properties and export methods

        Raises:
            StructureNotFoundError: If structure cannot be loaded
            NoCompatibleCodeError: If no compatible code is available
            WorkflowValidationError: If workflow configuration is invalid
            ClusterConnectionError: If cluster is unreachable

        Example:
            results = HighThroughput.run_standard_analysis(
                structure="mp-1234.cif",
                properties=["bands", "dos", "gw", "bse"],
                codes={"dft": "vasp", "gw": "yambo"},
                cluster="beefcake2",
                protocol="moderate"
            )

            # Access scalar results
            print(f"DFT band gap: {results.band_gap_ev:.2f} eV")
            print(f"GW band gap: {results.gw_gap_ev:.2f} eV")
            print(f"Optical gap: {results.optical_gap_ev:.2f} eV")

            # Export
            results.to_dataframe().to_csv("properties.csv")
            results.plot_bands_dos().savefig("electronic_structure.png")
        """
        # Stub implementation - will be completed in Phase 3
        raise NotImplementedError(
            "HighThroughput.run_standard_analysis() will be implemented in Phase 3. "
            "See docs/architecture/HIGH-LEVEL-API.md for design specification."
        )

    @classmethod
    def from_mp(
        cls,
        material_id: str,
        properties: List[str],
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Fetch structure from Materials Project and run analysis.

        Convenience method that combines Materials Project structure retrieval
        with run_standard_analysis(). Uses the MaterialsService from
        tui/src/core/materials_api/ for structure fetching.

        Args:
            material_id: Materials Project ID (e.g., "mp-1234", "mp-149")
            properties: Properties to calculate (see run_standard_analysis)
            **kwargs: Additional options passed to run_standard_analysis

        Returns:
            AnalysisResults with all computed properties

        Raises:
            StructureNotFoundError: If material_id not found in Materials Project
            AuthenticationError: If MP API key is invalid

        Example:
            # Calculate band structure of silicon (mp-149)
            results = HighThroughput.from_mp("mp-149", properties=["bands", "dos"])
            print(f"Si band gap: {results.band_gap_ev:.2f} eV")

            # NbOCl2 with GW corrections
            results = HighThroughput.from_mp(
                "mp-1234",
                properties=["bands", "gw", "bse"],
                cluster="beefcake2"
            )
        """
        # Stub implementation
        raise NotImplementedError(
            "HighThroughput.from_mp() will be implemented in Phase 3. "
            "See docs/architecture/HIGH-LEVEL-API.md for design specification."
        )

    @classmethod
    def from_poscar(
        cls,
        poscar_path: Union[str, Path],
        properties: List[str],
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Load VASP POSCAR and run analysis.

        Convenience method for VASP users who have structures in POSCAR format.

        Args:
            poscar_path: Path to POSCAR file
            properties: Properties to calculate
            **kwargs: Additional options passed to run_standard_analysis

        Returns:
            AnalysisResults with all computed properties

        Example:
            results = HighThroughput.from_poscar(
                "POSCAR",
                properties=["relax", "bands", "dos"]
            )
        """
        # Stub implementation
        raise NotImplementedError(
            "HighThroughput.from_poscar() will be implemented in Phase 3."
        )

    @classmethod
    def from_structure(
        cls,
        structure: "Structure",
        properties: List[str],
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Run analysis on pymatgen Structure object.

        For users who already have a pymatgen Structure in memory,
        this avoids file I/O overhead.

        Args:
            structure: pymatgen Structure object
            properties: Properties to calculate
            **kwargs: Additional options passed to run_standard_analysis

        Returns:
            AnalysisResults with all computed properties

        Example:
            from pymatgen.core import Structure, Lattice

            # Create structure programmatically
            lattice = Lattice.cubic(5.43)
            structure = Structure(lattice, ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])

            results = HighThroughput.from_structure(
                structure,
                properties=["bands", "phonon"]
            )
        """
        # Stub implementation
        raise NotImplementedError(
            "HighThroughput.from_structure() will be implemented in Phase 3."
        )

    @classmethod
    def from_aiida(
        cls,
        pk_or_uuid: Union[int, str],
        properties: List[str],
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Load structure from AiiDA database and run analysis.

        For integration with existing AiiDA workflows, this loads a
        StructureData node directly from the AiiDA database.

        Args:
            pk_or_uuid: AiiDA node PK (int) or UUID (str)
            properties: Properties to calculate
            **kwargs: Additional options passed to run_standard_analysis

        Returns:
            AnalysisResults with all computed properties

        Example:
            # Load by PK
            results = HighThroughput.from_aiida(12345, properties=["bands"])

            # Load by UUID
            results = HighThroughput.from_aiida(
                "a1b2c3d4-e5f6-...",
                properties=["elastic"]
            )
        """
        # Stub implementation
        raise NotImplementedError(
            "HighThroughput.from_aiida() will be implemented in Phase 3."
        )

    # =========================================================================
    # Internal Methods (for Phase 3 implementation)
    # =========================================================================

    @classmethod
    def _load_structure(
        cls,
        structure: Union[str, Path, "Structure"],
    ) -> "Structure":
        """Load structure from various input formats.

        Args:
            structure: Input structure (file path, Structure, etc.)

        Returns:
            pymatgen Structure object
        """
        # Will use StructureProvider protocol
        raise NotImplementedError("Phase 3")

    @classmethod
    def _determine_workflow_steps(
        cls,
        properties: List[str],
        codes: Optional[Dict[str, str]],
    ) -> List[tuple[str, WorkflowType, DFTCode]]:
        """Determine workflow steps from property list.

        Resolves dependencies and selects codes for each step.

        Args:
            properties: Requested properties
            codes: Code overrides

        Returns:
            List of (step_name, workflow_type, code) tuples in execution order
        """
        # Will use PropertyCalculator registry
        raise NotImplementedError("Phase 3")

    @classmethod
    def _generate_parameters(
        cls,
        structure: "Structure",
        workflow_type: WorkflowType,
        code: DFTCode,
        protocol: str,
    ) -> Dict[str, Any]:
        """Generate calculation parameters.

        Args:
            structure: Input structure
            workflow_type: Type of calculation
            code: DFT code to use
            protocol: Accuracy level

        Returns:
            Parameter dictionary for the calculation
        """
        # Will use ParameterGenerator protocol
        raise NotImplementedError("Phase 3")

    @classmethod
    def _validate_properties(cls, properties: List[str]) -> tuple[bool, List[str]]:
        """Validate requested properties.

        Args:
            properties: List of property names

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        for prop in properties:
            if prop not in PROPERTY_DEFINITIONS:
                issues.append(f"Unknown property: {prop}")
        return len(issues) == 0, issues

    @classmethod
    def get_supported_properties(cls) -> List[str]:
        """Get list of supported properties.

        Returns:
            List of property names that can be calculated
        """
        return list(PROPERTY_DEFINITIONS.keys())

    @classmethod
    def get_property_info(cls, property_name: str) -> Dict[str, Any]:
        """Get information about a property.

        Args:
            property_name: Property name

        Returns:
            Dictionary with workflow_type, default_code, dependencies

        Raises:
            KeyError: If property not found
        """
        if property_name not in PROPERTY_DEFINITIONS:
            raise KeyError(f"Unknown property: {property_name}. "
                          f"Supported: {cls.get_supported_properties()}")

        wf_type, default_code, deps = PROPERTY_DEFINITIONS[property_name]
        return {
            "name": property_name,
            "workflow_type": wf_type.value,
            "default_code": default_code,
            "dependencies": deps,
        }
