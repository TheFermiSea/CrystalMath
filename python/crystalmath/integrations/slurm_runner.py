"""
SLURM Workflow Runner - WorkflowRunner implementation for HPC clusters.

This module provides a WorkflowRunner implementation that submits jobs to
SLURM-managed HPC clusters via sbatch. It bridges the high-level workflow
API (StandardAnalysis, OpticalAnalysis, etc.) to actual job execution.

Architecture:
    HighThroughput / StandardAnalysis / OpticalAnalysis
                        ↓
                WorkflowRunner protocol
                        ↓
              SLURMWorkflowRunner (this module)
                        ↓
    tui/src/runners/slurm_runner.py (sbatch submission)

Key Features:
- Implements WorkflowRunner protocol for compatibility with high-level API
- Generates SLURM batch scripts for VASP, QE, CRYSTAL23, YAMBO
- Submits jobs via sbatch over SSH
- Monitors job status via squeue
- Downloads results when jobs complete
- Supports multi-code workflows with proper handoffs

CRITICAL: This ensures ALL computational tasks go through SLURM as required
by the beefcake2 cluster policy. NEVER run DFT codes directly on nodes.

Example:
    from crystalmath.integrations import SLURMWorkflowRunner
    from crystalmath.high_level import StandardAnalysis, get_cluster_profile

    # Create SLURM runner for beefcake2
    runner = SLURMWorkflowRunner.from_cluster_profile(
        profile=get_cluster_profile("beefcake2"),
        default_code="vasp"
    )

    # Use with high-level API
    analysis = StandardAnalysis(
        cluster=get_cluster_profile("beefcake2"),
        runner=runner,  # <-- This ensures SLURM submission
    )
    results = analysis.run("mp-149")

See Also:
    - crystalmath.protocols.WorkflowRunner: Protocol definition
    - tui/src/runners/slurm_runner.py: Underlying SLURM implementation
    - docs/workflows/cluster-setup.md: Cluster configuration guide
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)

if TYPE_CHECKING:
    from crystalmath.high_level.clusters import ClusterProfile
    from crystalmath.protocols import (
        DFTCode,
        ResourceRequirements,
        WorkflowResult,
        WorkflowState,
        WorkflowStep,
        WorkflowType,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class SLURMWorkflowError(Exception):
    """Base exception for SLURM workflow runner errors."""

    pass


class SLURMConnectionError(SLURMWorkflowError):
    """Failed to connect to cluster."""

    pass


class SLURMSubmissionError(SLURMWorkflowError):
    """Job submission via sbatch failed."""

    pass


class SLURMStatusError(SLURMWorkflowError):
    """Failed to retrieve job status."""

    pass


class SLURMResultError(SLURMWorkflowError):
    """Failed to retrieve job results."""

    pass


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class SLURMConfig:
    """Configuration for SLURM workflow runner.

    Attributes:
        cluster_host: Hostname or IP of the cluster head node
        cluster_port: SSH port (default 22)
        username: SSH username
        key_file: Path to SSH private key
        remote_scratch: Base directory for scratch space on cluster
        poll_interval_seconds: Interval for job status polling
        max_concurrent_jobs: Maximum jobs to run concurrently
        default_partition: Default SLURM partition
        default_account: Default SLURM account/project
        default_qos: Default quality of service
    """

    cluster_host: str
    cluster_port: int = 22
    username: str = "ubuntu"
    key_file: Optional[Path] = None
    remote_scratch: str = "/scratch/crystalmath"
    poll_interval_seconds: int = 30
    max_concurrent_jobs: int = 10
    default_partition: Optional[str] = None
    default_account: Optional[str] = None
    default_qos: Optional[str] = None
    allow_insecure: bool = False  # Disable SSH host key verification (opt-in)

    @classmethod
    def from_cluster_profile(cls, profile: "ClusterProfile") -> "SLURMConfig":
        """Create SLURMConfig from a ClusterProfile.

        Args:
            profile: ClusterProfile with cluster details

        Returns:
            SLURMConfig with settings from profile
        """
        # ClusterProfile has ssh_host and ssh_user directly
        if not profile.ssh_host:
            raise ValueError(
                f"ClusterProfile '{profile.name}' has no ssh_host configured"
            )

        # Use profile's SSH settings
        return cls(
            cluster_host=profile.ssh_host,
            cluster_port=22,  # Default SSH port
            username=profile.ssh_user or "root",
            remote_scratch="/scratch/crystalmath",
            default_partition=profile.default_partition,
            poll_interval_seconds=30,
            max_concurrent_jobs=10,
        )


@dataclass
class SLURMJobInfo:
    """Tracking information for a submitted SLURM job.

    Attributes:
        workflow_id: CrystalMath workflow identifier (UUID)
        slurm_job_id: SLURM job ID from sbatch
        state: Current SLURM job state
        remote_dir: Remote directory containing job files
        code: DFT code being run
        submitted_at: When job was submitted
        started_at: When job started running
        completed_at: When job finished
    """

    workflow_id: str
    slurm_job_id: str
    state: str = "PENDING"
    remote_dir: str = ""
    code: str = "vasp"
    submitted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    outputs: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


# =============================================================================
# SLURM Workflow Runner
# =============================================================================


class SLURMWorkflowRunner:
    """
    WorkflowRunner implementation that submits jobs to SLURM.

    This class bridges the high-level workflow API to actual SLURM job
    submission on HPC clusters. It implements the WorkflowRunner protocol
    defined in crystalmath.protocols.

    CRITICAL: This runner ensures all DFT calculations go through SLURM
    batch scheduling, as required by the beefcake2 cluster policy.

    Attributes:
        name: Runner identifier ("slurm")
        is_available: Whether SLURM runner can be used
        config: SLURM configuration settings

    Example:
        # Create runner from cluster profile
        runner = SLURMWorkflowRunner.from_cluster_profile(
            get_cluster_profile("beefcake2")
        )

        # Submit a workflow
        result = runner.submit(
            workflow_type=WorkflowType.RELAX,
            structure=structure,
            parameters={"kpoints": [8, 8, 8]},
            code="vasp",
        )

        # Monitor status
        state = runner.get_status(result.workflow_id)

        # Get results when complete
        final = runner.get_result(result.workflow_id)
    """

    def __init__(
        self,
        config: SLURMConfig,
        default_code: str = "vasp",
    ) -> None:
        """Initialize SLURM workflow runner.

        Args:
            config: SLURM configuration
            default_code: Default DFT code to use (vasp, quantum_espresso, etc.)
        """
        self._config = config
        self._default_code = default_code
        self._is_available: Optional[bool] = None

        # Track submitted jobs: workflow_id -> SLURMJobInfo
        self._jobs: Dict[str, SLURMJobInfo] = {}

        # Connection manager (lazy loaded)
        self._connection_manager: Optional[Any] = None
        self._slurm_runner: Optional[Any] = None

        logger.info(
            f"Initialized SLURMWorkflowRunner for {config.cluster_host}, "
            f"default_code={default_code}"
        )

    @classmethod
    def from_cluster_profile(
        cls,
        profile: "ClusterProfile",
        default_code: str = "vasp",
    ) -> "SLURMWorkflowRunner":
        """Create SLURMWorkflowRunner from a ClusterProfile.

        Args:
            profile: ClusterProfile with cluster configuration
            default_code: Default DFT code

        Returns:
            Configured SLURMWorkflowRunner
        """
        config = SLURMConfig.from_cluster_profile(profile)
        return cls(config=config, default_code=default_code)

    @staticmethod
    def _run_sync(coro):
        """Run an async coroutine from synchronous context.

        Uses asyncio.run() which safely creates a new event loop.
        Raises RuntimeError if called from within a running event loop
        (caller should use the async method directly).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running — safe to create one
            return asyncio.run(coro)
        raise RuntimeError(
            "Cannot call sync API from within a running event loop. "
            "Use the async method (e.g., submit_async, get_status_async) instead."
        )

    # =========================================================================
    # WorkflowRunner Protocol Properties
    # =========================================================================

    @property
    def name(self) -> str:
        """Runner identifier."""
        return "slurm"

    @property
    def is_available(self) -> bool:
        """Check if SLURM runner is available."""
        if self._is_available is None:
            self._is_available = self._check_availability()
        return self._is_available

    def _check_availability(self) -> bool:
        """Check if required dependencies are available."""
        try:
            # Check for TUI runner dependencies
            tui_path = Path(__file__).parent.parent.parent.parent.parent / "tui"
            if tui_path.exists():
                return True

            # Check if asyncssh is available for direct connection
            try:
                import asyncssh  # noqa: F401

                return True
            except ImportError:
                pass

            return False

        except Exception as e:
            logger.warning(f"SLURM runner availability check failed: {e}")
            return False

    # =========================================================================
    # WorkflowRunner Protocol Methods
    # =========================================================================

    async def submit_async(
        self,
        workflow_type: "WorkflowType",
        structure: Any,
        parameters: Dict[str, Any],
        code: Optional["DFTCode"] = None,
        resources: Optional["ResourceRequirements"] = None,
        **kwargs: Any,
    ) -> "WorkflowResult":
        """
        Submit a workflow for execution via SLURM (async).

        This method:
        1. Generates input files for the DFT code
        2. Creates a SLURM batch script
        3. Transfers files to the cluster
        4. Submits via sbatch
        5. Returns immediately with workflow_id for tracking

        Args:
            workflow_type: Type of workflow (SCF, RELAX, BANDS, etc.)
            structure: Input structure (pymatgen Structure, file path, etc.)
            parameters: Calculation parameters
            code: DFT code to use (defaults to self._default_code)
            resources: Computational resource requirements
            **kwargs: Additional options

        Returns:
            WorkflowResult with workflow_id for tracking

        Raises:
            SLURMSubmissionError: If job submission fails
        """
        from crystalmath.protocols import WorkflowResult

        # Generate unique workflow ID
        workflow_id = str(uuid.uuid4())

        # Use provided code or default
        dft_code = code or self._default_code

        logger.info(
            f"Submitting {workflow_type.value} workflow [{workflow_id[:8]}...] "
            f"with code={dft_code}"
        )

        try:
            # Await async submission directly
            slurm_job_id, remote_dir = await self._submit_async(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                structure=structure,
                parameters=parameters,
                code=dft_code,
                resources=resources,
                **kwargs,
            )

            # Track job
            job_info = SLURMJobInfo(
                workflow_id=workflow_id,
                slurm_job_id=slurm_job_id,
                state="PENDING",
                remote_dir=remote_dir,
                code=dft_code,
                submitted_at=datetime.now(),
            )
            self._jobs[workflow_id] = job_info

            logger.info(
                f"Submitted SLURM job {slurm_job_id} for workflow {workflow_id[:8]}"
            )

            return WorkflowResult(
                success=True,
                workflow_id=workflow_id,
                outputs={},
                metadata={
                    "runner": "slurm",
                    "slurm_job_id": slurm_job_id,
                    "remote_dir": remote_dir,
                    "code": dft_code,
                    "status": "submitted",
                },
                started_at=datetime.now(),
            )

        except Exception as e:
            logger.error(f"SLURM submission failed: {e}")
            return WorkflowResult(
                success=False,
                workflow_id=workflow_id,
                errors=[str(e)],
                metadata={"runner": "slurm", "status": "failed"},
            )

    def submit(
        self,
        workflow_type: "WorkflowType",
        structure: Any,
        parameters: Dict[str, Any],
        code: Optional["DFTCode"] = None,
        resources: Optional["ResourceRequirements"] = None,
        **kwargs: Any,
    ) -> "WorkflowResult":
        """Sync entry point for submit. Use submit_async() in async contexts."""
        return self._run_sync(
            self.submit_async(
                workflow_type, structure, parameters, code, resources, **kwargs
            )
        )

    async def _submit_async(
        self,
        workflow_id: str,
        workflow_type: "WorkflowType",
        structure: Any,
        parameters: Dict[str, Any],
        code: str,
        resources: Optional["ResourceRequirements"] = None,
        **kwargs: Any,
    ) -> tuple[str, str]:
        """Async implementation of job submission.

        Returns:
            Tuple of (slurm_job_id, remote_dir)
        """
        # Ensure connection manager is initialized
        await self._ensure_connection()

        # Create temporary directory for input files
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # Generate input files based on code
            input_file = self._generate_input_files(
                work_dir=work_dir,
                workflow_type=workflow_type,
                structure=structure,
                parameters=parameters,
                code=code,
            )

            # Generate SLURM script
            slurm_script = self._generate_slurm_script(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                code=code,
                resources=resources,
            )
            script_path = work_dir / "job.slurm"
            script_path.write_text(slurm_script)

            # Remote directory
            remote_dir = f"{self._config.remote_scratch}/{workflow_id}"

            # Submit via SLURM runner
            slurm_job_id = await self._submit_to_slurm(
                work_dir=work_dir,
                input_file=input_file,
                remote_dir=remote_dir,
            )

            return slurm_job_id, remote_dir

    async def _ensure_connection(self) -> None:
        """Ensure connection manager is initialized."""
        if self._connection_manager is not None:
            return

        try:
            # Try to use TUI connection manager
            tui_path = Path(__file__).parent.parent.parent.parent.parent / "tui"
            if tui_path.exists() and str(tui_path) not in sys.path:
                sys.path.insert(0, str(tui_path))

            from src.core.connection_manager import ConnectionManager

            self._connection_manager = ConnectionManager()

            # Register cluster
            self._connection_manager.register_cluster(
                cluster_id=1,  # Default cluster ID
                host=self._config.cluster_host,
                port=self._config.cluster_port,
                username=self._config.username,
                key_file=(
                    self._config.key_file
                    or Path("~/.ssh/id_ed25519").expanduser()
                ),
            )

            logger.debug(f"Connected to {self._config.cluster_host}")

        except ImportError:
            # Fall back to direct asyncssh
            logger.warning(
                "TUI connection manager not available, using direct asyncssh"
            )
            self._connection_manager = "asyncssh"  # Flag for direct mode

    def _get_known_hosts(self) -> Optional[str]:
        """Resolve known_hosts file for SSH host key verification.

        Returns:
            Path to known_hosts file, or None to skip verification
            (only when allow_insecure is explicitly True).
        """
        if self._config.allow_insecure:
            logger.warning(
                "SSH host key verification DISABLED for %s. "
                "Set allow_insecure=False in SLURMConfig for production use.",
                self._config.cluster_host,
            )
            return None

        known_hosts = Path.home() / ".ssh" / "known_hosts"
        if known_hosts.exists():
            return str(known_hosts)

        # Default: let asyncssh use its own defaults (will verify)
        return ()  # type: ignore[return-value]

    async def _submit_to_slurm(
        self,
        work_dir: Path,
        input_file: Path,
        remote_dir: str,
    ) -> str:
        """Submit job to SLURM via sbatch.

        Args:
            work_dir: Local directory with job files
            input_file: Path to main input file
            remote_dir: Remote directory for job

        Returns:
            SLURM job ID

        Raises:
            SLURMSubmissionError: If submission fails
        """
        import shlex

        if self._connection_manager == "asyncssh":
            # Direct asyncssh connection
            import asyncssh

            async with asyncssh.connect(
                host=self._config.cluster_host,
                port=self._config.cluster_port,
                username=self._config.username,
                known_hosts=self._get_known_hosts(),
            ) as conn:
                # Create remote directory
                await conn.run(f"mkdir -p {shlex.quote(remote_dir)}")

                # Transfer files via SFTP
                async with conn.start_sftp_client() as sftp:
                    for local_file in work_dir.iterdir():
                        if local_file.is_file():
                            remote_path = f"{remote_dir}/{local_file.name}"
                            await sftp.put(str(local_file), remote_path)

                # Submit job
                result = await conn.run(
                    f"cd {shlex.quote(remote_dir)} && sbatch job.slurm",
                    check=False,
                )

                if result.exit_status != 0:
                    raise SLURMSubmissionError(
                        f"sbatch failed: {result.stderr}"
                    )

                # Parse job ID from "Submitted batch job 12345"
                slurm_job_id = self._parse_job_id(result.stdout)
                return slurm_job_id

        else:
            # Use TUI connection manager
            async with self._connection_manager.get_connection(1) as conn:
                # Create remote directory
                await conn.run(f"mkdir -p {shlex.quote(remote_dir)}")

                # Transfer files via SFTP
                async with await conn.start_sftp_client() as sftp:
                    for local_file in work_dir.iterdir():
                        if local_file.is_file():
                            remote_path = f"{remote_dir}/{local_file.name}"
                            await sftp.put(str(local_file), remote_path)

                # Submit job
                result = await conn.run(
                    f"cd {shlex.quote(remote_dir)} && sbatch job.slurm",
                    check=False,
                )

                if result.exit_status != 0:
                    raise SLURMSubmissionError(
                        f"sbatch failed: {result.stderr}"
                    )

                slurm_job_id = self._parse_job_id(result.stdout)
                return slurm_job_id

    def _parse_job_id(self, output: str) -> str:
        """Parse SLURM job ID from sbatch output.

        Args:
            output: stdout from sbatch command

        Returns:
            SLURM job ID string

        Raises:
            SLURMSubmissionError: If job ID cannot be parsed
        """
        import re

        # Match "Submitted batch job 12345"
        match = re.search(r"Submitted batch job (\d+)", output)
        if match:
            return match.group(1)

        raise SLURMSubmissionError(
            f"Could not parse job ID from sbatch output: {output}"
        )

    def _generate_input_files(
        self,
        work_dir: Path,
        workflow_type: "WorkflowType",
        structure: Any,
        parameters: Dict[str, Any],
        code: str,
    ) -> Path:
        """Generate DFT input files.

        Args:
            work_dir: Directory to write files
            workflow_type: Type of calculation
            structure: Input structure
            parameters: Calculation parameters
            code: DFT code

        Returns:
            Path to main input file
        """
        # Convert structure to pymatgen if needed
        from pymatgen.core import Structure

        if isinstance(structure, (str, Path)):
            pmg_structure = Structure.from_file(str(structure))
        elif isinstance(structure, Structure):
            pmg_structure = structure
        else:
            raise ValueError(f"Unsupported structure type: {type(structure)}")

        if code == "vasp":
            return self._generate_vasp_inputs(
                work_dir, workflow_type, pmg_structure, parameters
            )
        elif code == "quantum_espresso":
            return self._generate_qe_inputs(
                work_dir, workflow_type, pmg_structure, parameters
            )
        elif code == "crystal23":
            return self._generate_crystal_inputs(
                work_dir, workflow_type, pmg_structure, parameters
            )
        elif code in ("yambo", "yambo_nl"):
            return self._generate_yambo_input(
                work_dir, workflow_type, parameters
            )
        else:
            raise ValueError(f"Unsupported DFT code: {code}")

    def _generate_vasp_inputs(
        self,
        work_dir: Path,
        workflow_type: "WorkflowType",
        structure: Any,
        parameters: Dict[str, Any],
    ) -> Path:
        """Generate VASP input files (INCAR, POSCAR, KPOINTS, POTCAR)."""
        from pymatgen.io.vasp import Incar, Kpoints, Poscar

        # POSCAR
        poscar = Poscar(structure)
        poscar.write_file(work_dir / "POSCAR")

        # INCAR based on workflow type
        incar_dict = {
            "PREC": "Accurate",
            "ENCUT": parameters.get("encut", 520),
            "EDIFF": parameters.get("energy_convergence", 1e-5),
            "ISMEAR": 0,
            "SIGMA": 0.05,
            "LWAVE": True,
            "LCHARG": True,
        }

        if workflow_type.value == "relax":
            incar_dict.update({
                "IBRION": 2,
                "ISIF": 3,
                "NSW": 200,
                "EDIFFG": parameters.get("force_convergence", -0.01),
            })
        elif workflow_type.value == "bands":
            incar_dict.update({
                "ICHARG": 11,
                "LORBIT": 11,
            })

        incar = Incar(incar_dict)
        incar.write_file(work_dir / "INCAR")

        # KPOINTS
        kpoint_density = parameters.get("kpoint_density", 0.04)
        kpoints = Kpoints.automatic_density(structure, kpoint_density * 1000)
        kpoints.write_file(work_dir / "KPOINTS")

        # Note: POTCAR must be provided separately (not generated here)
        # Write a placeholder for the runner to handle
        (work_dir / "POTCAR_NEEDED").write_text(
            "# POTCAR must be generated on the cluster\n"
        )

        return work_dir / "INCAR"

    def _generate_qe_inputs(
        self,
        work_dir: Path,
        workflow_type: "WorkflowType",
        structure: Any,
        parameters: Dict[str, Any],
    ) -> Path:
        """Generate Quantum ESPRESSO input file."""
        from pymatgen.io.pwscf import PWInput

        # Create PWInput
        pseudo_dir = parameters.get("pseudo_dir", "/opt/qe/pseudo")
        pseudopotentials = {}
        for el in structure.composition.elements:
            pseudopotentials[str(el)] = f"{el}.UPF"

        control = {
            "calculation": workflow_type.value if workflow_type.value in ["scf", "relax"] else "scf",
            "pseudo_dir": pseudo_dir,
            "outdir": "./tmp",
            "prefix": "pwscf",
        }

        system = {
            "ecutwfc": parameters.get("ecutwfc", 60),
            "ecutrho": parameters.get("ecutrho", 480),
        }

        electrons = {
            "conv_thr": parameters.get("energy_convergence", 1e-6),
        }

        pwinput = PWInput(
            structure=structure,
            pseudo=pseudopotentials,
            control=control,
            system=system,
            electrons=electrons,
        )

        input_path = work_dir / "pw.in"
        pwinput.write_file(str(input_path))

        return input_path

    def _generate_crystal_inputs(
        self,
        work_dir: Path,
        workflow_type: "WorkflowType",
        structure: Any,
        parameters: Dict[str, Any],
    ) -> Path:
        """Generate CRYSTAL23 input file."""
        # Simple CRYSTAL input generation
        lines = ["CRYSTAL", "0 0 0"]

        # Space group (simplified)
        lines.append("1")  # P1 for simplicity

        # Lattice parameters
        lattice = structure.lattice
        lines.append(
            f"{lattice.a:.6f} {lattice.b:.6f} {lattice.c:.6f} "
            f"{lattice.alpha:.2f} {lattice.beta:.2f} {lattice.gamma:.2f}"
        )

        # Atoms
        lines.append(str(len(structure)))
        for site in structure:
            atomic_number = site.specie.Z
            coords = site.frac_coords
            lines.append(
                f"{atomic_number} {coords[0]:.6f} {coords[1]:.6f} {coords[2]:.6f}"
            )

        # Basis set and options
        lines.extend([
            "END",
            "DFT",
            "PBE",
            "END",
            "SHRINK",
            "8 8",
            "TOLDEE",
            f"{-int(abs(parameters.get('energy_convergence', 1e-7)) >= 1e-7)}",
            "END",
        ])

        input_path = work_dir / "INPUT"
        input_path.write_text("\n".join(lines))

        return input_path

    def _generate_slurm_script(
        self,
        workflow_id: str,
        workflow_type: "WorkflowType",
        code: str,
        resources: Optional["ResourceRequirements"] = None,
    ) -> str:
        """Generate SLURM batch script.

        Args:
            workflow_id: Workflow identifier
            workflow_type: Type of calculation
            code: DFT code
            resources: Resource requirements

        Returns:
            SLURM script content
        """
        # Default resources
        nodes = 1
        ntasks = 40
        cpus_per_task = 1
        time_limit = "24:00:00"
        partition = self._config.default_partition or "compute"
        memory = "376G"
        gpus = 0

        if resources:
            nodes = resources.num_nodes
            ntasks = resources.num_mpi_ranks
            cpus_per_task = resources.num_threads_per_rank
            time_limit = f"{int(resources.walltime_hours):02d}:00:00"
            partition = resources.partition or partition
            memory = f"{int(resources.memory_gb)}G"
            gpus = resources.gpus

        # Build script
        lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name=cm_{workflow_id[:8]}",
            f"#SBATCH --nodes={nodes}",
            f"#SBATCH --ntasks={ntasks}",
            f"#SBATCH --cpus-per-task={cpus_per_task}",
            f"#SBATCH --time={time_limit}",
            f"#SBATCH --partition={partition}",
            f"#SBATCH --mem={memory}",
            "#SBATCH --output=slurm-%j.out",
            "#SBATCH --error=slurm-%j.err",
        ]

        if gpus > 0:
            lines.append(f"#SBATCH --gres=gpu:{gpus}")

        if self._config.default_account:
            lines.append(f"#SBATCH --account={self._config.default_account}")

        lines.append("")
        lines.append("# Environment setup")

        # Code-specific setup and execution
        if code == "vasp":
            lines.extend([
                "module load intel/2024.2",
                "module load vasp/6.4.3",
                "",
                "# Generate POTCAR if needed",
                "if [ -f POTCAR_NEEDED ]; then",
                "    /opt/vasp/scripts/generate_potcar.sh",
                "fi",
                "",
                "# Run VASP",
                "srun vasp_std",
            ])
        elif code == "quantum_espresso":
            lines.extend([
                "module load qe/7.3.1",
                "",
                "# Run QE",
                "srun pw.x < pw.in > pw.out",
            ])
        elif code == "crystal23":
            lines.extend([
                "source /opt/crystal23/cry23.bashrc",
                "",
                "# Run CRYSTAL",
                "srun Pcrystal < INPUT > OUTPUT",
            ])
        elif code == "yambo":
            lines.extend(self._generate_yambo_slurm_commands(workflow_type, resources))
        elif code == "yambo_nl":
            lines.extend(self._generate_yambo_nl_slurm_commands(workflow_type, resources))
        else:
            lines.append(f"echo 'Unknown code: {code}'")
            lines.append("exit 1")

        lines.append("")
        lines.append("# Mark completion")
        lines.append("echo 'JOB_COMPLETE' > .job_complete")

        return "\n".join(lines)

    def _generate_yambo_slurm_commands(
        self,
        workflow_type: "WorkflowType",
        resources: Optional["ResourceRequirements"] = None,
    ) -> List[str]:
        """Generate SLURM commands for standard YAMBO calculations.

        Supports GW, BSE, and other many-body perturbation theory calculations.

        Args:
            workflow_type: Type of YAMBO calculation
            resources: Resource requirements

        Returns:
            List of bash commands for SLURM script
        """
        lines = [
            "# Load YAMBO environment",
            "module load nvhpc/24.5",
            "export PATH=/opt/yambo/5.3.0-nvhpc-cuda/bin:$PATH",
            "export LD_LIBRARY_PATH=/opt/yambo/5.3.0-nvhpc-cuda/lib:$LD_LIBRARY_PATH",
            "",
            "# UCX settings for GPU-aware MPI",
            "export UCX_TLS=rc,cuda_copy,cuda_ipc",
            "export UCX_MEMTYPE_CACHE=n",
            "",
        ]

        # Determine yambo executable and input file based on workflow type
        workflow_value = workflow_type.value if hasattr(workflow_type, "value") else str(workflow_type)

        if workflow_value in ("gw", "qp"):
            lines.extend([
                "# GW/QP calculation",
                "mpirun yambo -F yambo.in -J GW",
            ])
        elif workflow_value in ("bse", "optical", "optics"):
            lines.extend([
                "# BSE optical absorption",
                "mpirun yambo -F yambo.in -J BSE",
            ])
        else:
            # Default: run with generic output
            lines.extend([
                "# YAMBO calculation",
                "mpirun yambo -F yambo.in -J yambo_output",
            ])

        return lines

    def _generate_yambo_nl_slurm_commands(
        self,
        workflow_type: "WorkflowType",
        resources: Optional["ResourceRequirements"] = None,
    ) -> List[str]:
        """Generate SLURM commands for YAMBO nonlinear optics (yambo_nl).

        Supports SHG, THG, and other nonlinear optical calculations using
        real-time propagation.

        Args:
            workflow_type: Type of nonlinear calculation (SHG, THG, etc.)
            resources: Resource requirements

        Returns:
            List of bash commands for SLURM script
        """
        lines = [
            "# Load YAMBO environment (GPU-enabled)",
            "module load nvhpc/24.5",
            "export PATH=/opt/yambo/5.3.0-nvhpc-cuda/bin:$PATH",
            "export LD_LIBRARY_PATH=/opt/yambo/5.3.0-nvhpc-cuda/lib:$LD_LIBRARY_PATH",
            "",
            "# UCX settings for GPU-aware MPI",
            "export UCX_TLS=rc,cuda_copy,cuda_ipc",
            "export UCX_MEMTYPE_CACHE=n",
            "",
            "# Optimize for nonlinear optics",
            "export OMP_NUM_THREADS=1",
            "export OMP_STACKSIZE=512M",
            "",
        ]

        # Determine output job name based on workflow type
        workflow_value = workflow_type.value if hasattr(workflow_type, "value") else str(workflow_type)

        if workflow_value in ("shg", "nonlinear"):
            job_name = "SHG"
            description = "Second Harmonic Generation"
        elif workflow_value == "thg":
            job_name = "THG"
            description = "Third Harmonic Generation"
        elif workflow_value == "shift":
            job_name = "SHIFT"
            description = "Shift Current"
        else:
            job_name = "NL"
            description = "Nonlinear Optics"

        lines.extend([
            f"# {description} calculation with yambo_nl",
            "# Note: yambo_nl uses real-time propagation for NLO response",
            f"mpirun yambo_nl -F yambo_nl.in -J {job_name}",
            "",
            "# Copy output files to standard names for parsing",
            f"if [ -d {job_name} ]; then",
            f"    cp -r {job_name}/* ./",
            "fi",
        ])

        return lines

    def _generate_yambo_input(
        self,
        work_dir: Path,
        workflow_type: "WorkflowType",
        parameters: Dict[str, Any],
    ) -> Path:
        """Generate YAMBO nonlinear optics input file.

        Args:
            work_dir: Directory to write input file
            workflow_type: Type of calculation (SHG, THG, etc.)
            parameters: Calculation parameters

        Returns:
            Path to input file
        """
        workflow_value = workflow_type.value if hasattr(workflow_type, "value") else str(workflow_type)

        # Default parameters for SHG
        energy_range = parameters.get("energy_range", (0.5, 3.5))
        energy_steps = parameters.get("energy_steps", 500)
        damping = parameters.get("damping", 0.1)
        response_type = parameters.get("response_type", "SHG")

        # Determine NL_Response based on workflow type
        if workflow_value in ("shg", "nonlinear"):
            nl_response = "SHG"
        elif workflow_value == "thg":
            nl_response = "THG"
        elif workflow_value == "shift":
            nl_response = "SHIFT"
        else:
            nl_response = response_type

        # Build yambo_nl input
        input_lines = [
            "# yambo_nl input for nonlinear optical response",
            "# Generated by CrystalMath SLURMWorkflowRunner",
            "",
            "nonlinear",
            "",
            "# Parallelization strategy",
            'NL_Threads = "e"',
            "",
            f"# Response type: {nl_response}",
            f'NL_Response = "{nl_response}"',
            "",
            "# Time integration parameters",
            "NL_nSteps = 10",
            "NL_ETStpsScale = 1.0",
            'NL_etStps = "0.001 Ha"',
            "",
            "# Damping/broadening",
            'NL_DampMode = "LORENTZIAN"',
            f'NL_Damping = "{damping} eV"',
            "",
            "# Long-range correction (0 for IPA)",
            "NL_LRC_alpha = 0.0",
            "",
            "# Energy range for response spectrum",
            f'NL_EnRange = "{energy_range[0]} {energy_range[1]} eV"',
            f"NL_EnSteps = {energy_steps}",
        ]

        input_path = work_dir / "yambo_nl.in"
        input_path.write_text("\n".join(input_lines))

        return input_path

    async def submit_composite_async(
        self,
        steps: Sequence["WorkflowStep"],
        structure: Any,
        **kwargs: Any,
    ) -> "WorkflowResult":
        """
        Submit a composite multi-step workflow (async).

        Creates a SLURM job array or dependent jobs for multi-step workflows.

        Args:
            steps: Sequence of workflow steps
            structure: Initial input structure
            **kwargs: Global options

        Returns:
            WorkflowResult with workflow_id
        """
        from crystalmath.protocols import WorkflowResult

        workflow_id = str(uuid.uuid4())

        logger.info(
            f"Submitting composite workflow [{workflow_id[:8]}...] "
            f"with {len(steps)} steps"
        )

        # For now, submit first step and chain dependencies
        # Full implementation would use job arrays or afterok dependencies

        if not steps:
            return WorkflowResult(
                success=False,
                workflow_id=workflow_id,
                errors=["No workflow steps provided"],
            )

        # Submit first step
        first_step = steps[0]
        result = await self.submit_async(
            workflow_type=first_step.workflow_type,
            structure=structure,
            parameters=first_step.parameters,
            code=first_step.code,
            resources=first_step.resources,
            **kwargs,
        )

        # Store remaining steps for later execution
        if result.success and len(steps) > 1:
            result.metadata["pending_steps"] = [
                {
                    "name": s.name,
                    "workflow_type": s.workflow_type.value,
                    "code": s.code,
                }
                for s in steps[1:]
            ]

        return result

    def submit_composite(
        self,
        steps: Sequence["WorkflowStep"],
        structure: Any,
        **kwargs: Any,
    ) -> "WorkflowResult":
        """Sync entry point for submit_composite. Use submit_composite_async() in async contexts."""
        return self._run_sync(
            self.submit_composite_async(steps, structure, **kwargs)
        )

    async def get_status_async(self, workflow_id: str) -> "WorkflowState":
        """
        Get current state of a workflow (async).

        Args:
            workflow_id: Workflow identifier

        Returns:
            Current workflow state
        """
        if workflow_id not in self._jobs:
            return "failed"

        job_info = self._jobs[workflow_id]

        # Query SLURM for current state
        try:
            state = await self._get_slurm_status(job_info.slurm_job_id)
            job_info.state = state
        except Exception as e:
            logger.warning(f"Failed to get SLURM status: {e}")

        # Map SLURM state to WorkflowState
        state_map = {
            "PENDING": "submitted",
            "RUNNING": "running",
            "COMPLETED": "completed",
            "FAILED": "failed",
            "CANCELLED": "cancelled",
            "TIMEOUT": "failed",
        }

        return state_map.get(job_info.state, "running")

    def get_status(self, workflow_id: str) -> "WorkflowState":
        """Sync entry point for get_status. Use get_status_async() in async contexts."""
        return self._run_sync(self.get_status_async(workflow_id))

    async def _get_slurm_status(self, slurm_job_id: str) -> str:
        """Get SLURM job state via squeue.

        Args:
            slurm_job_id: SLURM job ID

        Returns:
            SLURM job state string
        """
        await self._ensure_connection()

        cmd = f"squeue -j {slurm_job_id} -h -o '%T' 2>/dev/null || sacct -j {slurm_job_id} -n -o State | head -1"

        if self._connection_manager == "asyncssh":
            import asyncssh

            async with asyncssh.connect(
                host=self._config.cluster_host,
                port=self._config.cluster_port,
                username=self._config.username,
                known_hosts=self._get_known_hosts(),
            ) as conn:
                result = await conn.run(cmd, check=False)
                return result.stdout.strip() or "UNKNOWN"
        else:
            async with self._connection_manager.get_connection(1) as conn:
                result = await conn.run(cmd, check=False)
                return result.stdout.strip() or "UNKNOWN"

    async def get_result_async(self, workflow_id: str) -> "WorkflowResult":
        """
        Get complete result of a finished workflow (async).

        Args:
            workflow_id: Workflow identifier

        Returns:
            WorkflowResult with outputs and metadata
        """
        from crystalmath.protocols import WorkflowResult

        if workflow_id not in self._jobs:
            return WorkflowResult(
                success=False,
                workflow_id=workflow_id,
                errors=["Workflow not found"],
            )

        job_info = self._jobs[workflow_id]

        # Check if complete
        state = await self.get_status_async(workflow_id)
        if state not in ("completed", "failed"):
            return WorkflowResult(
                success=True,
                workflow_id=workflow_id,
                outputs={},
                metadata={
                    "status": state,
                    "slurm_job_id": job_info.slurm_job_id,
                },
            )

        # Retrieve results
        try:
            outputs = await self._retrieve_results(job_info)
            job_info.outputs = outputs
            job_info.completed_at = datetime.now()

            return WorkflowResult(
                success=state == "completed",
                workflow_id=workflow_id,
                outputs=outputs,
                errors=job_info.errors,
                started_at=job_info.submitted_at,
                completed_at=job_info.completed_at,
            )

        except Exception as e:
            logger.error(f"Failed to retrieve results: {e}")
            return WorkflowResult(
                success=False,
                workflow_id=workflow_id,
                errors=[str(e)],
            )

    def get_result(self, workflow_id: str) -> "WorkflowResult":
        """Sync entry point for get_result. Use get_result_async() in async contexts."""
        return self._run_sync(self.get_result_async(workflow_id))

    async def _retrieve_results(self, job_info: SLURMJobInfo) -> Dict[str, Any]:
        """Retrieve results from completed job.

        Args:
            job_info: Job tracking information

        Returns:
            Dictionary of outputs
        """
        await self._ensure_connection()

        outputs: Dict[str, Any] = {}

        # Download key output files based on code
        if job_info.code == "vasp":
            files_to_get = ["OUTCAR", "vasprun.xml", "CONTCAR"]
        elif job_info.code == "quantum_espresso":
            files_to_get = ["pw.out"]
        elif job_info.code == "crystal23":
            files_to_get = ["OUTPUT", "fort.9"]
        elif job_info.code in ("yambo", "yambo_nl"):
            # YAMBO output files for nonlinear optics
            files_to_get = [
                "o-SHG.YPP-SHG_x",  # χ²_xxx component
                "o-SHG.YPP-SHG_y",  # χ²_yyy component
                "r_setup",          # Setup report
                "l_setup",          # Setup log
                "o-SHG.YPP-SHG_z",  # χ²_zzz component (if present)
            ]
        else:
            files_to_get = []

        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = Path(tmpdir)

            if self._connection_manager == "asyncssh":
                import asyncssh

                async with asyncssh.connect(
                    host=self._config.cluster_host,
                    port=self._config.cluster_port,
                    username=self._config.username,
                    known_hosts=self._get_known_hosts(),
                ) as conn:
                    async with conn.start_sftp_client() as sftp:
                        for filename in files_to_get:
                            remote_path = f"{job_info.remote_dir}/{filename}"
                            local_path = local_dir / filename
                            try:
                                await sftp.get(remote_path, str(local_path))
                                outputs[f"file_{filename}"] = str(local_path)
                            except Exception:
                                pass  # File may not exist
            else:
                async with self._connection_manager.get_connection(1) as conn:
                    async with await conn.start_sftp_client() as sftp:
                        for filename in files_to_get:
                            remote_path = f"{job_info.remote_dir}/{filename}"
                            local_path = local_dir / filename
                            try:
                                await sftp.get(remote_path, str(local_path))
                                outputs[f"file_{filename}"] = str(local_path)
                            except Exception:
                                pass

            # Parse outputs (code-specific)
            if job_info.code == "vasp" and (local_dir / "vasprun.xml").exists():
                try:
                    from pymatgen.io.vasp import Vasprun

                    vasprun = Vasprun(str(local_dir / "vasprun.xml"))
                    outputs["energy"] = vasprun.final_energy
                    outputs["band_gap"] = vasprun.get_band_structure().get_band_gap()
                except Exception as e:
                    logger.warning(f"Failed to parse VASP results: {e}")

            # Parse YAMBO SHG output files
            if job_info.code in ("yambo", "yambo_nl"):
                outputs.update(self._parse_yambo_shg_output(local_dir))

        return outputs

    def _parse_yambo_shg_output(self, output_dir: Path) -> Dict[str, Any]:
        """Parse YAMBO SHG output files.

        Args:
            output_dir: Directory containing output files

        Returns:
            Dictionary with parsed χ² susceptibility data
        """
        import math

        results: Dict[str, Any] = {}

        # Parse each polarization component
        for component in ["x", "y", "z"]:
            filename = f"o-SHG.YPP-SHG_{component}"
            filepath = output_dir / filename

            if filepath.exists():
                try:
                    # Read and parse the file manually (no numpy dependency)
                    lines = filepath.read_text().strip().split("\n")
                    data_lines = [
                        line for line in lines if line.strip() and not line.startswith("#")
                    ]

                    if not data_lines:
                        continue

                    energies = []
                    real_parts = []
                    imag_parts = []
                    abs_parts = []

                    for line in data_lines:
                        parts = line.split()
                        if len(parts) >= 3:
                            energies.append(float(parts[0]))
                            real_parts.append(float(parts[1]))
                            imag_parts.append(float(parts[2]))
                            if len(parts) >= 4:
                                abs_parts.append(float(parts[3]))

                    if energies:
                        results[f"chi2_{component}_energy"] = energies
                        results[f"chi2_{component}_real"] = real_parts
                        results[f"chi2_{component}_imag"] = imag_parts
                        if abs_parts:
                            results[f"chi2_{component}_abs"] = abs_parts

                        # Find peak value (C-exciton resonance)
                        abs_chi = [
                            math.sqrt(r ** 2 + i ** 2)
                            for r, i in zip(real_parts, imag_parts)
                        ]
                        peak_idx = abs_chi.index(max(abs_chi))
                        results[f"chi2_{component}_peak_energy"] = energies[peak_idx]
                        results[f"chi2_{component}_peak_value"] = abs_chi[peak_idx]

                        logger.info(
                            f"Parsed χ²_{component}: peak at "
                            f"{results[f'chi2_{component}_peak_energy']:.3f} eV"
                        )

                except Exception as e:
                    logger.warning(f"Failed to parse {filename}: {e}")

        return results

    async def cancel_async(self, workflow_id: str) -> bool:
        """
        Cancel a running workflow (async).

        Args:
            workflow_id: Workflow identifier

        Returns:
            True if cancellation succeeded
        """
        if workflow_id not in self._jobs:
            return False

        job_info = self._jobs[workflow_id]

        try:
            await self._cancel_slurm_job(job_info.slurm_job_id)
            job_info.state = "CANCELLED"
            return True

        except Exception as e:
            logger.error(f"Failed to cancel job: {e}")
            return False

    def cancel(self, workflow_id: str) -> bool:
        """Sync entry point for cancel. Use cancel_async() in async contexts."""
        return self._run_sync(self.cancel_async(workflow_id))

    async def _cancel_slurm_job(self, slurm_job_id: str) -> None:
        """Cancel SLURM job via scancel."""
        await self._ensure_connection()

        cmd = f"scancel {slurm_job_id}"

        if self._connection_manager == "asyncssh":
            import asyncssh

            async with asyncssh.connect(
                host=self._config.cluster_host,
                port=self._config.cluster_port,
                username=self._config.username,
                known_hosts=self._get_known_hosts(),
            ) as conn:
                await conn.run(cmd, check=False)
        else:
            async with self._connection_manager.get_connection(1) as conn:
                await conn.run(cmd, check=False)

    async def list_workflows_async(
        self,
        state: Optional["WorkflowState"] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List workflows with optional state filter (async).

        Args:
            state: Filter by state (None for all)
            limit: Maximum number to return

        Returns:
            List of workflow info dicts
        """
        workflows = []

        for wf_id, job_info in list(self._jobs.items())[:limit]:
            current_state = await self.get_status_async(wf_id)

            if state is None or current_state == state:
                workflows.append({
                    "workflow_id": wf_id,
                    "slurm_job_id": job_info.slurm_job_id,
                    "state": current_state,
                    "code": job_info.code,
                    "submitted_at": (
                        job_info.submitted_at.isoformat()
                        if job_info.submitted_at
                        else None
                    ),
                    "remote_dir": job_info.remote_dir,
                })

        return workflows

    def list_workflows(
        self,
        state: Optional["WorkflowState"] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Sync entry point for list_workflows. Use list_workflows_async() in async contexts."""
        return self._run_sync(self.list_workflows_async(state, limit))


# =============================================================================
# Factory Functions
# =============================================================================


def create_slurm_runner(
    cluster_name: str = "beefcake2",
    default_code: str = "vasp",
) -> SLURMWorkflowRunner:
    """Create a SLURMWorkflowRunner for a named cluster.

    Args:
        cluster_name: Name of cluster profile
        default_code: Default DFT code

    Returns:
        Configured SLURMWorkflowRunner
    """
    from crystalmath.high_level.clusters import get_cluster_profile

    profile = get_cluster_profile(cluster_name)
    return SLURMWorkflowRunner.from_cluster_profile(
        profile=profile,
        default_code=default_code,
    )


# =============================================================================
# Module Exports
# =============================================================================


__all__ = [
    # Exceptions
    "SLURMWorkflowError",
    "SLURMConnectionError",
    "SLURMSubmissionError",
    "SLURMStatusError",
    "SLURMResultError",
    # Configuration
    "SLURMConfig",
    "SLURMJobInfo",
    # Runner
    "SLURMWorkflowRunner",
    # Factory
    "create_slurm_runner",
]
