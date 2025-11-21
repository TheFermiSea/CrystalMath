"""
Template Browser screen for browsing, selecting, and using calculation templates.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.widgets import (
    Input, Button, Static, Label, Select, Tree, TextArea,
    Checkbox, RadioSet, RadioButton
)
from textual.widget import Widget
from textual.message import Message
from textual.binding import Binding
from textual.widgets.tree import TreeNode

from ...core.templates import TemplateManager, Template, ParameterDefinition
from ...core.database import Database


class TemplateSelected(Message):
    """Message posted when a template is selected for use."""

    def __init__(self, template: Template, parameters: Dict[str, Any]) -> None:
        self.template = template
        self.parameters = parameters
        super().__init__()


class ParameterForm(Widget):
    """Dynamic form for editing template parameters."""

    def __init__(
        self,
        template: Template,
        id: Optional[str] = None,
        classes: Optional[str] = None
    ):
        super().__init__(id=id, classes=classes)
        self.template = template
        self.parameter_widgets: Dict[str, Widget] = {}

    def compose(self) -> ComposeResult:
        """Compose parameter form based on template definition."""
        if not self.template.parameters:
            yield Label("No parameters required for this template.", classes="info_message")
            return

        with ScrollableContainer(classes="parameter_form_scroll"):
            for param_name, param_def in self.template.parameters.items():
                with Vertical(classes="parameter_field"):
                    # Parameter label with description
                    label_text = f"{param_name}"
                    if param_def.required:
                        label_text += " *"
                    yield Label(label_text, classes="parameter_label")

                    if param_def.description:
                        yield Label(param_def.description, classes="parameter_description")

                    # Generate appropriate input widget based on type
                    widget_id = f"param_{param_name}"

                    if param_def.type == "select":
                        # Dropdown select
                        options = [(opt, opt) for opt in (param_def.options or [])]
                        default_index = 0
                        if param_def.default and param_def.options:
                            try:
                                default_index = param_def.options.index(param_def.default)
                            except ValueError:
                                pass

                        yield Select(
                            options=options,
                            value=param_def.default or (param_def.options[0] if param_def.options else None),
                            id=widget_id,
                            classes="parameter_input"
                        )

                    elif param_def.type == "boolean":
                        # Checkbox for boolean
                        yield Checkbox(
                            f"Enable {param_name}",
                            value=bool(param_def.default),
                            id=widget_id,
                            classes="parameter_input"
                        )

                    elif param_def.type == "integer":
                        # Integer input with validation
                        placeholder = f"Integer"
                        if param_def.min is not None and param_def.max is not None:
                            placeholder += f" ({param_def.min}-{param_def.max})"

                        yield Input(
                            value=str(param_def.default) if param_def.default is not None else "",
                            placeholder=placeholder,
                            type="integer",
                            id=widget_id,
                            classes="parameter_input"
                        )

                    elif param_def.type == "float":
                        # Float input with validation
                        placeholder = f"Number"
                        if param_def.min is not None and param_def.max is not None:
                            placeholder += f" ({param_def.min}-{param_def.max})"

                        yield Input(
                            value=str(param_def.default) if param_def.default is not None else "",
                            placeholder=placeholder,
                            type="number",
                            id=widget_id,
                            classes="parameter_input"
                        )

                    elif param_def.type == "file":
                        # File path input
                        yield Input(
                            value=str(param_def.default) if param_def.default else "",
                            placeholder="Path to file",
                            id=widget_id,
                            classes="parameter_input"
                        )

                    else:  # string or default
                        # Text input
                        yield Input(
                            value=str(param_def.default) if param_def.default else "",
                            placeholder=f"Enter {param_name}",
                            id=widget_id,
                            classes="parameter_input"
                        )

                    # Validation error placeholder
                    yield Label("", id=f"error_{param_name}", classes="parameter_error")

    def get_parameter_values(self) -> Dict[str, Any]:
        """Extract parameter values from form widgets."""
        values = {}

        for param_name, param_def in self.template.parameters.items():
            widget_id = f"param_{param_name}"

            try:
                if param_def.type == "select":
                    widget = self.query_one(f"#{widget_id}", Select)
                    values[param_name] = widget.value

                elif param_def.type == "boolean":
                    widget = self.query_one(f"#{widget_id}", Checkbox)
                    values[param_name] = widget.value

                elif param_def.type == "integer":
                    widget = self.query_one(f"#{widget_id}", Input)
                    if widget.value:
                        values[param_name] = int(widget.value)
                    elif param_def.default is not None:
                        values[param_name] = param_def.default

                elif param_def.type == "float":
                    widget = self.query_one(f"#{widget_id}", Input)
                    if widget.value:
                        values[param_name] = float(widget.value)
                    elif param_def.default is not None:
                        values[param_name] = param_def.default

                else:  # string, file, or default
                    widget = self.query_one(f"#{widget_id}", Input)
                    values[param_name] = widget.value if widget.value else param_def.default

            except Exception:
                # If widget not found or conversion fails, use default
                if param_def.default is not None:
                    values[param_name] = param_def.default

        return values

    def validate_parameters(self) -> List[str]:
        """Validate all parameters and show errors."""
        errors = []
        values = self.get_parameter_values()

        for param_name, param_def in self.template.parameters.items():
            value = values.get(param_name)
            param_errors = param_def.validate(value)

            error_label = self.query_one(f"#error_{param_name}", Label)

            if param_errors:
                errors.extend(param_errors)
                error_label.update(param_errors[0])  # Show first error
                error_label.add_class("visible")
            else:
                error_label.update("")
                error_label.remove_class("visible")

        return errors


class TemplateBrowserScreen(ModalScreen):
    """Modal screen for browsing and selecting calculation templates."""

    CSS = """
    TemplateBrowserScreen {
        align: center middle;
    }

    #browser_container {
        width: 95%;
        height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }

    #browser_title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: $primary;
        padding: 0 0 1 0;
    }

    #search_bar {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }

    #search_input {
        width: 70%;
    }

    #tag_filter {
        width: 30%;
        margin: 0 0 0 1;
    }

    #main_content {
        layout: horizontal;
        width: 100%;
        height: 1fr;
    }

    #template_list_panel {
        width: 30%;
        border: solid $accent;
        padding: 1;
    }

    #template_list_title {
        width: 100%;
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    #template_tree {
        width: 100%;
        height: 1fr;
        scrollbar-gutter: stable;
    }

    #details_panel {
        width: 70%;
        border: solid $accent;
        padding: 1;
        margin: 0 0 0 1;
    }

    #details_scroll {
        width: 100%;
        height: 1fr;
    }

    #template_metadata {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }

    .metadata_row {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }

    .metadata_label {
        color: $accent;
        text-style: bold;
    }

    #parameters_section {
        width: 100%;
        height: auto;
        padding: 1 0;
        border-top: solid $accent-darken-1;
    }

    .section_title {
        width: 100%;
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    .parameter_form_scroll {
        width: 100%;
        height: auto;
        max-height: 20;
    }

    .parameter_field {
        width: 100%;
        padding: 0 0 1 0;
    }

    .parameter_label {
        color: $text;
        text-style: bold;
    }

    .parameter_description {
        color: $text-muted;
        text-style: italic;
        padding: 0 0 1 0;
    }

    .parameter_input {
        width: 100%;
        margin: 0 0 1 0;
    }

    .parameter_error {
        color: $error;
        text-style: bold;
        display: none;
    }

    .parameter_error.visible {
        display: block;
    }

    #preview_section {
        width: 100%;
        height: auto;
        padding: 1 0;
        border-top: solid $accent-darken-1;
    }

    #preview_textarea {
        width: 100%;
        height: 15;
        border: solid $accent;
    }

    #button_bar {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }

    #button_row {
        width: auto;
        height: auto;
    }

    Button {
        margin: 0 1;
        min-width: 15;
    }

    #error_message {
        width: 100%;
        color: $error;
        text-style: bold;
        padding: 1 0;
        display: none;
    }

    #error_message.visible {
        display: block;
    }

    .info_message {
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("t", "focus_tree", "Focus Templates", show=False),
        Binding("/", "focus_search", "Search", show=True),
        Binding("enter", "select_template", "Select", show=True),
        Binding("space", "preview", "Preview", show=True),
    ]

    def __init__(
        self,
        database: Database,
        calculations_dir: Path,
        template_dir: Optional[Path] = None,
        name: Optional[str] = None,
        id: Optional[str] = None
    ):
        super().__init__(name=name, id=id)
        self.database = database
        self.calculations_dir = calculations_dir

        # Initialize template manager
        if template_dir is None:
            # Default to monorepo templates directory
            template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"

        self.template_manager = TemplateManager(template_dir)
        self.current_template: Optional[Template] = None
        self.parameter_form: Optional[ParameterForm] = None

    def compose(self) -> ComposeResult:
        """Compose the template browser layout."""
        with Container(id="browser_container"):
            yield Static("Template Browser", id="browser_title")

            # Search and filter bar
            with Horizontal(id="search_bar"):
                yield Input(placeholder="Search templates...", id="search_input")
                yield Input(placeholder="Filter by tags (comma-separated)", id="tag_filter")

            # Main content area
            with Horizontal(id="main_content"):
                # Left panel: Template tree
                with Vertical(id="template_list_panel"):
                    yield Label("Templates", id="template_list_title")
                    yield Tree("Templates", id="template_tree")

                # Right panel: Template details and preview
                with Vertical(id="details_panel"):
                    with ScrollableContainer(id="details_scroll"):
                        # Template metadata
                        with Vertical(id="template_metadata"):
                            yield Label("Select a template to view details", classes="info_message")

            # Error message
            yield Static("", id="error_message")

            # Action buttons
            with Horizontal(id="button_bar"):
                with Horizontal(id="button_row"):
                    yield Button("Use Template", variant="success", id="use_button", disabled=True)
                    yield Button("Preview", variant="default", id="preview_button", disabled=True)
                    yield Button("Cancel", variant="default", id="cancel_button")

    def on_mount(self) -> None:
        """Initialize the template tree and load templates."""
        self._load_template_tree()
        search_input = self.query_one("#search_input", Input)
        search_input.focus()

    def _load_template_tree(self) -> None:
        """Load templates and populate the tree view."""
        tree = self.query_one("#template_tree", Tree)
        tree.clear()

        # Load all templates
        templates = self.template_manager.list_templates()

        # Group templates by category
        categories: Dict[str, List[Template]] = {
            "basic": [],
            "advanced": [],
            "workflows": [],
            "other": []
        }

        for template in templates:
            # Determine category from tags
            if "basic" in template.tags:
                categories["basic"].append(template)
            elif "workflow" in template.tags:
                categories["workflows"].append(template)
            elif "advanced" in template.tags:
                categories["advanced"].append(template)
            else:
                categories["other"].append(template)

        # Build tree
        root = tree.root
        root.expand()

        # Add categories
        for category, category_templates in categories.items():
            if not category_templates:
                continue

            icon = {
                "basic": "📄",
                "advanced": "🔬",
                "workflows": "🔄",
                "other": "📦"
            }.get(category, "📦")

            category_label = f"{icon} {category.title()} ({len(category_templates)})"
            category_node = root.add(category_label, expand=False)

            # Add templates to category
            for template in sorted(category_templates, key=lambda t: t.name):
                template_label = f"{template.name} (v{template.version})"
                template_node = category_node.add_leaf(template_label)
                template_node.data = template  # Store template object in node

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Handle template selection in tree."""
        node = event.node

        if node.data and isinstance(node.data, Template):
            self.current_template = node.data
            self._display_template_details(self.current_template)

            # Enable action buttons
            use_button = self.query_one("#use_button", Button)
            preview_button = self.query_one("#preview_button", Button)
            use_button.disabled = False
            preview_button.disabled = False

    def _display_template_details(self, template: Template) -> None:
        """Display template details in the right panel."""
        details_scroll = self.query_one("#details_scroll", ScrollableContainer)

        # Clear existing content
        details_scroll.remove_children()

        # Create new content
        with details_scroll:
            # Metadata section
            with Vertical(id="template_metadata"):
                yield Static(f"[bold]{template.name}[/bold]", classes="metadata_row")
                yield Static(f"[dim]Author:[/dim] {template.author}", classes="metadata_row")
                yield Static(f"[dim]Version:[/dim] {template.version}", classes="metadata_row")
                yield Static(f"[dim]Description:[/dim] {template.description}", classes="metadata_row")
                yield Static(f"[dim]Tags:[/dim] {', '.join(template.tags)}", classes="metadata_row")

            # Parameters section
            if template.parameters:
                with Vertical(id="parameters_section"):
                    yield Label("Parameters", classes="section_title")

                    # Create parameter form
                    self.parameter_form = ParameterForm(template, id="parameter_form")
                    yield self.parameter_form

            # Preview section
            with Vertical(id="preview_section"):
                yield Label("Preview (with default parameters)", classes="section_title")
                preview_text = self.template_manager.preview_template(template)
                yield TextArea(
                    preview_text,
                    id="preview_textarea",
                    language="text",
                    read_only=True,
                    show_line_numbers=True
                )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search and filter changes."""
        if event.input.id == "search_input":
            self._filter_templates()
        elif event.input.id == "tag_filter":
            self._filter_templates()

    def _filter_templates(self) -> None:
        """Filter templates based on search and tag filters."""
        search_input = self.query_one("#search_input", Input)
        tag_filter = self.query_one("#tag_filter", Input)

        search_text = search_input.value.lower()
        tag_text = tag_filter.value.lower()

        # Parse tags
        filter_tags = [t.strip() for t in tag_text.split(",") if t.strip()]

        # Reload tree with filters
        templates = self.template_manager.list_templates()

        # Apply filters
        filtered = []
        for template in templates:
            # Search filter
            if search_text:
                if search_text not in template.name.lower() and \
                   search_text not in template.description.lower():
                    continue

            # Tag filter
            if filter_tags:
                if not any(tag in template.tags for tag in filter_tags):
                    continue

            filtered.append(template)

        # Rebuild tree with filtered templates
        tree = self.query_one("#template_tree", Tree)
        tree.clear()
        root = tree.root
        root.expand()

        # Group and add
        for template in sorted(filtered, key=lambda t: t.name):
            template_label = f"{template.name} (v{template.version})"
            template_node = root.add_leaf(template_label)
            template_node.data = template

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "use_button":
            self.action_select_template()
        elif event.button.id == "preview_button":
            self.action_preview()
        elif event.button.id == "cancel_button":
            self.action_cancel()

    def action_cancel(self) -> None:
        """Cancel and close the modal."""
        self.dismiss(None)

    def action_focus_tree(self) -> None:
        """Focus the template tree."""
        tree = self.query_one("#template_tree", Tree)
        tree.focus()

    def action_focus_search(self) -> None:
        """Focus the search input."""
        search_input = self.query_one("#search_input", Input)
        search_input.focus()

    def action_preview(self) -> None:
        """Preview the template with current parameter values."""
        if not self.current_template or not self.parameter_form:
            return

        # Get parameter values
        params = self.parameter_form.get_parameter_values()

        # Render template
        try:
            rendered = self.template_manager.render(self.current_template, params)

            # Update preview
            preview_textarea = self.query_one("#preview_textarea", TextArea)
            preview_textarea.load_text(rendered)

            # Clear error
            error_message = self.query_one("#error_message", Static)
            error_message.update("")
            error_message.remove_class("visible")

        except Exception as e:
            self._show_error(f"Preview error: {str(e)}")

    def action_select_template(self) -> None:
        """Use the selected template to create a job."""
        if not self.current_template:
            self._show_error("No template selected")
            return

        # Validate parameters
        if self.parameter_form:
            errors = self.parameter_form.validate_parameters()
            if errors:
                self._show_error(f"Parameter validation failed: {errors[0]}")
                return

            params = self.parameter_form.get_parameter_values()
        else:
            params = {}

        # Try to render the template
        try:
            rendered = self.template_manager.render(self.current_template, params)
        except Exception as e:
            self._show_error(f"Failed to render template: {str(e)}")
            return

        # Post message and close
        self.dismiss((self.current_template, params, rendered))
        self.post_message(TemplateSelected(self.current_template, params))

    def _show_error(self, message: str) -> None:
        """Display an error message."""
        error_message = self.query_one("#error_message", Static)
        error_message.update(f"Error: {message}")
        error_message.add_class("visible")
