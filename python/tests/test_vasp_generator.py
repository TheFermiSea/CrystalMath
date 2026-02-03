"""Tests for VASP input file generation utilities."""

import pytest


class TestIncarBuilder:
    """Tests for IncarBuilder class."""

    def test_from_preset_static(self):
        """Test STATIC preset configuration."""
        from crystalmath.vasp.incar import IncarBuilder, IncarPreset

        builder = IncarBuilder.from_preset(IncarPreset.STATIC)
        assert builder.ibrion == -1
        assert builder.nsw == 0

    def test_from_preset_relax(self):
        """Test RELAX preset configuration."""
        from crystalmath.vasp.incar import IncarBuilder, IncarPreset

        builder = IncarBuilder.from_preset(IncarPreset.RELAX)
        assert builder.ibrion == 2
        assert builder.nsw == 100
        assert builder.ediffg == -0.01

    def test_from_preset_dos(self):
        """Test DOS preset configuration."""
        from crystalmath.vasp.incar import IncarBuilder, IncarPreset

        builder = IncarBuilder.from_preset(IncarPreset.DOS)
        assert builder.ismear == -5
        assert builder.extra.get("NEDOS") == 2001

    def test_from_preset_with_overrides(self):
        """Test preset with parameter overrides."""
        from crystalmath.vasp.incar import IncarBuilder, IncarPreset

        builder = IncarBuilder.from_preset(IncarPreset.RELAX, nsw=200, encut=520)
        assert builder.nsw == 200
        assert builder.encut == 520

    def test_to_string_static(self):
        """Test INCAR string generation for static calculation."""
        from crystalmath.vasp.incar import IncarBuilder, IncarPreset

        builder = IncarBuilder.from_preset(IncarPreset.STATIC, encut=400)
        incar_str = builder.to_string()

        assert "ENCUT = 400" in incar_str
        assert "EDIFF" in incar_str
        assert "ISMEAR" in incar_str
        assert "IBRION" not in incar_str  # Static doesn't include ionic params

    def test_to_string_relax(self):
        """Test INCAR string generation for relaxation."""
        from crystalmath.vasp.incar import IncarBuilder, IncarPreset

        builder = IncarBuilder.from_preset(IncarPreset.RELAX, encut=520)
        incar_str = builder.to_string()

        assert "ENCUT = 520" in incar_str
        assert "IBRION = 2" in incar_str
        assert "NSW = 100" in incar_str
        assert "EDIFFG" in incar_str


class TestKpointsBuilder:
    """Tests for KpointsBuilder class."""

    def test_gamma_centered(self):
        """Test Gamma-centered mesh creation."""
        from crystalmath.vasp.kpoints import KpointsBuilder

        mesh = KpointsBuilder.gamma_centered(4, 4, 4)
        assert mesh.mesh == (4, 4, 4)
        assert mesh.shift == (0.0, 0.0, 0.0)

    def test_kpoints_mesh_to_string(self):
        """Test KPOINTS string generation."""
        from crystalmath.vasp.kpoints import KpointsMesh

        mesh = KpointsMesh(mesh=(4, 4, 2))
        kpoints_str = mesh.to_string()

        assert "Automatic mesh" in kpoints_str
        assert "Monkhorst-Pack" in kpoints_str
        assert "4  4  2" in kpoints_str

    @pytest.mark.skipif(
        not pytest.importorskip("pymatgen", reason="pymatgen not available"),
        reason="pymatgen not available",
    )
    def test_from_density(self):
        """Test automatic mesh from k-point density."""
        from pymatgen.core import Lattice, Structure

        from crystalmath.vasp.kpoints import KpointsBuilder

        # Create a simple cubic structure
        lattice = Lattice.cubic(5.0)
        structure = Structure(lattice, ["Si"], [[0, 0, 0]])

        mesh = KpointsBuilder.from_density(structure, kppra=1000)

        # Should have roughly equal k-points in each direction for cubic
        assert mesh.mesh[0] > 0
        assert mesh.mesh[1] > 0
        assert mesh.mesh[2] > 0
        assert mesh.mesh[0] == mesh.mesh[1] == mesh.mesh[2]  # Cubic symmetry


class TestVaspInputGenerator:
    """Tests for VaspInputGenerator class."""

    @pytest.mark.skipif(
        not pytest.importorskip("pymatgen", reason="pymatgen not available"),
        reason="pymatgen not available",
    )
    def test_generate_complete_inputs(self):
        """Test complete VASP input generation."""
        from pymatgen.core import Lattice, Structure

        from crystalmath.vasp import IncarPreset, VaspInputGenerator

        # Create a simple structure
        lattice = Lattice.cubic(5.43)
        structure = Structure(
            lattice, ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]]
        )

        generator = VaspInputGenerator(structure, preset=IncarPreset.STATIC)
        inputs = generator.generate()

        # Check all files generated
        assert inputs.poscar is not None
        assert inputs.incar is not None
        assert inputs.kpoints is not None
        assert inputs.potcar_symbols == ["Si"]

        # Check POSCAR content
        assert "Si" in inputs.poscar
        assert "5.43" in inputs.poscar or "5.4300" in inputs.poscar

        # Check INCAR content
        assert "ENCUT" in inputs.incar

        # Check KPOINTS content
        assert "Monkhorst-Pack" in inputs.kpoints

    @pytest.mark.skipif(
        not pytest.importorskip("pymatgen", reason="pymatgen not available"),
        reason="pymatgen not available",
    )
    def test_estimate_encut(self):
        """Test ENCUT estimation from elements."""
        from pymatgen.core import Lattice, Structure

        from crystalmath.vasp import VaspInputGenerator

        # Si structure - ENMAX ~245 eV, estimated ENCUT ~320 eV (1.3x)
        lattice = Lattice.cubic(5.43)
        structure = Structure(lattice, ["Si"], [[0, 0, 0]])

        generator = VaspInputGenerator(structure)
        # Should be about 1.3 * 245 = 318.5
        assert 300 < generator.encut < 350

    @pytest.mark.skipif(
        not pytest.importorskip("pymatgen", reason="pymatgen not available"),
        reason="pymatgen not available",
    )
    def test_to_dict_serializable(self):
        """Test VaspInputs is JSON-serializable."""
        import json

        from pymatgen.core import Lattice, Structure

        from crystalmath.vasp import VaspInputGenerator

        lattice = Lattice.cubic(5.0)
        structure = Structure(lattice, ["Si"], [[0, 0, 0]])

        generator = VaspInputGenerator(structure)
        inputs = generator.generate()

        # Should serialize to JSON without error
        data = inputs.to_dict()
        json_str = json.dumps(data)
        assert len(json_str) > 0

        # Should deserialize back
        from crystalmath.vasp import VaspInputs

        restored = VaspInputs.from_dict(json.loads(json_str))
        assert restored.potcar_symbols == inputs.potcar_symbols


class TestStructureToPoscar:
    """Tests for structure_to_poscar function."""

    @pytest.mark.skipif(
        not pytest.importorskip("pymatgen", reason="pymatgen not available"),
        reason="pymatgen not available",
    )
    def test_structure_to_poscar_basic(self):
        """Test basic POSCAR generation."""
        from pymatgen.core import Lattice, Structure

        from crystalmath.integrations.pymatgen_bridge import structure_to_poscar

        lattice = Lattice.cubic(5.0)
        structure = Structure(lattice, ["Si", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])

        poscar = structure_to_poscar(structure)

        # Should contain lattice constant
        assert "5.0" in poscar or "5.000" in poscar
        # Should contain species
        assert "Si" in poscar
        assert "O" in poscar

    @pytest.mark.skipif(
        not pytest.importorskip("pymatgen", reason="pymatgen not available"),
        reason="pymatgen not available",
    )
    def test_structure_to_poscar_custom_comment(self):
        """Test POSCAR with custom comment."""
        from pymatgen.core import Lattice, Structure

        from crystalmath.integrations.pymatgen_bridge import structure_to_poscar

        lattice = Lattice.cubic(5.0)
        structure = Structure(lattice, ["Si"], [[0, 0, 0]])

        poscar = structure_to_poscar(structure, comment="My custom structure")

        # First line should be the comment
        first_line = poscar.split("\n")[0]
        assert "My custom structure" in first_line
