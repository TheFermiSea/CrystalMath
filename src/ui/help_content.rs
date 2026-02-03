//! Static help content for the hierarchical help system.
//!
//! This module contains all the help text organized by topic.

use crate::state::help::HelpTopic;

/// Get the help content for a given topic.
pub fn get_content(topic: HelpTopic) -> &'static str {
    match topic {
        // Root level
        HelpTopic::Overview => OVERVIEW,
        HelpTopic::Navigation => NAVIGATION,
        HelpTopic::KeyBindings => KEY_BINDINGS,

        // Jobs Tab
        HelpTopic::Jobs => JOBS,
        HelpTopic::JobsNavigation => JOBS_NAVIGATION,
        HelpTopic::JobsNewJob => JOBS_NEW_JOB,
        HelpTopic::JobsClusterConfig => JOBS_CLUSTER_CONFIG,
        HelpTopic::JobsCancelJobs => JOBS_CANCEL,
        HelpTopic::JobsWorkflows => JOBS_WORKFLOWS,
        HelpTopic::JobsSlurmQueue => JOBS_SLURM_QUEUE,

        // Editor Tab
        HelpTopic::Editor => EDITOR,
        HelpTopic::EditorBasics => EDITOR_BASICS,
        HelpTopic::EditorSubmit => EDITOR_SUBMIT,
        HelpTopic::EditorLsp => EDITOR_LSP,

        // Results Tab
        HelpTopic::Results => RESULTS,
        HelpTopic::ResultsNavigation => RESULTS_NAVIGATION,
        HelpTopic::ResultsDetails => RESULTS_DETAILS,

        // Log Tab
        HelpTopic::Log => LOG,
        HelpTopic::LogNavigation => LOG_NAVIGATION,
        HelpTopic::LogFollowMode => LOG_FOLLOW_MODE,

        // Modals
        HelpTopic::RecipeBrowser => RECIPE_BROWSER,
        HelpTopic::RecipeNavigation => RECIPE_NAVIGATION,
        HelpTopic::RecipeLaunching => RECIPE_LAUNCHING,

        HelpTopic::MaterialsSearch => MATERIALS_SEARCH,
        HelpTopic::MaterialsFormula => MATERIALS_FORMULA,
        HelpTopic::MaterialsImportD12 => MATERIALS_IMPORT_D12,
        HelpTopic::MaterialsImportVasp => MATERIALS_IMPORT_VASP,

        HelpTopic::ClusterManager => CLUSTER_MANAGER,
        HelpTopic::ClusterAdd => CLUSTER_ADD,
        HelpTopic::ClusterEdit => CLUSTER_EDIT,
        HelpTopic::ClusterTest => CLUSTER_TEST,

        HelpTopic::WorkflowLauncher => WORKFLOW_LAUNCHER,
        HelpTopic::WorkflowConvergence => WORKFLOW_CONVERGENCE,
        HelpTopic::WorkflowBandStructure => WORKFLOW_BAND_STRUCTURE,
        HelpTopic::WorkflowPhonon => WORKFLOW_PHONON,
        HelpTopic::WorkflowEos => WORKFLOW_EOS,

        HelpTopic::TemplateBrowser => TEMPLATE_BROWSER,
        HelpTopic::VaspInput => VASP_INPUT,
        HelpTopic::BatchSubmission => BATCH_SUBMISSION,
    }
}

// =============================================================================
// Overview / Global
// =============================================================================

const OVERVIEW: &str = "\
CrystalMath TUI - High-performance interface for CRYSTAL23 and VASP calculations.

This is the Cockpit view - a Rust-based TUI focused on monitoring and job \
management. Use this interface for:

  • Viewing and managing calculation jobs
  • Monitoring job status and output logs
  • Submitting new calculations
  • Browsing workflow results

QUICK START:

  1. Press Tab to switch between tabs (Jobs, Editor, Results, Log)
  2. Use j/k or arrow keys to navigate lists
  3. Press n to create a new job from the Jobs tab
  4. Press c to configure cluster connections
  5. Press ? anytime to open this help

The TUI automatically refreshes job status. Use Ctrl+R for manual refresh.
";

const NAVIGATION: &str = "\
GLOBAL NAVIGATION

Tab Switching:
  Tab         - Next tab
  Shift+Tab   - Previous tab
  1/2/3/4     - Jump to Jobs/Editor/Results/Log directly

Modal Controls:
  Esc         - Close current modal
  ?           - Open help (works from anywhere)

Application:
  Ctrl+Q      - Quit application
  Ctrl+C      - Quit application (alternative)
  Ctrl+R      - Refresh jobs list

Within any list or table:
  j or ↓      - Move down
  k or ↑      - Move up
  Enter       - Select/activate
  Home        - Jump to first item
  End         - Jump to last item
";

const KEY_BINDINGS: &str = "\
QUICK REFERENCE - ALL KEY BINDINGS

Global:
  ?           Open help
  Tab         Next tab
  Shift+Tab   Previous tab
  1-4         Direct tab access
  Ctrl+R      Refresh jobs
  Ctrl+Q      Quit

Jobs Tab:
  n           New job
  c           Cluster manager
  r           Recipe browser
  w           Workflow launcher
  s           SLURM queue
  v           VASP input
  T           Template browser
  B           Batch submission
  l           View log
  C           Cancel job (press twice)
  W           Workflow dashboard

Editor Tab:
  Ctrl+Enter  Submit job
  Ctrl+I      Materials import

Results Tab:
  j/k         Scroll results
  PgUp/PgDn   Page scroll

Log Tab:
  j/k         Scroll log
  f           Toggle follow mode
  g           Jump to top
  G           Jump to bottom
";

// =============================================================================
// Jobs Tab
// =============================================================================

const JOBS: &str = "\
JOBS TAB

The Jobs tab displays all submitted calculations with their current status.

Each job shows:
  • Job name and ID
  • DFT code (CRYSTAL, VASP, QE)
  • Status (pending, running, completed, failed)
  • Cluster where job is running
  • Submission time

COLOR CODES:
  Green   - Completed successfully
  Yellow  - Running or pending
  Red     - Failed
  Blue    - Recently changed

ACTIONS FROM THIS TAB:
  n - Create new job
  c - Manage clusters
  w - Launch workflows
  s - View SLURM queue
  r - Browse recipes

Press Enter on a job to view its details in the Results tab.
";

const JOBS_NAVIGATION: &str = "\
JOBS LIST NAVIGATION

Moving through jobs:
  j or ↓      Move to next job
  k or ↑      Move to previous job
  Home        Jump to first job
  End         Jump to last job

Viewing details:
  Enter       View job details (switches to Results tab)
  l           View job log (switches to Log tab)

Selection indicator shows the currently focused job.
";

const JOBS_NEW_JOB: &str = "\
CREATING A NEW JOB

Press n from the Jobs tab to open the New Job modal.

REQUIRED FIELDS:
  Job Name    - Alphanumeric with hyphens/underscores
  DFT Code    - CRYSTAL, VASP, or Quantum ESPRESSO
  Runner      - Local, SSH, or SLURM

OPTIONAL FIELDS:
  Cluster     - Required for SSH/SLURM runners
  MPI Ranks   - Number of parallel processes
  Walltime    - Maximum runtime (HH:MM:SS)
  Memory      - Memory limit in GB
  Partition   - SLURM partition name

NAVIGATION:
  Tab         Next field
  Shift+Tab   Previous field
  Space       Cycle options (DFT code, runner)
  Enter       Submit job
  Esc         Cancel

The job will use the content currently in the Editor tab.
";

const JOBS_CLUSTER_CONFIG: &str = "\
CLUSTER CONFIGURATION

Press c from the Jobs tab to open the Cluster Manager.

A cluster represents a remote compute resource (SSH server or SLURM system).

CLUSTER TYPES:
  SSH   - Direct SSH execution (crystalOMP runs via SSH)
  SLURM - Batch scheduler (job submitted via sbatch)

REQUIRED SETTINGS:
  Name        - Display name for the cluster
  Hostname    - Server address (e.g., login.hpc.edu)
  Username    - Your account on the cluster
  Work Dir    - Remote directory for job files

SLURM-SPECIFIC:
  Partition   - Default partition/queue
  Account     - Allocation account (if required)

Use Tab to navigate fields, Enter to save.
";

const JOBS_CANCEL: &str = "\
CANCELING JOBS

Press C (Shift+c) on a selected job to request cancellation.

SAFETY: Cancellation requires confirmation. Press C twice within 3 seconds \
to confirm the cancellation.

WHAT HAPPENS:
  Local jobs  - Process is terminated (SIGTERM then SIGKILL)
  SSH jobs    - Kill signal sent via SSH
  SLURM jobs  - scancel command issued

NOTES:
  • Only pending or running jobs can be canceled
  • Completed/failed jobs cannot be canceled
  • Cancellation may take a moment to propagate
";

const JOBS_WORKFLOWS: &str = "\
WORKFLOWS

Workflows are multi-job calculations with dependencies.

Press w from Jobs tab to launch a new workflow.
Press W (Shift+w) to open the Workflow Dashboard.

AVAILABLE WORKFLOWS:
  Convergence     - Test parameter convergence (k-points, cutoffs)
  Band Structure  - Electronic band structure calculation
  Phonon          - Vibrational frequencies
  EOS             - Equation of state / volume scan

WORKFLOW DASHBOARD:
  Shows workflows grouped with their child jobs
  Track overall progress (completed/total)
  View aggregated results
  Retry failed jobs

Each workflow creates multiple jobs that run in sequence or parallel.
";

const JOBS_SLURM_QUEUE: &str = "\
SLURM QUEUE VIEWER

Press s from Jobs tab to view the SLURM queue for a configured cluster.

DISPLAY:
  Job ID      - SLURM job identifier
  Name        - Job name
  Status      - R(unning), PD(pending), etc.
  Time        - Elapsed runtime
  Nodes       - Allocated nodes

ACTIONS:
  j/k         Navigate queue
  r           Refresh queue (fetches current state)
  Esc         Close viewer

This shows all jobs in the queue, not just yours. Useful for checking \
cluster utilization and queue wait times.
";

// =============================================================================
// Editor Tab
// =============================================================================

const EDITOR: &str = "\
EDITOR TAB

The Editor tab provides a text editor for DFT input files.

FEATURES:
  • Syntax-aware editing (via LSP integration)
  • Live diagnostics for input validation
  • Direct job submission

The editor content is used when creating new jobs. Edit your input file \
here, then press n from Jobs tab to submit it.

LSP INTEGRATION:
  If configured, the editor provides:
  • Error highlighting
  • Warnings for common issues
  • Syntax validation

Use Ctrl+I to import a structure from Materials Project directly into \
the editor.
";

const EDITOR_BASICS: &str = "\
EDITOR BASICS

Standard text editing with vim-like navigation:

CURSOR MOVEMENT:
  Arrow keys  - Move cursor
  Home/End    - Start/end of line
  Ctrl+Home   - Start of document
  Ctrl+End    - End of document

EDITING:
  Type        - Insert text at cursor
  Backspace   - Delete character before cursor
  Delete      - Delete character at cursor
  Enter       - Insert new line

SELECTION:
  Shift+Arrow - Select text
  Ctrl+A      - Select all

The editor automatically saves state. Your content persists between sessions.
";

const EDITOR_SUBMIT: &str = "\
SUBMITTING FROM EDITOR

Press Ctrl+Enter to submit the current editor content as a new job.

This is a shortcut that:
  1. Takes the editor content as input
  2. Opens the New Job modal
  3. Pre-fills the input content

You can also:
  1. Edit your input in the Editor tab
  2. Press n from Jobs tab
  3. The new job uses editor content automatically

CONFIRMATION:
  Job submission requires pressing Ctrl+Enter twice within 3 seconds \
  to prevent accidental submissions.
";

const EDITOR_LSP: &str = "\
LSP INTEGRATION

The editor integrates with a Language Server Protocol (LSP) server \
for intelligent editing support.

FEATURES:
  • Real-time error detection
  • Syntax validation
  • Keyword completion hints

DIAGNOSTICS:
  Errors appear highlighted in the editor
  The Log tab shows detailed diagnostic messages

CONFIGURATION:
  Set CRYSTAL_TUI_LSP_PATH to specify the LSP server executable.
  Default: vasp-lsp (if installed on PATH)

If no LSP server is available, the editor works normally without \
diagnostics - this is graceful degradation.
";

// =============================================================================
// Results Tab
// =============================================================================

const RESULTS: &str = "\
RESULTS TAB

The Results tab displays detailed information about a selected job.

To view job results:
  1. Select a job in the Jobs tab
  2. Press Enter to load details

DISPLAYED INFORMATION:
  • Job status and timing
  • Calculation parameters
  • Energy values (if completed)
  • Convergence information
  • Errors (if failed)

Use j/k to scroll through long results.
";

const RESULTS_NAVIGATION: &str = "\
RESULTS NAVIGATION

Scrolling through results:
  j or ↓      Scroll down one line
  k or ↑      Scroll up one line
  Page Down   Scroll down one page
  Page Up     Scroll up one page

The results view wraps long lines. Scroll to see all content.
";

const RESULTS_DETAILS: &str = "\
RESULTS DETAILS

The results view shows parsed output from completed calculations:

CRYSTAL OUTPUTS:
  • Total energy (Hartree)
  • Energy per atom
  • SCF convergence history
  • Geometry optimization progress
  • Frequency results

VASP OUTPUTS:
  • Total energy (eV)
  • Band gap
  • Ionic relaxation steps
  • Forces and stress

Results are parsed from the calculation output files. If parsing fails, \
raw output is displayed.
";

// =============================================================================
// Log Tab
// =============================================================================

const LOG: &str = "\
LOG TAB

The Log tab shows the raw output file from a running or completed job.

To view a job's log:
  1. Select a job in the Jobs tab
  2. Press l (lowercase L)

FEATURES:
  • Real-time updates for running jobs
  • Follow mode (auto-scroll to bottom)
  • Full output file content

This is useful for monitoring calculation progress and debugging failures.
";

const LOG_NAVIGATION: &str = "\
LOG NAVIGATION

Scrolling through the log:
  j or ↓      Scroll down one line
  k or ↑      Scroll up one line
  Page Down   Scroll down one page
  Page Up     Scroll up one page
  g           Jump to top (first line)
  G           Jump to bottom (last line)

Manual refresh:
  r           Refresh log content
";

const LOG_FOLLOW_MODE: &str = "\
LOG FOLLOW MODE

Press f to toggle follow mode.

WHEN ENABLED:
  • Log automatically refreshes every 2 seconds
  • View stays scrolled to the bottom
  • New output appears as job runs
  • Indicator shows 'FOLLOW' in status bar

WHEN DISABLED:
  • Log stays at current scroll position
  • Manual refresh with r key
  • Useful for reviewing specific output sections

Follow mode is especially useful for monitoring long-running calculations.
";

// =============================================================================
// Recipe Browser
// =============================================================================

const RECIPE_BROWSER: &str = "\
RECIPE BROWSER

Press r from Jobs tab to open the Recipe Browser.

Recipes are pre-configured calculation workflows from quacc (quantum \
chemistry calculation framework).

RECIPE CATEGORIES:
  • Static (single-point energy)
  • Relax (geometry optimization)
  • Phonon (vibrational)
  • Band structure
  • Custom workflows

Select a recipe to see its description and required inputs.
";

const RECIPE_NAVIGATION: &str = "\
RECIPE BROWSER NAVIGATION

  j or ↓      Move to next recipe
  k or ↑      Move to previous recipe
  Tab         Switch between recipe list and details
  Enter       Launch selected recipe
  Esc         Close browser

Recipes are organized by DFT code and calculation type.
";

const RECIPE_LAUNCHING: &str = "\
LAUNCHING RECIPES

Select a recipe and press Enter to launch it.

A configuration modal will open for:
  • Selecting input structure
  • Choosing cluster
  • Setting calculation parameters

The recipe creates one or more jobs based on the workflow definition.

REQUIREMENTS:
  • Valid cluster configuration
  • Input structure (from Materials Project or editor)
  • quacc integration enabled
";

// =============================================================================
// Materials Search
// =============================================================================

const MATERIALS_SEARCH: &str = "\
MATERIALS PROJECT SEARCH

Press Ctrl+I from Editor tab (or m from various contexts) to search \
the Materials Project database.

Search by chemical formula to find crystal structures:
  • MoS2   - Molybdenum disulfide
  • Si     - Silicon
  • LiFePO4 - Lithium iron phosphate

Results show:
  • Material ID
  • Formula
  • Space group
  • Band gap
  • Energy above hull

Select a material to import its structure into your calculation.
";

const MATERIALS_FORMULA: &str = "\
FORMULA SEARCH

Enter a chemical formula to search:

EXAMPLES:
  Fe2O3     - Iron oxide (hematite)
  GaAs      - Gallium arsenide
  BaTiO3    - Barium titanate

TIPS:
  • Use proper capitalization (Fe not FE)
  • Subscripts as numbers (H2O not H₂O)
  • Anonymous formulas work (AB2 finds all 1:2 compounds)

Press Enter to search after typing your formula.
";

const MATERIALS_IMPORT_D12: &str = "\
IMPORT TO D12 (CRYSTAL)

After selecting a material, press Enter to generate a CRYSTAL .d12 input.

The generated input includes:
  • Crystal structure (from Materials Project)
  • Default basis set (based on elements)
  • Standard SCF settings
  • K-point grid

You can then edit the generated input in the Editor tab before submitting.

CONFIGURATION:
  Basis sets and default settings can be customized in the import dialog.
";

const MATERIALS_IMPORT_VASP: &str = "\
IMPORT TO VASP

After selecting a material, press v to generate VASP input files.

GENERATED FILES:
  POSCAR   - Crystal structure
  INCAR    - Calculation settings
  KPOINTS  - K-point mesh
  (POTCAR config - you provide the actual POTCAR)

PRESETS:
  p - Cycle through presets (relax, static, band, dos)
  K - Cycle k-point density (500, 1000, 2000, 4000 KPPRA)

The VASP Input modal opens with all files ready for editing.
";

// =============================================================================
// Cluster Manager
// =============================================================================

const CLUSTER_MANAGER: &str = "\
CLUSTER MANAGER

Press c from Jobs tab to manage compute cluster configurations.

CLUSTER TYPES:
  SSH   - Direct execution via SSH
  SLURM - Batch job submission

Each cluster stores:
  • Connection details (host, user)
  • Default settings (partition, account)
  • Work directory path

Clusters are used when submitting jobs with SSH or SLURM runners.
";

const CLUSTER_ADD: &str = "\
ADDING A CLUSTER

In the Cluster Manager, press n to add a new cluster.

REQUIRED FIELDS:
  Name      - Display name (e.g., 'HPC Cluster')
  Type      - SSH or SLURM
  Hostname  - Server address
  Username  - Your login username
  Work Dir  - Remote working directory

OPTIONAL:
  Port      - SSH port (default: 22)
  Partition - Default SLURM partition
  Account   - SLURM account (if required)

Press Enter to save, Esc to cancel.
";

const CLUSTER_EDIT: &str = "\
EDITING A CLUSTER

Select a cluster and press e to edit its configuration.

All fields can be modified:
  • Connection settings
  • Default parameters
  • Work directory

Changes take effect immediately for new jobs. Running jobs are not affected.
";

const CLUSTER_TEST: &str = "\
TESTING CLUSTER CONNECTION

Select a cluster and press t to test the connection.

THE TEST VERIFIES:
  1. SSH connection can be established
  2. Authentication succeeds
  3. Work directory exists/is writable
  4. (SLURM) Scheduler commands work

Results show success or detailed error message.

TROUBLESHOOTING:
  • Check hostname and port
  • Verify SSH key is configured
  • Ensure user has access to work directory
";

// =============================================================================
// Workflow Launcher
// =============================================================================

const WORKFLOW_LAUNCHER: &str = "\
WORKFLOW LAUNCHER

Press w from Jobs tab to launch multi-step calculation workflows.

AVAILABLE WORKFLOWS:
  Convergence     - Parameter convergence testing
  Band Structure  - Electronic band structure
  Phonon          - Vibrational properties
  EOS             - Equation of state

Select a workflow type, then configure its parameters in the following modal.

Workflows create multiple jobs that execute in order with dependencies.
";

const WORKFLOW_CONVERGENCE: &str = "\
CONVERGENCE WORKFLOW

Test how results change with computational parameters.

CONFIGURABLE PARAMETERS:
  K-points (SHRINK) - Brillouin zone sampling
  Basis set         - Wavefunction expansion
  ENCUT/ECUTWFC     - Plane-wave cutoff (VASP/QE)

WORKFLOW:
  1. Creates jobs for each parameter value
  2. Runs jobs in parallel
  3. Collects energy results
  4. Reports convergence threshold

Example: Test SHRINK = 4, 6, 8, 10, 12 to find sufficient k-point density.
";

const WORKFLOW_BAND_STRUCTURE: &str = "\
BAND STRUCTURE WORKFLOW

Calculate electronic band structure along high-symmetry paths.

STEPS:
  1. SCF calculation (ground state)
  2. Non-SCF along k-path

PATH OPTIONS:
  Auto        - Automatic path based on space group
  Cubic       - Γ-X-M-Γ-R-X
  FCC         - Γ-X-W-K-Γ-L
  Hexagonal   - Γ-M-K-Γ-A
  Custom      - Specify your own path

Requires completed SCF job as starting point.
";

const WORKFLOW_PHONON: &str = "\
PHONON WORKFLOW

Calculate vibrational properties using finite differences.

PARAMETERS:
  Supercell   - Size in each direction (e.g., 2x2x2)
  Displacement - Atom displacement magnitude (Å)

WORKFLOW:
  1. Create supercell
  2. Generate displaced configurations
  3. Calculate forces for each
  4. Compute dynamical matrix
  5. Extract phonon frequencies

Results include phonon DOS and band structure.
";

const WORKFLOW_EOS: &str = "\
EQUATION OF STATE WORKFLOW

Calculate energy vs. volume for determining bulk properties.

PARAMETERS:
  Strain range  - Min/max volume scaling
  Steps         - Number of volumes to calculate

WORKFLOW:
  1. Create structures at different volumes
  2. Run SCF for each volume
  3. Fit E(V) curve (Birch-Murnaghan)
  4. Extract bulk modulus and equilibrium volume

Results:
  • V0 - Equilibrium volume
  • B0 - Bulk modulus
  • B' - Pressure derivative
";

// =============================================================================
// Other Modals
// =============================================================================

const TEMPLATE_BROWSER: &str = "\
TEMPLATE BROWSER

Press T (Shift+t) from Jobs or Editor tab to browse calculation templates.

Templates are pre-made input files for common calculation types:
  • Basic SCF
  • Geometry optimization
  • Frequency calculation
  • Band structure
  • DOS calculation

Select a template to load it into the Editor for customization.

NAVIGATION:
  j/k     - Navigate templates
  Enter   - Load template to editor
  Tab     - Switch between list and preview
  Esc     - Close browser
";

const VASP_INPUT: &str = "\
VASP INPUT EDITOR

Press v from Jobs tab to open the multi-file VASP input editor.

TABS:
  POSCAR   - Structure definition
  INCAR    - Calculation parameters
  KPOINTS  - K-point mesh
  POTCAR   - Pseudopotential info (read-only reference)

NAVIGATION:
  1/2/3/4  - Switch between files
  Tab      - Next file
  Esc      - Close editor
  Ctrl+S   - Save changes

Each tab has its own text editor for the respective VASP input file.
";

const BATCH_SUBMISSION: &str = "\
BATCH SUBMISSION

Press B (Shift+b) from Jobs or Editor tab to submit multiple jobs at once.

WORKFLOW:
  1. Add jobs to the batch (from templates or manually)
  2. Configure common settings (cluster, resources)
  3. Review job list
  4. Submit all jobs

COMMON SETTINGS apply to all jobs:
  • Cluster selection
  • MPI ranks
  • Walltime
  • Memory
  • Partition

NAVIGATION:
  Tab         - Move between settings and job list
  a           - Add job to batch
  d           - Remove selected job
  Enter       - Submit batch
  Esc         - Cancel
";
