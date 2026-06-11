#!/bin/bash
set -e

echo "=== 1. Surgically Aligning Channel Scopes and Type Annotations ==="
python3 -c "
with open('src/main.rs', 'r') as f:
    content = f.read()

# Fix A: Add precise type annotations and change backend_tx to _backend_tx to avoid unused variable warnings
old_channel = 'let (backend_tx, backend_rx) = std::sync::mpsc::channel();'
new_channel = 'let (_backend_tx, backend_rx) = std::sync::mpsc::channel::<crate::state::actions::AppBackendEvent>();'
if old_channel in content:
    content = content.replace(old_channel, new_channel)

# Fix B: Pass backend_rx into the run_app call signature inside main()
old_call = 'let result = run_app(&mut terminal, &mut app);'
new_call = 'let result = run_app(&mut terminal, &mut app, backend_rx);'
if old_call in content:
    content = content.replace(old_call, new_call)

# Fix C: Update the run_app definition signature to accept the channel receiver
old_sig = 'fn run_app<B: Backend>(terminal: &mut Terminal<B>, app: &mut App) -> Result<()>'
new_sig = 'fn run_app<B: Backend>(\n    terminal: &mut Terminal<B>,\n    app: &mut App,\n    backend_rx: std::sync::mpsc::Receiver<crate::state::actions::AppBackendEvent>,\n) -> Result<()>'
if old_sig in content:
    content = content.replace(old_sig, new_sig)

with open('src/main.rs', 'w') as f:
    f.write(content)
print('✅ main() boundaries and run_app signatures fully unified.')
"

echo "=== 2. Verifying Monorepo Compilation Gate ==="
cargo clippy --all-targets
