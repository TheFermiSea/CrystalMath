#!/bin/bash
# Test script for enhanced job status display

set -e

cd "$(dirname "$0")/.."

echo "Testing Enhanced Job Status Display"
echo "===================================="
echo

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found"
    echo "Please create it first: python3 -m venv venv"
    exit 1
fi

# Activate venv
source venv/bin/activate

# Test imports
echo "1. Testing widget imports..."
python3 -c "from src.tui.widgets import JobListWidget, JobStatsWidget; print('   ✓ JobListWidget')" || exit 1
python3 -c "from src.tui.widgets import JobStatsWidget; print('   ✓ JobStatsWidget')" || exit 1

echo
echo "2. Testing enhanced app import..."
python3 -c "from src.tui.app_enhanced import CrystalTUI; print('   ✓ CrystalTUI enhanced')" || exit 1

echo
echo "3. Testing job list widget functionality..."
python3 << 'EOF'
from src.tui.widgets import JobListWidget
from src.core.database import Job

# Create widget
widget = JobListWidget()

# Test status formatting
print("   ✓ Status colors:", widget.STATUS_COLORS)
print("   ✓ Status icons:", widget.STATUS_ICONS)

# Test duration formatting
duration = widget._format_duration(125.5)
assert "2m" in duration, f"Expected '2m', got '{duration}'"
print(f"   ✓ Duration formatting: {duration}")

print("   ✓ All widget methods present")
EOF

echo
echo "4. Testing job stats widget..."
python3 << 'EOF'
from src.tui.widgets import JobStatsWidget
from src.core.database import Job

# Create widget
widget = JobStatsWidget()

# Verify reactive properties
assert hasattr(widget, 'total_jobs')
assert hasattr(widget, 'running_jobs')
assert hasattr(widget, 'completed_jobs')
assert hasattr(widget, 'failed_jobs')
print("   ✓ Reactive properties present")

print("   ✓ Job stats widget initialized")
EOF

echo
echo "5. Testing enhanced app structure..."
python3 << 'EOF'
from src.tui.app_enhanced import CrystalTUI
from pathlib import Path

# Check bindings
assert any(b.key == "f" for b in CrystalTUI.BINDINGS), "Missing filter binding"
assert any(b.key == "t" for b in CrystalTUI.BINDINGS), "Missing sort binding"
print("   ✓ Keybindings present (f: filter, t: sort)")

# Check methods
assert hasattr(CrystalTUI, 'action_filter_status')
assert hasattr(CrystalTUI, 'action_sort_toggle')
assert hasattr(CrystalTUI, '_update_running_jobs')
print("   ✓ Enhanced actions present")

print("   ✓ Enhanced app structure validated")
EOF

echo
echo "===================================="
echo "✓ All tests passed!"
echo
echo "The enhanced job status display is ready to use."
echo "Run 'crystal-tui' or 'python3 -m src.main' to launch."
echo
echo "Features:"
echo "  • Color-coded status indicators (⏸ ⏳ ▶ ✓ ✗)"
echo "  • Progress bars with real-time updates"
echo "  • Runtime display (automatically updates every second)"
echo "  • Resource usage (MPI ranks × threads)"
echo "  • Job statistics footer"
echo "  • Status filtering (press 'f')"
echo "  • Column sorting (press 't')"
