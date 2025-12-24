# New Job Modal - Complete Documentation

## Overview

The New Job Modal is a professional, user-friendly interface for creating new CRYSTAL23 calculation jobs within the TUI. It provides comprehensive input validation, auxiliary file management, parallelism configuration, and automatic directory setup.

## Features

### 1. Job Configuration
- **Job Name Input**: Validated to allow only alphanumeric characters, hyphens, and underscores
- **Unique Name Check**: Prevents duplicate job names in the database
- **Real-time Work Directory Preview**: Shows the auto-generated directory path

### 2. Input File Management
- **Text Area Editor**: Syntax-highlighted editor with line numbers
- **Paste Support**: Paste complete .d12 files directly
- **Input Validation**: Checks for required CRYSTAL keywords (CRYSTAL/SLAB/POLYMER/MOLECULE, END)
- **Browse Files**: Button to load files from disk (future enhancement)

### 3. Auxiliary Files Support
Three optional auxiliary file types with checkbox toggles:

- **`.gui` file**: External geometry file (used with EXTERNAL keyword)
- **`.f9` file**: Wave function guess file (GUESSP/GUESSF restart)
- **`.hessopt` file**: Hessian matrix for optimization restart

**Features**:
- Checkboxes enable/disable file path inputs
- File existence validation before job creation
- Automatic file copying to job work directory
- Files renamed to match job name (e.g., `mgo_bulk.gui`, `mgo_bulk.f9`)

### 4. Parallelism Settings
Two execution modes with radio buttons:

- **Serial Mode** (default):
  - Single process execution
  - OpenMP threading only
  - Best for small systems or testing

- **Parallel Mode**:
  - MPI + OpenMP hybrid parallelism
  - Configurable number of MPI ranks
  - Automatic validation of rank count (must be positive integer)

### 5. Working Directory
- **Auto-generated Path**: `calculations/XXXX_jobname`
- **Sequential Numbering**: XXXX is zero-padded job ID (0001, 0002, etc.)
- **Live Preview**: Updates as job name is typed
- **Automatic Creation**: Directory created on job submission

### 6. Validation & Error Handling

**Comprehensive Validation**:
- Job name: non-empty, valid characters, unique
- Input content: non-empty, valid CRYSTAL format
- Auxiliary files: file existence checks
- MPI ranks: positive integer when parallel mode selected
- Work directory: prevents duplicate directories

**User-Friendly Error Messages**:
- Red error banner at bottom of modal
- Focus moved to problematic field
- Clear instructions on how to fix issues

### 7. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `ESC` | Cancel and close modal |
| `Ctrl+S` | Submit/create job |
| `Tab` | Navigate between fields |
| `Enter` | Submit when on button |

## Usage

### Opening the Modal

From the main TUI screen:
- Press `n` key, or
- Click "New Job" button (if using mouse)

### Creating a Job - Basic Workflow

1. **Enter Job Name**:
   ```
   Job Name: mgo_bulk_optimization
   ```

2. **Paste Input Content**:
   ```crystal
   MgO bulk structure optimization
   CRYSTAL
   0 0 0
   225
   4.211
   1
   12 0.0 0.0 0.0
   2
   12 0.0
   8 0.0
   END
   ...
   ```

3. **Configure Parallelism** (optional):
   - Select "Parallel" radio button
   - Enter MPI ranks (e.g., 8)

4. **Submit**:
   - Press `Ctrl+S` or click "Create Job"

### Creating a Job - Advanced (with Auxiliary Files)

1. **Enter Job Name**: `mgo_restart_calc`

2. **Add Input Content**: (paste .d12 content)

3. **Enable Auxiliary Files**:
   - Check "Use .f9 file"
   - Enter path: `/path/to/previous_run/mgo.f9`
   - Check "Use .hessopt file"
   - Enter path: `/path/to/previous_run/mgo.hessopt`

4. **Configure Parallelism**:
   - Select "Parallel"
   - Enter ranks: 16

5. **Submit**: `Ctrl+S`

**Result**:
- Creates `calculations/0005_mgo_restart_calc/`
- Copies `input.d12`, `mgo_restart_calc.f9`, `mgo_restart_calc.hessopt`
- Creates `job_metadata.json` with parallel settings
- Adds job to database with PENDING status

## File Structure Created

For job `mgo_bulk` (ID 3):

```
calculations/
└── 0003_mgo_bulk/
    ├── input.d12              # Main input file
    ├── mgo_bulk.gui           # (if .gui file was provided)
    ├── mgo_bulk.f9            # (if .f9 file was provided)
    ├── mgo_bulk.hessopt       # (if .hessopt file was provided)
    └── job_metadata.json      # Job configuration metadata
```

### job_metadata.json Format

```json
{
  "mpi_ranks": 8,
  "parallel_mode": "parallel",
  "auxiliary_files": ["f9", "hessopt"]
}
```

## Input Validation Rules

### Job Name
- **Required**: Yes
- **Allowed Characters**: Letters, numbers, hyphens (`-`), underscores (`_`)
- **Disallowed**: Spaces, special characters (`!@#$%^&*()`)
- **Uniqueness**: Must not exist in database
- **Examples**:
  - ✅ `mgo_bulk`
  - ✅ `optimization-test-01`
  - ✅ `Fe2O3_surface_100`
  - ❌ `my job` (space)
  - ❌ `test@home` (special char)

### Input File Content
- **Required**: Yes
- **Minimum Length**: 5 lines
- **Required Keywords**:
  - One of: `CRYSTAL`, `SLAB`, `POLYMER`, `MOLECULE`, `EXTERNAL`
  - At least two `END` keywords (geometry section + basis set section)

### Auxiliary Files
- **Required**: No (all optional)
- **Validation**: File must exist if path is provided
- **Path Format**: Absolute or relative paths accepted

### MPI Ranks
- **Required**: Only if parallel mode selected
- **Type**: Integer
- **Range**: >= 1
- **Default**: 1 (serial mode)

## Integration with Database

The modal integrates with the TUI database (`Database` class) to:
1. Check for duplicate job names
2. Generate sequential job IDs
3. Store job metadata (name, work_dir, input_content, status)
4. Set initial status to `PENDING`

**Database Record Created**:
```python
Job(
    id=5,
    name="mgo_bulk_optimization",
    work_dir="/path/to/calculations/0005_mgo_bulk_optimization",
    status="PENDING",
    created_at="2025-01-20 15:30:45",
    input_file="<full .d12 content>",
    ...
)
```

## Event Flow

### Successful Job Creation
1. User fills form and clicks "Create Job"
2. Validation passes ✅
3. Work directory created
4. Input file written
5. Auxiliary files copied (if any)
6. Metadata JSON written
7. Database record created
8. `JobCreated` message posted to app
9. Modal dismissed
10. Main app refreshes job list
11. Success notification shown

### Failed Validation
1. User clicks "Create Job"
2. Validation fails ❌
3. Error message displayed in red banner
4. Focus moved to problematic field
5. Modal remains open
6. User can correct and retry

### Cancellation
1. User presses `ESC` or clicks "Cancel"
2. Modal dismissed with `None` result
3. No files or database changes
4. Optional notification: "Job creation cancelled"

## Textual Implementation Details

### Screen Type
- **Class**: `ModalScreen` (from `textual.screen`)
- **Modal Behavior**: Blocks interaction with main app
- **Dismiss Result**: Returns job ID (int) or `None`

### Widget Hierarchy
```
NewJobScreen (ModalScreen)
└── Container (#modal_container)
    ├── Static (#modal_title)
    ├── ScrollableContainer (#form_scroll)
    │   ├── Vertical (.form_section) - Job Configuration
    │   │   ├── Label (.section_title)
    │   │   ├── Label (.field_label)
    │   │   └── Input (#job_name_input)
    │   ├── Vertical (.form_section) - Input File
    │   │   ├── Label (.section_title)
    │   │   ├── Static (#info_message)
    │   │   ├── TextArea (#input_textarea)
    │   │   └── Button (#browse_button)
    │   ├── Vertical (.form_section) - Auxiliary Files
    │   │   └── Vertical (#aux_files_container)
    │   │       ├── Horizontal (.aux_file_row)
    │   │       │   ├── Checkbox (#gui_checkbox)
    │   │       │   └── Input (#gui_file_input)
    │   │       ├── Horizontal (.aux_file_row)
    │   │       │   ├── Checkbox (#f9_checkbox)
    │   │       │   └── Input (#f9_file_input)
    │   │       └── Horizontal (.aux_file_row)
    │   │           ├── Checkbox (#hessopt_checkbox)
    │   │           └── Input (#hessopt_file_input)
    │   ├── Vertical (.form_section) - Parallelism
    │   │   ├── RadioSet (#parallel_mode)
    │   │   │   ├── RadioButton (#serial_radio)
    │   │   │   └── RadioButton (#parallel_radio)
    │   │   └── Input (#mpi_ranks_input)
    │   └── Vertical (.form_section) - Work Directory
    │       └── Input (#work_dir_input, disabled)
    ├── Static (#error_message, hidden by default)
    └── Horizontal (#button_container)
        └── Horizontal (#button_row)
            ├── Button (#create_button)
            └── Button (#cancel_button)
```

### Event Handlers
- `on_mount()`: Initialize focus and preview
- `on_input_changed()`: Update work directory preview
- `on_checkbox_changed()`: Enable/disable auxiliary file inputs
- `on_radio_set_changed()`: Enable/disable MPI ranks input
- `on_button_pressed()`: Handle Create/Cancel/Browse buttons
- `action_submit()`: Validate and create job
- `action_cancel()`: Close modal without creating job

## Testing

### Manual Testing Script
Use `test_new_job_modal.py` for interactive testing:

```bash
cd tui/
source venv/bin/activate
python test_new_job_modal.py
```

**Test Cases**:
1. ✅ Valid job creation (minimal)
2. ✅ Valid job creation (with all aux files)
3. ✅ Duplicate job name error
4. ✅ Invalid job name characters
5. ✅ Empty input content error
6. ✅ Invalid CRYSTAL input format
7. ✅ Non-existent auxiliary file error
8. ✅ Invalid MPI ranks (negative, non-integer)
9. ✅ Cancel button / ESC key
10. ✅ Ctrl+S keyboard shortcut

### Unit Testing (Future)
```python
# tests/test_new_job_screen.py
from textual.widgets import Input, TextArea, Checkbox, RadioSet

async def test_job_name_validation():
    """Test job name validation rules."""
    # Test invalid characters
    # Test duplicate names
    # Test empty name

async def test_auxiliary_file_toggle():
    """Test checkbox enables/disables inputs."""
    # Check .gui checkbox
    # Verify gui_file_input is enabled
    # Uncheck, verify disabled

async def test_parallel_mode_toggle():
    """Test parallel mode enables MPI ranks input."""
    # Select parallel radio
    # Verify mpi_ranks_input enabled
    # Select serial, verify disabled

async def test_input_validation():
    """Test CRYSTAL input validation."""
    # Valid input passes
    # Missing END keyword fails
    # Too short fails
    # Missing geometry type fails
```

## Future Enhancements

### Planned Features
1. **File Browser Dialog**: Native file picker for auxiliary files
2. **Input File Templates**: Pre-populated templates for common calculations
3. **Syntax Highlighting**: CRYSTAL-specific syntax coloring
4. **Drag-and-Drop**: Drop .d12 files into text area
5. **Input File History**: Quick access to previous inputs
6. **Batch Job Creation**: Create multiple similar jobs at once
7. **Advanced Settings**: Scratch directory, OMP threads, timeout
8. **Input Validation**: Real-time validation with inline error indicators
9. **Preview Mode**: Show generated file structure before creation
10. **Import from CLI**: Import jobs from CLI work directories

### Possible Improvements
- Auto-detect optimal MPI ranks based on system cores
- Suggest auxiliary files if found in same directory as input
- Save form state if cancelled (restore on next open)
- Job templates database for common calculation types
- Input file editor with autocomplete for keywords
- Visual file tree preview of what will be created

## Troubleshooting

### Modal Doesn't Open
- Check that database is initialized
- Verify calculations directory exists
- Check console for exceptions

### Input Not Saving
- Ensure TextArea has focus when typing
- Check for validation errors (red banner)
- Verify disk space available

### Auxiliary Files Not Copied
- Check file paths are absolute or relative to TUI cwd
- Verify source files exist and are readable
- Check destination directory permissions

### Parallel Settings Not Saved
- Verify RadioSet index (0=serial, 1=parallel)
- Check metadata JSON file in work directory
- Ensure integer value entered for MPI ranks

## Code References

**Files**:
- Modal screen: `src/tui/screens/new_job.py` (580 lines)
- Database integration: `src/core/database.py`
- Main app integration: `src/tui/app.py` (lines 184-195, 258-262)

**Key Classes**:
- `NewJobScreen(ModalScreen)`: Main modal screen
- `JobCreated(Message)`: Message posted on success
- `Database`: Job persistence layer

**Key Methods**:
- `compose()`: Layout definition
- `action_submit()`: Validation and job creation
- `_validate_crystal_input()`: Input format validation
- `_update_work_dir_preview()`: Real-time directory preview

---

**Last Updated**: 2025-01-20
**Version**: 1.0
**Status**: Production Ready ✅
