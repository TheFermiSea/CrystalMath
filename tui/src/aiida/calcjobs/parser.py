"""
AiiDA Parser for CRYSTAL23 output files.

This module provides the Crystal23Parser class for parsing CRYSTAL23
calculation output and extracting results into AiiDA data nodes.

The parser handles:
    - SCF convergence and final energy
    - Geometry optimization results
    - Basis set information
    - Electronic structure (band gap, etc.)
    - Error detection and reporting
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from aiida import orm
from aiida.parsers import Parser

if TYPE_CHECKING:
    from aiida.engine import ExitCode


class Crystal23Parser(Parser):
    """
    Parser for CRYSTAL23 calculation output.

    Parses the main OUTPUT file and extracts key results into
    AiiDA Dict and StructureData nodes.
    """

    def parse(self, **kwargs) -> "ExitCode" | None:
        """
        Parse CRYSTAL23 output files.

        Returns:
            ExitCode on failure, None on success.
        """
        # Get output filename from calculation options
        output_filename = self.node.get_option("output_filename")

        # Check if output file exists
        try:
            output_file = self.retrieved.get_object_content(output_filename)
        except FileNotFoundError:
            return self.exit_codes.ERROR_MISSING_OUTPUT

        # Try CRYSTALpytools first, fall back to manual parsing
        try:
            results = self._parse_with_crystalpytools(output_file)
        except ImportError:
            results = self._parse_manual(output_file)
        except Exception as e:
            self.logger.warning(f"CRYSTALpytools parsing failed: {e}")
            results = self._parse_manual(output_file)

        if results is None:
            return self.exit_codes.ERROR_OUTPUT_PARSING

        # Check for calculation errors
        if not results.get("completed", False):
            if "insufficient memory" in results.get("error_message", "").lower():
                return self.exit_codes.ERROR_INSUFFICIENT_MEMORY
            if "timeout" in results.get("error_message", "").lower():
                return self.exit_codes.ERROR_TIMEOUT
            if not results.get("scf_converged", True):
                return self.exit_codes.ERROR_SCF_NOT_CONVERGED
            if not results.get("geom_converged", True):
                return self.exit_codes.ERROR_GEOMETRY_NOT_CONVERGED

        # Store output parameters
        self.out("output_parameters", orm.Dict(dict=results))

        # Store optimized structure if geometry optimization
        if "final_structure" in results:
            self._store_output_structure(results["final_structure"])

        # Store wavefunction if available
        self._store_wavefunction()

        return None

    def _parse_with_crystalpytools(self, output_content: str) -> dict:
        """
        Parse output using CRYSTALpytools library.

        Args:
            output_content: Content of the OUTPUT file.

        Returns:
            Dictionary of parsed results.
        """
        from CRYSTALpytools.crystal_io import Crystal_output

        # CRYSTALpytools expects a file path, so we create a temporary one
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(output_content)
            temp_path = f.name

        try:
            cry_out = Crystal_output(temp_path)

            results = {
                "parser": "CRYSTALpytools",
                "completed": cry_out.is_terminated_normally(),
                "scf_converged": cry_out.is_converged(),
            }

            # Extract energy
            try:
                results["final_energy_hartree"] = cry_out.get_final_energy()
                results["final_energy_ev"] = results["final_energy_hartree"] * 27.2114
            except Exception:
                pass

            # Extract SCF info
            try:
                results["scf_iterations"] = cry_out.get_scf_iterations()
            except Exception:
                pass

            # Extract geometry optimization info
            try:
                if cry_out.is_geometry_optimization():
                    results["is_geometry_optimization"] = True
                    results["geom_converged"] = cry_out.is_opt_converged()
                    results["optimization_steps"] = cry_out.get_opt_steps()
            except Exception:
                pass

            # Extract band gap
            try:
                gap = cry_out.get_band_gap()
                if gap is not None:
                    results["band_gap_ev"] = gap
            except Exception:
                pass

            return results

        finally:
            Path(temp_path).unlink(missing_ok=True)

    def _parse_manual(self, output_content: str) -> dict:
        """
        Manual parsing of CRYSTAL23 output.

        Fallback parser when CRYSTALpytools is not available.

        Args:
            output_content: Content of the OUTPUT file.

        Returns:
            Dictionary of parsed results.
        """
        results = {
            "parser": "manual",
            "completed": False,
            "scf_converged": False,
        }

        lines = output_content.split("\n")

        # Check for normal termination
        for line in reversed(lines[-100:]):
            if "EEEEEEEE" in line and "TERMINATION" in line:
                results["completed"] = True
                break

        # Find final energy
        energy_pattern = re.compile(
            r"TOTAL ENERGY\(DFT\)\(AU\)\s*\(\s*\d+\)\s+([-\d.]+)"
        )
        scf_converged_pattern = re.compile(r"== SCF ENDED")

        for i, line in enumerate(lines):
            # SCF convergence
            if "== SCF ENDED" in line and "CONVERGE" in line:
                results["scf_converged"] = True

            # Final energy
            match = energy_pattern.search(line)
            if match:
                energy = float(match.group(1))
                results["final_energy_hartree"] = energy
                results["final_energy_ev"] = energy * 27.2114

            # SCF iterations
            if "CYC" in line and "ETOT(AU)" in line:
                # Count following SCF cycle lines
                cycle_count = 0
                for j in range(i + 1, min(i + 1000, len(lines))):
                    if re.match(r"\s+\d+\s+[-\d.]+", lines[j]):
                        cycle_count += 1
                    elif "==" in lines[j]:
                        break
                if cycle_count > 0:
                    results["scf_iterations"] = cycle_count

            # Geometry optimization
            if "OPTOPTOPTOPT" in line or "GEOMETRY OPTIMIZATION" in line:
                results["is_geometry_optimization"] = True

            # Geometry convergence
            if "CONVERGENCE TESTS SATISFIED" in line:
                results["geom_converged"] = True

            # Optimization steps
            opt_step_match = re.match(
                r"\s*OPTIMIZATION - PAIR DISTANCE EVALUATION\s*(\d+)", line
            )
            if opt_step_match:
                results["optimization_steps"] = int(opt_step_match.group(1))

            # Band gap
            gap_match = re.search(
                r"(DIRECT|INDIRECT)\s+BAND\s+GAP:\s+([\d.]+)\s+EV", line
            )
            if gap_match:
                results["band_gap_type"] = gap_match.group(1).lower()
                results["band_gap_ev"] = float(gap_match.group(2))

        # Error detection
        error_patterns = [
            (r"ERROR .* INSUFFICIENT MEMORY", "Insufficient memory"),
            (r"ERROR .* TIMEOUT", "Calculation timeout"),
            (r"SCF DID NOT CONVERGE", "SCF did not converge"),
            (r"GEOMETRY DID NOT CONVERGE", "Geometry did not converge"),
        ]

        for pattern, message in error_patterns:
            if re.search(pattern, output_content, re.IGNORECASE):
                results["error_message"] = message
                results["completed"] = False
                break

        return results

    def _store_output_structure(self, structure_data: dict) -> None:
        """
        Store optimized structure as StructureData.

        Args:
            structure_data: Dictionary with cell and positions.
        """
        # Parse structure from fort.34 if available
        try:
            fort34_content = self.retrieved.get_object_content("fort.34")
            structure = self._parse_fort34(fort34_content)
            if structure:
                self.out("output_structure", structure)
        except FileNotFoundError:
            pass

    def _parse_fort34(self, content: str) -> orm.StructureData | None:
        """
        Parse fort.34 (external geometry) file into StructureData.

        Args:
            content: Content of fort.34 file.

        Returns:
            StructureData or None if parsing fails.
        """
        lines = content.strip().split("\n")

        try:
            # fort.34 format varies, this is a simplified parser
            # Line 0: dimensionality flag
            # Lines 1-3: cell vectors
            # Following: atomic positions

            cell = []
            positions = []
            symbols = []

            # Find cell vectors (3 lines of 3 floats)
            cell_start = None
            for i, line in enumerate(lines):
                parts = line.split()
                if len(parts) == 3:
                    try:
                        [float(x) for x in parts]
                        if cell_start is None:
                            cell_start = i
                    except ValueError:
                        continue

            if cell_start is None:
                return None

            # Read cell vectors
            for i in range(3):
                parts = lines[cell_start + i].split()
                cell.append([float(x) for x in parts])

            # Read atoms (atomic number, x, y, z)
            for line in lines[cell_start + 3 :]:
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        atomic_num = int(parts[0])
                        pos = [float(parts[1]), float(parts[2]), float(parts[3])]

                        # Map atomic number to symbol
                        from aiida.common.constants import elements

                        symbol = elements.get(atomic_num, "X")
                        symbols.append(symbol)
                        positions.append(pos)
                    except ValueError:
                        continue

            if not cell or not positions:
                return None

            # Create StructureData
            structure = orm.StructureData(cell=cell)
            for symbol, pos in zip(symbols, positions):
                structure.append_atom(position=pos, symbols=symbol)

            return structure

        except Exception as e:
            self.logger.warning(f"Failed to parse fort.34: {e}")
            return None

    def _store_wavefunction(self) -> None:
        """Store converged wavefunction file."""
        try:
            # Check for fort.9 (binary wavefunction)
            fort9_content = self.retrieved.get_object_content("fort.9", mode="rb")
            wavefunction = orm.SinglefileData(file=fort9_content, filename="fort.9")
            self.out("wavefunction", wavefunction)
        except FileNotFoundError:
            pass
