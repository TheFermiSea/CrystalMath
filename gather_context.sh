#!/bin/bash
set -e

OUTPUT_FILE="crystalmath_context_dump.txt"
echo "=== CrystalMath Deep Structural Context Miner ===" >"$OUTPUT_FILE"
echo "Generated on: $(date)" >>"$OUTPUT_FILE"
echo "==================================================" >>"$OUTPUT_FILE"

echo "🔍 Mapping codebase layout..."

# 1. Track 1 Context: Extracting main.rs event loop and rendering pipelines
echo -e "\n--- [SECTION 1: src/main.rs RENDERING & EVENT PUMP] ---" >>"$OUTPUT_FILE"
if [ -f src/main.rs ]; then
  echo "• Mining src/main.rs structural loop..."
  # Locate where terminal.draw is called inside main.rs
  sg scan --pattern 'terminal.draw($$$)' src/main.rs >>"$OUTPUT_FILE" 2>/dev/null || true
  # Grab the block surrounding your event polling
  grep -A 30 -B 10 "crossterm::event::read" src/main.rs >>"$OUTPUT_FILE" 2>/dev/null || true
else
  echo "⚠️ src/main.rs not found!" >>"$OUTPUT_FILE"
fi

# 2. Track 2 Context: Extracting Editor layout and keystroke routing
echo -e "\n--- [SECTION 2: src/ui/editor.rs HANDLING & STATE] ---" >>"$OUTPUT_FILE"
if [ -f src/ui/editor.rs ]; then
  echo "• Mining src/ui/editor.rs view structures..."
  # Grab the key matching blocks inside the editor component
  sg scan --pattern 'match ($$$) { $$$ }' src/ui/editor.rs >>"$OUTPUT_FILE" 2>/dev/null || true
  # Pull the render signature to inspect how app state passes through the UI layer
  grep -A 20 "pub fn render" src/ui/editor.rs >>"$OUTPUT_FILE" 2>/dev/null || true
else
  echo "⚠️ src/ui/editor.rs not found!" >>"$OUTPUT_FILE"
fi

# 3. Track 3 Context: Inspecting Python modules and promoted code verticals
echo -e "\n--- [SECTION 3: PYTHON CODE MODES & BASE TASKDOCS] ---" >>"$OUTPUT_FILE"
echo "• Listing promoted code vertical files..."
echo "Files in python/crystalmath/codes/:" >>"$OUTPUT_FILE"
find python/crystalmath/codes -type f >>"$OUTPUT_FILE" 2>/dev/null || true

if [ -f python/crystalmath/models.py ]; then
  echo "• Mining python/crystalmath/models.py schemas..."
  # Extract structural classes matching TaskDoc patterns to find the serialization models
  grep -E "class .*Doc|class .*Metadata" -A 15 python/crystalmath/models.py >>"$OUTPUT_FILE" 2>/dev/null || true
else
  echo "⚠️ python/crystalmath/models.py not found!" >>"$OUTPUT_FILE"
fi

# 4. Global App Properties: Inspecting App struct for state parameters
echo -e "\n--- [SECTION 4: src/app.rs CORE FIELD SCHEMAS] ---" >>"$OUTPUT_FILE"
if [ -f src/app.rs ]; then
  echo "• Mining src/app.rs state structures..."
  # Find the central App struct definition to see active field names
  grep -A 40 "pub struct App" src/app.rs >>"$OUTPUT_FILE" 2>/dev/null || true
fi

echo "==================================================" >>"$OUTPUT_FILE"
echo "✅ Context mining complete! Data saved to: $OUTPUT_FILE"
echo "Copy and paste the contents of that file here, and we'll start implementing the tracks."
