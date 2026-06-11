#!/bin/bash
set -e

echo "================================================================="
echo "⚡ Implementing Track 2: Editor Hotkeys & File Sync [crystalmath-j0c] ⚡"
echo "================================================================="

# Patch src/main.rs to intercept Ctrl+O and Ctrl+S inside app::AppTab::Editor
python3 -c "
with open('src/main.rs', 'r') as f:
    content = f.read()

target_block = \"\"\"        app::AppTab::Editor => {
            // Handle Ctrl+Enter for job submission (before passing to editor)\"\"\"

replacement_block = \"\"\"        app::AppTab::Editor => {
            // Handle Ctrl+S for saving file safely
            if key.code == KeyCode::Char('s') && key.modifiers.contains(KeyModifiers::CONTROL) {
                app.request_save_editor_file();
                return;
            }

            // Handle Ctrl+O for opening/reloading file layout
            if key.code == KeyCode::Char('o') && key.modifiers.contains(KeyModifiers::CONTROL) {
                app.request_open_editor_file();
                return;
            }

            // Handle Ctrl+Enter for job submission (before passing to editor)\"\"\"

if target_block in content:
    content = content.replace(target_block, replacement_block)
    with open('src/main.rs', 'w') as f:
        f.write(content)
    print('✅ Ctrl+O and Ctrl+S hotkey triggers injected into src/main.rs.')
else:
    print('⚠️ Target Editor input match block not found in src/main.rs.')
"

# Append file open/save implementation helper methods onto the end of src/app.rs
cat <<'EOF' >>src/app.rs

// --- Editor File I/O Extensions [crystalmath-j0c] ---
impl<'a> App<'a> {
    /// Serializes active text area content back to the active deck file path.
    pub fn request_save_editor_file(&mut self) {
        if let Some(ref path) = self.editor_file_path {
            let content = self.editor.lines().join("\n");
            if std::fs::write(path, content).is_ok() {
                self.mark_dirty();
            }
        }
    }

    /// Reloads content from the active file path into the editor textarea buffer.
    pub fn request_open_editor_file(&mut self) {
        if let Some(ref path) = self.editor_file_path {
            if let Ok(content) = std::fs::read_to_string(path) {
                let lines: Vec<String> = content.lines().map(String::from).collect();
                self.editor = tui_textarea::TextArea::new(lines);
                self.mark_dirty();
            }
        }
    }
}
EOF
echo "✅ App file serialization methods added to src/app.rs."

echo "================================================================="
echo "⚡ Implementing Track 3: Authoring CrystalTaskDoc [crystalmath-u94.2] ⚡"
echo "================================================================="
# Create the parser schema for CRYSTAL23 calculations inside your code module space
mkdir -p python/crystalmath/codes/crystal23
cat <<'EOF' >python/crystalmath/codes/crystal23/parser.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class CrystalTaskDoc(BaseModel):
    """
    Structured emmet-pattern documentation parser schema for CRYSTAL23 output files.
    Resolves crystalmath-u94.2.
    """
    energy: Optional[float] = Field(None, description="Total final electronic energy in Hartree")
    spin_density: Optional[float] = Field(None, description="Calculated spin density value")
    is_converged: bool = Field(False, description="True if self-consistent field cycle converged successfully")
    geometry_history: List[Dict[str, Any]] = Field(default_factory=list, description="List of intermediate geometric configurations")

    @classmethod
    def from_output_string(cls, output_text: str) -> "CrystalTaskDoc":
        """Parses a raw CRYSTAL23 text block stream into a structured TaskDoc framework."""
        doc = cls(energy=None, spin_density=None, is_converged=False, geometry_history=[])
        
        for line in output_text.splitlines():
            if "TOTAL ENERGY" in line or "FINAL ENERGY" in line:
                try:
                    doc.energy = float(line.split()[-1])
                except (ValueError, IndexError):
                    pass
            if "SCF ENDED - CONVERGENCE ACHIEVED" in line:
                doc.is_converged = True
                
        return doc
EOF
echo "✅ Authored CrystalTaskDoc scientific data schema successfully."

echo "================================================================="
echo "🔍 Running Workspace-Wide Sanity Check Suite..."
echo "================================================================="
cargo clippy --all-targets
