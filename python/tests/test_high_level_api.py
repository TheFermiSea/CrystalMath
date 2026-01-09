"""Tests for high-level API (api.py module).

This module tests the high-level API including:
- HighThroughput.get_supported_properties()
- HighThroughput.get_property_info()
- HighThroughput._validate_properties()
- HighThroughputConfig dataclass
- PROPERTY_DEFINITIONS dictionary
- AnalysisResults export methods

Tests are designed to verify API behavior without running actual calculations.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from dataclasses import dataclass
from datetime import datetime

from crystalmath.protocols import WorkflowType


# Check if optional dependencies are available
try:
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_structure() -> Mock:
    """Create a mock pymatgen Structure."""
    mock = Mock()
    mock.formula = "NbOCl2"
    mock.composition.reduced_formula = "NbOCl2"
    mock.num_sites = 8
    mock.volume = 150.0
    mock.lattice.abc = (5.0, 5.0, 10.0)
    mock.lattice.angles = (90.0, 90.0, 90.0)
    return mock


@pytest.fixture
def sample_cif_file(tmp_path: Path) -> Path:
    """Create a sample CIF file."""
    cif_content = """data_Test
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 10.0
loop_
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si 0.0 0.0 0.0
"""
    cif_path = tmp_path / "test.cif"
    cif_path.write_text(cif_content)
    return cif_path


# =============================================================================
# Test HighThroughput.get_supported_properties()
# =============================================================================


class TestGetSupportedProperties:
    """Tests for HighThroughput.get_supported_properties()."""

    def test_returns_list(self) -> None:
        """Test that method returns a list."""
        from crystalmath.high_level.api import HighThroughput

        properties = HighThroughput.get_supported_properties()
        assert isinstance(properties, list)

    def test_contains_standard_properties(self) -> None:
        """Test that standard properties are included."""
        from crystalmath.high_level.api import HighThroughput

        properties = HighThroughput.get_supported_properties()

        # Standard DFT properties
        assert "scf" in properties
        assert "relax" in properties
        assert "bands" in properties
        assert "dos" in properties

    def test_contains_mechanical_properties(self) -> None:
        """Test that mechanical properties are included."""
        from crystalmath.high_level.api import HighThroughput

        properties = HighThroughput.get_supported_properties()

        assert "elastic" in properties
        assert "phonon" in properties

    def test_contains_optical_properties(self) -> None:
        """Test that optical properties are included."""
        from crystalmath.high_level.api import HighThroughput

        properties = HighThroughput.get_supported_properties()

        assert "gw" in properties
        assert "bse" in properties

    def test_contains_advanced_properties(self) -> None:
        """Test that advanced properties are included."""
        from crystalmath.high_level.api import HighThroughput

        properties = HighThroughput.get_supported_properties()

        assert "dielectric" in properties
        assert "eos" in properties
        assert "neb" in properties

    def test_no_duplicates(self) -> None:
        """Test that there are no duplicate properties."""
        from crystalmath.high_level.api import HighThroughput

        properties = HighThroughput.get_supported_properties()
        assert len(properties) == len(set(properties))


# =============================================================================
# Test HighThroughput.get_property_info()
# =============================================================================


class TestGetPropertyInfo:
    """Tests for HighThroughput.get_property_info()."""

    def test_returns_dict(self) -> None:
        """Test that method returns a dictionary."""
        from crystalmath.high_level.api import HighThroughput

        info = HighThroughput.get_property_info("bands")
        assert isinstance(info, dict)

    def test_contains_required_keys(self) -> None:
        """Test that info contains required keys."""
        from crystalmath.high_level.api import HighThroughput

        info = HighThroughput.get_property_info("bands")

        assert "name" in info
        assert "workflow_type" in info
        assert "default_code" in info
        assert "dependencies" in info

    def test_bands_info(self) -> None:
        """Test property info for bands calculation."""
        from crystalmath.high_level.api import HighThroughput

        info = HighThroughput.get_property_info("bands")

        assert info["name"] == "bands"
        assert info["workflow_type"] == WorkflowType.BANDS.value
        assert "scf" in info["dependencies"]

    def test_gw_info(self) -> None:
        """Test property info for GW calculation."""
        from crystalmath.high_level.api import HighThroughput

        info = HighThroughput.get_property_info("gw")

        assert info["name"] == "gw"
        assert info["workflow_type"] == WorkflowType.GW.value
        assert info["default_code"] == "yambo"

    def test_bse_info(self) -> None:
        """Test property info for BSE calculation."""
        from crystalmath.high_level.api import HighThroughput

        info = HighThroughput.get_property_info("bse")

        assert info["name"] == "bse"
        assert "gw" in info["dependencies"]

    @pytest.mark.parametrize(
        "property_name",
        ["scf", "relax", "bands", "dos", "phonon", "elastic", "gw", "bse"],
    )
    def test_all_properties_have_info(self, property_name: str) -> None:
        """Test that all supported properties have info."""
        from crystalmath.high_level.api import HighThroughput

        info = HighThroughput.get_property_info(property_name)
        assert info["name"] == property_name

    def test_unknown_property_raises(self) -> None:
        """Test that unknown property raises KeyError."""
        from crystalmath.high_level.api import HighThroughput

        with pytest.raises(KeyError):
            HighThroughput.get_property_info("unknown_property")


# =============================================================================
# Test HighThroughput._validate_properties()
# =============================================================================


class TestValidateProperties:
    """Tests for HighThroughput._validate_properties()."""

    def test_valid_properties(self) -> None:
        """Test validation of valid properties."""
        from crystalmath.high_level.api import HighThroughput

        is_valid, issues = HighThroughput._validate_properties(["scf", "bands", "dos"])

        assert is_valid is True
        assert len(issues) == 0

    def test_invalid_property(self) -> None:
        """Test validation fails for invalid property."""
        from crystalmath.high_level.api import HighThroughput

        is_valid, issues = HighThroughput._validate_properties(["invalid_prop"])

        assert is_valid is False
        assert len(issues) > 0
        assert "invalid_prop" in issues[0]

    def test_mixed_valid_invalid(self) -> None:
        """Test validation with mixed valid and invalid properties."""
        from crystalmath.high_level.api import HighThroughput

        is_valid, issues = HighThroughput._validate_properties(
            ["scf", "invalid1", "bands", "invalid2"]
        )

        assert is_valid is False
        assert len(issues) == 2

    def test_empty_list(self) -> None:
        """Test validation of empty property list."""
        from crystalmath.high_level.api import HighThroughput

        is_valid, issues = HighThroughput._validate_properties([])

        # Empty list is valid (no invalid properties)
        assert is_valid is True

    @pytest.mark.parametrize(
        "properties",
        [
            ["scf"],
            ["scf", "bands"],
            ["relax", "scf", "bands", "dos"],
            ["scf", "gw", "bse"],
        ],
    )
    def test_valid_combinations(self, properties: List[str]) -> None:
        """Test validation of valid property combinations."""
        from crystalmath.high_level.api import HighThroughput

        is_valid, issues = HighThroughput._validate_properties(properties)
        assert is_valid is True


# =============================================================================
# Test HighThroughput entry points (stub verification)
# =============================================================================


class TestHighThroughputEntryPoints:
    """Tests for HighThroughput entry point methods."""

    def test_run_standard_analysis_raises_not_implemented(
        self, mock_structure: Mock
    ) -> None:
        """Test that run_standard_analysis raises NotImplementedError."""
        from crystalmath.high_level.api import HighThroughput

        with pytest.raises(NotImplementedError):
            HighThroughput.run_standard_analysis(
                structure=mock_structure,
                properties=["bands"],
            )

    def test_from_mp_raises_not_implemented(self) -> None:
        """Test that from_mp raises NotImplementedError."""
        from crystalmath.high_level.api import HighThroughput

        with pytest.raises(NotImplementedError):
            HighThroughput.from_mp("mp-149", properties=["bands"])

    def test_from_poscar_raises_not_implemented(self, tmp_path: Path) -> None:
        """Test that from_poscar raises NotImplementedError."""
        poscar_path = tmp_path / "POSCAR"
        poscar_path.write_text("test")

        from crystalmath.high_level.api import HighThroughput

        with pytest.raises(NotImplementedError):
            HighThroughput.from_poscar(str(poscar_path), properties=["bands"])

    def test_from_structure_raises_not_implemented(self, mock_structure: Mock) -> None:
        """Test that from_structure raises NotImplementedError."""
        from crystalmath.high_level.api import HighThroughput

        with pytest.raises(NotImplementedError):
            HighThroughput.from_structure(mock_structure, properties=["bands"])

    def test_from_aiida_raises_not_implemented(self) -> None:
        """Test that from_aiida raises NotImplementedError."""
        from crystalmath.high_level.api import HighThroughput

        with pytest.raises(NotImplementedError):
            HighThroughput.from_aiida(12345, properties=["bands"])


# =============================================================================
# Test HighThroughputConfig
# =============================================================================


class TestHighThroughputConfig:
    """Tests for HighThroughputConfig dataclass."""

    def test_create_config(self) -> None:
        """Test creating configuration."""
        from crystalmath.high_level.api import HighThroughputConfig

        config = HighThroughputConfig(
            properties=["bands", "dos"],
            protocol="moderate",
            cluster="beefcake2",
        )

        assert config.properties == ["bands", "dos"]
        assert config.protocol == "moderate"
        assert config.cluster == "beefcake2"

    def test_default_values(self) -> None:
        """Test default configuration values."""
        from crystalmath.high_level.api import HighThroughputConfig

        config = HighThroughputConfig(properties=["scf"])

        assert config.protocol == "moderate"
        assert config.codes is None
        assert config.cluster is None
        assert config.checkpoint_interval == 1

    @pytest.mark.parametrize("protocol", ["fast", "moderate", "precise"])
    def test_protocol_options(self, protocol: str) -> None:
        """Test different protocol options."""
        from crystalmath.high_level.api import HighThroughputConfig

        config = HighThroughputConfig(
            properties=["scf"],
            protocol=protocol,
        )

        assert config.protocol == protocol


# =============================================================================
# Test Property Definitions
# =============================================================================


class TestPropertyDefinitions:
    """Tests for property definitions."""

    def test_property_definitions_exist(self) -> None:
        """Test that property definitions dictionary exists."""
        from crystalmath.high_level.api import PROPERTY_DEFINITIONS

        assert isinstance(PROPERTY_DEFINITIONS, dict)
        assert len(PROPERTY_DEFINITIONS) > 0

    def test_scf_definition(self) -> None:
        """Test SCF property definition."""
        from crystalmath.high_level.api import PROPERTY_DEFINITIONS

        assert "scf" in PROPERTY_DEFINITIONS
        wf_type, code, deps = PROPERTY_DEFINITIONS["scf"]
        assert wf_type == WorkflowType.SCF
        assert deps == []

    def test_bands_definition(self) -> None:
        """Test bands property definition."""
        from crystalmath.high_level.api import PROPERTY_DEFINITIONS

        assert "bands" in PROPERTY_DEFINITIONS
        wf_type, code, deps = PROPERTY_DEFINITIONS["bands"]
        assert wf_type == WorkflowType.BANDS
        assert "scf" in deps

    def test_gw_definition(self) -> None:
        """Test GW property definition."""
        from crystalmath.high_level.api import PROPERTY_DEFINITIONS

        assert "gw" in PROPERTY_DEFINITIONS
        wf_type, code, deps = PROPERTY_DEFINITIONS["gw"]
        assert wf_type == WorkflowType.GW
        assert code == "yambo"

    def test_bse_definition(self) -> None:
        """Test BSE property definition."""
        from crystalmath.high_level.api import PROPERTY_DEFINITIONS

        assert "bse" in PROPERTY_DEFINITIONS
        wf_type, code, deps = PROPERTY_DEFINITIONS["bse"]
        assert wf_type == WorkflowType.BSE
        assert "gw" in deps


# =============================================================================
# Test AnalysisResults
# =============================================================================


class TestAnalysisResults:
    """Tests for AnalysisResults dataclass."""

    def test_create_results(self) -> None:
        """Test creating analysis results."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )

        assert results.formula == "NbOCl2"
        assert results.band_gap_ev == 1.85

    def test_default_values(self) -> None:
        """Test default values in AnalysisResults."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults()

        assert results.formula == ""
        assert results.band_gap_ev is None
        assert results.structure is None
        assert results.is_metal is False

    def test_to_dict(self) -> None:
        """Test exporting to dictionary."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )
        data = results.to_dict()

        assert isinstance(data, dict)
        assert data["formula"] == "NbOCl2"
        assert "electronic" in data
        assert data["electronic"]["band_gap_ev"] == 1.85

    def test_to_json_string(self) -> None:
        """Test exporting to JSON string."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )
        json_str = results.to_json()

        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert data["formula"] == "NbOCl2"

    def test_to_json_file(self, tmp_path: Path) -> None:
        """Test exporting to JSON file."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )
        output_file = tmp_path / "results.json"

        results.to_json(str(output_file))

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["formula"] == "NbOCl2"


class TestAnalysisResultsPlotting:
    """Tests for AnalysisResults plotting methods."""

    @pytest.mark.skipif(not HAS_MATPLOTLIB, reason="matplotlib not installed")
    def test_plot_bands_no_data(self) -> None:
        """Test plot_bands raises error when no data."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(formula="NbOCl2")
        # No band_structure data

        with pytest.raises(ValueError):
            results.plot_bands()

    @pytest.mark.skipif(not HAS_MATPLOTLIB, reason="matplotlib not installed")
    def test_plot_dos_no_data(self) -> None:
        """Test plot_dos raises error when no data."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(formula="NbOCl2")
        # No dos data

        with pytest.raises(ValueError):
            results.plot_dos()

    @pytest.mark.skipif(not HAS_MATPLOTLIB, reason="matplotlib not installed")
    def test_plot_phonons_no_data(self) -> None:
        """Test plot_phonons raises error when no data."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(formula="NbOCl2")
        # No phonon_dispersion data

        with pytest.raises(ValueError):
            results.plot_phonons()

    @pytest.mark.skipif(not HAS_PLOTLY, reason="plotly not installed")
    def test_iplot_bands_no_data(self) -> None:
        """Test iplot_bands raises error when no data."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(formula="NbOCl2")

        with pytest.raises(ValueError):
            results.iplot_bands()


class TestAnalysisResultsLatex:
    """Tests for AnalysisResults LaTeX export methods."""

    def test_to_latex_table(self) -> None:
        """Test exporting to LaTeX table."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )
        latex = results.to_latex_table()

        assert isinstance(latex, str)
        assert "\\begin{table}" in latex
        assert "NbOCl2" in latex

    def test_to_latex_table_booktabs(self) -> None:
        """Test LaTeX table with booktabs format."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )
        latex = results.to_latex_table(format_spec="booktabs")

        assert "\\toprule" in latex
        assert "\\midrule" in latex
        assert "\\bottomrule" in latex

    def test_to_latex_table_simple(self) -> None:
        """Test LaTeX table with simple format."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )
        latex = results.to_latex_table(format_spec="simple")

        assert "\\hline" in latex

    def test_to_latex_table_file(self, tmp_path: Path) -> None:
        """Test exporting LaTeX table to file."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )
        output_file = tmp_path / "table.tex"

        results.to_latex_table(str(output_file))

        assert output_file.exists()
        content = output_file.read_text()
        assert "\\begin{table}" in content


# =============================================================================
# Test Data Classes from results.py
# =============================================================================


class TestBandStructureData:
    """Tests for BandStructureData container."""

    def test_create_band_structure_data(self) -> None:
        """Test creating band structure data."""
        from crystalmath.high_level.results import BandStructureData

        mock_energies = Mock()
        mock_kpoints = Mock()

        data = BandStructureData(
            energies=mock_energies,
            kpoints=mock_kpoints,
            fermi_energy=0.0,
        )

        assert data.energies == mock_energies
        assert data.fermi_energy == 0.0

    def test_band_structure_with_labels(self) -> None:
        """Test band structure with k-point labels."""
        from crystalmath.high_level.results import BandStructureData

        data = BandStructureData(
            energies=Mock(),
            kpoints=Mock(),
            kpoint_labels=["G", "X", "M", "G"],
            kpoint_positions=[0, 50, 100, 150],
        )

        assert len(data.kpoint_labels) == 4
        assert data.kpoint_labels[0] == "G"

    def test_band_structure_defaults(self) -> None:
        """Test BandStructureData default values."""
        from crystalmath.high_level.results import BandStructureData

        data = BandStructureData(
            energies=Mock(),
            kpoints=Mock(),
        )

        assert data.kpoint_labels == []
        assert data.kpoint_positions == []
        assert data.fermi_energy == 0.0
        assert data.is_spin_polarized is False


class TestDOSData:
    """Tests for DOSData container."""

    def test_create_dos_data(self) -> None:
        """Test creating DOS data."""
        from crystalmath.high_level.results import DOSData

        data = DOSData(
            energies=Mock(),
            total_dos=Mock(),
            fermi_energy=0.0,
        )

        assert data.fermi_energy == 0.0

    def test_dos_with_projected(self) -> None:
        """Test DOS with projected data."""
        from crystalmath.high_level.results import DOSData

        projected = {"s": Mock(), "p": Mock(), "d": Mock()}
        data = DOSData(
            energies=Mock(),
            total_dos=Mock(),
            projected_dos=projected,
        )

        assert "s" in data.projected_dos

    def test_dos_defaults(self) -> None:
        """Test DOSData default values."""
        from crystalmath.high_level.results import DOSData

        data = DOSData(
            energies=Mock(),
            total_dos=Mock(),
        )

        assert data.projected_dos is None
        assert data.fermi_energy == 0.0


class TestPhononData:
    """Tests for PhononData container."""

    def test_create_phonon_data(self) -> None:
        """Test creating phonon data."""
        from crystalmath.high_level.results import PhononData

        data = PhononData(
            frequencies=Mock(),
            qpoints=Mock(),
        )

        assert data.frequencies is not None

    def test_phonon_defaults(self) -> None:
        """Test PhononData default values."""
        from crystalmath.high_level.results import PhononData

        data = PhononData(
            frequencies=Mock(),
            qpoints=Mock(),
        )

        assert data.qpoint_labels == []
        assert data.qpoint_positions == []


class TestElasticTensor:
    """Tests for ElasticTensor container."""

    def test_create_elastic_tensor(self) -> None:
        """Test creating elastic tensor data."""
        from crystalmath.high_level.results import ElasticTensor

        voigt = Mock()
        data = ElasticTensor(voigt=voigt)

        assert data.voigt == voigt

    def test_elastic_tensor_defaults(self) -> None:
        """Test ElasticTensor default values."""
        from crystalmath.high_level.results import ElasticTensor

        data = ElasticTensor(voigt=Mock())

        assert data.compliance is None


class TestDielectricTensor:
    """Tests for DielectricTensor container."""

    def test_create_dielectric_tensor(self) -> None:
        """Test creating dielectric tensor data."""
        from crystalmath.high_level.results import DielectricTensor

        static = Mock()
        data = DielectricTensor(static=static)

        assert data.static == static

    def test_dielectric_tensor_defaults(self) -> None:
        """Test DielectricTensor default values."""
        from crystalmath.high_level.results import DielectricTensor

        data = DielectricTensor(static=Mock())

        assert data.high_freq is None
        assert data.born_charges is None


# =============================================================================
# Test Integration
# =============================================================================


class TestAPIIntegration:
    """Integration tests for high-level API."""

    def test_property_info_matches_definitions(self) -> None:
        """Test that property info matches definitions."""
        from crystalmath.high_level.api import (
            HighThroughput,
            PROPERTY_DEFINITIONS,
        )

        for prop_name in PROPERTY_DEFINITIONS:
            info = HighThroughput.get_property_info(prop_name)

            wf_type, code, deps = PROPERTY_DEFINITIONS[prop_name]
            assert info["workflow_type"] == wf_type.value
            assert info["default_code"] == code
            assert info["dependencies"] == deps

    def test_results_export_roundtrip(self, tmp_path: Path) -> None:
        """Test results export and reimport."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="NbOCl2",
            band_gap_ev=1.85,
        )

        # Export to JSON
        json_file = tmp_path / "results.json"
        results.to_json(str(json_file))

        # Read back
        data = json.loads(json_file.read_text())

        assert data["formula"] == results.formula
        assert data["electronic"]["band_gap_ev"] == results.band_gap_ev


# =============================================================================
# Test Module Exports
# =============================================================================


class TestModuleExports:
    """Tests for module exports."""

    def test_api_module_has_highthroughput(self) -> None:
        """Test that api module exports HighThroughput."""
        from crystalmath.high_level import api

        assert hasattr(api, "HighThroughput")

    def test_api_module_has_config(self) -> None:
        """Test that api module exports HighThroughputConfig."""
        from crystalmath.high_level import api

        assert hasattr(api, "HighThroughputConfig")

    def test_api_module_has_property_definitions(self) -> None:
        """Test that api module exports PROPERTY_DEFINITIONS."""
        from crystalmath.high_level import api

        assert hasattr(api, "PROPERTY_DEFINITIONS")

    def test_results_module_has_analysis_results(self) -> None:
        """Test that results module exports AnalysisResults."""
        from crystalmath.high_level import results

        assert hasattr(results, "AnalysisResults")

    def test_results_module_has_band_structure_data(self) -> None:
        """Test that results module exports BandStructureData."""
        from crystalmath.high_level import results

        assert hasattr(results, "BandStructureData")

    def test_results_module_has_dos_data(self) -> None:
        """Test that results module exports DOSData."""
        from crystalmath.high_level import results

        assert hasattr(results, "DOSData")

    def test_results_module_has_phonon_data(self) -> None:
        """Test that results module exports PhononData."""
        from crystalmath.high_level import results

        assert hasattr(results, "PhononData")

    def test_results_module_has_elastic_tensor(self) -> None:
        """Test that results module exports ElasticTensor."""
        from crystalmath.high_level import results

        assert hasattr(results, "ElasticTensor")

    def test_results_module_has_dielectric_tensor(self) -> None:
        """Test that results module exports DielectricTensor."""
        from crystalmath.high_level import results

        assert hasattr(results, "DielectricTensor")
