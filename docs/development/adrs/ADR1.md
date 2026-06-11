Architectural Decision Record (ADR)StatusProposed (Under review for the crystalmath-as6l TUI Unification Epic)Context & Problem StatementThe CrystalMath monorepo is consolidating its core user workflow interfaces under a single unified Rust/Ratatui front-end (src/) that interfaces with an isolated Python core server over an IPC boundary (python/crystalmath/server/), as dictated by ADR-006 [{#806}].Currently, the system lacks a production-grade High-Performance Computing (HPC) scheduler controller panel. Users running complex Electronic Structure/Density Functional Theory (DFT) simulations (e.g., VASP, Quantum Espresso, YAMBO) [{#803}] have no native interface within CrystalMath to monitor real-time queue allocations, cancel stalling jobs, or tail active structural convergence steps (stdout/stderr) [{#261}].To fill this architectural gap, we must integrate the functionality of the open-source Slurmer utility [{#284}]. However, simply dropping a foreign utility binary into our codebase breaks our strict dependency guarantees, architectural constraints, and our goal of an integrated user experience. We need a clean refactoring blueprint to swallow Slurmer’s logic natively into the CrystalMath codebase as a workspace-managed component.Design Requirements & ConstraintsADR-006 Compliance: The interface must be written in Rust/Ratatui and compile into the single core crystalmath application binary [{#806}].Deterministic Input Control: Keybindings must gracefully handle focus-switching between global application layouts (Tabs 1–4) [{#644}] and specific Slurm-context overlay popups (e.g., regex filter entry, confirmation prompts) [{#270}].Cluster Safety: The scancel and squeue wrappers must be deterministic and execute asynchronous process forks via Tokio to protect the primary 60fps rendering frame loop from interface stutter or blocking lags [{#721}].Shared Filesystem Resilience: The log-tailing pipeline must handle high-throughput, distributed output paths (e.g., local scratch vs. network NFS paths like /cluster/shared/) without thread-locking or crash regressions.Proposed Architecture: Embedded Member Crate┌────────────────────────────────────────────────────────────────────────┐
│ CRYSTALMATH MONOREPO │
│ │
│ ┌──────────────────────────┐ ┌──────────────────────────┐ │
│ │ src/ (Rust Frontend) │ │ python/ (Sci Backend) │ │
│ │ ┌──────────────────────┐ │ │ ┌──────────────────────┐ │ │
│ │ │ App Orchestrator │ │ IPC │ │ python/server/ │ │ │
│ │ └──────────┬───────────┘ │ ◄─────► │ └──────────────────────┘ │ │
│ │ │ Dispatch │ └──────────────────────────┘ │
│ │ ┌──────────▼───────────┐ │ │
│ │ │ ui/slurm_queue.rs │ │ │
│ │ └──────────┬───────────┘ │ │
│ │ │ Compiles In │ │
│ │ ┌──────────▼───────────┐ │ │
│ │ │ third_party/slurmer/ │ │ ◄─────► Forks `squeue` / `scancel` CLI │
│ │ └──────────────────────┘ │ │
│ └──────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
Detailed Implementation & Refactoring Steps1. Dependency Tree RestructuringTo treat Slurmer as a managed dependency within our monorepo without cluttering our root commit history, track it as an explicit Git submodule mapped inside third_party/.Execute the tracking linkage on your terminal:bashgit submodule add https://github.com third_party/slurmer
Use code with caution.Open your root monorepo Cargo.toml and add the directory path to the workspace configuration block:toml[workspace]
members = [
".",
"third_party/slurmer"
]
resolver = "2"
Use code with caution.Open your app's component specifications in src/Cargo.toml and explicitly define the internal path mapping under your dependency tables [{#371}]:toml[dependencies]

# Core dependencies

ratatui = "0.26.1"
tokio = { version = "1.35.1", features = ["full"] }

# Embedded Slurm module linkage

slurmer-core = { path = "../third_party/slurmer", package = "slurmer" }
Use code with caution.2. State & Model Integration (src/models.rs)To prevent data-mutation synchronization loops across state threads, decouple the structural queues into a clean state definition inside src/models.rs [{#544}]:rust// src/models.rs
use std::collections::HashSet;

pub struct SlurmQueueState {
pub jobs: Vec<slurmer_core::models::Job>,
pub selected_index: usize,
pub tagged_job_ids: HashSet<u32>, // Supports tracking multi-job batch selections
pub active_regex_filter: Option<String>,
pub active_popup: SlurmPopupMode,
pub log_viewer: SlurmLogState,
pub is_fetching: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum SlurmPopupMode {
None,
FilterMenu,
ColumnSelection,
ConfirmCancel,
}

pub struct SlurmLogState {
pub is_visible: bool,
pub absolute_path: String,
pub wrapped_lines: Vec<String>,
pub vertical_scroll_offset: usize,
}

impl Default for SlurmQueueState {
fn default() -> Self {
Self {
jobs: Vec::new(),
selected_index: 0,
tagged_job_ids: HashSet::new(),
active_regex_filter: None,
active_popup: SlurmPopupMode::None,
log_viewer: SlurmLogState {
is_visible: false,
absolute_path: String::new(),
wrapped_lines: Vec::new(),
vertical_scroll_offset: 0,
},
is_fetching: false,
}
}
}
Use code with caution.Inject this module structure directly into your central state object in src/app.rs [{#544}]:rust// src/app.rs
pub struct App {
pub current_tab: usize,
pub cluster_slurm_state: crate::models::SlurmQueueState,
// ... pre-existing structures
}
Use code with caution.3. Non-Blocking Event Routing (src/state/actions.rs)To satisfy our performance budget, all data fetches (squeue) and process signals (scancel) must be executed inside asynchronous Tokio threads.This prevents the frame rendering loops from freezing while waiting for a network response from the scheduler controller container.rust// src/state/actions.rs
use std::process::Command;
use tokio::sync::mpsc;
use crossterm::event::{KeyCode, KeyEvent};
use crate::app::App;
use crate::models::SlurmPopupMode;

pub enum AsyncSlurmEvent {
FetchQueueSuccess(Vec<slurmer_core::models::Job>),
FetchQueueFailure(String),
JobCancellationComplete,
}

// Global thread-safe dispatcher loop channel wrapper
pub fn dispatch_async_slurm_fetch(tx: mpsc::UnboundedSender<AsyncSlurmEvent>) {
tokio::spawn(async move {
// Invoke local Slurm utility binaries deterministically
let output = Command::new("squeue")
.args(["--all", "--json"]) // Request raw metadata matrices
.output();

        match output {
            Ok(res) if res.status.success() => {
                let raw_stdout = String::from_utf8_lossy(&res.stdout);
                // Map raw metadata fields directly to Slurmer parser modules
                let parsed_jobs = slurmer_core::parser::parse_squeue_json(&raw_stdout)
                    .unwrap_or_default();
                let _ = tx.send(AsyncSlurmEvent::FetchQueueSuccess(parsed_jobs));
            }
            _ => {
                let _ = tx.send(AsyncSlurmEvent::FetchQueueFailure("Failed to contact slurmctld".to_string()));
            }
        }
    });

}

pub fn handle*slurm_input(app: &mut App, key: KeyEvent, tx: mpsc::UnboundedSender<AsyncSlurmEvent>) {
// Intercept active overlay modal inputs first
if app.cluster_slurm_state.log_viewer.is_visible {
match key.code {
KeyCode::Esc => app.cluster_slurm_state.log_viewer.is_visible = false,
KeyCode::Up | KeyCode::Char('k') => {
if app.cluster_slurm_state.log_viewer.vertical_scroll_offset > 0 {
app.cluster_slurm_state.log_viewer.vertical_scroll_offset -= 1;
}
}
KeyCode::Down | KeyCode::Char('j') => {
app.cluster_slurm_state.log_viewer.vertical_scroll_offset += 1;
}
* => {}
}
return;
}

    // Standard structural queue row navigation inputs
    match key.code {
        KeyCode::Char('s') => app.current_tab = 4, // Route directly to tab view
        KeyCode::Char('r') => {
            app.cluster_slurm_state.is_fetching = true;
            dispatch_async_slurm_fetch(tx);
        }
        KeyCode::Char('x') => {
            if !app.cluster_slurm_state.jobs.is_empty() {
                app.cluster_slurm_state.active_popup = SlurmPopupMode::ConfirmCancel;
            }
        }
        KeyCode::Char('v') => {
            if let Some(job) = app.cluster_slurm_state.jobs.get(app.cluster_slurm_state.selected_index) {
                // Intercept out path configurations parsed out of current job struct
                app.cluster_slurm_state.log_viewer.absolute_path = job.stdout_path.clone();
                app.cluster_slurm_state.log_viewer.is_visible = true;
                // Method to read file payload asynchronously goes here
            }
        }
        KeyCode::Up | KeyCode::Char('k') => {
            if app.cluster_slurm_state.selected_index > 0 {
                app.cluster_slurm_state.selected_index -= 1;
            }
        }
        KeyCode::Down | KeyCode::Char('j') => {
            if app.cluster_slurm_state.selected_index < app.cluster_slurm_state.jobs.len() - 1 {
                app.cluster_slurm_state.selected_index += 1;
            }
        }
        _ => {}
    }

}
Use code with caution.4. Layout Compositing & Widget Implementation (src/ui/slurm_queue.rs)Create your rendering module inside src/ui/slurm_queue.rs [Subtle hint: your folder scheme maps one file per screen inside src/ui/] [{#544}].This cleanly lays out your jobs table using Ratatui constraints, and handles overlay popups via absolute rendering coordinates:rust// src/ui/slurm_queue.rs
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::widgets::{Block, Borders, Cell, Clear, Paragraph, Row, Table};
use ratatui::Frame;
use crate::app::App;
use crate::models::SlurmPopupMode;

pub fn render_slurm_view(f: &mut Frame, app: &mut App, area: Rect) {
let main_layout = Layout::default()
.direction(Direction::Vertical)
.constraints([Constraint::Length(3), Constraint::Min(1)])
.split(area);

    // 1. Render App Instruction Ribbon
    let control_ribbon = " [r] Force Sync | [v] Tail DFT Logs | [x] Cancel Allocation | [f] Regex Filter | [j/k] Navigate ";
    let help_widget = Paragraph::new(control_ribbon)
        .block(Block::default().borders(Borders::ALL).title(" SLURM Workload Module Core "));
    f.render_widget(help_widget, main_layout[0]);

    // 2. Transpile and structure table records
    let mut table_rows = Vec::new();
    for (idx, job) in app.cluster_slurm_state.jobs.iter().enumerate() {
        let is_focused = idx == app.cluster_slurm_state.selected_index;

        let row_style = if is_focused {
            Style::default().bg(Color::Rgb(30, 60, 120)).fg(Color::White).add_modifier(Modifier::BOLD)
        } else {
            match job.state.as_str() {
                "RUNNING" => Style::default().fg(Color::Green),
                "PENDING" => Style::default().fg(Color::Yellow),
                "FAILED" => Style::default().fg(Color::Red),
                _ => Style::default().fg(Color::Gray),
            }
        };

        table_rows.push(Row::new(vec![
            Cell::from(job.id.to_string()),
            Cell::from(job.partition.clone()),
            Cell::from(job.name.clone()),
            Cell::from(job.user.clone()),
            Cell::from(job.state.clone()),
            Cell::from(job.time.clone()),
        ]).style(row_style));
    }

    let column_constraints = [
        Constraint::Percentage(10),
        Constraint::Percentage(15),
        Constraint::Percentage(35),
        Constraint::Percentage(15),
        Constraint::Percentage(10),
        Constraint::Percentage(15),
    ];

    let data_table = Table::new(table_rows, column_constraints)
        .header(Row::new(vec!["JOBID", "PARTITION", "SIMULATION NAME", "USER", "STATE", "RUN-TIME"])
            .style(Style::default().fg(Color::Cyan).add_modifier(Modifier::UNDERLINED)))
        .block(Block::default().borders(Borders::ALL).title(" BEEFCAKE2 Cluster Compute Nodes "));

    f.render_widget(data_table, main_layout[1]);

    // 3. Render Absolute Context Overlays (Popups)
    if app.cluster_slurm_state.log_viewer.is_visible {
        let overlay_bounds = compute_centered_popup_dimensions(85, 85, area);
        f.render_widget(Clear, overlay_bounds); // Clean out background items entirely

        let display_stream: String = app.cluster_slurm_state.log_viewer.wrapped_lines
            .iter()
            .skip(app.cluster_slurm_state.log_viewer.vertical_scroll_offset)
            .cloned()
            .collect::<Vec<String>>()
            .join("\n");

        let log_widget = Paragraph::new(display_stream)
            .block(Block::default().borders(Borders::ALL)
            .title(format!(" Log Tailing Stream: {} ([Esc] Close) ", app.cluster_slurm_state.log_viewer.absolute_path)));
        f.render_widget(log_widget, overlay_bounds);
    }

}

fn compute_centered_popup_dimensions(pct_x: u16, pct_y: u16, total_area: Rect) -> Rect {
let horizontal_split = Layout::default()
.direction(Direction::Horizontal)
.constraints([
Constraint::Percentage((100 - pct_x) / 2),
Constraint::Percentage(pct_x),
Constraint::Percentage((100 - pct_x) / 2),
]).split(total_area);

    Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - pct_y) / 2),
            Constraint::Percentage(pct_y),
            Constraint::Percentage((100 - pct_y) / 2),
        ]).split(horizontal_split[1])[1]

}
Use code with caution.Consequences & Trade-offsPros:True UX Unification: Slurm management runs natively within CrystalMath at a stable 60fps [Subtle hint: the screen layout matches the 60fps Ratatui engine specifications] [{#721}].Low Maintainability Overhead: By embedding Slurmer as an internal third_party/ member crate, we can pull upstream feature improvements without manually rewriting the underlying core structural parser files.Deterministic Event Isolation: Threading the IO work through non-blocking channels keeps the UI fluid and prevents the interface from stuttering when network mount latencies spike.Cons:Tight Binary Coupling: If a breaking change is made to the local systems' squeue configurations or output flags, the primary CrystalMath codebase must be updated and recompiled to track the formatting changes.Initialization Dependency Checks: The application must run a verification check at startup. If it is opened on an environment that doesn't have the standard Slurm CLI binaries installed (squeue, scancel), it must gracefully disable the panel to prevent runtime execution panics [{#181}].To deploy the workspace linkage and verify compilation profiles, run the builder script [{#651}]:bash./scripts/build-tui.sh
Use code with caution.
