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
import json
import logging
import math
import os
import shlex
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
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
    key_file: Path | None = None
    remote_scratch: str = "/scratch/crystalmath"
    poll_interval_seconds: int = 30
    max_concurrent_jobs: int = 10
    default_partition: str | None = None
    default_account: str | None = None
    default_qos: str | None = None
    allow_insecure: bool = False  # Disable SSH host key verification (opt-in)

    def __post_init__(self) -> None:
        # Never allow host-key verification to be disabled in a production
        # environment, regardless of how the config was constructed.
        if self.allow_insecure and os.getenv("CRYSTALMATH_ENV", "").lower() == "production":
            raise ValueError(
                "allow_insecure=True (SSH host-key verification disabled) is refused "
                "when CRYSTALMATH_ENV=production. Add the host key to known_hosts instead."
            )

    @classmethod
    def from_cluster_profile(cls, profile: ClusterProfile) -> SLURMConfig:
        """Create SLURMConfig from a ClusterProfile.

        Args:
            profile: ClusterProfile with cluster details

        Returns:
            SLURMConfig with settings from profile
        """
        # ClusterProfile has ssh_host and ssh_user directly
        if not profile.ssh_host:
            raise ValueError(f"ClusterProfile '{profile.name}' has no ssh_host configured")

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
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    # datetime fields that must be (de)serialized to/from ISO-8601 strings.
    _DATETIME_FIELDS = ("submitted_at", "started_at", "completed_at")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (datetimes -> ISO-8601 strings)."""
        data: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            data[f.name] = value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SLURMJobInfo:
        """Deserialize from a dict produced by :meth:`to_dict`.

        Unknown keys are ignored and missing keys fall back to dataclass
        defaults so the format can evolve without breaking older state files.
        ISO-8601 strings in datetime fields are parsed back to ``datetime``.
        """
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {k: v for k, v in data.items() if k in known}
        for name in cls._DATETIME_FIELDS:
            raw = kwargs.get(name)
            if isinstance(raw, str):
                try:
                    kwargs[name] = datetime.fromisoformat(raw)
                except ValueError:
                    kwargs[name] = None
        return cls(**kwargs)


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
        state_file: str | Path | None = None,
    ) -> None:
        """Initialize SLURM workflow runner.

        Args:
            config: SLURM configuration
            default_code: Default DFT code to use (vasp, quantum_espresso, etc.)
            state_file: Optional path to the JSON file used to persist the
                ``_jobs`` map across server restarts. When ``None`` a stable
                per-user default is derived (see :meth:`_default_state_file`).
                Pass an explicit path (e.g. ``tmp_path / "jobs.json"``) in tests.
        """
        self._config = config
        self._default_code = default_code
        self._is_available: bool | None = None

        # Track submitted jobs: workflow_id -> SLURMJobInfo
        self._jobs: dict[str, SLURMJobInfo] = {}

        # Resolve the persistence location. This must never fail construction.
        self._state_file: Path = (
            Path(state_file).expanduser() if state_file is not None else self._default_state_file()
        )

        # Connection manager (lazy loaded)
        self._connection_manager: Any | None = None
        self._slurm_runner: Any | None = None

        # Reload any previously-persisted in-progress jobs so that
        # get_status/get_result/cancel keep working across a server restart.
        self._load_state()

        logger.info(
            f"Initialized SLURMWorkflowRunner for {config.cluster_host}, "
            f"default_code={default_code}, state_file={self._state_file} "
            f"({len(self._jobs)} job(s) reloaded)"
        )

    @classmethod
    def from_cluster_profile(
        cls,
        profile: ClusterProfile,
        default_code: str = "vasp",
        state_file: str | Path | None = None,
    ) -> SLURMWorkflowRunner:
        """Create SLURMWorkflowRunner from a ClusterProfile.

        Args:
            profile: ClusterProfile with cluster configuration
            default_code: Default DFT code
            state_file: Optional override for the persisted job state file.

        Returns:
            Configured SLURMWorkflowRunner
        """
        config = SLURMConfig.from_cluster_profile(profile)
        return cls(config=config, default_code=default_code, state_file=state_file)

    # =========================================================================
    # Job-state persistence (survives an IPC-server restart)
    # =========================================================================

    def _default_state_file(self) -> Path:
        """Derive a stable default location for the persisted job state file.

        Preference order:
          1. ``$CRYSTALMATH_SLURM_STATE_FILE`` (explicit operator override).
          2. ``$CRYSTALMATH_STATE_DIR/slurm_jobs.json`` if that env var is set.
          3. An XDG-style per-user data dir:
             ``$XDG_DATA_HOME/crystalmath/slurm_jobs.json`` or
             ``~/.local/share/crystalmath/slurm_jobs.json``.

        The path is namespaced by ``cluster_host`` so multiple runners pointed
        at different clusters do not clobber each other's state.
        """
        override = os.getenv("CRYSTALMATH_SLURM_STATE_FILE")
        if override:
            return Path(override).expanduser()

        state_dir_env = os.getenv("CRYSTALMATH_STATE_DIR")
        if state_dir_env:
            base = Path(state_dir_env).expanduser()
        else:
            xdg = os.getenv("XDG_DATA_HOME")
            base = Path(xdg).expanduser() if xdg else (Path.home() / ".local" / "share")
            base = base / "crystalmath"

        # Namespace by host so distinct clusters keep independent state files.
        safe_host = "".join(
            c if (c.isalnum() or c in "-_.") else "_" for c in self._config.cluster_host
        )
        return base / "slurm_jobs" / f"{safe_host}.json"

    def _load_state(self) -> None:
        """Reload persisted jobs into ``self._jobs``.

        Defensive by design: a missing or corrupt state file must never crash
        construction. On any error we log and start with an empty job map.
        """
        path = self._state_file
        try:
            if not path.exists():
                return
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            data = json.loads(raw)
        except (OSError, ValueError) as e:
            logger.warning(
                "Could not read SLURM state file %s (%s); starting with no tracked jobs.",
                path,
                e,
            )
            return

        records = data.get("jobs") if isinstance(data, dict) else data
        if not isinstance(records, list):
            logger.warning("SLURM state file %s has unexpected structure; ignoring.", path)
            return

        reloaded = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                job = SLURMJobInfo.from_dict(record)
            except (TypeError, ValueError) as e:
                logger.warning("Skipping malformed SLURM job record (%s): %r", e, record)
                continue
            if not job.workflow_id:
                continue
            self._jobs[job.workflow_id] = job
            reloaded += 1

        if reloaded:
            logger.info("Reloaded %d SLURM job(s) from %s", reloaded, path)

    def _save_state(self) -> None:
        """Persist the current ``_jobs`` map to the JSON state file.

        Writes atomically (temp file + ``os.replace``) so a crash mid-write
        cannot corrupt the existing state. Failures are logged but never
        propagated — persistence is best-effort and must not break a live
        submit/status/cancel call.
        """
        path = self._state_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "cluster_host": self._config.cluster_host,
                "jobs": [job.to_dict() for job in self._jobs.values()],
            }
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            # default=str so a non-JSON-serializable value in job.outputs (e.g. a
            # numpy scalar from result parsing) degrades to a string instead of
            # raising — this runs inside get_result_async's try-block, where an
            # uncaught error would wrongly flip a successful result to failed.
            tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError) as e:
            logger.warning("Failed to persist SLURM state to %s: %s", path, e)

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
            # The vendored connection manager (ADR-006) needs asyncssh to drive
            # a real SLURM cluster over SSH. The vendored module itself is always
            # importable, so availability hinges on the asyncssh optional extra.
            try:
                import asyncssh  # noqa: F401

                return True
            except ImportError:
                return False

        except Exception as e:
            logger.warning(f"SLURM runner availability check failed: {e}")
            return False

    # =========================================================================
    # WorkflowRunner Protocol Methods
    # =========================================================================

    async def submit_async(
        self,
        workflow_type: WorkflowType,
        structure: Any,
        parameters: dict[str, Any],
        code: DFTCode | None = None,
        resources: ResourceRequirements | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
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
            f"Submitting {workflow_type.value} workflow [{workflow_id[:8]}...] with code={dft_code}"
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
            self._save_state()

            logger.info(f"Submitted SLURM job {slurm_job_id} for workflow {workflow_id[:8]}")

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
        workflow_type: WorkflowType,
        structure: Any,
        parameters: dict[str, Any],
        code: DFTCode | None = None,
        resources: ResourceRequirements | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Sync entry point for submit. Use submit_async() in async contexts."""
        return self._run_sync(
            self.submit_async(workflow_type, structure, parameters, code, resources, **kwargs)
        )

    async def _submit_async(
        self,
        workflow_id: str,
        workflow_type: WorkflowType,
        structure: Any,
        parameters: dict[str, Any],
        code: str,
        resources: ResourceRequirements | None = None,
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
            # Use the vendored connection manager (ADR-006): no dependency on tui/.
            from crystalmath._vendor.core.connection_manager import ConnectionManager

            self._connection_manager = ConnectionManager()

            # Register cluster
            self._connection_manager.register_cluster(
                cluster_id=1,  # Default cluster ID
                host=self._config.cluster_host,
                port=self._config.cluster_port,
                username=self._config.username,
                key_file=(self._config.key_file or Path("~/.ssh/id_ed25519").expanduser()),
            )

            logger.debug(f"Connected to {self._config.cluster_host}")

        except ImportError:
            # Fall back to direct asyncssh
            logger.warning("TUI connection manager not available, using direct asyncssh")
            self._connection_manager = "asyncssh"  # Flag for direct mode

    def _get_known_hosts(self) -> str | tuple[()] | None:
        """Resolve the ``known_hosts`` value for an asyncssh connection.

        asyncssh semantics matter here:
          * ``None``  -> host-key verification is **disabled** (insecure).
          * a path    -> verify against that known_hosts file.
          * ``()``    -> verify, but trust nothing -> fails closed for unknown hosts.

        We therefore only return ``None`` when ``allow_insecure`` is explicitly set
        (and never in production, enforced in ``SLURMConfig.__post_init__``). When no
        ``~/.ssh/known_hosts`` exists we return ``()`` so the connection fails closed
        rather than silently skipping verification.
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

        # Fail closed: no known_hosts file means we cannot verify the host key, so
        # reject rather than connect blindly. Add the host key to ~/.ssh/known_hosts
        # (e.g. `ssh-keyscan`) to enable connections.
        logger.warning(
            "No ~/.ssh/known_hosts file found; SSH connections to %s will fail until "
            "the host key is added (secure fail-closed posture).",
            self._config.cluster_host,
        )
        return ()

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
                    raise SLURMSubmissionError(f"sbatch failed: {result.stderr}")

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
                    raise SLURMSubmissionError(f"sbatch failed: {result.stderr}")

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

        raise SLURMSubmissionError(f"Could not parse job ID from sbatch output: {output}")

    def _generate_input_files(
        self,
        work_dir: Path,
        workflow_type: WorkflowType,
        structure: Any,
        parameters: dict[str, Any],
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

        # Deck generation is a first-class seam (crystalmath.decks): one adapter
        # per DFT code produces an InputDeck, which stage() writes (assembling the
        # VASP POTCAR from VASP_PP_PATH, fail-fast). See crystalmath-pvo.
        from crystalmath.decks import DeckStagingError, get_deck_generator, stage

        try:
            generator = get_deck_generator(code)
        except ValueError as exc:
            raise ValueError(f"Unsupported DFT code: {code}") from exc

        deck = generator.generate(pmg_structure, workflow_type, parameters)
        try:
            stage(deck, work_dir)
        except DeckStagingError as exc:
            raise SLURMWorkflowError(str(exc)) from exc

        primary = next(iter(deck.files), None)
        return work_dir / primary if primary else work_dir

    def _generate_slurm_script(
        self,
        workflow_id: str,
        workflow_type: WorkflowType,
        code: str,
        resources: ResourceRequirements | None = None,
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
            lines.extend(
                [
                    "module load intel/2024.2",
                    "module load vasp/6.4.3",
                    "",
                    "# POTCAR is staged locally with the other inputs; verify it",
                    "# exists before launching VASP (VASP aborts without it).",
                    "if [ ! -s POTCAR ]; then",
                    '    echo "ERROR: POTCAR missing or empty. It must be staged'
                    ' with the job inputs (VASP_PP_PATH on the submit host)." >&2',
                    "    exit 1",
                    "fi",
                    "",
                    "# Run VASP",
                    "srun vasp_std",
                ]
            )
        elif code == "quantum_espresso":
            lines.extend(
                [
                    "module load qe/7.3.1",
                    "",
                    "# Run QE",
                    "srun pw.x < pw.in > pw.out",
                ]
            )
        elif code == "crystal23":
            lines.extend(
                [
                    "source /opt/crystal23/cry23.bashrc",
                    "",
                    "# Run CRYSTAL",
                    "srun Pcrystal < INPUT > OUTPUT",
                ]
            )
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
        workflow_type: WorkflowType,
        resources: ResourceRequirements | None = None,
    ) -> list[str]:
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
        workflow_value = (
            workflow_type.value if hasattr(workflow_type, "value") else str(workflow_type)
        )

        if workflow_value in ("gw", "qp"):
            lines.extend(
                [
                    "# GW/QP calculation",
                    "mpirun yambo -F yambo.in -J GW",
                ]
            )
        elif workflow_value in ("bse", "optical", "optics"):
            lines.extend(
                [
                    "# BSE optical absorption",
                    "mpirun yambo -F yambo.in -J BSE",
                ]
            )
        else:
            # Default: run with generic output
            lines.extend(
                [
                    "# YAMBO calculation",
                    "mpirun yambo -F yambo.in -J yambo_output",
                ]
            )

        return lines

    def _generate_yambo_nl_slurm_commands(
        self,
        workflow_type: WorkflowType,
        resources: ResourceRequirements | None = None,
    ) -> list[str]:
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
        workflow_value = (
            workflow_type.value if hasattr(workflow_type, "value") else str(workflow_type)
        )

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

        lines.extend(
            [
                f"# {description} calculation with yambo_nl",
                "# Note: yambo_nl uses real-time propagation for NLO response",
                f"mpirun yambo_nl -F yambo_nl.in -J {job_name}",
                "",
                "# Copy output files to standard names for parsing",
                f"if [ -d {job_name} ]; then",
                f"    cp -r {job_name}/* ./",
                "fi",
            ]
        )

        return lines

    def submit_composite(
        self,
        steps: Sequence[WorkflowStep],
        structure: Any,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Sync entry point for submit_composite. Use submit_composite_async() in async contexts."""
        return self._run_sync(self.submit_composite_async(steps, structure, **kwargs))

    async def get_status_async(self, workflow_id: str) -> WorkflowState:
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
            if state != job_info.state:
                job_info.state = state
                # Persist the observed transition so a restart sees fresh state.
                self._save_state()
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

    def get_status(self, workflow_id: str) -> WorkflowState:
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

        job = shlex.quote(slurm_job_id)
        cmd = f"squeue -j {job} -h -o '%T' 2>/dev/null || sacct -j {job} -n -o State | head -1"

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

    async def get_result_async(self, workflow_id: str) -> WorkflowResult:
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
            # Persist completion metadata (outputs path refs + completed_at).
            self._save_state()

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

    def get_result(self, workflow_id: str) -> WorkflowResult:
        """Sync entry point for get_result. Use get_result_async() in async contexts."""
        return self._run_sync(self.get_result_async(workflow_id))

    async def _retrieve_results(self, job_info: SLURMJobInfo) -> dict[str, Any]:
        """Retrieve results from completed job.

        Args:
            job_info: Job tracking information

        Returns:
            Dictionary of outputs
        """
        await self._ensure_connection()

        outputs: dict[str, Any] = {}

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
                "r_setup",  # Setup report
                "l_setup",  # Setup log
                "o-SHG.YPP-SHG_z",  # χ²_zzz component (if present)
            ]
        else:
            files_to_get = []

        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = Path(tmpdir)

            if self._connection_manager == "asyncssh":
                import asyncssh

                async with (
                    asyncssh.connect(
                        host=self._config.cluster_host,
                        port=self._config.cluster_port,
                        username=self._config.username,
                        known_hosts=self._get_known_hosts(),
                    ) as conn,
                    conn.start_sftp_client() as sftp,
                ):
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

    def _parse_yambo_shg_output(self, output_dir: Path) -> dict[str, Any]:
        """Parse YAMBO SHG output files.

        Args:
            output_dir: Directory containing output files

        Returns:
            Dictionary with parsed χ² susceptibility data
        """

        results: dict[str, Any] = {}

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
                        abs_chi = [math.sqrt(r**2 + i**2) for r, i in zip(real_parts, imag_parts)]
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
            self._save_state()
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

        cmd = f"scancel {shlex.quote(slurm_job_id)}"

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
        state: WorkflowState | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
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
                workflows.append(
                    {
                        "workflow_id": wf_id,
                        "slurm_job_id": job_info.slurm_job_id,
                        "state": current_state,
                        "code": job_info.code,
                        "submitted_at": (
                            job_info.submitted_at.isoformat() if job_info.submitted_at else None
                        ),
                        "remote_dir": job_info.remote_dir,
                    }
                )

        return workflows

    def list_workflows(
        self,
        state: WorkflowState | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
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


def generate_sbatch_script(config_dict: dict, execution_commands: list[str]) -> str:
    """
    Programmatically builds clean, standardized #SBATCH script headers from
    dictionary configurations instead of brittle raw text block formats.
    """
    script_lines = ["#!/bin/bash"]

    # Process standard headers deterministically
    for key, val in config_dict.items():
        normalized_key = key.replace("_", "-")
        script_lines.append(f"#SBATCH --{normalized_key}={val}")

    script_lines.append("")  # Spatial padding
    script_lines.extend(execution_commands)
    return "\n".join(script_lines)
