# High-Level API Design

**Version:** 1.0.0
**Status:** Design Phase
**Date:** 2026-01-09
**Phase:** 2.3 of CrystalMath Workflow Integration Project

---

## Executive Summary

This document defines the "batteries included" high-level API for CrystalMath, providing:

1. **HighThroughput** - One-liner workflows from structure to publication-quality results
2. **WorkflowBuilder** - Fluent interface for custom workflow construction
3. **PropertyCalculator** - Registry for automatic code selection
4. **ClusterProfile** - Pre-configured cluster settings
5. **Publication Export** - pandas, matplotlib, plotly, and LaTeX export

The API wraps the protocol interfaces defined in `protocols.py` without duplicating them.

---

## Table of Contents

1. [Target User Experience](#target-user-experience)
2. [Architecture Overview](#architecture-overview)
3. [HighThroughput Class](#highthroughput-class)
4. [WorkflowBuilder](#workflowbuilder)
5. [PropertyCalculator Registry](#propertycalculator-registry)
6. [ClusterProfile Configuration](#clusterprofile-configuration)
7. [Publication Export](#publication-export)
8. [Progress Tracking](#progress-tracking)
9. [Implementation Notes](#implementation-notes)

---

## Target User Experience

### One-Liner Workflow

```python
from crystalmath import HighThroughput

# Complete workflow from CIF to publication-quality results
results = HighThroughput.run_standard_analysis(
    structure="NbOCl2.cif",
    properties=["bands", "dos", "phonon", "bse"],
    codes={"dft": "vasp", "gw": "yambo"},
    cluster="beefcake2"
)

# Access results
print(f"Band gap: {results.band_gap_ev:.2f} eV")
print(f"Is direct gap: {results.is_direct_gap}")

# Export to publication formats
results.to_dataframe().to_csv("results.csv")
results.plot_bands().savefig("bands.png")
results.to_latex_table("properties.tex")
```

### From Materials Project

```python
# Fetch structure from Materials Project and run analysis
results = HighThroughput.from_mp(
    "mp-1234",
    properties=["elastic", "transport", "dielectric"],
    protocol="precise"
)
```

### Fluent Builder Pattern

```python
from crystalmath import WorkflowBuilder

# Build custom workflow with explicit control
workflow = (
    WorkflowBuilder()
    .from_file("NbOCl2.cif")
    .relax(code="vasp", protocol="moderate")
    .then_bands(kpath="auto", kpoints_per_segment=50)
    .then_dos(mesh=[12, 12, 12])
    .with_gw(code="yambo", protocol="gw0")
    .with_bse(code="yambo", n_valence=4, n_conduction=4)
    .on_cluster("beefcake2", partition="gpu")
    .with_progress(callback=my_progress_handler)
    .build()
)

# Execute and monitor
result = workflow.run()
```

### Interactive (Jupyter) Usage

```python
# Async iteration for progress updates in Jupyter
async for update in workflow.run_async():
    print(f"Step: {update.step_name}, Progress: {update.percent}%")
    if update.has_intermediate_result:
        display(update.intermediate_result.plot())
```

---

## Architecture Overview

```
+===========================================================================+
|                          User-Facing API                                   |
|  +--------------------------+  +----------------------------------+        |
|  |     HighThroughput       |  |       WorkflowBuilder            |        |
|  |  - run_standard_analysis |  |  - from_file() / from_mp()       |        |
|  |  - from_mp()             |  |  - relax() / bands() / dos()     |        |
|  |  - from_poscar()         |  |  - with_gw() / with_bse()        |        |
|  |  - from_structure()      |  |  - on_cluster() / build()        |        |
|  +--------------------------+  +----------------------------------+        |
+===========================================================================+
                                    |
                                    v
+===========================================================================+
|                         Internal Components                                |
|  +-------------------+  +----------------------+  +--------------------+   |
|  | PropertyCalculator|  |   ClusterProfile     |  |  ResultsExporter   |   |
|  | Registry          |  |   - beefcake2        |  |  - to_dataframe()  |   |
|  | - bands -> codes  |  |   - local            |  |  - plot_*()        |   |
|  | - gw -> yambo     |  |   - custom           |  |  - to_latex()      |   |
|  +-------------------+  +----------------------+  +--------------------+   |
+===========================================================================+
                                    |
                                    v
+===========================================================================+
|                       Protocol Layer (protocols.py)                        |
|  +------------------+  +--------------------+  +-----------------------+   |
|  | WorkflowRunner   |  | StructureProvider  |  | ParameterGenerator    |   |
|  +------------------+  +--------------------+  +-----------------------+   |
+===========================================================================+
```

---

## HighThroughput Class

### Class Definition

```python
@dataclass
class HighThroughputConfig:
    """Configuration for high-throughput analysis."""

    # Property calculation settings
    properties: List[str]
    protocol: str = "moderate"  # fast, moderate, precise

    # Code selection (auto if not specified)
    codes: Optional[Dict[str, DFTCode]] = None

    # Cluster settings
    cluster: Optional[str] = None
    resources: Optional[ResourceRequirements] = None

    # Progress and output
    progress_callback: Optional[ProgressCallback] = None
    output_dir: Optional[Path] = None

    # Recovery settings
    checkpoint_interval: int = 1  # Checkpoint after each step
    recovery_strategy: ErrorRecoveryStrategy = ErrorRecoveryStrategy.ADAPTIVE


class HighThroughput:
    """High-level API for automated materials analysis.

    Provides one-liner methods for complete workflows from structure
    to publication-ready results. Automatically selects appropriate
    DFT codes based on property type and handles all intermediate steps.

    Example:
        results = HighThroughput.run_standard_analysis(
            structure="NbOCl2.cif",
            properties=["bands", "dos", "phonon"],
            cluster="beefcake2"
        )
    """

    @classmethod
    def run_standard_analysis(
        cls,
        structure: Union[str, Path, "Structure", "StructureData"],
        properties: List[str],
        codes: Optional[Dict[str, str]] = None,
        cluster: Optional[str] = None,
        protocol: str = "moderate",
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Run complete analysis workflow.

        Args:
            structure: Input structure (file path, pymatgen Structure, or AiiDA StructureData)
            properties: Properties to calculate (bands, dos, phonon, elastic, gw, bse, etc.)
            codes: Code selection override {"dft": "vasp", "gw": "yambo"}
            cluster: Cluster profile name (None for local)
            protocol: Accuracy level (fast, moderate, precise)
            **kwargs: Additional workflow options

        Returns:
            AnalysisResults with all computed properties
        """
        ...

    @classmethod
    def from_mp(
        cls,
        material_id: str,
        properties: List[str],
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Fetch structure from Materials Project and run analysis.

        Args:
            material_id: Materials Project ID (e.g., "mp-1234")
            properties: Properties to calculate
            **kwargs: Additional options passed to run_standard_analysis

        Returns:
            AnalysisResults with all computed properties
        """
        ...

    @classmethod
    def from_poscar(
        cls,
        poscar_path: Union[str, Path],
        properties: List[str],
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Load POSCAR and run analysis.

        Args:
            poscar_path: Path to POSCAR file
            properties: Properties to calculate
            **kwargs: Additional options

        Returns:
            AnalysisResults
        """
        ...

    @classmethod
    def from_structure(
        cls,
        structure: "Structure",
        properties: List[str],
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Run analysis on pymatgen Structure.

        Args:
            structure: pymatgen Structure object
            properties: Properties to calculate
            **kwargs: Additional options

        Returns:
            AnalysisResults
        """
        ...
```

### Supported Properties

| Property | Default Code | Description | Dependencies |
|----------|--------------|-------------|--------------|
| `scf` | vasp/crystal23 | Self-consistent field | None |
| `relax` | vasp/crystal23 | Geometry optimization | None |
| `bands` | vasp/crystal23 | Band structure | scf |
| `dos` | vasp/crystal23 | Density of states | scf |
| `phonon` | vasp + phonopy | Phonon dispersion | relax |
| `elastic` | vasp | Elastic constants | relax |
| `dielectric` | vasp | Dielectric tensor | scf |
| `gw` | yambo | GW quasiparticle | scf (with wavefunctions) |
| `bse` | yambo | BSE optical | gw |
| `transport` | boltztrap2 | Transport properties | bands (dense mesh) |
| `neb` | vasp | Transition state | relax (endpoints) |

---

## WorkflowBuilder

### Fluent Interface Design

```python
class WorkflowBuilder:
    """Fluent builder for custom workflow construction.

    Enables step-by-step workflow definition with explicit control
    over each calculation stage while maintaining a clean, readable API.

    Example:
        workflow = (
            WorkflowBuilder()
            .from_file("structure.cif")
            .relax(code="vasp", protocol="moderate")
            .then_bands(kpath="auto")
            .then_dos()
            .on_cluster("beefcake2")
            .build()
        )
    """

    def __init__(self) -> None:
        """Initialize empty workflow builder."""
        self._structure: Optional[Any] = None
        self._structure_source: Optional[str] = None
        self._steps: List[WorkflowStep] = []
        self._cluster: Optional[ClusterProfile] = None
        self._progress_callback: Optional[ProgressCallback] = None
        self._output_dir: Optional[Path] = None
        self._recovery_strategy: ErrorRecoveryStrategy = ErrorRecoveryStrategy.ADAPTIVE

    # =========== Structure Input Methods ===========

    def from_file(self, path: Union[str, Path]) -> "WorkflowBuilder":
        """Load structure from file (CIF, POSCAR, XYZ, etc.).

        Args:
            path: Path to structure file

        Returns:
            Self for method chaining
        """
        ...

    def from_mp(self, material_id: str) -> "WorkflowBuilder":
        """Fetch structure from Materials Project.

        Args:
            material_id: Materials Project ID

        Returns:
            Self for method chaining
        """
        ...

    def from_structure(self, structure: "Structure") -> "WorkflowBuilder":
        """Use pymatgen Structure directly.

        Args:
            structure: pymatgen Structure object

        Returns:
            Self for method chaining
        """
        ...

    def from_aiida(self, pk_or_uuid: Union[int, str]) -> "WorkflowBuilder":
        """Load structure from AiiDA database.

        Args:
            pk_or_uuid: AiiDA node PK or UUID

        Returns:
            Self for method chaining
        """
        ...

    # =========== DFT Workflow Steps ===========

    def relax(
        self,
        code: Optional[DFTCode] = None,
        protocol: str = "moderate",
        force_threshold: float = 0.01,  # eV/A
        stress_threshold: float = 0.1,  # kbar
        max_steps: int = 200,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add geometry optimization step.

        Args:
            code: DFT code (auto-selected if None)
            protocol: Accuracy level (fast, moderate, precise)
            force_threshold: Force convergence criterion
            stress_threshold: Stress convergence criterion
            max_steps: Maximum optimization steps
            **params: Additional code-specific parameters

        Returns:
            Self for method chaining
        """
        ...

    def scf(
        self,
        code: Optional[DFTCode] = None,
        protocol: str = "moderate",
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add SCF calculation step.

        Args:
            code: DFT code (auto-selected if None)
            protocol: Accuracy level
            **params: Additional parameters

        Returns:
            Self for method chaining
        """
        ...

    def then_bands(
        self,
        kpath: Union[str, List[Tuple[str, List[float]]]] = "auto",
        kpoints_per_segment: int = 50,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add band structure calculation (depends on previous SCF).

        Args:
            kpath: K-point path ("auto", preset name, or custom path)
            kpoints_per_segment: Number of k-points per path segment
            **params: Additional parameters

        Returns:
            Self for method chaining
        """
        ...

    def then_dos(
        self,
        mesh: Optional[List[int]] = None,
        smearing: float = 0.05,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add DOS calculation (depends on previous SCF).

        Args:
            mesh: K-point mesh for DOS (auto if None)
            smearing: Gaussian smearing width (eV)
            **params: Additional parameters

        Returns:
            Self for method chaining
        """
        ...

    def then_phonon(
        self,
        supercell: Optional[List[int]] = None,
        displacement: float = 0.01,  # Angstrom
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add phonon calculation (depends on relaxed structure).

        Args:
            supercell: Supercell dimensions (auto if None)
            displacement: Finite displacement amplitude
            **params: Additional parameters

        Returns:
            Self for method chaining
        """
        ...

    def then_elastic(
, **params: Any) -> "WorkflowBuilder":
        """Add elastic constants calculation.

        Args:
            **params: Additional parameters

        Returns:
            Self for method chaining
        """
        ...

    # =========== Many-Body Perturbation Theory ===========

    def with_gw(
        self,
        code: DFTCode = "yambo",
        protocol: str = "gw0",  # g0w0, gw0, evgw
        n_bands: Optional[int] = None,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add GW quasiparticle calculation.

        Requires SCF step with compatible code (VASP, QE, or CRYSTAL23
        with appropriate wavefunction output).

        Args:
            code: Many-body code (yambo, berkeleygw)
            protocol: GW flavor (g0w0, gw0, evgw)
            n_bands: Number of bands for GW
            **params: Additional parameters

        Returns:
            Self for method chaining
        """
        ...

    def with_bse(
        self,
        code: DFTCode = "yambo",
        n_valence: int = 4,
        n_conduction: int = 4,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add BSE optical calculation.

        Requires GW step for quasiparticle corrections.

        Args:
            code: Many-body code (yambo, berkeleygw)
            n_valence: Number of valence bands
            n_conduction: Number of conduction bands
            **params: Additional parameters

        Returns:
            Self for method chaining
        """
        ...

    # =========== Cluster and Execution ===========

    def on_cluster(
        self,
        cluster: str,
        partition: Optional[str] = None,
        resources: Optional[ResourceRequirements] = None,
    ) -> "WorkflowBuilder":
        """Configure cluster execution.

        Args:
            cluster: Cluster profile name (e.g., "beefcake2", "local")
            partition: SLURM partition (None for default)
            resources: Custom resource requirements

        Returns:
            Self for method chaining
        """
        ...

    def with_progress(
        self,
        callback: Optional[ProgressCallback] = None,
    ) -> "WorkflowBuilder":
        """Enable progress tracking.

        Args:
            callback: Progress callback (uses default console if None)

        Returns:
            Self for method chaining
        """
        ...

    def with_output(self, output_dir: Union[str, Path]) -> "WorkflowBuilder":
        """Set output directory for results.

        Args:
            output_dir: Directory for output files

        Returns:
            Self for method chaining
        """
        ...

    def with_recovery(
        self,
        strategy: ErrorRecoveryStrategy,
    ) -> "WorkflowBuilder":
        """Configure error recovery strategy.

        Args:
            strategy: Recovery strategy (FAIL_FAST, RETRY, ADAPTIVE, etc.)

        Returns:
            Self for method chaining
        """
        ...

    # =========== Build and Execute ===========

    def build(self) -> "Workflow":
        """Build the workflow for execution.

        Validates the workflow configuration and returns an executable
        Workflow object.

        Returns:
            Configured Workflow ready for execution

        Raises:
            ValidationError: If workflow is invalid
        """
        ...

    def validate(self) -> Tuple[bool, List[str]]:
        """Validate workflow configuration.

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        ...
```

### Workflow Object

```python
class Workflow:
    """Executable workflow built by WorkflowBuilder.

    Provides synchronous and asynchronous execution methods with
    progress tracking and intermediate result access.
    """

    def run(self) -> "AnalysisResults":
        """Execute workflow synchronously.

        Returns:
            AnalysisResults with all computed properties
        """
        ...

    async def run_async(self) -> AsyncIterator["ProgressUpdate"]:
        """Execute workflow asynchronously with progress updates.

        Yields:
            ProgressUpdate objects for each step

        Returns:
            AnalysisResults when complete
        """
        ...

    def submit(self) -> str:
        """Submit workflow without waiting.

        Returns:
            Workflow ID for status tracking
        """
        ...

    @classmethod
    def get_status(cls, workflow_id: str) -> "WorkflowStatus":
        """Get status of submitted workflow.

        Args:
            workflow_id: Workflow ID from submit()

        Returns:
            Current workflow status
        """
        ...

    @classmethod
    def get_result(cls, workflow_id: str) -> "AnalysisResults":
        """Get results of completed workflow.

        Args:
            workflow_id: Workflow ID from submit()

        Returns:
            AnalysisResults if complete

        Raises:
            WorkflowNotCompleteError: If workflow still running
        """
        ...
```

---

## PropertyCalculator Registry

### Automatic Code Selection

```python
class PropertyCalculator:
    """Registry for property -> code mapping.

    Determines which DFT code is best suited for each property type,
    considering:
    - Property requirements (e.g., BSE requires GW which requires specific codes)
    - Available codes on the cluster
    - User preferences
    """

    # Default code mappings
    DEFAULT_CODES: Dict[str, List[DFTCode]] = {
        # Ground state DFT
        "scf": ["vasp", "crystal23", "quantum_espresso"],
        "relax": ["vasp", "crystal23", "quantum_espresso"],
        "bands": ["vasp", "crystal23", "quantum_espresso"],
        "dos": ["vasp", "crystal23", "quantum_espresso"],

        # Mechanical properties
        "elastic": ["vasp"],
        "phonon": ["vasp", "crystal23", "quantum_espresso"],

        # Electronic response
        "dielectric": ["vasp", "crystal23"],

        # Many-body perturbation theory
        "gw": ["yambo", "berkeleygw"],
        "bse": ["yambo", "berkeleygw"],

        # Transport
        "transport": ["boltztrap2"],

        # Transition states
        "neb": ["vasp"],
    }

    # Code compatibility matrix for multi-code workflows
    CODE_COMPATIBILITY: Dict[Tuple[str, str], bool] = {
        # DFT -> GW code compatibility
        ("vasp", "yambo"): True,
        ("quantum_espresso", "yambo"): True,
        ("crystal23", "yambo"): True,  # Via converter
        ("vasp", "berkeleygw"): True,
        ("quantum_espresso", "berkeleygw"): True,
    }

    @classmethod
    def select_code(
        cls,
        property_name: str,
        available_codes: Optional[List[DFTCode]] = None,
        user_preference: Optional[DFTCode] = None,
        previous_code: Optional[DFTCode] = None,
    ) -> DFTCode:
        """Select best code for a property.

        Args:
            property_name: Property to calculate
            available_codes: Codes available on the cluster
            user_preference: User-specified preference
            previous_code: Code used in previous step (for compatibility)

        Returns:
            Selected DFT code

        Raises:
            NoCompatibleCodeError: If no compatible code available
        """
        ...

    @classmethod
    def validate_workflow_codes(
        cls,
        steps: List[WorkflowStep],
    ) -> Tuple[bool, List[str]]:
        """Validate code compatibility across workflow steps.

        Args:
            steps: List of workflow steps with assigned codes

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        ...
```

---

## ClusterProfile Configuration

### Pre-Configured Clusters

```python
@dataclass
class ClusterProfile:
    """Configuration profile for a compute cluster.

    Includes hardware specs, available codes, default resources,
    and SLURM/scheduler settings.
    """

    name: str
    description: str

    # Hardware
    nodes: int
    cores_per_node: int
    memory_gb_per_node: float
    gpus_per_node: int = 0
    gpu_type: Optional[str] = None

    # Available codes
    available_codes: List[DFTCode] = field(default_factory=list)
    code_paths: Dict[DFTCode, str] = field(default_factory=dict)

    # Default resources
    default_partition: str = "default"
    default_walltime_hours: float = 24.0

    # Resource presets
    presets: Dict[str, ResourceRequirements] = field(default_factory=dict)

    # Connection settings
    ssh_host: Optional[str] = None
    ssh_user: Optional[str] = None
    scheduler: str = "slurm"


# Pre-configured profiles
CLUSTER_PROFILES: Dict[str, ClusterProfile] = {
    "beefcake2": ClusterProfile(
        name="beefcake2",
        description="Beefcake2 HPC cluster (6 nodes, V100S GPUs)",
        nodes=6,
        cores_per_node=40,
        memory_gb_per_node=376,
        gpus_per_node=1,
        gpu_type="Tesla V100S",
        available_codes=["vasp", "quantum_espresso", "yambo", "crystal23"],
        code_paths={
            "vasp": "/opt/vasp/6.5.1/bin/vasp_std",
            "quantum_espresso": "/opt/qe/7.3.1/bin/pw.x",
            "yambo": "/opt/yambo/5.3.0/bin/yambo",
        },
        default_partition="compute",
        presets={
            "small": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=8,
                num_threads_per_rank=1,
                memory_gb=32,
                walltime_hours=4,
            ),
            "medium": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=20,
                num_threads_per_rank=2,
                memory_gb=128,
                walltime_hours=12,
            ),
            "large": ResourceRequirements(
                num_nodes=2,
                num_mpi_ranks=40,
                num_threads_per_rank=2,
                memory_gb=256,
                walltime_hours=24,
            ),
            "gpu-single": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=1,
                gpus=1,
                memory_gb=64,
                walltime_hours=12,
            ),
            "gpu-multi": ResourceRequirements(
                num_nodes=3,
                num_mpi_ranks=3,
                gpus=3,
                memory_gb=192,
                walltime_hours=24,
            ),
        },
    ),
    "local": ClusterProfile(
        name="local",
        description="Local execution (development/testing)",
        nodes=1,
        cores_per_node=4,
        memory_gb_per_node=16,
        available_codes=["crystal23"],
        default_partition="local",
        presets={
            "default": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=4,
                memory_gb=8,
                walltime_hours=1,
            ),
        },
    ),
}


def get_cluster_profile(name: str) -> ClusterProfile:
    """Get cluster profile by name.

    Args:
        name: Profile name

    Returns:
        ClusterProfile configuration

    Raises:
        KeyError: If profile not found
    """
    if name not in CLUSTER_PROFILES:
        raise KeyError(f"Unknown cluster profile: {name}. "
                      f"Available: {list(CLUSTER_PROFILES.keys())}")
    return CLUSTER_PROFILES[name]
```

---

## Publication Export

### AnalysisResults Class

```python
@dataclass
class AnalysisResults:
    """Container for all computed properties.

    Provides methods for data access and export to various
    publication-ready formats.
    """

    # Structure info
    formula: str
    structure: "Structure"
    space_group: str

    # Electronic properties
    band_gap_ev: Optional[float] = None
    is_direct_gap: Optional[bool] = None
    fermi_energy_ev: Optional[float] = None
    is_metal: bool = False

    # Band structure data
    band_structure: Optional["BandStructureData"] = None
    dos: Optional["DOSData"] = None

    # GW/BSE results
    gw_gap_ev: Optional[float] = None
    gw_corrections: Optional[Dict[str, float]] = None
    optical_gap_ev: Optional[float] = None
    exciton_binding_ev: Optional[float] = None

    # Mechanical properties
    elastic_tensor: Optional["ElasticTensor"] = None
    bulk_modulus_gpa: Optional[float] = None
    shear_modulus_gpa: Optional[float] = None
    youngs_modulus_gpa: Optional[float] = None
    poisson_ratio: Optional[float] = None

    # Phonon properties
    phonon_dispersion: Optional["PhononData"] = None
    has_imaginary_modes: Optional[bool] = None

    # Dielectric properties
    dielectric_tensor: Optional["DielectricTensor"] = None
    static_dielectric: Optional[float] = None
    high_freq_dielectric: Optional[float] = None

    # Transport properties
    seebeck_coefficient: Optional[float] = None
    electrical_conductivity: Optional[float] = None
    thermal_conductivity: Optional[float] = None

    # Workflow metadata
    workflow_id: Optional[str] = None
    completed_at: Optional[datetime] = None
    total_cpu_hours: Optional[float] = None

    # =========== Export Methods ===========

    def to_dataframe(self) -> "pd.DataFrame":
        """Export scalar properties to pandas DataFrame.

        Returns:
            DataFrame with property names and values
        """
        import pandas as pd

        data = {
            "formula": self.formula,
            "space_group": self.space_group,
            "band_gap_ev": self.band_gap_ev,
            "is_direct_gap": self.is_direct_gap,
            "is_metal": self.is_metal,
            "gw_gap_ev": self.gw_gap_ev,
            "optical_gap_ev": self.optical_gap_ev,
            "exciton_binding_ev": self.exciton_binding_ev,
            "bulk_modulus_gpa": self.bulk_modulus_gpa,
            "shear_modulus_gpa": self.shear_modulus_gpa,
            "youngs_modulus_gpa": self.youngs_modulus_gpa,
            "poisson_ratio": self.poisson_ratio,
            "static_dielectric": self.static_dielectric,
        }
        return pd.DataFrame([data])

    def to_dict(self) -> Dict[str, Any]:
        """Export all data to dictionary.

        Returns:
            Nested dictionary with all results
        """
        ...

    def to_json(self, path: Optional[Union[str, Path]] = None) -> str:
        """Export results to JSON.

        Args:
            path: Optional file path (returns string if None)

        Returns:
            JSON string
        """
        ...

    # =========== Plotting Methods ===========

    def plot_bands(
        self,
        ax: Optional["plt.Axes"] = None,
        **kwargs: Any,
    ) -> "plt.Figure":
        """Plot band structure.

        Args:
            ax: Matplotlib axes (creates new figure if None)
            **kwargs: Additional matplotlib options

        Returns:
            Matplotlib figure
        """
        ...

    def plot_dos(
        self,
        ax: Optional["plt.Axes"] = None,
        projected: bool = False,
        **kwargs: Any,
    ) -> "plt.Figure":
        """Plot density of states.

        Args:
            ax: Matplotlib axes
            projected: Show orbital-projected DOS
            **kwargs: Additional options

        Returns:
            Matplotlib figure
        """
        ...

    def plot_bands_dos(
        self,
        figsize: Tuple[float, float] = (10, 6),
        **kwargs: Any,
    ) -> "plt.Figure":
        """Plot combined band structure and DOS.

        Args:
            figsize: Figure size in inches
            **kwargs: Additional options

        Returns:
            Matplotlib figure with bands and DOS side-by-side
        """
        ...

    def plot_phonons(
        self,
        ax: Optional["plt.Axes"] = None,
        **kwargs: Any,
    ) -> "plt.Figure":
        """Plot phonon dispersion.

        Args:
            ax: Matplotlib axes
            **kwargs: Additional options

        Returns:
            Matplotlib figure
        """
        ...

    def plot_optical(
        self,
        ax: Optional["plt.Axes"] = None,
        components: str = "xx",
        **kwargs: Any,
    ) -> "plt.Figure":
        """Plot optical absorption spectrum.

        Args:
            ax: Matplotlib axes
            components: Tensor component(s) to plot
            **kwargs: Additional options

        Returns:
            Matplotlib figure
        """
        ...

    # =========== Interactive Plotting (Plotly) ===========

    def iplot_bands(self, **kwargs: Any) -> "go.Figure":
        """Interactive band structure plot using Plotly.

        Args:
            **kwargs: Plotly options

        Returns:
            Plotly figure
        """
        ...

    def iplot_dos(self, **kwargs: Any) -> "go.Figure":
        """Interactive DOS plot using Plotly.

        Args:
            **kwargs: Plotly options

        Returns:
            Plotly figure
        """
        ...

    # =========== LaTeX Export ===========

    def to_latex_table(
        self,
        path: Optional[Union[str, Path]] = None,
        properties: Optional[List[str]] = None,
        format_spec: str = "booktabs",
    ) -> str:
        """Export properties as LaTeX table.

        Args:
            path: Optional file path (returns string if None)
            properties: Properties to include (all if None)
            format_spec: Table format (booktabs, simple)

        Returns:
            LaTeX table string
        """
        ...

    def to_latex_si_table(
        self,
        path: Optional[Union[str, Path]] = None,
    ) -> str:
        """Export as LaTeX SI table with proper units.

        Args:
            path: Optional file path

        Returns:
            LaTeX table with siunitx formatting
        """
        ...
```

### Example LaTeX Output

```latex
\begin{table}[htbp]
\centering
\caption{Calculated properties of NbOCl$_2$}
\label{tab:properties}
\begin{tabular}{lS[table-format=2.3]}
\toprule
Property & {Value} \\
\midrule
Band gap (PBE) & \SI{1.23}{\electronvolt} \\
Band gap (GW) & \SI{2.45}{\electronvolt} \\
Optical gap (BSE) & \SI{2.12}{\electronvolt} \\
Exciton binding & \SI{0.33}{\electronvolt} \\
Bulk modulus & \SI{45.2}{\giga\pascal} \\
\bottomrule
\end{tabular}
\end{table}
```

---

## Progress Tracking

### ProgressUpdate Class

```python
@dataclass
class ProgressUpdate:
    """Progress update for async workflow execution."""

    workflow_id: str
    step_name: str
    step_index: int
    total_steps: int
    percent: float
    status: str  # pending, running, completed, failed
    message: Optional[str] = None

    # Intermediate results
    has_intermediate_result: bool = False
    intermediate_result: Optional["PartialResults"] = None

    # Timing
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: Optional[float] = None


class ConsoleProgressCallback(ProgressCallback):
    """Default progress callback for console output."""

    def on_started(self, workflow_id: str, workflow_type: WorkflowType) -> None:
        print(f"Starting {workflow_type.value} workflow [{workflow_id}]")

    def on_progress(
        self,
        workflow_id: str,
        step: str,
        progress_percent: float,
        message: Optional[str] = None,
    ) -> None:
        bar = "=" * int(progress_percent / 5) + ">" + " " * (20 - int(progress_percent / 5))
        print(f"\r[{bar}] {progress_percent:.1f}% - {step}", end="", flush=True)
        if message:
            print(f" ({message})", end="", flush=True)

    def on_completed(self, workflow_id: str, result: WorkflowResult) -> None:
        print(f"\nCompleted [{workflow_id}]")
        if result.outputs.get("band_gap_ev"):
            print(f"  Band gap: {result.outputs['band_gap_ev']:.2f} eV")

    def on_failed(
        self,
        workflow_id: str,
        error: str,
        recoverable: bool,
    ) -> None:
        print(f"\nFailed [{workflow_id}]: {error}")
        if recoverable:
            print("  (Recoverable - attempting restart)")


class JupyterProgressCallback(ProgressCallback):
    """Progress callback with Jupyter widget display."""

    def __init__(self) -> None:
        from ipywidgets import FloatProgress, HTML, VBox
        from IPython.display import display

        self.progress_bar = FloatProgress(min=0, max=100)
        self.status_label = HTML()
        self.widget = VBox([self.status_label, self.progress_bar])
        display(self.widget)

    def on_progress(
        self,
        workflow_id: str,
        step: str,
        progress_percent: float,
        message: Optional[str] = None,
    ) -> None:
        self.progress_bar.value = progress_percent
        self.status_label.value = f"<b>{step}</b>" + (f": {message}" if message else "")
```

---

## Implementation Notes

### Integration with Protocol Layer

The high-level API **wraps** the protocol layer, not duplicates it:

```python
class HighThroughput:
    """High-level API implementation."""

    @classmethod
    def run_standard_analysis(cls, structure, properties, **kwargs):
        # 1. Get structure provider from protocols
        provider = get_structure_provider("auto")
        struct = provider.get_structure(structure)
        info = provider.get_info(struct)

        # 2. Build workflow using WorkflowComposer
        composer = WorkflowComposer()
        for prop in properties:
            code = PropertyCalculator.select_code(prop)
            composer.add_step(prop, WorkflowType[prop.upper()], code=code)
        steps = composer.build()

        # 3. Get runner from protocols
        runner = get_runner(kwargs.get("backend", "aiida"))

        # 4. Submit and wait
        result = runner.submit_composite(steps, struct)

        # 5. Convert to AnalysisResults
        return cls._to_analysis_results(result)
```

### Smart Defaults

Protocol settings vary by accuracy level:

| Protocol | K-point Density | Energy Cutoff | SCF Tolerance | Description |
|----------|-----------------|---------------|---------------|-------------|
| `fast` | 0.08 A^-1 | Low | 1e-5 | Screening, quick tests |
| `moderate` | 0.04 A^-1 | Standard | 1e-7 | Production calculations |
| `precise` | 0.02 A^-1 | High | 1e-9 | Publication-quality |

### Error Handling

```python
class CrystalMathError(Exception):
    """Base exception for CrystalMath errors."""
    pass

class StructureNotFoundError(CrystalMathError):
    """Structure could not be loaded or found."""
    pass

class NoCompatibleCodeError(CrystalMathError):
    """No compatible DFT code available for the requested property."""
    pass

class WorkflowValidationError(CrystalMathError):
    """Workflow configuration is invalid."""
    pass

class ClusterConnectionError(CrystalMathError):
    """Could not connect to compute cluster."""
    pass
```

---

## File Locations

| File | Purpose |
|------|---------|
| `python/crystalmath/high_level/__init__.py` | Package exports |
| `python/crystalmath/high_level/api.py` | HighThroughput class |
| `python/crystalmath/high_level/builder.py` | WorkflowBuilder class |
| `python/crystalmath/high_level/results.py` | AnalysisResults and export |
| `python/crystalmath/high_level/clusters.py` | ClusterProfile definitions |
| `python/crystalmath/high_level/registry.py` | PropertyCalculator registry |
| `python/crystalmath/high_level/progress.py` | Progress callbacks |

---

## Dependencies

Required:
- `pymatgen` - Structure handling
- `numpy` - Numerical operations

Optional (for full functionality):
- `pandas` - DataFrame export
- `matplotlib` - Static plotting
- `plotly` - Interactive plotting
- `mp-api` - Materials Project access
- `ipywidgets` - Jupyter progress

---

## References

1. Protocol definitions: `python/crystalmath/protocols.py`
2. Architecture overview: `docs/architecture/UNIFIED-WORKFLOW-ARCHITECTURE.md`
3. Existing workflows: `python/crystalmath/workflows/`
4. TUI Materials API: `tui/src/core/materials_api/service.py`
