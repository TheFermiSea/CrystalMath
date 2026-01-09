"""PropertyCalculator registry for automatic code selection.

This module provides intelligent code selection based on property type,
cluster availability, and code compatibility requirements.

Example:
    from crystalmath.high_level.registry import PropertyCalculator

    # Automatic selection
    code = PropertyCalculator.select_code("bands", available_codes=["vasp", "crystal23"])

    # Check compatibility
    is_valid, issues = PropertyCalculator.validate_workflow_codes(steps)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from crystalmath.protocols import DFTCode, WorkflowStep, WorkflowType

logger = logging.getLogger(__name__)


class PropertyCalculator:
    """Registry for property -> code mapping.

    Determines which DFT code is best suited for each property type,
    considering property requirements, available codes on the cluster,
    and user preferences.

    The selection algorithm considers:
    1. Property requirements (e.g., BSE requires GW which requires specific codes)
    2. Available codes on the target cluster
    3. User preferences (explicit code overrides)
    4. Code compatibility for multi-code workflows
    """

    # Default code preferences for each property (ordered by preference)
    DEFAULT_CODES: Dict[str, List[DFTCode]] = {
        # Ground state DFT
        "scf": ["vasp", "crystal23", "quantum_espresso"],
        "relax": ["vasp", "crystal23", "quantum_espresso"],
        "bands": ["vasp", "crystal23", "quantum_espresso"],
        "dos": ["vasp", "crystal23", "quantum_espresso"],

        # Mechanical properties
        "elastic": ["vasp"],
        "phonon": ["vasp", "crystal23", "quantum_espresso"],

        # Electronic response
        "dielectric": ["vasp", "crystal23"],

        # Many-body perturbation theory
        "gw": ["yambo", "berkeleygw"],
        "bse": ["yambo", "berkeleygw"],

        # Transport
        "transport": ["vasp"],  # with boltztrap2 post-processing

        # Transition states
        "neb": ["vasp"],

        # Convergence and EOS
        "convergence": ["vasp", "crystal23", "quantum_espresso"],
        "eos": ["vasp", "crystal23", "quantum_espresso"],
    }

    # Code compatibility matrix for multi-code workflows
    # (source_code, target_code) -> can_transfer
    CODE_COMPATIBILITY: Dict[Tuple[DFTCode, DFTCode], bool] = {
        # DFT -> GW code compatibility (wavefunction transfer)
        ("vasp", "yambo"): True,
        ("quantum_espresso", "yambo"): True,
        ("crystal23", "yambo"): True,  # Via p2y converter
        ("vasp", "berkeleygw"): True,
        ("quantum_espresso", "berkeleygw"): True,

        # Same code (always compatible)
        ("vasp", "vasp"): True,
        ("crystal23", "crystal23"): True,
        ("quantum_espresso", "quantum_espresso"): True,
        ("yambo", "yambo"): True,
        ("berkeleygw", "berkeleygw"): True,
    }

    # Properties that require special codes
    REQUIRED_CODES: Dict[str, List[DFTCode]] = {
        "gw": ["yambo", "berkeleygw"],
        "bse": ["yambo", "berkeleygw"],
    }

    @classmethod
    def select_code(
        cls,
        property_name: str,
        available_codes: Optional[List[DFTCode]] = None,
        user_preference: Optional[DFTCode] = None,
        previous_code: Optional[DFTCode] = None,
    ) -> DFTCode:
        """Select best code for a property.

        Selection algorithm:
        1. If user specified a preference and it's available, use it
        2. If previous code exists, prefer compatible continuation
        3. Select from defaults based on availability

        Args:
            property_name: Property to calculate (bands, dos, gw, etc.)
            available_codes: Codes available on the cluster (None = all)
            user_preference: User-specified preference
            previous_code: Code used in previous step (for compatibility)

        Returns:
            Selected DFT code

        Raises:
            NoCompatibleCodeError: If no compatible code is available

        Example:
            code = PropertyCalculator.select_code(
                "bands",
                available_codes=["vasp", "crystal23"],
                previous_code="vasp"
            )
        """
        # Get default codes for this property
        defaults = cls.DEFAULT_CODES.get(property_name, ["vasp"])

        # Check if property requires specific codes
        required = cls.REQUIRED_CODES.get(property_name)
        if required:
            defaults = required

        # Filter by availability
        if available_codes:
            defaults = [c for c in defaults if c in available_codes]

        # Handle user preference
        if user_preference:
            if available_codes and user_preference not in available_codes:
                logger.warning(
                    f"User preference '{user_preference}' not available. "
                    f"Available: {available_codes}"
                )
            elif required and user_preference not in required:
                logger.warning(
                    f"User preference '{user_preference}' cannot calculate {property_name}. "
                    f"Required: {required}"
                )
            else:
                return user_preference

        # Check compatibility with previous code
        if previous_code and defaults:
            compatible = [
                c for c in defaults
                if cls.CODE_COMPATIBILITY.get((previous_code, c), False)
            ]
            if compatible:
                defaults = compatible

        # Return first available
        if defaults:
            return defaults[0]

        # No compatible code found
        raise NoCompatibleCodeError(
            f"No compatible code available for '{property_name}'. "
            f"Required: {required or 'any'}. "
            f"Available: {available_codes or 'none specified'}"
        )

    @classmethod
    def validate_workflow_codes(
        cls,
        steps: List[WorkflowStep],
    ) -> Tuple[bool, List[str]]:
        """Validate code compatibility across workflow steps.

        Checks that data can be transferred between consecutive steps
        that use different codes.

        Args:
            steps: List of workflow steps with assigned codes

        Returns:
            Tuple of (is_valid, list_of_issues)

        Example:
            is_valid, issues = PropertyCalculator.validate_workflow_codes(steps)
            if not is_valid:
                print("Incompatible codes:", issues)
        """
        issues: List[str] = []

        # Build dependency map
        step_map = {s.name: s for s in steps}

        for step in steps:
            for dep_name in step.depends_on:
                if dep_name not in step_map:
                    issues.append(f"Step '{step.name}' depends on unknown step '{dep_name}'")
                    continue

                dep_step = step_map[dep_name]
                source_code = dep_step.code
                target_code = step.code

                # Check compatibility
                if not cls.CODE_COMPATIBILITY.get((source_code, target_code), False):
                    issues.append(
                        f"Incompatible codes: '{dep_name}' ({source_code}) -> "
                        f"'{step.name}' ({target_code})"
                    )

        return len(issues) == 0, issues

    @classmethod
    def get_code_capabilities(cls, code: DFTCode) -> List[str]:
        """Get list of properties a code can calculate.

        Args:
            code: DFT code

        Returns:
            List of property names the code supports

        Example:
            caps = PropertyCalculator.get_code_capabilities("vasp")
            print("VASP can calculate:", caps)
        """
        capabilities = []
        for prop, codes in cls.DEFAULT_CODES.items():
            if code in codes:
                capabilities.append(prop)
        return capabilities

    @classmethod
    def get_property_codes(cls, property_name: str) -> List[DFTCode]:
        """Get codes that can calculate a property.

        Args:
            property_name: Property name

        Returns:
            List of compatible codes

        Example:
            codes = PropertyCalculator.get_property_codes("gw")
            print("GW available in:", codes)
        """
        return cls.DEFAULT_CODES.get(property_name, [])


class NoCompatibleCodeError(Exception):
    """Raised when no compatible DFT code is available for a property."""

    pass
