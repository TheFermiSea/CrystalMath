#!/bin/bash
# Module: cry-stage
# Description: File staging and preparation for crystallization operations
# Dependencies: core, cry-ui, cry-scratch

# Prevent multiple sourcing
if [[ -n "${CRY_STAGE_LOADED:-}" ]]; then
    return 0
fi

# Error handling

# Mark as loaded
if [[ -n "${ZSH_VERSION:-}" ]]; then
    typeset -gr CRY_STAGE_LOADED=1
else
    declare -r CRY_STAGE_LOADED=1
fi

# Module-level constants (non-readonly to avoid conflicts with other modules)
MODULE_NAME="cry-stage"
MODULE_VERSION="1.0.0"

# Stage tracking
declare -g STAGE_ACTIVE="${STAGE_ACTIVE:-false}"
declare -g STAGE_ROOT=""
declare -ga STAGE_FILES=()
declare -gA STAGE_FILE_METADATA=()

# Public functions

stage_init() {
    # Initialize staging area
    # Args: none
    # Returns: 0 on success, 1 on failure

    if [[ "$STAGE_ACTIVE" == "true" ]]; then
        ui_warning "Stage already initialized"
        return 0
    fi

    # Create staging area in scratch space
    if ! STAGE_ROOT=$(scratch_create_dir "stage"); then
        ui_error "Failed to create staging area"
        return 1
    fi

    STAGE_ACTIVE="true"
    ui_info "Stage initialized: $STAGE_ROOT"
    return 0
}

stage_add() {
    # Add a file to staging area
    # Args: $1 - file path, $2 - stage name (optional)
    # Returns: 0 on success, 1 on failure
    local file="$1"
    local stage_name="${2:-$(basename "$file")}"

    if [[ "$STAGE_ACTIVE" != "true" ]]; then
        ui_error "Stage not initialized"
        return 1
    fi

    if [[ ! -f "$file" ]]; then
        ui_error "File not found: $file"
        return 1
    fi

    # Copy file to staging area
    local staged_file="$STAGE_ROOT/$stage_name"
    if ! cp "$file" "$staged_file"; then
        ui_error "Failed to stage file: $file"
        return 1
    fi

    # Track staged file
    STAGE_FILES+=("$stage_name")
    STAGE_FILE_METADATA["$stage_name:original"]="$file"
    STAGE_FILE_METADATA["$stage_name:size"]=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file")
    STAGE_FILE_METADATA["$stage_name:mtime"]=$(stat -f%m "$file" 2>/dev/null || stat -c%Y "$file")

    ui_success "Staged: $file → $stage_name"
    return 0
}

stage_add_pattern() {
    # Add files matching a pattern to staging area
    # Args: $1 - glob pattern, $2 - base directory (optional, defaults to pwd)
    # Returns: 0 on success, count of files added
    local pattern="$1"
    local base_dir="${2:-.}"
    local count=0

    if [[ "$STAGE_ACTIVE" != "true" ]]; then
        ui_error "Stage not initialized"
        return 1
    fi

    # Find matching files
    while IFS= read -r -d '' file; do
        local relative_path="${file#$base_dir/}"
        stage_add "$file" "$relative_path"
        ((count++))
    done < <(find "$base_dir" -type f -name "$pattern" -print0)

    ui_info "Staged $count files matching pattern: $pattern"
    return 0
}

stage_remove() {
    # Remove a file from staging area
    # Args: $1 - stage name
    # Returns: 0 on success, 1 on failure
    local stage_name="$1"

    if [[ "$STAGE_ACTIVE" != "true" ]]; then
        ui_error "Stage not initialized"
        return 1
    fi

    # Check if file is staged
    if ! _stage_is_staged "$stage_name"; then
        ui_error "File not in stage: $stage_name"
        return 1
    fi

    # Remove file
    rm -f "$STAGE_ROOT/$stage_name"

    # Update tracking
    STAGE_FILES=("${STAGE_FILES[@]/$stage_name}")
    unset "STAGE_FILE_METADATA[$stage_name:original]"
    unset "STAGE_FILE_METADATA[$stage_name:size]"
    unset "STAGE_FILE_METADATA[$stage_name:mtime]"

    ui_success "Unstaged: $stage_name"
    return 0
}

stage_list() {
    # List all staged files
    # Args: none
    # Returns: 0 on success
    if [[ "$STAGE_ACTIVE" != "true" ]]; then
        ui_error "Stage not initialized"
        return 1
    fi

    if [[ ${#STAGE_FILES[@]} -eq 0 ]]; then
        echo "No files staged"
        return 0
    fi

    ui_table_header "Stage Name" "Original Path" "Size"
    for stage_name in "${STAGE_FILES[@]}"; do
        local original="${STAGE_FILE_METADATA[$stage_name:original]:-unknown}"
        local size="${STAGE_FILE_METADATA[$stage_name:size]:-0}"
        ui_table_row "$stage_name" "$original" "$(_stage_format_size "$size")"
    done

    return 0
}

stage_get_path() {
    # Get the staged file path
    # Args: $1 - stage name
    # Returns: 0 on success, prints path to stdout
    local stage_name="$1"

    if [[ "$STAGE_ACTIVE" != "true" ]]; then
        ui_error "Stage not initialized"
        return 1
    fi

    if ! _stage_is_staged "$stage_name"; then
        ui_error "File not in stage: $stage_name"
        return 1
    fi

    echo "$STAGE_ROOT/$stage_name"
    return 0
}

stage_count() {
    # Get count of staged files
    # Args: none
    # Returns: 0 on success, prints count to stdout
    echo "${#STAGE_FILES[@]}"
    return 0
}

stage_clear() {
    # Clear all staged files
    # Args: none
    # Returns: 0 on success
    if [[ "$STAGE_ACTIVE" != "true" ]]; then
        ui_warning "Stage not initialized"
        return 0
    fi

    # Remove all files
    rm -rf "${STAGE_ROOT:?}"/*

    # Clear tracking
    STAGE_FILES=()
    STAGE_FILE_METADATA=()

    ui_info "Stage cleared"
    return 0
}

stage_validate() {
    # Validate all staged files still exist and match metadata
    # Args: none
    # Returns: 0 if valid, 1 if any issues found
    if [[ "$STAGE_ACTIVE" != "true" ]]; then
        ui_error "Stage not initialized"
        return 1
    fi

    local issues=0

    for stage_name in "${STAGE_FILES[@]}"; do
        local staged_file="$STAGE_ROOT/$stage_name"

        # Check existence
        if [[ ! -f "$staged_file" ]]; then
            ui_error "Staged file missing: $stage_name"
            ((issues++))
            continue
        fi

        # Check size
        local expected_size="${STAGE_FILE_METADATA[$stage_name:size]}"
        local actual_size=$(stat -f%z "$staged_file" 2>/dev/null || stat -c%s "$staged_file")
        if [[ "$actual_size" != "$expected_size" ]]; then
            ui_warning "Size mismatch for $stage_name: expected $expected_size, got $actual_size"
            ((issues++))
        fi
    done

    if [[ $issues -eq 0 ]]; then
        ui_success "Stage validation passed"
        return 0
    else
        ui_error "Stage validation failed: $issues issues found"
        return 1
    fi
}

stage_commit() {
    # Commit staged files to output directory
    # Args: $1 - output directory
    # Returns: 0 on success, 1 on failure
    local output_dir="$1"

    if [[ "$STAGE_ACTIVE" != "true" ]]; then
        ui_error "Stage not initialized"
        return 1
    fi

    # Validate before commit
    if ! stage_validate; then
        ui_error "Stage validation failed, commit aborted"
        return 1
    fi

    # Create output directory
    mkdir -p "$output_dir"

    # Copy staged files
    local count=0
    for stage_name in "${STAGE_FILES[@]}"; do
        local staged_file="$STAGE_ROOT/$stage_name"
        local output_file="$output_dir/$stage_name"

        # Create parent directory if needed
        mkdir -p "$(dirname "$output_file")"

        if cp "$staged_file" "$output_file"; then
            ((count++))
        else
            ui_error "Failed to commit: $stage_name"
        fi
    done

    ui_success "Committed $count files to: $output_dir"
    return 0
}

# Private functions

_stage_is_staged() {
    # Check if a file is staged
    # Args: $1 - stage name
    # Returns: 0 if staged, 1 if not
    local stage_name="$1"

    for staged in "${STAGE_FILES[@]}"; do
        if [[ "$staged" == "$stage_name" ]]; then
            return 0
        fi
    done

    return 1
}

_stage_format_size() {
    # Format file size for display
    # Args: $1 - size in bytes
    # Returns: formatted size string
    local size="$1"

    if [[ $size -lt 1024 ]]; then
        echo "${size}B"
    elif [[ $size -lt $((1024 * 1024)) ]]; then
        echo "$((size / 1024))KB"
    elif [[ $size -lt $((1024 * 1024 * 1024)) ]]; then
        echo "$((size / 1024 / 1024))MB"
    else
        echo "$((size / 1024 / 1024 / 1024))GB"
    fi
}

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
