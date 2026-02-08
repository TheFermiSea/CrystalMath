#!/usr/bin/env bash
# Test script for cry-stage.sh staging functions

set -euo pipefail

# Source required modules
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$SCRIPT_DIR/../lib"

source "$LIB_DIR/cry-config.sh"
source "$LIB_DIR/cry-ui.sh"
source "$LIB_DIR/cry-stage.sh"

# Test setup
TEST_DIR="$(mktemp -d)"
WORK_DIR="$TEST_DIR/work"
ORIG_DIR="$TEST_DIR/orig"

cleanup() {
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

# Create test directories
mkdir -p "$WORK_DIR" "$ORIG_DIR"

# Test 1: stage_inputs with required .d12 file only
echo "Test 1: Stage inputs with required .d12 file"
cat > "$ORIG_DIR/test.d12" <<'EOF'
Test INPUT file
CRYSTAL
END
EOF

if stage_inputs "test" "$WORK_DIR" "$ORIG_DIR"; then
    if [[ -f "$WORK_DIR/INPUT" ]]; then
        ui_success "Test 1 PASSED: INPUT file staged"
    else
        ui_error "Test 1 FAILED: INPUT file not found"
        exit 1
    fi
else
    ui_error "Test 1 FAILED: stage_inputs returned error"
    exit 1
fi

# Test 2: stage_inputs with auxiliary files
echo ""
echo "Test 2: Stage inputs with auxiliary files"
rm -rf "${WORK_DIR:?}"/*
touch "$ORIG_DIR/test.gui"
touch "$ORIG_DIR/test.f9"
touch "$ORIG_DIR/test.hessopt"

if stage_inputs "test" "$WORK_DIR" "$ORIG_DIR"; then
    files_ok=true
    [[ -f "$WORK_DIR/INPUT" ]] || files_ok=false
    [[ -f "$WORK_DIR/fort.34" ]] || files_ok=false
    [[ -f "$WORK_DIR/fort.20" ]] || files_ok=false
    [[ -f "$WORK_DIR/HESSOPT.DAT" ]] || files_ok=false

    if $files_ok; then
        ui_success "Test 2 PASSED: All auxiliary files staged"
    else
        ui_error "Test 2 FAILED: Some files missing"
        ls -la "$WORK_DIR"
        exit 1
    fi
else
    ui_error "Test 2 FAILED: stage_inputs returned error"
    exit 1
fi

# Test 3: stage_retrieve_results
echo ""
echo "Test 3: Retrieve results"
cat > "$WORK_DIR/OUTPUT" <<'EOF'
Test output
EOF
touch "$WORK_DIR/fort.9"
touch "$WORK_DIR/OPTINFO.DAT"

if stage_retrieve_results "result" "$WORK_DIR" "$ORIG_DIR"; then
    files_ok=true
    [[ -f "$ORIG_DIR/result.out" ]] || files_ok=false
    [[ -f "$ORIG_DIR/result.f9" ]] || files_ok=false
    [[ -f "$ORIG_DIR/result.optinfo" ]] || files_ok=false

    if $files_ok; then
        ui_success "Test 3 PASSED: All result files retrieved"
    else
        ui_error "Test 3 FAILED: Some result files missing"
        ls -la "$ORIG_DIR"
        exit 1
    fi
else
    ui_error "Test 3 FAILED: stage_retrieve_results returned error"
    exit 1
fi

# Test 4: Missing required file
echo ""
echo "Test 4: Error handling for missing .d12 file"
rm -rf "${WORK_DIR:?}"/* "${ORIG_DIR:?}"/*

if stage_inputs "missing" "$WORK_DIR" "$ORIG_DIR" 2>/dev/null; then
    ui_error "Test 4 FAILED: Should have returned error for missing .d12"
    exit 1
else
    ui_success "Test 4 PASSED: Correctly handled missing .d12 file"
fi

echo ""
ui_success "All tests passed!"
