"""
Cluster Management Screen for VASP and DFT remote execution.

Provides UI for:
- Adding/editing remote cluster configurations
- Testing SSH connectivity
- Configuring DFT code paths (VASP, CRYSTAL, QE)
- Managing cluster credentials
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
    Switch,
    Header,
    Footer,
    DataTable,
    Select,
)
from textual.validation import ValidationResult, Validator

from ...core.database import Database, Cluster, ClusterType
from ...core.connection_manager import ConnectionManager
from ...core.codes import DFTCode
from .slurm_queue import SLURMQueueScreen

logger = logging.getLogger(__name__)


class PathValidator(Validator):
    """Validates that input is a valid Unix path."""

    def validate(self, value: str) -> ValidationResult:
        """Check if value is a valid path."""
        if not value:
            return self.failure("Path cannot be empty")

        # Basic Unix path validation
        if not value.startswith("/") and not value.startswith("~"):
            return self.failure("Path must be absolute (start with / or ~)")

        return self.success()


class ClusterManagerScreen(Screen):
    """
    Screen for managing remote cluster configurations.

    Allows users to:
    - Add new clusters (VASP, CRYSTAL, QE)
    - Edit existing cluster configurations
    - Test SSH connectivity
    - Verify DFT software installation
    - Delete clusters
    """

    CSS = """
    ClusterManagerScreen {
        layout: vertical;
    }

    #title {
        padding: 1;
        background: $primary;
        color: $text;
        text-align: center;
    }

    .section-header {
        margin-top: 1;
        margin-bottom: 1;
        color: $accent;
        text-style: bold;
    }

    .subsection-header {
        margin-top: 1;
        margin-bottom: 0;
        color: $secondary;
        text-style: bold;
    }

    #config_form {
        padding: 1;
    }

    #config_form Label {
        margin-top: 1;
    }

    #config_form Input {
        margin-bottom: 1;
    }

    .switch-row {
        height: 3;
        align: left middle;
    }

    .switch-row Label {
        width: 30;
        margin-right: 2;
    }

    .hidden {
        display: none;
    }

    #actions {
        margin-top: 2;
        height: 3;
        align: center middle;
    }

    #actions Button {
        margin-right: 1;
    }

    #status_message {
        margin-top: 1;
        padding: 1;
        text-align: center;
        color: $text;
    }

    #cluster_table {
        height: 10;
        margin-bottom: 2;
    }

    #cluster_actions {
        height: 3;
        margin-bottom: 1;
    }

    #cluster_actions Button {
        margin-right: 1;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("ctrl+n", "new_cluster", "New Cluster"),
        ("u", "open_queue", "Open Queue"),
    ]

    def __init__(
        self,
        db: Database,
        connection_manager: ConnectionManager,
        cluster_id: Optional[int] = None,
    ):
        """
        Initialize cluster manager screen.

        Args:
            db: Database instance
            connection_manager: ConnectionManager for testing connections
            cluster_id: If provided, edit this cluster instead of creating new
        """
        super().__init__()
        self.db = db
        self.connection_manager = connection_manager
        self.cluster_id = cluster_id
        self.is_edit_mode = cluster_id is not None

        # State
        self._testing_connection = False
        self._current_cluster: Optional[Cluster] = None

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header()

        with ScrollableContainer():
            # Title
            title = "Edit Cluster" if self.is_edit_mode else "Add New Cluster"
            yield Static(f"# {title}", id="title")

            # Cluster list (only in non-edit mode)
            if not self.is_edit_mode:
                yield Static("## Existing Clusters", classes="section-header")
                yield DataTable(id="cluster_table")
                with Horizontal(id="cluster_actions"):
                    yield Button("New Cluster", id="new_cluster_btn", variant="primary")
                    yield Button("View Queue", id="view_queue_btn", variant="default", disabled=True)

            # Configuration form
            yield Static("## Cluster Configuration", classes="section-header")

            with Vertical(id="config_form"):
                # Basic info
                yield Label("Cluster Name:")
                yield Input(placeholder="e.g., vasp-vm-cluster", id="cluster_name")

                yield Label("DFT Code:")
                yield Select(
                    options=[
                        ("VASP", "vasp"),
                        ("CRYSTAL23", "crystal"),
                        ("Quantum Espresso", "quantum_espresso"),
                    ],
                    value="vasp",
                    id="dft_code_select",
                )

                # SSH connection
                yield Static("### SSH Connection", classes="subsection-header")

                yield Label("Hostname:")
                yield Input(placeholder="e.g., 192.168.1.100 or cluster.domain.com", id="hostname")

                yield Label("Port:")
                yield Input(value="22", id="port")

                yield Label("Username:")
                yield Input(placeholder="e.g., username", id="username")

                yield Label("SSH Key File (optional):")
                yield Input(placeholder="e.g., ~/.ssh/id_rsa", id="key_file")

                with Horizontal(classes="switch-row"):
                    yield Label("Use SSH Agent:")
                    yield Switch(value=True, id="use_agent")

                with Horizontal(classes="switch-row"):
                    yield Label("Strict Host Key Checking:")
                    yield Switch(value=True, id="strict_host_keys")

                # DFT software paths
                yield Static("### DFT Software Configuration", classes="subsection-header")

                yield Label("DFT Root Directory:")
                yield Input(
                    placeholder="e.g., /home/user/vasp or ~/CRYSTAL23",
                    id="dft_root",
                    validators=[PathValidator()],
                )

                yield Label("Executable Path:")
                yield Input(
                    placeholder="e.g., /opt/vasp/bin/vasp_std or ~/CRYSTAL23/bin/.../crystalOMP",
                    id="executable_path",
                    validators=[PathValidator()],
                )

                # VASP-specific configuration
                with Vertical(id="vasp_config", classes="hidden"):
                    yield Static("#### VASP Configuration", classes="subsection-header")

                    yield Label("VASP_PP_PATH (Pseudopotentials):")
                    yield Input(
                        placeholder="e.g., /opt/vasp/potentials or ~/vasp_pp",
                        id="vasp_pp_path",
                        validators=[PathValidator()],
                    )

                    yield Label("VASP Variant:")
                    yield Select(
                        options=[
                            ("Standard (vasp_std)", "std"),
                            ("Gamma-point (vasp_gam)", "gam"),
                            ("Non-collinear (vasp_ncl)", "ncl"),
                        ],
                        value="std",
                        id="vasp_variant",
                    )

                # Scratch directory
                yield Label("Scratch Directory:")
                yield Input(
                    value="~/dft_jobs",
                    placeholder="e.g., ~/dft_jobs or /scratch/username",
                    id="scratch_dir",
                    validators=[PathValidator()],
                )

                # Actions
                with Horizontal(id="actions"):
                    yield Button("Test Connection", id="test_connection_btn", variant="default")
                    yield Button("Save Cluster", id="save_cluster_btn", variant="success")
                    yield Button("Cancel", id="cancel_btn")

                # Status messages
                yield Static("", id="status_message")

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        # Load cluster list if not in edit mode
        if not self.is_edit_mode:
            await self._load_cluster_table()
        else:
            # Load cluster data for editing
            await self._load_cluster_for_edit()

        # Set up event handlers for DFT code selection
        self._update_code_specific_fields()

    async def _load_cluster_table(self) -> None:
        """Load existing clusters into the table."""
        table = self.query_one("#cluster_table", DataTable)
        table.clear(columns=True)

        # Add columns
        table.add_columns("Name", "Type", "Host", "Status", "Actions")

        # Load clusters from database
        clusters = self.db.get_all_clusters()

        for cluster in clusters:
            table.add_row(
                cluster.name,
                cluster.type,
                f"{cluster.hostname}:{cluster.port}",
                cluster.status,
                f"[Edit] [Delete]",  # TODO: Make these clickable
            )

    async def _load_cluster_for_edit(self) -> None:
        """Load cluster data into form for editing."""
        if not self.cluster_id:
            return

        cluster = self.db.get_cluster(self.cluster_id)
        if not cluster:
            logger.error(f"Cluster {self.cluster_id} not found")
            return

        self._current_cluster = cluster

        # Populate form fields
        self.query_one("#cluster_name", Input).value = cluster.name
        self.query_one("#hostname", Input).value = cluster.hostname
        self.query_one("#port", Input).value = str(cluster.port)
        self.query_one("#username", Input).value = cluster.username

        # Load connection config
        config = cluster.connection_config
        if "key_file" in config:
            self.query_one("#key_file", Input).value = config["key_file"]
        if "use_agent" in config:
            self.query_one("#use_agent", Switch).value = config["use_agent"]
        if "strict_host_key_checking" in config:
            self.query_one("#strict_host_keys", Switch).value = config["strict_host_key_checking"]

        # Load DFT configuration
        if "dft_root" in config:
            self.query_one("#dft_root", Input).value = config["dft_root"]
        if "executable_path" in config:
            self.query_one("#executable_path", Input).value = config["executable_path"]
        if "scratch_dir" in config:
            self.query_one("#scratch_dir", Input).value = config["scratch_dir"]

        # VASP-specific
        if "vasp_pp_path" in config:
            self.query_one("#vasp_pp_path", Input).value = config["vasp_pp_path"]
        if "vasp_variant" in config:
            self.query_one("#vasp_variant", Select).value = config["vasp_variant"]

    @on(Select.Changed, "#dft_code_select")
    def _on_code_changed(self, event: Select.Changed) -> None:
        """Handle DFT code selection changes."""
        self._update_code_specific_fields()

    def _update_code_specific_fields(self) -> None:
        """Show/hide code-specific configuration fields."""
        code_select = self.query_one("#dft_code_select", Select)
        selected_code = code_select.value

        # Show/hide VASP config
        vasp_config = self.query_one("#vasp_config", Vertical)
        if selected_code == "vasp":
            vasp_config.remove_class("hidden")
        else:
            vasp_config.add_class("hidden")

    @on(Button.Pressed, "#test_connection_btn")
    async def _test_connection(self, event: Button.Pressed) -> None:
        """Test SSH connection to the cluster."""
        if self._testing_connection:
            return

        self._testing_connection = True
        status = self.query_one("#status_message", Static)
        status.update("🔄 Testing connection...")

        try:
            # Get form values
            hostname = self.query_one("#hostname", Input).value
            port_str = self.query_one("#port", Input).value
            username = self.query_one("#username", Input).value
            key_file_str = self.query_one("#key_file", Input).value
            use_agent = self.query_one("#use_agent", Switch).value

            if not hostname or not username:
                status.update("❌ Hostname and username are required")
                return

            try:
                port = int(port_str)
            except ValueError:
                status.update("❌ Invalid port number")
                return

            # Create temporary connection config
            key_file = Path(key_file_str).expanduser() if key_file_str else None

            # Register temporary cluster for testing
            temp_cluster_id = 99999
            self.connection_manager.register_cluster(
                cluster_id=temp_cluster_id,
                host=hostname,
                port=port,
                username=username,
                key_file=key_file,
                use_agent=use_agent,
            )

            # Test connection
            async with self.connection_manager.get_connection(temp_cluster_id) as conn:
                # Run a simple command to verify
                result = await conn.run("hostname && uname -a", check=True)
                remote_hostname = result.stdout.strip().split('\n')[0]

                status.update(f"✅ Connection successful! Remote host: {remote_hostname}")

                # Test DFT software availability
                executable_path = self.query_one("#executable_path", Input).value
                if executable_path:
                    test_result = await conn.run(f"test -x {executable_path} && echo OK || echo NOT_FOUND")
                    if "OK" in test_result.stdout:
                        status.update(f"✅ Connection successful! DFT executable found at {executable_path}")
                    else:
                        status.update(f"⚠️ Connection successful, but executable not found at {executable_path}")

        except Exception as e:
            logger.exception("Connection test failed")
            status.update(f"❌ Connection failed: {str(e)}")
        finally:
            self._testing_connection = False

    @on(Button.Pressed, "#save_cluster_btn")
    async def _save_cluster(self, event: Button.Pressed) -> None:
        """Save the cluster configuration."""
        status = self.query_one("#status_message", Static)

        try:
            # Collect form values
            name = self.query_one("#cluster_name", Input).value
            hostname = self.query_one("#hostname", Input).value
            port_str = self.query_one("#port", Input).value
            username = self.query_one("#username", Input).value
            dft_code = self.query_one("#dft_code_select", Select).value

            # Validate required fields
            if not all([name, hostname, username]):
                status.update("❌ Name, hostname, and username are required")
                return

            try:
                port = int(port_str)
            except ValueError:
                status.update("❌ Invalid port number")
                return

            # Build connection config
            connection_config: Dict[str, Any] = {
                "dft_code": dft_code,
                "dft_root": self.query_one("#dft_root", Input).value,
                "executable_path": self.query_one("#executable_path", Input).value,
                "scratch_dir": self.query_one("#scratch_dir", Input).value,
                "use_agent": self.query_one("#use_agent", Switch).value,
                "strict_host_key_checking": self.query_one("#strict_host_keys", Switch).value,
            }

            # Add key file if provided
            key_file_str = self.query_one("#key_file", Input).value
            if key_file_str:
                connection_config["key_file"] = key_file_str

            # Add VASP-specific config if applicable
            if dft_code == "vasp":
                connection_config["vasp_pp_path"] = self.query_one("#vasp_pp_path", Input).value
                connection_config["vasp_variant"] = self.query_one("#vasp_variant", Select).value

            # Determine cluster type
            cluster_type = ClusterType.SSH.value  # For now, all are SSH-based

            # Save to database
            if self.is_edit_mode and self.cluster_id:
                # Update existing cluster
                self.db.update_cluster(
                    cluster_id=self.cluster_id,
                    name=name,
                    hostname=hostname,
                    port=port,
                    username=username,
                    connection_config=connection_config,
                )
                status.update(f"✅ Cluster '{name}' updated successfully!")
            else:
                # Create new cluster
                cluster_id = self.db.create_cluster(
                    name=name,
                    type=cluster_type,
                    hostname=hostname,
                    port=port,
                    username=username,
                    connection_config=connection_config,
                )
                status.update(f"✅ Cluster '{name}' created successfully (ID: {cluster_id})")

            # Dismiss after short delay
            await asyncio.sleep(2)
            self.dismiss()

        except Exception as e:
            logger.exception("Failed to save cluster")
            status.update(f"❌ Failed to save: {str(e)}")

    @on(Button.Pressed, "#cancel_btn")
    def _cancel(self, event: Button.Pressed) -> None:
        """Cancel and close the screen."""
        self.dismiss()

    def action_dismiss(self) -> None:
        """Dismiss the screen."""
        self.dismiss()

    @on(Button.Pressed, "#new_cluster_btn")
    def action_new_cluster(self) -> None:
        """Open form to create a new cluster."""
        # Just scroll to the form
        self.query_one("#config_form").scroll_visible()

    @on(DataTable.RowHighlighted, "#cluster_table")
    def _on_cluster_selected(self, event: DataTable.RowHighlighted) -> None:
        """Handle cluster selection - enable/disable queue button."""
        if self.is_edit_mode:
            return

        try:
            view_queue_btn = self.query_one("#view_queue_btn", Button)
        except Exception:
            return

        if event.row_key is None:
            view_queue_btn.disabled = True
            return

        # Get cluster type from selected row
        table = self.query_one("#cluster_table", DataTable)
        try:
            row_data = table.get_row(event.row_key)
            cluster_type = row_data[1] if len(row_data) > 1 else ""

            # Enable queue button only for SLURM clusters
            view_queue_btn.disabled = cluster_type.lower() != "slurm"
        except Exception:
            view_queue_btn.disabled = True

    @on(Button.Pressed, "#view_queue_btn")
    def _on_view_queue_pressed(self, event: Button.Pressed) -> None:
        """Handle View Queue button press."""
        self.action_open_queue()

    def action_open_queue(self) -> None:
        """Open SLURM queue screen for selected cluster."""
        if self.is_edit_mode:
            return

        table = self.query_one("#cluster_table", DataTable)
        if table.cursor_row is None:
            return

        try:
            row_data = table.get_row(table.cursor_row)
            cluster_name = row_data[0] if row_data else ""
            cluster_type = row_data[1] if len(row_data) > 1 else ""

            if cluster_type.lower() != "slurm":
                return

            # Find cluster by name
            cluster = self.db.get_cluster_by_name(cluster_name)
            if not cluster or cluster.id is None:
                return

            # Push queue screen
            self.app.push_screen(
                SLURMQueueScreen(
                    db=self.db,
                    connection_manager=self.connection_manager,
                    cluster_id=cluster.id
                )
            )
        except Exception as e:
            logger.exception("Failed to open queue screen")
