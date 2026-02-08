# Template System Reference

The template system provides pre-configured input files for common DFT calculations across CRYSTAL, VASP, and Quantum Espresso.

## Import

```python
from crystalmath.templates import list_templates, get_template, load_template, TemplateInfo
```

## Functions

### list_templates

List available templates with optional filtering.

```python
list_templates(
    category: Optional[str] = None,
    dft_code: Optional[str] = None,
) -> Iterator[TemplateInfo]
```

**Parameters:**
- `category` - Filter by category: basic, advanced, workflows, vasp, qe, slurm
- `dft_code` - Filter by DFT code: crystal, vasp, qe

**Returns:** Iterator of `TemplateInfo` objects

**Example:**

```python
from crystalmath.templates import list_templates

# List all templates
for template in list_templates():
    print(f"{template.category}/{template.name}: {template.description}")

# Filter by category
for template in list_templates(category="advanced"):
    print(f"{template.name}: {template.description}")

# Filter by DFT code
for template in list_templates(dft_code="vasp"):
    print(f"{template.category}/{template.name}")

# Combined filtering
for template in list_templates(category="workflows", dft_code="crystal"):
    print(f"{template.name}: {template.tags}")
```

**Output:**

```
basic/single_point: Single-point energy calculation
basic/geometry_opt: Geometry optimization
advanced/band_structure: Band structure calculation with SCF + non-SCF steps
advanced/dos: Density of states calculation
workflows/convergence: Convergence study workflow
```

### get_template

Get path to a template file by ID.

```python
get_template(template_id: str) -> Optional[Path]
```

**Parameters:**
- `template_id` - Template identifier in format "category/name" (e.g., "basic/single_point")

**Returns:** `Path` to template file, or `None` if not found

**Example:**

```python
from crystalmath.templates import get_template

# Get template path
path = get_template("basic/single_point")
if path:
    print(f"Template found at: {path}")
    content = path.read_text()
else:
    print("Template not found")

# Short form (searches all categories)
path = get_template("single_point")
```

### load_template

Load and parse a template YAML file.

```python
load_template(template_id: str) -> Optional[dict]
```

**Parameters:**
- `template_id` - Template identifier in format "category/name"

**Returns:** Parsed template data as dictionary, or `None` if not found

**Example:**

```python
from crystalmath.templates import load_template

# Load template
data = load_template("advanced/band_structure")

if data:
    print(f"Description: {data['description']}")
    print(f"DFT Code: {data['dft_code']}")
    print(f"Tags: {data['tags']}")

    # Access template content
    if 'template' in data:
        print(f"Template content:\n{data['template']}")

    # Access parameters
    if 'parameters' in data:
        print(f"Parameters: {data['parameters']}")
```

**Template Structure:**

```yaml
description: "Band structure calculation with SCF + non-SCF steps"
dft_code: crystal
tags:
  - band_structure
  - electronic_structure
  - advanced

parameters:
  k_path:
    type: string
    description: "High-symmetry k-point path (e.g., 'GXMG')"
    default: "GXMG"
  k_points:
    type: integer
    description: "Number of k-points along path"
    default: 40

template: |
  {{ base_input }}
  BAND
  {{ k_points }} {{ k_path }}
  END
```

### get_template_dir

Get the canonical templates directory path.

```python
from crystalmath.templates import get_template_dir

templates_dir = get_template_dir()
print(f"Templates directory: {templates_dir}")
```

## TemplateInfo Dataclass

Metadata for a template file.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Template name (filename without extension) |
| `category` | `str` | Category (basic, advanced, workflows, vasp, qe, slurm) |
| `path` | `Path` | Full path to template file |
| `description` | `str` | Human-readable description |
| `dft_code` | `str` | Target DFT code (crystal, vasp, qe) |
| `tags` | `List[str]` | Searchable tags |

**Example:**

```python
from crystalmath.templates import list_templates

for template in list_templates(category="advanced"):
    print(f"Name: {template.name}")
    print(f"Category: {template.category}")
    print(f"Description: {template.description}")
    print(f"DFT Code: {template.dft_code}")
    print(f"Tags: {', '.join(template.tags)}")
    print(f"Path: {template.path}")
    print()
```

## Template Categories

### basic/

Simple single-step calculations:
- `single_point` - Single-point energy calculation
- `geometry_opt` - Geometry optimization
- `scf` - Self-consistent field calculation

**DFT Code:** crystal (default)

**Example:**

```python
from crystalmath.templates import load_template

data = load_template("basic/single_point")
```

### advanced/

Multi-step and specialized calculations:
- `band_structure` - Band structure calculation
- `dos` - Density of states
- `phonon` - Phonon calculation
- `elastic_constants` - Elastic tensor
- `eos` - Equation of state

**DFT Code:** crystal (default)

**Example:**

```python
from crystalmath.templates import list_templates

for t in list_templates(category="advanced"):
    print(f"{t.name}: {t.description}")
```

### workflows/

Multi-job workflow templates:
- `convergence` - Convergence study (k-points, basis, cutoff)
- `band_structure_workflow` - SCF + bands workflow
- `phonon_workflow` - Geometry optimization + phonon
- `eos_workflow` - Equation of state with volume scaling

**DFT Code:** crystal (default)

**Example:**

```python
from crystalmath.templates import load_template

workflow = load_template("workflows/convergence")
print(f"Steps: {workflow.get('steps', [])}")
```

### vasp/

VASP-specific templates:
- `relax` - Geometry relaxation
- `static` - Static calculation
- `bands` - Band structure
- `dos` - Density of states
- `convergence` - Convergence testing

**DFT Code:** vasp

**Example:**

```python
from crystalmath.templates import list_templates

for t in list_templates(dft_code="vasp"):
    print(f"{t.category}/{t.name}")
```

### qe/

Quantum Espresso templates:
- `scf` - Self-consistent field
- `relax` - Geometry relaxation
- `bands` - Band structure

**DFT Code:** qe (quantum_espresso)

### slurm/

Job scheduler templates:
- `basic_job` - Basic SLURM job script
- `array_job` - SLURM array job
- `mpi_job` - MPI parallel job

**Note:** These are shell script templates, not DFT input files.

## Template Rendering

Templates use Jinja2 syntax for parameter substitution:

```yaml
template: |
  CRYSTAL
  0 0 0
  {{ space_group }}
  {{ lattice_a }} {{ lattice_b }} {{ lattice_c }}
  {{ n_atoms }}
  {% for atom in atoms %}
  {{ atom.atomic_number }} {{ atom.x }} {{ atom.y }} {{ atom.z }}
  {% endfor %}
  END
```

**Rendering Example:**

```python
from jinja2 import Template
from crystalmath.templates import load_template

# Load template
data = load_template("basic/single_point")
template_str = data["template"]

# Render with parameters
template = Template(template_str)
rendered = template.render(
    space_group=225,
    lattice_a=4.211,
    lattice_b=4.211,
    lattice_c=4.211,
    n_atoms=2,
    atoms=[
        {"atomic_number": 12, "x": 0.0, "y": 0.0, "z": 0.0},
        {"atomic_number": 8, "x": 0.5, "y": 0.5, "z": 0.5},
    ],
)

print(rendered)
```

## Template Discovery

Templates are stored in the package at:

```
python/crystalmath/templates/
├── basic/
│   ├── single_point.yml
│   ├── geometry_opt.yml
│   └── scf.yml
├── advanced/
│   ├── band_structure.yml
│   ├── dos.yml
│   └── phonon.yml
├── workflows/
│   ├── convergence.yml
│   └── band_structure_workflow.yml
├── vasp/
│   ├── relax.yml
│   └── static.yml
└── slurm/
    └── basic_job.yml
```

**Custom Template Directories:**

You can add custom templates by placing YAML files in the appropriate category subdirectory.

## Complete Example

```python
from crystalmath.templates import list_templates, load_template
from jinja2 import Template

# List all CRYSTAL templates
print("Available CRYSTAL templates:")
for t in list_templates(dft_code="crystal"):
    print(f"  {t.category}/{t.name}: {t.description}")

# Load a specific template
data = load_template("advanced/band_structure")

if data:
    print(f"\nTemplate: {data['description']}")
    print(f"Tags: {', '.join(data['tags'])}")

    # Get parameters
    params = data.get("parameters", {})
    print("\nParameters:")
    for name, config in params.items():
        print(f"  {name}: {config['description']} (default: {config.get('default')})")

    # Render template
    template = Template(data["template"])
    rendered = template.render(
        base_input="...",  # Base SCF input
        k_points=40,
        k_path="GXMG",
    )
    print(f"\nRendered:\n{rendered}")
```

## Integration with API

Templates are automatically available through the API:

```python
from crystalmath.api import CrystalController

ctrl = CrystalController()

# List templates via JSON API
templates_json = ctrl.list_templates_json()

# Render template via JSON API
rendered_json = ctrl.render_template_json(
    "basic/single_point",
    '{"space_group": 225, "lattice_a": 4.211}'
)
```

## See Also

- [API Reference](api.md) - CrystalController methods
- [Models Reference](models.md) - Data structures
- [VASP Reference](vasp.md) - VASP input generation
