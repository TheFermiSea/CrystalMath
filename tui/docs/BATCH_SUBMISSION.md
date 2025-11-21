# Batch Job Submission

The Batch Job Submission feature allows you to create and submit multiple CRYSTAL calculation jobs simultaneously with common settings and per-job customization.

## Overview

The Batch Submission screen provides:

- **Common Settings**: Configure default parameters for all jobs in the batch
- **Job Management**: Add, remove, and organize multiple jobs
- **Bulk Submission**: Submit all jobs at once with validation
- **Status Tracking**: Monitor submission progress in real-time
- **Per-Job Overrides**: Customize individual job settings (future feature)

## Accessing Batch Submission

### From Main App

Press `b` (or click the "Batch" button in the footer) to open the Batch Submission screen.

### From Command Line

```bash
# Launch TUI and press 'b'
crystal-tui
```

## UI Layout

```
┌─ Batch Job Submission ────────────────────────────┐
│ Common Settings:                                   │
│ Cluster: [Local ▼]  Partition: [compute]          │
│ MPI Ranks: [14]  Threads: [4]  Time: [24:00:00]  │
├────────────────────────────────────────────────────┤
│ Jobs (3 total):                                    │
│ ┌────────────────────────────────────────────────┐│
│ │Name      Input File    Status   Resources      ││
│ │mgo_1     mgo_1.d12     READY    14×4           ││
│ │mgo_2     mgo_2.d12     READY    14×4           ││
│ │mgo_3     mgo_3.d12     READY    14×4           ││
│ └────────────────────────────────────────────────┘│
├────────────────────────────────────────────────────┤
│ Status: Ready to submit                            │
│ Progress: Submitting job 2/3: mgo_2                │
├────────────────────────────────────────────────────┤
│ [Add Job] [Remove] [Submit All] [Cancel]          │
└────────────────────────────────────────────────────┘
```

## Common Settings

Configure default parameters that apply to all jobs:

### Cluster Selection

- **Local**: Execute jobs on the local machine (default)
- **HPC-Cluster**: Submit jobs to remote HPC cluster (requires SSH/SLURM runner)

### Parallelism Settings

- **MPI Ranks**: Number of MPI processes (default: 14)
- **Threads**: OpenMP threads per MPI rank (default: 4)
- **Total Cores**: Ranks × Threads (e.g., 14 × 4 = 56 cores)

### Job Scheduling

- **Partition**: Queue/partition name (default: "compute")
- **Time Limit**: Maximum walltime in HH:MM:SS format (default: "24:00:00")

## Managing Jobs

### Adding Jobs

**Keyboard**: Press `a`
**Mouse**: Click "Add Job" button

Currently adds a demo job for testing. In production, this will open:
- File picker to select `.d12` input files
- Bulk import from directory
- Job template selection

### Removing Jobs

1. Select a job in the table using arrow keys
2. Press `d` or click "Remove" button
3. Job is removed from the batch (not yet submitted jobs only)

### Reviewing Jobs

The jobs table displays:

- **Name**: Unique job identifier
- **Input File**: Path to `.d12` input file
- **Status**: Current state (READY, SUBMITTING, PENDING, ERROR)
- **Cluster**: Execution target (local or remote)
- **Resources**: MPI ranks × threads configuration

## Validation

Before submission, the system validates:

### Job-Level Validation

- **Unique Names**: No duplicate job names in batch
- **Valid Characters**: Names contain only letters, numbers, hyphens, underscores
- **No Conflicts**: Names don't conflict with existing jobs in database
- **Input Files Exist**: All `.d12` files are accessible
- **Valid Resources**: MPI ranks ≥ 1, threads ≥ 1

### Batch-Level Validation

- **At Least One Job**: Batch contains at least one job
- **Cluster Configuration**: Selected cluster is properly configured
- **Resource Limits**: Requests don't exceed system limits (future)

### Validation Errors

Errors are displayed in the error message area:
- Red text highlights the problem
- Auto-clears after 5 seconds
- Prevents submission until resolved

## Submission Workflow

### Step 1: Press Enter or Click "Submit All"

Triggers validation and submission process.

### Step 2: Job Validation

System validates all jobs in the batch. If errors are found:
- First error is displayed
- Submission is cancelled
- Fix errors and try again

### Step 3: Job Creation

For each job in the batch:
1. Create unique work directory: `calculations/XXXX_jobname`
2. Copy input file to `work_dir/input.d12`
3. Write metadata to `work_dir/job_metadata.json`
4. Create database record with PENDING status

### Step 4: Progress Tracking

The UI displays real-time progress:
```
Progress: Submitting job 2/5: mgo_optimization_2
```

Job status in table updates:
- **READY** → **SUBMITTING** → **PENDING** (or **ERROR**)

### Step 5: Completion

On successful completion:
- Success message displayed
- All jobs appear in main job list
- Modal closes automatically after 1.5 seconds

## Keyboard Shortcuts

| Key | Action | Description |
|-----|--------|-------------|
| `b` | Open Batch | Open batch submission screen (from main app) |
| `a` | Add Job | Add new job to batch |
| `d` | Delete Job | Remove selected job from batch |
| `Enter` | Submit All | Validate and submit all jobs |
| `Esc` | Cancel | Close modal without submitting |
| `↑/↓` | Navigate | Move selection in jobs table |

## Job Metadata

Each submitted job includes metadata file (`job_metadata.json`):

```json
{
  "mpi_ranks": 14,
  "threads": 4,
  "cluster": "local",
  "partition": "compute",
  "time_limit": "24:00:00",
  "parallel_mode": "parallel"
}
```

This metadata is used by the execution runner to configure the job properly.

## Database Integration

Batch jobs are stored in the SQLite database with:

- **Status**: PENDING (ready to run)
- **Work Directory**: `calculations/XXXX_jobname/`
- **Input Content**: Full `.d12` file content
- **Created At**: Timestamp of submission

Jobs appear immediately in the main job list after submission.

## Error Handling

### Common Errors

**"No jobs to submit"**
- Add at least one job before submitting

**"Duplicate job names found"**
- Ensure all job names in batch are unique

**"Invalid characters in name"**
- Use only letters, numbers, hyphens, underscores

**"Job name already exists"**
- Job with this name exists in database
- Choose a different name

**"Input file not found"**
- Verify `.d12` file path is correct
- Check file permissions

**"Work directory already exists"**
- Database may be out of sync
- Check `calculations/` directory manually

### Recovery

If submission fails partway through:
1. Check which jobs were created in main list
2. Failed jobs will show ERROR status
3. Remove failed jobs from batch
4. Fix issues and resubmit remaining jobs

## Example Workflows

### Example 1: Parameter Scan

Submit multiple jobs with varying parameters:

```
Job Name            Input File           MPI×Threads
------------------------------------------------------
mgo_a_5.0           mgo_a_5.0.d12       14×4
mgo_a_5.1           mgo_a_5.1.d12       14×4
mgo_a_5.2           mgo_a_5.2.d12       14×4
mgo_a_5.3           mgo_a_5.3.d12       14×4
```

All jobs use common settings, different input files scan lattice parameter.

### Example 2: Basis Set Comparison

Compare different basis sets:

```
Job Name            Input File           Resources
------------------------------------------------------
mgo_sto3g           mgo_sto3g.d12       14×4
mgo_631g            mgo_631g.d12        14×4
mgo_def2svp         mgo_def2svp.d12     28×2 (larger basis)
mgo_def2tzvp        mgo_def2tzvp.d12    28×2 (larger basis)
```

### Example 3: Multi-System Study

Submit jobs for different materials:

```
Job Name            Input File           Cluster
------------------------------------------------------
mgo_bulk            mgo_bulk.d12        local
cao_bulk            cao_bulk.d12        local
sro_bulk            sro_bulk.d12        hpc (larger system)
bao_bulk            bao_bulk.d12        hpc (larger system)
```

## Future Features

### Per-Job Overrides

- Override common settings for specific jobs
- Different clusters for different jobs
- Custom time limits per job

### Job Dependencies

- Configure job A to run after job B completes
- Build workflows with multiple stages
- Automatic chaining of calculations

### Job Naming Patterns

- Auto-generate names with patterns
- Template-based naming: `{system}_{parameter}_{index}`
- Bulk rename functionality

### Advanced Validation

- Check for duplicate input file content
- Validate CRYSTAL input syntax
- Estimate resource requirements
- Warn about oversubscription

### Input File Management

- Browse and select multiple `.d12` files
- Import entire directories
- Preview input file content
- Edit inputs before submission

### Progress Visualization

- Progress bar for batch submission
- Estimated time remaining
- Parallel submission (multiple jobs at once)
- Submission queue management

## Integration with Other Features

### With LocalRunner

Batch jobs use the same LocalRunner backend:
- Same validation rules
- Same output parsing
- Same result storage

### With Job List

Batch jobs appear in main job list:
- Can be run individually
- Can be stopped
- Can view logs and results

### With Database

All batch jobs stored in SQLite:
- Persistent across sessions
- Full job history
- Query and filter capabilities

## Technical Details

### Implementation

The batch submission feature is implemented in:
- **Screen**: `src/tui/screens/batch_submission.py`
- **Tests**: `tests/test_batch_submission.py`
- **Database**: Uses existing `Database` class
- **Runner**: Uses `LocalRunner` for execution

### Data Model

```python
@dataclass
class BatchJobConfig:
    name: str
    input_file: Path
    cluster: str = "local"
    mpi_ranks: int = 1
    threads: int = 4
    partition: str = "compute"
    time_limit: str = "24:00:00"
```

### Message Passing

```python
class BatchJobsCreated(Message):
    job_ids: List[int]
    job_names: List[str]
```

Posted to main app after successful submission.

## Troubleshooting

### Jobs Not Appearing in Main List

1. Check database file: `.crystal_tui.db`
2. Verify `calculations/` directory exists
3. Check submission didn't error partway
4. Restart TUI to refresh database connection

### Validation Always Failing

1. Check job names for invalid characters
2. Verify no duplicate names in batch
3. Ensure input files exist and are readable
4. Check database for conflicting job names

### Submission Hangs

1. Press `Esc` to cancel
2. Check system resources
3. Verify database isn't locked
4. Check `calculations/` directory permissions

## Best Practices

1. **Test with Small Batches**: Start with 2-3 jobs before large batches
2. **Unique Naming**: Use descriptive, systematic naming schemes
3. **Verify Inputs**: Check input files are correct before submission
4. **Monitor Progress**: Watch status messages during submission
5. **Check Results**: Verify first job completes successfully before submitting more

## See Also

- [New Job Screen](NEW_JOB.md) - Single job creation
- [Job Execution](JOB_EXECUTION.md) - Running jobs
- [Project Status](PROJECT_STATUS.md) - TUI roadmap
- [Database Schema](DATABASE.md) - Job storage details
