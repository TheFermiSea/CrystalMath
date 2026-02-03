//! VASP Multi-File Input modal for creating VASP calculation jobs.
//!
//! This modal provides a tabbed interface for editing all four VASP input files:
//! - POSCAR: Atomic structure and lattice vectors
//! - INCAR: Calculation parameters (ENCUT, EDIFF, ISMEAR, etc.)
//! - KPOINTS: k-point mesh for Brillouin zone sampling
//! - POTCAR: Pseudopotential configuration (element list)

use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Tabs, Wrap};
use tui_textarea::TextArea;

use crate::app::App;
use crate::models::VaspInputFiles;

/// Active VASP file tab.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum VaspFileTab {
    #[default]
    Poscar,
    Incar,
    Kpoints,
    Potcar,
}

impl VaspFileTab {
    /// Get the display name for this tab.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Poscar => "POSCAR",
            Self::Incar => "INCAR",
            Self::Kpoints => "KPOINTS",
            Self::Potcar => "POTCAR",
        }
    }

    /// Move to the next tab (wraps around).
    pub fn next(self) -> Self {
        match self {
            Self::Poscar => Self::Incar,
            Self::Incar => Self::Kpoints,
            Self::Kpoints => Self::Potcar,
            Self::Potcar => Self::Poscar,
        }
    }

    /// Move to the previous tab (wraps around).
    pub fn prev(self) -> Self {
        match self {
            Self::Poscar => Self::Potcar,
            Self::Incar => Self::Poscar,
            Self::Kpoints => Self::Incar,
            Self::Potcar => Self::Kpoints,
        }
    }

    /// Get all tabs in order.
    pub fn all() -> &'static [VaspFileTab] {
        &[
            VaspFileTab::Poscar,
            VaspFileTab::Incar,
            VaspFileTab::Kpoints,
            VaspFileTab::Potcar,
        ]
    }
}

/// VASP Input Modal state.
#[derive(Debug)]
pub struct VaspInputState {
    /// Whether the modal is active.
    pub active: bool,

    /// Currently selected tab.
    pub current_tab: VaspFileTab,

    /// TextArea for POSCAR file.
    pub poscar_editor: TextArea<'static>,

    /// TextArea for INCAR file.
    pub incar_editor: TextArea<'static>,

    /// TextArea for KPOINTS file.
    pub kpoints_editor: TextArea<'static>,

    /// Simple text for POTCAR element configuration.
    /// Example: "Elements: Si O" or "Elements: Fe Ni Cr"
    pub potcar_config: String,

    /// Error message from validation or submission.
    pub error: Option<String>,

    /// Status message (success feedback).
    pub status: Option<String>,
}

impl Default for VaspInputState {
    fn default() -> Self {
        Self::new()
    }
}

impl VaspInputState {
    /// Create a new VASP input modal state with default templates.
    pub fn new() -> Self {
        let mut poscar_editor = TextArea::default();
        poscar_editor.set_placeholder_text("POSCAR structure file");
        poscar_editor.insert_str(Self::default_poscar_template());

        let mut incar_editor = TextArea::default();
        incar_editor.set_placeholder_text("INCAR calculation parameters");
        incar_editor.insert_str(Self::default_incar_template());

        let mut kpoints_editor = TextArea::default();
        kpoints_editor.set_placeholder_text("KPOINTS mesh configuration");
        kpoints_editor.insert_str(Self::default_kpoints_template());

        Self {
            active: false,
            current_tab: VaspFileTab::default(),
            poscar_editor,
            incar_editor,
            kpoints_editor,
            potcar_config: "Elements: ".to_string(),
            error: None,
            status: None,
        }
    }

    /// Open the modal (activate).
    pub fn open(&mut self) {
        self.active = true;
        self.current_tab = VaspFileTab::Poscar;
        self.error = None;
        self.status = None;
    }

    /// Close the modal (deactivate).
    pub fn close(&mut self) {
        self.active = false;
    }

    /// Move to the next tab.
    pub fn next_tab(&mut self) {
        self.current_tab = self.current_tab.next();
        self.error = None;
    }

    /// Move to the previous tab.
    pub fn prev_tab(&mut self) {
        self.current_tab = self.current_tab.prev();
        self.error = None;
    }

    /// Get a mutable reference to the currently active editor.
    pub fn current_editor_mut(&mut self) -> Option<&mut TextArea<'static>> {
        match self.current_tab {
            VaspFileTab::Poscar => Some(&mut self.poscar_editor),
            VaspFileTab::Incar => Some(&mut self.incar_editor),
            VaspFileTab::Kpoints => Some(&mut self.kpoints_editor),
            VaspFileTab::Potcar => None, // POTCAR uses simple string input, not TextArea
        }
    }

    /// Extract content from all editors.
    pub fn get_contents(&self) -> VaspInputFiles {
        VaspInputFiles {
            poscar: self.poscar_editor.lines().join("\n"),
            incar: self.incar_editor.lines().join("\n"),
            kpoints: self.kpoints_editor.lines().join("\n"),
            potcar_config: self.potcar_config.clone(),
        }
    }

    /// Validate the current input files.
    pub fn validate(&self) -> Result<(), String> {
        // Basic validation: ensure all files have content
        let contents = self.get_contents();

        if contents.poscar.trim().is_empty() {
            return Err("POSCAR cannot be empty".to_string());
        }

        if contents.incar.trim().is_empty() {
            return Err("INCAR cannot be empty".to_string());
        }

        if contents.kpoints.trim().is_empty() {
            return Err("KPOINTS cannot be empty".to_string());
        }

        if contents.potcar_config.trim() == "Elements:" || contents.potcar_config.trim().is_empty()
        {
            return Err("POTCAR elements must be specified".to_string());
        }

        Ok(())
    }

    /// Set an error message.
    pub fn set_error(&mut self, error: String) {
        self.error = Some(error);
        self.status = None;
    }

    /// Set a status message.
    #[allow(dead_code)]
    pub fn set_status(&mut self, status: String) {
        self.status = Some(status);
        self.error = None;
    }

    /// Clear error and status messages.
    pub fn clear_messages(&mut self) {
        self.error = None;
        self.status = None;
    }

    // ===== Default Templates =====

    /// Default POSCAR template with placeholder structure.
    fn default_poscar_template() -> &'static str {
        "Placeholder Structure\n\
         1.0          ! Universal scaling factor\n\
         5.0  0.0  0.0  ! Lattice vector a\n\
         0.0  5.0  0.0  ! Lattice vector b\n\
         0.0  0.0  5.0  ! Lattice vector c\n\
         Si           ! Element name(s)\n\
         2            ! Number of atoms per element\n\
         Direct       ! Coordinate type (Direct or Cartesian)\n\
         0.00  0.00  0.00  ! Atom 1\n\
         0.25  0.25  0.25  ! Atom 2\n"
    }

    /// Default INCAR template with common parameters.
    fn default_incar_template() -> &'static str {
        "# VASP Calculation Parameters\n\
         \n\
         # Electronic convergence\n\
         ENCUT = 520       ! Plane-wave cutoff energy (eV)\n\
         EDIFF = 1E-6      ! SCF convergence criterion\n\
         NELM = 100        ! Maximum SCF steps\n\
         \n\
         # Smearing\n\
         ISMEAR = 0        ! Gaussian smearing\n\
         SIGMA = 0.05      ! Smearing width (eV)\n\
         \n\
         # Output control\n\
         LWAVE = .FALSE.   ! Write WAVECAR\n\
         LCHARG = .FALSE.  ! Write CHGCAR\n\
         \n\
         # Parallelization\n\
         NCORE = 4         ! Number of cores per band\n"
    }

    /// Default KPOINTS template with Monkhorst-Pack mesh.
    fn default_kpoints_template() -> &'static str {
        "Automatic mesh\n\
         0              ! 0 for automatic generation\n\
         Monkhorst-Pack ! Mesh type\n\
         3  3  1        ! k-point mesh density\n\
         0  0  0        ! Mesh shift\n"
    }
}

/// Render the VASP input modal overlay.
pub fn render(frame: &mut Frame, app: &mut App) {
    let area = frame.area();

    // Dim the background
    frame.render_widget(
        Block::default().style(Style::default().bg(Color::Black)),
        area,
    );

    // Center the modal (90% width, 85% height)
    let modal_area = centered_rect(90, 85, area);

    // Clear the background
    frame.render_widget(Clear, modal_area);

    // Modal border
    let border_style = if app.vasp_input_state.error.is_some() {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Cyan)
    };

    let modal_block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(" VASP Multi-File Input ")
        .title_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(modal_block, modal_area);

    // Layout: Tabs, Editor, Status, Footer
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // Tab bar
            Constraint::Min(10),   // Main editor area
            Constraint::Length(3), // Status bar
            Constraint::Length(3), // Footer help
        ])
        .split(modal_area);

    // Render tab bar
    render_tab_bar(frame, app, chunks[0]);

    // Render editor for current tab
    render_editor_area(frame, app, chunks[1]);

    // Render status bar
    render_status_bar(frame, app, chunks[2]);

    // Render footer
    render_footer(frame, chunks[3]);
}

/// Render the tab bar showing all VASP files.
fn render_tab_bar(frame: &mut Frame, app: &App, area: Rect) {
    let titles: Vec<_> = VaspFileTab::all().iter().map(|tab| tab.name()).collect();

    let selected = VaspFileTab::all()
        .iter()
        .position(|&tab| tab == app.vasp_input_state.current_tab)
        .unwrap_or(0);

    let tabs = Tabs::new(titles)
        .block(Block::default().borders(Borders::ALL).title(" Files "))
        .select(selected)
        .style(Style::default().fg(Color::White))
        .highlight_style(
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        );

    frame.render_widget(tabs, area);
}

/// Render the main editor area for the current tab.
fn render_editor_area(frame: &mut Frame, app: &mut App, area: Rect) {
    let state = &app.vasp_input_state;
    let tab_name = state.current_tab.name();

    match state.current_tab {
        VaspFileTab::Poscar | VaspFileTab::Incar | VaspFileTab::Kpoints => {
            // Render TextArea widget
            let block = Block::default()
                .borders(Borders::ALL)
                .title(format!(" {} Editor ", tab_name))
                .title_style(Style::default().fg(Color::Cyan));

            let inner = block.inner(area);
            frame.render_widget(block, area);

            // Render the appropriate TextArea
            match state.current_tab {
                VaspFileTab::Poscar => frame.render_widget(&state.poscar_editor, inner),
                VaspFileTab::Incar => frame.render_widget(&state.incar_editor, inner),
                VaspFileTab::Kpoints => frame.render_widget(&state.kpoints_editor, inner),
                _ => unreachable!(),
            }
        }

        VaspFileTab::Potcar => {
            // Render simple text input for POTCAR config
            let cursor = "_";
            let display = format!("{}{}", state.potcar_config, cursor);

            let help_text = format!(
                "{}\n\n\
                 Help: Enter space-separated element symbols.\n\
                 Example: Elements: Si O\n\
                 Example: Elements: Fe Ni Cr",
                display
            );

            let paragraph = Paragraph::new(help_text)
                .style(Style::default().fg(Color::White))
                .block(
                    Block::default()
                        .borders(Borders::ALL)
                        .title(" POTCAR Configuration ")
                        .title_style(Style::default().fg(Color::Cyan)),
                )
                .wrap(Wrap { trim: false });

            frame.render_widget(paragraph, area);
        }
    }
}

/// Render the status bar showing current tab help or error message.
fn render_status_bar(frame: &mut Frame, app: &App, area: Rect) {
    let state = &app.vasp_input_state;

    let (text, style) = if let Some(ref error) = state.error {
        (format!("Error: {}", error), Style::default().fg(Color::Red))
    } else if let Some(ref status) = state.status {
        (status.clone(), Style::default().fg(Color::Green))
    } else {
        // Show help for current tab
        let help = match state.current_tab {
            VaspFileTab::Poscar => "Edit atomic positions and lattice vectors",
            VaspFileTab::Incar => "Configure calculation parameters (ENCUT, EDIFF, ISMEAR, etc.)",
            VaspFileTab::Kpoints => "Define k-point mesh for Brillouin zone sampling",
            VaspFileTab::Potcar => "Specify elements for pseudopotential files",
        };
        (help.to_string(), Style::default().fg(Color::DarkGray))
    };

    let paragraph = Paragraph::new(text)
        .style(style)
        .block(Block::default().borders(Borders::ALL).title(" Status "))
        .wrap(Wrap { trim: true });

    frame.render_widget(paragraph, area);
}

/// Render the footer with keyboard shortcuts.
fn render_footer(frame: &mut Frame, area: Rect) {
    let shortcuts = Line::from(vec![
        Span::styled(
            " Tab/Shift+Tab ",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Switch Files", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " Ctrl+S ",
            Style::default()
                .fg(Color::Green)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled("Submit", Style::default().fg(Color::White)),
        Span::raw("  "),
        Span::styled(
            " Esc ",
            Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
        ),
        Span::styled("Cancel", Style::default().fg(Color::White)),
    ]);

    let paragraph = Paragraph::new(shortcuts).alignment(Alignment::Center);
    frame.render_widget(paragraph, area);
}

/// Helper function to create a centered rectangle.
fn centered_rect(percent_x: u16, percent_y: u16, r: Rect) -> Rect {
    let popup_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - percent_y) / 2),
            Constraint::Percentage(percent_y),
            Constraint::Percentage((100 - percent_y) / 2),
        ])
        .split(r);

    Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - percent_x) / 2),
            Constraint::Percentage(percent_x),
            Constraint::Percentage((100 - percent_x) / 2),
        ])
        .split(popup_layout[1])[1]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_set_status_clears_error() {
        let mut state = VaspInputState::new();
        state.error = Some("boom".to_string());
        state.set_status("ok".to_string());
        assert_eq!(state.status, Some("ok".to_string()));
        assert!(state.error.is_none());
    }
}
