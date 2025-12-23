from pathlib import Path

from src.core.codes import (
    DFTCode,
    InvocationStyle,
    get_code_config,
    list_available_codes,
)
from src.core.codes.crystal import CRYSTAL_CONFIG


class TestCrystalConfig:
    def test_crystal_registered(self):
        assert DFTCode.CRYSTAL in list_available_codes()

    def test_get_crystal_config(self):
        config = get_code_config(DFTCode.CRYSTAL)
        assert config.name == "crystal"
        assert config.display_name == "CRYSTAL23"

    def test_crystal_input_extensions(self):
        assert CRYSTAL_CONFIG.input_extensions == [".d12"]

    def test_crystal_executables(self):
        assert CRYSTAL_CONFIG.serial_executable == "crystalOMP"
        assert CRYSTAL_CONFIG.parallel_executable == "PcrystalOMP"

    def test_crystal_invocation_style(self):
        assert CRYSTAL_CONFIG.invocation_style == InvocationStyle.STDIN

    def test_build_serial_command(self):
        cmd = CRYSTAL_CONFIG.build_command(
            Path("input.d12"), Path("output.out"), parallel=False
        )
        assert "crystalOMP" in cmd[-1]
        assert "< input.d12" in cmd[-1]
        assert "> output.out" in cmd[-1]

    def test_build_parallel_command(self):
        cmd = CRYSTAL_CONFIG.build_command(
            Path("input.d12"), Path("output.out"), parallel=True
        )
        assert "PcrystalOMP" in cmd[-1]

    def test_auxiliary_inputs_mapping(self):
        assert CRYSTAL_CONFIG.auxiliary_inputs[".gui"] == "fort.34"
        assert CRYSTAL_CONFIG.auxiliary_inputs[".f9"] == "fort.20"

    def test_auxiliary_outputs_mapping(self):
        assert CRYSTAL_CONFIG.auxiliary_outputs["fort.9"] == ".f9"
        assert CRYSTAL_CONFIG.auxiliary_outputs["fort.98"] == ".f98"
