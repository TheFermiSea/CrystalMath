# AutoForm: Dynamic Form Generation

The `AutoForm` widget provides automatic generation of Textual forms from JSON schemas with comprehensive validation, conditional fields, and support for multiple input types.

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Field Types](#field-types)
4. [Validation](#validation)
5. [Conditional Fields](#conditional-fields)
6. [Form Groups](#form-groups)
7. [Advanced Features](#advanced-features)
8. [API Reference](#api-reference)
9. [Examples](#examples)

## Overview

AutoForm enables rapid development of parameter input interfaces by automatically generating forms from JSON schema definitions. It handles:

- **Multiple field types**: string, integer, float, boolean, select, multiselect, file
- **Real-time validation**: Immediate feedback as users type
- **Conditional visibility**: Show/hide fields based on other field values
- **Field dependencies**: Cross-field validation rules
- **Grouping**: Organize fields into collapsible sections
- **State persistence**: Save/load form state as JSON

## Quick Start

### Basic Usage

```python
from textual.app import App, ComposeResult
from src.tui.widgets.auto_form import AutoForm

class MyApp(App):
    def compose(self) -> ComposeResult:
        schema = {
            "fields": [
                {
                    "name": "username",
                    "type": "string",
                    "label": "Username",
                    "required": True,
                    "help": "Your username"
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

        form = AutoForm.from_schema(schema)
        yield form

    def on_auto_form_submitted(self, message: AutoForm.Submitted) -> None:
        values = message.values
        self.notify(f"Form submitted: {values}")

if __name__ == "__main__":
    MyApp().run()
```

### Loading from JSON File

```python
import json
from pathlib import Path

# Load schema from file
schema_path = Path("examples/forms/complex_form.json")
with open(schema_path) as f:
    schema = json.load(f)

# Create form
form = AutoForm.from_schema(schema)
```

## Field Types

### String Field

Text input with optional pattern validation.

```json
{
  "name": "email",
  "type": "string",
  "label": "Email Address",
  "required": true,
  "pattern": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
  "placeholder": "user@example.com",
  "help": "Enter your email address"
}
```

**Properties:**
- `pattern`: Regex pattern for validation
- `placeholder`: Placeholder text
- `default`: Default value

### Integer Field

Integer input with range validation.

```json
{
  "name": "port",
  "type": "integer",
  "label": "Port Number",
  "default": 8080,
  "min": 1024,
  "max": 65535,
  "required": true,
  "help": "TCP port for the server"
}
```

**Properties:**
- `min`: Minimum value
- `max`: Maximum value
- `default`: Default value

### Float Field

Floating-point input with range validation.

```json
{
  "name": "tolerance",
  "type": "float",
  "label": "Convergence Tolerance",
  "default": 1e-7,
  "min": 1e-12,
  "max": 1e-3,
  "help": "SCF convergence threshold"
}
```

**Properties:**
- `min`: Minimum value
- `max`: Maximum value
- `default`: Default value

### Boolean Field

On/off switch widget.

```json
{
  "name": "enable_logging",
  "type": "boolean",
  "label": "Enable Debug Logging",
  "default": false,
  "help": "Save detailed execution logs"
}
```

**Properties:**
- `default`: Default state (true/false)

### Select Field

Dropdown selection from predefined options.

```json
{
  "name": "basis_set",
  "type": "select",
  "label": "Basis Set",
  "options": ["sto-3g", "6-21g", "6-31g", "pob-tzvp"],
  "default": "sto-3g",
  "required": true,
  "help": "Choose basis set for calculation"
}
```

**Properties:**
- `options`: List of available choices
- `default`: Default selection
- `required`: Whether selection is mandatory

### MultiSelect Field

Multiple selection using checkboxes.

```json
{
  "name": "properties",
  "type": "multiselect",
  "label": "Properties to Calculate",
  "options": ["BAND", "DOSS", "ECHG", "POTM"],
  "default": ["BAND"],
  "help": "Select one or more properties"
}
```

**Properties:**
- `options`: List of available choices
- `default`: List of pre-selected values

### File Field

File path input with browse button.

```json
{
  "name": "input_file",
  "type": "file",
  "label": "Input Geometry",
  "help": "Select .cif or .xyz file",
  "required": false
}
```

**Properties:**
- Automatically validates file existence
- Browse button for file picker (implementation pending)

## Validation

### Built-in Validation

AutoForm provides automatic validation for all field types:

- **Required fields**: Show `*` indicator, validate on submit
- **Range validation**: Min/max for numeric types
- **Pattern matching**: Regex validation for strings
- **File existence**: Check if file paths exist

### Custom Validators

Define custom validation functions:

```json
{
  "name": "even_number",
  "type": "integer",
  "label": "Even Number",
  "validator": "lambda x: int(x) % 2 == 0",
  "validator_message": "Must be an even number"
}
```

In Python:

```python
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
```

### Real-time Validation

Forms validate as users type:

- **Green border**: Valid input
- **Red border**: Invalid input
- **Error messages**: Displayed below field
- **Submit disabled**: Until all fields valid

### Cross-field Validation

Validate dependencies between fields:

```json
{
  "name": "max_cycles",
  "type": "integer",
  "depends_on": "enable_optimization"
}
```

If `enable_optimization` is false/empty and `max_cycles` has a value, validation fails with:
> "Requires enable_optimization to be set"

## Conditional Fields

### Visibility Conditions

Show/hide fields based on other field values:

```json
{
  "name": "enable_optimization",
  "type": "boolean",
  "label": "Enable Optimization",
  "default": false
},
{
  "name": "max_cycles",
  "type": "integer",
  "label": "Max Optimization Cycles",
  "visible_when": {
    "enable_optimization": true
  }
}
```

The `max_cycles` field only appears when `enable_optimization` is checked.

### Multiple Conditions

Require multiple conditions to be met:

```json
{
  "name": "advanced_option",
  "type": "string",
  "visible_when": {
    "mode": "advanced",
    "enable_features": true
  }
}
```

Field appears only when BOTH conditions are true.

### Field Dependencies

Mark fields as dependent on others for validation:

```json
{
  "name": "convergence_threshold",
  "type": "float",
  "depends_on": "enable_optimization"
}
```

This creates a validation relationship without affecting visibility.

## Form Groups

Organize fields into collapsible sections:

```json
{
  "fields": [
    {
      "name": "basis_set",
      "type": "select",
      "group": "Electronic Structure",
      ...
    },
    {
      "name": "functional",
      "type": "select",
      "group": "Electronic Structure",
      ...
    },
    {
      "name": "shrink",
      "type": "integer",
      "group": "Sampling",
      ...
    }
  ]
}
```

Creates visual groups with borders and titles.

## Advanced Features

### Form State Persistence

Save and restore form state:

```python
# Save form state
state = form.to_json()
with open("form_state.json", "w") as f:
    json.dump(state, f)

# Load form state
with open("form_state.json") as f:
    state = json.load(f)
form = AutoForm.from_json(state)
```

### Submit Callback

Register callback for form submission:

```python
def handle_submit(values: Dict[str, Any]):
    print(f"Received values: {values}")
    # Process form data

form.on_submit(handle_submit)
```

### Change Events

React to individual field changes:

```python
def on_auto_form_changed(self, message: AutoForm.Changed):
    field_name = message.field_name
    value = message.value
    print(f"{field_name} changed to {value}")
```

### Programmatic Value Setting

Set form values from code:

```python
# Set individual values
form.set_values({
    "basis_set": "6-31g",
    "shrink": 12,
    "enable_optimization": True
})

# Get current values
values = form.get_values()
print(values)  # {"basis_set": "6-31g", ...}
```

### Reset to Defaults

Reset form to default values:

```python
form.reset()
```

## API Reference

### AutoForm Class

#### Constructor

```python
AutoForm(schema: Dict[str, Any], **kwargs)
```

#### Class Methods

**`from_schema(schema: Dict[str, Any]) -> AutoForm`**

Create form from schema dictionary.

**`from_json(data: Dict[str, Any]) -> AutoForm`**

Create form from saved JSON state (includes schema + values).

#### Instance Methods

**`get_values() -> Dict[str, Any]`**

Collect all form field values.

**`set_values(data: Dict[str, Any]) -> None`**

Set form values from dictionary.

**`validate() -> List[ValidationError]`**

Validate all fields and return errors.

**`reset() -> None`**

Reset all fields to default values.

**`on_submit(callback: Callable[[Dict[str, Any]], None]) -> None`**

Register callback for form submission.

**`to_json() -> Dict[str, Any]`**

Export form state (schema + values) to JSON.

#### Messages

**`AutoForm.Submitted(values: Dict[str, Any])`**

Posted when form is submitted successfully.

**`AutoForm.Changed(field_name: str, value: Any)`**

Posted when any field value changes.

### FieldSchema Dataclass

```python
@dataclass
class FieldSchema:
    name: str
    type: str
    label: str = ""
    default: Any = None
    required: bool = False
    help: str = ""

    # Validation
    min: Optional[Union[int, float]] = None
    max: Optional[Union[int, float]] = None
    pattern: Optional[str] = None
    options: Optional[List[Any]] = None

    # Conditional
    visible_when: Optional[Dict[str, Any]] = None
    depends_on: Optional[str] = None

    # Custom
    validator: Optional[Callable[[Any], bool]] = None
    validator_message: str = "Invalid value"

    # UI
    placeholder: str = ""
    disabled: bool = False
    group: str = ""
```

### ValidationError Dataclass

```python
@dataclass
class ValidationError:
    field_name: str
    message: str
    severity: str = "error"  # error, warning, info
```

## Examples

### Example 1: Simple Contact Form

```python
from src.tui.widgets.auto_form import AutoForm

schema = {
    "fields": [
        {
            "name": "name",
            "type": "string",
            "label": "Full Name",
            "required": True,
            "placeholder": "John Doe"
        },
        {
            "name": "email",
            "type": "string",
            "label": "Email",
            "required": True,
            "pattern": "^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$",
            "placeholder": "john@example.com"
        },
        {
            "name": "age",
            "type": "integer",
            "label": "Age",
            "min": 18,
            "max": 100
        },
        {
            "name": "subscribe",
            "type": "boolean",
            "label": "Subscribe to newsletter",
            "default": False
        }
    ]
}

form = AutoForm.from_schema(schema)
```

### Example 2: CRYSTAL23 Calculation Parameters

See `examples/forms/complex_form.json` for a complete example with:
- Electronic structure settings (basis set, functional)
- Convergence parameters (tolerances, max cycles)
- Sampling options (k-points)
- Properties to calculate
- Resource allocation

```python
import json

with open("examples/forms/complex_form.json") as f:
    schema = json.load(f)

form = AutoForm.from_schema(schema)
```

### Example 3: Conditional Workflow Form

See `examples/forms/conditional_form.json` for:
- Calculation type selection
- Conditional optimization parameters
- Conditional frequency calculation
- Conditional elastic constants
- Conditional MPI settings

Fields appear/disappear based on user selections.

### Example 4: Integration with TUI

```python
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer
from src.tui.widgets.auto_form import AutoForm
import json

class CalculationSetup(App):
    """Setup screen for CRYSTAL23 calculation."""

    CSS = """
    Screen {
        align: center middle;
    }

    AutoForm {
        width: 80%;
        height: 90%;
        border: thick $primary;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()

        # Load complex calculation schema
        with open("examples/forms/complex_form.json") as f:
            schema = json.load(f)

        form = AutoForm.from_schema(schema)
        form.on_submit(self.handle_submit)
        yield form

        yield Footer()

    def handle_submit(self, values: dict):
        """Handle form submission."""
        # Save configuration
        with open("calculation_config.json", "w") as f:
            json.dump(values, f, indent=2)

        self.notify("Configuration saved!", severity="information")
        self.exit(values)

if __name__ == "__main__":
    result = CalculationSetup().run()
    print(f"Calculation parameters: {result}")
```

## Best Practices

### 1. Use Descriptive Labels and Help Text

```json
{
  "name": "shrink",
  "type": "integer",
  "label": "Shrink Factor (k-mesh)",
  "help": "Monkhorst-Pack k-point mesh density. Higher values = more accurate but slower."
}
```

### 2. Set Reasonable Defaults

Provide sensible defaults to reduce user effort:

```json
{
  "name": "scf_tolerance",
  "type": "float",
  "default": 1e-7,
  "help": "Default is suitable for most calculations"
}
```

### 3. Group Related Fields

Organize forms into logical sections:

```json
{
  "group": "Electronic Structure"  // Basis set, functional
},
{
  "group": "Convergence"  // Tolerances, max cycles
}
```

### 4. Use Conditional Fields Sparingly

Only hide fields when truly dependent on other choices. Don't over-nest conditions.

### 5. Validate Early

Use `required`, `min`, `max`, and `pattern` for immediate validation feedback.

### 6. Test with Example Data

Use `examples/forms/` JSON files to test your form behavior before deployment.

## Troubleshooting

### Form Doesn't Display

**Problem**: Form appears empty or fields missing.

**Solution**: Check schema JSON syntax and field types. Ensure all required properties are present.

### Validation Not Working

**Problem**: Invalid inputs accepted.

**Solution**: Verify validators are correctly defined. Check that `min`, `max`, `pattern`, and custom validators are properly set.

### Conditional Fields Not Showing

**Problem**: Conditional fields never appear.

**Solution**: Inspect `visible_when` conditions. Use `get_values()` to debug current field values.

### Performance Issues with Large Forms

**Problem**: Form is slow with 50+ fields.

**Solution**: Use field groups to organize content. Consider splitting into multiple forms/screens.

## Future Enhancements

Planned features for future versions:

1. **Range/Slider Widget**: For numeric ranges with visual slider
2. **Date/Time Pickers**: For temporal data input
3. **Color Picker**: For visualization settings
4. **Dynamic Field Arrays**: Add/remove array elements
5. **Custom Field Renderers**: Plugin system for custom widgets
6. **Form Wizard**: Multi-step forms with progress tracking
7. **Auto-save**: Periodic form state persistence
8. **Undo/Redo**: Form editing history

## Contributing

To extend AutoForm with new field types:

1. Create a new `FormField` subclass in `auto_form.py`
2. Implement `compose()`, `get_value()`, `set_value()`, and `validate_field()`
3. Add type mapping in `AutoForm._create_field()`
4. Write unit tests in `tests/test_auto_form.py`
5. Document the new field type in this guide

## See Also

- **Textual Documentation**: https://textual.textualize.io/
- **CRYSTAL23 Manual**: For parameter descriptions
- **JSON Schema**: For schema validation standards
