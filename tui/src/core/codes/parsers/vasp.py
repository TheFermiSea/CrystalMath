"""VASP output parser implementation.

Parses VASP OUTCAR files to extract energy, convergence status,
forces, and other calculation results.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, List

from ..base import DFTCode
from .base import OutputParser, ParsingResult, register_parser


class VASPParser(OutputParser):
    """Parser for VASP output files (OUTCAR).

    Supports SCF, geometry optimization, and molecular dynamics outputs.
    """

    # Regex patterns for VASP OUTCAR parsing
    # Free energy: "  free  energy   TOTEN  =       -85.54234987 eV"
    TOTEN_PATTERN = re.compile(r"free\s+energy\s+TOTEN\s*=\s*([-\d.]+)\s*eV", re.IGNORECASE)

    # Energy without entropy: "  energy  without entropy =       -85.53789012"
    E0_PATTERN = re.compile(r"energy\s+without entropy\s*=\s*([-\d.]+)")

    # Electronic steps: "       N       E                     dE"
    # Requires MULTILINE so ^ matches at start of each line, not just string start
    ELECTRONIC_STEP_PATTERN = re.compile(
        r"^\s+(\d+)\s+([-\d.E+]+)\s+([-\d.E+]+)", re.MULTILINE
    )

    # Ionic step (for geometry optimization)
    IONIC_STEP_PATTERN = re.compile(r"------------------------ aborting loop because EDIFF is reached ----------------------")

    # Forces: "  TOTAL-FORCE (eV/Angst)"
    MAX_FORCE_PATTERN = re.compile(r"RMS\s+([-\d.E+]+)")

    # Timing patterns for benchmarking
    # "   LOOP:  cpu time  123.45: real time  234.56"
    LOOP_TIME_PATTERN = re.compile(r"LOOP:\s+cpu time\s+([\d.]+):\s+real time\s+([\d.]+)")
    # " Total CPU time used (sec):     1234.567"
    TOTAL_CPU_PATTERN = re.compile(r"Total CPU time used \(sec\):\s+([\d.]+)")
    # " Elapsed time (sec):     2345.678"
    ELAPSED_TIME_PATTERN = re.compile(r"Elapsed time \(sec\):\s+([\d.]+)")
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
            return ParsingResult(
                success=False,
                final_energy=None,
                energy_unit=self.get_energy_unit(),
                convergence_status="UNKNOWN",
                errors=[f"OUTCAR file not found: {output_file}"],
            )

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
                    ionic_count = len(re.findall(r"FREE ENERGIE OF THE ION-ELECTRON SYSTEM", content))
                    if ionic_count >= max_steps:
                        geometry_converged = False

        # Determine success - VASP typically ends with timing info
        has_timing = "TOTAL CPU TIME" in content_upper or "GENERAL TIMING AND ACCOUNTING" in content_upper
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

    def _extract_benchmark_data(self, content: str) -> dict:
        """Extract timing and parallelization data for benchmarking.

        Args:
            content: OUTCAR file content.

        Returns:
            Dictionary with benchmark metrics.
        """
        benchmark = {}

        # Extract total CPU time
        cpu_match = self.TOTAL_CPU_PATTERN.search(content)
        if cpu_match:
            try:
                benchmark["total_cpu_time_sec"] = float(cpu_match.group(1))
            except ValueError:
                pass

        # Extract elapsed (wall) time
        elapsed_match = self.ELAPSED_TIME_PATTERN.search(content)
        if elapsed_match:
            try:
                benchmark["elapsed_time_sec"] = float(elapsed_match.group(1))
            except ValueError:
                pass

        # Extract loop timing (sum of all LOOP times)
        loop_matches = self.LOOP_TIME_PATTERN.findall(content)
        if loop_matches:
            try:
                total_loop_cpu = sum(float(m[0]) for m in loop_matches)
                total_loop_real = sum(float(m[1]) for m in loop_matches)
                benchmark["loop_cpu_time_sec"] = total_loop_cpu
                benchmark["loop_real_time_sec"] = total_loop_real
                benchmark["loop_count"] = len(loop_matches)
            except (ValueError, IndexError):
                pass

        # Extract parallelization settings
        npar_match = self.NPAR_PATTERN.search(content)
        if npar_match:
            try:
                benchmark["npar"] = int(npar_match.group(1))
            except ValueError:
                pass

        ncore_match = self.NCORE_PATTERN.search(content)
        if ncore_match:
            try:
                benchmark["ncore"] = int(ncore_match.group(1))
            except ValueError:
                pass

        kpar_match = self.KPAR_PATTERN.search(content)
        if kpar_match:
            try:
                benchmark["kpar"] = int(kpar_match.group(1))
            except ValueError:
                pass

        # Calculate efficiency if we have both CPU and elapsed time
        if "total_cpu_time_sec" in benchmark and "elapsed_time_sec" in benchmark:
            elapsed = benchmark["elapsed_time_sec"]
            if elapsed > 0:
                # Parallel efficiency: CPU time / (elapsed time * num_procs)
                # Without knowing num_procs, we estimate from the ratio
                benchmark["cpu_to_wall_ratio"] = benchmark["total_cpu_time_sec"] / elapsed

        return benchmark


# Singleton instance
_parser = VASPParser()

# Auto-register when module is imported
register_parser(DFTCode.VASP, _parser)


__all__ = ["VASPParser"]
