"""AiiDA workflow launcher - bridges to existing AiiDA workchains.

This module provides a unified interface to launch AiiDA workflows from the
Rust TUI. It wraps the existing workchains in tui/src/aiida/workchains/ and
optionally integrates with aiida-common-workflows for multi-code support.

Available workflows:
- CrystalBaseWorkChain: Self-healing SCF with adaptive error recovery
- CrystalGeometryOptimizationWorkChain: Geometry optimization with restart
- CrystalBandStructureWorkChain: Band structure calculation
- CrystalDOSWorkChain: Density of states calculation
- EquationOfState: EOS via aiida-common-workflows (if available)
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Add legacy TUI to path for workchain imports
_repo_root = Path(__file__).parent.parent.parent.parent
_tui_path = _repo_root / "tui" / "src"
if str(_tui_path) not in sys.path:
    sys.path.insert(0, str(_tui_path))


class WorkflowType(str, Enum):
    """Available workflow types."""

    SCF = "scf"  # CrystalBaseWorkChain
    GEOMETRY_OPTIMIZATION = "geometry_optimization"
    BAND_STRUCTURE = "band_structure"
    DOS = "dos"
    EOS = "eos"  # Equation of state


@dataclass
class WorkflowLaunchResult:
    """Result from launching a workflow."""

    success: bool
    workflow_pk: int | None = None
    workflow_uuid: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "success": self.success,
            "workflow_pk": self.workflow_pk,
            "workflow_uuid": self.workflow_uuid,
            "error_message": self.error_message,
        }


def check_aiida_available() -> tuple[bool, str]:
    """Check if AiiDA is available and configured.

    Returns:
        Tuple of (available, reason)
    """
    try:
        from aiida import load_profile, orm  # noqa: F401 - orm imported to verify availability

        # Try to load default profile
        try:
            load_profile()
            return True, "AiiDA profile loaded"
        except Exception as e:
            return False, f"Failed to load AiiDA profile: {e}"
    except ImportError:
        return False, "AiiDA not installed"


def check_common_workflows_available() -> tuple[bool, str]:
    """Check if aiida-common-workflows is available.

    Returns:
        Tuple of (available, reason)
    """
    try:
        from aiida_common_workflows.plugins import WorkflowFactory  # noqa: F401

        return True, "aiida-common-workflows available"
    except ImportError:
        return False, "aiida-common-workflows not installed"


def get_available_workflows() -> dict[str, dict[str, Any]]:
    """Get list of available workflows and their status.

    Returns:
        Dict mapping workflow type to availability info
    """
    aiida_ok, aiida_reason = check_aiida_available()
    acwf_ok, acwf_reason = check_common_workflows_available()

    workflows = {
        "scf": {
            "available": aiida_ok,
            "name": "SCF Calculation",
            "description": "Self-healing SCF with adaptive error recovery",
            "workchain": "CrystalBaseWorkChain",
            "reason": aiida_reason if not aiida_ok else None,
        },
        "geometry_optimization": {
            "available": aiida_ok,
            "name": "Geometry Optimization",
            "description": "Geometry optimization with restart capability",
            "workchain": "CrystalGeometryOptimizationWorkChain",
            "reason": aiida_reason if not aiida_ok else None,
        },
        "band_structure": {
            "available": aiida_ok,
            "name": "Band Structure",
            "description": "Electronic band structure along k-path",
            "workchain": "CrystalBandStructureWorkChain",
            "reason": aiida_reason if not aiida_ok else None,
        },
        "dos": {
            "available": aiida_ok,
            "name": "Density of States",
            "description": "Electronic density of states",
            "workchain": "CrystalDOSWorkChain",
            "reason": aiida_reason if not aiida_ok else None,
        },
        "eos": {
            "available": acwf_ok,
            "name": "Equation of State",
            "description": "Volume scaling for bulk modulus",
            "workchain": "common_workflows.eos",
            "reason": acwf_reason if not acwf_ok else None,
        },
    }

    return workflows


def launch_geometry_optimization(
    structure_pk: int,
    code_label: str,
    parameters: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    optimization_mode: str = "fulloptg",
    max_iterations: int = 10,
    force_threshold: float = 0.00045,
    restart_pk: int | None = None,
) -> WorkflowLaunchResult:
    """Launch a geometry optimization workflow.

    This wraps CrystalGeometryOptimizationWorkChain with automatic restart
    capability if restart_pk is provided.

    Args:
        structure_pk: PK of the input StructureData
        code_label: Label of the CRYSTAL23 code
        parameters: CRYSTAL23 input parameters
        options: Calculation options (resources, walltime)
        optimization_mode: Optimization mode (fulloptg, atomonly, cellonly, itatocel)
        max_iterations: Maximum optimization iterations
        force_threshold: Force convergence threshold (Hartree/Bohr)
        restart_pk: PK of failed/interrupted job to restart from

    Returns:
        WorkflowLaunchResult with workflow PK/UUID or error
    """
    try:
        from aiida import orm
        from aiida.engine import submit
        from aiida.workchains import CrystalGeometryOptimizationWorkChain
    except ImportError as e:
        return WorkflowLaunchResult(
            success=False,
            error_message=f"Import error: {e}",
        )

    try:
        # Load inputs
        structure = orm.load_node(structure_pk)
        code = orm.load_code(code_label)

        # Handle restart case
        if restart_pk:
            restart_node = orm.load_node(restart_pk)

            # Try to get last structure from failed job
            if hasattr(restart_node, "outputs") and hasattr(
                restart_node.outputs, "output_structure"
            ):
                structure = restart_node.outputs.output_structure
                logger.info(f"Restarting from structure of job {restart_pk}")

            # Try to get wavefunction for GUESSP restart
            wavefunction = None
            if hasattr(restart_node, "outputs") and hasattr(restart_node.outputs, "wavefunction"):
                wavefunction = restart_node.outputs.wavefunction

        # Prepare parameters
        params = parameters or {}
        params.setdefault("optgeom", {})

        # Prepare options
        opts = options or {}
        opts.setdefault("resources", {"num_machines": 1, "num_mpiprocs_per_machine": 4})
        opts.setdefault("max_wallclock_seconds", 3600)

        # Build inputs
        inputs = {
            "structure": structure,
            "parameters": orm.Dict(dict=params),
            "code": code,
            "options": orm.Dict(dict=opts),
            "optimization_mode": orm.Str(optimization_mode),
            "max_iterations": orm.Int(max_iterations),
            "force_threshold": orm.Float(force_threshold),
        }

        # Add wavefunction for restart if available
        if restart_pk and wavefunction:
            # Need to modify parameters to use GUESSP
            params.setdefault("scf", {})
            params["scf"]["guessp"] = True
            inputs["parameters"] = orm.Dict(dict=params)
            # Note: The workchain would need to accept wavefunction input

        # Submit workflow
        node = submit(CrystalGeometryOptimizationWorkChain, **inputs)

        return WorkflowLaunchResult(
            success=True,
            workflow_pk=node.pk,
            workflow_uuid=str(node.uuid),
        )

    except Exception as e:
        logger.exception(f"Failed to launch geometry optimization: {e}")
        return WorkflowLaunchResult(
            success=False,
            error_message=str(e),
        )


def launch_band_structure(
    structure_pk: int | None = None,
    scf_pk: int | None = None,
    code_label: str = "",
    kpoints_distance: float = 0.05,
    options: dict[str, Any] | None = None,
) -> WorkflowLaunchResult:
    """Launch a band structure workflow.

    Args:
        structure_pk: PK of the input StructureData (if no SCF provided)
        scf_pk: PK of completed SCF job (to use wavefunction)
        code_label: Label of the CRYSTAL23 code
        kpoints_distance: K-point spacing in 1/Angstrom
        options: Calculation options

    Returns:
        WorkflowLaunchResult with workflow PK/UUID or error
    """
    try:
        from aiida import orm
        from aiida.engine import submit
        from aiida.workchains import CrystalBandStructureWorkChain
    except ImportError as e:
        return WorkflowLaunchResult(
            success=False,
            error_message=f"Import error: {e}",
        )

    try:
        # Load code
        code = orm.load_code(code_label)

        # Get structure and optional wavefunction
        if scf_pk:
            scf_node = orm.load_node(scf_pk)
            if hasattr(scf_node, "outputs"):
                if hasattr(scf_node.outputs, "output_structure"):
                    structure = scf_node.outputs.output_structure
                else:
                    structure = scf_node.inputs.structure
                if hasattr(scf_node.outputs, "wavefunction"):
                    wavefunction = scf_node.outputs.wavefunction
                else:
                    wavefunction = None
            else:
                return WorkflowLaunchResult(
                    success=False,
                    error_message=f"SCF job {scf_pk} has no outputs",
                )
        elif structure_pk:
            structure = orm.load_node(structure_pk)
            wavefunction = None
        else:
            return WorkflowLaunchResult(
                success=False,
                error_message="Either structure_pk or scf_pk required",
            )

        # Prepare options
        opts = options or {}
        opts.setdefault("resources", {"num_machines": 1, "num_mpiprocs_per_machine": 4})
        opts.setdefault("max_wallclock_seconds", 3600)

        # Build inputs
        inputs = {
            "structure": structure,
            "code": code,
            "kpoints_distance": orm.Float(kpoints_distance),
            "options": orm.Dict(dict=opts),
        }

        if wavefunction:
            inputs["wavefunction"] = wavefunction

        # Submit workflow
        node = submit(CrystalBandStructureWorkChain, **inputs)

        return WorkflowLaunchResult(
            success=True,
            workflow_pk=node.pk,
            workflow_uuid=str(node.uuid),
        )

    except Exception as e:
        logger.exception(f"Failed to launch band structure: {e}")
        return WorkflowLaunchResult(
            success=False,
            error_message=str(e),
        )


def launch_eos(
    structure_pk: int,
    code_label: str,
    scale_factors: list[float] | None = None,
    scale_count: int = 7,
    scale_increment: float = 0.02,
    protocol: str = "moderate",
    options: dict[str, Any] | None = None,
) -> WorkflowLaunchResult:
    """Launch an Equation of State workflow.

    Uses aiida-common-workflows if available, otherwise falls back to
    our simple EOS workflow.

    Args:
        structure_pk: PK of the input StructureData
        code_label: Label of the code to use
        scale_factors: Explicit volume scale factors
        scale_count: Number of points (if scale_factors not provided)
        scale_increment: Increment between scales (if scale_factors not provided)
        protocol: Calculation protocol (fast, moderate, precise)
        options: Calculation options

    Returns:
        WorkflowLaunchResult with workflow PK/UUID or error
    """
    # Try aiida-common-workflows first
    acwf_ok, _ = check_common_workflows_available()

    if acwf_ok:
        return _launch_eos_acwf(
            structure_pk=structure_pk,
            code_label=code_label,
            scale_factors=scale_factors,
            scale_count=scale_count,
            scale_increment=scale_increment,
            protocol=protocol,
            options=options,
        )
    else:
        return WorkflowLaunchResult(
            success=False,
            error_message="EOS workflow requires aiida-common-workflows. "
            "Install with: pip install aiida-common-workflows",
        )


def _launch_eos_acwf(
    structure_pk: int,
    code_label: str,
    scale_factors: list[float] | None = None,
    scale_count: int = 7,
    scale_increment: float = 0.02,
    protocol: str = "moderate",
    options: dict[str, Any] | None = None,
) -> WorkflowLaunchResult:
    """Launch EOS using aiida-common-workflows."""
    try:
        from aiida import orm
        from aiida.engine import submit
        from aiida_common_workflows.plugins import WorkflowFactory
    except ImportError as e:
        return WorkflowLaunchResult(
            success=False,
            error_message=f"Import error: {e}",
        )

    try:
        # Load EOS workflow
        EosWorkChain = WorkflowFactory("common_workflows.eos")

        # Load structure and code
        structure = orm.load_node(structure_pk)
        code = orm.load_code(code_label)

        # Prepare options
        opts = options or {}
        opts.setdefault("resources", {"num_machines": 1, "num_mpiprocs_per_machine": 4})
        opts.setdefault("max_wallclock_seconds", 7200)

        # Determine which relax implementation to use based on code
        code_plugin = code.default_calc_job_plugin
        if "quantum_espresso" in code_plugin or "pw" in code_plugin:
            sub_process_class = "common_workflows.relax.quantum_espresso"
        elif "vasp" in code_plugin.lower():
            sub_process_class = "common_workflows.relax.vasp"
        elif "siesta" in code_plugin.lower():
            sub_process_class = "common_workflows.relax.siesta"
        else:
            return WorkflowLaunchResult(
                success=False,
                error_message=f"No common relax workflow for plugin: {code_plugin}. "
                "CRYSTAL23 is not yet supported by aiida-common-workflows.",
            )

        # Build inputs
        inputs = {
            "structure": structure,
            "sub_process_class": sub_process_class,
            "generator_inputs": {
                "engines": {
                    "relax": {
                        "code": code,
                        "options": opts,
                    }
                },
                "protocol": protocol,
                "relax_type": "positions",  # Fixed volume for EOS
            },
        }

        # Set scale factors
        if scale_factors:
            inputs["scale_factors"] = orm.List(list=scale_factors)
        else:
            inputs["scale_count"] = orm.Int(scale_count)
            inputs["scale_increment"] = orm.Float(scale_increment)

        # Submit workflow
        node = submit(EosWorkChain, **inputs)

        return WorkflowLaunchResult(
            success=True,
            workflow_pk=node.pk,
            workflow_uuid=str(node.uuid),
        )

    except Exception as e:
        logger.exception(f"Failed to launch EOS workflow: {e}")
        return WorkflowLaunchResult(
            success=False,
            error_message=str(e),
        )


def get_workflow_status(workflow_pk: int) -> dict[str, Any]:
    """Get status of a running workflow.

    Args:
        workflow_pk: PK of the workflow

    Returns:
        Dict with workflow status information
    """
    try:
        from aiida import orm
    except ImportError:
        return {"error": "AiiDA not available"}

    try:
        node = orm.load_node(workflow_pk)

        result = {
            "pk": node.pk,
            "uuid": str(node.uuid),
            "process_state": str(node.process_state),
            "exit_status": node.exit_status,
            "exit_message": node.exit_message,
            "is_finished": node.is_finished,
            "is_finished_ok": node.is_finished_ok,
            "is_failed": node.is_failed,
        }

        # Add outputs if finished
        if node.is_finished:
            result["outputs"] = {}
            for key in node.outputs:
                output = node.outputs[key]
                if hasattr(output, "value"):
                    result["outputs"][key] = output.value
                elif hasattr(output, "get_dict"):
                    result["outputs"][key] = output.get_dict()
                else:
                    result["outputs"][key] = str(output)

        return result

    except Exception as e:
        return {"error": str(e)}


def extract_restart_geometry(job_pk: int) -> dict[str, Any] | None:
    """Extract last good geometry from a failed/interrupted job.

    This is the key function for geometry optimization restart.

    Args:
        job_pk: PK of the failed job

    Returns:
        Dict with structure info or None if not extractable
    """
    try:
        from aiida import orm
    except ImportError:
        return None

    try:
        node = orm.load_node(job_pk)

        # Try to get output structure
        if hasattr(node, "outputs") and hasattr(node.outputs, "output_structure"):
            structure = node.outputs.output_structure
            return {
                "structure_pk": structure.pk,
                "cell": structure.cell,
                "sites": [
                    {
                        "symbol": site.kind_name,
                        "position": list(site.position),
                    }
                    for site in structure.sites
                ],
                "source": "output_structure",
            }

        # Try to parse from retrieved files
        if hasattr(node, "outputs") and hasattr(node.outputs, "retrieved"):
            retrieved = node.outputs.retrieved
            # Look for .gui or geometry output files
            try:
                # This would require parsing CRYSTAL output for last geometry
                # For now, return None - a future enhancement
                pass
            except Exception:
                pass

        return None

    except Exception as e:
        logger.error(f"Failed to extract restart geometry: {e}")
        return None
