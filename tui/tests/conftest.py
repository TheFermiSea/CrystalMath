"""Pytest configuration for AiiDA tests.

This module provides fixtures and mocks for testing AiiDA integration
without requiring AiiDA to be installed.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = REPO_ROOT / "python"
TUI_ROOT = REPO_ROOT / "tui"
if CORE_PATH.exists() and str(CORE_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_PATH))
if TUI_ROOT.exists() and str(TUI_ROOT) not in sys.path:
    sys.path.insert(0, str(TUI_ROOT))


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


class MockDict(dict):
    """Mock AiiDA Dict that behaves like a dict with get_dict() method."""

    def __init__(self, dict=None, **kwargs):  # noqa: A002
        if dict is not None:
            super().__init__(dict)
        else:
            super().__init__(**kwargs)

    def get_dict(self):
        """Return the underlying dictionary."""
        return dict(self)


aiida_mock.orm.Dict = MockDict


class MockStr(str):
    """Mock AiiDA Str that behaves like a string."""

    def __new__(cls, value=""):
        return super().__new__(cls, value)

    @property
    def value(self):
        return str(self)


class MockBool:
    """Mock AiiDA Bool that behaves like a boolean."""

    def __init__(self, value=False):
        self._value = value

    @property
    def value(self):
        return self._value

    def __bool__(self):
        return self._value


class MockList(list):
    """Mock AiiDA List that behaves like a list."""

    def __init__(self, list=None):  # noqa: A002
        if list is not None:
            super().__init__(list)
        else:
            super().__init__()

    def get_list(self):
        return list(self)


aiida_mock.orm.Str = MockStr
aiida_mock.orm.Bool = MockBool
aiida_mock.orm.List = MockList
aiida_mock.orm.SinglefileData = MagicMock
aiida_mock.orm.StructureData = MagicMock
aiida_mock.orm.BandsData = MagicMock
aiida_mock.orm.XyData = MagicMock
aiida_mock.orm.AbstractCode = MagicMock
aiida_mock.orm.load_node = MagicMock()
aiida_mock.orm.load_code = MagicMock()

# Mock engine functions
aiida_mock.engine.submit = MagicMock()
aiida_mock.engine.run = MagicMock()

# Make calcfunction decorator pass through the function (for testing logic)
def _passthrough_decorator(func):
    """Mock calcfunction that returns the original function."""
    return func

aiida_mock.engine.calcfunction = _passthrough_decorator

# Mock ToContext for workflow steps
aiida_mock.engine.ToContext = MagicMock()

# Mock if_ conditional for workflow outlines
def _mock_if(condition):
    """Mock if_ that returns a callable for outline definition."""
    def wrapper(*steps):
        return steps
    return wrapper

aiida_mock.engine.if_ = _mock_if


class MockWorkChainSpec:
    """Mock WorkChain specification for testing."""

    def __init__(self):
        self.inputs = {}
        self.outputs = {}
        self.exit_codes = {}
        self._outline = []

    def input(self, name, valid_type=None, required=True, default=None, help=None):
        """Define an input."""
        self.inputs[name] = {
            "valid_type": valid_type,
            "required": required,
            "default": default,
            "help": help,
        }

    def output(self, name, valid_type=None, required=True, help=None):
        """Define an output."""
        self.outputs[name] = {
            "valid_type": valid_type,
            "required": required,
            "help": help,
        }

    def exit_code(self, code, name, message):
        """Define an exit code."""
        self.exit_codes[code] = {"name": name, "message": message}

    def outline(self, *steps):
        """Define the workflow outline."""
        self._outline = list(steps)


class MockWorkChain:
    """Mock WorkChain base class for testing."""

    REQUIRED_CODES = []
    _spec = None

    @classmethod
    def spec(cls):
        """Return the workflow specification."""
        if cls._spec is None:
            cls._spec = MockWorkChainSpec()
            if hasattr(cls, "define"):
                cls.define(cls._spec)
        return cls._spec

    @classmethod
    def define(cls, spec):
        """Define the workflow specification (to be overridden)."""
        pass

    @classmethod
    def get_builder(cls):
        """Get a builder for the workchain."""
        return MagicMock()


aiida_mock.engine.WorkChain = MockWorkChain

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
