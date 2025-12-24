# InputPreview Widget - Visual Example

## What Users See

When a job is selected in the TUI, the Input tab displays the input file with syntax highlighting:

### Example: KCoF3 Calculation

```
╭────────────────────── Input File Preview ──────────────────────╮
│                                                                 │
│     File: input.d12                                            │
│     Size: 2,847 bytes                                          │
│ Modified: 2025-11-20 21:45:00                                  │
│    Lines: 105                                                  │
│                                                                 │
│    1 │ KCoF3 base all-electron ferro 4 4 4                     │
│    2 │ CRYSTAL                            [bold magenta]       │
│    3 │ 0 0 0                              [cyan numbers]       │
│    4 │ 221                                [cyan]               │
│    5 │ 4.071                              [cyan]               │
│    6 │ 3                                  [cyan]               │
│    7 │ 27    .0  .0  .0                   [cyan]               │
│    8 │ 9     .5  .0  .0                   [cyan]               │
│    9 │ 19    .5  .5   .5                  [cyan]               │
│   10 │ ENDG                               [bold magenta]       │
│   11 │ 27 7                               [cyan]               │
│   12 │  0 0 8 2.0  1.0                    [cyan]               │
│   13 │         341701        0.000227     [cyan]               │
│   14 │         48850.0        0.001929    [cyan]               │
│   15 │         10400.9        0.0111      [cyan]               │
│   ...                                                           │
│   88 │  99 0                              [cyan]               │
│   89 │ ENDBS                              [bold magenta]       │
│   90 │ UHF                                [bold magenta]       │
│   91 │ TOLINTEG                           [bold magenta]       │
│   92 │ 7 7 7 7 14                         [cyan]               │
│   93 │ SHRINK                             [bold magenta]       │
│   94 │ 8 8                                [cyan]               │
│   95 │ FMIXING                            [bold magenta]       │
│   96 │ 30                                 [cyan]               │
│   97 │ TOLDEE                             [bold magenta]       │
│   98 │ 7                                  [cyan]               │
│   99 │ SPINLOCK                           [bold magenta]       │
│  100 │ 3 30                               [cyan]               │
│  101 │ LEVSHIFT                           [bold magenta]       │
│  102 │ 3 1                                [cyan]               │
│  103 │ MULPOPAN                           [bold magenta]       │
│  104 │ END                                [bold magenta]       │
│                                                                 │
╰─────────────────────────────────────────────────────────────────╯
```

## Color Scheme

- **Line Numbers**: Dim cyan with separator (│)
- **Keywords**: Bold magenta (CRYSTAL, UHF, TOLINTEG, SHRINK, END, etc.)
- **Numbers**: Cyan (integers and floats)
- **Regular Text**: White (atom labels, descriptions)
- **Comments**: Dim green (lines starting with #)

## Interactive Features

### Navigation
- **Scroll Up/Down**: Arrow keys or mouse wheel
- **Page Up/Down**: Page through long files
- **Home/End**: Jump to start/end of file

### Automatic Updates
- Selecting a different job in the job list automatically updates the preview
- No manual refresh needed

### File Metadata
- File name, size, last modified time, and line count displayed at top
- Helps identify which input file you're viewing

## Use Cases

### 1. Reviewing Input Before Execution
Before running a job, review the input file to ensure:
- Correct basis set specified
- Proper SCF settings (TOLINTEG, SHRINK, etc.)
- Appropriate Hamiltonian (UHF, DFT, etc.)
- Geometry is correct

### 2. Debugging Failed Jobs
When a job fails, check the input file for:
- Syntax errors
- Invalid keywords
- Incorrect numerical parameters
- Missing END statements

### 3. Comparing Job Setups
Switch between jobs to compare:
- Different basis sets
- SCF convergence parameters
- Geometry variations
- Method differences (UHF vs. RHF, etc.)

### 4. Learning CRYSTAL Syntax
Study example input files to learn:
- Keyword structure
- Parameter formatting
- Common patterns
- Best practices

## Accessibility

- **High Contrast**: Colors chosen for readability on various terminals
- **Line Numbers**: Help reference specific lines in discussions
- **Scrollbar**: Visual indicator of position in file
- **Keyboard-Friendly**: All navigation via keyboard

## Integration with Workflow

1. **Create Job** → Input stored in database
2. **Select Job** → Preview updates automatically
3. **Review Input** → Switch to Input tab
4. **Run Job** → Execute with confidence
5. **Check Results** → Compare input and output

## Example Workflows

### Workflow 1: Create and Review
```
1. Press 'n' to create new job
2. Enter job name: "test_kcof3"
3. Paste input file content
4. Job appears in list
5. Select job → Input tab shows highlighted preview
6. Review parameters
7. Press 'r' to run
```

### Workflow 2: Compare Two Jobs
```
1. Select first job → Review input in Input tab
2. Select second job → Preview updates
3. Switch back and forth to compare
4. Note differences in parameters
```

### Workflow 3: Debug Failed Job
```
1. Notice job FAILED in job list
2. Select job → Input tab
3. Scan for common errors:
   - Missing END statement?
   - Invalid TOLINTEG values?
   - Typo in keyword?
4. Fix issues externally
5. Create new job with corrected input
```

## Tips

1. **Use Line Numbers**: When discussing input files, reference line numbers
2. **Scroll Through Large Files**: PageUp/PageDown for faster navigation
3. **Check Metadata**: File size can indicate if input loaded correctly
4. **Look for Patterns**: Color highlighting makes keywords easy to spot
5. **Compare Side-by-Side**: Use multiple terminal windows if needed

## Known Limitations

- **Read-Only**: Cannot edit input files directly (future enhancement)
- **No Validation**: Syntax highlighting only, no error checking (future)
- **No Search**: Cannot search within input file (future enhancement)

## Future Enhancements

Planned improvements:
1. Inline editing capability
2. Real-time syntax validation
3. Error highlighting and suggestions
4. Search/find functionality
5. Section folding (collapse basis sets)
6. Export with highlighting

---

**Note**: The actual colors appear in the TUI terminal and are shown with Rich styling. This document uses annotations like [bold magenta] to indicate the colors that appear in the real interface.
