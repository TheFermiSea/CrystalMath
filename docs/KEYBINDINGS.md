# TUI Keybinding Specification

Standard keybindings for both Rust TUI (Cockpit) and Python TUI (Workshop).

## Design Principles

1. **Vim-style navigation**: j/k for up/down, consistent with developer muscle memory
2. **Mnemonic keys**: First letter of action where possible (L=Logs, R=Refresh, C=Cancel)
3. **Modifier for destructive**: Ctrl+ prefix for actions that modify state
4. **Two-key confirmation**: Destructive actions require confirmation (press twice)

## Universal Keybindings

These keys work the same in both TUIs:

| Key | Action | Notes |
|-----|--------|-------|
| `q` / `Ctrl+Q` | Quit | Exit application |
| `j` / `Down` | Move down | Navigate lists |
| `k` / `Up` | Move up | Navigate lists |
| `Enter` | Select/Details | View selected item details |
| `Ctrl+R` | Refresh | Refresh job list |
| `r` | Run/Refresh | Context-dependent |
| `c` | Cancel job | Two-key confirmation in Rust TUI |
| `l` / `L` | View logs | Switch to log view for selected job |

## Rust TUI (Cockpit) Specific

Fast monitoring interface - read-heavy operations:

| Key | Context | Action |
|-----|---------|--------|
| `Tab` | Global | Next tab |
| `Shift+Tab` | Global | Previous tab |
| `1-4` | Global | Jump to tab (Jobs/Editor/Results/Log) |
| `s` | Jobs | Open SLURM queue modal (remembers last-used cluster) |
| `c` | Jobs | Open cluster manager modal |
| `v` | Jobs | Open VASP multi-file input modal |
| `Ctrl+Enter` | Editor | Submit job (two-key confirmation) |
| `Ctrl+I` | Editor | Materials Project import |
| `F` | Log | Toggle follow mode (auto-refresh) |
| `g` | Log | Jump to top |
| `G` | Log | Jump to bottom |
| `PageUp/Down` | Log/Results | Page scroll |
| `Home/End` | Jobs | First/Last job |

## Python TUI (Workshop) Specific

Complex forms and configuration - write-heavy operations:

| Key | Action |
|-----|--------|
| `n` | New job dialog |
| `t` | Template browser |
| `b` | Batch submission |
| `u` | SLURM queue view |
| `s` | Stop/Cancel job |
| `f` | Filter by status |

## Conflict Resolution

When keys conflict between modes:

- **`c`**: Cancel in Rust TUI, Cluster manager in Python TUI
  - Resolution: Python TUI uses `s` for Stop, Rust TUI uses `c` for Cancel
- **`r`**: Refresh in Rust TUI (Log tab), Run in Python TUI
  - Resolution: Both valid in context (Rust=refresh log, Python=run job)

## Footer Display Format

Rust TUI footer format:
```
[Tab] Switch | [j/k] Navigate | [Enter] Details | [L] Logs | [C] Cancel | [Ctrl+R] Refresh
```

Python TUI uses Textual's built-in Footer widget with BINDINGS.

## Implementation Status

| Feature | Rust TUI | Python TUI |
|---------|----------|------------|
| j/k navigation | ✓ | ✓ (DataTable default) |
| Enter for details | ✓ | ✓ |
| Ctrl+R refresh | ✓ | - (uses r) |
| Cancel confirmation | ✓ (two-key) | - (immediate) |
| Help footer | ✓ | ✓ (Textual Footer) |
| SLURM queue modal | ✓ (multi-cluster) | ✓ |
| Cluster manager | ✓ | ✓ |
| VASP input modal | ✓ | ✓ |
