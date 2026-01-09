"""
Extended AiiDA utilities for CrystalMath.

This module provides enhanced AiiDA integration utilities that bridge
existing AiiDA functionality with CrystalMath protocols and atomate2
workflows. It offers:

- Profile management for multi-profile setups
- Simplified QueryBuilder wrappers
- Conversion utilities between AiiDA and atomate2 formats
- Dataclasses for type-safe profile and calculation info

Architecture:
-------------
This module sits between the low-level AiiDA integration in
`tui/src/aiida/` and the high-level protocol interfaces in
`crystalmath.protocols`. It provides the bridge utilities needed
for seamless interoperability.

```
    crystalmath.protocols          crystalmath.integrations
    +------------------+           +----------------------+
    | WorkflowRunner   |           | Atomate2Bridge       |
    | WorkflowResult   |  <-----   | AiiDAProfileManager  |
    +------------------+     |     | AiiDAQueryHelper     |
                             |     +----------------------+
                             |               |
    tui/src/aiida/           |               v
    +------------------+     |     +----------------------+
    | AiiDAQueryAdapter|  ---+     | aiida_enhanced.py    |
    | AiiDASubmitter   |           | (this module)        |
    +------------------+           +----------------------+
```

Example:
--------
>>> from crystalmath.integrations.aiida_enhanced import (
...     AiiDAProfileManager,
...     AiiDAQueryHelper,
... )
>>>
>>> # Check profile availability
>>> if AiiDAProfileManager.profile_exists("production"):
...     AiiDAProfileManager.load_profile("production")
...     info = AiiDAProfileManager.get_profile_info()
...     print(f"Using profile: {info.name}")
>>>
>>> # Query calculations
>>> helper = AiiDAQueryHelper()
>>> calcs = helper.query_calculations(
...     process_label="Crystal23Calculation",
...     state="finished",
...     limit=10,
... )
>>> for calc in calcs:
...     print(f"{calc.pk}: {calc.process_state}")

See Also:
---------
- `crystalmath.backends.aiida` - Backend implementation
- `tui/src/aiida/query_adapter.py` - TUI query adapter
- `crystalmath.protocols` - Protocol definitions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Check if AiiDA is available
AIIDA_AVAILABLE = False
_AIIDA_IMPORT_ERROR: Optional[str] = None

try:
    import aiida  # noqa: F401

    AIIDA_AVAILABLE = True
except ImportError as e:
    _AIIDA_IMPORT_ERROR = str(e)

if TYPE_CHECKING:
    from aiida.engine import ProcessState
    from aiida.orm import Computer, Node, ProcessNode, Profile


# =============================================================================
# Helper function for import checking
# =============================================================================


def _check_aiida_available() -> None:
    """Raise ImportError with helpful message if AiiDA not installed."""
    if not AIIDA_AVAILABLE:
        raise ImportError(
            "AiiDA is not installed. Install with: pip install aiida-core\n"
            f"Original error: {_AIIDA_IMPORT_ERROR}"
        )


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ProfileInfo:
    """
    Information about an AiiDA profile.

    Attributes:
        name: Profile name (e.g., "default", "production")
        storage_backend: Storage backend type (e.g., "psql_dos")
        process_control_backend: Process control backend (e.g., "rabbitmq")
        is_default: Whether this is the default profile
        repository_path: Path to the file repository
        database_uri: Database connection URI (if available)
    """

    name: str
    storage_backend: str
    process_control_backend: str
    is_default: bool
    repository_path: Path
    database_uri: Optional[str] = None

    @classmethod
    def from_aiida_profile(cls, profile: "Profile") -> "ProfileInfo":
        """
        Create ProfileInfo from an AiiDA Profile object.

        Args:
            profile: AiiDA Profile instance

        Returns:
            ProfileInfo with extracted data
        """
        from aiida.manage.configuration import get_config

        config = get_config()

        # Get storage backend info
        storage_config = profile.storage_config
        storage_backend = profile.storage_backend

        # Try to get database URI if available
        database_uri = None
        if "database_uri" in storage_config:
            database_uri = storage_config["database_uri"]
        elif "database_hostname" in storage_config:
            # Construct URI from parts
            host = storage_config.get("database_hostname", "localhost")
            port = storage_config.get("database_port", 5432)
            name = storage_config.get("database_name", profile.name)
            database_uri = f"postgresql://{host}:{port}/{name}"

        # Get repository path
        repo_path = Path(storage_config.get("repository_uri", "").replace("file://", ""))
        if not repo_path.is_absolute():
            repo_path = Path(config.dirpath) / "repository" / profile.name

        return cls(
            name=profile.name,
            storage_backend=storage_backend,
            process_control_backend=profile.process_control_backend or "direct",
            is_default=profile.name == config.default_profile_name,
            repository_path=repo_path,
            database_uri=database_uri,
        )


@dataclass
class CalculationInfo:
    """
    Information about an AiiDA calculation node.

    Attributes:
        pk: Node primary key
        uuid: Node UUID
        process_label: Process class label (e.g., "Crystal23Calculation")
        process_state: Current process state
        exit_status: Exit code (None if not finished)
        ctime: Creation time
        mtime: Last modification time
        computer: Computer label (if applicable)
        description: Node description
        label: Node label
    """

    pk: int
    uuid: str
    process_label: str
    process_state: str
    exit_status: Optional[int]
    ctime: datetime
    mtime: datetime
    computer: Optional[str] = None
    description: Optional[str] = None
    label: Optional[str] = None

    @classmethod
    def from_aiida_node(cls, node: "ProcessNode") -> "CalculationInfo":
        """
        Create CalculationInfo from an AiiDA ProcessNode.

        Args:
            node: AiiDA ProcessNode instance

        Returns:
            CalculationInfo with extracted data
        """
        # Get computer label if available
        computer_label = None
        if hasattr(node, "computer") and node.computer is not None:
            computer_label = node.computer.label

        # Get process state as string
        process_state = "unknown"
        if node.process_state is not None:
            process_state = node.process_state.value

        return cls(
            pk=node.pk,
            uuid=str(node.uuid),
            process_label=node.process_label or "unknown",
            process_state=process_state,
            exit_status=node.exit_status,
            ctime=node.ctime,
            mtime=node.mtime,
            computer=computer_label,
            description=node.description,
            label=node.label,
        )

    def is_finished(self) -> bool:
        """Check if the calculation has finished (successfully or not)."""
        return self.process_state in ("finished", "excepted", "killed")

    def is_successful(self) -> bool:
        """Check if the calculation finished successfully."""
        return self.process_state == "finished" and self.exit_status == 0

    def is_running(self) -> bool:
        """Check if the calculation is currently running."""
        return self.process_state == "running"


# =============================================================================
# AiiDAProfileManager: Profile Management
# =============================================================================


class AiiDAProfileManager:
    """
    Manage AiiDA profiles for CrystalMath.

    This class provides static methods for profile management operations,
    enabling multi-profile setups for development, testing, and production.

    Example:
        >>> AiiDAProfileManager.load_profile("production")
        >>> info = AiiDAProfileManager.get_profile_info()
        >>> print(f"Loaded: {info.name}, default: {info.is_default}")
    """

    _loaded_profile: Optional[str] = None

    @classmethod
    def get_default_profile(cls) -> Optional[str]:
        """
        Get the default AiiDA profile name.

        Returns:
            Default profile name, or None if no profiles configured
        """
        _check_aiida_available()

        from aiida.manage.configuration import get_config

        try:
            config = get_config()
            return config.default_profile_name
        except Exception as e:
            logger.warning(f"Failed to get default profile: {e}")
            return None

    @classmethod
    def profile_exists(cls, name: str) -> bool:
        """
        Check if an AiiDA profile exists.

        Args:
            name: Profile name to check

        Returns:
            True if the profile exists
        """
        _check_aiida_available()

        from aiida.manage.configuration import get_config

        try:
            config = get_config()
            return name in config.profile_names
        except Exception as e:
            logger.warning(f"Failed to check profile existence: {e}")
            return False

    @classmethod
    def list_profiles(cls) -> List[str]:
        """
        List all available AiiDA profiles.

        Returns:
            List of profile names
        """
        _check_aiida_available()

        from aiida.manage.configuration import get_config

        try:
            config = get_config()
            return list(config.profile_names)
        except Exception as e:
            logger.warning(f"Failed to list profiles: {e}")
            return []

    @classmethod
    def load_profile(cls, name: Optional[str] = None) -> None:
        """
        Load an AiiDA profile.

        If name is None, loads the default profile.

        Args:
            name: Profile name to load, or None for default

        Raises:
            ImportError: If AiiDA is not installed
            ValueError: If profile does not exist
            RuntimeError: If profile loading fails
        """
        _check_aiida_available()

        from aiida import load_profile
        from aiida.manage.configuration import get_config

        profile_name = name
        if profile_name is None:
            profile_name = cls.get_default_profile()
            if profile_name is None:
                raise ValueError("No default AiiDA profile configured")

        if not cls.profile_exists(profile_name):
            available = cls.list_profiles()
            raise ValueError(
                f"Profile '{profile_name}' does not exist. "
                f"Available profiles: {available}"
            )

        try:
            load_profile(profile_name)
            cls._loaded_profile = profile_name
            logger.info(f"Loaded AiiDA profile: {profile_name}")
        except Exception as e:
            raise RuntimeError(f"Failed to load profile '{profile_name}': {e}") from e

    @classmethod
    def get_loaded_profile(cls) -> Optional[str]:
        """
        Get the currently loaded profile name.

        Returns:
            Name of loaded profile, or None if no profile loaded
        """
        _check_aiida_available()

        from aiida.manage.configuration import get_profile

        try:
            profile = get_profile()
            return profile.name if profile else None
        except Exception:
            return cls._loaded_profile

    @classmethod
    def get_profile_info(cls, name: Optional[str] = None) -> ProfileInfo:
        """
        Get information about an AiiDA profile.

        Args:
            name: Profile name, or None for the currently loaded profile

        Returns:
            ProfileInfo with profile details

        Raises:
            ValueError: If profile does not exist or no profile is loaded
        """
        _check_aiida_available()

        from aiida.manage.configuration import get_config, get_profile

        config = get_config()

        if name is None:
            profile = get_profile()
            if profile is None:
                raise ValueError("No AiiDA profile is currently loaded")
        else:
            if not cls.profile_exists(name):
                raise ValueError(f"Profile '{name}' does not exist")
            profile = config.get_profile(name)

        return ProfileInfo.from_aiida_profile(profile)

    @classmethod
    def is_profile_loaded(cls) -> bool:
        """
        Check if any AiiDA profile is currently loaded.

        Returns:
            True if a profile is loaded
        """
        _check_aiida_available()

        from aiida.manage.configuration import get_profile

        try:
            return get_profile() is not None
        except Exception:
            return False


# =============================================================================
# AiiDAQueryHelper: Simplified Query Interface
# =============================================================================


class AiiDAQueryHelper:
    """
    Simplified AiiDA QueryBuilder wrapper.

    Provides convenient methods for common query patterns, reducing the
    boilerplate required for AiiDA QueryBuilder usage.

    Example:
        >>> helper = AiiDAQueryHelper()
        >>> # Get recent CRYSTAL calculations
        >>> calcs = helper.query_calculations(
        ...     process_label="Crystal23Calculation",
        ...     state="running",
        ...     limit=50,
        ... )
        >>> # Get specific calculation by PK
        >>> calc = helper.get_calculation_by_pk(123)
        >>> if calc and calc.is_successful():
        ...     outputs = helper.get_outputs(calc.pk)
    """

    # State mapping between common names and AiiDA states
    STATE_MAP = {
        "pending": ["created", "waiting"],
        "queued": ["created", "waiting"],
        "running": ["running"],
        "finished": ["finished"],
        "completed": ["finished"],
        "failed": ["excepted", "killed"],
        "excepted": ["excepted"],
        "killed": ["killed"],
    }

    def __init__(self, ensure_profile: bool = True):
        """
        Initialize the query helper.

        Args:
            ensure_profile: If True, loads default profile if none loaded
        """
        _check_aiida_available()

        if ensure_profile and not AiiDAProfileManager.is_profile_loaded():
            AiiDAProfileManager.load_profile()

    def query_calculations(
        self,
        process_label: Optional[str] = None,
        state: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        computer: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "ctime",
        order_dir: str = "desc",
    ) -> List[CalculationInfo]:
        """
        Query calculations with filters.

        Args:
            process_label: Filter by process label (e.g., "Crystal23Calculation")
            state: Filter by state ("running", "finished", "failed", etc.)
            since: Filter by creation time (after this datetime)
            until: Filter by creation time (before this datetime)
            computer: Filter by computer label
            limit: Maximum number of results
            offset: Number of results to skip
            order_by: Field to order by ("ctime", "mtime", "pk")
            order_dir: Order direction ("asc" or "desc")

        Returns:
            List of CalculationInfo objects
        """
        from aiida.orm import CalcJobNode, QueryBuilder, WorkChainNode

        qb = QueryBuilder()

        # Query both CalcJobs and WorkChains
        qb.append(
            (CalcJobNode, WorkChainNode),
            tag="process",
            project=[
                "id",
                "uuid",
                "attributes.process_label",
                "attributes.process_state",
                "attributes.exit_status",
                "ctime",
                "mtime",
                "label",
                "description",
            ],
        )

        # Apply filters
        filters: Dict[str, Any] = {}

        if process_label:
            filters["attributes.process_label"] = {"==": process_label}

        if state:
            aiida_states = self.STATE_MAP.get(state.lower(), [state])
            filters["attributes.process_state"] = {"in": aiida_states}

        if since:
            filters["ctime"] = {">": since}

        if until:
            if "ctime" in filters:
                filters["ctime"]["<"] = until
            else:
                filters["ctime"] = {"<": until}

        if filters:
            qb.add_filter("process", filters)

        # Apply computer filter (requires join)
        if computer:
            qb.append(
                CalcJobNode,
                filters={"attributes.computer": {"==": computer}},
                with_node="process",
            )

        # Order by
        order_field = order_by if order_by in ("ctime", "mtime", "id") else "ctime"
        qb.order_by({"process": {order_field: order_dir}})

        # Pagination
        if limit:
            qb.limit(limit)
        if offset:
            qb.offset(offset)

        # Build results
        results: List[CalculationInfo] = []
        for row in qb.all():
            pk, uuid, proc_label, proc_state, exit_status, ctime, mtime, label, desc = row

            results.append(
                CalculationInfo(
                    pk=pk,
                    uuid=str(uuid),
                    process_label=proc_label or "unknown",
                    process_state=proc_state or "unknown",
                    exit_status=exit_status,
                    ctime=ctime,
                    mtime=mtime,
                    label=label,
                    description=desc,
                )
            )

        return results

    def get_calculation_by_pk(self, pk: int) -> Optional[CalculationInfo]:
        """
        Get calculation info by primary key.

        Args:
            pk: Node primary key

        Returns:
            CalculationInfo or None if not found
        """
        from aiida.common.exceptions import NotExistent
        from aiida.orm import CalcJobNode, WorkChainNode, load_node

        try:
            node = load_node(pk)

            # Only accept calculation/workflow nodes
            if not isinstance(node, (CalcJobNode, WorkChainNode)):
                logger.warning(f"Node {pk} is not a calculation or workchain")
                return None

            return CalculationInfo.from_aiida_node(node)

        except NotExistent:
            logger.debug(f"Node {pk} does not exist")
            return None
        except Exception as e:
            logger.warning(f"Error loading node {pk}: {e}")
            return None

    def get_calculation_by_uuid(self, uuid: str) -> Optional[CalculationInfo]:
        """
        Get calculation info by UUID.

        Args:
            uuid: Node UUID

        Returns:
            CalculationInfo or None if not found
        """
        from aiida.common.exceptions import NotExistent
        from aiida.orm import CalcJobNode, WorkChainNode, load_node

        try:
            node = load_node(uuid=uuid)

            if not isinstance(node, (CalcJobNode, WorkChainNode)):
                return None

            return CalculationInfo.from_aiida_node(node)

        except NotExistent:
            return None
        except Exception as e:
            logger.warning(f"Error loading node by uuid {uuid}: {e}")
            return None

    def get_outputs(self, pk: int) -> Dict[str, Any]:
        """
        Get outputs of a calculation.

        Args:
            pk: Node primary key

        Returns:
            Dictionary mapping output link labels to values/descriptions
        """
        from aiida.common.exceptions import NotExistent
        from aiida.orm import Dict as AiiDADict
        from aiida.orm import load_node

        try:
            node = load_node(pk)
        except NotExistent:
            logger.warning(f"Node {pk} does not exist")
            return {}
        except Exception as e:
            logger.warning(f"Error loading node {pk}: {e}")
            return {}

        outputs: Dict[str, Any] = {}

        if not hasattr(node, "outputs"):
            return outputs

        for link_label in node.outputs:
            try:
                output_node = getattr(node.outputs, link_label)

                # Extract value based on node type
                if isinstance(output_node, AiiDADict):
                    outputs[link_label] = output_node.get_dict()
                elif hasattr(output_node, "value"):
                    outputs[link_label] = output_node.value
                elif hasattr(output_node, "get_content"):
                    # For file-like nodes, just note the type
                    outputs[link_label] = {
                        "type": output_node.__class__.__name__,
                        "pk": output_node.pk,
                    }
                else:
                    outputs[link_label] = {
                        "type": output_node.__class__.__name__,
                        "pk": output_node.pk,
                    }

            except Exception as e:
                logger.warning(f"Error extracting output '{link_label}': {e}")
                outputs[link_label] = {"error": str(e)}

        return outputs

    def get_inputs(self, pk: int) -> Dict[str, Any]:
        """
        Get inputs of a calculation.

        Args:
            pk: Node primary key

        Returns:
            Dictionary mapping input link labels to values/descriptions
        """
        from aiida.common.exceptions import NotExistent
        from aiida.orm import Dict as AiiDADict
        from aiida.orm import load_node

        try:
            node = load_node(pk)
        except NotExistent:
            return {}
        except Exception as e:
            logger.warning(f"Error loading node {pk}: {e}")
            return {}

        inputs: Dict[str, Any] = {}

        if not hasattr(node, "inputs"):
            return inputs

        for link_label in node.inputs:
            try:
                input_node = getattr(node.inputs, link_label)

                if isinstance(input_node, AiiDADict):
                    inputs[link_label] = input_node.get_dict()
                elif hasattr(input_node, "value"):
                    inputs[link_label] = input_node.value
                else:
                    inputs[link_label] = {
                        "type": input_node.__class__.__name__,
                        "pk": input_node.pk,
                    }

            except Exception as e:
                inputs[link_label] = {"error": str(e)}

        return inputs

    def count_calculations(
        self,
        process_label: Optional[str] = None,
        state: Optional[str] = None,
    ) -> int:
        """
        Count calculations matching filters.

        Args:
            process_label: Filter by process label
            state: Filter by state

        Returns:
            Number of matching calculations
        """
        from aiida.orm import CalcJobNode, QueryBuilder, WorkChainNode

        qb = QueryBuilder()
        qb.append((CalcJobNode, WorkChainNode), tag="process")

        filters: Dict[str, Any] = {}

        if process_label:
            filters["attributes.process_label"] = {"==": process_label}

        if state:
            aiida_states = self.STATE_MAP.get(state.lower(), [state])
            filters["attributes.process_state"] = {"in": aiida_states}

        if filters:
            qb.add_filter("process", filters)

        return qb.count()


# =============================================================================
# Conversion Utilities
# =============================================================================


def aiida_to_atomate2_job(node: "ProcessNode") -> Dict[str, Any]:
    """
    Convert AiiDA calculation to atomate2-compatible job dict.

    This function extracts relevant information from an AiiDA ProcessNode
    and formats it for compatibility with atomate2/jobflow workflows.

    Args:
        node: AiiDA ProcessNode (CalcJobNode or WorkChainNode)

    Returns:
        Dictionary with atomate2-compatible job information:
        - uuid: Job UUID
        - name: Job name/label
        - state: Mapped job state
        - inputs: Input data
        - outputs: Output data
        - metadata: Job metadata

    Example:
        >>> from aiida.orm import load_node
        >>> node = load_node(123)
        >>> job_dict = aiida_to_atomate2_job(node)
        >>> print(job_dict["state"])
    """
    _check_aiida_available()

    from aiida.orm import CalcJobNode, WorkChainNode

    if not isinstance(node, (CalcJobNode, WorkChainNode)):
        raise TypeError(
            f"Expected CalcJobNode or WorkChainNode, got {type(node).__name__}"
        )

    # Map AiiDA process state to jobflow-style state
    state_map = {
        "created": "ready",
        "waiting": "waiting",
        "running": "running",
        "finished": "completed",
        "excepted": "failed",
        "killed": "stopped",
    }

    process_state = node.process_state.value if node.process_state else "unknown"
    job_state = state_map.get(process_state, "unknown")

    # Check if actually failed (finished with non-zero exit)
    if process_state == "finished" and node.exit_status != 0:
        job_state = "failed"

    # Extract inputs
    inputs: Dict[str, Any] = {}
    if hasattr(node, "inputs"):
        for link_label in node.inputs:
            try:
                input_node = getattr(node.inputs, link_label)
                if hasattr(input_node, "get_dict"):
                    inputs[link_label] = input_node.get_dict()
                elif hasattr(input_node, "value"):
                    inputs[link_label] = input_node.value
                else:
                    inputs[link_label] = {"pk": input_node.pk}
            except Exception:
                pass

    # Extract outputs
    outputs: Dict[str, Any] = {}
    if hasattr(node, "outputs"):
        for link_label in node.outputs:
            try:
                output_node = getattr(node.outputs, link_label)
                if hasattr(output_node, "get_dict"):
                    outputs[link_label] = output_node.get_dict()
                elif hasattr(output_node, "value"):
                    outputs[link_label] = output_node.value
                else:
                    outputs[link_label] = {"pk": output_node.pk}
            except Exception:
                pass

    # Build metadata
    metadata: Dict[str, Any] = {
        "aiida_pk": node.pk,
        "aiida_uuid": str(node.uuid),
        "process_label": node.process_label,
        "ctime": node.ctime.isoformat() if node.ctime else None,
        "mtime": node.mtime.isoformat() if node.mtime else None,
    }

    if hasattr(node, "computer") and node.computer:
        metadata["computer"] = node.computer.label

    if node.exit_status is not None:
        metadata["exit_status"] = node.exit_status
    if node.exit_message:
        metadata["exit_message"] = node.exit_message

    return {
        "uuid": str(node.uuid),
        "name": node.label or node.process_label or f"Job {node.pk}",
        "state": job_state,
        "inputs": inputs,
        "outputs": outputs,
        "metadata": metadata,
        "index": 1,  # jobflow uses this for job ordering
        "hosts": [],  # jobflow reference tracking
    }


def atomate2_to_aiida_inputs(job_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert atomate2 job dict to AiiDA input dict.

    This function takes a job dictionary from atomate2/jobflow and
    converts it to a format suitable for AiiDA submission.

    Args:
        job_dict: atomate2/jobflow job dictionary with keys:
            - function: Job function reference
            - args: Positional arguments
            - kwargs: Keyword arguments
            - config: Job configuration
            - metadata: Job metadata

    Returns:
        Dictionary with AiiDA-compatible inputs:
            - code: Code label to use
            - inputs: Namespace inputs for CalcJob/WorkChain
            - metadata: AiiDA metadata dict

    Example:
        >>> job_dict = {"function": "vasp_relax", "kwargs": {...}}
        >>> aiida_inputs = atomate2_to_aiida_inputs(job_dict)
    """
    _check_aiida_available()

    aiida_inputs: Dict[str, Any] = {
        "code": None,
        "inputs": {},
        "metadata": {
            "options": {
                "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1},
                "max_wallclock_seconds": 3600,
            },
        },
    }

    # Extract code from config
    config = job_dict.get("config", {}) or {}
    manager_config = config.get("manager_config", {}) or {}

    if "code" in manager_config:
        aiida_inputs["code"] = manager_config["code"]

    # Extract resources
    resources = config.get("resources", {}) or {}
    if resources:
        aiida_resources: Dict[str, Any] = {}
        if "num_nodes" in resources:
            aiida_resources["num_machines"] = resources["num_nodes"]
        if "num_mpi_ranks" in resources:
            aiida_resources["num_mpiprocs_per_machine"] = (
                resources["num_mpi_ranks"] // resources.get("num_nodes", 1)
            )
        if "walltime_hours" in resources:
            aiida_inputs["metadata"]["options"]["max_wallclock_seconds"] = int(
                resources["walltime_hours"] * 3600
            )
        if aiida_resources:
            aiida_inputs["metadata"]["options"]["resources"] = aiida_resources

    # Extract label/description
    metadata = job_dict.get("metadata", {}) or {}
    if "name" in job_dict:
        aiida_inputs["metadata"]["label"] = job_dict["name"]
    if "description" in metadata:
        aiida_inputs["metadata"]["description"] = metadata["description"]

    # Extract kwargs as inputs
    kwargs = job_dict.get("kwargs", {}) or {}

    # Handle structure specially
    if "structure" in kwargs:
        structure = kwargs.pop("structure")
        # If it's already a dict representation, include it
        if isinstance(structure, dict):
            aiida_inputs["inputs"]["structure_dict"] = structure

    # Handle parameters
    if "parameters" in kwargs:
        aiida_inputs["inputs"]["parameters"] = kwargs.pop("parameters")

    # Include remaining kwargs
    aiida_inputs["inputs"].update(kwargs)

    return aiida_inputs


def workflow_result_from_aiida(node: "ProcessNode") -> "WorkflowResult":
    """
    Create a CrystalMath WorkflowResult from an AiiDA ProcessNode.

    Args:
        node: AiiDA ProcessNode

    Returns:
        WorkflowResult instance
    """
    _check_aiida_available()

    from crystalmath.protocols import WorkflowResult

    # Determine success
    process_state = node.process_state.value if node.process_state else "unknown"
    success = process_state == "finished" and node.exit_status == 0

    # Collect outputs
    outputs: Dict[str, Any] = {}
    if hasattr(node, "outputs"):
        for link_label in node.outputs:
            try:
                output_node = getattr(node.outputs, link_label)
                if hasattr(output_node, "get_dict"):
                    outputs[link_label] = output_node.get_dict()
                elif hasattr(output_node, "value"):
                    outputs[link_label] = output_node.value
            except Exception:
                pass

    # Collect errors
    errors: List[str] = []
    if not success:
        if node.exit_message:
            errors.append(node.exit_message)
        if process_state == "excepted":
            errors.append(f"Process excepted (state: {process_state})")
        elif process_state == "killed":
            errors.append("Process was killed")
        elif node.exit_status and node.exit_status != 0:
            errors.append(f"Exit status: {node.exit_status}")

    # Build metadata
    metadata: Dict[str, Any] = {
        "source": "aiida",
        "aiida_pk": node.pk,
        "aiida_uuid": str(node.uuid),
        "process_label": node.process_label,
        "process_state": process_state,
    }

    if hasattr(node, "computer") and node.computer:
        metadata["computer"] = node.computer.label

    return WorkflowResult(
        success=success,
        workflow_id=str(node.uuid),
        workflow_pk=node.pk,
        outputs=outputs,
        errors=errors,
        metadata=metadata,
        started_at=node.ctime,
        completed_at=node.mtime if node.is_sealed else None,
    )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Availability check
    "AIIDA_AVAILABLE",
    # Data classes
    "ProfileInfo",
    "CalculationInfo",
    # Profile management
    "AiiDAProfileManager",
    # Query utilities
    "AiiDAQueryHelper",
    # Conversion utilities
    "aiida_to_atomate2_job",
    "atomate2_to_aiida_inputs",
    "workflow_result_from_aiida",
]
