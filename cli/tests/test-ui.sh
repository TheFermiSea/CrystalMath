#!/usr/bin/env bash
# Test script for lib/cry-ui.sh

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source dependencies
source "$PROJECT_ROOT/lib/cry-config.sh"
source "$PROJECT_ROOT/lib/cry-ui.sh"

echo "=== Testing cry-ui.sh Module ==="
echo ""

# Test 1: Banner
echo "Test 1: ui_banner"
ui_banner
echo ""

# Test 2: Card
echo "Test 2: ui_card"
ui_card "Configuration" \
    "Version: 1.0.1" \
    "Architecture: Linux-ifort_i64_omp" \
    "Binary Path: /home/user/CRYSTAL23/bin"
echo ""

# Test 3: Status Lines
echo "Test 3: ui_status_line"
ui_status_line "Status" "Ready"
ui_status_line "Mode" "Optimization"
ui_status_line "Cores" "16"
echo ""

# Test 4: File Found
echo "Test 4: ui_file_found"
ui_file_found "/path/to/input.d12"
ui_file_found "/path/to/geometry.gui"
echo ""

# Test 5: Messages
echo "Test 5: Messages"
ui_success "Operation completed successfully"
ui_error "Test error message (expected)"
ui_warning "Test warning message"
ui_info "Test info message"
echo ""

# Test 6: List
echo "Test 6: ui_list"
echo "Available tutorials:"
ui_list "Tutorial 1: Basic Structure" "Tutorial 2: Optimization" "Tutorial 3: Frequency Calculation"
echo ""

# Test 7: Spinner (if gum available)
echo "Test 7: ui_spin"
if $HAS_GUM; then
    ui_spin "Testing spinner" "sleep 2"
    echo "Spinner test completed"
else
    echo "Gum not available, skipping spinner test"
fi
echo ""

# Test 8: Progress
echo "Test 8: ui_progress"
for i in {1..5}; do
    ui_progress "$i" 5 "Processing step $i..."
    sleep 0.5
done
echo ""

# Test 9: Table
echo "Test 9: Table display"
ui_table_header "File" "Size" "Status"
ui_table_row "input.d12" "2.3 KB" "Ready"
ui_table_row "output.out" "145.7 KB" "Complete"
ui_table_row "geometry.gui" "1.1 KB" "Staged"
echo ""

echo "=== All tests completed ==="
echo "HAS_GUM: $HAS_GUM"
echo ""
