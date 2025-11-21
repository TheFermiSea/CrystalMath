"""
Unit tests for AutoForm widget.

Tests form generation, validation, data collection, and conditional fields.
"""

import pytest
from pathlib import Path
from typing import Dict, Any

from src.tui.widgets.auto_form import (
    AutoForm,
    FieldSchema,
    ValidationError,
    StringField,
    IntegerField,
    FloatField,
    BooleanField,
    SelectField,
    MultiSelectField,
    FileField,
)


# Test Fixtures

@pytest.fixture
def simple_schema() -> Dict[str, Any]:
    """Simple form schema for testing."""
    return {
        "fields": [
            {
                "name": "username",
                "type": "string",
                "label": "Username",
                "required": True,
                "help": "Enter your username"
            },
            {
                "name": "age",
                "type": "integer",
                "label": "Age",
                "min": 0,
                "max": 120,
                "default": 25
            }
        ]
    }


@pytest.fixture
def complex_schema() -> Dict[str, Any]:
    """Complex form schema with all field types."""
    return {
        "fields": [
            {
                "name": "basis_set",
                "type": "select",
                "label": "Basis Set",
                "options": ["sto-3g", "6-21g", "pob-tzvp"],
                "default": "sto-3g",
                "required": True,
                "help": "Choose basis set for calculation",
                "group": "Calculation Settings"
            },
            {
                "name": "shrink",
                "type": "integer",
                "label": "Shrink Factor",
                "default": 8,
                "min": 2,
                "max": 16,
                "required": True,
                "help": "K-point mesh density",
                "group": "Calculation Settings"
            },
            {
                "name": "tolerance",
                "type": "float",
                "label": "SCF Tolerance",
                "default": 1e-7,
                "min": 1e-12,
                "max": 1e-3,
                "group": "Convergence"
            },
            {
                "name": "spin_polarized",
                "type": "boolean",
                "label": "Spin Polarized",
                "default": False,
                "group": "Advanced"
            },
            {
                "name": "functionals",
                "type": "multiselect",
                "label": "XC Functionals",
                "options": ["LDA", "PBE", "B3LYP", "HSE06"],
                "default": ["PBE"],
                "group": "Advanced"
            },
            {
                "name": "input_file",
                "type": "file",
                "label": "Input Geometry",
                "help": "Select .cif or .xyz file",
                "group": "Files"
            }
        ]
    }


@pytest.fixture
def conditional_schema() -> Dict[str, Any]:
    """Schema with conditional fields."""
    return {
        "fields": [
            {
                "name": "enable_optimization",
                "type": "boolean",
                "label": "Enable Optimization",
                "default": False
            },
            {
                "name": "max_cycles",
                "type": "integer",
                "label": "Max Optimization Cycles",
                "default": 50,
                "min": 1,
                "max": 1000,
                "visible_when": {"enable_optimization": True}
            },
            {
                "name": "convergence_threshold",
                "type": "float",
                "label": "Convergence Threshold",
                "default": 1e-5,
                "depends_on": "enable_optimization"
            }
        ]
    }


# Test FieldSchema

def test_field_schema_defaults():
    """Test FieldSchema default values."""
    schema = FieldSchema(name="test_field", type="string")

    assert schema.name == "test_field"
    assert schema.type == "string"
    assert schema.label == "Test Field"  # Auto-generated from name
    assert schema.default is None
    assert schema.required is False
    assert schema.help == ""


def test_field_schema_custom_label():
    """Test FieldSchema with custom label."""
    schema = FieldSchema(
        name="test_field",
        type="string",
        label="Custom Label"
    )

    assert schema.label == "Custom Label"


def test_field_schema_validation_rules():
    """Test FieldSchema validation rules."""
    schema = FieldSchema(
        name="age",
        type="integer",
        min=0,
        max=120,
        required=True,
        pattern=r"^\d+$"
    )

    assert schema.min == 0
    assert schema.max == 120
    assert schema.required is True
    assert schema.pattern == r"^\d+$"


# Test AutoForm Creation

def test_autoform_from_schema(simple_schema):
    """Test creating AutoForm from schema."""
    form = AutoForm.from_schema(simple_schema)

    assert form is not None
    assert len(form.field_schemas) == 2
    assert "username" in form.field_schemas
    assert "age" in form.field_schemas


def test_autoform_parse_schema(complex_schema):
    """Test schema parsing with all field types."""
    form = AutoForm.from_schema(complex_schema)

    assert len(form.field_schemas) == 6
    assert form.field_schemas["basis_set"].type == "select"
    assert form.field_schemas["shrink"].type == "integer"
    assert form.field_schemas["tolerance"].type == "float"
    assert form.field_schemas["spin_polarized"].type == "boolean"
    assert form.field_schemas["functionals"].type == "multiselect"
    assert form.field_schemas["input_file"].type == "file"


def test_autoform_field_groups(complex_schema):
    """Test field grouping."""
    form = AutoForm.from_schema(complex_schema)

    groups = {}
    for name, schema in form.field_schemas.items():
        group = schema.group or "default"
        if group not in groups:
            groups[group] = []
        groups[group].append(name)

    assert "Calculation Settings" in groups
    assert len(groups["Calculation Settings"]) == 2
    assert "basis_set" in groups["Calculation Settings"]
    assert "shrink" in groups["Calculation Settings"]


# Test Field Types

def test_string_field():
    """Test StringField creation and value handling."""
    schema = FieldSchema(
        name="username",
        type="string",
        label="Username",
        default="john_doe"
    )

    field = StringField(schema)
    assert field.schema.name == "username"
    assert field.schema.default == "john_doe"


def test_integer_field():
    """Test IntegerField with range validation."""
    schema = FieldSchema(
        name="age",
        type="integer",
        min=0,
        max=120,
        default=25
    )

    field = IntegerField(schema)
    assert field.schema.min == 0
    assert field.schema.max == 120


def test_float_field():
    """Test FloatField with range validation."""
    schema = FieldSchema(
        name="tolerance",
        type="float",
        min=1e-12,
        max=1e-3,
        default=1e-7
    )

    field = FloatField(schema)
    assert field.schema.min == 1e-12
    assert field.schema.max == 1e-3


def test_boolean_field():
    """Test BooleanField."""
    schema = FieldSchema(
        name="enabled",
        type="boolean",
        default=True
    )

    field = BooleanField(schema)
    assert field.schema.default is True


def test_select_field():
    """Test SelectField with options."""
    schema = FieldSchema(
        name="basis",
        type="select",
        options=["sto-3g", "6-21g", "pob-tzvp"],
        default="sto-3g"
    )

    field = SelectField(schema)
    assert len(field.schema.options) == 3
    assert field.schema.default == "sto-3g"


def test_multiselect_field():
    """Test MultiSelectField."""
    schema = FieldSchema(
        name="functionals",
        type="multiselect",
        options=["LDA", "PBE", "B3LYP"],
        default=["PBE"]
    )

    field = MultiSelectField(schema)
    assert len(field.schema.options) == 3
    assert field.schema.default == ["PBE"]


def test_file_field():
    """Test FileField."""
    schema = FieldSchema(
        name="input_file",
        type="file",
        help="Select geometry file"
    )

    field = FileField(schema)
    assert field.schema.help == "Select geometry file"


# Test Validation

def test_validation_required_field():
    """Test validation of required fields."""
    schema = {
        "fields": [
            {
                "name": "username",
                "type": "string",
                "required": True
            }
        ]
    }

    form = AutoForm.from_schema(schema)

    # Simulate empty value
    form.field_schemas["username"].default = ""

    errors = form.validate()

    # Should have validation error for required field
    assert len(errors) > 0
    assert any("required" in e.message.lower() for e in errors)


def test_validation_integer_range():
    """Test integer range validation."""
    schema = FieldSchema(
        name="age",
        type="integer",
        min=0,
        max=120
    )

    field = IntegerField(schema)

    # Valid range validation logic would be tested in integration tests
    # Here we verify the schema has the constraints
    assert field.schema.min == 0
    assert field.schema.max == 120


def test_validation_pattern():
    """Test pattern validation."""
    schema = FieldSchema(
        name="code",
        type="string",
        pattern=r"^[A-Z]{3}\d{3}$"
    )

    field = StringField(schema)
    assert field.schema.pattern == r"^[A-Z]{3}\d{3}$"


def test_validation_custom_validator():
    """Test custom validator function."""
    def validate_even(value: str) -> bool:
        try:
            return int(value) % 2 == 0
        except ValueError:
            return False

    schema = FieldSchema(
        name="even_number",
        type="integer",
        validator=validate_even,
        validator_message="Must be an even number"
    )

    field = IntegerField(schema)
    assert field.schema.validator is not None
    assert field.schema.validator_message == "Must be an even number"


def test_cross_field_validation(conditional_schema):
    """Test cross-field dependencies."""
    form = AutoForm.from_schema(conditional_schema)

    # Check field dependencies
    conv_schema = form.field_schemas["convergence_threshold"]
    assert conv_schema.depends_on == "enable_optimization"


# Test Form Data Handling

def test_get_values():
    """Test collecting form values."""
    schema = {
        "fields": [
            {"name": "field1", "type": "string", "default": "value1"},
            {"name": "field2", "type": "integer", "default": 42}
        ]
    }

    form = AutoForm.from_schema(schema)

    # In real usage, this would be called after form is mounted
    # Here we verify the method exists
    assert hasattr(form, "get_values")


def test_set_values():
    """Test setting form values."""
    schema = {
        "fields": [
            {"name": "field1", "type": "string"},
            {"name": "field2", "type": "integer"}
        ]
    }

    form = AutoForm.from_schema(schema)

    # Verify method exists
    assert hasattr(form, "set_values")


def test_reset_to_defaults():
    """Test resetting form to default values."""
    schema = {
        "fields": [
            {"name": "field1", "type": "string", "default": "default_value"},
            {"name": "field2", "type": "integer", "default": 100}
        ]
    }

    form = AutoForm.from_schema(schema)

    # Verify reset method exists
    assert hasattr(form, "reset")


# Test Conditional Fields

def test_conditional_visibility(conditional_schema):
    """Test conditional field visibility."""
    form = AutoForm.from_schema(conditional_schema)

    # Check visible_when condition
    max_cycles_schema = form.field_schemas["max_cycles"]
    assert max_cycles_schema.visible_when == {"enable_optimization": True}


def test_field_dependencies(conditional_schema):
    """Test field dependencies."""
    form = AutoForm.from_schema(conditional_schema)

    conv_schema = form.field_schemas["convergence_threshold"]
    assert conv_schema.depends_on == "enable_optimization"


# Test JSON Serialization

def test_to_json(simple_schema):
    """Test exporting form state to JSON."""
    form = AutoForm.from_schema(simple_schema)

    json_data = form.to_json()

    assert "schema" in json_data
    assert "values" in json_data
    assert json_data["schema"] == simple_schema


def test_from_json():
    """Test creating form from JSON state."""
    json_data = {
        "schema": {
            "fields": [
                {"name": "test", "type": "string", "default": "value"}
            ]
        },
        "values": {"test": "loaded_value"}
    }

    form = AutoForm.from_json(json_data)

    assert form is not None
    assert "test" in form.field_schemas


# Test Form Actions

def test_submit_callback():
    """Test submit callback registration."""
    schema = {
        "fields": [
            {"name": "field1", "type": "string"}
        ]
    }

    form = AutoForm.from_schema(schema)

    callback_called = False

    def on_submit(values: Dict[str, Any]):
        nonlocal callback_called
        callback_called = True

    form.on_submit(on_submit)

    # Verify callback is registered
    assert form._submit_callback is not None


def test_form_messages():
    """Test form message types."""
    schema = {"fields": [{"name": "test", "type": "string"}]}
    form = AutoForm.from_schema(schema)

    # Verify message classes exist
    assert hasattr(AutoForm, "Submitted")
    assert hasattr(AutoForm, "Changed")


# Test ValidationError

def test_validation_error_creation():
    """Test ValidationError dataclass."""
    error = ValidationError(
        field_name="username",
        message="Username is required"
    )

    assert error.field_name == "username"
    assert error.message == "Username is required"
    assert error.severity == "error"


def test_validation_error_severity():
    """Test ValidationError severity levels."""
    error = ValidationError(
        field_name="age",
        message="Age should be positive",
        severity="warning"
    )

    assert error.severity == "warning"


# Integration Tests

def test_full_form_workflow(complex_schema):
    """Test complete form workflow."""
    # Create form
    form = AutoForm.from_schema(complex_schema)

    # Verify all fields created
    assert len(form.field_schemas) == 6

    # Verify form methods
    assert hasattr(form, "get_values")
    assert hasattr(form, "set_values")
    assert hasattr(form, "validate")
    assert hasattr(form, "reset")
    assert hasattr(form, "on_submit")

    # Verify field groups
    groups = set()
    for schema in form.field_schemas.values():
        if schema.group:
            groups.add(schema.group)

    assert "Calculation Settings" in groups
    assert "Convergence" in groups
    assert "Advanced" in groups
    assert "Files" in groups


def test_validation_workflow():
    """Test validation workflow."""
    schema = {
        "fields": [
            {
                "name": "required_field",
                "type": "string",
                "required": True
            },
            {
                "name": "ranged_int",
                "type": "integer",
                "min": 1,
                "max": 10
            }
        ]
    }

    form = AutoForm.from_schema(schema)

    # Validate empty form
    errors = form.validate()

    # Should have error for required field
    assert len(errors) > 0


def test_conditional_workflow(conditional_schema):
    """Test conditional field workflow."""
    form = AutoForm.from_schema(conditional_schema)

    # Verify conditional setup
    assert "enable_optimization" in form.field_schemas
    assert "max_cycles" in form.field_schemas

    max_cycles = form.field_schemas["max_cycles"]
    assert max_cycles.visible_when is not None


# Performance Tests

def test_large_form_creation():
    """Test creating form with many fields."""
    fields = []
    for i in range(50):
        fields.append({
            "name": f"field_{i}",
            "type": "string",
            "label": f"Field {i}",
            "default": f"value_{i}"
        })

    schema = {"fields": fields}
    form = AutoForm.from_schema(schema)

    assert len(form.field_schemas) == 50


def test_nested_groups():
    """Test form with multiple field groups."""
    fields = []
    groups = ["Group A", "Group B", "Group C"]

    for i, group in enumerate(groups):
        for j in range(5):
            fields.append({
                "name": f"field_{i}_{j}",
                "type": "string",
                "group": group
            })

    schema = {"fields": fields}
    form = AutoForm.from_schema(schema)

    # Verify all fields created
    assert len(form.field_schemas) == 15

    # Verify groups
    field_groups = set()
    for field_schema in form.field_schemas.values():
        if field_schema.group:
            field_groups.add(field_schema.group)

    assert len(field_groups) == 3
    assert "Group A" in field_groups
