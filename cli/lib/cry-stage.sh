#!/bin/bash
# Module: cry-stage
# Description: File staging and preparation for crystallization operations
# Dependencies: core, cry-ui, cry-scratch

# Enable strict mode for better error handling
set -euo pipefail

# Prevent multiple sourcing
if [[ -n "${CRY_STAGE_LOADED:-}" ]]; then
    return 0
fi

# Mark as loaded
if [[ -n "${ZSH_VERSION:-}" ]]; then
    typeset -gr CRY_STAGE_LOADED=1
else
    declare -r CRY_STAGE_LOADED=1
fi

# Module-level constants (non-readonly to avoid conflicts with other modules)
MODULE_NAME="cry-stage"
MODULE_VERSION="1.0.0"

# NOTE: Legacy generic staging API (stage_init, stage_add, stage_remove, etc.)
# was removed as it used unimplemented scratch_create_dir helper and was never
# called by production code. Production uses stage_inputs/stage_retrieve_results.

_stage_init() {
    # Initialize stage module
    # Returns: 0 on success
    return 0
}

#===============================================================================
# CRYSTAL23-Specific Staging Functions
#===============================================================================

stage_inputs() {
    # Stage CRYSTAL23 input files to scratch directory
    # Args: $1 - file prefix, $2 - work directory, $3 - original directory
    # Returns: 0 on success, 1 on failure
    local file_prefix="$1"
    local work_dir="$2"
    local original_dir="$3"

    if [[ -z "$file_prefix" ]] || [[ -z "$work_dir" ]] || [[ -z "$original_dir" ]]; then
        ui_error "stage_inputs: Missing required arguments"
        return 1
    fi

    # Copy INPUT file (required)
    local input_file="${original_dir}/${file_prefix}.d12"
    if [[ ! -f "$input_file" ]]; then
        ui_error "Required INPUT file not found: $input_file"
        return 1
    fi

    if ! cp "$input_file" "$work_dir/INPUT"; then
        ui_error "Failed to copy INPUT file: $input_file"
        return 1
    fi

    # Stage auxiliary files (optional) using STAGE_MAP
    local found_list=()

    # Iterate through STAGE_MAP for optional auxiliary files
    if [[ -n "${ZSH_VERSION:-}" ]] || [[ "${BASH_VERSINFO:-0}" -ge 4 ]]; then
        # Use associative array
        for ext in "${!STAGE_MAP[@]}"; do
            local src_file="${original_dir}/${file_prefix}.${ext}"
            local dest_file="${STAGE_MAP[$ext]}"

            if [[ -f "$src_file" ]]; then
                if cp "$src_file" "$work_dir/$dest_file"; then
                    found_list+=("$src_file")
                fi
            fi
        done
    else
        # Fallback for bash 3.x using string format
        IFS=';' read -ra pairs <<< "$STAGE_MAP"
        for pair in "${pairs[@]}"; do
            IFS=':' read -r ext dest_file <<< "$pair"
            local src_file="${original_dir}/${file_prefix}.${ext}"

            if [[ -f "$src_file" ]]; then
                if cp "$src_file" "$work_dir/$dest_file"; then
                    found_list+=("$src_file")
                fi
            fi
        done
    fi

    # Report found auxiliary files
    if [[ ${#found_list[@]} -gt 0 ]]; then
        for file in "${found_list[@]}"; do
            ui_file_found "$file"
        done
    fi

    return 0
}

stage_retrieve_results() {
    # Retrieve CRYSTAL23 result files from scratch directory
    # Args: $1 - file prefix, $2 - work directory, $3 - original directory
    # Returns: 0 on success
    local file_prefix="$1"
    local work_dir="$2"
    local original_dir="$3"

    if [[ -z "$file_prefix" ]] || [[ -z "$work_dir" ]] || [[ -z "$original_dir" ]]; then
        ui_error "stage_retrieve_results: Missing required arguments"
        return 1
    fi

    # Always retrieve OUTPUT file (main output)
    local output_file="$work_dir/OUTPUT"
    if [[ -f "$output_file" ]]; then
        cp "$output_file" "${original_dir}/${file_prefix}.out"
    fi

    # Retrieve auxiliary result files using RETRIEVE_MAP
    if [[ -n "${ZSH_VERSION:-}" ]] || [[ "${BASH_VERSINFO:-0}" -ge 4 ]]; then
        # Use associative array
        for work_file in "${!RETRIEVE_MAP[@]}"; do
            local output_ext="${RETRIEVE_MAP[$work_file]}"
            local src="${work_dir}/${work_file}"
            local dest="${original_dir}/${file_prefix}.${output_ext}"

            if [[ -f "$src" ]]; then
                cp "$src" "$dest"
            fi
        done
    else
        # Fallback for bash 3.x using string format
        IFS=';' read -ra pairs <<< "$RETRIEVE_MAP"
        for pair in "${pairs[@]}"; do
            IFS=':' read -r work_file output_ext <<< "$pair"
            local src="${work_dir}/${work_file}"
            local dest="${original_dir}/${file_prefix}.${output_ext}"

            if [[ -f "$src" ]]; then
                cp "$src" "$dest"
            fi
        done
    fi

    return 0
}

# Auto-initialize
_stage_init
