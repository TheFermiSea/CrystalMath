#!/usr/bin/env bash
# cry-scratch.sh - Scratch space management module for CRY_CLI
# Provides scratch directory creation, cleanup, and file staging

# Prevent multiple sourcing
[[ -n "${CRY_SCRATCH_LOADED:-}" ]] && return 0
if [[ -n "${ZSH_VERSION:-}" ]]; then
    typeset -gr CRY_SCRATCH_LOADED=1
else
    declare -r CRY_SCRATCH_LOADED=1
fi

#===============================================================================
# Scratch Directory Management
#===============================================================================

scratch_create() {
    # Create unique scratch directory for job execution
    # Usage: scratch_create FILE_PREFIX
    # Exports: WORK_DIR - Path to scratch directory

    local file_prefix="$1"

    if [[ -z "$file_prefix" ]]; then
        echo "Error: File prefix required for scratch_create" >&2
        return 1
    fi

    # Ensure CRY_SCRATCH_BASE is set (from cry-config.sh)
    if [[ -z "${CRY_SCRATCH_BASE:-}" ]]; then
        echo "Error: CRY_SCRATCH_BASE not set. Source cry-config.sh first." >&2
        return 1
    fi

    # Generate unique job ID with PID
    local job_id="cry_${file_prefix}_$$"

    # Export WORK_DIR for global access
    export WORK_DIR="$CRY_SCRATCH_BASE/$job_id"

    # Create scratch directory
    if ! mkdir -p "$WORK_DIR"; then
        echo "Error: Failed to create scratch directory: $WORK_DIR" >&2
        return 1
    fi

    return 0
}

scratch_cleanup() {
    # Remove scratch directory (idempotent, safe with trap)
    # Usage: scratch_cleanup
    # Safe to call even if scratch_create failed

    # Only proceed if WORK_DIR is set and is a directory
    if [[ -n "${WORK_DIR:-}" ]] && [[ -d "$WORK_DIR" ]]; then
        # Safety check: ensure WORK_DIR is within CRY_SCRATCH_BASE
        if [[ "$WORK_DIR" == "$CRY_SCRATCH_BASE"/* ]]; then
            rm -rf "$WORK_DIR"
        else
            echo "Warning: WORK_DIR outside CRY_SCRATCH_BASE, skipping cleanup: $WORK_DIR" >&2
            unset WORK_DIR
            return 1
        fi
    fi

    # Always unset WORK_DIR after cleanup attempt
    unset WORK_DIR
    return 0
}

scratch_info() {
    # Display information about current scratch directory
    # Usage: scratch_info

    if [[ -z "${WORK_DIR:-}" ]]; then
        echo "No scratch directory active"
        return 1
    fi

    echo "Scratch Directory Information:"
    echo "  WORK_DIR:       $WORK_DIR"
    echo "  CRY_SCRATCH_BASE:   $CRY_SCRATCH_BASE"

    if [[ -d "$WORK_DIR" ]]; then
        echo "  Status:         EXISTS"
        echo "  Size:           $(du -sh "$WORK_DIR" 2>/dev/null | cut -f1 || echo 'unknown')"
        echo "  Files:          $(find "$WORK_DIR" -type f 2>/dev/null | wc -l || echo '0')"
    else
        echo "  Status:         NOT CREATED"
    fi
}

#===============================================================================
# File Staging Functions
#===============================================================================

scratch_stage_file() {
    # Stage a single file to scratch directory
    # Usage: scratch_stage_file SOURCE_FILE DEST_NAME
    # Returns: 0 if file staged, 1 if source doesn't exist or staging fails

    local src_file="$1"
    local dest_name="$2"

    if [[ -z "$src_file" ]] || [[ -z "$dest_name" ]]; then
        echo "Error: scratch_stage_file requires SOURCE_FILE and DEST_NAME" >&2
        return 1
    fi

    if [[ -z "${WORK_DIR:-}" ]] || [[ ! -d "$WORK_DIR" ]]; then
        echo "Error: Scratch directory not initialized. Call scratch_create first." >&2
        return 1
    fi

    # Only copy if source file exists
    if [[ -f "$src_file" ]]; then
        if cp "$src_file" "$WORK_DIR/$dest_name"; then
            return 0
        else
            echo "Error: Failed to stage file: $src_file -> $WORK_DIR/$dest_name" >&2
            return 1
        fi
    fi

    # File doesn't exist - not an error, just skip
    return 1
}

scratch_stage_main() {
    # Stage main input file (INPUT) to scratch directory
    # Usage: scratch_stage_main INPUT_FILE

    local input_file="$1"

    if [[ -z "$input_file" ]]; then
        echo "Error: Input file required for scratch_stage_main" >&2
        return 1
    fi

    if [[ ! -f "$input_file" ]]; then
        echo "Error: Input file not found: $input_file" >&2
        return 1
    fi

    scratch_stage_file "$input_file" "INPUT"
}

scratch_stage_auxiliary() {
    # Stage auxiliary files using STAGE_MAP from cry-config.sh
    # Usage: scratch_stage_auxiliary FILE_PREFIX
    # Returns: Number of files staged

    local file_prefix="$1"
    local staged_count=0

    if [[ -z "$file_prefix" ]]; then
        echo "Error: File prefix required for scratch_stage_auxiliary" >&2
        return 1
    fi

    # Stage files based on STAGE_MAP
    # Format: local_file -> fort.XX or special name
    local -a stage_files=(
        "${file_prefix}.gui:fort.34"
        "${file_prefix}.f9:fort.20"
        "${file_prefix}.f98:fort.98"
        "${file_prefix}.hessopt:HESSOPT.DAT"
        "${file_prefix}.born:BORN.DAT"
    )

    for entry in "${stage_files[@]}"; do
        local src="${entry%%:*}"
        local dest="${entry##*:}"

        if scratch_stage_file "$src" "$dest"; then
            ((staged_count++))
        fi
    done

    return "$staged_count"
}

#===============================================================================
# File Retrieval Functions
#===============================================================================

scratch_retrieve_file() {
    # Retrieve a single file from scratch directory
    # Usage: scratch_retrieve_file WORK_FILE OUTPUT_FILE
    # Returns: 0 if file retrieved, 1 if not found or retrieval fails

    local work_file="$1"
    local output_file="$2"

    if [[ -z "$work_file" ]] || [[ -z "$output_file" ]]; then
        echo "Error: scratch_retrieve_file requires WORK_FILE and OUTPUT_FILE" >&2
        return 1
    fi

    if [[ -z "${WORK_DIR:-}" ]] || [[ ! -d "$WORK_DIR" ]]; then
        echo "Error: Scratch directory not initialized" >&2
        return 1
    fi

    # Determine output directory (preserve current working directory)
    local output_dir="${OLDPWD:-$(pwd)}"

    # Only copy if work file exists
    if [[ -f "$WORK_DIR/$work_file" ]]; then
        if cp "$WORK_DIR/$work_file" "$output_dir/$output_file"; then
            return 0
        else
            echo "Error: Failed to retrieve file: $WORK_DIR/$work_file -> $output_dir/$output_file" >&2
            return 1
        fi
    fi

    # File doesn't exist - not an error, just skip
    return 1
}

scratch_retrieve_results() {
    # Retrieve result files using RETRIEVE_MAP pattern
    # Usage: scratch_retrieve_results FILE_PREFIX
    # Returns: Number of files retrieved

    local file_prefix="$1"
    local retrieved_count=0

    if [[ -z "$file_prefix" ]]; then
        echo "Error: File prefix required for scratch_retrieve_results" >&2
        return 1
    fi

    # Retrieve output file
    if scratch_retrieve_file "${file_prefix}.out" "${file_prefix}.out"; then
        ((retrieved_count++))
    fi

    # Retrieve standard result files
    local -a retrieve_files=(
        "fort.9:${file_prefix}.f9"
        "fort.98:${file_prefix}.f98"
        "HESSOPT.DAT:${file_prefix}.hessopt"
        "OPTINFO.DAT:${file_prefix}.optinfo"
        "FREQINFO.DAT:${file_prefix}.freqinfo"
    )

    for entry in "${retrieve_files[@]}"; do
        local work_file="${entry%%:*}"
        local output_file="${entry##*:}"

        if scratch_retrieve_file "$work_file" "$output_file"; then
            ((retrieved_count++))
        fi
    done

    return "$retrieved_count"
}

#===============================================================================
# Utility Functions
#===============================================================================

scratch_cd() {
    # Change directory to scratch workspace
    # Usage: scratch_cd

    if [[ -z "${WORK_DIR:-}" ]] || [[ ! -d "$WORK_DIR" ]]; then
        echo "Error: Scratch directory not initialized or doesn't exist" >&2
        return 1
    fi

    cd "$WORK_DIR" || return 1
}

scratch_list() {
    # List files in scratch directory
    # Usage: scratch_list

    if [[ -z "${WORK_DIR:-}" ]] || [[ ! -d "$WORK_DIR" ]]; then
        echo "Error: Scratch directory not initialized or doesn't exist" >&2
        return 1
    fi

    echo "Contents of $WORK_DIR:"
    ls -lh "$WORK_DIR"
}

scratch_validate() {
    # Validate scratch directory state
    # Usage: scratch_validate
    # Returns: 0 if valid, 1 if invalid

    local errors=0

    # Check if CRY_SCRATCH_BASE exists
    if [[ ! -d "$CRY_SCRATCH_BASE" ]]; then
        echo "Error: CRY_SCRATCH_BASE does not exist: $CRY_SCRATCH_BASE" >&2
        ((errors++))
    fi

    # Check if WORK_DIR is set
    if [[ -z "${WORK_DIR:-}" ]]; then
        echo "Warning: WORK_DIR not set (call scratch_create first)" >&2
    else
        # Check if WORK_DIR exists
        if [[ ! -d "$WORK_DIR" ]]; then
            echo "Warning: WORK_DIR set but directory doesn't exist: $WORK_DIR" >&2
        fi

        # Check if WORK_DIR is within CRY_SCRATCH_BASE
        if [[ "$WORK_DIR" != "$CRY_SCRATCH_BASE"/* ]]; then
            echo "Error: WORK_DIR is outside CRY_SCRATCH_BASE!" >&2
            ((errors++))
        fi
    fi

    return "$errors"
}
