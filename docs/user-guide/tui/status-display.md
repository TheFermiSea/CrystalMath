# Enhanced Job Status Display

This document describes the enhanced job status display features implemented for Issue crystalmath-hai.

## Overview

The TUI now features a rich, color-coded job list with real-time updates, progress indicators, and comprehensive job statistics.

## Features Implemented

### 1. Color-Coded Status Indicators

Jobs are displayed with color-coded status indicators:

- ⏸ **PENDING** (dim gray) - Job not yet started
- ⏳ **QUEUED** (yellow) - Job queued for execution
- ▶ **RUNNING** (cyan bold) - Job currently executing
- ✓ **COMPLETED** (green bold) - Job finished successfully
- ✗ **FAILED** (red bold) - Job failed

### 2. Progress Indicators

Visual progress bars show job progress:

```
⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀  - Pending (empty bar)
⣿⣿⣿⣿⣿⣀⣀⣀⣀⣀  - Running (50% bar, updates in real-time)
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿  - Completed (full bar)
⣿⣿⣀⣀⣀⣀⣀⣀⣀⣀  - Failed (20% bar)
```

### 3. Runtime Display

Jobs show runtime in human-readable format:

- **Running jobs**: Live-updated elapsed time (1s, 45s, 3m 24s, 1h 5m, 2d 3h)
- **Completed/failed jobs**: Total runtime from start to completion
- **Pending jobs**: "N/A"

Updates automatically every second for running jobs.

### 4. Resource Usage

Display shows resource allocation when available:

- **MPI + Threads**: "4R×8T" (4 ranks × 8 threads)
- **Threads only**: "8T" (8 threads)
- **Process ID**: "PID:12345" (fallback)

### 5. Enhanced Columns

The job list includes 8 columns:

| Column | Description |
|--------|-------------|
| ID | Database job ID |
| Name | Job name |
| Status | Color-coded status with icon |
| Progress | Visual progress bar |
| Runtime | Elapsed/total time |
| Resources | MPI ranks, threads, or PID |
| Energy (Ha) | Final energy (8 decimal places) |
| Created | Creation timestamp (YYYY-MM-DD HH:MM) |

### 6. Filtering

Press `f` to cycle through status filters:

1. **ALL** - Show all jobs (default)
2. **RUNNING** - Show only running jobs
3. **COMPLETED** - Show only completed jobs
4. **FAILED** - Show only failed jobs
5. **PENDING** - Show only pending jobs
6. Back to **ALL**

Current filter is displayed in a notification.

### 7. Sorting

Press `t` to cycle through sort columns:

1. **Created** - Sort by creation time (newest first, default)
2. **Name** - Sort by job name alphabetically
3. **Status** - Sort by status
4. **Runtime** - Sort by runtime (longest first)
5. **Energy** - Sort by final energy (highest first)
6. Back to **Created**

Current sort is displayed in a notification.

### 8. Job Statistics Footer

A new footer widget displays overall statistics:

```
Total: 25  ▶ Running: 3  ✓ Completed: 18  ✗ Failed: 4  Success Rate: 81.8%
```

Statistics include:

- **Total jobs**: Total number of jobs
- **Pending/Queued**: Count with dim gray styling (hidden if zero)
- **Running**: Count with cyan bold styling (hidden if zero)
- **Completed**: Count with green bold styling (hidden if zero)
- **Failed**: Count with red bold styling (hidden if zero)
- **Success Rate**: Percentage of successful completions (color-coded)

Success rate color coding:

- **Green**: ≥80% success rate
- **Yellow**: 50-79% success rate
- **Red**: <50% success rate

### 9. Real-Time Updates

The TUI automatically updates every second:

- Runtime for running jobs increments live
- Progress indicators animate
- Status changes reflect immediately
- Statistics update automatically

## Architecture

### New Components

#### `JobListWidget` (`src/tui/widgets/job_list.py`)

Custom DataTable subclass with:

- Reactive properties for filtering and sorting
- Color-coded status formatting
- Progress indicator generation
- Runtime calculation and formatting
- Resource usage display
- In-place cell updates for efficiency

#### `JobStatsWidget` (`src/tui/widgets/job_stats.py`)

Footer widget displaying:

- Aggregated job statistics
- Color-coded counts
- Success rate calculation
- Dynamic updates based on job list

### Modified Components

#### `app_enhanced.py`

Enhanced version of the main application:

- Uses `JobListWidget` instead of plain `DataTable`
- Adds `JobStatsWidget` to layout
- Implements `set_interval` for real-time updates
- Adds keybindings for filtering (`f`) and sorting (`t`)
- Updates message handlers to use new widgets

## UI Layout

```
┌─────────────────────────────────────────────────────────┐
│ Header                                                  │
├───────────────────────┬─────────────────────────────────┤
│ Job List (50%)        │ Content Tabs (50%)              │
│                       │                                 │
│ ID  Name  Status ...  │ ┌─ Log ─┐┌ Input ┐┌ Results ┐  │
│ 1   job1  ✓ ...       │ │       ││       ││         │  │
│ 2   job2  ▶ ...       │ │ Log   ││ Input ││ Results │  │
│ 3   job3  ⏸ ...       │ │ output││ file  ││ summary │  │
│ ...                   │ │       ││       ││         │  │
├───────────────────────┤ └───────┘└───────┘└─────────┘  │
│ Job Statistics        │                                 │
│ Total: 3  ▶ Running: │                                 │
└───────────────────────┴─────────────────────────────────┘
│ Footer (q) Quit  (n) New Job  (r) Run  (f) Filter  (t) │
└─────────────────────────────────────────────────────────┘
```

## Usage Examples

### View All Running Jobs

1. Press `f` to activate filter
2. Filter cycles to "RUNNING"
3. Only running jobs are displayed
4. Press `f` four more times to return to "ALL"

### Sort by Runtime

1. Press `t` three times to reach "Runtime" sort
2. Jobs are sorted by runtime (longest first)
3. Press `t` two more times to return to "Created" sort

### Monitor Real-Time Progress

1. Select a running job with arrow keys
2. Watch the Runtime column increment every second
3. View live log output in the Log tab
4. Check job statistics footer for overall progress

## Testing

To test the enhanced display:

```bash
cd /Users/briansquires/CRYSTAL23/crystalmath/tui

# Run the TUI
python3 -m src.main

# Create several test jobs (press 'n')
# Run some jobs (press 'r')
# Test filtering (press 'f')
# Test sorting (press 't')
# Watch real-time updates for running jobs
```

## Technical Details

### Performance Optimizations

1. **Reactive Properties**: Only update when values change
2. **Efficient Cell Updates**: Update individual cells instead of full refresh
3. **Cached Job Data**: Store job objects to avoid repeated database queries
4. **Throttled Updates**: Runtime updates limited to 1 second intervals

### Textual Integration

- Uses Textual's reactive system for automatic updates
- Leverages Rich's Text objects for styled output
- Implements custom event handlers for row selection
- Uses DataTable's built-in row keying for efficient updates

### Database Schema

No changes to database schema required. All enhancements use existing fields:

- `status` - Job status
- `created_at`, `started_at`, `completed_at` - Timestamps
- `pid` - Process ID
- `final_energy` - Energy value
- `key_results` - JSON metadata (includes resource info)

## Future Enhancements

Potential improvements for Phase 2:

1. **Estimated Time Remaining**: Use historical data to predict completion time
2. **CPU/Memory Usage**: Show real-time resource consumption (requires psutil)
3. **Progress Percentage**: Calculate progress from SCF cycles or optimization steps
4. **Custom Filters**: Allow user-defined filter expressions
5. **Column Customization**: Let users choose which columns to display
6. **Export Statistics**: Export job statistics to CSV/JSON

## Compatibility

- Requires Textual 0.40.0+
- Python 3.10+
- Works with existing database schema
- Backward compatible with original app.py

## References

- Issue: crystalmath-hai
- Related Files:
  - `src/tui/widgets/job_list.py`
  - `src/tui/widgets/job_stats.py`
  - `src/tui/app_enhanced.py`
  - `src/main.py`
