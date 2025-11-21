# Input File Preview Widget

## Overview

The `InputPreview` widget provides syntax-highlighted preview of CRYSTAL input files (.d12) within the TUI. It enhances readability by highlighting keywords, numbers, and comments with distinct colors.

## Features

- **Syntax Highlighting**: Keywords, numbers, and comments are color-coded
- **Line Numbers**: Each line is numbered for easy reference
- **File Metadata**: Displays file name, size, last modified time, and line count
- **Scrollable**: Handles large files with smooth scrolling
- **Automatic Updates**: Updates when a job is selected in the job list

## Highlighted Elements

### Keywords (Bold Magenta)
CRYSTAL input keywords are highlighted in bold magenta, including:

**Structure Keywords**:
- CRYSTAL, SLAB, POLYMER, MOLECULE, EXTERNAL, HELIX
- SUPERCEL, NANOTUBE, CLUSTER, ENDG, ENDBS, END

**Basis Set Keywords**:
- BASIS, BASISSET, BS, ATOMSYMM, GHOSTS

**Hamiltonian Keywords**:
- UHF, ROHF, RHF, DFT, B3LYP, PBE, PBE0, HSE06, M06
- HAMILTONIAN, EXCHSIZE, CORRELAT, HYBRID, MIXING

**SCF Keywords**:
- TOLINTEG, TOLDEE, TOLPSEUD, SHRINK, FMIXING, BROYDEN
- ANDERSON, DIIS, MAXCYCLE, LEVSHIFT, SPINLOCK, SMEAR
- BIPOSIZE, EXCHPERM, NOBIPOLA, ATOMSPIN

**Optimization Keywords**:
- OPTGEOM, FULLOPTG, CELLONLY, ITATOCEL, MAXCYCLE
- TOLDEG, TOLDEX, FRAGMENT, FREQCALC, RESTART

**Properties Keywords**:
- NEWK, BAND, DOSS, COORPRT, MULPOPAN, PPAN
- ELASTCON, ELASFITR, ELASFITN

### Numbers (Cyan)
All numeric values (integers and floats) are highlighted in cyan:
- Integers: 27, 221, 4
- Floats: 4.071, 0.5, 0.000227
- Scientific notation: 341701, 48850.0

### Comments (Dim Green)
Lines starting with `#` are treated as comments and shown in dim green.

### Regular Text (White)
Atom labels and other non-keyword text appears in white.

## Usage

### In the Application

The InputPreview widget is automatically integrated into the TUI:

1. **Automatic Display**: When you select a job in the job list, the input file preview updates automatically
2. **Tab Navigation**: Switch to the "Input" tab to view the preview
3. **Scrolling**: Use arrow keys or Page Up/Down to scroll through long files

### Programmatic Usage

```python
from pathlib import Path
from src.tui.widgets import InputPreview

# Create widget
preview = InputPreview()

# Display input file
input_file = Path("calculations/my_job/input.d12")
preview.display_input("my_job", input_file)

# Update content directly
with open(input_file) as f:
    content = f.read()
preview.update_content(content, input_file)

# Clear preview
preview.clear()
```

## File Metadata

When displaying a file, the widget shows:

```
    File: input.d12
    Size: 1,234 bytes
Modified: 2025-11-20 21:45:00
   Lines: 24
```

## Implementation Details

### Syntax Highlighting Algorithm

1. **Line-by-line Processing**: Each line is processed independently
2. **Token Classification**: Each whitespace-separated token is classified:
   - Check if token matches a keyword (case-insensitive)
   - Check if token is a valid number
   - Otherwise, treat as regular text
3. **Spacing Preservation**: Original spacing and formatting is maintained
4. **Line Numbers**: Added with a separator (│) for clarity

### Performance Considerations

- **Lazy Rendering**: Content is only highlighted when rendered
- **Efficient Number Detection**: Uses try/except with float() for performance
- **No Regular Expressions**: Simple string operations for speed
- **Scrollable Container**: Large files don't impact UI responsiveness

### Keyword Database

The widget maintains a comprehensive set of CRYSTAL23 keywords. To add new keywords:

```python
# In input_preview.py, add to the KEYWORDS set:
KEYWORDS = {
    # ... existing keywords ...
    "NEWKEYWORD",  # Add your keyword here
}
```

## Example Output

```
   1 │ KCoF3 base all-electron ferro 4 4 4
   2 │ CRYSTAL
   3 │ 0 0 0
   4 │ 221
   5 │ 4.071
   6 │ 3
   7 │ 27    .0  .0  .0
   8 │ 9     .5  .0  .0
   9 │ 19    .5  .5   .5
  10 │ ENDG
  11 │ UHF
  12 │ TOLINTEG
  13 │ 7 7 7 7 14
  14 │ SHRINK
  15 │ 8 8
```

In the actual TUI:
- "CRYSTAL", "ENDG", "UHF", "TOLINTEG", "SHRINK" appear in **bold magenta**
- All numbers (4, 0, 221, 4.071, etc.) appear in **cyan**
- Line numbers and separators appear in **dim cyan**
- Regular text appears in **white**

## Integration with Job List

The InputPreview widget is automatically updated when:

1. A job row is selected in the job list
2. The `on_data_table_row_highlighted` event handler fires
3. The handler retrieves the job's input file from the database
4. The preview is updated via `display_input()` method

## Error Handling

- **Missing File**: If the input file doesn't exist, displays "No input file selected"
- **Empty Content**: Gracefully handles empty input files
- **Invalid Characters**: Displays all characters, even if non-standard

## Future Enhancements

Potential improvements for future versions:

1. **Inline Editing**: Allow editing the input file directly in the preview
2. **Validation**: Real-time syntax validation with error highlighting
3. **Folding**: Collapse/expand basis set sections
4. **Search**: Find text within the input file
5. **Export**: Export with syntax highlighting to HTML/PDF
6. **Diff View**: Compare two input files side-by-side

## Related Files

- `src/tui/widgets/input_preview.py` - Widget implementation
- `src/tui/app.py` - Integration into main application
- `src/core/database.py` - Job database storing input_file content
- `src/tui/screens/new_job.py` - Creates jobs with input files

## Testing

To test the InputPreview widget:

```bash
# Run TUI and create a test job
cd tui/
crystal-tui

# In the TUI:
# 1. Press 'n' to create a new job
# 2. Fill in job details and paste/type an input file
# 3. Select the job in the list
# 4. Switch to "Input" tab
# 5. Verify syntax highlighting appears correctly
```

## Accessibility

- **High Contrast**: Color choices ensure readability
- **Line Numbers**: Help users reference specific lines
- **Scrollbar**: Visual indicator for long files
- **Keyboard Navigation**: Full keyboard support for scrolling

---

**Version**: 1.0.0
**Last Updated**: 2025-11-20
**Author**: CRYSTAL-TUI Team
