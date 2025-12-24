# Quick Reference: Enhanced Job Status Display

## What's New

The CRYSTAL-TUI now features a rich, color-coded job list with real-time updates!

## Visual Guide

```
┌─────────────────────────────────────────────────────────────┐
│ CRYSTAL-TUI                                                 │
├───────────────────────────┬─────────────────────────────────┤
│ ID│Name │Status│Progress│ │ Log  │ Input │ Results         │
│ 1 │mgo  │✓ COMP│██████████ │      │       │                 │
│ 2 │si   │▶ RUN │█████░░░░░ │ Output logs appear here...    │
│ 3 │test │⏸ PEND│░░░░░░░░░░ │                               │
├───────────────────────────┤                                 │
│ Total: 3  ✓: 1  ▶: 1  ⏸: 1│                               │
└───────────────────────────┴─────────────────────────────────┘
```

## Status Colors

- ⏸ **PENDING** → dim gray (not started)
- ⏳ **QUEUED** → yellow (waiting)
- ▶ **RUNNING** → cyan bold (executing)
- ✓ **COMPLETED** → green bold (success)
- ✗ **FAILED** → red bold (error)

## Keyboard Shortcuts

| Key | Action | Description |
|-----|--------|-------------|
| `n` | New Job | Create a new calculation |
| `r` | Run | Start selected job |
| `s` | Stop | Cancel running job |
| `f` | Filter | Cycle through status filters |
| `t` | Sort | Cycle through sort options |
| `q` | Quit | Exit application |

## Features

### 1. Real-Time Updates

Runtime updates automatically every second:
```
Runtime: 45s → 46s → 47s ...
Runtime: 3m 24s → 3m 25s → 3m 26s ...
Runtime: 1h 5m → 1h 5m → 1h 6m ...
```

### 2. Progress Bars

Visual indicators using Unicode braille:
```
⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀  Pending
⣿⣿⣿⣿⣿⣀⣀⣀⣀⣀  Running (50%)
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿  Completed (100%)
⣿⣿⣀⣀⣀⣀⣀⣀⣀⣀  Failed (20%)
```

### 3. Resource Display

Shows job configuration:
```
4R×8T   → 4 MPI ranks × 8 threads
8T      → 8 threads (serial)
PID:123 → Process ID (fallback)
```

### 4. Filtering (Press `f`)

Cycle through filters:
1. ALL → Show all jobs
2. RUNNING → Show only running
3. COMPLETED → Show only successful
4. FAILED → Show only errors
5. PENDING → Show only waiting
6. ALL → Back to start

### 5. Sorting (Press `t`)

Cycle through sort options:
1. Created → Newest first (default)
2. Name → Alphabetical order
3. Status → Group by status
4. Runtime → Longest first
5. Energy → Highest first
6. Created → Back to start

### 6. Statistics Footer

Always visible summary:
```
Total: 25  ▶ Running: 3  ✓ Completed: 18  ✗ Failed: 4  Success Rate: 81.8%
```

Color-coded success rate:
- **Green**: ≥80% success (good)
- **Yellow**: 50-79% success (okay)
- **Red**: <50% success (needs attention)

## Common Workflows

### Monitor Running Jobs

1. Press `f` to filter to RUNNING
2. Watch runtime increment live
3. View output in Log tab
4. Check statistics footer for overall progress

### Find Completed Jobs

1. Press `f` twice to filter to COMPLETED
2. Press `t` four times to sort by energy
3. Select job to view results
4. Results appear in Results tab

### Review Failed Jobs

1. Press `f` three times to filter to FAILED
2. Select failed job
3. View errors in Log tab
4. Check input file in Input tab

### Compare Job Performance

1. Press `t` three times to sort by runtime
2. Longest jobs appear at top
3. Identify performance patterns
4. Optimize future jobs

## Tips

- **Navigation**: Use arrow keys to select jobs
- **Quick View**: Select job to see input/output/results
- **Live Updates**: Leave TUI running to monitor progress
- **Statistics**: Check footer for success rate trends

## Example Session

```bash
# Start TUI
crystal-tui

# Create a new job (press 'n')
# Fill in: Name=mgo, MPI ranks=4, Threads=8
# Submit job

# Run the job (press 'r')
# Watch runtime increment: 0s → 1s → 2s ...
# View live log output in Log tab

# Filter to running jobs (press 'f')
# Only running jobs displayed
# Statistics show: "▶ Running: 1"

# Sort by runtime (press 't' 3 times)
# Jobs ordered by runtime
# Longest jobs at top

# Wait for completion
# Status changes to "✓ COMPLETED"
# Energy displayed in table
# Results available in Results tab

# Press 'f' 5 times to show all jobs again
# Review statistics footer for overall success rate
```

## Troubleshooting

**Q: Runtime not updating?**
A: Timer runs automatically every 1 second. Wait a moment.

**Q: Progress bar stuck?**
A: Progress is estimate-based. Check Log tab for actual output.

**Q: Statistics not updating?**
A: Stats update after status changes. Wait for job completion.

**Q: Filter not working?**
A: Press `f` multiple times to cycle through all filters.

**Q: Can't see all columns?**
A: Resize terminal window for more space (minimum 80x24).

## More Information

- Full documentation: `docs/ENHANCED_STATUS_DISPLAY.md`
- Implementation details: `docs/IMPLEMENTATION_SUMMARY.md`
- Testing: `docs/test_enhanced_display.sh`

## Issue Tracking

- Issue ID: crystalmath-hai
- Status: Closed ✓
- Date: 2025-11-20

---

*For help, press `?` in the TUI or see the full documentation.*
