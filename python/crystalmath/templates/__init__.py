"""
Centralized DFT templates for CRYSTAL, VASP, and Quantum Espresso.

This module provides:
- Canonical template directory location
- Template discovery and listing
- DFT code-specific template organization

Template Organization:
    templates/
    ├── basic/          # Simple single-point, optimization
    ├── advanced/       # Band structure, DOS, elastic
    ├── workflows/      # Multi-step calculations
    ├── vasp/           # VASP-specific templates
    ├── qe/             # Quantum Espresso templates
    └── slurm/          # Job scheduler templates

Usage:
    from crystalmath.templates import get_template_dir, list_templates, get_template

    # Get the canonical templates directory
    templates_dir = get_template_dir()

    # List all available templates
    for template in list_templates():
        print(f"{template.category}/{template.name}: {template.description}")

    # Get a specific template
    template = get_template("basic/single_point")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Canonical templates directory (relative to this file)
_TEMPLATES_DIR = Path(__file__).parent


def get_template_dir() -> Path:
    """
    Get the canonical templates directory.

    Returns:
        Path to the templates directory
    """
    return _TEMPLATES_DIR


@dataclass(frozen=True)
class TemplateInfo:
    """Metadata for a template file."""

    name: str
    category: str  # basic, advanced, workflows, vasp, qe, slurm
    path: Path
    description: str = ""
    dft_code: str = "crystal"  # crystal, vasp, qe
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            object.__setattr__(self, "tags", [])


def _parse_template_metadata(path: Path) -> dict:
    """Extract metadata from a template YAML file."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                return {
                    "description": data.get("description", ""),
                    "dft_code": data.get("dft_code", "crystal"),
                    "tags": data.get("tags", []),
                }
    except Exception as e:
        logger.debug(f"Could not parse template metadata from {path}: {e}")
    return {}


def list_templates(
    category: Optional[str] = None,
    dft_code: Optional[str] = None,
) -> Iterator[TemplateInfo]:
    """
    List available templates.

    Args:
        category: Filter by category (basic, advanced, workflows, vasp, qe, slurm)
        dft_code: Filter by DFT code (crystal, vasp, qe)

    Yields:
        TemplateInfo objects for matching templates
    """
    templates_dir = get_template_dir()

    # Categories to search
    categories = [category] if category else [
        d.name for d in templates_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    ]

    for cat in categories:
        cat_dir = templates_dir / cat
        if not cat_dir.is_dir():
            continue

        # Infer dft_code from category
        inferred_code = "crystal"
        if cat == "vasp":
            inferred_code = "vasp"
        elif cat == "qe":
            inferred_code = "qe"

        for template_path in cat_dir.glob("*.yml"):
            metadata = _parse_template_metadata(template_path)
            template_dft_code = metadata.get("dft_code", inferred_code)

            # Apply dft_code filter
            if dft_code and template_dft_code != dft_code:
                continue

            yield TemplateInfo(
                name=template_path.stem,
                category=cat,
                path=template_path,
                description=metadata.get("description", ""),
                dft_code=template_dft_code,
                tags=metadata.get("tags", []),
            )

        # Also check .yaml extension
        for template_path in cat_dir.glob("*.yaml"):
            metadata = _parse_template_metadata(template_path)
            template_dft_code = metadata.get("dft_code", inferred_code)

            if dft_code and template_dft_code != dft_code:
                continue

            yield TemplateInfo(
                name=template_path.stem,
                category=cat,
                path=template_path,
                description=metadata.get("description", ""),
                dft_code=template_dft_code,
                tags=metadata.get("tags", []),
            )


def get_template(template_id: str) -> Optional[Path]:
    """
    Get path to a template by ID.

    Args:
        template_id: Template identifier in format "category/name" (e.g., "basic/single_point")

    Returns:
        Path to the template file, or None if not found
    """
    templates_dir = get_template_dir()

    # Parse template_id
    if "/" in template_id:
        category, name = template_id.split("/", 1)
    else:
        # Search all categories for the name
        for info in list_templates():
            if info.name == template_id:
                return info.path
        return None

    # Check for .yml and .yaml extensions
    for ext in [".yml", ".yaml"]:
        path = templates_dir / category / f"{name}{ext}"
        if path.exists():
            return path

    return None


def load_template(template_id: str) -> Optional[dict]:
    """
    Load a template by ID.

    Args:
        template_id: Template identifier in format "category/name"

    Returns:
        Parsed template data, or None if not found
    """
    path = get_template(template_id)
    if path is None:
        return None

    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load template {template_id}: {e}")
        return None


__all__ = [
    "get_template_dir",
    "list_templates",
    "get_template",
    "load_template",
    "TemplateInfo",
]
