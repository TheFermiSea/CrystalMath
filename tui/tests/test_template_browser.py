"""
Tests for template browser screen.
"""

import pytest
from pathlib import Path
from textual.widgets import Tree

from src.core.templates import TemplateManager, Template, ParameterDefinition
from src.tui.screens.template_browser import TemplateBrowserScreen, ParameterForm


@pytest.fixture
def template_dir(tmp_path):
    """Create a temporary template directory with sample templates."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    # Create a basic template
    basic_dir = templates_dir / "basic"
    basic_dir.mkdir()

    basic_template = basic_dir / "test_basic.yaml"
    basic_template.write_text("""
name: "Test Basic Template"
version: "1.0"
description: "A basic test template"
author: "Test Author"
tags: ["basic", "test"]

parameters:
  param1:
    type: string
    description: "A string parameter"
    default: "default_value"
    required: true

  param2:
    type: integer
    description: "An integer parameter"
    default: 10
    min: 1
    max: 100
    required: false

input_template: |
  Test Input
  Parameter 1: {{ param1 }}
  Parameter 2: {{ param2 }}
  END
""")

    # Create an advanced template
    advanced_dir = templates_dir / "advanced"
    advanced_dir.mkdir()

    advanced_template = advanced_dir / "test_advanced.yaml"
    advanced_template.write_text("""
name: "Test Advanced Template"
version: "2.0"
description: "An advanced test template"
author: "Test Author"
tags: ["advanced", "test"]

parameters:
  basis_set:
    type: select
    description: "Basis set selection"
    default: "sto-3g"
    options: ["sto-3g", "6-31g", "6-311g"]
    required: true

  use_optimization:
    type: boolean
    description: "Enable geometry optimization"
    default: true

input_template: |
  Advanced Test Input
  Basis: {{ basis_set }}
  {% if use_optimization %}
  OPTGEOM
  {% endif %}
  END
""")

    return templates_dir


def test_template_manager_loading(template_dir):
    """Test that TemplateManager can load templates."""
    manager = TemplateManager(template_dir)
    templates = manager.list_templates()

    assert len(templates) == 2
    assert any(t.name == "Test Basic Template" for t in templates)
    assert any(t.name == "Test Advanced Template" for t in templates)


def test_template_filtering_by_tags(template_dir):
    """Test filtering templates by tags."""
    manager = TemplateManager(template_dir)

    # Filter by basic tag
    basic_templates = manager.list_templates(tags=["basic"])
    assert len(basic_templates) == 1
    assert basic_templates[0].name == "Test Basic Template"

    # Filter by advanced tag
    advanced_templates = manager.list_templates(tags=["advanced"])
    assert len(advanced_templates) == 1
    assert advanced_templates[0].name == "Test Advanced Template"


def test_parameter_validation():
    """Test parameter validation."""
    # Integer parameter with range
    param_def = ParameterDefinition(
        name="test_param",
        type="integer",
        min=1,
        max=10,
        required=True
    )

    # Valid value
    errors = param_def.validate(5)
    assert len(errors) == 0

    # Out of range
    errors = param_def.validate(15)
    assert len(errors) > 0
    assert "must be <=" in errors[0]

    # Required parameter missing
    errors = param_def.validate(None)
    assert len(errors) > 0
    assert "required" in errors[0]


def test_parameter_validation_select():
    """Test select parameter validation."""
    param_def = ParameterDefinition(
        name="basis_set",
        type="select",
        options=["sto-3g", "6-31g", "6-311g"],
        required=True
    )

    # Valid value
    errors = param_def.validate("sto-3g")
    assert len(errors) == 0

    # Invalid value
    errors = param_def.validate("invalid-basis")
    assert len(errors) > 0
    assert "must be one of" in errors[0]


def test_template_rendering(template_dir):
    """Test template rendering with parameters."""
    manager = TemplateManager(template_dir)
    template = manager.find_template("Test Basic Template")

    assert template is not None

    # Render with default parameters
    rendered = manager.render(template, {})
    assert "default_value" in rendered
    assert "10" in rendered

    # Render with custom parameters
    rendered = manager.render(template, {
        "param1": "custom_value",
        "param2": 50
    })
    assert "custom_value" in rendered
    assert "50" in rendered


def test_template_rendering_with_conditionals(template_dir):
    """Test template rendering with conditional blocks."""
    manager = TemplateManager(template_dir)
    template = manager.find_template("Test Advanced Template")

    assert template is not None

    # Render with optimization enabled
    rendered = manager.render(template, {
        "basis_set": "6-31g",
        "use_optimization": True
    })
    assert "6-31g" in rendered
    assert "OPTGEOM" in rendered

    # Render with optimization disabled
    rendered = manager.render(template, {
        "basis_set": "sto-3g",
        "use_optimization": False
    })
    assert "sto-3g" in rendered
    assert "OPTGEOM" not in rendered


def test_parameter_form_value_extraction(template_dir):
    """Test ParameterForm can extract values."""
    manager = TemplateManager(template_dir)
    template = manager.find_template("Test Basic Template")

    assert template is not None

    # Create parameter form (without mounting - just test logic)
    form = ParameterForm(template)

    # Test get_default_params
    defaults = manager.get_default_params(template)
    assert defaults["param1"] == "default_value"
    assert defaults["param2"] == 10


def test_preview_template(template_dir):
    """Test template preview generation."""
    manager = TemplateManager(template_dir)
    template = manager.find_template("Test Basic Template")

    assert template is not None

    preview = manager.preview_template(template)
    assert "default_value" in preview
    assert "10" in preview


def test_template_validation_errors(template_dir):
    """Test that validation errors are caught."""
    manager = TemplateManager(template_dir)
    template = manager.find_template("Test Basic Template")

    assert template is not None

    # Try to render with invalid parameters
    with pytest.raises(ValueError) as exc_info:
        manager.render(template, {
            "param1": "valid",
            "param2": 200  # Out of range (max is 100)
        })

    assert "validation failed" in str(exc_info.value).lower()


def test_template_info(template_dir):
    """Test getting template information."""
    manager = TemplateManager(template_dir)
    template = manager.find_template("Test Basic Template")

    assert template is not None

    info = manager.get_template_info(template)

    assert info["name"] == "Test Basic Template"
    assert info["version"] == "1.0"
    assert info["author"] == "Test Author"
    assert len(info["parameters"]) == 2
    assert info["parameter_count"] == 2


def test_template_save_and_load(template_dir):
    """Test saving and loading templates."""
    manager = TemplateManager(template_dir)

    # Create a new template
    new_template = Template(
        name="Test Save Template",
        version="1.0",
        description="Test saving",
        author="Test",
        tags=["test"],
        parameters={
            "test_param": ParameterDefinition(
                name="test_param",
                type="string",
                default="test"
            )
        },
        input_template="Test {{ test_param }}"
    )

    # Save template
    save_path = template_dir / "test_save.yaml"
    manager.save_template(new_template, save_path)

    assert save_path.exists()

    # Load template back
    loaded = manager.load_template(save_path)
    assert loaded.name == new_template.name
    assert loaded.version == new_template.version
    assert "test_param" in loaded.parameters
