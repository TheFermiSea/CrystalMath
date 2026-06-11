#!/bin/bash
set -e

echo "=== 1. Automatically Unifying Scatetered TOML Headers ==="
python3 -c "
with open('python/pyproject.toml', 'r') as f:
    lines = f.readlines()

script_entries = []
cleaned_lines = []
in_scripts = False

for line in lines:
    stripped = line.strip()
    # Detect a new section header block
    if stripped.startswith('[') and stripped.endswith(']'):
        if stripped == '[project.scripts]':
            in_scripts = True
            continue
        else:
            in_scripts = False

    if in_scripts:
        if stripped: # Preserve valid configuration definitions and comments inside the block
            script_entries.append(line)
    else:
        cleaned_lines.append(line)

# Re-insert the single aggregated [project.scripts] block right before [project.urls]
final_lines = []
inserted = False
for line in cleaned_lines:
    if line.strip() == '[project.urls]' and not inserted:
        final_lines.append('[project.scripts]\n')
        final_lines.extend(script_entries)
        if not script_entries[-1].endswith('\n'):
            final_lines.append('\n')
        final_lines.append('\n')
        inserted = True
    final_lines.append(line)

with open('python/pyproject.toml', 'w') as f:
    f.writelines(final_lines)
print('✅ Consolidated all script entry points under a single [project.scripts] section.')
"

echo "=== 2. Re-triggering Local Python Package Installation ==="
uv pip install -e ./python

echo "=== 3. Launching Unified TUI Core Runtime Engine ==="
cargo run --release
