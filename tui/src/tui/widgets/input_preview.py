"""
Input file preview widget with syntax highlighting for CRYSTAL input files.
"""

import re
from pathlib import Path
from typing import Optional
from datetime import datetime

from textual.widgets import Static
from textual.containers import VerticalScroll
from rich.console import RenderableType
from rich.syntax import Syntax
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class InputPreview(Static):
    """
    A widget for previewing CRYSTAL input files (.d12) with syntax highlighting.

    Features:
    - Syntax highlighting for CRYSTAL keywords, numbers, and comments
    - Line numbers
    - Scrollable content
    - File metadata display
    """

    # CRYSTAL keywords for syntax highlighting
    KEYWORDS = {
        # Main structure keywords
        "CRYSTAL", "SLAB", "POLYMER", "MOLECULE", "EXTERNAL", "HELIX",
        "SUPERCEL", "NANOTUBE", "CLUSTER", "ENDG", "ENDBS", "END",

        # Basis set keywords
        "BASIS", "BASISSET", "BS", "ATOMSYMM", "GHOSTS",

        # Hamiltonian keywords
        "HAMILTONIAN", "UHF", "ROHF", "RHF", "DFT", "B3LYP", "PBE", "PBE0",
        "HSE06", "M06", "EXCHSIZE", "CORRELAT", "HYBRID", "MIXING",

        # SCF keywords
        "TOLINTEG", "TOLDEE", "TOLPSEUD", "SHRINK", "FMIXING", "BROYDEN",
        "ANDERSON", "DIIS", "MAXCYCLE", "LEVSHIFT", "SPINLOCK", "SMEAR",
        "BIPOSIZE", "EXCHPERM", "NOBIPOLA", "ATOMSPIN",

        # Geometry optimization
        "OPTGEOM", "FULLOPTG", "CELLONLY", "ITATOCEL", "MAXCYCLE",
        "TOLDEG", "TOLDEX", "FRAGMENT", "FREQCALC", "RESTART",

        # Elastic constants
        "ELASTCON", "ELASFITR", "ELASFITN",

        # Properties
        "NEWK", "BAND", "DOSS", "COORPRT", "MULPOPAN", "PPAN",

        # Other
        "GUESSP", "GUESSF", "ECP", "MODISYMM", "INTGPACK",
        "COMPRESS", "SUPERCELL"
    }

    def __init__(
        self,
        content: str = "",
        file_path: Optional[Path] = None,
        name: Optional[str] = None,
        id: Optional[str] = None,
        classes: Optional[str] = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self._content = content
        self._file_path = file_path

    def render(self) -> RenderableType:
        """Render the input file with syntax highlighting."""
        if not self._content:
            return Panel(
                "[dim]No input file selected[/dim]",
                title="Input Preview",
                border_style="dim"
            )

        # Create metadata table if we have file info
        if self._file_path and self._file_path.exists():
            metadata = self._create_metadata_table()
        else:
            metadata = None

        # Apply syntax highlighting
        highlighted = self._highlight_crystal_input(self._content)

        # Create panel with content
        if metadata:
            # Combine metadata and content
            from rich.console import Group
            content_panel = Panel(
                Group(metadata, "", highlighted),
                title="Input File Preview",
                border_style="cyan"
            )
        else:
            content_panel = Panel(
                highlighted,
                title="Input File Preview",
                border_style="cyan"
            )

        return content_panel

    def update_content(self, content: str, file_path: Optional[Path] = None) -> None:
        """Update the preview content."""
        self._content = content
        self._file_path = file_path
        self.refresh()

    def display_input(self, job_name: str, input_file: Path) -> None:
        """Display input file for a specific job."""
        if input_file.exists():
            with open(input_file, 'r') as f:
                content = f.read()
            self._content = content
            self._file_path = input_file
        else:
            self._content = ""
            self._file_path = None
        self.refresh()

    def display_no_input(self) -> None:
        """Display message when no input file is available."""
        self._content = ""
        self._file_path = None
        self.refresh()

    def clear(self) -> None:
        """Clear the preview."""
        self._content = ""
        self._file_path = None
        self.refresh()

    def _create_metadata_table(self) -> Table:
        """Create a metadata table for the file."""
        if not self._file_path or not self._file_path.exists():
            return Table()

        stat = self._file_path.stat()

        # Create compact metadata table
        table = Table.grid(padding=(0, 1))
        table.add_column(style="cyan", justify="right")
        table.add_column(style="white")

        # File info
        table.add_row("File:", self._file_path.name)
        table.add_row("Size:", f"{stat.st_size:,} bytes")

        # Last modified
        mtime = datetime.fromtimestamp(stat.st_mtime)
        table.add_row("Modified:", mtime.strftime("%Y-%m-%d %H:%M:%S"))

        # Line count
        line_count = len(self._content.splitlines())
        table.add_row("Lines:", str(line_count))

        return table

    def _highlight_crystal_input(self, content: str) -> Text:
        """
        Apply syntax highlighting to CRYSTAL input content.

        Highlights:
        - Keywords (CRYSTAL, EXTERNAL, UHF, etc.)
        - Numbers (integers and floats)
        - Comments (lines starting with #)
        """
        text = Text()

        for line_num, line in enumerate(content.splitlines(), start=1):
            # Add line number
            text.append(f"{line_num:4d} │ ", style="dim cyan")

            # Check for comment (# at start of line)
            if line.strip().startswith("#"):
                text.append(line, style="dim green")
                text.append("\n")
                continue

            # Process line token by token
            tokens = line.split()
            col_pos = 0

            for token_idx, token in enumerate(tokens):
                # Find position in original line to preserve spacing
                token_pos = line.find(token, col_pos)
                if token_pos > col_pos:
                    # Add whitespace before token
                    text.append(line[col_pos:token_pos])

                # Determine token style
                if token.upper() in self.KEYWORDS:
                    # Keyword
                    text.append(token, style="bold magenta")
                elif self._is_number(token):
                    # Number
                    text.append(token, style="cyan")
                else:
                    # Regular text
                    text.append(token, style="white")

                col_pos = token_pos + len(token)

            # Add any remaining whitespace/content at end of line
            if col_pos < len(line):
                text.append(line[col_pos:])

            text.append("\n")

        return text

    @staticmethod
    def _is_number(s: str) -> bool:
        """Check if a string represents a number (int or float)."""
        try:
            float(s)
            return True
        except ValueError:
            return False
