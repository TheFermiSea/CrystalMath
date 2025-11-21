"""
Entry point for the CRYSTAL-TUI application.
"""

import sys
from pathlib import Path
from .tui.app import CrystalTUI
from .core.environment import load_crystal_environment, EnvironmentError


def main() -> None:
    """Main entry point."""
    # Use current directory as project directory
    project_dir = Path.cwd()

    print(f"CRYSTAL-TUI")
    print(f"Project directory: {project_dir}")
    print()

    # Load and validate CRYSTAL23 environment
    print("Loading CRYSTAL23 environment...")
    try:
        config = load_crystal_environment()
        print(f"✓ CRYSTAL23 version: {config.version}")
        print(f"✓ Executable: {config.executable_path}")
        print(f"✓ Scratch directory: {config.scratch_dir}")
        print()
    except EnvironmentError as e:
        print(f"ERROR: Failed to load CRYSTAL23 environment")
        print(f"{e}")
        print()
        print("Please ensure:")
        print("  1. CRYSTAL23 is properly installed")
        print("  2. cry23.bashrc is configured correctly")
        print("  3. crystalOMP executable is present and executable")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error loading environment: {e}")
        sys.exit(1)

    print("Initializing TUI...")
    app = CrystalTUI(project_dir)
    app.run()


if __name__ == "__main__":
    main()
