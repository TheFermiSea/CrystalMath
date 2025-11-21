# Template Browser

The Template Browser provides a graphical interface for browsing, selecting, and using pre-defined calculation templates in CRYSTAL-TUI.

## Overview

Templates are YAML-based configuration files that define:
- **Input structure**: Jinja2 template for generating CRYSTAL input files
- **Parameters**: Customizable values with types, defaults, and validation rules
- **Metadata**: Name, author, version, tags, and description

## Opening the Template Browser

Press `t` from the main TUI screen to open the Template Browser.

## UI Layout

```
┌─ Template Browser ────────────────────────────────┐
│ Search: [________]  Tags: [oxide] [bulk]          │
├──────────────┬────────────────────────────────────┤
│ Templates    │ Template Details                   │
│              │                                     │
│ 📁 Basic (3) │ Name: MgO Optimization            │
│  📄 Single   │ Author: CRYSTAL Team               │
│  📄 Opt ←    │ Version: 1.0                       │
│  📄 Freq     │                                     │
│              │ Parameters:                         │
│ 🔬 Advanced  │ • basis_set: sto-3g (select)       │
│  📄 Band     │ • shrink: 8 (integer, 2-16)        │
│  📄 DOS      │ • convergence: 1e-8 (float)        │
│              │                                     │
│ 🔄 Workflows │ Preview:                            │
│  📄 Opt+Freq │ ┌────────────────────────┐         │
│              │ │MgO Crystal - sto-3g    │         │
│              │ │CRYSTAL                 │         │
│              │ │0 0 0                   │         │
│              │ └────────────────────────┘         │
├──────────────┴────────────────────────────────────┤
│ [Use Template] [Preview] [Cancel]                 │
└────────────────────────────────────────────────────┘
```

### Left Panel: Template List

- **Tree Structure**: Templates organized by category
  - 📄 Basic - Simple single-step calculations
  - 🔬 Advanced - Complex or specialized calculations
  - 🔄 Workflows - Multi-step calculation sequences

- **Template Count**: Number of templates in each category
- **Navigation**: Use arrow keys to browse, Enter to select

### Right Panel: Template Details

When a template is selected, the right panel shows:

1. **Metadata Section**
   - Template name
   - Author and version
   - Description
   - Tags

2. **Parameters Section**
   - List of all parameters with descriptions
   - Auto-generated form fields based on parameter types:
     - **String**: Text input
     - **Integer**: Numeric input with range validation
     - **Float**: Numeric input with range validation
     - **Boolean**: Checkbox
     - **Select**: Dropdown menu with predefined options
     - **File**: File path input

3. **Preview Section**
   - Live preview of rendered input file
   - Updates when parameters are changed
   - Syntax highlighted
   - Shows default parameter values initially

## Using Templates

### Basic Workflow

1. **Open Template Browser** (`t` key)
2. **Browse Templates**: Navigate the tree with arrow keys
3. **Select Template**: Click or press Enter on a template
4. **Review Details**: Check metadata and parameters
5. **Edit Parameters** (optional): Modify default values
6. **Preview**: Press "Preview" button or `Space` to see rendered input
7. **Use Template**: Press "Use Template" button or `Enter` to create job
8. **Job Created**: Job is automatically created with rendered input

### Search and Filter

**Search Box** (top-left):
- Incremental search by template name or description
- Press `/` to focus search box
- Type to filter templates in real-time

**Tag Filter** (top-right):
- Filter by tags (comma-separated)
- Example: `oxide,bulk` shows only oxide bulk templates
- Supports multiple tags (OR logic)

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `t` | Focus template tree |
| `/` | Focus search box |
| `↑`/`↓` | Navigate template tree |
| `Enter` | Use selected template |
| `Space` | Preview with current parameters |
| `Esc` | Cancel and close |

## Parameter Types

### String Parameters

```yaml
parameters:
  crystal_name:
    type: string
    description: "Name of the crystal system"
    default: "MgO"
    required: true
```

UI: Text input field

### Integer Parameters

```yaml
parameters:
  shrink:
    type: integer
    description: "k-point shrinking factor"
    default: 8
    min: 2
    max: 16
    required: true
```

UI: Numeric input with range validation

### Float Parameters

```yaml
parameters:
  convergence:
    type: float
    description: "SCF convergence threshold"
    default: 1.0e-8
    min: 1.0e-12
    max: 1.0e-4
    required: true
```

UI: Numeric input with scientific notation support

### Select Parameters

```yaml
parameters:
  basis_set:
    type: select
    description: "Basis set for calculation"
    default: "sto-3g"
    options: ["sto-3g", "6-21g", "6-31g", "6-311g"]
    required: true
```

UI: Dropdown menu with predefined options

### Boolean Parameters

```yaml
parameters:
  use_optimization:
    type: boolean
    description: "Enable geometry optimization"
    default: true
```

UI: Checkbox

### File Parameters

```yaml
parameters:
  structure_file:
    type: file
    description: "External structure file (.gui)"
    required: false
```

UI: File path input with validation

## Parameter Validation

Parameters are validated in real-time and before template rendering:

- **Required Check**: Required parameters must have a value
- **Type Check**: Values must match parameter type
- **Range Check**: Numeric values must be within min/max bounds
- **Options Check**: Select values must be from predefined options
- **File Check**: File paths must exist

Validation errors are displayed below the parameter field in red.

## Template Structure

Templates are YAML files located in `/templates/` directory:

```yaml
name: "Template Name"
version: "1.0"
description: "Template description"
author: "Author Name"
tags: ["tag1", "tag2"]

parameters:
  param_name:
    type: string|integer|float|boolean|select|file
    description: "Parameter description"
    default: default_value
    min: minimum_value       # For integer/float
    max: maximum_value       # For integer/float
    options: [opt1, opt2]    # For select
    required: true|false

input_template: |
  CRYSTAL input content
  Using {{ param_name }} syntax
  {% if conditional %}
  Conditional content
  {% endif %}
  END
```

### Jinja2 Templating

Templates use Jinja2 syntax:

- **Variables**: `{{ parameter_name }}`
- **Conditionals**: `{% if condition %} ... {% endif %}`
- **Loops**: `{% for item in list %} ... {% endfor %}`
- **Comments**: `{# This is a comment #}`

Example:
```jinja2
MgO Crystal - {{ basis_set }}
CRYSTAL
0 0 0
225
4.21
2
12 0.0 0.0 0.0
8  0.5 0.5 0.5
{% if optimize %}
OPTGEOM
FULLOPTG
END
{% endif %}
END
```

## Creating Custom Templates

### Template Directory Structure

```
templates/
├── basic/
│   ├── single_point.yaml
│   ├── optimization.yaml
│   └── frequency.yaml
├── advanced/
│   ├── band_structure.yaml
│   ├── dos.yaml
│   └── phonon.yaml
└── workflows/
    ├── opt_freq.yaml
    └── convergence_test.yaml
```

### Template Categories

Templates are automatically categorized based on tags:
- **basic** tag → Basic category (📄)
- **advanced** tag → Advanced category (🔬)
- **workflow** tag → Workflows category (🔄)
- No matching tag → Other category (📦)

### Example: Creating a Band Structure Template

```yaml
name: "Band Structure Calculation"
version: "1.0"
description: "Calculate electronic band structure with optional DOS"
author: "Your Name"
tags: ["advanced", "band", "electronic"]

parameters:
  shrink_scf:
    type: integer
    description: "k-point mesh for SCF"
    default: 8
    min: 2
    max: 20
    required: true

  shrink_bands:
    type: integer
    description: "k-point mesh for bands"
    default: 16
    min: 4
    max: 40
    required: true

  calculate_dos:
    type: boolean
    description: "Also calculate density of states"
    default: true

  num_bands:
    type: integer
    description: "Number of bands to print"
    default: 20
    min: 1
    max: 100

input_template: |
  Band Structure Calculation
  CRYSTAL
  0 0 0
  225
  4.21
  2
  12 0.0 0.0 0.0
  8  0.5 0.5 0.5
  END
  {# Basis set section #}
  12 3
  0 0 6 2.0 1.0
    2.568500e+03 2.143510e-03
    3.849300e+02 1.649790e-02
  ...
  END
  SHRINK
  {{ shrink_scf }} {{ shrink_scf }}
  TOLDEE
  8
  END
  {# Properties calculation #}
  BAND
  {{ num_bands }}
  1 0 0 50  # Path definition
  0 1 0 50
  SHRINK
  {{ shrink_bands }} {{ shrink_bands }}
  {% if calculate_dos %}
  DOSS
  20
  {% endif %}
  END

metadata:
  calculation_type: "band_structure"
  complexity: "advanced"
```

## Integration with Job Creation

When "Use Template" is clicked:

1. **Parameters Validated**: All parameters checked against definitions
2. **Template Rendered**: Jinja2 template rendered with parameter values
3. **Job Created**: New job created in database with rendered input
4. **Working Directory**: Created as `calculations/XXXX_template_name_timestamp/`
5. **Files Written**:
   - `input.d12` - Rendered CRYSTAL input file
   - `template_metadata.json` - Template name and parameter values

## Troubleshooting

### Template Not Found

**Problem**: Template doesn't appear in browser

**Solutions**:
- Check template is in `/templates/` directory
- Verify YAML syntax is valid (`yamllint template.yaml`)
- Check file extension is `.yaml` or `.yml`
- Restart TUI to reload templates

### Validation Errors

**Problem**: Cannot use template due to validation errors

**Solutions**:
- Check parameter values are within allowed ranges
- Ensure required parameters are filled
- For file parameters, verify file paths exist
- Check parameter types match (e.g., integer not string)

### Rendering Errors

**Problem**: Template fails to render

**Solutions**:
- Check Jinja2 syntax is correct
- Ensure all referenced parameters are defined
- Test template with `preview` before using
- Check for unmatched `{% %}` blocks

### Preview Shows Errors

**Problem**: Preview shows template syntax errors

**Solutions**:
- Validate Jinja2 syntax
- Check variable names match parameter definitions
- Ensure conditional blocks are properly closed
- Test with default parameters first

## Advanced Features

### Conditional Parameters

Parameters can depend on other parameter values:

```yaml
parameters:
  use_custom_basis:
    type: boolean
    default: false

  custom_basis_file:
    type: file
    depends_on:
      use_custom_basis: true
    required: false
```

The `custom_basis_file` parameter only appears when `use_custom_basis` is true.

### Template Inheritance

Templates can extend other templates:

```yaml
extends: "basic/single_point.yaml"

# Only need to override specific sections
parameters:
  additional_param:
    type: integer
    default: 5
```

### Template Includes

Templates can include reusable fragments:

```yaml
includes:
  - "fragments/basis_sets.yaml"
  - "fragments/convergence.yaml"
```

## Best Practices

1. **Descriptive Names**: Use clear, descriptive template names
2. **Good Defaults**: Provide sensible default values for all parameters
3. **Validation**: Set appropriate min/max ranges and required flags
4. **Documentation**: Write clear parameter descriptions
5. **Tags**: Use meaningful tags for easy filtering
6. **Testing**: Test templates with various parameter combinations
7. **Version Control**: Increment version when making changes
8. **Categories**: Use appropriate tags (basic/advanced/workflow)

## Example Templates

### Basic Optimization Template

```yaml
name: "Simple Optimization"
version: "1.0"
description: "Basic geometry optimization for any system"
author: "CRYSTAL Team"
tags: ["basic", "optimization"]

parameters:
  shrink:
    type: integer
    description: "k-point shrinking factor"
    default: 8
    min: 2
    max: 16
    required: true

  max_opt_steps:
    type: integer
    description: "Maximum optimization steps"
    default: 100
    min: 10
    max: 500

input_template: |
  Geometry Optimization
  EXTERNAL
  OPTGEOM
  MAXCYCLE
  {{ max_opt_steps }}
  END
  {# Load external geometry #}
  END
  SHRINK
  {{ shrink }} {{ shrink }}
  TOLDEE
  8
  END
```

## Future Enhancements

Planned features for future versions:

- [ ] Template favorites/bookmarks
- [ ] Recently used templates section
- [ ] Usage statistics tracking
- [ ] Template export/import
- [ ] Template sharing via repository
- [ ] Visual template editor
- [ ] Template validation before save
- [ ] Batch template application

## See Also

- [Template System Documentation](../src/core/templates.py)
- [Job Creation](./JOB_CREATION.md)
- [Input File Validation](./VALIDATION.md)
