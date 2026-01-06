# LSP Strategy: Use Upstream, Avoid Custom LSP

We will **not** implement a custom LSP in Rust. The complexity and maintenance cost is disproportionate to the value.

## Decision

- **Use upstream `dft-language-server`** (`vasp-lsp` / `dft-lsp`) for diagnostics.
- **Prefer external editors** via `$EDITOR` for rich editing (VS Code, Neovim, etc.).
- If an in-app editor exists, keep it **minimal** (syntax highlighting only).

## Installation (Optional)

```bash
npm install -g dft-language-server
```

## In-App Editor Guidance

- Show lint/diagnostic output by calling the upstream server (not by reimplementing it).
- Provide an **Open in $EDITOR** action for full-featured editing.
- Avoid LSP-specific logic inside Rust UI beyond connecting to the upstream server.

## Acceptance Criteria

- No new custom LSP implementation in Rust.
- Upstream LSP usage documented.
- $EDITOR workflow supported for full editing.
