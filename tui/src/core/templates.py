"""
Template system for CRYSTAL23 input file generation using Jinja2.

This module provides a comprehensive template system with:
- Jinja2-based input file generation
- Parameter validation and type checking
- Template inheritance and includes
- Built-in template library
- Database integration
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml
from jinja2 import Environment, FileSystemLoader, Template as Jinja2Template, TemplateSyntaxError


@dataclass
class ParameterDefinition:
    """Definition of a template parameter."""

    name: str
    type: str  # string, integer, float, boolean, select, multiselect, file, structure
    default: Any = None
    description: str = ""
    min: Optional[Union[int, float]] = None
    max: Optional[Union[int, float]] = None
    options: Optional[List[str]] = None  # For select/multiselect
    required: bool = False
    depends_on: Optional[Dict[str, Any]] = None  # Conditional parameters

    def validate(self, value: Any) -> List[str]:
        """Validate a parameter value against this definition.

        Args:
            value: The value to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check required
        if self.required and value is None:
            errors.append(f"Parameter '{self.name}' is required")
            return errors

        if value is None:
            return errors

        # Type validation
        if self.type == "integer":
            if not isinstance(value, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    errors.append(f"Parameter '{self.name}' must be an integer")
                    return errors

            if self.min is not None and value < self.min:
                errors.append(f"Parameter '{self.name}' must be >= {self.min}")
            if self.max is not None and value > self.max:
                errors.append(f"Parameter '{self.name}' must be <= {self.max}")

        elif self.type == "float":
            if not isinstance(value, (int, float)):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    errors.append(f"Parameter '{self.name}' must be a number")
                    return errors

            if self.min is not None and value < self.min:
                errors.append(f"Parameter '{self.name}' must be >= {self.min}")
            if self.max is not None and value > self.max:
                errors.append(f"Parameter '{self.name}' must be <= {self.max}")

        elif self.type == "boolean":
            if not isinstance(value, bool):
                if str(value).lower() not in ["true", "false", "yes", "no", "1", "0"]:
                    errors.append(f"Parameter '{self.name}' must be a boolean")

        elif self.type == "string":
            if not isinstance(value, str):
                errors.append(f"Parameter '{self.name}' must be a string")

        elif self.type == "select":
            if self.options and value not in self.options:
                errors.append(
                    f"Parameter '{self.name}' must be one of {self.options}"
                )

        elif self.type == "multiselect":
            if not isinstance(value, list):
                errors.append(f"Parameter '{self.name}' must be a list")
            elif self.options:
                for item in value:
                    if item not in self.options:
                        errors.append(
                            f"Value '{item}' in '{self.name}' must be one of {self.options}"
                        )

        elif self.type == "file":
            if not isinstance(value, (str, Path)):
                errors.append(f"Parameter '{self.name}' must be a file path")
            elif not Path(value).exists():
                errors.append(f"File '{value}' for parameter '{self.name}' does not exist")

        return errors


@dataclass
class Template:
    """A CRYSTAL23 input file template."""

    name: str
    version: str
    description: str
    author: str
    tags: List[str]
    parameters: Dict[str, ParameterDefinition]
    input_template: str
    extends: Optional[str] = None  # Template inheritance
    includes: List[str] = field(default_factory=list)  # Include other templates
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Template":
        """Create a Template from a dictionary (loaded from YAML)."""
        # Parse parameters
        params = {}
        for name, param_data in data.get("parameters", {}).items():
            params[name] = ParameterDefinition(
                name=name,
                type=param_data["type"],
                default=param_data.get("default"),
                description=param_data.get("description", ""),
                min=param_data.get("min"),
                max=param_data.get("max"),
                options=param_data.get("options"),
                required=param_data.get("required", False),
                depends_on=param_data.get("depends_on"),
            )

        return cls(
            name=data["name"],
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            author=data.get("author", "Unknown"),
            tags=data.get("tags", []),
            parameters=params,
            input_template=data["input_template"],
            extends=data.get("extends"),
            includes=data.get("includes", []),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert Template to dictionary (for saving to YAML)."""
        params_dict = {}
        for name, param in self.parameters.items():
            param_dict = {
                "type": param.type,
                "description": param.description,
            }
            if param.default is not None:
                param_dict["default"] = param.default
            if param.min is not None:
                param_dict["min"] = param.min
            if param.max is not None:
                param_dict["max"] = param.max
            if param.options:
                param_dict["options"] = param.options
            if param.required:
                param_dict["required"] = param.required
            if param.depends_on:
                param_dict["depends_on"] = param.depends_on

            params_dict[name] = param_dict

        result = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "parameters": params_dict,
            "input_template": self.input_template,
        }

        if self.extends:
            result["extends"] = self.extends
        if self.includes:
            result["includes"] = self.includes
        if self.metadata:
            result["metadata"] = self.metadata

        return result


class TemplateManager:
    """Manager for CRYSTAL23 input file templates."""

    def __init__(self, template_dir: Optional[Path] = None):
        """Initialize the template manager.

        Args:
            template_dir: Directory containing template files (default: templates/)
        """
        if template_dir is None:
            # Default to templates/ directory relative to this file
            template_dir = Path(__file__).parent.parent.parent / "templates"

        self.template_dir = Path(template_dir)
        self.template_dir.mkdir(parents=True, exist_ok=True)

        # Create Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Cache loaded templates
        self._template_cache: Dict[str, Template] = {}

    def load_template(self, path: Path) -> Template:
        """Load a template from a YAML file.

        Args:
            path: Path to template YAML file

        Returns:
            Loaded Template object

        Raises:
            FileNotFoundError: If template file doesn't exist
            yaml.YAMLError: If YAML parsing fails
            ValueError: If template structure is invalid
        """
        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")

        # Check cache
        cache_key = str(path.resolve())
        if cache_key in self._template_cache:
            return self._template_cache[cache_key]

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty template file: {path}")

        # Validate required fields
        required_fields = ["name", "input_template"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Template missing required field '{field}': {path}")

        template = Template.from_dict(data)

        # Cache the template
        self._template_cache[cache_key] = template

        return template

    def render(self, template: Template, params: Dict[str, Any]) -> str:
        """Render a template with given parameters.

        Args:
            template: Template to render
            params: Dictionary of parameter values

        Returns:
            Rendered input file content

        Raises:
            ValueError: If parameter validation fails
            TemplateSyntaxError: If template has syntax errors
        """
        # Validate parameters
        errors = self.validate_params(template, params)
        if errors:
            raise ValueError(f"Parameter validation failed:\n" + "\n".join(errors))

        # Merge with defaults
        render_params = self.get_default_params(template)
        render_params.update(params)

        # Render template
        try:
            jinja_template = self.jinja_env.from_string(template.input_template)
            rendered = jinja_template.render(**render_params)
            return rendered
        except TemplateSyntaxError as e:
            raise TemplateSyntaxError(f"Template syntax error: {e}", e.lineno)

    def validate_params(self, template: Template, params: Dict[str, Any]) -> List[str]:
        """Validate parameters against template definition.

        Args:
            template: Template with parameter definitions
            params: Dictionary of parameter values

        Returns:
            List of error messages (empty if all valid)
        """
        errors = []

        # Check for unknown parameters only if template has parameters defined
        # This allows templates to accept arbitrary data for complex Jinja2 structures
        if template.parameters:
            for param_name in params:
                if param_name not in template.parameters:
                    errors.append(f"Unknown parameter: {param_name}")

        # Validate each defined parameter
        for param_name, param_def in template.parameters.items():
            value = params.get(param_name)

            # Check conditional parameters
            if param_def.depends_on:
                condition_met = all(
                    params.get(dep_name) == dep_value
                    for dep_name, dep_value in param_def.depends_on.items()
                )
                if not condition_met and value is not None:
                    errors.append(
                        f"Parameter '{param_name}' should only be set when {param_def.depends_on}"
                    )
                    continue
                if condition_met and value is None and param_def.required:
                    errors.append(
                        f"Parameter '{param_name}' is required when {param_def.depends_on}"
                    )
                    continue

            # Validate parameter value
            param_errors = param_def.validate(value)
            errors.extend(param_errors)

        return errors

    def get_default_params(self, template: Template) -> Dict[str, Any]:
        """Get dictionary of default parameter values.

        Args:
            template: Template to extract defaults from

        Returns:
            Dictionary of parameter names to default values
        """
        defaults = {}
        for param_name, param_def in template.parameters.items():
            if param_def.default is not None:
                defaults[param_name] = param_def.default
        return defaults

    def list_templates(self, tags: Optional[List[str]] = None) -> List[Template]:
        """List all available templates, optionally filtered by tags.

        Args:
            tags: Optional list of tags to filter by (OR logic)

        Returns:
            List of Template objects
        """
        templates = []

        # Search for .yml and .yaml files in template directory
        for template_path in self.template_dir.rglob("*.y*ml"):
            try:
                template = self.load_template(template_path)

                # Filter by tags if specified
                if tags is None or any(tag in template.tags for tag in tags):
                    templates.append(template)

            except Exception as e:
                print(f"Warning: Failed to load template {template_path}: {e}")

        return templates

    def save_template(self, template: Template, path: Path) -> None:
        """Save a template to a YAML file.

        Args:
            template: Template to save
            path: Destination path for YAML file

        Raises:
            OSError: If file cannot be written
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        data = template.to_dict()

        with open(path, "w") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        # Update cache
        cache_key = str(path.resolve())
        self._template_cache[cache_key] = template

    def find_template(self, name: str) -> Optional[Template]:
        """Find a template by name.

        Args:
            name: Template name to search for

        Returns:
            Template object if found, None otherwise
        """
        for template in self.list_templates():
            if template.name == name:
                return template
        return None

    def preview_template(self, template: Template) -> str:
        """Generate a preview of template with default parameters.

        Args:
            template: Template to preview

        Returns:
            Rendered template with default values
        """
        defaults = self.get_default_params(template)
        try:
            return self.render(template, defaults)
        except Exception as e:
            return f"Error rendering preview: {e}"

    def get_template_info(self, template: Template) -> Dict[str, Any]:
        """Get detailed information about a template.

        Args:
            template: Template to inspect

        Returns:
            Dictionary with template metadata and parameter info
        """
        return {
            "name": template.name,
            "version": template.version,
            "description": template.description,
            "author": template.author,
            "tags": template.tags,
            "parameter_count": len(template.parameters),
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "required": p.required,
                    "default": p.default,
                    "description": p.description,
                }
                for p in template.parameters.values()
            ],
            "extends": template.extends,
            "includes": template.includes,
        }


# Convenience function for quick template rendering
def render_template(template_path: Path, params: Dict[str, Any]) -> str:
    """Quick function to render a template.

    Args:
        template_path: Path to template YAML file
        params: Dictionary of parameter values

    Returns:
        Rendered input file content
    """
    manager = TemplateManager()
    template = manager.load_template(template_path)
    return manager.render(template, params)
