//! Action types for MVU/Reducer pattern.
//!
//! This module defines the action types that drive state transitions in the application.
//! All state mutations should be triggered via `App::update(action)` to make
//! transitions explicit and testable.

// =============================================================================
// MVU/Reducer Pattern: Action Enum
// =============================================================================

/// Actions that can modify application state.
///
/// This enum represents all possible state transitions in the application,
/// following the MVU (Model-View-Update) / reducer pattern. All state
/// mutations should be triggered via `App::update(action)` to make
/// transitions explicit and testable.
#[derive(Debug, Clone, PartialEq)]
#[allow(dead_code)] // Public API for MVU pattern; used by callers
pub enum Action {
    // ===== Tab Navigation =====
    /// Move to the next tab.
    TabNext,
    /// Move to the previous tab.
    TabPrev,
    /// Set the current tab directly.
    TabSet(AppTab),

    // ===== Jobs Tab =====
    /// Select the next job in the list.
    JobSelectNext,
    /// Select the previous job in the list.
    JobSelectPrev,
    /// Select the first job.
    JobSelectFirst,
    /// Select the last job.
    JobSelectLast,
    /// View logs for the selected job.
    JobViewLog,
    /// Request to cancel the selected job (two-key confirmation).
    JobCancelRequest,
    /// Request diff comparison for the selected job.
    JobDiffRequest,
    /// Request job list refresh.
    JobsRefresh,
    /// Request sync with remote clusters (squeue/sacct).
    JobsSync,

    // ===== Results Tab =====
    /// Scroll results view up by one line.
    ResultsScrollUp,
    /// Scroll results view down by one line.
    ResultsScrollDown,
    /// Scroll results view up by one page.
    ResultsPageUp,
    /// Scroll results view down by one page.
    ResultsPageDown,

    // ===== Log Tab =====
    /// Scroll log view up by one line.
    LogScrollUp,
    /// Scroll log view down by one line.
    LogScrollDown,
    /// Scroll log view up by one page.
    LogPageUp,
    /// Scroll log view down by one page.
    LogPageDown,
    /// Scroll log view to top.
    LogScrollTop,
    /// Scroll log view to bottom.
    LogScrollBottom,
    /// Toggle log follow mode.
    LogToggleFollow,

    // ===== Editor Tab =====
    /// Request job submission from editor content (two-key confirmation).
    EditorSubmitRequest,

    // ===== SLURM =====
    /// Toggle SLURM queue view visibility.
    SlurmToggle,

    // ===== Materials Modal =====
    /// Open the materials search modal.
    MaterialsOpen,
    /// Close the materials search modal.
    MaterialsClose,
    /// Submit a materials search.
    MaterialsSearch,
    /// Generate D12 for selected material.
    MaterialsGenerateD12,
    /// Select next material in results.
    MaterialsSelectNext,
    /// Select previous material in results.
    MaterialsSelectPrev,

    // ===== General =====
    /// Clear the current error message.
    ErrorClear,
    /// Request application quit.
    Quit,
}

// =============================================================================
// Diff Line Type
// =============================================================================

/// Diff line type for job comparison.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[allow(dead_code)] // Planned for job diff feature
pub enum DiffLineType {
    /// Line is the same in both files.
    Same,
    /// Line was added (only in right/compare job).
    Added,
    /// Line was removed (only in left/base job).
    Removed,
    /// Line was modified (different in both).
    Modified,
}

// =============================================================================
// Application Tabs
// =============================================================================

/// Application tabs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppTab {
    Jobs,
    Editor,
    Results,
    Log,
}

impl AppTab {
    /// Get tab display name.
    pub fn name(&self) -> &'static str {
        match self {
            AppTab::Jobs => "Jobs",
            AppTab::Editor => "Editor",
            AppTab::Results => "Results",
            AppTab::Log => "Log",
        }
    }

    /// Get all tabs in order.
    pub fn all() -> &'static [AppTab] {
        &[AppTab::Jobs, AppTab::Editor, AppTab::Results, AppTab::Log]
    }
}
