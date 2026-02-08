#!/usr/bin/env bash
# cry-scratch.sh - Scratch space management module for CRY_CLI
# Provides scratch directory creation, cleanup, and file staging

# Enable strict mode for better error handling
set -euo pipefail

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

