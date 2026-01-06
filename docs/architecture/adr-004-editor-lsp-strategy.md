# ADR-004: Editor/LSP Strategy - Upstream Integration Only

**Status:** Accepted
**Date:** 2026-01-06
**Deciders:** Project maintainers
**Depends on:** ADR-001, ADR-002

## Context

The project previously considered building custom LSP functionality for DFT input validation. This would involve maintaining parsers, semantic analysis, and diagnostic generation for CRYSTAL23, VASP, and Quantum Espresso input formats.

The upstream `dft-language-server` (bundled in `third_party/vasp-language-server`) already provides:
- VASP INCAR/POSCAR/KPOINTS validation
- CRYSTAL23 .d12 parsing (planned)
- VS Code extension

Maintaining a parallel LSP implementation adds significant maintenance burden for limited benefit.

## Decision

### 1. No Custom LSP Implementation

**Scope limitation:**
- Do NOT implement custom parsers for DFT input validation
- Do NOT duplicate upstream diagnostic logic
- The current `src/lsp.rs` is a **thin client wrapper** only

**Current `lsp.rs` scope (retained):**
- Spawns upstream LSP server process
- JSON-RPC communication over stdio
- Translates LSP events to UI updates
- No semantic parsing or validation logic

### 2. Upstream LSP as Single Source

**Server discovery (in order):**

| Priority | Source | Path |
|----------|--------|------|
| 1 | Environment | `CRYSTAL_TUI_LSP_PATH` |
| 2 | Bundled | `third_party/vasp-language-server/out/server.js` |
| 3 | Global | `vasp-lsp` or `dft-lsp` CLI on PATH |

**Installation methods:**

```bash
# Option A: Global install (npm)
npm install -g dft-language-server

# Option B: Build bundled (development)
cd third_party/vasp-language-server
npm install && npm run build
```

### 3. External Editor Workflow

For users who need full editing capabilities beyond the embedded editor:

**Recommended workflow:**

1. **Export input file** to working directory
2. **Edit with external editor** (VS Code, Neovim, etc.) with LSP support
3. **Re-import** or monitor file for changes

**VS Code integration:**

```bash
# Install the VS Code extension
code --install-extension dft-lsp.vasp-language-features
```

**Neovim integration:**

```lua
-- In lua/lspconfig.lua or init.lua
require('lspconfig').vasp_ls.setup{}
```

### 4. Embedded Editor Scope (Rust TUI)

The Rust TUI's embedded editor (`tui-textarea`) is **minimal by design**:

| Feature | Status | Notes |
|---------|--------|-------|
| Basic editing | ✅ | Insert, delete, navigation |
| Line numbers | ✅ | Display only |
| Diagnostics overlay | ✅ | From upstream LSP |
| Syntax highlighting | ❌ | Not implemented |
| Auto-completion | ❌ | Not planned |
| Go-to-definition | ❌ | Not planned |
| Refactoring | ❌ | Not planned |

**Rationale:** Full IDE features are better served by external editors with native LSP support.

### 5. Python TUI Editor (Future)

Per ADR-001, Python TUI is primary. If advanced editing is needed:

- Use Textual's native text input widgets
- Connect to upstream LSP via subprocess
- Same "thin client" pattern as Rust TUI

## Consequences

### Positive
- **Reduced maintenance**: No custom parser upkeep
- **Better validation**: Upstream LSP is actively maintained
- **User choice**: External editors for power users
- **Focus**: Resources on workflow features, not editor features

### Negative / Tradeoffs
- **Dependency**: Relies on upstream LSP availability
- **Limited embedded editing**: Power users need external editor
- **Node.js requirement**: LSP server needs Node.js runtime

### Mitigations
- Bundle upstream LSP in `third_party/` for offline use
- Clear documentation for external editor setup
- Graceful degradation if LSP unavailable

## Implementation Checklist

- [x] `lsp.rs` is thin client only (current state)
- [x] README documents LSP installation
- [x] Bundled LSP in third_party/
- [ ] Add ADR reference to CLAUDE.md
- [ ] Document external editor workflow in user guide

## Related Issues

- crystalmath-as6l.12: Editor/LSP strategy + upstream integration (this ADR)
- crystalmath-as6l.16: Remove legacy Rust LSP implementation
