"""
CrystalController: Primary Python core API for TUIs and CLI.

This module is the single point of entry for Python consumers. Methods return
native Python objects (Pydantic models, dicts). JSON serialization should be
handled at the Rust/IPC boundary (see python/crystalmath/rust_bridge.py).

Legacy JSON-returning methods are retained for backward compatibility with the
current Rust bridge, but they should be treated as adapters, not core APIs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from crystalmath.models import (
    DftCode,
    JobDetails,
    JobState,
    JobStatus,
    JobSubmission,
    RunnerType,
)

logger = logging.getLogger(__name__)


# ========== Structured Error Response Helpers ==========


def _ok_response(data: Any) -> str:
    """Wrap successful data in structured response."""
    return json.dumps({"ok": True, "data": data})


def _error_response(code: str, message: str) -> str:
    """Create structured error response JSON."""
    return json.dumps(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
            },
        }
    )


# ========== JSON-RPC 2.0 Protocol Support ==========

# JSON-RPC 2.0 error codes (https://www.jsonrpc.org/specification#error_object)
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


def _jsonrpc_error(code: int, message: str, data: Any = None, request_id: Any = None) -> str:
    """Create a JSON-RPC 2.0 error response."""
    error_obj: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error_obj["data"] = data
    return json.dumps({
        "jsonrpc": "2.0",
        "error": error_obj,
        "id": request_id,
    })


def _jsonrpc_result(result: Any, request_id: Any) -> str:
    """Create a JSON-RPC 2.0 success response."""
    return json.dumps({
        "jsonrpc": "2.0",
        "result": result,
        "id": request_id,
    })


class CrystalController:
    """
    Primary Python API facade for TUIs/CLI.

    This class manages backend selection (AiiDA, SQLite, demo) and returns
    native Pydantic models or dicts. JSON serialization is provided by
    legacy adapter methods for Rust compatibility.

    Backend Selection (via create_backend):
    1. AiiDA if use_aiida=True and AiiDA is available
    2. SQLite if db_path is provided
    3. Demo backend as fallback
    """

    def __init__(
        self,
        profile_name: str = "default",
        use_aiida: bool = True,
        db_path: Optional[str] = None,
    ) -> None:
        """
        Initialize the controller.

        Args:
            profile_name: AiiDA profile to load (ignored if use_aiida=False)
            use_aiida: If False, use SQLite fallback instead of AiiDA
            db_path: Path to SQLite database (for fallback mode)
        """
        from crystalmath.backends import create_backend

        self._use_aiida = use_aiida
        self._profile_name = profile_name
        self._db_path = db_path

        # Create backend using factory function
        self._backend = create_backend(
            use_aiida=use_aiida,
            db_path=db_path,
            profile_name=profile_name,
        )

        # Backward compatibility flags
        self._aiida_available = self._backend.name == "aiida"

        # Legacy attributes for advanced methods that need direct DB/AiiDA access
        if self._backend.name == "sqlite" and db_path:
            self._init_sqlite(db_path)
        if self._backend.name == "aiida":
            self._init_aiida(profile_name)

        # JSON-RPC method registry: method_name -> (handler_callable, param_names)
        # This enables the thin IPC pattern where Rust sends generic JSON-RPC
        # requests rather than specific enum variants
        self._rpc_registry: Dict[str, tuple] = self._build_rpc_registry()

    def _init_aiida(self, profile_name: str) -> bool:
        """
        Initialize AiiDA profile.

        Returns:
            True if AiiDA is available and loaded successfully
        """
        try:
            import aiida
            from aiida import orm

            aiida.load_profile(profile_name)
            self._aiida = aiida
            self._orm = orm
            logger.info(f"Loaded AiiDA profile: {profile_name}")
            return True
        except ImportError:
            logger.info("AiiDA not installed - using fallback mode")
            return False
        except Exception as e:
            logger.warning(f"Failed to load AiiDA profile '{profile_name}': {e}")
            return False

    def _init_sqlite(self, db_path: str) -> None:
        """Initialize SQLite database for fallback mode."""
        try:
            # Import TUI database module via uv workspace (crystal-tui package)
            from src.core.database import Database

            self._db = Database(Path(db_path))
            logger.info(f"Loaded SQLite database: {db_path}")
        except Exception as e:
            logger.warning(f"Failed to load SQLite database: {e}")
            self._db = None

    def _build_rpc_registry(self) -> Dict[str, tuple]:
        """Build the JSON-RPC method registry.

        Maps method names to (handler, param_names) tuples. Only methods
        explicitly listed here can be called via JSON-RPC dispatch.

        Security: This whitelist prevents arbitrary method invocation.

        Returns:
            Registry mapping method names to (callable, [param_names]) tuples.
        """
        return {
            # Job operations
            "fetch_jobs": (self.get_jobs_json, ["limit"]),
            "fetch_job_details": (self.get_job_details_json, ["pk"]),
            "submit_job": (self.submit_job_json, ["json_payload"]),
            "cancel_job": (self.cancel_job, ["pk"]),
            "fetch_job_log": (self.get_job_log_json, ["pk", "tail_lines"]),

            # Cluster operations
            "fetch_clusters": (self.get_clusters_json, []),
            "fetch_cluster": (self.get_cluster_json, ["cluster_id"]),
            "create_cluster": (self.create_cluster_json, ["json_payload"]),
            "update_cluster": (self.update_cluster_json, ["cluster_id", "json_payload"]),
            "delete_cluster": (self.delete_cluster, ["cluster_id"]),
            "test_cluster_connection": (self.test_cluster_connection_json, ["cluster_id"]),

            # SLURM operations
            "fetch_slurm_queue": (self.get_slurm_queue_json, ["cluster_id"]),
            "sync_remote_jobs": (self.sync_remote_jobs_json, []),
            "adopt_slurm_job": (self.adopt_slurm_job_json, ["cluster_id", "slurm_job_id"]),
            "cancel_slurm_job": (self.cancel_slurm_job_json, ["cluster_id", "slurm_job_id"]),

            # Materials operations
            "search_materials": (self.search_materials_json, ["formula", "limit"]),
            "fetch_material_details": (self.get_material_details_json, ["mp_id"]),
            "generate_d12": (self.generate_d12_json, ["mp_id", "config_json"]),

            # Template operations
            "list_templates": (self.list_templates_json, []),
            "render_template": (self.render_template_json, ["template_name", "params_json"]),

            # Workflow operations
            "check_workflows_available": (self.check_workflows_available_json, []),
            "create_convergence_study": (self.create_convergence_study_json, ["config_json"]),
            "update_convergence_study": (
                self.update_convergence_study_json,
                ["workflow_json", "updates_json"],
            ),
            "create_band_structure_workflow": (
                self.create_band_structure_workflow_json,
                ["config_json"],
            ),
            "create_phonon_workflow": (self.create_phonon_workflow_json, ["config_json"]),
            "update_phonon_workflow": (
                self.update_phonon_workflow_json,
                ["workflow_json", "updates_json"],
            ),
            "create_eos_workflow": (self.create_eos_workflow_json, ["config_json"]),
            "generate_eos_structures": (
                self.generate_eos_structures_json,
                ["workflow_json", "cell_json", "positions_json", "symbols_json"],
            ),
            "fit_eos": (self.fit_eos_json, ["workflow_json"]),

            # AiiDA operations
            "fetch_aiida_workflows": (self.get_aiida_workflows_json, []),
            "launch_aiida_geopt": (self.launch_aiida_geopt_json, ["config_json"]),
            "launch_aiida_bands": (self.launch_aiida_bands_json, ["config_json"]),
            "fetch_aiida_workflow_status": (
                self.get_aiida_workflow_status_json,
                ["workflow_pk"],
            ),
            "extract_restart_geometry": (self.extract_restart_geometry_json, ["job_pk"]),

            # AI assistant operations
            "check_ai_available": (self.check_ai_available_json, []),
            "ask_assistant": (self.ask_assistant_json, ["message", "context_json"]),
            "analyze_job_error": (self.analyze_job_error_json, ["pk"]),
            "suggest_parameters": (
                self.suggest_parameters_json,
                ["calculation_type", "system_description"],
            ),
            # quacc integration (Phase 2)
            "recipes.list": (self.get_recipes_list, []),
            "clusters.list": (self.get_quacc_clusters_list, []),
            "jobs.list": (self.get_quacc_jobs_list, ["status", "limit"]),
            # VASP input generation (Phase 3)
            "vasp.generate_inputs": (self.generate_vasp_inputs_json, ["config_json"]),
            "vasp.generate_from_mp": (self.generate_vasp_from_mp_json, ["mp_id", "config_json"]),
            "vasp.validate_inputs": (self.validate_vasp_inputs_json, ["inputs_json"]),
            "structures.import_poscar": (self.import_poscar_json, ["poscar_content"]),
            "structures.preview": (self.preview_structure_json, ["source_type", "source_data"]),
        }

    def dispatch(self, request_json: str) -> str:
        """Dispatch a JSON-RPC 2.0 request to the appropriate handler.

        This is the single entry point for the thin IPC bridge pattern.
        Rust sends generic JSON-RPC requests through this method instead
        of calling individual methods directly.

        Protocol: JSON-RPC 2.0 (https://www.jsonrpc.org/specification)
        Request:  {"jsonrpc": "2.0", "method": "...", "params": {...}, "id": ...}
        Response: {"jsonrpc": "2.0", "result": ..., "id": ...}
        Error:    {"jsonrpc": "2.0", "error": {"code": ..., "message": ...}, "id": ...}

        Security: Only methods in _rpc_registry can be called.

        Args:
            request_json: JSON-RPC 2.0 request string.

        Returns:
            JSON-RPC 2.0 response string.
        """
        request_id = None

        try:
            # Parse request
            try:
                request = json.loads(request_json)
            except json.JSONDecodeError as e:
                return _jsonrpc_error(
                    JSONRPC_PARSE_ERROR,
                    f"Parse error: {e}",
                    request_id=request_id,
                )

            # Extract id (may be null or missing for notifications)
            request_id = request.get("id")

            # Validate JSON-RPC version
            if request.get("jsonrpc") != "2.0":
                return _jsonrpc_error(
                    JSONRPC_INVALID_REQUEST,
                    "Invalid Request: missing or invalid 'jsonrpc' field",
                    request_id=request_id,
                )

            # Extract method
            method_name = request.get("method")
            if not method_name or not isinstance(method_name, str):
                return _jsonrpc_error(
                    JSONRPC_INVALID_REQUEST,
                    "Invalid Request: missing or invalid 'method' field",
                    request_id=request_id,
                )

            # Security: Only allow registered methods
            if method_name not in self._rpc_registry:
                return _jsonrpc_error(
                    JSONRPC_METHOD_NOT_FOUND,
                    f"Method not found: {method_name}",
                    request_id=request_id,
                )

            # Get handler and param spec
            handler, param_names = self._rpc_registry[method_name]
            params = request.get("params", {})

            # Build kwargs from params
            if isinstance(params, dict):
                # Named parameters
                kwargs = {}
                for name in param_names:
                    if name in params:
                        kwargs[name] = params[name]
            elif isinstance(params, list):
                # Positional parameters (convert to kwargs)
                kwargs = {}
                for i, name in enumerate(param_names):
                    if i < len(params):
                        kwargs[name] = params[i]
            else:
                kwargs = {}

            # Call the handler
            result = handler(**kwargs)

            # If result is already a JSON string from a *_json method,
            # parse it so we can re-serialize in JSON-RPC envelope
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    # Keep as string if not valid JSON
                    pass

            return _jsonrpc_result(result, request_id)

        except TypeError as e:
            # Usually parameter mismatch
            return _jsonrpc_error(
                JSONRPC_INVALID_PARAMS,
                f"Invalid params: {e}",
                request_id=request_id,
            )
        except Exception as e:
            # Log the full traceback for debugging
            import traceback
            tb = traceback.format_exc()
            logger.error(f"JSON-RPC dispatch error: {e}\n{tb}")

            return _jsonrpc_error(
                JSONRPC_INTERNAL_ERROR,
                f"Internal error: {e}",
                data=tb if logger.isEnabledFor(logging.DEBUG) else None,
                request_id=request_id,
            )

    # ========== Public API Methods (primary Python interface) ==========

    def get_jobs(self, limit: int = 100) -> List[JobStatus]:
        """Get list of jobs as native JobStatus objects."""
        return self._backend.get_jobs(limit)

    def get_job_details(self, pk: int) -> Optional[JobDetails]:
        """Get detailed job info as a JobDetails object (or None if not found)."""
        return self._backend.get_job_details(pk)

    def submit_job(self, submission: JobSubmission) -> int:
        """Submit a new job from a JobSubmission object."""
        return self._backend.submit_job(submission)

    def get_job_log(self, pk: int, tail_lines: int = 100) -> Dict[str, List[str]]:
        """Get job stdout/stderr log as a dict with stdout/stderr arrays."""
        return self._backend.get_job_log(pk, tail_lines)

    # ========== Legacy JSON API (Rust compatibility) ==========

    def get_jobs_json(self, limit: int = 100) -> str:
        """Get list of jobs as JSON string (legacy)."""
        jobs = self.get_jobs(limit)
        return json.dumps([job.model_dump(mode="json") for job in jobs])

    def get_job_details_json(self, pk: int) -> str:
        """Get detailed job info as JSON string (legacy)."""
        details = self.get_job_details(pk)
        if details is None:
            return _error_response("NOT_FOUND", f"Job with pk={pk} not found")
        return _ok_response(details.model_dump(mode="json"))

    def submit_job_json(self, json_payload: str) -> int:
        """Submit a new job from JSON payload (legacy)."""
        try:
            submission = JobSubmission.model_validate_json(json_payload)
            return self.submit_job(submission)
        except Exception as e:
            raise RuntimeError(f"Job submission failed: {e}") from e

    def cancel_job(self, pk: int) -> bool:
        """
        Cancel a running job.

        Args:
            pk: Job primary key

        Returns:
            True if cancellation succeeded
        """
        return self._backend.cancel_job(pk)

    def get_job_log_json(self, pk: int, tail_lines: int = 100) -> str:
        """
        Get job stdout/stderr log as JSON.

        Args:
            pk: Job primary key
            tail_lines: Number of lines from end of log

        Returns:
            JSON object with "stdout" and "stderr" arrays
        """
        logs = self.get_job_log(pk, tail_lines)
        return json.dumps(logs)

    # ========== quacc Integration Methods ==========

    def get_recipes_list(self) -> Dict[str, Any]:
        """Get list of available quacc VASP recipes.

        Returns:
            Dict with recipes list, quacc_version, and error field.
        """
        try:
            from crystalmath.quacc.discovery import discover_vasp_recipes

            recipes = discover_vasp_recipes()

            # Get quacc version if available
            try:
                import quacc
                quacc_version = getattr(quacc, "__version__", "unknown")
            except ImportError:
                quacc_version = None

            return {
                "recipes": recipes,
                "quacc_version": quacc_version,
                "error": None,
            }
        except ImportError as e:
            return {
                "recipes": [],
                "quacc_version": None,
                "error": f"quacc not available: {e}",
            }
        except Exception as e:
            return {
                "recipes": [],
                "quacc_version": None,
                "error": f"Error discovering recipes: {e}",
            }

    def get_quacc_clusters_list(self) -> Dict[str, Any]:
        """Get list of configured quacc clusters and workflow engine status.

        Returns:
            Dict with clusters list and workflow_engine status.
        """
        try:
            from crystalmath.quacc.config import ClusterConfigStore
            from crystalmath.quacc.engines import get_engine_status

            store = ClusterConfigStore()

            return {
                "clusters": store.list_clusters(),
                "workflow_engine": get_engine_status(),
            }
        except ImportError as e:
            return {
                "clusters": [],
                "workflow_engine": {
                    "configured": None,
                    "installed": [],
                    "quacc_installed": False,
                },
            }
        except Exception as e:
            logger.error(f"Error getting quacc clusters: {e}")
            return {
                "clusters": [],
                "workflow_engine": {
                    "configured": None,
                    "installed": [],
                    "quacc_installed": False,
                },
            }

    def get_quacc_jobs_list(
        self, status: Optional[str] = None, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get list of quacc jobs with optional filtering.

        Args:
            status: Optional status filter (e.g., "running", "completed")
            limit: Optional maximum number of jobs to return

        Returns:
            Dict with jobs list and total count.
        """
        try:
            from crystalmath.quacc.store import JobStore

            store = JobStore()
            jobs = store.list_jobs(status=status, limit=limit)

            return {
                "jobs": [job.model_dump() for job in jobs],
                "total": len(jobs),
            }
        except ImportError as e:
            return {
                "jobs": [],
                "total": 0,
            }
        except Exception as e:
            logger.error(f"Error getting quacc jobs: {e}")
            return {
                "jobs": [],
                "total": 0,
            }

    # ========== VASP Input Generation Methods (Phase 3) ==========

    def generate_vasp_inputs_json(self, config_json: str) -> str:
        """Generate VASP input files from structure.

        Args:
            config_json: JSON configuration with:
                - poscar: POSCAR file content (string)
                - preset: "relax", "static", "bands", "dos", "convergence"
                - encut: Optional plane-wave cutoff (eV)
                - kppra: k-points per reciprocal atom (default 1000)
                - incar_overrides: Optional dict of INCAR parameters

        Returns:
            JSON string with POSCAR, INCAR, KPOINTS, and POTCAR symbols.
        """
        try:
            from pymatgen.io.vasp import Poscar

            from crystalmath.vasp import IncarPreset, VaspInputGenerator

            config = json.loads(config_json)
            poscar_str = config.get("poscar", "")
            if not poscar_str:
                return _error_response("VALIDATION_ERROR", "POSCAR content required")

            # Parse POSCAR to get structure
            poscar = Poscar.from_str(poscar_str)
            structure = poscar.structure

            # Get preset
            preset_name = config.get("preset", "static")
            try:
                preset = IncarPreset(preset_name)
            except ValueError:
                preset = IncarPreset.STATIC

            # Generate inputs
            generator = VaspInputGenerator(
                structure,
                preset=preset,
                encut=config.get("encut"),
                kppra=config.get("kppra", 1000),
                **config.get("incar_overrides", {}),
            )
            inputs = generator.generate()

            return _ok_response(inputs.to_dict())

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid config JSON: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"VASP module not available: {e}")
        except Exception as e:
            logger.error(f"VASP input generation failed: {e}")
            return _error_response("GENERATION_ERROR", str(e))

    def generate_vasp_from_mp_json(self, mp_id: str, config_json: str) -> str:
        """Generate VASP inputs directly from Materials Project ID.

        Args:
            mp_id: Materials Project ID (e.g., "mp-149")
            config_json: JSON configuration (same as generate_vasp_inputs_json,
                         but without poscar field)

        Returns:
            JSON string with POSCAR, INCAR, KPOINTS, and POTCAR symbols.
        """
        try:
            from crystalmath.integrations.pymatgen_bridge import structure_from_mp
            from crystalmath.vasp import IncarPreset, VaspInputGenerator

            config = json.loads(config_json) if config_json else {}

            # Fetch structure from Materials Project
            structure = structure_from_mp(mp_id)

            # Get preset
            preset_name = config.get("preset", "static")
            try:
                preset = IncarPreset(preset_name)
            except ValueError:
                preset = IncarPreset.STATIC

            # Generate inputs
            generator = VaspInputGenerator(
                structure,
                preset=preset,
                encut=config.get("encut"),
                kppra=config.get("kppra", 1000),
                **config.get("incar_overrides", {}),
            )
            inputs = generator.generate()

            return _ok_response(inputs.to_dict())

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid config JSON: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Dependencies not available: {e}")
        except Exception as e:
            logger.error(f"VASP generation from MP failed: {e}")
            return _error_response("GENERATION_ERROR", str(e))

    def validate_vasp_inputs_json(self, inputs_json: str) -> str:
        """Validate VASP input files using Pymatgen.

        Args:
            inputs_json: JSON with keys "poscar", "incar", "kpoints".

        Returns:
            JSON with validation results:
            {
                "valid": bool,
                "errors": [{"file": "POSCAR", "message": "..."}],
                "warnings": [{"file": "INCAR", "message": "..."}]
            }
        """
        try:
            from pymatgen.io.vasp import Incar, Kpoints, Poscar

            inputs = json.loads(inputs_json)
            errors = []
            warnings = []

            # POSCAR
            if "poscar" in inputs and inputs["poscar"].strip():
                try:
                    Poscar.from_str(inputs["poscar"])
                except Exception as e:
                    errors.append({"file": "POSCAR", "message": str(e)})

            # INCAR
            if "incar" in inputs and inputs["incar"].strip():
                try:
                    # Pymatgen's Incar validation is lenient, mostly checks parsing
                    Incar.from_string(inputs["incar"])
                except Exception as e:
                    errors.append({"file": "INCAR", "message": str(e)})

            # KPOINTS
            if "kpoints" in inputs and inputs["kpoints"].strip():
                try:
                    Kpoints.from_string(inputs["kpoints"])
                except Exception as e:
                    errors.append({"file": "KPOINTS", "message": str(e)})

            return _ok_response({
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
            })

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid inputs JSON: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"pymatgen not available: {e}")
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return _error_response("VALIDATION_ERROR", str(e))

    def import_poscar_json(self, poscar_content: str) -> str:
        """Import POSCAR and return structure info.

        Args:
            poscar_content: POSCAR file content as string

        Returns:
            JSON with structure metadata (formula, natoms, lattice, species)
        """
        try:
            from pymatgen.io.vasp import Poscar

            poscar = Poscar.from_str(poscar_content)
            structure = poscar.structure

            # Extract metadata
            lattice = structure.lattice
            metadata = {
                "formula": structure.formula,
                "reduced_formula": structure.composition.reduced_formula,
                "num_sites": structure.num_sites,
                "volume": lattice.volume,
                "lattice": {
                    "a": lattice.a,
                    "b": lattice.b,
                    "c": lattice.c,
                    "alpha": lattice.alpha,
                    "beta": lattice.beta,
                    "gamma": lattice.gamma,
                },
                "species": list(dict.fromkeys(str(s) for s in structure.species)),
            }

            return _ok_response(metadata)

        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"pymatgen not available: {e}")
        except Exception as e:
            logger.error(f"POSCAR import failed: {e}")
            return _error_response("PARSE_ERROR", f"Invalid POSCAR: {e}")

    def preview_structure_json(self, source_type: str, source_data: str) -> str:
        """Preview structure from various sources.

        Args:
            source_type: "poscar", "cif", "mp_id"
            source_data: Content or ID depending on source_type

        Returns:
            JSON with structure preview (formula, lattice, atoms, symmetry)
        """
        try:
            from pymatgen.core import Structure

            # Load structure based on source type
            if source_type == "poscar":
                from pymatgen.io.vasp import Poscar

                poscar = Poscar.from_str(source_data)
                structure = poscar.structure
            elif source_type == "cif":
                structure = Structure.from_str(source_data, fmt="cif")
            elif source_type == "mp_id":
                from crystalmath.integrations.pymatgen_bridge import structure_from_mp

                structure = structure_from_mp(source_data)
            else:
                return _error_response(
                    "VALIDATION_ERROR", f"Unknown source_type: {source_type}"
                )

            # Build preview data
            lattice = structure.lattice
            preview = {
                "formula": structure.formula,
                "reduced_formula": structure.composition.reduced_formula,
                "num_sites": structure.num_sites,
                "volume": round(lattice.volume, 3),
                "density": round(structure.density, 3),
                "lattice": {
                    "a": round(lattice.a, 4),
                    "b": round(lattice.b, 4),
                    "c": round(lattice.c, 4),
                    "alpha": round(lattice.alpha, 2),
                    "beta": round(lattice.beta, 2),
                    "gamma": round(lattice.gamma, 2),
                },
                "species": list(dict.fromkeys(str(s) for s in structure.species)),
                "composition": {
                    str(el): int(amt)
                    for el, amt in structure.composition.items()
                },
            }

            # Try to get symmetry info
            try:
                from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

                sga = SpacegroupAnalyzer(structure)
                preview["symmetry"] = {
                    "space_group": sga.get_space_group_symbol(),
                    "space_group_number": sga.get_space_group_number(),
                    "crystal_system": sga.get_crystal_system(),
                    "point_group": sga.get_point_group_symbol(),
                }
            except Exception:
                preview["symmetry"] = None

            return _ok_response(preview)

        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Dependencies not available: {e}")
        except Exception as e:
            logger.error(f"Structure preview failed: {e}")
            return _error_response("PREVIEW_ERROR", str(e))

    # ========== Materials Project API Methods ==========

    def search_materials_json(self, formula: str, limit: int = 20) -> str:
        """
        Search Materials Project for structures by formula.

        This method bridges the async MaterialsService to sync PyO3 calls
        using asyncio.run(). The blocking happens only on the Rust worker
        thread, not the UI thread.

        Args:
            formula: Chemical formula to search (e.g., "MoS2", "LiFePO4")
            limit: Maximum number of results to return

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": [MaterialRecord, ...]}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}
        """
        import asyncio

        async def _run() -> List[Dict[str, Any]]:
            # Lazy import to avoid loading heavy dependencies on startup
            from src.core.materials_api.service import MaterialsService
            from src.core.materials_api.settings import MaterialsSettings

            settings = MaterialsSettings.get_instance()

            if not settings.has_mp_api_key:
                raise ValueError("MP_API_KEY not set. Get your key at materialsproject.org/api")

            async with MaterialsService(settings=settings) as service:
                result = await service.search_by_formula(formula, limit=limit)
                # Convert to JSON-serializable dicts
                return [r.to_dict() for r in result.records]

        try:
            data = asyncio.run(_run())
            return _ok_response(data)
        except ValueError as e:
            return _error_response("CONFIGURATION_ERROR", str(e))
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Materials API not available: {e}")
        except Exception as e:
            logger.error(f"Materials search failed for '{formula}': {e}")
            return _error_response("SEARCH_FAILED", str(e))

    def generate_d12_json(self, mp_id: str, config_json: str) -> str:
        """
        Generate CRYSTAL23 .d12 input file from a Materials Project structure.

        Args:
            mp_id: Materials Project ID (e.g., "mp-2815")
            config_json: JSON string with generation config:
                {
                    "functional": "PBE",
                    "basis_set": "POB-TZVP-REV2",
                    "shrink": [8, 8],
                    "optimize": false
                }

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": "<d12 file content>"}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}
        """
        import asyncio

        async def _run() -> str:
            from src.core.materials_api.service import MaterialsService
            from src.core.materials_api.settings import MaterialsSettings

            settings = MaterialsSettings.get_instance()

            if not settings.has_mp_api_key:
                raise ValueError("MP_API_KEY not set. Get your key at materialsproject.org/api")

            # Parse config
            config = json.loads(config_json) if config_json else {}

            async with MaterialsService(settings=settings) as service:
                return await service.generate_crystal_input(mp_id, config=config)

        try:
            content = asyncio.run(_run())
            return _ok_response(content)
        except ValueError as e:
            return _error_response("CONFIGURATION_ERROR", str(e))
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Materials API not available: {e}")
        except Exception as e:
            logger.error(f"D12 generation failed for '{mp_id}': {e}")
            return _error_response("GENERATION_FAILED", str(e))

    def get_material_details_json(self, mp_id: str) -> str:
        """
        Get detailed information about a specific material.

        Args:
            mp_id: Materials Project ID (e.g., "mp-2815")

        Returns:
            JSON string with material details including structure
        """
        import asyncio

        async def _run() -> Dict[str, Any]:
            from src.core.materials_api.service import MaterialsService
            from src.core.materials_api.settings import MaterialsSettings

            settings = MaterialsSettings.get_instance()

            if not settings.has_mp_api_key:
                raise ValueError("MP_API_KEY not set. Get your key at materialsproject.org/api")

            async with MaterialsService(settings=settings) as service:
                record = await service.get_structure(mp_id)
                return record.to_dict()

        try:
            data = asyncio.run(_run())
            return _ok_response(data)
        except ValueError as e:
            return _error_response("CONFIGURATION_ERROR", str(e))
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Materials API not available: {e}")
        except Exception as e:
            logger.error(f"Get material details failed for '{mp_id}': {e}")
            return _error_response("NOT_FOUND", str(e))

    # ========== SLURM Queue Methods ==========

    def get_slurm_queue_json(self, cluster_id: int = 1) -> str:
        """
        Get SLURM queue status from remote cluster.

        Connects to the specified cluster via SSH and queries squeue
        to get the current job queue status.

        Args:
            cluster_id: Cluster database ID (default: 1)

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": [SlurmQueueEntry, ...]}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}

        Each SlurmQueueEntry contains:
            - job_id: SLURM job ID
            - name: Job name
            - user: Username
            - state: Job state (PENDING, RUNNING, etc.)
            - time: Time used
            - nodes: Number of nodes
            - partition: SLURM partition
        """
        import asyncio

        async def _run() -> List[Dict[str, Any]]:
            from src.core.connection_manager import ConnectionManager, ConnectionConfig
            from src.runners.slurm_runner import SLURMRunner

            # Get cluster config from database
            if not hasattr(self, "_db") or not self._db:
                raise ValueError("Database not available - cannot fetch cluster config")

            cluster = self._db.get_cluster(cluster_id)
            if not cluster:
                raise ValueError(f"Cluster {cluster_id} not found in database")

            # Parse connection config from cluster
            import json as json_module

            conn_config_data = (
                json_module.loads(cluster.connection_config)
                if isinstance(cluster.connection_config, str)
                else cluster.connection_config
            )

            # Create connection config
            # Note: We don't construct ConnectionConfig directly here as register_cluster handles it

            # Create connection manager
            conn_manager = ConnectionManager()

            # Register cluster with proper method
            conn_manager.register_cluster(
                cluster_id=cluster_id,
                host=cluster.hostname,
                port=cluster.port,
                username=cluster.username,
                key_file=Path(conn_config_data.get("key_file", "~/.ssh/id_ed25519")).expanduser(),
                strict_host_key_checking=True,  # Enable security by default
            )

            try:
                # Create SLURM runner and get queue
                runner = SLURMRunner(
                    connection_manager=conn_manager,
                    cluster_id=cluster_id,
                )

                # Use timeout to prevent blocking the bridge thread indefinitely
                try:
                    jobs = await asyncio.wait_for(
                        runner.get_queue_status(user_only=False),
                        timeout=15.0,  # 15 second timeout for HPC environments
                    )
                except asyncio.TimeoutError:
                    raise ValueError("SLURM queue fetch timed out after 15 seconds")

                # Ensure job_id is string for Rust compatibility
                for job in jobs:
                    if "job_id" in job:
                        job["job_id"] = str(job["job_id"])

                return jobs
            finally:
                await conn_manager.stop()

        try:
            data = asyncio.run(_run())
            return _ok_response(data)
        except ValueError as e:
            return _error_response("CONFIGURATION_ERROR", str(e))
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"SLURM runner not available: {e}")
        except Exception as e:
            logger.error(f"SLURM queue fetch failed for cluster {cluster_id}: {e}")
            return _error_response("SLURM_ERROR", str(e))

    def sync_remote_jobs_json(self) -> str:
        """
        Synchronize status of tracked remote jobs with actual SLURM state.

        1. Identifies active remote jobs in local DB (SUBMITTED/QUEUED/RUNNING).
        2. Groups them by cluster.
        3. Queries squeue (for running) and sacct (for completed) on each cluster.
        4. Updates local DB with fresh status.
        5. Returns updated job list (same as get_jobs_json).

        Returns:
            JSON string with updated job list (same format as get_jobs_json)
        """
        import asyncio

        async def _run() -> None:
            from src.core.connection_manager import ConnectionManager
            from src.runners.slurm_runner import SLURMRunner, SLURMJobState

            if not hasattr(self, "_db") or not self._db:
                logger.warning("Database not available - cannot sync remote jobs")
                return

            # 1. Get active remote jobs
            # Join jobs with remote_jobs to get the handle
            cursor = self._db.conn.execute(
                """
                SELECT j.id, j.cluster_id, r.remote_handle 
                FROM jobs j
                JOIN remote_jobs r ON j.id = r.job_id
                WHERE j.status IN ('SUBMITTED', 'QUEUED', 'RUNNING') 
                AND j.runner_type = 'slurm'
                """
            )
            active_jobs = [
                {"id": row[0], "cluster_id": row[1], "remote_job_id": row[2]}
                for row in cursor.fetchall()
            ]

            if not active_jobs:
                return

            # Group by cluster
            jobs_by_cluster: Dict[int, List[Dict[str, Any]]] = {}
            for job in active_jobs:
                cid = job["cluster_id"]
                if cid not in jobs_by_cluster:
                    jobs_by_cluster[cid] = []
                jobs_by_cluster[cid].append(job)

            # Process each cluster
            conn_manager = ConnectionManager()
            try:
                for cluster_id, jobs in jobs_by_cluster.items():
                    try:
                        # Get cluster config
                        cluster = self._db.get_cluster(cluster_id)
                        if not cluster:
                            logger.warning(f"Cluster {cluster_id} not found, skipping sync")
                            continue

                        # Register cluster
                        import json as json_module

                        conn_config = (
                            json_module.loads(cluster.connection_config)
                            if isinstance(cluster.connection_config, str)
                            else cluster.connection_config
                        )

                        conn_manager.register_cluster(
                            cluster_id=cluster_id,
                            host=cluster.hostname,
                            port=cluster.port,
                            username=cluster.username,
                            key_file=Path(
                                conn_config.get("key_file", "~/.ssh/id_ed25519")
                            ).expanduser(),
                            strict_host_key_checking=True,
                        )

                        runner = SLURMRunner(connection_manager=conn_manager, cluster_id=cluster_id)

                        async with conn_manager.get_connection(cluster_id) as conn:
                            # A. Get current queue (squeue)
                            # Use timeout to prevent hanging
                            try:
                                queue_jobs = await asyncio.wait_for(
                                    runner.get_queue_status(user_only=True), timeout=15.0
                                )
                            except asyncio.TimeoutError:
                                logger.error(f"Timeout syncing cluster {cluster_id}")
                                continue

                            # Create map of remote_id -> status string
                            queue_map = {str(j["job_id"]): j["state"] for j in queue_jobs}

                            # B. Identify missing jobs (potentially completed/failed)
                            missing_job_ids = []
                            for job in jobs:
                                rid = str(job["remote_job_id"])
                                if rid in queue_map:
                                    # Job found in queue - update status
                                    slurm_state_str = queue_map[rid]
                                    slurm_state = runner._parse_state(slurm_state_str)
                                    new_status = runner._slurm_state_to_job_status(slurm_state)
                                    self._db.update_status(job["id"], new_status.value)
                                else:
                                    # Job not in squeue - check sacct
                                    missing_job_ids.append(rid)

                            # C. Bulk check sacct for missing jobs
                            if missing_job_ids:
                                id_list = ",".join(missing_job_ids)
                                sacct_cmd = f"sacct -j {id_list} -n -o JobID,State -P"
                                try:
                                    result = await asyncio.wait_for(
                                        conn.run(sacct_cmd, check=False), timeout=15.0
                                    )
                                    if result.exit_status == 0:
                                        # Parse sacct output: 12345|COMPLETED
                                        sacct_map = {}
                                        for line in result.stdout.strip().splitlines():
                                            parts = line.split("|")
                                            if len(parts) >= 2:
                                                jid, state = parts[0], parts[1]
                                                if "." not in jid:
                                                    sacct_map[jid] = state

                                        # Update DB for found jobs
                                        for job in jobs:
                                            rid = str(job["remote_job_id"])
                                            if rid in missing_job_ids and rid in sacct_map:
                                                slurm_state = runner._parse_state(sacct_map[rid])
                                                new_status = runner._slurm_state_to_job_status(
                                                    slurm_state
                                                )
                                                self._db.update_status(job["id"], new_status.value)
                                    else:
                                        logger.warning(f"sacct failed: {result.stderr}")

                                except asyncio.TimeoutError:
                                    logger.error("sacct timed out")

                    except Exception as e:
                        logger.error(f"Error syncing cluster {cluster_id}: {e}")

            finally:
                await conn_manager.stop()

        try:
            # Run the sync process
            asyncio.run(_run())
            return self.get_jobs_json()
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Dependencies missing: {e}")
        except Exception as e:
            logger.error(f"Remote sync failed: {e}")
            return _error_response("SYNC_FAILED", str(e))

    def adopt_slurm_job_json(self, cluster_id: int, slurm_job_id: str) -> str:
        """
        Adopt an untracked SLURM job into the local database.

        1. Fetches full job details from SLURM (scontrol).
        2. Creates a local Job record (runner_type=slurm).
        3. Creates a RemoteJob record linking to the SLURM ID.
        4. Creates a local working directory for results.

        Args:
            cluster_id: Cluster ID
            slurm_job_id: SLURM Job ID

        Returns:
            JSON string with {"ok": true} or error.
        """
        import asyncio
        import os

        async def _run() -> None:
            from src.core.connection_manager import ConnectionManager
            from src.runners.slurm_runner import SLURMRunner

            if not hasattr(self, "_db") or not self._db:
                raise ValueError("Database not available")

            cluster = self._db.get_cluster(cluster_id)
            if not cluster:
                raise ValueError(f"Cluster {cluster_id} not found")

            # Initialize connection
            import json as json_module

            conn_config = (
                json_module.loads(cluster.connection_config)
                if isinstance(cluster.connection_config, str)
                else cluster.connection_config
            )

            conn_manager = ConnectionManager()
            conn_manager.register_cluster(
                cluster_id=cluster_id,
                host=cluster.hostname,
                port=cluster.port,
                username=cluster.username,
                key_file=Path(conn_config.get("key_file", "~/.ssh/id_ed25519")).expanduser(),
                strict_host_key_checking=True,
            )

            try:
                runner = SLURMRunner(connection_manager=conn_manager, cluster_id=cluster_id)

                # Fetch job details
                details = await runner.get_job_details(slurm_job_id)
                if not details:
                    raise ValueError(f"Could not fetch details for SLURM job {slurm_job_id}")

                # Extract metadata
                job_name = details.get("JobName", f"adopted_{slurm_job_id}")
                work_dir_remote = details.get("WorkDir", "")
                partition = details.get("Partition", "")

                # Determine state
                state_str = details.get("JobState", "UNKNOWN")
                slurm_state = runner._parse_state(state_str)
                job_status = runner._slurm_state_to_job_status(slurm_state)

                # Create local working directory
                # Use standard location: ~/.local/share/crystal-tui/adopted/<job_name>_<uuid>
                # Or try to map from remote structure if it matches
                local_base = Path(os.environ.get("CRY_SCRATCH_BASE", "/tmp/crystal_adopted"))
                local_work_dir = local_base / f"{job_name}_{slurm_job_id}"
                local_work_dir.mkdir(parents=True, exist_ok=True)

                # Create Job record
                job_id = self._db.create_job(
                    name=job_name,
                    work_dir=str(local_work_dir),
                    input_content="",  # Unknown at this point
                    cluster_id=cluster_id,
                    runner_type="slurm",
                    dft_code="crystal",  # Default assumption
                )

                # Update status
                self._db.update_status(job_id, job_status.value)

                # Create RemoteJob record
                self._db.create_remote_job(
                    job_id=job_id,
                    cluster_id=cluster_id,
                    remote_handle=slurm_job_id,
                    working_directory=work_dir_remote,
                    queue_name=partition,
                    metadata=details,
                )

                logger.info(f"Adopted SLURM job {slurm_job_id} as local job {job_id}")
                return _ok_response({"success": True, "pk": job_id})

            finally:
                await conn_manager.stop()

        try:
            return asyncio.run(_run())
        except ValueError as e:
            return _error_response("CONFIGURATION_ERROR", str(e))
        except Exception as e:
            logger.error(f"Failed to adopt job {slurm_job_id}: {e}")
            return _error_response("ADOPTION_FAILED", str(e))

    def cancel_slurm_job_json(self, cluster_id: int, slurm_job_id: str) -> str:
        """
        Cancel a SLURM job on a remote cluster.

        Connects to the specified cluster via SSH and cancels the job
        using scancel.

        Args:
            cluster_id: Cluster database ID
            slurm_job_id: SLURM job ID to cancel

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": {"success": true, "message": "..."}}
            - Failure: {"ok": true, "data": {"success": false, "message": "..."}}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}
        """
        import asyncio

        async def _run() -> Dict[str, Any]:
            from src.core.connection_manager import ConnectionManager
            from src.runners.slurm_runner import SLURMRunner

            # Get cluster config from database
            if not hasattr(self, "_db") or not self._db:
                raise ValueError("Database not available - cannot fetch cluster config")

            cluster = self._db.get_cluster(cluster_id)
            if not cluster:
                raise ValueError(f"Cluster {cluster_id} not found in database")

            # Parse connection config from cluster
            import json as json_module

            conn_config_data = (
                json_module.loads(cluster.connection_config)
                if isinstance(cluster.connection_config, str)
                else cluster.connection_config
            )

            # Create connection manager
            conn_manager = ConnectionManager()

            # Register cluster with proper method
            conn_manager.register_cluster(
                cluster_id=cluster_id,
                host=cluster.hostname,
                port=cluster.port,
                username=cluster.username,
                key_file=Path(conn_config_data.get("key_file", "~/.ssh/id_ed25519")).expanduser(),
                strict_host_key_checking=True,
            )

            try:
                # Create SLURM runner and cancel job
                runner = SLURMRunner(
                    connection_manager=conn_manager,
                    cluster_id=cluster_id,
                )

                # Use timeout to prevent blocking the bridge thread indefinitely
                try:
                    success, message = await asyncio.wait_for(
                        runner.cancel_slurm_job(slurm_job_id), timeout=15.0
                    )
                except asyncio.TimeoutError:
                    return {
                        "success": False,
                        "message": "Cancel request timed out after 15 seconds",
                    }

                return {"success": success, "message": message}
            finally:
                await conn_manager.stop()

        try:
            data = asyncio.run(_run())
            return _ok_response(data)
        except ValueError as e:
            return _error_response("CONFIGURATION_ERROR", str(e))
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"SLURM runner not available: {e}")
        except Exception as e:
            logger.error(f"SLURM job cancel failed for {slurm_job_id} on cluster {cluster_id}: {e}")
            return _error_response("SLURM_ERROR", str(e))

    # ========== Cluster Management Methods ==========

    def get_clusters_json(self) -> str:
        """
        Get list of all configured clusters.

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": [ClusterConfig, ...]}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}

        Each ClusterConfig contains:
            - id: Cluster database ID
            - name: Display name
            - hostname: SSH hostname
            - port: SSH port (default 22)
            - username: SSH username
            - type: Cluster type (ssh, slurm)
            - connection_config: Additional config (key_file, env paths, etc.)
        """
        try:
            if not hasattr(self, "_db") or not self._db:
                return _error_response("NO_DATABASE", "Database not available")

            clusters = self._db.get_all_clusters()
            results: List[Dict[str, Any]] = []

            for cluster in clusters:
                # Parse connection_config if it's a string
                conn_config = cluster.connection_config
                if isinstance(conn_config, str):
                    try:
                        conn_config = json.loads(conn_config)
                    except json.JSONDecodeError:
                        conn_config = {}

                results.append(
                    {
                        "id": cluster.id,
                        "name": cluster.name,
                        "hostname": cluster.hostname,
                        "port": cluster.port,
                        "username": cluster.username,
                        "cluster_type": cluster.type,  # Must match Rust ClusterConfig field name
                        "status": cluster.status,
                        # Flatten connection_config to match Rust ClusterConfig
                        "key_file": conn_config.get("key_file"),
                        "remote_workdir": conn_config.get("remote_workdir"),
                        "queue_name": conn_config.get("queue_name"),
                        "max_concurrent": conn_config.get("max_concurrent", 4),
                        "cry23_root": cluster.cry23_root,
                        "vasp_root": cluster.vasp_root,
                        "setup_commands": cluster.setup_commands or [],
                    }
                )

            return _ok_response(results)
        except Exception as e:
            logger.error(f"Failed to get clusters: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def get_cluster_json(self, cluster_id: int) -> str:
        """
        Get details of a specific cluster.

        Args:
            cluster_id: Cluster database ID

        Returns:
            JSON string with cluster details or error
        """
        try:
            if not hasattr(self, "_db") or not self._db:
                return _error_response("NO_DATABASE", "Database not available")

            cluster = self._db.get_cluster(cluster_id)
            if not cluster:
                return _error_response("NOT_FOUND", f"Cluster {cluster_id} not found")

            conn_config = cluster.connection_config
            if isinstance(conn_config, str):
                try:
                    conn_config = json.loads(conn_config)
                except json.JSONDecodeError:
                    conn_config = {}

            return _ok_response(
                {
                    "id": cluster.id,
                    "name": cluster.name,
                    "hostname": cluster.hostname,
                    "port": cluster.port,
                    "username": cluster.username,
                    "cluster_type": cluster.type,  # Must match Rust ClusterConfig field name
                    "status": cluster.status,
                    # Flatten connection_config to match Rust ClusterConfig
                    "key_file": conn_config.get("key_file"),
                    "remote_workdir": conn_config.get("remote_workdir"),
                    "queue_name": conn_config.get("queue_name"),
                    "max_concurrent": conn_config.get("max_concurrent", 4),
                    "cry23_root": cluster.cry23_root,
                    "vasp_root": cluster.vasp_root,
                    "setup_commands": cluster.setup_commands or [],
                }
            )
        except Exception as e:
            logger.error(f"Failed to get cluster {cluster_id}: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def create_cluster_json(self, json_payload: str) -> str:
        """Create a new cluster from JSON payload.

        Accepts flat fields matching Rust ClusterConfig (key_file, remote_workdir,
        queue_name, max_concurrent) and packs them into connection_config for DB storage.
        """
        try:
            config = json.loads(json_payload)
            # Build connection_config from flat fields (Rust sends flat ClusterConfig)
            conn_config = config.get("connection_config", {})
            for field in ("key_file", "remote_workdir", "queue_name", "max_concurrent"):
                if field in config and config[field] is not None:
                    conn_config[field] = config[field]
            cluster_id = self._db.create_cluster(
                name=config["name"],
                type=config["cluster_type"],
                hostname=config["hostname"],
                port=config.get("port", 22),
                username=config["username"],
                connection_config=conn_config,
                cry23_root=config.get("cry23_root"),
                vasp_root=config.get("vasp_root"),
                setup_commands=config.get("setup_commands", []),
            )
            # Return the created cluster
            return self.get_cluster_json(cluster_id)
        except Exception as e:
            return _error_response("CREATE_FAILED", str(e))

    def update_cluster_json(self, cluster_id: int, json_payload: str) -> str:
        """
        Update an existing cluster configuration.

        Accepts flat fields matching Rust ClusterConfig (key_file, remote_workdir,
        queue_name, max_concurrent) and packs them into connection_config for DB storage.

        Args:
            cluster_id: Cluster database ID
            json_payload: JSON string with updated fields

        Returns:
            JSON string with success status or error
        """
        try:
            if not hasattr(self, "_db") or not self._db:
                return _error_response("NO_DATABASE", "Database not available")

            data = json.loads(json_payload)

            # Build connection_config from flat fields (Rust sends flat ClusterConfig)
            conn_config = data.get("connection_config")
            flat_fields = ("key_file", "remote_workdir", "queue_name", "max_concurrent")
            if any(f in data for f in flat_fields):
                conn_config = conn_config or {}
                for field in flat_fields:
                    if field in data and data[field] is not None:
                        conn_config[field] = data[field]

            self._db.update_cluster(
                cluster_id=cluster_id,
                name=data.get("name"),
                hostname=data.get("hostname"),
                port=data.get("port"),
                username=data.get("username"),
                connection_config=conn_config,
                cry23_root=data.get("cry23_root"),
                vasp_root=data.get("vasp_root"),
                setup_commands=data.get("setup_commands"),
            )

            return _ok_response({"success": True})
        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Failed to update cluster {cluster_id}: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def delete_cluster(self, cluster_id: int) -> str:
        """
        Delete a cluster configuration.

        Args:
            cluster_id: Cluster database ID

        Returns:
            JSON string with success status or error
        """
        try:
            if not hasattr(self, "_db") or not self._db:
                return _error_response("NO_DATABASE", "Database not available")

            self._db.delete_cluster(cluster_id)
            return _ok_response({"success": True})
        except Exception as e:
            logger.error(f"Failed to delete cluster {cluster_id}: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def test_cluster_connection_json(self, cluster_id: int) -> str:
        """
        Test SSH connection to a cluster.

        Args:
            cluster_id: Cluster database ID

        Returns:
            JSON string with connection test result:
            - Success: {"ok": true, "data": {"success": true, "hostname": "...", "system_info": "..."}}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}
        """
        import asyncio

        async def _test() -> Dict[str, Any]:
            from src.core.connection_manager import ConnectionManager

            if not hasattr(self, "_db") or not self._db:
                raise ValueError("Database not available")

            cluster = self._db.get_cluster(cluster_id)
            if not cluster:
                raise ValueError(f"Cluster {cluster_id} not found")

            conn_config = cluster.connection_config
            if isinstance(conn_config, str):
                conn_config = json.loads(conn_config)

            conn_manager = ConnectionManager()

            key_file = conn_config.get("key_file")
            if key_file:
                key_file = Path(key_file).expanduser()

            conn_manager.register_cluster(
                cluster_id=cluster_id,
                host=cluster.hostname,
                port=cluster.port,
                username=cluster.username,
                key_file=key_file,
                strict_host_key_checking=conn_config.get("strict_host_key_checking", True),
            )

            try:
                async with conn_manager.get_connection(cluster_id) as conn:
                    result = await asyncio.wait_for(conn.run("hostname && uname -a"), timeout=10.0)
                    lines = result.stdout.strip().split("\n")
                    remote_hostname = lines[0] if lines else "unknown"
                    system_info = lines[1] if len(lines) > 1 else ""

                    return {
                        "success": True,
                        "hostname": remote_hostname,
                        "system_info": system_info,
                    }
            finally:
                await conn_manager.stop()

        try:
            data = asyncio.run(_test())
            return _ok_response(data)
        except asyncio.TimeoutError:
            return _error_response("TIMEOUT", "Connection timed out after 10 seconds")
        except ValueError as e:
            return _error_response("CONFIGURATION_ERROR", str(e))
        except Exception as e:
            logger.error(f"Connection test failed for cluster {cluster_id}: {e}")
            return _error_response("CONNECTION_FAILED", str(e))

    # ========== AI Assistant Methods ==========

    def ask_assistant_json(self, message: str, context_json: str = "{}") -> str:
        """
        Send a message to the AI assistant.

        Args:
            message: User's question or message
            context_json: Optional JSON string with context (e.g., current job info)

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": {"response": "..."}}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}
        """
        try:
            from crystalmath.ai import AI_AVAILABLE, get_ai_service

            if not AI_AVAILABLE:
                return _error_response(
                    "AI_NOT_AVAILABLE",
                    "AI features require the 'llm' extra. Install with: pip install crystalmath[llm]",
                )

            # Parse context
            context = json.loads(context_json) if context_json else None

            # Get AI service and send message
            service = get_ai_service()
            response = service.chat(message=message, context=context)

            return _ok_response({"response": response})

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid context JSON: {e}")
        except ValueError as e:
            # API key not configured
            return _error_response("CONFIGURATION_ERROR", str(e))
        except Exception as e:
            logger.error(f"AI assistant error: {e}")
            return _error_response("AI_ERROR", str(e))

    def analyze_job_error_json(self, pk: int) -> str:
        """
        Analyze a failed job using AI to diagnose the error and suggest fixes.

        Fetches job details, error output, and input file, then sends to AI
        for analysis.

        Args:
            pk: Job primary key

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": {"diagnosis": "...", "job_name": "..."}}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}
        """
        try:
            from crystalmath.ai import AI_AVAILABLE, get_ai_service

            if not AI_AVAILABLE:
                return _error_response(
                    "AI_NOT_AVAILABLE",
                    "AI features require the 'llm' extra. Install with: pip install crystalmath[llm]",
                )

            # Fetch job error context
            error_context = self._get_job_error_context(pk)
            if error_context is None:
                return _error_response("NOT_FOUND", f"Job with pk={pk} not found")

            # Get AI service and analyze
            service = get_ai_service()
            diagnosis = service.diagnose_job(
                job_pk=pk,
                error_output=error_context["error_output"],
                input_file=error_context.get("input_content"),
                additional_context={
                    "job_name": error_context["job_name"],
                    "dft_code": error_context.get("dft_code"),
                    "state": error_context.get("state"),
                },
            )

            return _ok_response(
                {
                    "diagnosis": diagnosis,
                    "job_name": error_context["job_name"],
                    "job_pk": pk,
                }
            )

        except ValueError as e:
            # API key not configured
            return _error_response("CONFIGURATION_ERROR", str(e))
        except Exception as e:
            logger.error(f"Job error analysis failed for pk={pk}: {e}")
            return _error_response("AI_ERROR", str(e))

    def _get_job_error_context(self, pk: int) -> Optional[Dict[str, Any]]:
        """
        Fetch error context for a job from the database.

        Returns dict with:
            - job_name: Job name
            - error_output: Combined stderr and stdout tail
            - input_content: Input file content (if available)
            - dft_code: DFT code used
            - state: Job state

        Returns None if job not found.
        """
        backend_name = self._backend.name
        if backend_name == "aiida":
            return self._get_aiida_job_error_context(pk)
        elif backend_name == "sqlite":
            return self._get_sqlite_job_error_context(pk)
        else:
            return self._get_demo_job_error_context(pk)

    def _get_aiida_job_error_context(self, pk: int) -> Optional[Dict[str, Any]]:
        """Get error context from AiiDA."""
        from aiida import orm
        from aiida.common import NotExistent

        try:
            node = orm.load_node(pk)

            # Get stdout/stderr
            stdout_lines: List[str] = []
            stderr_lines: List[str] = []

            if "retrieved" in node.outputs:
                try:
                    stdout = node.outputs.retrieved.get_object_content("_scheduler-stdout.txt")
                    stdout_lines = stdout.splitlines()[-50:]
                except Exception:
                    pass
                try:
                    stderr = node.outputs.retrieved.get_object_content("_scheduler-stderr.txt")
                    stderr_lines = stderr.splitlines()[-50:]
                except Exception:
                    pass

            # Combine error output
            error_parts = []
            if stderr_lines:
                error_parts.append("=== STDERR ===\n" + "\n".join(stderr_lines))
            if stdout_lines:
                error_parts.append("=== STDOUT (last 50 lines) ===\n" + "\n".join(stdout_lines))

            error_output = "\n\n".join(error_parts) if error_parts else "No output available"

            # Get input content if available
            input_content = None
            if "input_file" in node.inputs:
                try:
                    input_content = node.inputs.input_file.get_content()
                except Exception:
                    pass

            return {
                "job_name": node.label or f"Job {pk}",
                "error_output": error_output,
                "input_content": input_content,
                "dft_code": "crystal",  # TODO: detect from node type
                "state": node.process_state.value if node.process_state else "unknown",
            }

        except NotExistent:
            return None
        except Exception as e:
            logger.error(f"Error fetching AiiDA job context for pk={pk}: {e}")
            return None

    def _get_sqlite_job_error_context(self, pk: int) -> Optional[Dict[str, Any]]:
        """Get error context from SQLite database."""
        try:
            job = self._db.get_job(pk)
            if not job:
                return None

            # Build error output from work directory logs
            error_output = ""
            work_dir = Path(job.work_dir) if job.work_dir else None

            if work_dir and work_dir.exists():
                # Try to read output files
                output_parts = []

                # CRYSTAL23 output file
                for out_file in ["OUTPUT", "output", f"{job.name}.out"]:
                    out_path = work_dir / out_file
                    if out_path.exists():
                        try:
                            content = out_path.read_text()
                            lines = content.splitlines()[-100:]  # Last 100 lines
                            output_parts.append(
                                f"=== {out_file} (last 100 lines) ===\n" + "\n".join(lines)
                            )
                        except Exception:
                            pass
                        break

                # Stderr if available
                stderr_path = work_dir / "stderr"
                if stderr_path.exists():
                    try:
                        stderr = stderr_path.read_text()
                        if stderr.strip():
                            output_parts.append("=== STDERR ===\n" + stderr[-5000:])
                    except Exception:
                        pass

                error_output = (
                    "\n\n".join(output_parts) if output_parts else "No output files found"
                )
            else:
                error_output = "Work directory not available"

            return {
                "job_name": job.name,
                "error_output": error_output,
                "input_content": job.input_file if hasattr(job, "input_file") else None,
                "dft_code": job.dft_code if hasattr(job, "dft_code") else "crystal",
                "state": job.status,
            }

        except Exception as e:
            logger.error(f"Error fetching SQLite job context for pk={pk}: {e}")
            return None

    def _get_demo_job_error_context(self, pk: int) -> Optional[Dict[str, Any]]:
        """Get error context for demo jobs."""
        for job in self._backend.get_jobs():
            if job.pk == pk:
                return {
                    "job_name": job.name,
                    "error_output": "Demo job - SCF convergence not reached after 100 cycles.\nLast energy: -274.987654 AU",
                    "input_content": "MgO\nCRYSTAL\n0 0 0\n225\n4.21\n2\n12 0.0 0.0 0.0\n8 0.5 0.5 0.5\nEND",
                    "dft_code": job.dft_code.value,
                    "state": job.state.value,
                }
        return None

    def suggest_parameters_json(self, calculation_type: str, system_description: str) -> str:
        """
        Get AI suggestions for input parameters.

        Args:
            calculation_type: Type of calculation (e.g., "geometry optimization", "band structure")
            system_description: Description of the system being studied

        Returns:
            JSON string with parameter suggestions
        """
        try:
            from crystalmath.ai import AI_AVAILABLE, get_ai_service

            if not AI_AVAILABLE:
                return _error_response(
                    "AI_NOT_AVAILABLE",
                    "AI features require the 'llm' extra. Install with: pip install crystalmath[llm]",
                )

            service = get_ai_service()
            suggestions = service.suggest_parameters(
                calculation_type=calculation_type,
                system_description=system_description,
            )

            return _ok_response({"suggestions": suggestions})

        except ValueError as e:
            return _error_response("CONFIGURATION_ERROR", str(e))
        except Exception as e:
            logger.error(f"Parameter suggestion failed: {e}")
            return _error_response("AI_ERROR", str(e))

    def check_ai_available_json(self) -> str:
        """
        Check if AI features are available and configured.

        Returns:
            JSON string with availability status:
            {"ok": true, "data": {"available": true/false, "reason": "..."}}
        """
        try:
            from crystalmath.ai import AI_AVAILABLE

            if not AI_AVAILABLE:
                return _ok_response(
                    {
                        "available": False,
                        "reason": "LLM dependencies not installed. Run: pip install crystalmath[llm]",
                    }
                )

            # Check if API key is configured
            import os

            if not os.environ.get("ANTHROPIC_API_KEY"):
                return _ok_response(
                    {
                        "available": False,
                        "reason": "ANTHROPIC_API_KEY environment variable not set",
                    }
                )

            return _ok_response(
                {
                    "available": True,
                    "reason": "AI features ready",
                }
            )

        except Exception as e:
            return _ok_response(
                {
                    "available": False,
                    "reason": str(e),
                }
            )

    # ========== Template Methods ==========

    def list_templates_json(self) -> str:
        """
        List all available input file templates.

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": [Template, ...]}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}
        """
        try:
            from src.core.templates import TemplateManager

            # Use monorepo templates directory
            repo_root = Path(__file__).parent.parent.parent
            template_dir = repo_root / "templates"
            manager = TemplateManager(template_dir)

            templates = manager.list_templates()
            results = []
            for t in templates:
                # Convert to JSON-serializable dict matching Rust Template struct
                params_dict = {}
                for name, param in t.parameters.items():
                    params_dict[name] = {
                        "name": param.name,
                        "type": param.type,
                        "default": param.default,
                        "description": param.description,
                        "min": param.min,
                        "max": param.max,
                        "options": param.options,
                        "required": param.required,
                        "depends_on": param.depends_on,
                    }

                results.append(
                    {
                        "name": t.name,
                        "version": t.version,
                        "description": t.description,
                        "author": t.author,
                        "tags": t.tags,
                        "parameters": params_dict,
                        "input_template": t.input_template,
                        "extends": t.extends,
                        "includes": t.includes,
                        "metadata": t.metadata,
                    }
                )

            return _ok_response(results)
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Template system not available: {e}")
        except Exception as e:
            logger.error(f"Failed to list templates: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def render_template_json(self, template_name: str, params_json: str) -> str:
        """
        Render a template with the given parameters.

        Args:
            template_name: Name of the template to render
            params_json: JSON string with parameter values

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": "<rendered content>"}
            - Error: {"ok": false, "error": {"code": "...", "message": "..."}}
        """
        try:
            from src.core.templates import TemplateManager

            # Use monorepo templates directory
            repo_root = Path(__file__).parent.parent.parent
            template_dir = repo_root / "templates"
            manager = TemplateManager(template_dir)

            # Find template by name
            template = manager.find_template(template_name)
            if not template:
                return _error_response("NOT_FOUND", f"Template '{template_name}' not found")

            # Parse parameters
            params = json.loads(params_json) if params_json else {}

            # Render
            rendered = manager.render(template, params)
            return _ok_response(rendered)

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid parameters JSON: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Template system not available: {e}")
        except ValueError as e:
            return _error_response("VALIDATION_ERROR", str(e))
        except Exception as e:
            logger.error(f"Failed to render template '{template_name}': {e}")
            return _error_response("RENDER_ERROR", str(e))

    # ========== Workflow API Methods ==========

    def check_workflows_available_json(self) -> str:
        """
        Check if workflow automation is available.

        Returns:
            JSON string with structure:
            - Success: {"ok": true, "data": {"available": bool, "workflows": [str, ...],
                        "aiida_available": bool, "quacc_available": bool}}
        """
        try:
            from crystalmath.workflows import (
                WORKFLOWS_AVAILABLE,
                AIIDA_LAUNCHER_AVAILABLE,
                ConvergenceWorkflow,
                BandStructureWorkflow,
                PhononWorkflow,
                EOSWorkflow,
            )

            available_workflows = []
            if ConvergenceWorkflow is not None:
                available_workflows.append("convergence")
            if BandStructureWorkflow is not None:
                available_workflows.append("band_structure")
            if PhononWorkflow is not None:
                available_workflows.append("phonon")
            if EOSWorkflow is not None:
                available_workflows.append("eos")
            # Geometry optimization requires AiiDA
            if AIIDA_LAUNCHER_AVAILABLE:
                available_workflows.append("geometry_optimization")

            # Check quacc availability
            try:
                from crystalmath.quacc.discovery import discover_vasp_recipes
                quacc_available = len(discover_vasp_recipes()) > 0
            except ImportError:
                quacc_available = False

            return _ok_response(
                {
                    "available": WORKFLOWS_AVAILABLE or quacc_available,
                    "workflows": available_workflows,
                    "aiida_available": AIIDA_LAUNCHER_AVAILABLE,
                    "quacc_available": quacc_available,
                }
            )
        except ImportError as e:
            # Check if at least quacc is available
            try:
                from crystalmath.quacc.discovery import discover_vasp_recipes
                quacc_available = len(discover_vasp_recipes()) > 0
                quacc_workflows = ["convergence", "band_structure", "phonon", "eos", "geometry_optimization"] if quacc_available else []
            except ImportError:
                quacc_available = False
                quacc_workflows = []

            return _ok_response(
                {
                    "available": quacc_available,
                    "workflows": quacc_workflows,
                    "aiida_available": False,
                    "quacc_available": quacc_available,
                    "error": str(e) if not quacc_available else None,
                }
            )

    def create_convergence_study_json(self, config_json: str) -> str:
        """
        Create a new convergence study workflow.

        Args:
            config_json: JSON configuration with:
                - parameter: "shrink", "kpoints", "encut", "ecutwfc", "basis"
                - values: List of values to test
                - base_input: Base input file content
                - energy_threshold: Convergence threshold (default 0.001 eV/atom)
                - dft_code: "crystal", "vasp", "qe"
                - cluster_id: Cluster to run on (optional)
                - name_prefix: Job name prefix (default "conv")

        Returns:
            JSON string with workflow state including generated inputs
        """
        try:
            from crystalmath.workflows.convergence import (
                ConvergenceStudy,
                ConvergenceStudyConfig,
                ConvergenceParameter,
            )

            config_data = json.loads(config_json)

            config = ConvergenceStudyConfig(
                parameter=ConvergenceParameter(config_data["parameter"]),
                values=config_data["values"],
                base_input=config_data["base_input"],
                structure_file=config_data.get("structure_file"),
                energy_threshold=config_data.get("energy_threshold", 0.001),
                dft_code=config_data.get("dft_code", "crystal"),
                cluster_id=config_data.get("cluster_id"),
                name_prefix=config_data.get("name_prefix", "conv"),
            )

            study = ConvergenceStudy(config)

            # Generate input files
            inputs = study.generate_inputs()

            return _ok_response(
                {
                    "workflow_json": study.to_json(),
                    "inputs": [{"name": name, "content": content} for name, content in inputs],
                }
            )

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid config JSON: {e}")
        except KeyError as e:
            return _error_response("MISSING_FIELD", f"Missing required field: {e}")
        except ValueError as e:
            return _error_response("VALIDATION_ERROR", str(e))
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Workflow module not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create convergence study: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def update_convergence_study_json(self, workflow_json: str, updates_json: str) -> str:
        """
        Update convergence study with job results.

        Args:
            workflow_json: Current workflow state JSON
            updates_json: JSON with updates:
                - index: Point index to update
                - energy: Total energy (optional)
                - energy_per_atom: Energy per atom (optional)
                - job_pk: Job PK (optional)
                - status: "pending", "running", "completed", "failed"
                - error_message: Error message if failed (optional)

        Returns:
            Updated workflow JSON with analysis if complete
        """
        try:
            from crystalmath.workflows.convergence import ConvergenceStudy

            study = ConvergenceStudy.from_json(workflow_json)
            updates = json.loads(updates_json)

            study.update_point(
                updates["index"],
                energy=updates.get("energy"),
                energy_per_atom=updates.get("energy_per_atom"),
                forces_max=updates.get("forces_max"),
                wall_time_seconds=updates.get("wall_time_seconds"),
                job_pk=updates.get("job_pk"),
                status=updates.get("status"),
                error_message=updates.get("error_message"),
            )

            # Check if all complete and analyze
            completed = sum(1 for p in study.result.points if p.status == "completed")
            if completed == len(study.result.points):
                study.analyze_results()

            return _ok_response(
                {
                    "workflow_json": study.to_json(),
                    "result": study.result.to_dict(),
                }
            )

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid JSON: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Workflow module not available: {e}")
        except Exception as e:
            logger.error(f"Failed to update convergence study: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def create_band_structure_workflow_json(self, config_json: str) -> str:
        """
        Create a band structure calculation workflow.

        Args:
            config_json: JSON configuration with:
                - source_job_pk: PK of converged SCF job
                - kpoints_distance: K-point spacing (default 0.05)
                - path_type: "auto", "crystal_system", or "explicit"
                - crystal_system: "cubic", "fcc", "bcc", "hexagonal", "tetragonal"
                - explicit_path: Custom k-path (e.g., "Gamma X M Gamma")
                - calculate_dos: Whether to calculate DOS (default true)
                - protocol: "fast", "moderate", "precise"

        Returns:
            JSON string with workflow state and generated input
        """
        try:
            from crystalmath.workflows.bands import (
                BandStructureWorkflow,
                BandStructureConfig,
                BandPathType,
            )

            config_data = json.loads(config_json)

            config = BandStructureConfig(
                source_job_pk=config_data["source_job_pk"],
                kpoints_distance=config_data.get("kpoints_distance", 0.05),
                path_type=BandPathType(config_data.get("path_type", "auto")),
                crystal_system=config_data.get("crystal_system"),
                explicit_path=config_data.get("explicit_path"),
                calculate_dos=config_data.get("calculate_dos", True),
                dos_mesh=tuple(config_data.get("dos_mesh", [12, 12, 12])),
                protocol=config_data.get("protocol", "moderate"),
                cluster_id=config_data.get("cluster_id"),
            )

            workflow = BandStructureWorkflow(config)

            # Generate k-path if cell provided
            kpath = None
            if "cell" in config_data:
                kpath = workflow.generate_kpath(
                    config_data["cell"],
                    config_data.get("positions"),
                )

            return _ok_response(
                {
                    "workflow_json": workflow.to_json(),
                    "kpath": [{"label": l, "kpoint": k} for l, k in kpath] if kpath else None,
                }
            )

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid config JSON: {e}")
        except KeyError as e:
            return _error_response("MISSING_FIELD", f"Missing required field: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Workflow module not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create band structure workflow: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def create_phonon_workflow_json(self, config_json: str) -> str:
        """
        Create a phonon calculation workflow.

        Args:
            config_json: JSON configuration with:
                - source_job_pk: PK of optimized geometry job
                - supercell_dim: [nx, ny, nz] supercell dimensions
                - displacement_distance: Displacement amplitude (default 0.01 A)
                - symmetry: Use symmetry (default true)
                - mesh: Q-point mesh for DOS [mx, my, mz]
                - tmin, tmax, tstep: Temperature range for thermal properties
                - structure: Dict with cell, positions, symbols (for displacement gen)

        Returns:
            JSON string with workflow state and displacement structures
        """
        try:
            from crystalmath.workflows.phonon import (
                PhononWorkflow,
                PhononConfig,
                PhononMethod,
                DFTCode,
            )

            config_data = json.loads(config_json)

            config = PhononConfig(
                source_job_pk=config_data["source_job_pk"],
                supercell_dim=tuple(config_data.get("supercell_dim", [2, 2, 2])),
                method=PhononMethod(config_data.get("method", "finite_displacement")),
                dft_code=DFTCode(config_data.get("dft_code", "crystal")),
                displacement_distance=config_data.get("displacement_distance", 0.01),
                symmetry=config_data.get("symmetry", True),
                acoustic_sum_rule=config_data.get("acoustic_sum_rule", True),
                mesh=tuple(config_data.get("mesh", [20, 20, 20])),
                band_path=config_data.get("band_path", "AUTO"),
                tmin=config_data.get("tmin", 0.0),
                tmax=config_data.get("tmax", 1000.0),
                tstep=config_data.get("tstep", 10.0),
                cluster_id=config_data.get("cluster_id"),
            )

            workflow = PhononWorkflow(config)

            # Generate displacements if structure provided
            displacements = None
            if "structure" in config_data:
                structure = config_data["structure"]
                displacements = workflow.generate_displacements(structure)

            return _ok_response(
                {
                    "workflow_json": workflow.to_json(),
                    "num_displacements": workflow.result.num_displacements,
                    "displacements": displacements,
                }
            )

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid config JSON: {e}")
        except KeyError as e:
            return _error_response("MISSING_FIELD", f"Missing required field: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Workflow module not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create phonon workflow: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def update_phonon_workflow_json(self, workflow_json: str, updates_json: str) -> str:
        """
        Update phonon workflow with force calculation results.

        Args:
            workflow_json: Current workflow state JSON
            updates_json: JSON with updates:
                - displacement_id: Which displacement to update
                - job_pk: Job primary key
                - status: "pending", "submitted", "running", "completed", "failed"
                - forces: List of [fx, fy, fz] for each atom
                - energy: Total energy
                - error_message: Error message if failed

        Returns:
            Updated workflow JSON
        """
        try:
            from crystalmath.workflows.phonon import PhononWorkflow

            workflow = PhononWorkflow.from_json(workflow_json)
            updates = json.loads(updates_json)

            workflow.update_displacement(
                updates["displacement_id"],
                job_pk=updates.get("job_pk"),
                status=updates.get("status"),
                forces=updates.get("forces"),
                energy=updates.get("energy"),
                error_message=updates.get("error_message"),
            )

            return _ok_response(
                {
                    "workflow_json": workflow.to_json(),
                    "num_completed": workflow.result.num_completed,
                    "num_failed": workflow.result.num_failed,
                    "all_complete": workflow.all_forces_ready(),
                }
            )

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid JSON: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Workflow module not available: {e}")
        except Exception as e:
            logger.error(f"Failed to update phonon workflow: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    # ========== EOS Workflow Methods ==========

    def create_eos_workflow_json(self, config_json: str) -> str:
        """
        Create an Equation of State workflow.

        Args:
            config_json: JSON configuration with:
                - source_job_pk: PK of optimized geometry job
                - volume_range: [min_scale, max_scale] (default [0.90, 1.10])
                - num_points: Number of volume points (default 7)
                - eos_type: EOS type (default "birch_murnaghan")

        Returns:
            JSON with workflow state
        """
        try:
            from crystalmath.workflows.eos import EOSWorkflow, EOSConfig

            config_data = json.loads(config_json)

            config = EOSConfig(
                source_job_pk=config_data["source_job_pk"],
                volume_range=tuple(config_data.get("volume_range", [0.90, 1.10])),
                num_points=config_data.get("num_points", 7),
                eos_type=config_data.get("eos_type", "birch_murnaghan"),
                dft_code=config_data.get("dft_code", "crystal"),
                cluster_id=config_data.get("cluster_id"),
                name_prefix=config_data.get("name_prefix", "eos"),
            )

            workflow = EOSWorkflow(config)

            return _ok_response({"workflow_json": workflow.to_json()})

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", f"Invalid config JSON: {e}")
        except KeyError as e:
            return _error_response("MISSING_FIELD", f"Missing required field: {e}")
        except ImportError as e:
            return _error_response("IMPORT_ERROR", f"Workflow module not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create EOS workflow: {e}")
            return _error_response("WORKFLOW_ERROR", str(e))

    def generate_eos_structures_json(
        self,
        workflow_json: str,
        structure_json: str,
    ) -> str:
        """
        Generate volume-scaled structures for EOS.

        Args:
            workflow_json: EOS workflow state
            structure_json: Reference structure with cell, positions, symbols

        Returns:
            JSON with scaled structures and updated workflow
        """
        try:
            from crystalmath.workflows.eos import EOSWorkflow

            workflow = EOSWorkflow.from_json(workflow_json)
            structure = json.loads(structure_json)

            scaled = workflow.generate_volume_points(
                cell=structure["cell"],
                positions=structure["positions"],
                symbols=structure["symbols"],
            )

            return _ok_response(
                {
                    "workflow_json": workflow.to_json(),
                    "structures": scaled,
                    "num_points": len(scaled),
                }
            )

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", str(e))
        except Exception as e:
            logger.error(f"Failed to generate EOS structures: {e}")
            return _error_response("WORKFLOW_ERROR", str(e))

    def fit_eos_json(self, workflow_json: str) -> str:
        """
        Fit equation of state after all calculations complete.

        Args:
            workflow_json: EOS workflow with completed energy calculations

        Returns:
            JSON with fitted EOS parameters (V0, E0, B0, B')
        """
        try:
            from crystalmath.workflows.eos import EOSWorkflow

            workflow = EOSWorkflow.from_json(workflow_json)
            result = workflow.fit_eos()

            return _ok_response(
                {
                    "workflow_json": workflow.to_json(),
                    "result": result.to_dict(),
                }
            )

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", str(e))
        except Exception as e:
            logger.error(f"Failed to fit EOS: {e}")
            return _error_response("WORKFLOW_ERROR", str(e))

    # ========== AiiDA Workflow Launcher Methods ==========

    def get_aiida_workflows_json(self) -> str:
        """
        Get available AiiDA workflows and their status.

        Returns:
            JSON with available workflows and AiiDA status
        """
        try:
            from crystalmath.workflows import (
                AIIDA_LAUNCHER_AVAILABLE,
                check_aiida_available,
                check_common_workflows_available,
                get_available_workflows,
            )

            if not AIIDA_LAUNCHER_AVAILABLE:
                return _ok_response(
                    {
                        "aiida_available": False,
                        "reason": "AiiDA launcher module not available",
                        "workflows": {},
                    }
                )

            aiida_ok, aiida_reason = check_aiida_available()
            acwf_ok, acwf_reason = check_common_workflows_available()
            workflows = get_available_workflows()

            return _ok_response(
                {
                    "aiida_available": aiida_ok,
                    "aiida_reason": aiida_reason,
                    "common_workflows_available": acwf_ok,
                    "common_workflows_reason": acwf_reason,
                    "workflows": workflows,
                }
            )

        except Exception as e:
            logger.error(f"Failed to get AiiDA workflows: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def launch_aiida_geopt_json(self, config_json: str) -> str:
        """
        Launch AiiDA geometry optimization workflow.

        Args:
            config_json: JSON configuration with:
                - structure_pk: PK of input StructureData
                - code_label: Label of CRYSTAL23 code
                - parameters: CRYSTAL23 input parameters (optional)
                - options: Calculation options (optional)
                - optimization_mode: fulloptg, atomonly, cellonly, itatocel
                - max_iterations: Max optimization iterations
                - restart_pk: PK of failed job to restart from (optional)

        Returns:
            JSON with workflow PK/UUID or error
        """
        try:
            from crystalmath.workflows import (
                AIIDA_LAUNCHER_AVAILABLE,
                launch_geometry_optimization,
            )

            if not AIIDA_LAUNCHER_AVAILABLE:
                return _error_response(
                    "AIIDA_NOT_AVAILABLE",
                    "AiiDA launcher not available",
                )

            config = json.loads(config_json)

            result = launch_geometry_optimization(
                structure_pk=config["structure_pk"],
                code_label=config["code_label"],
                parameters=config.get("parameters"),
                options=config.get("options"),
                optimization_mode=config.get("optimization_mode", "fulloptg"),
                max_iterations=config.get("max_iterations", 10),
                force_threshold=config.get("force_threshold", 0.00045),
                restart_pk=config.get("restart_pk"),
            )

            return _ok_response(result.to_dict())

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", str(e))
        except KeyError as e:
            return _error_response("MISSING_FIELD", f"Missing required field: {e}")
        except Exception as e:
            logger.error(f"Failed to launch geometry optimization: {e}")
            return _error_response("LAUNCH_ERROR", str(e))

    def launch_aiida_bands_json(self, config_json: str) -> str:
        """
        Launch AiiDA band structure workflow.

        Args:
            config_json: JSON configuration with:
                - structure_pk: PK of input StructureData (if no scf_pk)
                - scf_pk: PK of completed SCF job (to reuse wavefunction)
                - code_label: Label of CRYSTAL23 code
                - kpoints_distance: K-point spacing (default 0.05)
                - options: Calculation options (optional)

        Returns:
            JSON with workflow PK/UUID or error
        """
        try:
            from crystalmath.workflows import (
                AIIDA_LAUNCHER_AVAILABLE,
                launch_band_structure,
            )

            if not AIIDA_LAUNCHER_AVAILABLE:
                return _error_response(
                    "AIIDA_NOT_AVAILABLE",
                    "AiiDA launcher not available",
                )

            config = json.loads(config_json)

            result = launch_band_structure(
                structure_pk=config.get("structure_pk"),
                scf_pk=config.get("scf_pk"),
                code_label=config["code_label"],
                kpoints_distance=config.get("kpoints_distance", 0.05),
                options=config.get("options"),
            )

            return _ok_response(result.to_dict())

        except json.JSONDecodeError as e:
            return _error_response("INVALID_JSON", str(e))
        except KeyError as e:
            return _error_response("MISSING_FIELD", f"Missing required field: {e}")
        except Exception as e:
            logger.error(f"Failed to launch band structure: {e}")
            return _error_response("LAUNCH_ERROR", str(e))

    def get_aiida_workflow_status_json(self, workflow_pk: int) -> str:
        """
        Get status of an AiiDA workflow.

        Args:
            workflow_pk: PK of the workflow

        Returns:
            JSON with workflow status and outputs
        """
        try:
            from crystalmath.workflows import (
                AIIDA_LAUNCHER_AVAILABLE,
                get_workflow_status,
            )

            if not AIIDA_LAUNCHER_AVAILABLE:
                return _error_response(
                    "AIIDA_NOT_AVAILABLE",
                    "AiiDA launcher not available",
                )

            status = get_workflow_status(workflow_pk)
            return _ok_response(status)

        except Exception as e:
            logger.error(f"Failed to get workflow status: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def extract_restart_geometry_json(self, job_pk: int) -> str:
        """
        Extract last good geometry from failed/interrupted job.

        This is the key function for geometry optimization restart.

        Args:
            job_pk: PK of the failed job

        Returns:
            JSON with structure info or error if not extractable
        """
        try:
            from crystalmath.workflows import (
                AIIDA_LAUNCHER_AVAILABLE,
                extract_restart_geometry,
            )

            if not AIIDA_LAUNCHER_AVAILABLE:
                return _error_response(
                    "AIIDA_NOT_AVAILABLE",
                    "AiiDA launcher not available",
                )

            result = extract_restart_geometry(job_pk)
            if result:
                return _ok_response(result)
            else:
                return _error_response(
                    "EXTRACTION_FAILED",
                    f"Could not extract geometry from job {job_pk}",
                )

        except Exception as e:
            logger.error(f"Failed to extract restart geometry: {e}")
            return _error_response("INTERNAL_ERROR", str(e))


# Convenience function for Rust initialization
def create_controller(
    profile_name: str = "default",
    use_aiida: bool = True,
    db_path: Optional[str] = None,
) -> CrystalController:
    """
    Factory function to create a CrystalController.

    This is the entry point called from Rust via PyO3.

    Args:
        profile_name: AiiDA profile name
        use_aiida: Whether to use AiiDA backend
        db_path: SQLite database path for fallback

    Returns:
        Configured CrystalController instance
    """
    return CrystalController(
        profile_name=profile_name,
        use_aiida=use_aiida,
        db_path=db_path,
    )
