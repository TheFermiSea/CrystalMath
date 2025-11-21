# AutoForm Examples

This directory contains example form schemas demonstrating the AutoForm widget capabilities.

## Files

### JSON Schemas

1. **`simple_form.json`** - Basic form with 3 fields
   - String field (job_name) with pattern validation
   - Integer field (num_cores) with range validation
   - Boolean field (enable_logging)

2. **`complex_form.json`** - Comprehensive CRYSTAL23 calculation parameters
   - 13 fields organized into groups
   - Electronic structure settings (basis set, functional)
   - Convergence parameters (tolerances, max cycles)
   - Sampling (k-point mesh)
   - Properties to calculate
   - Resource allocation
   - Demonstrates all field types

3. **`conditional_form.json`** - Advanced form with conditional fields
   - 14 fields with conditional visibility
   - Calculation type selection affects available options
   - Optimization parameters appear when optimization enabled
   - Frequency calculation options conditional
   - Elastic constants options conditional
   - MPI settings conditional on parallel execution

### Test Application

**`test_auto_form.py`** - Interactive test application

Run the test app to see AutoForm in action:

```bash
# Simple form
python3 test_auto_form.py simple_form.json

# Complex form
python3 test_auto_form.py complex_form.json

# Conditional form
python3 test_auto_form.py conditional_form.json
```

**Keyboard shortcuts:**
- `1` - Load simple form
- `2` - Load complex form
- `3` - Load conditional form
- `q` - Quit

## Usage Examples

### Loading a Schema

```python
import json
from src.tui.widgets.auto_form import AutoForm

# Load from file
with open("examples/forms/simple_form.json") as f:
    schema = json.load(f)

# Create form
form = AutoForm.from_schema(schema)
```

### Handling Submission

```python
def handle_submit(values: dict):
    print(f"Form submitted with values: {values}")

form = AutoForm.from_schema(schema)
form.on_submit(handle_submit)
```

### Getting Form Values

```python
# Get all values
values = form.get_values()

# Set values programmatically
form.set_values({
    "job_name": "my_calculation",
    "num_cores": 8,
    "enable_logging": True
})
```

### Validation

```python
# Validate form
errors = form.validate()

if errors:
    for error in errors:
        print(f"{error.field_name}: {error.message}")
else:
    print("Form is valid!")
```

## Schema Structure

All schemas follow this structure:

```json
{
  "fields": [
    {
      "name": "field_name",           // Required: Field identifier
      "type": "string",                // Required: Field type
      "label": "Display Label",        // Optional: Human-readable label
      "default": "default_value",      // Optional: Default value
      "required": true,                // Optional: Required field (default: false)
      "help": "Help text",             // Optional: Explanation text
      "placeholder": "Enter value",    // Optional: Placeholder text
      "pattern": "^regex$",            // Optional: Validation pattern
      "min": 0,                        // Optional: Min value (numeric)
      "max": 100,                      // Optional: Max value (numeric)
      "options": ["opt1", "opt2"],     // Optional: Select options
      "group": "Group Name",           // Optional: Field group
      "visible_when": {                // Optional: Conditional visibility
        "other_field": "value"
      },
      "depends_on": "other_field"      // Optional: Dependency validation
    }
  ]
}
```

## Field Types

- **string**: Text input with optional pattern validation
- **integer**: Integer input with range validation
- **float**: Floating-point input with range validation
- **boolean**: On/off switch
- **select**: Dropdown selection from options
- **multiselect**: Multiple selection using checkboxes
- **file**: File path input with browse button

## Best Practices

1. **Start Simple**: Begin with `simple_form.json` and add complexity
2. **Use Groups**: Organize related fields with `group` property
3. **Provide Help**: Always include `help` text for user guidance
4. **Set Defaults**: Provide sensible default values
5. **Validate Early**: Use `required`, `min`, `max`, `pattern` for immediate feedback
6. **Test Conditions**: Use `conditional_form.json` to test complex logic

## Creating Custom Schemas

1. Copy one of the example schemas as a template
2. Modify fields to match your requirements
3. Test with `test_auto_form.py`
4. Integrate into your TUI application

## Integration

To use AutoForm in your TUI application:

```python
from textual.app import App, ComposeResult
from src.tui.widgets.auto_form import AutoForm
import json

class MyApp(App):
    def compose(self) -> ComposeResult:
        # Load schema
        with open("path/to/schema.json") as f:
            schema = json.load(f)

        # Create and mount form
        form = AutoForm.from_schema(schema)
        form.on_submit(self.handle_submit)
        yield form

    def handle_submit(self, values: dict):
        # Process form data
        print(f"Received: {values}")

    def on_auto_form_submitted(self, message: AutoForm.Submitted):
        # Alternative: Handle via message
        self.handle_submit(message.values)
```

## See Also

- **Documentation**: `docs/AUTO_FORM.md`
- **Tests**: `tests/test_auto_form.py`
- **Source**: `src/tui/widgets/auto_form.py`
