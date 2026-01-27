"""VASP output parser implementation.

Parses VASP OUTCAR files to extract energy, convergence status,
forces, benchmark timing data, and other calculation results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import DFTCode
from .base import OutputParser, ParsingResult, register_parser


@dataclass
class VASPBenchmarkMetrics:
    """Container for VASP benchmark timing and resource data.

    Stores comprehensive timing breakdown from OUTCAR including:
    - Total wall and CPU time
    - Per-routine timing (LOOP, LOOP+, POTLOK, SETDIJ, etc.)
    - Memory usage per core
    - Parallelization settings (NPAR, NCORE, KPAR)
    - Ionic step timings
    """

    # Total timing
    total_cpu_time_sec: Optional[float] = None
    elapsed_time_sec: Optional[float] = None

    # LOOP timings (summed across all iterations)
    loop_cpu_time_sec: Optional[float] = None
    loop_real_time_sec: Optional[float] = None
    loop_count: int = 0

    # LOOP+ timings (ionic step overhead)
    loop_plus_cpu_time_sec: Optional[float] = None
    loop_plus_real_time_sec: Optional[float] = None
    loop_plus_count: int = 0

    # Individual routine timings (from timing table)
    routine_timings: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # Memory usage
    memory_per_core_mb: Optional[float] = None
    maximum_memory_used_mb: Optional[float] = None

    # Parallelization settings
    npar: Optional[int] = None
    ncore: Optional[int] = None
    kpar: Optional[int] = None
    num_cores: Optional[int] = None

    # Efficiency metrics
    cpu_to_wall_ratio: Optional[float] = None
    parallel_efficiency: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: Dict[str, Any] = {}

        # Total timing
        if self.total_cpu_time_sec is not None:
            result["total_cpu_time_sec"] = self.total_cpu_time_sec
        if self.elapsed_time_sec is not None:
            result["elapsed_time_sec"] = self.elapsed_time_sec

        # LOOP timings
        if self.loop_cpu_time_sec is not None:
            result["loop_cpu_time_sec"] = self.loop_cpu_time_sec
        if self.loop_real_time_sec is not None:
            result["loop_real_time_sec"] = self.loop_real_time_sec
        if self.loop_count > 0:
            result["loop_count"] = self.loop_count

        # LOOP+ timings
        if self.loop_plus_cpu_time_sec is not None:
            result["loop_plus_cpu_time_sec"] = self.loop_plus_cpu_time_sec
        if self.loop_plus_real_time_sec is not None:
            result["loop_plus_real_time_sec"] = self.loop_plus_real_time_sec
        if self.loop_plus_count > 0:
            result["loop_plus_count"] = self.loop_plus_count

        # Routine timings (only if non-empty)
        if self.routine_timings:
            result["routine_timings"] = self.routine_timings

        # Memory
        if self.memory_per_core_mb is not None:
            result["memory_per_core_mb"] = self.memory_per_core_mb
        if self.maximum_memory_used_mb is not None:
            result["maximum_memory_used_mb"] = self.maximum_memory_used_mb

        # Parallelization
        if self.npar is not None:
            result["npar"] = self.npar
        if self.ncore is not None:
            result["ncore"] = self.ncore
        if self.kpar is not None:
            result["kpar"] = self.kpar
        if self.num_cores is not None:
            result["num_cores"] = self.num_cores

        # Efficiency
        if self.cpu_to_wall_ratio is not None:
            result["cpu_to_wall_ratio"] = self.cpu_to_wall_ratio
        if self.parallel_efficiency is not None:
            result["parallel_efficiency"] = self.parallel_efficiency

        return result


class VASPParser(OutputParser):
    """Parser for VASP output files (OUTCAR).

    Supports SCF, geometry optimization, and molecular dynamics outputs.
    Extracts comprehensive benchmark timing data for performance analysis.
    """

    # Regex patterns for VASP OUTCAR parsing
    # Free energy: "  free  energy   TOTEN  =       -85.54234987 eV"
    TOTEN_PATTERN = re.compile(r"free\s+energy\s+TOTEN\s*=\s*([-\d.]+)\s*eV", re.IGNORECASE)

    # Energy without entropy: "  energy  without entropy =       -85.53789012"
    E0_PATTERN = re.compile(r"energy\s+without entropy\s*=\s*([-\d.]+)")

    # Electronic steps: "       N       E                     dE"
    # Requires MULTILINE so ^ matches at start of each line, not just string start
    ELECTRONIC_STEP_PATTERN = re.compile(r"^\s+(\d+)\s+([-\d.E+]+)\s+([-\d.E+]+)", re.MULTILINE)

    # Ionic step (for geometry optimization)
    IONIC_STEP_PATTERN = re.compile(
        r"------------------------ aborting loop because EDIFF is reached ----------------------"
    )

    # Forces: "  TOTAL-FORCE (eV/Angst)"
    MAX_FORCE_PATTERN = re.compile(r"RMS\s+([-\d.E+]+)")

    # ========== Timing patterns for benchmarking ==========

    # Per-iteration routine timing: "   POTLOK:  cpu time   1.23: real time   1.45"
    # Captures routine name and both CPU and real time
    ROUTINE_TIME_PATTERN = re.compile(
        r"^\s*(\w+):\s+cpu time\s+([\d.]+):\s+real time\s+([\d.]+)", re.MULTILINE
    )

    # LOOP timing (SCF iteration): "   LOOP:  cpu time  123.45: real time  234.56"
    LOOP_TIME_PATTERN = re.compile(r"LOOP:\s+cpu time\s+([\d.]+):\s+real time\s+([\d.]+)")

    # LOOP+ timing (ionic step): "   LOOP+:  cpu time   12.34: real time   23.45"
    LOOP_PLUS_TIME_PATTERN = re.compile(r"LOOP\+:\s+cpu time\s+([\d.]+):\s+real time\s+([\d.]+)")

    # Total CPU time: " Total CPU time used (sec):     1234.567"
    TOTAL_CPU_PATTERN = re.compile(r"Total CPU time used \(sec\):\s+([\d.]+)")

    # Elapsed time: " Elapsed time (sec):     2345.678"
    ELAPSED_TIME_PATTERN = re.compile(r"Elapsed time \(sec\):\s+([\d.]+)")

    # Memory patterns
    # " total amount of memory used by VASP MPI-rank0   123456. kBytes"
    MEMORY_RANK0_PATTERN = re.compile(
        r"total amount of memory used by VASP.*?(\d+\.?\d*)\s*kBytes", re.IGNORECASE
    )
    # " Maximum memory used (kb):     123456."
    MAX_MEMORY_PATTERN = re.compile(r"Maximum memory used \(kb\):\s+([\d.]+)")

    # Number of cores: " running on    4 total cores"
    NUM_CORES_PATTERN = re.compile(r"running on\s+(\d+)\s+total cores")

    # Parallelization settings
    # "   NPAR = 4"
    NPAR_PATTERN = re.compile(r"NPAR\s*=\s*(\d+)")
    # "   NCORE = 2"
    NCORE_PATTERN = re.compile(r"NCORE\s*=\s*(\d+)")
    # "   KPAR = 2"
    KPAR_PATTERN = re.compile(r"KPAR\s*=\s*(\d+)")

    # Warning patterns
    WARNING_PATTERNS = [
        re.compile(r"WARNING.*", re.IGNORECASE),
        re.compile(r"VERY BAD NEWS.*", re.IGNORECASE),
    ]

    # Routines to track in timing breakdown
    TRACKED_ROUTINES = [
        "POTLOK",  # Local potential
        "SETDIJ",  # PAW setup
        "EDDIAG",  # Eigenvalue problem
        "RMM-DIIS",  # Davidson/RMM-DIIS
        "ORTHCH",  # Orthogonalization
        "DOS",  # Density of states
        "CHARGE",  # Charge density
        "MIXING",  # Charge mixing
        "EFIELD",  # Electric field
        "FORCES",  # Force calculation
        "STRESS",  # Stress tensor
        "FORHAR",  # Hartree forces
        "FORLOC",  # Local forces
        "FORNL",  # Non-local forces
        "LOOP",  # SCF loop
        "LOOP+",  # Ionic loop
    ]

    def _parse_with_parsevasp(self, output_file: Path) -> Optional[ParsingResult]:
        """Parse VASP output using parsevasp (from aiida-vasp).

        Tries to use vasprun.xml for accurate energies/forces, and OUTCAR
        for timing and status.
        """
        try:
            from parsevasp.vasprun import Xml
            from parsevasp.outcar import Outcar
        except ImportError:
            return None

        vasprun_path = output_file.parent / "vasprun.xml"
        outcar_path = output_file if output_file.name == "OUTCAR" else output_file.parent / "OUTCAR"

        xml_data = None
        outcar_data = None

        # Parse vasprun.xml if available
        if vasprun_path.exists():
            final_energy = None
            try:
                xml = Xml(file_path=str(vasprun_path))
                # get_energies returns dict with numpy arrays
                # We want 'energy_free' (TOTEN)
                energies_dict = xml.get_energies(status="last", etype=["energy_free"])

                if energies_dict and "energy_free_final" in energies_dict:
                    finals = energies_dict["energy_free_final"]
                    # Handle numpy array or list
                    try:
                        if hasattr(finals, "size") and finals.size > 0:
                            final_energy = float(finals[-1])
                        elif isinstance(finals, list) and finals:
                            final_energy = float(finals[-1])
                    except (ValueError, IndexError, TypeError):
                        pass

                xml_data = {
                    "final_energy": final_energy,
                }

                # Try to get forces/stress if needed
                try:
                    forces = xml.get_forces(status="last")
                    # get_forces returns numpy array of shape (atoms, 3) for 'last'
                    if forces is not None:
                        xml_data["forces"] = forces
                except Exception:
                    pass
            except Exception:
                pass

        # Parse OUTCAR if available
        if outcar_path.exists():
            try:
                outcar = Outcar(file_path=str(outcar_path))
                outcar_data = {
                    "status": outcar.get_run_status(),
                    "stats": outcar.get_run_stats(),
                }
            except (Exception, SystemExit):
                # parsevasp may sys.exit() on severe errors
                pass

        if not xml_data and not outcar_data:
            return None

        # Combine results
        final_energy = None
        if xml_data and xml_data.get("final_energy") is not None:
            final_energy = xml_data["final_energy"]

        # Determine status from OUTCAR if possible
        convergence_status = "UNKNOWN"
        scf_cycles = None
        geometry_converged = None

        if outcar_data:
            status = outcar_data.get("status", {})
            if status.get("finished"):
                convergence_status = "COMPLETED"

            # Refine status
            if status.get("electronic_converged") and status.get("ionic_converged") is not False:
                convergence_status = "CONVERGED"

            geometry_converged = status.get("ionic_converged")

            # Extract SCF cycles
            last_iter = status.get("last_iteration_index")
            if last_iter:
                scf_cycles = last_iter[1]

        # If we have energy but no status, assume at least partial success
        if final_energy is not None and convergence_status == "UNKNOWN":
            convergence_status = "COMPLETED"  # Tentative

        # Build metadata
        metadata = {
            "parser": "parsevasp",
            "has_timing_info": False,
        }

        if outcar_data:
            stats = outcar_data.get("stats", {})
            if stats:
                metadata["has_timing_info"] = True
                metadata["benchmark"] = stats  # Use parsevasp's stats structure directly

        if xml_data:
            forces = xml_data.get("forces")
            if forces is not None:
                # Calculate max force
                import math

                max_force = 0.0
                try:
                    for f in forces:
                        # Ensure f is iterable (e.g. list or numpy array)
                        norm = math.sqrt(sum(x * x for x in f))
                        if norm > max_force:
                            max_force = norm
                    metadata["rms_force"] = max_force
                except Exception:
                    pass

        return ParsingResult(
            success=(convergence_status in ["CONVERGED", "COMPLETED"]),
            final_energy=final_energy,
            energy_unit="eV",  # VASP is eV
            convergence_status=convergence_status,
            scf_cycles=scf_cycles,
            geometry_converged=geometry_converged,
            metadata=metadata,
        )

    async def parse(self, output_file: Path) -> ParsingResult:
        """Parse a VASP OUTCAR file into a structured ParsingResult.

        Args:
            output_file: Path to the OUTCAR file or directory containing it.

        Returns:
            ParsingResult with extracted energy, convergence, and metadata.
        """
        # VASP outputs to OUTCAR in the current directory
        # If output_file is a directory, look for OUTCAR
        if output_file.is_dir():
            output_file = output_file / "OUTCAR"

        if not output_file.exists():
            # Check if vasprun.xml exists even if OUTCAR doesn't (unlikely but possible)
            vasprun_path = output_file.parent / "vasprun.xml"
            if not vasprun_path.exists():
                return ParsingResult(
                    success=False,
                    final_energy=None,
                    energy_unit=self.get_energy_unit(),
                    convergence_status="UNKNOWN",
                    errors=[f"OUTCAR/vasprun.xml file not found in: {output_file.parent}"],
                )

        # Try to parse using parsevasp (from aiida-vasp) first
        try:
            parsevasp_result = self._parse_with_parsevasp(output_file)
            # Only accept parsevasp result if it found something useful (energy or success)
            if parsevasp_result and (
                parsevasp_result.success or parsevasp_result.final_energy is not None
            ):
                return parsevasp_result
        except Exception:
            # Fallback to manual parsing if parsevasp fails
            pass

        try:
            content = output_file.read_text()
        except Exception as e:
            return ParsingResult(
                success=False,
                final_energy=None,
                energy_unit=self.get_energy_unit(),
                convergence_status="UNKNOWN",
                errors=[f"Failed to read OUTCAR: {e}"],
            )

        errors: List[str] = []
        warnings: List[str] = []
        content_upper = content.upper()

        # Check for errors (exclude lines that are warnings)
        if "ERROR" in content_upper and "NO ERROR" not in content_upper:
            for line in content.split("\n"):
                line_lower = line.lower().strip()
                # Skip lines that are warnings (contain "error" as part of message but are warnings)
                if line_lower.startswith("warning"):
                    continue
                if "error" in line_lower and "no error" not in line_lower:
                    errors.append(line.strip())
                    if len(errors) >= 5:
                        break

        if "VERY BAD NEWS" in content_upper:
            errors.append("VASP reported very bad news - check input/output")

        # Extract warnings
        for pattern in self.WARNING_PATTERNS:
            for match in pattern.finditer(content):
                warn_text = match.group(0).strip()
                if warn_text not in warnings:
                    warnings.append(warn_text)
                if len(warnings) >= 10:
                    break

        # Extract final energy - prefer TOTEN, fall back to energy without entropy
        final_energy: Optional[float] = None
        toten_matches = self.TOTEN_PATTERN.findall(content)
        if toten_matches:
            try:
                final_energy = float(toten_matches[-1])
            except ValueError:
                pass

        if final_energy is None:
            e0_matches = self.E0_PATTERN.findall(content)
            if e0_matches:
                try:
                    final_energy = float(e0_matches[-1])
                except ValueError:
                    pass

        # Count SCF cycles (electronic steps in final ionic step)
        scf_cycles: Optional[int] = None
        # Find the last EDIFF block and count electronic steps
        ediff_blocks = self.IONIC_STEP_PATTERN.findall(content)
        if ediff_blocks:
            # Get content after last ionic step header
            last_block_pos = content.rfind("aborting loop because EDIFF is reached")
            if last_block_pos > 0:
                # Count electronic iterations before this
                block_content = content[:last_block_pos]
                last_ionic = block_content.rfind("FREE ENERGIE OF THE ION-ELECTRON SYSTEM")
                if last_ionic > 0:
                    recent_content = block_content[last_ionic:]
                    steps = self.ELECTRONIC_STEP_PATTERN.findall(recent_content)
                    if steps:
                        try:
                            scf_cycles = int(steps[-1][0])
                        except (ValueError, IndexError):
                            pass

        # Check for geometry convergence (for relaxation calculations)
        geometry_converged: Optional[bool] = None
        if "IBRION" in content:  # This is a relaxation calculation
            if "REACHED REQUIRED ACCURACY" in content_upper:
                geometry_converged = True
            elif "NSW" in content:
                # Check if max ionic steps reached
                nsw_match = re.search(r"NSW\s*=\s*(\d+)", content)
                if nsw_match:
                    max_steps = int(nsw_match.group(1))
                    ionic_count = len(
                        re.findall(r"FREE ENERGIE OF THE ION-ELECTRON SYSTEM", content)
                    )
                    if ionic_count >= max_steps:
                        geometry_converged = False

        # Determine success - VASP typically ends with timing info
        has_timing = (
            "TOTAL CPU TIME" in content_upper or "GENERAL TIMING AND ACCOUNTING" in content_upper
        )
        success = has_timing and len(errors) == 0

        # Determine convergence status
        if "REACHED REQUIRED ACCURACY" in content_upper:
            convergence_status = "CONVERGED"
        elif has_timing and len(errors) == 0:
            convergence_status = "COMPLETED"
        elif errors:
            convergence_status = "FAILED"
        else:
            convergence_status = "UNKNOWN"

        # Build metadata
        metadata = {
            "parser": "vasp",
            "has_timing_info": has_timing,
        }

        # Try to extract max force for geometry optimizations
        max_force_section = re.search(r"TOTAL-FORCE.*?LOOP\+", content, re.DOTALL)
        if max_force_section:
            rms_matches = self.MAX_FORCE_PATTERN.findall(max_force_section.group(0))
            if rms_matches:
                try:
                    metadata["rms_force"] = float(rms_matches[-1])
                except ValueError:
                    pass

        # Extract benchmark/timing data
        benchmark_metrics = self._extract_benchmark_data(content)
        if benchmark_metrics:
            metadata["benchmark"] = benchmark_metrics

        return ParsingResult(
            success=success,
            final_energy=final_energy,
            energy_unit=self.get_energy_unit(),
            convergence_status=convergence_status,
            scf_cycles=scf_cycles,
            geometry_converged=geometry_converged,
            errors=errors[:5],
            warnings=warnings[:5],
            metadata=metadata,
        )

    def get_energy_unit(self) -> str:
        """Return the energy unit (eV for VASP)."""
        return "eV"

    def _extract_benchmark_data(self, content: str) -> Dict[str, Any]:
        """Extract comprehensive timing and parallelization data for benchmarking.

        Parses the OUTCAR file to extract:
        - Total wall time and CPU time
        - SCF iteration timing (LOOP)
        - Ionic step timing (LOOP+)
        - Per-routine timing breakdown (POTLOK, SETDIJ, CHARGE, etc.)
        - Memory usage per core
        - Parallelization settings (NPAR, NCORE, KPAR)

        Args:
            content: OUTCAR file content.

        Returns:
            Dictionary with benchmark metrics suitable for JSON serialization.
        """
        metrics = VASPBenchmarkMetrics()

        # Extract total CPU time
        cpu_match = self.TOTAL_CPU_PATTERN.search(content)
        if cpu_match:
            try:
                metrics.total_cpu_time_sec = float(cpu_match.group(1))
            except ValueError:
                pass

        # Extract elapsed (wall) time
        elapsed_match = self.ELAPSED_TIME_PATTERN.search(content)
        if elapsed_match:
            try:
                metrics.elapsed_time_sec = float(elapsed_match.group(1))
            except ValueError:
                pass

        # Extract LOOP timing (SCF iterations - sum of all)
        loop_matches = self.LOOP_TIME_PATTERN.findall(content)
        if loop_matches:
            try:
                metrics.loop_cpu_time_sec = sum(float(m[0]) for m in loop_matches)
                metrics.loop_real_time_sec = sum(float(m[1]) for m in loop_matches)
                metrics.loop_count = len(loop_matches)
            except (ValueError, IndexError):
                pass

        # Extract LOOP+ timing (ionic steps - sum of all)
        loop_plus_matches = self.LOOP_PLUS_TIME_PATTERN.findall(content)
        if loop_plus_matches:
            try:
                metrics.loop_plus_cpu_time_sec = sum(float(m[0]) for m in loop_plus_matches)
                metrics.loop_plus_real_time_sec = sum(float(m[1]) for m in loop_plus_matches)
                metrics.loop_plus_count = len(loop_plus_matches)
            except (ValueError, IndexError):
                pass

        # Extract per-routine timing breakdown
        metrics.routine_timings = self._extract_routine_timings(content)

        # Extract memory usage
        memory_match = self.MEMORY_RANK0_PATTERN.search(content)
        if memory_match:
            try:
                # Convert kBytes to MB
                kb = float(memory_match.group(1))
                metrics.memory_per_core_mb = kb / 1024.0
            except ValueError:
                pass

        max_mem_match = self.MAX_MEMORY_PATTERN.search(content)
        if max_mem_match:
            try:
                # Convert kb to MB
                kb = float(max_mem_match.group(1))
                metrics.maximum_memory_used_mb = kb / 1024.0
            except ValueError:
                pass

        # Extract number of cores
        cores_match = self.NUM_CORES_PATTERN.search(content)
        if cores_match:
            try:
                metrics.num_cores = int(cores_match.group(1))
            except ValueError:
                pass

        # Extract parallelization settings
        npar_match = self.NPAR_PATTERN.search(content)
        if npar_match:
            try:
                metrics.npar = int(npar_match.group(1))
            except ValueError:
                pass

        ncore_match = self.NCORE_PATTERN.search(content)
        if ncore_match:
            try:
                metrics.ncore = int(ncore_match.group(1))
            except ValueError:
                pass

        kpar_match = self.KPAR_PATTERN.search(content)
        if kpar_match:
            try:
                metrics.kpar = int(kpar_match.group(1))
            except ValueError:
                pass

        # Calculate efficiency metrics
        if metrics.total_cpu_time_sec is not None and metrics.elapsed_time_sec is not None:
            if metrics.elapsed_time_sec > 0:
                metrics.cpu_to_wall_ratio = metrics.total_cpu_time_sec / metrics.elapsed_time_sec

                # Calculate parallel efficiency if we know the number of cores
                if metrics.num_cores is not None and metrics.num_cores > 0:
                    # Parallel efficiency = CPU time / (wall time * num_cores)
                    metrics.parallel_efficiency = metrics.total_cpu_time_sec / (
                        metrics.elapsed_time_sec * metrics.num_cores
                    )

        return metrics.to_dict()

    def _extract_routine_timings(self, content: str) -> Dict[str, Dict[str, float]]:
        """Extract per-routine timing breakdown from OUTCAR.

        Parses timing lines like:
            POTLOK:  cpu time   1.23: real time   1.45
            SETDIJ:  cpu time   0.56: real time   0.78

        Aggregates timings across all iterations.

        Args:
            content: OUTCAR file content.

        Returns:
            Dictionary mapping routine name to timing dict with 'cpu_sec',
            'real_sec', and 'count' keys.
        """
        routine_timings: Dict[str, Dict[str, float]] = {}

        # Find all routine timing lines
        for match in self.ROUTINE_TIME_PATTERN.finditer(content):
            routine_name = match.group(1).upper()

            # Only track known routines to avoid noise
            # But be flexible - track anything that looks like a routine
            try:
                cpu_time = float(match.group(2))
                real_time = float(match.group(3))
            except ValueError:
                continue

            if routine_name not in routine_timings:
                routine_timings[routine_name] = {
                    "cpu_sec": 0.0,
                    "real_sec": 0.0,
                    "count": 0,
                }

            routine_timings[routine_name]["cpu_sec"] += cpu_time
            routine_timings[routine_name]["real_sec"] += real_time
            routine_timings[routine_name]["count"] += 1

        return routine_timings

    def extract_timing_data(self, content: str) -> Dict[str, Any]:
        """Public method to extract timing data from OUTCAR content.

        This is the main entry point for benchmark timing extraction.
        Can be called independently of the full parse() method.

        Args:
            content: OUTCAR file content as string.

        Returns:
            Dictionary containing comprehensive benchmark metrics:
            - total_cpu_time_sec: Total CPU time in seconds
            - elapsed_time_sec: Wall clock time in seconds
            - loop_cpu_time_sec: Sum of LOOP (SCF) CPU times
            - loop_real_time_sec: Sum of LOOP (SCF) real times
            - loop_count: Number of SCF iterations
            - loop_plus_cpu_time_sec: Sum of LOOP+ (ionic) CPU times
            - loop_plus_real_time_sec: Sum of LOOP+ (ionic) real times
            - loop_plus_count: Number of ionic steps
            - routine_timings: Per-routine timing breakdown
            - memory_per_core_mb: Memory used per MPI rank in MB
            - maximum_memory_used_mb: Peak memory usage in MB
            - npar, ncore, kpar: Parallelization settings
            - num_cores: Number of cores used
            - cpu_to_wall_ratio: CPU time / wall time ratio
            - parallel_efficiency: Parallel scaling efficiency

        Example:
            >>> parser = VASPParser()
            >>> with open("OUTCAR") as f:
            ...     timing = parser.extract_timing_data(f.read())
            >>> print(f"Wall time: {timing.get('elapsed_time_sec', 0):.1f} sec")
        """
        return self._extract_benchmark_data(content)


# Singleton instance
_parser = VASPParser()

# Auto-register when module is imported
register_parser(DFTCode.VASP, _parser)


__all__ = ["VASPParser", "VASPBenchmarkMetrics"]
