# LSP Integration: dft-language-server

Your project includes a robust DFT Language Server (`dft-language-server`, formerly `vasp-language-server`). This server now supports **both VASP and CRYSTAL23** input files, providing real-time error checking in the terminal.

## Current Implementation Status

The LSP server (v1.1.0) has been upgraded with full CRYSTAL23 support:

### Supported File Types

| Code | Files | Features |
|------|-------|----------|
| VASP | INCAR, POSCAR, KPOINTS, POTCAR | Validation, completion, hover docs |
| CRYSTAL23 | `.d12` | Parsing, validation, completion, hover, semantic tokens |

### CRYSTAL23 Features Implemented

- **Tokenizer & Parser** (`features/crystal/parsing.ts`) - Full `.d12` file parsing
- **Validation/Linting** (`features/crystal/linting.ts`) - Space group validation (1-230 for CRYSTAL, 1-80 for SLAB), SHRINK/TOLINTEG/FMIXING checks
- **Completions** (`features/crystal/completion.ts`) - Keyword completions with documentation
- **Hover Documentation** (`features/crystal/hover.ts`) - Inline docs for keywords
- **Semantic Tokens** (`features/crystal/semantic-tokens.ts`) - Syntax highlighting
- **Tag Dictionary** (`data/crystal-tags.ts`) - 50+ CRYSTAL23 keywords with metadata

### Architecture

```
dft-language-server/
├── src/
│   ├── core/
│   │   ├── document-cache.ts    # CrystalDocument type support
│   │   └── lsp-server.ts        # CRYSTAL23 dispatch routing
│   ├── data/
│   │   ├── vasp-tags.ts         # VASP keyword definitions
│   │   └── crystal-tags.ts      # 50+ CRYSTAL23 keywords
│   └── features/
│       ├── crystal/             # NEW: Complete CRYSTAL23 module
│       │   ├── index.ts
│       │   ├── parsing.ts       # Tokenizer for .d12 files
│       │   ├── linting.ts       # Validation (space groups, SHRINK, etc.)
│       │   ├── completion.ts    # Keyword completions
│       │   ├── hover.ts         # Documentation on hover
│       │   └── semantic-tokens.ts
│       ├── incar/
│       ├── poscar/
│       ├── kpoints/
│       └── potcar/
└── package.json                 # name=dft-language-server
```

## 1. Rust LSP Client (`src/lsp.rs`)

We need a dedicated client struct to manage the child process (Node.js) and communicate via JSON-RPC over Standard I/O.

```rust
use std::process::{Command, Stdio, Child, ChildStdin};
use std::io::{Write, BufRead, BufReader};
use std::sync::mpsc::Sender;
use std::thread;
use serde_json::json;
use serde::{Deserialize, Serialize};

/// Supported DFT code types for language detection
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum DftCodeType {
    Crystal,  // .d12 files
    Vasp,     // INCAR, POSCAR, KPOINTS, POTCAR
}

impl DftCodeType {
    pub fn language_id(&self) -> &'static str {
        match self {
            DftCodeType::Crystal => "crystal",
            DftCodeType::Vasp => "vasp",
        }
    }
    
    pub fn from_filename(name: &str) -> Option<Self> {
        if name.ends_with(".d12") {
            Some(DftCodeType::Crystal)
        } else if matches!(name, "INCAR" | "POSCAR" | "KPOINTS" | "POTCAR") {
            Some(DftCodeType::Vasp)
        } else {
            None
        }
    }
}

#[derive(Debug)]
pub enum LspEvent {
    Diagnostics(String, Vec<Diagnostic>),  // (uri, diagnostics)
    ServerReady,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Diagnostic {
    pub range: Range,
    pub message: String,
    pub severity: Option<i32>,
    pub source: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Range {
    pub start: Position,
    pub end: Position,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Position {
    pub line: u32,
    pub character: u32,
}

pub struct LspClient {
    stdin: ChildStdin,
    request_id: i32,
}

impl LspClient {
    /// Spawns the Node.js LSP server and starts a reader thread.
    pub fn start(server_path: &str, event_tx: Sender<LspEvent>) -> anyhow::Result<Self> {
        let mut child = Command::new("node")
            .arg(server_path)
            .arg("--stdio")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()?;

        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();

        // Spawn a thread to read stdout from the LSP server
        thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                // 1. Read Headers (Content-Length: ...)
                let mut size = 0;
                let mut header = String::new();
                if reader.read_line(&mut header).unwrap() == 0 {
                    break;
                }
                
                if header.starts_with("Content-Length: ") {
                    let size_str = header.trim().trim_start_matches("Content-Length: ");
                    size = size_str.parse::<usize>().unwrap_or(0);
                }
                
                // Read empty line separator
                reader.read_line(&mut String::new()).unwrap();

                // 2. Read Body
                let mut body_buf = vec![0; size];
                reader.read_exact(&mut body_buf).unwrap();
                let body_str = String::from_utf8(body_buf).unwrap();
                
                // 3. Parse JSON
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&body_str) {
                    // Check for "textDocument/publishDiagnostics"
                    if json["method"] == "textDocument/publishDiagnostics" {
                        let uri = json["params"]["uri"].as_str().unwrap_or("").to_string();
                        if let Ok(diags) = serde_json::from_value::<Vec<Diagnostic>>(
                            json["params"]["diagnostics"].clone()
                        ) {
                            event_tx.send(LspEvent::Diagnostics(uri, diags)).unwrap();
                        }
                    }
                }
            }
        });

        // Send 'initialize' request immediately
        let mut client = LspClient { stdin, request_id: 0 };
        client.initialize();
        Ok(client)
    }

    fn next_id(&mut self) -> i32 {
        self.request_id += 1;
        self.request_id
    }

    fn initialize(&mut self) {
        let req = json!({
            "jsonrpc": "2.0",
            "id": self.next_id(),
            "method": "initialize",
            "params": {
                "processId": std::process::id(),
                "rootUri": null,
                "capabilities": {
                    "textDocument": {
                        "publishDiagnostics": { "relatedInformation": true },
                        "completion": { "completionItem": { "snippetSupport": true } },
                        "hover": { "contentFormat": ["markdown", "plaintext"] }
                    }
                }
            }
        });
        self.send(&req);
    }

    /// Open a document with automatic language detection
    pub fn did_open(&mut self, file_name: &str, text: &str) {
        let lang_id = DftCodeType::from_filename(file_name)
            .map(|t| t.language_id())
            .unwrap_or("plaintext");
            
        let notification = json!({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": format!("file:///{}", file_name),
                    "languageId": lang_id,
                    "version": 1,
                    "text": text
                }
            }
        });
        self.send(&notification);
    }

    pub fn did_change(&mut self, file_name: &str, version: i32, text: &str) {
        let notification = json!({
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {
                    "uri": format!("file:///{}", file_name),
                    "version": version
                },
                "contentChanges": [{"text": text}]
            }
        });
        self.send(&notification);
    }

    fn send(&mut self, json: &serde_json::Value) {
        let msg = json.to_string();
        let req = format!("Content-Length: {}\r\n\r\n{}", msg.len(), msg);
        self.stdin.write_all(req.as_bytes()).unwrap();
        self.stdin.flush().unwrap();
    }
}
```

## 2. Integration with TUI App (`src/app.rs` update)

Update the App struct to support multiple DFT codes:

```rust
use crate::lsp::{LspClient, LspEvent, DftCodeType};

pub struct App<'a> {
    // ... existing fields ...
    
    // Editor State - now with DFT code awareness
    pub editor: TextArea<'a>,
    pub editor_file_path: Option<String>,
    pub editor_dft_code: Option<DftCodeType>,
    pub editor_version: i32,
    pub lsp_diagnostics: Vec<crate::lsp::Diagnostic>,
    
    // LSP Client
    pub lsp_client: Option<LspClient>,
    pub lsp_receiver: std::sync::mpsc::Receiver<LspEvent>,
}

impl<'a> App<'a> {
    pub fn new(py_controller: pyo3::PyObject) -> Self {
        let (tx, rx) = std::sync::mpsc::channel();
        
        // Path to dft-language-server
        let lsp_path = "./dft-language-server/out/server.js"; 
        let client = LspClient::start(lsp_path, tx).ok();
        
        // ... rest of initialization ...
    }
    
    /// Open a file in the editor with LSP support
    pub fn open_file(&mut self, path: &str, content: &str) {
        self.editor = TextArea::from(content.lines());
        self.editor_file_path = Some(path.to_string());
        self.editor_dft_code = DftCodeType::from_filename(path);
        self.editor_version = 1;
        
        if let Some(client) = &mut self.lsp_client {
            client.did_open(path, content);
        }
    }
    
    /// Notify LSP of editor changes
    pub fn on_editor_change(&mut self) {
        if let (Some(client), Some(path)) = (&mut self.lsp_client, &self.editor_file_path) {
            self.editor_version += 1;
            let content = self.editor.lines().join("\n");
            client.did_change(path, self.editor_version, &content);
        }
    }
}
```

## 3. Main Loop Integration (`src/main.rs`)

```rust
// In main loop
loop {
    terminal.draw(|f| ui::render(f, &mut app))?;

    // Poll LSP events (non-blocking)
    while let Ok(event) = app.lsp_receiver.try_recv() {
        match event {
            LspEvent::Diagnostics(uri, diags) => {
                // Only update if diagnostics are for current file
                if app.editor_file_path.as_ref().map(|p| uri.ends_with(p)).unwrap_or(false) {
                    app.lsp_diagnostics = diags;
                }
            },
            LspEvent::ServerReady => {
                // Re-open current file if any
                if let Some(path) = &app.editor_file_path.clone() {
                    let content = app.editor.lines().join("\n");
                    if let Some(client) = &mut app.lsp_client {
                        client.did_open(path, &content);
                    }
                }
            }
        }
    }

    // Handle Input
    if event::poll(Duration::from_millis(16))? {
        if let Event::Key(key) = event::read()? {
            match key.code {
                KeyCode::Char('q') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                    app.should_quit = true;
                },
                KeyCode::Tab => app.next_tab(),
                _ => {
                    if let app::AppTab::Editor = app.current_tab {
                        let changed = app.editor.input(key);
                        if changed {
                            app.on_editor_change();
                        }
                    }
                }
            }
        }
    }

    if app.should_quit {
        break;
    }
}
```

## 4. Rendering Diagnostics (`src/ui.rs`)

Enhanced rendering with DFT code awareness:

```rust
fn render_editor(f: &mut Frame, app: &mut App, area: Rect) {
    // Apply styles based on diagnostics
    app.editor.set_style(Style::default()); 
    
    for diag in &app.lsp_diagnostics {
        let line_idx = diag.range.start.line as usize;
        
        // Determine color based on severity (1=Error, 2=Warning, 3=Info, 4=Hint)
        let color = match diag.severity.unwrap_or(1) {
            1 => Color::Red,
            2 => Color::Yellow,
            3 => Color::Blue,
            _ => Color::Cyan,
        };
        
        // Highlight the specific line
        app.editor.set_line_style(line_idx, Style::default().bg(color));
    }

    // Dynamic title based on file type
    let title = match app.editor_dft_code {
        Some(DftCodeType::Crystal) => "CRYSTAL23 Input Editor (.d12)",
        Some(DftCodeType::Vasp) => "VASP Input Editor",
        None => "Input Editor",
    };
    
    let diag_count = app.lsp_diagnostics.len();
    let title_with_status = if diag_count > 0 {
        format!("{} [{} issues]", title, diag_count)
    } else {
        format!("{} [✓]", title)
    };

    let mut widget = app.editor.widget();
    widget.set_block(
        Block::default()
            .borders(Borders::ALL)
            .title(title_with_status)
    );
    f.render_widget(widget, area);
}
```

## 5. CRYSTAL23 Validation Examples

The LSP now provides these validations for `.d12` files:

```
# Space group validation
CRYSTAL
0 0 0
300        # Error: Space group must be 1-230 for CRYSTAL

# SHRINK validation  
SHRINK
8          # Warning: SHRINK requires 2 arguments (IS and IP)

# Geometry type validation
SLAB
0 0 0
85         # Error: Layer group must be 1-80 for SLAB

# Typo suggestions (Levenshtein-based)
SHRNK      # Warning: Unknown keyword. Did you mean 'SHRINK'?
```
