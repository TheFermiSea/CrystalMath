"""Pytest configuration for AiiDA tests.

This module provides fixtures and mocks for testing AiiDA integration
without requiring AiiDA to be installed.
"""

import sys
from unittest.mock import MagicMock, Mock
import pytest


def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--aiida",
        action="store_true",
        default=False,
        help="Run AiiDA E2E integration tests (requires infrastructure)",
    )


# Create mock AiiDA modules before any tests import them
aiida_mock = MagicMock()
aiida_mock.orm = MagicMock()
aiida_mock.engine = MagicMock()
aiida_mock.parsers = MagicMock()
aiida_mock.common = MagicMock()
aiida_mock.common.constants = MagicMock()

# Mock common AiiDA classes
aiida_mock.orm.CalcJobNode = type("CalcJobNode", (), {})
aiida_mock.orm.WorkChainNode = type("WorkChainNode", (), {})
aiida_mock.orm.Computer = MagicMock()
aiida_mock.orm.QueryBuilder = MagicMock
aiida_mock.orm.Dict = MagicMock
aiida_mock.orm.SinglefileData = MagicMock
aiida_mock.orm.StructureData = MagicMock
aiida_mock.orm.load_node = MagicMock()
aiida_mock.orm.load_code = MagicMock()

# Mock engine functions
aiida_mock.engine.submit = MagicMock()
aiida_mock.engine.run = MagicMock()

# Mock Parser base class
aiida_mock.parsers.Parser = type("Parser", (), {})

# Mock load_profile function
aiida_mock.load_profile = MagicMock()

# Mock elements for atomic number mapping
aiida_mock.common.constants.elements = {
    1: "H",
    6: "C",
    7: "N",
    8: "O",
    14: "Si",
}

# Install mocks in sys.modules
sys.modules["aiida"] = aiida_mock
sys.modules["aiida.orm"] = aiida_mock.orm
sys.modules["aiida.engine"] = aiida_mock.engine
sys.modules["aiida.parsers"] = aiida_mock.parsers
sys.modules["aiida.common"] = aiida_mock.common
sys.modules["aiida.common.constants"] = aiida_mock.common.constants

# Mock CRYSTALpytools (optional dependency)
crystalpytools_mock = MagicMock()
crystalpytools_mock.crystal_io = MagicMock()
crystalpytools_mock.crystal_io.Crystal_output = MagicMock

sys.modules["CRYSTALpytools"] = crystalpytools_mock
sys.modules["CRYSTALpytools.crystal_io"] = crystalpytools_mock.crystal_io
