#!/bin/bash
set -e

echo "=== 1. Purging Duplicate Sections and Keys from pyproject.toml ==="
python3 -c "
with open('python/pyproject.toml', 'r') as f:
    lines = f.readlines()

script_entries = {}
cleaned_lines = []
in_scripts = False

for line in lines:
    stripped = line.strip()
    
    # Track section entry boundaries
    if stripped.startswith('[') and stripped.endswith(']'):
        if stripped == '[project.scripts]':
            in_scripts = True
            continue
        else:
            in_scripts = False

    if in_scripts:
        # Only capture unique, non-comment key-value definitions
        if stripped and '=' in stripped and not stripped.startswith('#'):
            key = stripped.split('=')[0].strip()
            script_entries[key] = line
    else:
        cleaned_lines.append(line)

# Re-assemble the manifest, placing the single clean section right before project URLs
final_lines = []
inserted = False
for line in cleaned_lines:
    if line.strip() == '[project.urls]' and not inserted:
        final_lines.append('[project.scripts]\n')
        for unique_line in script_entries.values():
            final_lines.append(unique_line)
        final_lines.append('\n')
        inserted = True
    final_lines.append(line)

with open('python/pyproject.toml', 'w') as f:
    f.writelines(final_lines)
print('✅ Successfully consolidated headers and purged duplicate script assignments.')
"

echo "=== 2. Re-triggering Python Workspace Package Sync ==="
uv pip install -e ./python

echo "=== 3. Launching Unified TUI Engine ==="
cargo run --release
