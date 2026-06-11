# CRYSTAL23 Template System Documentation

## Overview

The CRYSTAL23 Template System provides a powerful and flexible way to generate input files for CRYSTAL23 calculations using Jinja2 templates. It includes parameter validation, type checking, template inheritance, and a comprehensive library of pre-built templates.

## Features

- **Jinja2-based templating** - Full power of Jinja2 syntax (conditionals, loops, filters)
- **Parameter validation** - Type checking, range validation, required parameters
- **Template library** - Pre-built templates for common calculations
- **Template inheritance** - Extend base templates for specialized use cases
- **Database integration** - Store and track templates
- **Preview mode** - See rendered output before running calculations

## Installation

The template system is included in the CRYSTAL-TUI package. Ensure you have the required dependencies:

```bash
pip install jinja2>=3.1.0 pyyaml>=6.0.0
```

Or install the full package:

```bash
pip install -e ".[dev]"
```

## Quick Start

### Using the TemplateManager

```python
from pathlib import Path
from src.core.templates import TemplateManager

# Initialize the manager
manager = TemplateManager()

# Load a template
template = manager.load_template(Path("templates/basic/single_point.yml"))

# Render with parameters
params = {
    "system_name": "MgO Crystal",
    "space_group": 225,
    "lattice_param": 4.21,
    "basis_set": "pob-tzvp",
    "shrink": 12,
    "convergence": 1e-9
}

input_file = manager.render(template, params)
print(input_file)
```

### Convenience Function

```python
from src.core.templates import render_template

# Quick rendering
input_file = render_template(
    Path("templates/basic/optimization.yml"),
    {"system_name": "Test", "basis_set": "6-21g"}
)
```

## Template Structure

Templates are YAML files with the following structure:

```yaml
name: "Template Name"
version: "1.0"
description: "What this template does"
author: "Your Name"
tags: ["category1", "category2"]

parameters:
  parameter_name:
    type: "parameter_type"
    default: default_value
    description: "What this parameter controls"
    # Optional constraints
    min: minimum_value
    max: maximum_value
    options: ["option1", "option2"]
    required: true/false

input_template: |
  Your CRYSTAL23 input file template
  Using {{ parameter_name }} syntax
```

## Parameter Types

### String

```yaml
system_name:
  type: "string"
  default: "My System"
  description: "System name/description"
  required: true
```

### Integer

```yaml
shrink:
  type: "integer"
  default: 8
  min: 1
  max: 32
  description: "K-point mesh density"
```

### Float

```yaml
convergence:
  type: "float"
  default: 1.0e-8
  min: 1.0e-12
  max: 1.0e-4
  description: "SCF convergence threshold"
```

### Boolean

```yaml
use_dft:
  type: "boolean"
  default: true
  description: "Enable DFT calculations"
```

### Select (Dropdown)

```yaml
basis_set:
  type: "select"
  options: ["sto-3g", "6-21g", "pob-tzvp"]
  default: "sto-3g"
  description: "Basis set selection"
```

### Multiselect (Multiple Choices)

```yaml
properties:
  type: "multiselect"
  options: ["band", "dos", "charge"]
  description: "Properties to calculate"
```

### File (File Path)

```yaml
geometry_file:
  type: "file"
  description: "External geometry file"
```

## Template Examples

### Basic Single Point Energy

```yaml
name: "Single Point Energy"
version: "1.0"
description: "Basic SCF energy calculation"
author: "CRYSTAL-TUI Team"
tags: ["basic", "energy"]

parameters:
  system_name:
    type: "string"
    default: "Crystal System"
    required: true

  basis_set:
    type: "select"
    options: ["sto-3g", "6-21g", "pob-tzvp"]
    default: "sto-3g"

  shrink:
    type: "integer"
    default: 8
    min: 1
    max: 32

input_template: |
  {{ system_name }}
  CRYSTAL
  0 0 0
  225
  4.21
  1
  12 {{ basis_set }}
  SHRINK
  {{ shrink }} {{ shrink }}
  END
```

### Template with Conditionals

```yaml
name: "Conditional Example"
parameters:
  use_dft:
    type: "boolean"
    default: false

  functional:
    type: "select"
    options: ["PBE", "B3LYP", "HSE06"]
    default: "PBE"
    depends_on:
      use_dft: true

input_template: |
  System
  CRYSTAL
  {% if use_dft %}
  DFT
  {{ functional }}
  {% endif %}
  END
```

### Template with Loops

```yaml
name: "Multi-Atom System"
parameters:
  atoms:
    type: "string"

input_template: |
  Multi-atom system
  CRYSTAL
  {% for atom in atoms %}
  ATOM {{ atom.number }}
  {{ atom.basis_set }}
  {% endfor %}
  END
```

## Built-in Template Library

### Basic Templates (`templates/basic/`)

1. **single_point.yml** - Single point energy calculation
2. **optimization.yml** - Geometry optimization
3. **frequency.yml** - Vibrational frequency analysis

### Advanced Templates (`templates/advanced/`)

1. **band_structure.yml** - Electronic band structure
2. **dos.yml** - Density of states
3. **elastic_constants.yml** - Mechanical properties
4. **surface_slab.yml** - Surface calculations

### Workflow Templates (`templates/workflows/`)

1. **opt_freq.yml** - Optimization followed by frequency
2. **convergence_scan.yml** - Basis set/k-point convergence testing

## TemplateManager API Reference

### Initialization

```python
manager = TemplateManager(template_dir: Optional[Path] = None)
```

Creates a new template manager. If `template_dir` is not specified, uses the default `templates/` directory.

### Loading Templates

```python
template = manager.load_template(path: Path) -> Template
```

Load a template from a YAML file. Templates are cached for performance.

### Rendering Templates

```python
input_file = manager.render(
    template: Template,
    params: Dict[str, Any]
) -> str
```

Render a template with given parameters. Validates parameters before rendering.

**Raises:**
- `ValueError` - If parameter validation fails
- `TemplateSyntaxError` - If template has syntax errors

### Validating Parameters

```python
errors = manager.validate_params(
    template: Template,
    params: Dict[str, Any]
) -> List[str]
```

Validate parameters without rendering. Returns list of error messages (empty if valid).

### Getting Defaults

```python
defaults = manager.get_default_params(template: Template) -> Dict[str, Any]
```

Get dictionary of all default parameter values.

### Listing Templates

```python
templates = manager.list_templates(tags: Optional[List[str]] = None) -> List[Template]
```

List all available templates, optionally filtered by tags (OR logic).

```python
# All templates
all_templates = manager.list_templates()

# Only optimization templates
opt_templates = manager.list_templates(tags=["optimization"])

# Advanced templates
advanced = manager.list_templates(tags=["advanced"])
```

### Finding Templates

```python
template = manager.find_template(name: str) -> Optional[Template]
```

Find a template by exact name match.

### Saving Templates

```python
manager.save_template(template: Template, path: Path) -> None
```

Save a template to a YAML file.

### Previewing Templates

```python
preview = manager.preview_template(template: Template) -> str
```

Generate a preview using default parameter values.

### Getting Template Info

```python
info = manager.get_template_info(template: Template) -> Dict[str, Any]
```

Get detailed metadata about a template:

```python
{
    "name": "Template Name",
    "version": "1.0",
    "description": "...",
    "author": "...",
    "tags": [...],
    "parameter_count": 5,
    "parameters": [
        {
            "name": "param1",
            "type": "integer",
            "required": True,
            "default": 8,
            "description": "..."
        },
        ...
    ]
}
```

## Advanced Usage

### Creating Custom Templates

```python
from src.core.templates import Template, ParameterDefinition

# Define parameters
params = {
    "system_name": ParameterDefinition(
        name="system_name",
        type="string",
        required=True,
        description="System name"
    ),
    "basis": ParameterDefinition(
        name="basis",
        type="select",
        options=["sto-3g", "6-21g"],
        default="sto-3g"
    )
}

# Create template
template = Template(
    name="Custom Template",
    version="1.0",
    description="My custom template",
    author="Me",
    tags=["custom"],
    parameters=params,
    input_template="""
{{ system_name }}
CRYSTAL
BASIS {{ basis }}
END
"""
)

# Save it
manager = TemplateManager()
manager.save_template(template, Path("templates/custom/my_template.yml"))
```

### Parameter Validation Details

The validation system checks:

1. **Type correctness** - Values match parameter type
2. **Range constraints** - Values within min/max bounds
3. **Required parameters** - All required parameters provided
4. **Valid options** - Select/multiselect values are valid
5. **Conditional dependencies** - Dependent parameters only when needed
6. **Unknown parameters** - No extra parameters provided

Example validation errors:

```python
errors = manager.validate_params(template, params)
# ['Parameter "shrink" must be <= 32',
#  'Parameter "basis_set" must be one of ["sto-3g", "6-21g"]',
#  'Unknown parameter: invalid_param']
```

### Template Inheritance (Future Feature)

```yaml
name: "Extended Optimization"
extends: "templates/basic/optimization.yml"

parameters:
  additional_param:
    type: "integer"
    default: 10

input_template: |
  {{ parent.input_template }}
  ADDITIONAL_KEYWORD
  {{ additional_param }}
```

### Template Includes (Future Feature)

```yaml
name: "Combined Template"
includes:
  - "templates/fragments/basis_block.yml"
  - "templates/fragments/scf_block.yml"

input_template: |
  System
  {{ include.basis_block }}
  {{ include.scf_block }}
  END
```

## Integration with TUI

The template system integrates with the TUI for interactive template selection and parameter input:

```python
# In TUI code
from src.core.templates import TemplateManager

manager = TemplateManager()

# List templates for user selection
templates = manager.list_templates(tags=["basic"])

# Get template info for display
info = manager.get_template_info(selected_template)

# Generate form from parameters
for param_name, param_def in template.parameters.items():
    if param_def.type == "select":
        # Show dropdown with options
        pass
    elif param_def.type == "integer":
        # Show integer input with min/max
        pass

# Render when user submits
try:
    input_file = manager.render(template, user_params)
    # Save and run calculation
except ValueError as e:
    # Show validation errors to user
    pass
```

## Integration with Database

Templates can be stored in the job database:

```python
from src.core.database import Database

db = Database()

# Store template with job
db.create_job(
    name="my_calculation",
    input_content=rendered_input,
    template_name=template.name,
    template_params=json.dumps(params)
)

# Retrieve and recreate
job = db.get_job(job_id)
template = manager.find_template(job.template_name)
params = json.loads(job.template_params)

# Re-render if needed
input_file = manager.render(template, params)
```

## Best Practices

### Template Design

1. **Clear naming** - Use descriptive parameter names
2. **Good defaults** - Provide sensible default values
3. **Documentation** - Write clear descriptions for all parameters
4. **Validation** - Set appropriate min/max ranges
5. **Tags** - Use consistent, searchable tags

### Parameter Organization

Group related parameters:

```yaml
# SCF parameters
scf_convergence:
  type: "float"
  default: 1.0e-8

scf_max_cycles:
  type: "integer"
  default: 50

# Geometry parameters
lattice_a:
  type: "float"

lattice_b:
  type: "float"
```

### Error Handling

Always handle validation errors:

```python
try:
    input_file = manager.render(template, params)
except ValueError as e:
    print(f"Parameter validation failed: {e}")
    # Show errors to user, don't proceed
except TemplateSyntaxError as e:
    print(f"Template syntax error at line {e.lineno}: {e}")
    # Template needs to be fixed
```

### Testing Templates

Test your templates with various parameter combinations:

```python
# Test with defaults
preview = manager.preview_template(template)
assert "CRYSTAL" in preview

# Test with edge cases
params_min = {"shrink": 1}  # Minimum value
params_max = {"shrink": 32}  # Maximum value

# Test validation
errors = manager.validate_params(template, {"shrink": 100})
assert len(errors) > 0  # Should fail validation
```

## Troubleshooting

### Template Not Found

```
FileNotFoundError: Template file not found: templates/my_template.yml
```

**Solution:** Check the path is correct and relative to the template directory.

### Parameter Validation Fails

```
ValueError: Parameter validation failed:
Parameter 'shrink' must be <= 32
```

**Solution:** Check parameter values are within defined ranges and of correct type.

### Template Syntax Error

```
TemplateSyntaxError: unexpected end of template, expected 'end of print statement'.
```

**Solution:** Check Jinja2 syntax in your template. Common issues:
- Missing closing braces `}}`
- Unclosed `{% if %}` blocks
- Invalid variable names

### Unknown Parameter

```
Parameter validation failed:
Unknown parameter: my_param
```

**Solution:** The parameter is not defined in the template's `parameters` section. Add it or remove it from your input.

## Examples Gallery

### Complete MgO Optimization

```python
from src.core.templates import TemplateManager
from pathlib import Path

manager = TemplateManager()
template = manager.load_template(Path("templates/basic/optimization.yml"))

params = {
    "system_name": "MgO Rocksalt Structure",
    "space_group": 225,
    "lattice_param": 4.21,
    "basis_set": "pob-tzvp",
    "shrink": 12,
    "convergence": 1e-9,
    "opt_type": "FULLOPTG",
    "max_opt_cycles": 100,
    "grad_threshold": 3e-4,
    "disp_threshold": 1.2e-3
}

input_file = manager.render(template, params)

# Save to file
with open("mgo_opt.d12", "w") as f:
    f.write(input_file)
```

### Band Structure Calculation

```python
manager = TemplateManager()
template = manager.load_template(Path("templates/advanced/band_structure.yml"))

params = {
    "system_name": "Silicon Band Structure",
    "space_group": 227,
    "lattice_param": 5.43,
    "basis_set": "pob-tzvp",
    "shrink": 16,
    "convergence": 1e-10,
    "k_path_points": 50,
    "band_range_lower": 1,
    "band_range_upper": 20,
    "use_dft": True,
    "fermi_print": True
}

input_file = manager.render(template, params)
```

### Workflow: Optimization + Frequency

```python
manager = TemplateManager()
template = manager.load_template(Path("templates/workflows/opt_freq.yml"))

params = {
    "system_name": "H2O Molecule Opt+Freq",
    "space_group": 1,
    "lattice_param": 15.0,  # Large cell for molecule
    "basis_set": "6-31g",
    "shrink": 1,  # Gamma point only
    "convergence": 1e-8,
    "opt_type": "ATOMONLY",
    "temperature": 298.15
}

input_file = manager.render(template, params)
```

## Future Enhancements

Planned features for future versions:

1. **Template inheritance** - Extend base templates
2. **Template includes** - Modular template composition
3. **Preset management** - Save/load parameter sets
4. **Template validation** - Check templates before use
5. **Template library updates** - More pre-built templates
6. **Visual template editor** - GUI for template creation
7. **Template versioning** - Track template changes
8. **Template sharing** - Export/import templates

## Contributing Templates

To contribute a template to the library:

1. Create your template YAML file
2. Test thoroughly with various parameters
3. Add comprehensive parameter descriptions
4. Tag appropriately for discoverability
5. Submit a pull request with:
   - Template file in appropriate directory
   - Example usage in this documentation
   - Unit tests for the template

## Support

For issues, questions, or contributions:

- GitHub Issues: [repository]/issues
- Documentation: `docs/TEMPLATE_SYSTEM.md`
- Examples: `templates/` directory
- Tests: `tests/test_templates.py`

## License

MIT License - see project LICENSE file.
