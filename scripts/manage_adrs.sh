#!/bin/bash
# ==============================================================================
# CRYSTALMATH MONOREPO - ARCHITECTURAL DECISION RECORD (ADR) MAINTENANCE TOOL
# ==============================================================================

set -euo pipefail

TARGET_DIR="docs/architecture"
BACKUP_DIR="docs/architecture_backup_$(date +%s)"

# Ensure we are executing from the monorepo root directory
if [ ! -d "$TARGET_DIR" ]; then
  echo "❌ Error: Could not find directory '$TARGET_DIR'."
  echo "   Please run this script from the root of the CrystalMath repository."
  exit 1
fi

echo "📦 Creating insurance backup layout at: $BACKUP_DIR"
cp -r "$TARGET_DIR" "$BACKUP_DIR"

echo "🔍 Phase 1: Cleaning transient syntax and dead extensions..."
# Cross-platform pattern cleaning via Perl
find "$TARGET_DIR" -type f \( -name "adr-*.md" -o -name "ADR*.md" \) | while read -r adr_file; do
  perl -pi -e 's/\r//g' "$adr_file"
done

echo "⚙️ Phase 2: Auditing current structural files to resolve title tags..."
# Removed 'declare -A' to ensure full compatibility with older macOS Bash versions
temp_manifest=$(mktemp -t crystalmath_manifest)

# Read structural entries to extract true semantic titles
find "$TARGET_DIR" -type f -name "*.md" | grep -E '/(adr-[0-9]|ADR|ATOMATE2|CONSOLIDATION|HIGH-LEVEL|REDESIGN|UNIFIED-WORKFLOW)' | while read -r adr_path; do
  filename=$(basename "$adr_path")

  # Extract original assigned number indicator if present
  raw_num=$(echo "$filename" | grep -oE '[0-9]+' | head -n1 | sed 's/^0*//' || echo "")

  # Fallback default sorting order if unnumbered
  if [ -z "$raw_num" ]; then
    raw_num="999"
  fi

  # Parse out the primary structural title heading (# ADR-XX: Title or # Title)
  title=$(grep -E '^# ' "$adr_path" | head -n 1 | sed -E 's/^# (ADR-[0-9]+: )?//' | tr -dc 'a-zA-Z0-9 _-')

  if [ -z "$title" ]; then
    title=$(echo "$filename" | sed -E 's/(adr-|ADR|[0-9]+|-|\.md)//g')
  fi

  # Clean spacing strings to generate strict canonical slugs
  slug=$(echo "$title" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -s '-' | sed 's/^-//;s/-$//')

  echo "$raw_num|$slug|$adr_path" >>"$temp_manifest"
done

echo "🔀 Phase 3: Enforcing chronological sequence indexing..."
# Sort manifest by original index numbers to maintain timeline history logic
counter=1
while IFS='|' read -r orig_num slug old_path; do
  # Format absolute uniform indexes (e.g., adr-001, adr-002)
  new_index=$(printf "%03d" "$counter")
  new_filename="adr-${new_index}-${slug}.md"
  new_path="${TARGET_DIR}/${new_filename}"

  # Move the file if the name has changed
  if [ "$old_path" != "$new_path" ]; then
    echo "   Moving: $(basename "$old_path") ➡️ $new_filename"
    mv "$old_path" "$new_path"
  fi

  # Check if Front Matter exists. If not, inject it.
  if ! grep -q "^---" "$new_path"; then
    echo "   Injecting Front-Matter Metadata Headers into $new_filename"
    clean_title=$(echo "$slug" | tr '-' ' ' | awk '{for(i=1;i<=NF;i++)sub(/./,toupper(substr($i,1,1)),$i)}1')

    # Create a temp file with the new header + old content (stripping the old # Title line)
    cat <<EOF >"${new_path}.tmp"
---
adr_id: ${new_index}
title: "${clean_title}"
status: "Accepted"
date: "$(date +%Y-%m-%d)"
macro_context: "crystalmath-tui-core"
---

# ADR-${new_index}: ${clean_title}

$(cat "$new_path" | sed -E 's/^# (ADR-[0-9]+: )?.*//')
EOF
    # Remove any leading blank lines left by the stripped title
    perl -i -0777 -pe 's/^\n+//' "${new_path}.tmp"
    mv "${new_path}.tmp" "$new_path"
  fi

  counter=$((counter + 1))
done < <(sort -n -t'|' -k1 "$temp_manifest")

rm -f "$temp_manifest"

echo "🔗 Phase 4: Compiling centralized active manifest ledger..."
MANIFEST_FILE="${TARGET_DIR}/README.md"
cat <<EOF >"$MANIFEST_FILE"
# CrystalMath Architectural Decision Records (ADRs)

This directory serves as the centralized repository log tracking foundational architecture decisions 
governing the CrystalMath platform ecosystem under our unified Rust/Ratatui strategy.

## 📋 Active Timeline Index

| Index | Architecture Decision Domain File | Status | Last Updated |
| :--- | :--- | :---: | :---: |
EOF

# Append every sorted, freshly numbered ADR dynamically into a markdown table
find "$TARGET_DIR" -type f -name "adr-*.md" | sort | while read -r final_adr; do
  fname=$(basename "$final_adr")
  idx=$(echo "$fname" | cut -d'-' -f2)

  # Extract Title from Front Matter if possible, else filename
  raw_title=$(grep "^title:" "$final_adr" | head -n1 | cut -d'"' -f2 || echo "")
  if [ -z "$raw_title" ]; then
    raw_title=$(echo "$fname" | cut -d'-' -f3- | sed 's/\.md//' | tr '-' ' ')
  fi

  # Extract Status from Front Matter
  status=$(grep "^status:" "$final_adr" | head -n1 | cut -d'"' -f2 || echo "Accepted")
  [ -z "$status" ] && status="Accepted"

  echo "| **${idx}** | [${raw_title}](${fname}) | \`${status}\` | $(date +%Y-%m-%d) |" >>"$MANIFEST_FILE"
done

echo "✅ Optimization Sequence complete!"
echo "   All ADRs have been re-indexed, normalized, and indexed at: $MANIFEST_FILE"
