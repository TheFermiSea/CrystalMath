"""
Comprehensive unit tests for the template system.
"""

import pytest
from pathlib import Path
import tempfile
import yaml

from src.core.templates import (
    ParameterDefinition,
    Template,
    TemplateManager,
    render_template,
)


class TestParameterDefinition:
    """Tests for ParameterDefinition class."""

    def test_integer_validation_success(self):
        """Test successful integer validation."""
        param = ParameterDefinition(
            name="shrink",
            type="integer",
            default=8,
            min=1,
            max=32,
        )
        errors = param.validate(8)
        assert len(errors) == 0

    def test_integer_validation_out_of_range(self):
        """Test integer out of range."""
        param = ParameterDefinition(
            name="shrink",
            type="integer",
            default=8,
            min=1,
            max=32,
        )
        errors = param.validate(50)
        assert len(errors) > 0
        assert "must be <=" in errors[0]

    def test_integer_validation_type_error(self):
        """Test integer with wrong type."""
        param = ParameterDefinition(
            name="shrink",
            type="integer",
            default=8,
        )
        errors = param.validate("not_a_number")
        assert len(errors) > 0
        assert "must be an integer" in errors[0]

    def test_float_validation_success(self):
        """Test successful float validation."""
        param = ParameterDefinition(
            name="convergence",
            type="float",
            default=1e-8,
            min=1e-12,
            max=1e-4,
        )
        errors = param.validate(1e-9)
        assert len(errors) == 0

    def test_float_validation_range(self):
        """Test float range validation."""
        param = ParameterDefinition(
            name="convergence",
            type="float",
            min=1e-12,
            max=1e-4,
        )
        # Test valid value within range
        errors = param.validate(1e-8)
        assert len(errors) == 0

        # Test value outside range (too large)
        errors = param.validate(1e-3)
        assert len(errors) > 0

    def test_string_validation(self):
        """Test string validation."""
        param = ParameterDefinition(
            name="name",
            type="string",
            required=True,
        )
        errors = param.validate("Test System")
        assert len(errors) == 0

        errors = param.validate(123)
        assert len(errors) > 0

    def test_boolean_validation(self):
        """Test boolean validation."""
        param = ParameterDefinition(
            name="use_dft",
            type="boolean",
            default=True,
        )
        errors = param.validate(True)
        assert len(errors) == 0

        errors = param.validate(False)
        assert len(errors) == 0

    def test_select_validation_success(self):
        """Test select validation with valid option."""
        param = ParameterDefinition(
            name="basis_set",
            type="select",
            options=["sto-3g", "6-21g", "pob-tzvp"],
            default="sto-3g",
        )
        errors = param.validate("6-21g")
        assert len(errors) == 0

    def test_select_validation_invalid_option(self):
        """Test select validation with invalid option."""
        param = ParameterDefinition(
            name="basis_set",
            type="select",
            options=["sto-3g", "6-21g", "pob-tzvp"],
            default="sto-3g",
        )
        errors = param.validate("invalid-basis")
        assert len(errors) > 0
        assert "must be one of" in errors[0]

    def test_multiselect_validation(self):
        """Test multiselect validation."""
        param = ParameterDefinition(
            name="tags",
            type="multiselect",
            options=["opt", "freq", "band"],
        )
        errors = param.validate(["opt", "freq"])
        assert len(errors) == 0

        errors = param.validate(["opt", "invalid"])
        assert len(errors) > 0

    def test_required_parameter(self):
        """Test required parameter validation."""
        param = ParameterDefinition(
            name="system_name",
            type="string",
            required=True,
        )
        errors = param.validate(None)
        assert len(errors) > 0
        assert "required" in errors[0].lower()

    def test_optional_parameter(self):
        """Test optional parameter with None value."""
        param = ParameterDefinition(
            name="optional_param",
            type="integer",
            required=False,
        )
        errors = param.validate(None)
        assert len(errors) == 0

    def test_conditional_parameter(self):
        """Test conditional parameter dependencies."""
        param = ParameterDefinition(
            name="opt_cycles",
            type="integer",
            depends_on={"optimize": True},
        )
        # When condition not checked, just validate if provided
        errors = param.validate(100)
        assert len(errors) == 0


class TestTemplate:
    """Tests for Template class."""

    def test_template_creation(self):
        """Test creating a template object."""
        template = Template(
            name="Test Template",
            version="1.0",
            description="A test template",
            author="Test Author",
            tags=["test", "basic"],
            parameters={
                "param1": ParameterDefinition(
                    name="param1",
                    type="string",
                    default="value1",
                )
            },
            input_template="Test: {{ param1 }}",
        )
        assert template.name == "Test Template"
        assert "param1" in template.parameters

    def test_template_from_dict(self):
        """Test creating template from dictionary."""
        data = {
            "name": "Test Template",
            "version": "1.0",
            "description": "A test",
            "author": "Test",
            "tags": ["test"],
            "parameters": {
                "param1": {
                    "type": "string",
                    "default": "value",
                    "description": "A parameter",
                }
            },
            "input_template": "{{ param1 }}",
        }
        template = Template.from_dict(data)
        assert template.name == "Test Template"
        assert "param1" in template.parameters

    def test_template_to_dict(self):
        """Test converting template to dictionary."""
        template = Template(
            name="Test",
            version="1.0",
            description="Test",
            author="Author",
            tags=["test"],
            parameters={
                "param1": ParameterDefinition(
                    name="param1",
                    type="integer",
                    default=5,
                    min=1,
                    max=10,
                )
            },
            input_template="Value: {{ param1 }}",
        )
        data = template.to_dict()
        assert data["name"] == "Test"
        assert "param1" in data["parameters"]
        assert data["parameters"]["param1"]["type"] == "integer"


class TestTemplateManager:
    """Tests for TemplateManager class."""

    @pytest.fixture
    def temp_template_dir(self):
        """Create a temporary directory for templates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_template_file(self, temp_template_dir):
        """Create a sample template file."""
        template_data = {
            "name": "Sample Template",
            "version": "1.0",
            "description": "A sample template",
            "author": "Test Author",
            "tags": ["test", "sample"],
            "parameters": {
                "system_name": {
                    "type": "string",
                    "default": "Test System",
                    "description": "System name",
                    "required": True,
                },
                "shrink": {
                    "type": "integer",
                    "default": 8,
                    "min": 1,
                    "max": 32,
                    "description": "K-point mesh",
                },
            },
            "input_template": "{{ system_name }}\nSHRINK\n{{ shrink }}",
        }
        template_path = temp_template_dir / "sample.yml"
        with open(template_path, "w") as f:
            yaml.dump(template_data, f)
        return template_path

    def test_template_manager_initialization(self, temp_template_dir):
        """Test TemplateManager initialization."""
        manager = TemplateManager(temp_template_dir)
        assert manager.template_dir == temp_template_dir
        assert manager.template_dir.exists()

    def test_load_template(self, sample_template_file):
        """Test loading a template from file."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)
        assert template.name == "Sample Template"
        assert "system_name" in template.parameters
        assert "shrink" in template.parameters

    def test_load_nonexistent_template(self, temp_template_dir):
        """Test loading non-existent template raises error."""
        manager = TemplateManager(temp_template_dir)
        with pytest.raises(FileNotFoundError):
            manager.load_template(temp_template_dir / "nonexistent.yml")

    def test_render_template_success(self, sample_template_file):
        """Test successful template rendering."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)

        result = manager.render(
            template,
            {"system_name": "MgO Crystal", "shrink": 12}
        )

        assert "MgO Crystal" in result
        assert "12" in result

    def test_render_template_with_defaults(self, sample_template_file):
        """Test rendering with default values."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)

        result = manager.render(template, {"system_name": "Test"})

        assert "Test" in result
        assert "8" in result  # Default shrink value

    def test_render_template_validation_error(self, sample_template_file):
        """Test rendering with invalid parameters."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)

        with pytest.raises(ValueError) as exc_info:
            manager.render(template, {"system_name": "Test", "shrink": 100})

        assert "validation failed" in str(exc_info.value).lower()

    def test_validate_params_success(self, sample_template_file):
        """Test successful parameter validation."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)

        errors = manager.validate_params(
            template,
            {"system_name": "Test", "shrink": 16}
        )

        assert len(errors) == 0

    def test_validate_params_unknown_parameter(self, sample_template_file):
        """Test validation with unknown parameter."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)

        errors = manager.validate_params(
            template,
            {"system_name": "Test", "unknown_param": "value"}
        )

        assert len(errors) > 0
        assert any("unknown" in e.lower() for e in errors)

    def test_get_default_params(self, sample_template_file):
        """Test getting default parameters."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)

        defaults = manager.get_default_params(template)

        assert defaults["system_name"] == "Test System"
        assert defaults["shrink"] == 8

    def test_save_template(self, temp_template_dir):
        """Test saving a template to file."""
        manager = TemplateManager(temp_template_dir)

        template = Template(
            name="New Template",
            version="1.0",
            description="Test",
            author="Author",
            tags=["test"],
            parameters={
                "param1": ParameterDefinition(
                    name="param1",
                    type="string",
                    default="value",
                )
            },
            input_template="{{ param1 }}",
        )

        save_path = temp_template_dir / "new_template.yml"
        manager.save_template(template, save_path)

        assert save_path.exists()

        # Load it back and verify
        loaded = manager.load_template(save_path)
        assert loaded.name == "New Template"

    def test_list_templates(self, temp_template_dir, sample_template_file):
        """Test listing available templates."""
        manager = TemplateManager(temp_template_dir)
        templates = manager.list_templates()

        assert len(templates) >= 1
        assert any(t.name == "Sample Template" for t in templates)

    def test_list_templates_with_tag_filter(self, temp_template_dir):
        """Test listing templates filtered by tags."""
        manager = TemplateManager(temp_template_dir)

        # Create templates with different tags
        template1 = Template(
            name="Opt Template",
            version="1.0",
            description="Optimization",
            author="Author",
            tags=["optimization", "basic"],
            parameters={},
            input_template="test",
        )
        template2 = Template(
            name="Band Template",
            version="1.0",
            description="Band structure",
            author="Author",
            tags=["band", "advanced"],
            parameters={},
            input_template="test",
        )

        manager.save_template(template1, temp_template_dir / "opt.yml")
        manager.save_template(template2, temp_template_dir / "band.yml")

        # Filter by tag
        opt_templates = manager.list_templates(tags=["optimization"])
        assert len(opt_templates) >= 1
        assert any(t.name == "Opt Template" for t in opt_templates)

    def test_find_template(self, sample_template_file):
        """Test finding a template by name."""
        manager = TemplateManager(sample_template_file.parent)

        template = manager.find_template("Sample Template")
        assert template is not None
        assert template.name == "Sample Template"

        not_found = manager.find_template("Nonexistent Template")
        assert not_found is None

    def test_preview_template(self, sample_template_file):
        """Test generating template preview."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)

        preview = manager.preview_template(template)

        assert "Test System" in preview  # Default system_name
        assert "8" in preview  # Default shrink

    def test_get_template_info(self, sample_template_file):
        """Test getting template information."""
        manager = TemplateManager(sample_template_file.parent)
        template = manager.load_template(sample_template_file)

        info = manager.get_template_info(template)

        assert info["name"] == "Sample Template"
        assert info["version"] == "1.0"
        assert info["parameter_count"] == 2
        assert len(info["parameters"]) == 2

    def test_template_caching(self, sample_template_file):
        """Test that templates are cached after first load."""
        manager = TemplateManager(sample_template_file.parent)

        # Load template twice
        template1 = manager.load_template(sample_template_file)
        template2 = manager.load_template(sample_template_file)

        # Should be the same cached object
        assert template1 is template2


class TestConvenienceFunction:
    """Tests for convenience functions."""

    def test_render_template_function(self, tmp_path):
        """Test the render_template convenience function."""
        # Create a simple template
        template_data = {
            "name": "Quick Template",
            "input_template": "Value: {{ value }}",
            "parameters": {
                "value": {
                    "type": "integer",
                    "default": 42,
                }
            },
        }

        template_path = tmp_path / "quick.yml"
        with open(template_path, "w") as f:
            yaml.dump(template_data, f)

        # Use convenience function
        result = render_template(template_path, {"value": 100})

        assert "100" in result


class TestComplexTemplates:
    """Tests for complex template features."""

    def test_template_with_conditionals(self, tmp_path):
        """Test template with Jinja2 conditionals."""
        template_data = {
            "name": "Conditional Template",
            "input_template": """
{% if use_dft %}
DFT
PBE
{% endif %}
SHRINK
{{ shrink }}
""",
            "parameters": {
                "use_dft": {
                    "type": "boolean",
                    "default": False,
                },
                "shrink": {
                    "type": "integer",
                    "default": 8,
                }
            },
        }

        template_path = tmp_path / "conditional.yml"
        with open(template_path, "w") as f:
            yaml.dump(template_data, f)

        manager = TemplateManager(tmp_path)
        template = manager.load_template(template_path)

        # Test with DFT enabled
        result_dft = manager.render(template, {"use_dft": True, "shrink": 8})
        assert "DFT" in result_dft
        assert "PBE" in result_dft

        # Test without DFT
        result_no_dft = manager.render(template, {"use_dft": False, "shrink": 8})
        assert "DFT" not in result_no_dft

    def test_template_with_loops(self, tmp_path):
        """Test template with Jinja2 loops."""
        # For complex structures like lists of dicts, we skip type validation
        # by not defining the parameter (Jinja2 will still work)
        template_data = {
            "name": "Loop Template",
            "input_template": """
{% for atom in atoms %}
ATOM {{ atom.number }} {{ atom.symbol }}
{% endfor %}
""",
            "parameters": {},  # No parameter validation for complex structures
        }

        template_path = tmp_path / "loop.yml"
        with open(template_path, "w") as f:
            yaml.dump(template_data, f)

        manager = TemplateManager(tmp_path)
        template = manager.load_template(template_path)

        # Render will work even though 'atoms' isn't defined in parameters
        # because Jinja2 accepts any variable
        result = manager.render(
            template,
            {
                "atoms": [
                    {"number": 12, "symbol": "Mg"},
                    {"number": 8, "symbol": "O"},
                ]
            }
        )

        assert "ATOM 12 Mg" in result
        assert "ATOM 8 O" in result


class TestRealWorldTemplates:
    """Tests using the actual template files in the templates/ directory."""

    @pytest.fixture
    def templates_dir(self):
        """Get the path to the real templates directory."""
        return Path(__file__).parent.parent / "templates"

    def test_load_single_point_template(self, templates_dir):
        """Test loading the single point template."""
        manager = TemplateManager(templates_dir)
        template_path = templates_dir / "basic" / "single_point.yml"

        if not template_path.exists():
            pytest.skip("Template file not found")

        template = manager.load_template(template_path)
        assert template.name == "Single Point Energy"
        assert "basis_set" in template.parameters

    def test_render_optimization_template(self, templates_dir):
        """Test rendering the optimization template."""
        manager = TemplateManager(templates_dir)
        template_path = templates_dir / "basic" / "optimization.yml"

        if not template_path.exists():
            pytest.skip("Template file not found")

        template = manager.load_template(template_path)
        result = manager.render(
            template,
            {
                "system_name": "MgO Optimization",
                "space_group": 225,
                "lattice_param": 4.21,
                "basis_set": "pob-tzvp",
                "shrink": 12,
                "convergence": 1e-9,
                "opt_type": "FULLOPTG",
            }
        )

        assert "MgO Optimization" in result
        assert "FULLOPTG" in result
        assert "pob-tzvp" in result
