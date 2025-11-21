"""
AutoForm: Dynamic form generation from parameter schemas.

This module provides automatic form generation from JSON schemas with comprehensive
validation, conditional fields, and support for multiple input types.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
import re
from pathlib import Path

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    Select,
    Static,
    Switch,
)
from textual.containers import Container, Vertical, Horizontal, VerticalScroll
from textual.message import Message
from textual.validation import Function, Integer, Number, ValidationResult, Validator


@dataclass
class ValidationError:
    """Represents a validation error for a field."""
    field_name: str
    message: str
    severity: str = "error"  # error, warning, info


@dataclass
class FieldSchema:
    """Schema definition for a form field."""
    name: str
    type: str  # string, integer, float, boolean, select, multiselect, file, range, date, color
    label: str = ""
    default: Any = None
    required: bool = False
    help: str = ""

    # Validation rules
    min: Optional[Union[int, float]] = None
    max: Optional[Union[int, float]] = None
    pattern: Optional[str] = None
    options: Optional[List[Any]] = None

    # Conditional display
    visible_when: Optional[Dict[str, Any]] = None
    depends_on: Optional[str] = None

    # Custom validation
    validator: Optional[Callable[[Any], bool]] = None
    validator_message: str = "Invalid value"

    # UI hints
    placeholder: str = ""
    disabled: bool = False
    group: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.name.replace("_", " ").title()


class CustomValidator(Validator):
    """Custom validator that uses a callable function."""

    def __init__(self, validate_fn: Callable[[str], bool], failure_description: str = "Invalid"):
        self.validate_fn = validate_fn
        self.failure_description = failure_description
        super().__init__(failure_description=failure_description)

    def validate(self, value: str) -> ValidationResult:
        """Validate the value using the custom function."""
        try:
            if self.validate_fn(value):
                return self.success()
            else:
                return self.failure(self.failure_description)
        except Exception as e:
            return self.failure(f"Validation error: {str(e)}")


class PatternValidator(Validator):
    """Validator for regex patterns."""

    def __init__(self, pattern: str, failure_description: str = "Pattern mismatch"):
        self.pattern = re.compile(pattern)
        super().__init__(failure_description=failure_description)

    def validate(self, value: str) -> ValidationResult:
        """Validate against regex pattern."""
        if self.pattern.match(value):
            return self.success()
        return self.failure(self.failure_description)


class RangeValidator(Validator):
    """Validator for numeric ranges."""

    def __init__(self, min_val: Optional[float] = None, max_val: Optional[float] = None,
                 value_type: str = "float"):
        self.min_val = min_val
        self.max_val = max_val
        self.value_type = value_type
        desc = f"Must be between {min_val} and {max_val}"
        super().__init__(failure_description=desc)

    def validate(self, value: str) -> ValidationResult:
        """Validate numeric range."""
        try:
            if self.value_type == "integer":
                num = int(value)
            else:
                num = float(value)

            if self.min_val is not None and num < self.min_val:
                return self.failure(f"Must be at least {self.min_val}")
            if self.max_val is not None and num > self.max_val:
                return self.failure(f"Must be at most {self.max_val}")

            return self.success()
        except ValueError:
            return self.failure(f"Must be a valid {self.value_type}")


class FormField(Widget):
    """Base class for form fields with label and help text."""

    DEFAULT_CSS = """
    FormField {
        layout: vertical;
        height: auto;
        margin: 0 0 1 0;
    }

    FormField .field-label {
        color: $text;
        margin: 0 0 0 0;
    }

    FormField .field-required {
        color: $error;
    }

    FormField .field-help {
        color: $text-muted;
        text-style: italic;
        margin: 0 0 0 0;
    }

    FormField .field-error {
        color: $error;
        margin: 0 0 0 0;
    }

    FormField .field-valid {
        border: tall $success;
    }

    FormField .field-invalid {
        border: tall $error;
    }
    """

    def __init__(self, schema: FieldSchema, **kwargs):
        super().__init__(**kwargs)
        self.schema = schema
        self.input_widget: Optional[Widget] = None
        self._validation_errors: List[str] = []

    def compose(self) -> ComposeResult:
        """Compose the field with label, input, and help text."""
        # Label with required indicator
        label_text = self.schema.label
        if self.schema.required:
            yield Label(f"{label_text} ", classes="field-label")
            yield Static("*", classes="field-required")
        else:
            yield Label(label_text, classes="field-label")

        # Input widget (to be set by subclasses)
        if self.input_widget:
            yield self.input_widget

        # Help text
        if self.schema.help:
            yield Static(f"ℹ {self.schema.help}", classes="field-help")

        # Error messages
        yield Static("", id=f"error-{self.schema.name}", classes="field-error")

    def get_value(self) -> Any:
        """Get the current value of the field."""
        raise NotImplementedError

    def set_value(self, value: Any) -> None:
        """Set the value of the field."""
        raise NotImplementedError

    def validate_field(self) -> List[str]:
        """Validate the field and return list of error messages."""
        errors = []
        value = self.get_value()

        # Required check
        if self.schema.required and (value is None or value == ""):
            errors.append(f"{self.schema.label} is required")

        # Custom validator
        if self.schema.validator and value:
            try:
                if not self.schema.validator(value):
                    errors.append(self.schema.validator_message)
            except Exception as e:
                errors.append(f"Validation error: {str(e)}")

        self._validation_errors = errors
        self._update_validation_display()
        return errors

    def _update_validation_display(self) -> None:
        """Update the visual validation state."""
        error_widget = self.query_one(f"#error-{self.schema.name}", Static)
        if self._validation_errors:
            error_widget.update("\n".join(self._validation_errors))
            if self.input_widget:
                self.input_widget.add_class("field-invalid")
                self.input_widget.remove_class("field-valid")
        else:
            error_widget.update("")
            if self.input_widget:
                self.input_widget.add_class("field-valid")
                self.input_widget.remove_class("field-invalid")


class StringField(FormField):
    """Text input field."""

    def compose(self) -> ComposeResult:
        """Create text input widget."""
        validators = []

        # Pattern validation
        if self.schema.pattern:
            validators.append(PatternValidator(
                self.schema.pattern,
                f"Must match pattern: {self.schema.pattern}"
            ))

        # Custom validation
        if self.schema.validator:
            validators.append(CustomValidator(
                self.schema.validator,
                self.schema.validator_message
            ))

        self.input_widget = Input(
            value=str(self.schema.default or ""),
            placeholder=self.schema.placeholder,
            validators=validators if validators else None,
            id=f"input-{self.schema.name}"
        )

        yield from super().compose()

    def get_value(self) -> str:
        """Get input value."""
        input_widget = self.query_one(f"#input-{self.schema.name}", Input)
        return input_widget.value

    def set_value(self, value: str) -> None:
        """Set input value."""
        input_widget = self.query_one(f"#input-{self.schema.name}", Input)
        input_widget.value = str(value)


class IntegerField(FormField):
    """Integer input field with range validation."""

    def compose(self) -> ComposeResult:
        """Create integer input widget."""
        validators = [Integer()]

        # Range validation
        if self.schema.min is not None or self.schema.max is not None:
            validators.append(RangeValidator(
                self.schema.min,
                self.schema.max,
                "integer"
            ))

        self.input_widget = Input(
            value=str(self.schema.default or ""),
            placeholder=self.schema.placeholder or "Enter integer",
            validators=validators,
            id=f"input-{self.schema.name}",
            type="integer"
        )

        yield from super().compose()

    def get_value(self) -> Optional[int]:
        """Get integer value."""
        input_widget = self.query_one(f"#input-{self.schema.name}", Input)
        try:
            return int(input_widget.value) if input_widget.value else None
        except ValueError:
            return None

    def set_value(self, value: int) -> None:
        """Set integer value."""
        input_widget = self.query_one(f"#input-{self.schema.name}", Input)
        input_widget.value = str(value)


class FloatField(FormField):
    """Float input field with range validation."""

    def compose(self) -> ComposeResult:
        """Create float input widget."""
        validators = [Number()]

        # Range validation
        if self.schema.min is not None or self.schema.max is not None:
            validators.append(RangeValidator(
                self.schema.min,
                self.schema.max,
                "float"
            ))

        self.input_widget = Input(
            value=str(self.schema.default or ""),
            placeholder=self.schema.placeholder or "Enter number",
            validators=validators,
            id=f"input-{self.schema.name}",
            type="number"
        )

        yield from super().compose()

    def get_value(self) -> Optional[float]:
        """Get float value."""
        input_widget = self.query_one(f"#input-{self.schema.name}", Input)
        try:
            return float(input_widget.value) if input_widget.value else None
        except ValueError:
            return None

    def set_value(self, value: float) -> None:
        """Set float value."""
        input_widget = self.query_one(f"#input-{self.schema.name}", Input)
        input_widget.value = str(value)


class BooleanField(FormField):
    """Boolean field using Switch widget."""

    def compose(self) -> ComposeResult:
        """Create switch widget."""
        self.input_widget = Switch(
            value=bool(self.schema.default),
            id=f"input-{self.schema.name}"
        )

        yield from super().compose()

    def get_value(self) -> bool:
        """Get boolean value."""
        switch = self.query_one(f"#input-{self.schema.name}", Switch)
        return switch.value

    def set_value(self, value: bool) -> None:
        """Set boolean value."""
        switch = self.query_one(f"#input-{self.schema.name}", Switch)
        switch.value = bool(value)


class SelectField(FormField):
    """Select dropdown field."""

    def compose(self) -> ComposeResult:
        """Create select widget."""
        options = self.schema.options or []
        options_tuples = [(str(opt), str(opt)) for opt in options]

        self.input_widget = Select(
            options=options_tuples,
            value=str(self.schema.default) if self.schema.default else None,
            id=f"input-{self.schema.name}",
            allow_blank=not self.schema.required
        )

        yield from super().compose()

    def get_value(self) -> Optional[str]:
        """Get selected value."""
        select = self.query_one(f"#input-{self.schema.name}", Select)
        return select.value

    def set_value(self, value: str) -> None:
        """Set selected value."""
        select = self.query_one(f"#input-{self.schema.name}", Select)
        select.value = str(value)


class MultiSelectField(FormField):
    """Multiple selection using checkboxes."""

    def compose(self) -> ComposeResult:
        """Create checkbox group."""
        # Label and help
        label_text = self.schema.label
        if self.schema.required:
            yield Label(f"{label_text} *", classes="field-label field-required")
        else:
            yield Label(label_text, classes="field-label")

        if self.schema.help:
            yield Static(f"ℹ {self.schema.help}", classes="field-help")

        # Checkboxes container
        with Vertical(id=f"multiselect-{self.schema.name}"):
            defaults = self.schema.default or []
            for option in (self.schema.options or []):
                yield Checkbox(
                    str(option),
                    value=(option in defaults),
                    id=f"check-{self.schema.name}-{option}"
                )

        # Error display
        yield Static("", id=f"error-{self.schema.name}", classes="field-error")

    def get_value(self) -> List[str]:
        """Get list of selected values."""
        selected = []
        container = self.query_one(f"#multiselect-{self.schema.name}")
        for checkbox in container.query(Checkbox):
            if checkbox.value:
                selected.append(checkbox.label.plain)
        return selected

    def set_value(self, values: List[str]) -> None:
        """Set selected values."""
        container = self.query_one(f"#multiselect-{self.schema.name}")
        for checkbox in container.query(Checkbox):
            checkbox.value = checkbox.label.plain in values


class FileField(FormField):
    """File selection field with path validation."""

    def compose(self) -> ComposeResult:
        """Create file input with browse button."""
        self.input_widget = Input(
            value=str(self.schema.default or ""),
            placeholder="Enter file path or click Browse",
            id=f"input-{self.schema.name}"
        )

        # Label
        label_text = self.schema.label
        if self.schema.required:
            yield Label(f"{label_text} *", classes="field-label field-required")
        else:
            yield Label(label_text, classes="field-label")

        # Input with browse button
        with Horizontal():
            yield self.input_widget
            yield Button("Browse", id=f"browse-{self.schema.name}", variant="primary")

        # Help and error
        if self.schema.help:
            yield Static(f"ℹ {self.schema.help}", classes="field-help")
        yield Static("", id=f"error-{self.schema.name}", classes="field-error")

    def get_value(self) -> str:
        """Get file path."""
        input_widget = self.query_one(f"#input-{self.schema.name}", Input)
        return input_widget.value

    def set_value(self, value: str) -> None:
        """Set file path."""
        input_widget = self.query_one(f"#input-{self.schema.name}", Input)
        input_widget.value = str(value)

    def validate_field(self) -> List[str]:
        """Validate file existence."""
        errors = super().validate_field()

        value = self.get_value()
        if value and not Path(value).exists():
            errors.append(f"File does not exist: {value}")

        self._validation_errors = errors
        self._update_validation_display()
        return errors


class AutoForm(Widget):
    """
    Automatically generated form from parameter schema.

    Features:
    - Multiple field types with validation
    - Conditional field visibility
    - Field grouping with collapsible sections
    - Real-time validation
    - Form state persistence
    """

    DEFAULT_CSS = """
    AutoForm {
        layout: vertical;
        height: auto;
    }

    AutoForm .form-group {
        layout: vertical;
        border: tall $primary;
        padding: 1;
        margin: 1 0;
        height: auto;
    }

    AutoForm .form-group-title {
        color: $primary;
        text-style: bold;
    }

    AutoForm .form-actions {
        layout: horizontal;
        height: auto;
        align: right middle;
        margin: 1 0;
    }

    AutoForm .form-actions Button {
        margin: 0 1;
    }
    """

    class Submitted(Message):
        """Form submitted message."""
        def __init__(self, values: Dict[str, Any]) -> None:
            self.values = values
            super().__init__()

    class Changed(Message):
        """Form value changed message."""
        def __init__(self, field_name: str, value: Any) -> None:
            self.field_name = field_name
            self.value = value
            super().__init__()

    def __init__(self, schema: Dict[str, Any], **kwargs):
        super().__init__(**kwargs)
        self.schema = schema
        self.fields: Dict[str, FormField] = {}
        self.field_schemas: Dict[str, FieldSchema] = {}
        self._submit_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._parse_schema()

    def _parse_schema(self) -> None:
        """Parse JSON schema into FieldSchema objects."""
        for field_dict in self.schema.get("fields", []):
            field_schema = FieldSchema(**field_dict)
            self.field_schemas[field_schema.name] = field_schema

    @classmethod
    def from_schema(cls, schema: Dict[str, Any]) -> "AutoForm":
        """Create form from schema dictionary."""
        return cls(schema)

    def compose(self) -> ComposeResult:
        """Generate form UI from schema."""
        # Group fields by group name
        groups: Dict[str, List[FieldSchema]] = {}
        for field_schema in self.field_schemas.values():
            group_name = field_schema.group or "default"
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(field_schema)

        # Create form fields
        with VerticalScroll():
            for group_name, field_schemas in groups.items():
                if group_name != "default":
                    with Container(classes="form-group"):
                        yield Static(group_name, classes="form-group-title")
                        yield from self._create_fields(field_schemas)
                else:
                    yield from self._create_fields(field_schemas)

        # Form actions
        with Container(classes="form-actions"):
            yield Button("Reset", id="btn-reset", variant="default")
            yield Button("Submit", id="btn-submit", variant="primary")

    def _create_fields(self, field_schemas: List[FieldSchema]) -> ComposeResult:
        """Create field widgets from schemas."""
        for field_schema in field_schemas:
            field = self._create_field(field_schema)
            if field:
                self.fields[field_schema.name] = field
                yield field

    def _create_field(self, schema: FieldSchema) -> Optional[FormField]:
        """Create appropriate field widget based on type."""
        field_type = schema.type.lower()

        if field_type == "string":
            return StringField(schema)
        elif field_type == "integer":
            return IntegerField(schema)
        elif field_type == "float":
            return FloatField(schema)
        elif field_type == "boolean":
            return BooleanField(schema)
        elif field_type == "select":
            return SelectField(schema)
        elif field_type == "multiselect":
            return MultiSelectField(schema)
        elif field_type == "file":
            return FileField(schema)
        else:
            # Fallback to string field
            return StringField(schema)

    def get_values(self) -> Dict[str, Any]:
        """Collect all form values."""
        values = {}
        for field_name, field in self.fields.items():
            values[field_name] = field.get_value()
        return values

    def set_values(self, data: Dict[str, Any]) -> None:
        """Set form values from dictionary."""
        for field_name, value in data.items():
            if field_name in self.fields:
                self.fields[field_name].set_value(value)

    def validate(self) -> List[ValidationError]:
        """Validate all fields and return errors."""
        errors = []

        for field_name, field in self.fields.items():
            field_errors = field.validate_field()
            for error_msg in field_errors:
                errors.append(ValidationError(
                    field_name=field_name,
                    message=error_msg
                ))

        # Cross-field validation
        errors.extend(self._validate_dependencies())

        return errors

    def _validate_dependencies(self) -> List[ValidationError]:
        """Validate field dependencies."""
        errors = []
        values = self.get_values()

        for field_name, field_schema in self.field_schemas.items():
            if field_schema.depends_on:
                dep_field = field_schema.depends_on
                if dep_field in values and not values[dep_field]:
                    if values.get(field_name):
                        errors.append(ValidationError(
                            field_name=field_name,
                            message=f"Requires {dep_field} to be set"
                        ))

        return errors

    def reset(self) -> None:
        """Reset all fields to default values."""
        for field_name, field_schema in self.field_schemas.items():
            if field_name in self.fields:
                default = field_schema.default
                if default is not None:
                    self.fields[field_name].set_value(default)

    def on_submit(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register submit callback."""
        self._submit_callback = callback

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-submit":
            errors = self.validate()
            if not errors:
                values = self.get_values()
                if self._submit_callback:
                    self._submit_callback(values)
                self.post_message(self.Submitted(values))
            else:
                # Show validation errors
                error_msg = "\n".join([f"{e.field_name}: {e.message}" for e in errors])
                self.notify(f"Validation errors:\n{error_msg}", severity="error")

        elif event.button.id == "btn-reset":
            self.reset()
            self.notify("Form reset to defaults", severity="information")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes for real-time validation."""
        # Find field name from input ID
        input_id = event.input.id
        if input_id and input_id.startswith("input-"):
            field_name = input_id[6:]  # Remove "input-" prefix
            if field_name in self.fields:
                # Validate field
                self.fields[field_name].validate_field()

                # Post change message
                value = self.fields[field_name].get_value()
                self.post_message(self.Changed(field_name, value))

                # Update conditional fields
                self._update_conditional_visibility()

    def _update_conditional_visibility(self) -> None:
        """Update visibility of conditional fields."""
        values = self.get_values()

        for field_name, field_schema in self.field_schemas.items():
            if field_schema.visible_when:
                # Check if visibility conditions are met
                should_show = True
                for dep_field, dep_value in field_schema.visible_when.items():
                    if values.get(dep_field) != dep_value:
                        should_show = False
                        break

                # Update field visibility
                if field_name in self.fields:
                    field = self.fields[field_name]
                    field.display = should_show

    def to_json(self) -> Dict[str, Any]:
        """Export form state to JSON."""
        return {
            "schema": self.schema,
            "values": self.get_values()
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "AutoForm":
        """Create form from JSON state."""
        form = cls.from_schema(data["schema"])
        form.set_values(data["values"])
        return form
