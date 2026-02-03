//! Help modal state management.
//!
//! This module contains the state for the hierarchical help system,
//! including topic navigation and content scrolling.

use ratatui::style::Color;
use tachyonfx::{fx, Effect, Motion};

use crate::app::AppTab;

/// Help topic identifiers for the hierarchical help system.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum HelpTopic {
    // Root level
    Overview,
    Navigation,
    KeyBindings,

    // Jobs Tab
    Jobs,
    JobsNavigation,
    JobsNewJob,
    JobsClusterConfig,
    JobsCancelJobs,
    JobsWorkflows,
    JobsSlurmQueue,

    // Editor Tab
    Editor,
    EditorBasics,
    EditorSubmit,
    EditorLsp,

    // Results Tab
    Results,
    ResultsNavigation,
    ResultsDetails,

    // Log Tab
    Log,
    LogNavigation,
    LogFollowMode,

    // Modals (context-aware)
    RecipeBrowser,
    RecipeNavigation,
    RecipeLaunching,

    MaterialsSearch,
    MaterialsFormula,
    MaterialsImportD12,
    MaterialsImportVasp,

    ClusterManager,
    ClusterAdd,
    ClusterEdit,
    ClusterTest,

    WorkflowLauncher,
    WorkflowConvergence,
    WorkflowBandStructure,
    WorkflowPhonon,
    WorkflowEos,

    TemplateBrowser,
    VaspInput,
    BatchSubmission,
}

impl HelpTopic {
    /// Get the display title for this topic.
    pub fn title(self) -> &'static str {
        match self {
            Self::Overview => "Overview",
            Self::Navigation => "Navigation",
            Self::KeyBindings => "Key Bindings",

            Self::Jobs => "Jobs Tab",
            Self::JobsNavigation => "Navigation",
            Self::JobsNewJob => "New Job",
            Self::JobsClusterConfig => "Cluster Config",
            Self::JobsCancelJobs => "Cancel Jobs",
            Self::JobsWorkflows => "Workflows",
            Self::JobsSlurmQueue => "SLURM Queue",

            Self::Editor => "Editor Tab",
            Self::EditorBasics => "Basics",
            Self::EditorSubmit => "Submit Job",
            Self::EditorLsp => "LSP Integration",

            Self::Results => "Results Tab",
            Self::ResultsNavigation => "Navigation",
            Self::ResultsDetails => "Details View",

            Self::Log => "Log Tab",
            Self::LogNavigation => "Navigation",
            Self::LogFollowMode => "Follow Mode",

            Self::RecipeBrowser => "Recipe Browser",
            Self::RecipeNavigation => "Navigation",
            Self::RecipeLaunching => "Launching Recipes",

            Self::MaterialsSearch => "Materials Search",
            Self::MaterialsFormula => "Formula Search",
            Self::MaterialsImportD12 => "Import to D12",
            Self::MaterialsImportVasp => "Import to VASP",

            Self::ClusterManager => "Cluster Manager",
            Self::ClusterAdd => "Add Cluster",
            Self::ClusterEdit => "Edit Cluster",
            Self::ClusterTest => "Test Connection",

            Self::WorkflowLauncher => "Workflow Launcher",
            Self::WorkflowConvergence => "Convergence Studies",
            Self::WorkflowBandStructure => "Band Structure",
            Self::WorkflowPhonon => "Phonon",
            Self::WorkflowEos => "EOS",

            Self::TemplateBrowser => "Template Browser",
            Self::VaspInput => "VASP Input",
            Self::BatchSubmission => "Batch Submission",
        }
    }

    /// Get child topics for hierarchical navigation.
    pub fn children(self) -> &'static [HelpTopic] {
        match self {
            Self::Overview => &[Self::Navigation, Self::KeyBindings],

            Self::Jobs => &[
                Self::JobsNavigation,
                Self::JobsNewJob,
                Self::JobsClusterConfig,
                Self::JobsCancelJobs,
                Self::JobsWorkflows,
                Self::JobsSlurmQueue,
            ],

            Self::Editor => &[Self::EditorBasics, Self::EditorSubmit, Self::EditorLsp],

            Self::Results => &[Self::ResultsNavigation, Self::ResultsDetails],

            Self::Log => &[Self::LogNavigation, Self::LogFollowMode],

            Self::RecipeBrowser => &[Self::RecipeNavigation, Self::RecipeLaunching],

            Self::MaterialsSearch => &[
                Self::MaterialsFormula,
                Self::MaterialsImportD12,
                Self::MaterialsImportVasp,
            ],

            Self::ClusterManager => &[Self::ClusterAdd, Self::ClusterEdit, Self::ClusterTest],

            Self::WorkflowLauncher => &[
                Self::WorkflowConvergence,
                Self::WorkflowBandStructure,
                Self::WorkflowPhonon,
                Self::WorkflowEos,
            ],

            // Leaf nodes have no children
            _ => &[],
        }
    }

    /// Get the parent topic, if any.
    pub fn parent(self) -> Option<HelpTopic> {
        match self {
            Self::Navigation | Self::KeyBindings => Some(Self::Overview),

            Self::JobsNavigation
            | Self::JobsNewJob
            | Self::JobsClusterConfig
            | Self::JobsCancelJobs
            | Self::JobsWorkflows
            | Self::JobsSlurmQueue => Some(Self::Jobs),

            Self::EditorBasics | Self::EditorSubmit | Self::EditorLsp => Some(Self::Editor),

            Self::ResultsNavigation | Self::ResultsDetails => Some(Self::Results),

            Self::LogNavigation | Self::LogFollowMode => Some(Self::Log),

            Self::RecipeNavigation | Self::RecipeLaunching => Some(Self::RecipeBrowser),

            Self::MaterialsFormula | Self::MaterialsImportD12 | Self::MaterialsImportVasp => {
                Some(Self::MaterialsSearch)
            }

            Self::ClusterAdd | Self::ClusterEdit | Self::ClusterTest => Some(Self::ClusterManager),

            Self::WorkflowConvergence
            | Self::WorkflowBandStructure
            | Self::WorkflowPhonon
            | Self::WorkflowEos => Some(Self::WorkflowLauncher),

            _ => None,
        }
    }

    /// Get root-level topics for the main help menu.
    pub fn root_topics() -> &'static [HelpTopic] {
        &[
            Self::Overview,
            Self::Jobs,
            Self::Editor,
            Self::Results,
            Self::Log,
            Self::RecipeBrowser,
            Self::MaterialsSearch,
            Self::ClusterManager,
            Self::WorkflowLauncher,
            Self::TemplateBrowser,
            Self::VaspInput,
            Self::BatchSubmission,
        ]
    }
}

/// Context for determining default help topic.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HelpContext {
    /// Help opened from a tab (no modal active).
    Tab(AppTab),
    /// Help opened from a specific modal.
    Modal(ModalType),
}

/// Modal types for context-aware help.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModalType {
    NewJob,
    Materials,
    ClusterManager,
    SlurmQueue,
    VaspInput,
    RecipeBrowser,
    WorkflowLauncher,
    WorkflowConfig,
    TemplateBrowser,
    BatchSubmission,
    WorkflowResults,
}

impl ModalType {
    /// Get the corresponding help topic for this modal.
    pub fn help_topic(self) -> HelpTopic {
        match self {
            Self::NewJob => HelpTopic::JobsNewJob,
            Self::Materials => HelpTopic::MaterialsSearch,
            Self::ClusterManager => HelpTopic::ClusterManager,
            Self::SlurmQueue => HelpTopic::JobsSlurmQueue,
            Self::VaspInput => HelpTopic::VaspInput,
            Self::RecipeBrowser => HelpTopic::RecipeBrowser,
            Self::WorkflowLauncher => HelpTopic::WorkflowLauncher,
            Self::WorkflowConfig => HelpTopic::WorkflowLauncher,
            Self::TemplateBrowser => HelpTopic::TemplateBrowser,
            Self::BatchSubmission => HelpTopic::BatchSubmission,
            Self::WorkflowResults => HelpTopic::JobsWorkflows,
        }
    }
}

/// Which pane of the help modal is focused.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum HelpPaneFocus {
    #[default]
    Sidebar,
    Content,
}

/// State for the hierarchical help modal.
pub struct HelpState {
    /// Whether the modal is currently active/visible.
    pub active: bool,

    /// Whether the modal is closing (for animation).
    pub closing: bool,

    /// Animation effect for open/close.
    pub effect: Option<Effect>,

    /// Breadcrumb path (current navigation hierarchy).
    pub path: Vec<HelpTopic>,

    /// Currently selected index in the sidebar.
    pub selected_index: usize,

    /// Scroll offset for the content pane.
    pub content_scroll: usize,

    /// Which pane is currently focused.
    pub focus: HelpPaneFocus,

    /// Visible topics in the sidebar (computed from path).
    visible_topics: Vec<HelpTopic>,
}

impl Default for HelpState {
    fn default() -> Self {
        Self {
            active: false,
            closing: false,
            effect: None,
            path: Vec::new(),
            selected_index: 0,
            content_scroll: 0,
            focus: HelpPaneFocus::Sidebar,
            visible_topics: HelpTopic::root_topics().to_vec(),
        }
    }
}

impl std::fmt::Debug for HelpState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("HelpState")
            .field("active", &self.active)
            .field("closing", &self.closing)
            .field("path", &self.path)
            .field("selected_index", &self.selected_index)
            .field("focus", &self.focus)
            .finish()
    }
}

impl HelpState {
    /// Open the help modal with context-aware default topic.
    pub fn open(&mut self, context: HelpContext) {
        self.active = true;
        self.closing = false;
        self.effect = Some(fx::slide_in(Motion::DownToUp, 15, 0, Color::Black, 300));

        // Reset navigation state
        self.path.clear();
        self.content_scroll = 0;
        self.focus = HelpPaneFocus::Sidebar;

        // Determine default topic based on context
        let default_topic = match context {
            HelpContext::Tab(tab) => match tab {
                AppTab::Jobs => HelpTopic::Jobs,
                AppTab::Editor => HelpTopic::Editor,
                AppTab::Results => HelpTopic::Results,
                AppTab::Log => HelpTopic::Log,
            },
            HelpContext::Modal(modal) => modal.help_topic(),
        };

        // Navigate to the default topic
        self.navigate_to(default_topic);
    }

    /// Close the help modal.
    pub fn close(&mut self) {
        self.closing = true;
        self.effect = Some(fx::slide_out(Motion::UpToDown, 15, 0, Color::Black, 300));
    }

    /// Toggle between sidebar and content focus.
    pub fn toggle_focus(&mut self) {
        self.focus = match self.focus {
            HelpPaneFocus::Sidebar => HelpPaneFocus::Content,
            HelpPaneFocus::Content => HelpPaneFocus::Sidebar,
        };
    }

    /// Select the next item (sidebar or content scroll based on focus).
    pub fn select_next(&mut self) {
        match self.focus {
            HelpPaneFocus::Sidebar => {
                if !self.visible_topics.is_empty() {
                    self.selected_index = (self.selected_index + 1) % self.visible_topics.len();
                    self.content_scroll = 0; // Reset content scroll when topic changes
                }
            }
            HelpPaneFocus::Content => {
                self.content_scroll = self.content_scroll.saturating_add(1);
            }
        }
    }

    /// Select the previous item (sidebar or content scroll based on focus).
    pub fn select_prev(&mut self) {
        match self.focus {
            HelpPaneFocus::Sidebar => {
                if !self.visible_topics.is_empty() {
                    if self.selected_index == 0 {
                        self.selected_index = self.visible_topics.len() - 1;
                    } else {
                        self.selected_index -= 1;
                    }
                    self.content_scroll = 0; // Reset content scroll when topic changes
                }
            }
            HelpPaneFocus::Content => {
                self.content_scroll = self.content_scroll.saturating_sub(1);
            }
        }
    }

    /// Scroll content pane up.
    pub fn scroll_content_up(&mut self) {
        self.content_scroll = self.content_scroll.saturating_sub(1);
    }

    /// Scroll content pane down.
    pub fn scroll_content_down(&mut self) {
        self.content_scroll = self.content_scroll.saturating_add(1);
    }

    /// Page up in content pane.
    pub fn page_up(&mut self) {
        self.content_scroll = self.content_scroll.saturating_sub(10);
    }

    /// Page down in content pane.
    pub fn page_down(&mut self) {
        self.content_scroll = self.content_scroll.saturating_add(10);
    }

    /// Enter the selected topic (drill down).
    pub fn enter_topic(&mut self) {
        if let Some(topic) = self.selected_topic() {
            let children = topic.children();
            if !children.is_empty() {
                // Has children - drill into it
                self.path.push(topic);
                self.visible_topics = children.to_vec();
                self.selected_index = 0;
                self.content_scroll = 0;
            }
            // If no children, just stay on current topic (show its content)
        }
    }

    /// Go back one level in the hierarchy.
    pub fn go_back(&mut self) {
        if self.path.is_empty() {
            // Already at root - do nothing
            return;
        }

        // Pop current level
        let popped = self.path.pop();

        // Update visible topics
        if self.path.is_empty() {
            // Back to root
            self.visible_topics = HelpTopic::root_topics().to_vec();
        } else {
            // Back to parent's children
            if let Some(parent) = self.path.last() {
                self.visible_topics = parent.children().to_vec();
            }
        }

        // Try to select the topic we just came from
        if let Some(topic) = popped {
            if let Some(idx) = self.visible_topics.iter().position(|t| *t == topic) {
                self.selected_index = idx;
            } else {
                self.selected_index = 0;
            }
        } else {
            self.selected_index = 0;
        }

        self.content_scroll = 0;
    }

    /// Go to the root of the help hierarchy.
    pub fn go_to_root(&mut self) {
        self.path.clear();
        self.visible_topics = HelpTopic::root_topics().to_vec();
        self.selected_index = 0;
        self.content_scroll = 0;
    }

    /// Get the currently selected topic.
    pub fn selected_topic(&self) -> Option<HelpTopic> {
        self.visible_topics.get(self.selected_index).copied()
    }

    /// Get the visible topics for the sidebar.
    pub fn visible_topics(&self) -> &[HelpTopic] {
        &self.visible_topics
    }

    /// Get the breadcrumb path for display.
    pub fn breadcrumb(&self) -> Vec<&'static str> {
        let mut crumbs = vec!["Help"];
        for topic in &self.path {
            crumbs.push(topic.title());
        }
        crumbs
    }

    /// Navigate directly to a specific topic (for context-aware opening).
    fn navigate_to(&mut self, target: HelpTopic) {
        // Build path from root to target
        let mut path_to_target = Vec::new();
        let mut current = Some(target);

        while let Some(topic) = current {
            if let Some(parent) = topic.parent() {
                path_to_target.push(topic);
                current = Some(parent);
            } else {
                // Reached a root-level topic
                path_to_target.push(topic);
                break;
            }
        }

        // Reverse to get path from root to target
        path_to_target.reverse();

        // Navigate through the path
        if path_to_target.is_empty() {
            return;
        }

        // Find and select the first topic at root level
        let first_topic = path_to_target[0];
        if let Some(idx) = HelpTopic::root_topics()
            .iter()
            .position(|t| *t == first_topic)
        {
            self.selected_index = idx;
        }

        // If there's a deeper path, navigate into it
        if path_to_target.len() > 1 {
            // Don't include the final topic in the path (it should be selected, not drilled into)
            for topic in &path_to_target[..path_to_target.len() - 1] {
                self.path.push(*topic);
            }

            // Set visible topics to the parent's children
            if let Some(parent) = path_to_target.get(path_to_target.len() - 2) {
                self.visible_topics = parent.children().to_vec();
            }

            // Select the target topic
            let target_topic = path_to_target[path_to_target.len() - 1];
            if let Some(idx) = self.visible_topics.iter().position(|t| *t == target_topic) {
                self.selected_index = idx;
            }
        }
    }
}
