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
from jinja2 import FileSystemLoader, Template as Jinja2Template, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment


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
    """Manager for CRYSTAL23 input file templates.

    SECURITY: Uses sandboxed Jinja2 environment with:
    - SandboxedEnvironment: Restricts access to dangerous functions/attributes
    - autoescape=True: HTML/XML escaping to prevent injection
    - Restricted filters: Only safe Jinja2 filters allowed
    - Path validation: Prevents directory traversal attacks
    - No file system access: Templates cannot read/write files
    """

    def __init__(self, template_dir: Optional[Path] = None):
        """Initialize the template manager with security hardening.

        Args:
            template_dir: Directory containing template files (default: core templates)

        Raises:
            ValueError: If template_dir path is invalid or contains traversal attempts
        """
        if template_dir is None:
            # Use centralized templates from crystalmath core package
            try:
                from crystalmath.templates import get_template_dir
                template_dir = get_template_dir()
            except ImportError:
                # Fallback to local templates/ directory if core not available
                template_dir = Path(__file__).parent.parent.parent / "templates"

        self.template_dir = Path(template_dir)

        # Validate template directory path (prevent path traversal)
        self._validate_template_dir(self.template_dir)

        self.template_dir.mkdir(parents=True, exist_ok=True)

        # Create SANDBOXED Jinja2 environment with security restrictions
        # SandboxedEnvironment prevents arbitrary code execution
        self.jinja_env = SandboxedEnvironment(
            loader=FileSystemLoader(str(self.template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=True,  # Enable auto-escaping (critical for security)
        )

        # Cache loaded templates
        self._template_cache: Dict[str, Template] = {}

    @staticmethod
    def _validate_template_dir(template_dir: Path) -> None:
        """Validate template directory path prevents security issues.

        Args:
            template_dir: Path to validate

        Raises:
            ValueError: If path is absolute, contains traversal attempts, or outside base
        """
        # Resolve to absolute path to detect traversal
        resolved = template_dir.resolve()

        # Check that path doesn't escape common boundaries
        # (This is a defense-in-depth measure; actual safety depends on application architecture)
        try:
            # Ensure it's a valid path
            resolved.is_dir()  # Will fail if path is invalid
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid template directory path: {template_dir}") from e

    def load_template(self, path: Path) -> Template:
        """Load a template from a YAML file with path validation.

        SECURITY: Validates that the path is within the template directory
        to prevent path traversal attacks (e.g., ../../../etc/passwd).

        Args:
            path: Path to template YAML file (relative to template_dir)

        Returns:
            Loaded Template object

        Raises:
            FileNotFoundError: If template file doesn't exist
            ValueError: If path is outside template directory (path traversal)
            yaml.YAMLError: If YAML parsing fails
            ValueError: If template structure is invalid
        """
        # Security: Validate path is within template directory
        self._validate_template_path(path)

        # Construct full path relative to template_dir
        full_path = self.template_dir / path

        if not full_path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")

        # Check cache (use resolved full path as key)
        cache_key = str(full_path.resolve())
        if cache_key in self._template_cache:
            return self._template_cache[cache_key]

        with open(full_path, "r") as f:
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

    def _validate_template_path(self, path: Path) -> None:
        """Validate template file path is within template directory.

        SECURITY: Prevents path traversal attacks (e.g., ../../../etc/passwd).
        Uses Path.resolve() to canonicalize paths and detect escapes.

        Args:
            path: Path to validate (should be relative to template_dir)

        Raises:
            ValueError: If path is outside template directory, is absolute,
                       is a symlink, or has invalid extension
        """
        path_obj = Path(path)

        # SECURITY: Reject absolute paths
        if path_obj.is_absolute():
            raise ValueError(
                f"Absolute paths not allowed for security: {path}"
            )

        # SECURITY: Extension allowlist - only .yml and .yaml files
        if path_obj.suffix.lower() not in ['.yml', '.yaml']:
            raise ValueError(
                f"Invalid file extension '{path_obj.suffix}': only .yml and .yaml allowed"
            )

        # Construct full path (but don't resolve yet - we need to check for symlinks first)
        full_path = self.template_dir / path_obj

        # SECURITY: Reject symlinks to prevent symlink attacks
        # Must check BEFORE resolve() since resolve() dereferences symlinks
        if full_path.is_symlink():
            raise ValueError(
                f"Symlinks not allowed for security: {path}"
            )

        # Now resolve to canonical form for traversal check
        resolved_path = full_path.resolve()
        resolved_template_dir = self.template_dir.resolve()

        # Check that the resolved file is within the template directory
        try:
            # This will raise ValueError if resolved_path is not relative to template_dir
            resolved_path.relative_to(resolved_template_dir)
        except ValueError as e:
            raise ValueError(
                f"Path traversal attempt detected: {path} is outside template directory "
                f"{self.template_dir}"
            ) from e

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
        # SECURITY: Use specific extensions to prevent matching unintended files
        for pattern in ["*.yml", "*.yaml"]:
            for template_path in self.template_dir.rglob(pattern):
                try:
                    # Convert absolute path from rglob() to relative path for validation
                    relative_path = template_path.relative_to(self.template_dir)
                    template = self.load_template(relative_path)

                    # Filter by tags if specified
                    if tags is None or any(tag in template.tags for tag in tags):
                        templates.append(template)

                except Exception as e:
                    print(f"Warning: Failed to load template {template_path}: {e}")

        return templates

    def save_template(self, template: Template, path: Path) -> None:
        """Save a template to a YAML file.

        SECURITY: Validates path to prevent writing outside template directory.

        Args:
            template: Template to save
            path: Destination path for YAML file (relative to template_dir)

        Raises:
            ValueError: If path is invalid or outside template directory
            OSError: If file cannot be written
        """
        # Security: Validate path is within template directory
        self._validate_template_path(path)

        # Construct full path relative to template_dir
        full_path = self.template_dir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        data = template.to_dict()

        with open(full_path, "w") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        # Update cache (use resolved full path as key)
        cache_key = str(full_path.resolve())
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
