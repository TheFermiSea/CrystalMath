"""AnalysisResults container with publication export capabilities.

This module provides the unified results container that aggregates all
computed properties and enables export to various publication formats.

Example:
    results = HighThroughput.run_standard_analysis(...)

    # Access properties
    print(f"Band gap: {results.band_gap_ev:.2f} eV")

    # Export to pandas
    df = results.to_dataframe()
    df.to_csv("results.csv")

    # Plot
    fig = results.plot_bands()
    fig.savefig("bands.png")

    # LaTeX table
    latex = results.to_latex_table()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    import pandas as pd
    import plotly.graph_objects as go
    from pymatgen.core import Structure


@dataclass
class BandStructureData:
    """Container for band structure data.

    Attributes:
        energies: Band energies [n_kpoints, n_bands] in eV
        kpoints: K-point coordinates [n_kpoints, 3]
        kpoint_labels: High-symmetry point labels
        kpoint_positions: Positions of labeled k-points
        fermi_energy: Fermi energy in eV
        is_spin_polarized: Whether calculation is spin-polarized
    """

    energies: Any  # numpy array
    kpoints: Any  # numpy array
    kpoint_labels: List[str] = field(default_factory=list)
    kpoint_positions: List[int] = field(default_factory=list)
    fermi_energy: float = 0.0
    is_spin_polarized: bool = False


@dataclass
class DOSData:
    """Container for density of states data.

    Attributes:
        energies: Energy grid in eV
        total_dos: Total DOS [n_energies]
        projected_dos: Orbital-projected DOS dict
        fermi_energy: Fermi energy in eV
    """

    energies: Any  # numpy array
    total_dos: Any  # numpy array
    projected_dos: Optional[Dict[str, Any]] = None
    fermi_energy: float = 0.0


@dataclass
class PhononData:
    """Container for phonon dispersion data.

    Attributes:
        frequencies: Phonon frequencies [n_qpoints, n_branches] in THz
        qpoints: Q-point coordinates
        qpoint_labels: High-symmetry point labels
        qpoint_positions: Positions of labeled q-points
    """

    frequencies: Any  # numpy array
    qpoints: Any  # numpy array
    qpoint_labels: List[str] = field(default_factory=list)
    qpoint_positions: List[int] = field(default_factory=list)


@dataclass
class ElasticTensor:
    """Container for elastic tensor data.

    Attributes:
        voigt: Elastic tensor in Voigt notation [6, 6] GPa
        compliance: Compliance tensor [6, 6] 1/GPa
    """

    voigt: Any  # numpy array [6, 6]
    compliance: Optional[Any] = None


@dataclass
class DielectricTensor:
    """Container for dielectric tensor data.

    Attributes:
        static: Static dielectric tensor [3, 3]
        high_freq: High-frequency dielectric tensor [3, 3]
        born_charges: Born effective charges
    """

    static: Any  # numpy array [3, 3]
    high_freq: Optional[Any] = None
    born_charges: Optional[Any] = None


@dataclass
class AnalysisResults:
    """Container for all computed properties.

    This is the main results container returned by HighThroughput methods.
    It provides access to all computed properties and methods for exporting
    to various publication-ready formats.

    Attributes:
        formula: Chemical formula
        structure: Final structure (pymatgen Structure)
        space_group: Space group symbol

        band_gap_ev: DFT band gap in eV
        is_direct_gap: Whether gap is direct
        fermi_energy_ev: Fermi energy in eV
        is_metal: Whether system is metallic

        band_structure: Full band structure data
        dos: Density of states data

        gw_gap_ev: GW quasiparticle gap in eV
        gw_corrections: GW corrections dict
        optical_gap_ev: BSE optical gap in eV
        exciton_binding_ev: Exciton binding energy in eV

        elastic_tensor: Elastic tensor data
        bulk_modulus_gpa: Bulk modulus in GPa
        shear_modulus_gpa: Shear modulus in GPa
        youngs_modulus_gpa: Young's modulus in GPa
        poisson_ratio: Poisson ratio

        phonon_dispersion: Phonon dispersion data
        has_imaginary_modes: Whether structure is dynamically stable

        dielectric_tensor: Dielectric tensor data
        static_dielectric: Isotropic static dielectric constant
        high_freq_dielectric: Isotropic high-frequency dielectric constant

        workflow_id: ID of the executed workflow
        completed_at: Completion timestamp
        total_cpu_hours: Total CPU time used
    """

    # Structure info
    formula: str = ""
    structure: Optional["Structure"] = None
    space_group: str = ""

    # Electronic properties
    band_gap_ev: Optional[float] = None
    is_direct_gap: Optional[bool] = None
    fermi_energy_ev: Optional[float] = None
    is_metal: bool = False

    # Band structure data
    band_structure: Optional[BandStructureData] = None
    dos: Optional[DOSData] = None

    # GW/BSE results
    gw_gap_ev: Optional[float] = None
    gw_corrections: Optional[Dict[str, float]] = None
    optical_gap_ev: Optional[float] = None
    exciton_binding_ev: Optional[float] = None

    # Mechanical properties
    elastic_tensor: Optional[ElasticTensor] = None
    bulk_modulus_gpa: Optional[float] = None
    shear_modulus_gpa: Optional[float] = None
    youngs_modulus_gpa: Optional[float] = None
    poisson_ratio: Optional[float] = None

    # Phonon properties
    phonon_dispersion: Optional[PhononData] = None
    has_imaginary_modes: Optional[bool] = None

    # Dielectric properties
    dielectric_tensor: Optional[DielectricTensor] = None
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

    # =========================================================================
    # DataFrame Export
    # =========================================================================

    def to_dataframe(self) -> "pd.DataFrame":
        """Export scalar properties to pandas DataFrame.

        Creates a single-row DataFrame with all scalar properties.
        Useful for combining results from multiple materials.

        Returns:
            DataFrame with property names as columns

        Example:
            df = results.to_dataframe()
            df.to_csv("properties.csv", index=False)
        """
        import pandas as pd

        data = {
            "formula": self.formula,
            "space_group": self.space_group,
            "band_gap_ev": self.band_gap_ev,
            "is_direct_gap": self.is_direct_gap,
            "is_metal": self.is_metal,
            "fermi_energy_ev": self.fermi_energy_ev,
            "gw_gap_ev": self.gw_gap_ev,
            "optical_gap_ev": self.optical_gap_ev,
            "exciton_binding_ev": self.exciton_binding_ev,
            "bulk_modulus_gpa": self.bulk_modulus_gpa,
            "shear_modulus_gpa": self.shear_modulus_gpa,
            "youngs_modulus_gpa": self.youngs_modulus_gpa,
            "poisson_ratio": self.poisson_ratio,
            "static_dielectric": self.static_dielectric,
            "high_freq_dielectric": self.high_freq_dielectric,
            "has_imaginary_modes": self.has_imaginary_modes,
            "total_cpu_hours": self.total_cpu_hours,
        }
        return pd.DataFrame([data])

    def to_dict(self) -> Dict[str, Any]:
        """Export all data to dictionary.

        Returns nested dictionary including array data (band structure,
        phonons, etc.) as lists.

        Returns:
            Nested dictionary with all results
        """
        result = {
            "formula": self.formula,
            "space_group": self.space_group,
            "electronic": {
                "band_gap_ev": self.band_gap_ev,
                "is_direct_gap": self.is_direct_gap,
                "is_metal": self.is_metal,
                "fermi_energy_ev": self.fermi_energy_ev,
            },
            "gw_bse": {
                "gw_gap_ev": self.gw_gap_ev,
                "optical_gap_ev": self.optical_gap_ev,
                "exciton_binding_ev": self.exciton_binding_ev,
            },
            "mechanical": {
                "bulk_modulus_gpa": self.bulk_modulus_gpa,
                "shear_modulus_gpa": self.shear_modulus_gpa,
                "youngs_modulus_gpa": self.youngs_modulus_gpa,
                "poisson_ratio": self.poisson_ratio,
            },
            "dielectric": {
                "static": self.static_dielectric,
                "high_freq": self.high_freq_dielectric,
            },
            "phonon": {
                "has_imaginary_modes": self.has_imaginary_modes,
            },
            "metadata": {
                "workflow_id": self.workflow_id,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "total_cpu_hours": self.total_cpu_hours,
            },
        }
        return result

    def to_json(self, path: Optional[Union[str, Path]] = None) -> str:
        """Export results to JSON.

        Args:
            path: Optional file path (returns string if None)

        Returns:
            JSON string

        Example:
            # Get JSON string
            json_str = results.to_json()

            # Write to file
            results.to_json("results.json")
        """
        import json

        json_str = json.dumps(self.to_dict(), indent=2, default=str)

        if path:
            Path(path).write_text(json_str)

        return json_str

    # =========================================================================
    # Matplotlib Plotting
    # =========================================================================

    def plot_bands(
        self,
        ax: Optional["plt.Axes"] = None,
        color: str = "blue",
        linewidth: float = 1.0,
        **kwargs: Any,
    ) -> "plt.Figure":
        """Plot band structure.

        Args:
            ax: Matplotlib axes (creates new figure if None)
            color: Line color
            linewidth: Line width
            **kwargs: Additional matplotlib options

        Returns:
            Matplotlib figure

        Example:
            fig = results.plot_bands()
            fig.savefig("bands.png", dpi=300)
        """
        import matplotlib.pyplot as plt

        if self.band_structure is None:
            raise ValueError("No band structure data available")

        if ax is None:
            fig, ax = plt.subplots(figsize=(8, 6))
        else:
            fig = ax.get_figure()

        # Stub implementation - will use actual data in Phase 3
        ax.set_xlabel("k-path")
        ax.set_ylabel("Energy (eV)")
        ax.set_title(f"Band Structure: {self.formula}")
        ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)

        return fig

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

        Example:
            fig = results.plot_dos(projected=True)
            fig.savefig("dos.png", dpi=300)
        """
        import matplotlib.pyplot as plt

        if self.dos is None:
            raise ValueError("No DOS data available")

        if ax is None:
            fig, ax = plt.subplots(figsize=(6, 8))
        else:
            fig = ax.get_figure()

        ax.set_xlabel("DOS (states/eV)")
        ax.set_ylabel("Energy (eV)")
        ax.set_title(f"Density of States: {self.formula}")

        return fig

    def plot_bands_dos(
        self,
        figsize: Tuple[float, float] = (10, 6),
        **kwargs: Any,
    ) -> "plt.Figure":
        """Plot combined band structure and DOS.

        Creates a side-by-side plot with band structure on the left
        and DOS on the right (standard publication format).

        Args:
            figsize: Figure size in inches
            **kwargs: Additional options

        Returns:
            Matplotlib figure

        Example:
            fig = results.plot_bands_dos()
            fig.savefig("electronic_structure.png", dpi=300)
        """
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(
            1, 2,
            figsize=figsize,
            sharey=True,
            gridspec_kw={"width_ratios": [3, 1]}
        )

        # Band structure
        ax1.set_xlabel("k-path")
        ax1.set_ylabel("Energy (eV)")
        ax1.set_title(f"Band Structure: {self.formula}")

        # DOS
        ax2.set_xlabel("DOS")
        ax2.set_title("DOS")

        plt.tight_layout()
        return fig

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

        Example:
            fig = results.plot_phonons()
            fig.savefig("phonons.png", dpi=300)
        """
        import matplotlib.pyplot as plt

        if self.phonon_dispersion is None:
            raise ValueError("No phonon data available")

        if ax is None:
            fig, ax = plt.subplots(figsize=(8, 6))
        else:
            fig = ax.get_figure()

        ax.set_xlabel("q-path")
        ax.set_ylabel("Frequency (THz)")
        ax.set_title(f"Phonon Dispersion: {self.formula}")
        ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)

        return fig

    def plot_optical(
        self,
        ax: Optional["plt.Axes"] = None,
        component: str = "xx",
        **kwargs: Any,
    ) -> "plt.Figure":
        """Plot optical absorption spectrum.

        Args:
            ax: Matplotlib axes
            component: Tensor component to plot (xx, yy, zz, xy, etc.)
            **kwargs: Additional options

        Returns:
            Matplotlib figure
        """
        import matplotlib.pyplot as plt

        if ax is None:
            fig, ax = plt.subplots(figsize=(8, 6))
        else:
            fig = ax.get_figure()

        ax.set_xlabel("Energy (eV)")
        ax.set_ylabel("Absorption (a.u.)")
        ax.set_title(f"Optical Absorption: {self.formula}")

        return fig

    # =========================================================================
    # Interactive Plotting (Plotly)
    # =========================================================================

    def iplot_bands(self, **kwargs: Any) -> "go.Figure":
        """Interactive band structure plot using Plotly.

        Creates an interactive plot suitable for Jupyter notebooks
        with hover information and zoom capabilities.

        Args:
            **kwargs: Plotly options

        Returns:
            Plotly figure

        Example:
            fig = results.iplot_bands()
            fig.show()
        """
        import plotly.graph_objects as go

        if self.band_structure is None:
            raise ValueError("No band structure data available")

        fig = go.Figure()
        fig.update_layout(
            title=f"Band Structure: {self.formula}",
            xaxis_title="k-path",
            yaxis_title="Energy (eV)",
        )

        return fig

    def iplot_dos(self, **kwargs: Any) -> "go.Figure":
        """Interactive DOS plot using Plotly.

        Args:
            **kwargs: Plotly options

        Returns:
            Plotly figure
        """
        import plotly.graph_objects as go

        if self.dos is None:
            raise ValueError("No DOS data available")

        fig = go.Figure()
        fig.update_layout(
            title=f"Density of States: {self.formula}",
            xaxis_title="DOS (states/eV)",
            yaxis_title="Energy (eV)",
        )

        return fig

    # =========================================================================
    # LaTeX Export
    # =========================================================================

    def to_latex_table(
        self,
        path: Optional[Union[str, Path]] = None,
        properties: Optional[List[str]] = None,
        format_spec: str = "booktabs",
    ) -> str:
        """Export properties as LaTeX table.

        Args:
            path: Optional file path (returns string if None)
            properties: Properties to include (all scalar properties if None)
            format_spec: Table format ("booktabs" or "simple")

        Returns:
            LaTeX table string

        Example:
            latex = results.to_latex_table()
            print(latex)

            # Write to file
            results.to_latex_table("table.tex")
        """
        lines = []

        if format_spec == "booktabs":
            lines.append(r"\begin{table}[htbp]")
            lines.append(r"\centering")
            lines.append(rf"\caption{{Calculated properties of {self.formula}}}")
            lines.append(r"\label{tab:properties}")
            lines.append(r"\begin{tabular}{lS[table-format=3.3]}")
            lines.append(r"\toprule")
            lines.append(r"Property & {Value} \\")
            lines.append(r"\midrule")
        else:
            lines.append(r"\begin{tabular}{ll}")
            lines.append(r"\hline")
            lines.append(r"Property & Value \\")
            lines.append(r"\hline")

        # Add properties
        prop_lines = []
        if self.band_gap_ev is not None:
            prop_lines.append(rf"Band gap (DFT) & \SI{{{self.band_gap_ev:.3f}}}{{\electronvolt}} \\")
        if self.gw_gap_ev is not None:
            prop_lines.append(rf"Band gap (GW) & \SI{{{self.gw_gap_ev:.3f}}}{{\electronvolt}} \\")
        if self.optical_gap_ev is not None:
            prop_lines.append(rf"Optical gap (BSE) & \SI{{{self.optical_gap_ev:.3f}}}{{\electronvolt}} \\")
        if self.exciton_binding_ev is not None:
            prop_lines.append(rf"Exciton binding & \SI{{{self.exciton_binding_ev:.3f}}}{{\electronvolt}} \\")
        if self.bulk_modulus_gpa is not None:
            prop_lines.append(rf"Bulk modulus & \SI{{{self.bulk_modulus_gpa:.1f}}}{{\giga\pascal}} \\")
        if self.shear_modulus_gpa is not None:
            prop_lines.append(rf"Shear modulus & \SI{{{self.shear_modulus_gpa:.1f}}}{{\giga\pascal}} \\")
        if self.static_dielectric is not None:
            prop_lines.append(rf"Static dielectric & {self.static_dielectric:.2f} \\")

        lines.extend(prop_lines)

        if format_spec == "booktabs":
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            lines.append(r"\end{table}")
        else:
            lines.append(r"\hline")
            lines.append(r"\end{tabular}")

        latex = "\n".join(lines)

        if path:
            Path(path).write_text(latex)

        return latex

    def to_latex_si_table(
        self,
        path: Optional[Union[str, Path]] = None,
    ) -> str:
        """Export as LaTeX SI table with proper units.

        Uses siunitx package formatting for consistent unit display.

        Args:
            path: Optional file path

        Returns:
            LaTeX table with siunitx formatting
        """
        return self.to_latex_table(path=path, format_spec="booktabs")
