#!/bin/bash
# Module: cry-exec
# Description: Execution engine for crystallization operations
# Dependencies: core, cry-ui, cry-parallel, cry-scratch, cry-stage

# Error handling
set -euo pipefail

# Module-level constants
MODULE_NAME="cry-exec"
MODULE_VERSION="1.0.0"

# Execution tracking
declare -g EXEC_DRY_RUN="${EXEC_DRY_RUN:-false}"
declare -g EXEC_VERBOSE="${EXEC_VERBOSE:-false}"
declare -g EXEC_LOG_FILE="${EXEC_LOG_FILE:-}"
declare -ga EXEC_HISTORY=()

# Public functions

exec_init() {
    # Initialize execution engine
    # Args: $1 - dry run (true/false, optional), $2 - verbose (true/false, optional)
    # Returns: 0 on success
    local dry_run="${1:-$EXEC_DRY_RUN}"
    local verbose="${2:-$EXEC_VERBOSE}"

    EXEC_DRY_RUN="$dry_run"
    EXEC_VERBOSE="$verbose"

    if [[ "$EXEC_DRY_RUN" == "true" ]]; then
        ui_info "Execution engine initialized (DRY RUN mode)"
    else
        ui_info "Execution engine initialized"
    fi

    return 0
}

exec_run() {
    # Execute a command with tracking and logging
    # Args: $1 - command description, $2... - command and arguments
    # Returns: command exit code
    local description="$1"
    shift
    local cmd=("$@")

    # Log execution
    _exec_log "START" "$description" "${cmd[*]}"

    # Show command if verbose or dry run
    if [[ "$EXEC_VERBOSE" == "true" ]] || [[ "$EXEC_DRY_RUN" == "true" ]]; then
        ui_info "Executing: ${cmd[*]}"
    fi

    # Execute or simulate
    local status=0
    if [[ "$EXEC_DRY_RUN" == "true" ]]; then
        ui_warning "[DRY RUN] Would execute: ${cmd[*]}"
    else
        if "${cmd[@]}"; then
            _exec_log "SUCCESS" "$description" "${cmd[*]}"
            ui_success "$description"
        else
            status=$?
            _exec_log "FAILED" "$description" "${cmd[*]}" "$status"
            ui_error "$description (exit code: $status)"
        fi
    fi

    # Track in history
    EXEC_HISTORY+=("$description")

    return $status
}

analyze_failure() {
    # Analyze CRYSTAL23 output for common errors
    # Args: $1 - path to output file
    # Returns: 0 always (analysis is informational)

    local logfile="$1"

    if [[ ! -f "$logfile" ]]; then
        ui_error "Output file not found: $logfile"
        return 0
    fi

    cry_log info "Analyzing failure in $logfile"

    # Check if gum is available
    local has_gum=false
    if command -v gum &> /dev/null; then
        has_gum=true
    fi

    # Check for SCF divergence
    if grep -q "DIVERGENCE" "$logfile" || grep -q "SCF NOT CONVERGED" "$logfile"; then
        if $has_gum; then
            gum style --foreground 214 "⚠️  Detected SCF Divergence"
        else
            echo "⚠️  Detected SCF Divergence"
        fi
        echo "The calculation is unstable. Try:"
        echo "1. Check your geometry (atoms too close?)"
        echo "2. Use a better initial guess (GUESSP)"
        echo "3. Increase FMIXING (e.g., FMIXING 30)"
        echo ""
        return 0
    fi

    # Check for memory errors
    if grep -q "insufficient memory" "$logfile" || grep -q "SIGSEGV" "$logfile" || grep -q "Segmentation fault" "$logfile"; then
        if $has_gum; then
            gum style --foreground 214 "⚠️  Memory Error Detected"
        else
            echo "⚠️  Memory Error Detected"
        fi
        echo "The job ran out of memory."
        echo "Try increasing the number of MPI ranks (e.g., runcrystal input 14)"
        echo "This spreads the memory load across more processes."
        echo ""
        return 0
    fi

    # Check for basis set issues
    if grep -q "BASIS SET" "$logfile" && grep -q "ERROR" "$logfile"; then
        if $has_gum; then
            gum style --foreground 214 "⚠️  Basis Set Error"
        else
            echo "⚠️  Basis Set Error"
        fi
        echo "Problem with basis set definition."
        echo "1. Check BS keyword syntax in your .d12 file"
        echo "2. Verify atomic numbers match basis set library"
        echo "3. Try using a standard basis set (e.g., STO-3G)"
        echo ""
        return 0
    fi

    # No specific error detected
    if $has_gum; then
        gum style --foreground 245 "No specific known error pattern detected."
    else
        echo "No specific known error pattern detected."
    fi
    echo "Check the error log below for details."
    echo ""
}

exec_crystal_run() {
    # Execute CRYSTAL23 calculation based on job state
    # Args: $1 - name reference to CRY_JOB associative array
    # Returns: exit code from crystal/mpirun execution
    #
    # Required job_state keys:
    #   - MODE: "Serial/OpenMP" or "Parallel/MPI"
    #   - EXE_PATH: full path to crystal executable
    #   - MPI_RANKS: number of MPI ranks (for parallel mode)
    #   - file_prefix: base name for output file
    #
    # Example usage:
    #   declare -A job_state=(
    #       [MODE]="Parallel/MPI"
    #       [EXE_PATH]="/path/to/PcrystalOMP"
    #       [MPI_RANKS]="4"
    #       [file_prefix]="mysim"
    #   )
    #   exec_crystal_run job_state

    local -n job_ref=$1

    # Validate required keys
    if [[ -z "${job_ref[MODE]:-}" ]] || [[ -z "${job_ref[EXE_PATH]:-}" ]] || \
       [[ -z "${job_ref[file_prefix]:-}" ]]; then
        ui_error "exec_crystal_run: Missing required job state keys (MODE, EXE_PATH, file_prefix)"
        return 1
    fi

    # Build command based on execution mode
    local cmd
    if [[ "${job_ref[MODE]}" == "Serial/OpenMP" ]]; then
        # Serial/OpenMP mode: direct execution
        cmd="${job_ref[EXE_PATH]} < INPUT > ${job_ref[file_prefix]}.out"
    else
        # Parallel/MPI mode: use mpirun
        if [[ -z "${job_ref[MPI_RANKS]:-}" ]]; then
            ui_error "exec_crystal_run: MPI_RANKS required for Parallel/MPI mode"
            return 1
        fi

        # Determine MPI binary location
        local mpi_bin
        if [[ -n "${I_MPI_ROOT:-}" ]]; then
            mpi_bin="${I_MPI_ROOT}/bin/mpirun"
        else
            mpi_bin="mpirun"
        fi

        cmd="$mpi_bin -np ${job_ref[MPI_RANKS]} ${job_ref[EXE_PATH]} < INPUT > ${job_ref[file_prefix]}.out"
    fi

    # Check if gum is available for spinner
    local has_gum=false
    if command -v gum &> /dev/null; then
        has_gum=true
    fi

    # Execute with or without gum spinner
    local exit_code=0
    local pid
    echo ""

    if $has_gum; then
        # Use gum for launch message
        gum style --foreground 86 ">> Launching Calculation..."
    else
        echo ">> Launching Calculation..."
    fi
    echo ""

    # Execute in background to enable live monitoring
    eval "$cmd" 2>&1 &
    pid=$!

    if $has_gum; then
        # Use gum spinner with PID monitoring
        # Note: macOS tail doesn't support --pid, so we use a bash while loop
        gum spin --spinner globe --title "Computing... (Tail: ${job_ref[file_prefix]}.out)" -- bash -c "while kill -0 $pid 2>/dev/null; do sleep 0.1; done"
    fi

    # Wait for background process to complete
    wait $pid
    exit_code=$?

    # Log result and perform error analysis if failed
    if [[ $exit_code -eq 0 ]]; then
        _exec_log "SUCCESS" "CRYSTAL23 calculation" "$cmd"
    else
        _exec_log "FAILED" "CRYSTAL23 calculation" "$cmd" "$exit_code"
        cry_log error "Calculation failed with exit code: $exit_code"

        # Run error analysis
        local output_file="${job_ref[file_prefix]}.out"
        if [[ -f "$output_file" ]]; then
            analyze_failure "$output_file"

            # Show error log tail with border
            if $has_gum; then
                gum style --border double --border-foreground 214 --foreground 214 --padding "0 1" \
                    "Error Log (Last 20 lines)"
            else
                echo "--- Error Log (Last 20 lines) ---"
            fi
            tail -n 20 "$output_file"
            echo ""
        fi
    fi

    return $exit_code
}

exec_stage_transform() {
    # Execute a transformation on staged files
    # Args: $1 - transformation command template (use {} for input, {output} for output)
    # Returns: 0 on success, non-zero on failure
    local cmd_template="$1"

    # Get staged files
    local stage_count
    stage_count=$(stage_count)

    if [[ $stage_count -eq 0 ]]; then
        ui_warning "No files in stage"
        return 0
    fi

    # Process each staged file
    local failed=0
    local processed=0

    for stage_name in "${STAGE_FILES[@]}"; do
        local input_file
        if ! input_file=$(stage_get_path "$stage_name"); then
            ((failed++))
            continue
        fi

        local output_file="${input_file}.out"
        local cmd="${cmd_template//\{\}/$input_file}"
        cmd="${cmd//\{output\}/$output_file}"

        if exec_run "Transform: $stage_name" bash -c "$cmd"; then
            # Replace original with transformed output if exists
            if [[ -f "$output_file" ]]; then
                mv "$output_file" "$input_file"
            fi
            ((processed++))
        else
            ((failed++))
        fi
    done

    ui_info "Processed $processed files ($failed failed)"
    return $failed
}

exec_parallel_transform() {
    # Execute transformations on staged files in parallel
    # Args: $1 - transformation command template, $2 - max parallel jobs (optional)
    # Returns: 0 on success, non-zero on failure
    local cmd_template="$1"
    local max_jobs="${2:-$PARALLEL_MAX_JOBS}"

    # Initialize parallel execution
    parallel_init "$max_jobs"

    # Get staged files
    local stage_count
    stage_count=$(stage_count)

    if [[ $stage_count -eq 0 ]]; then
        ui_warning "No files in stage"
        return 0
    fi

    # Queue transformations
    for stage_name in "${STAGE_FILES[@]}"; do
        local input_file
        if ! input_file=$(stage_get_path "$stage_name"); then
            continue
        fi

        local output_file="${input_file}.out"
        local cmd="${cmd_template//\{\}/$input_file}"
        cmd="${cmd//\{output\}/$output_file}"

        parallel_run "transform_$stage_name" bash -c "$cmd"
    done

    # Wait for all to complete
    local failed=0
    if ! parallel_wait_all; then
        failed=$?
    fi

    # Replace originals with outputs
    for stage_name in "${STAGE_FILES[@]}"; do
        local input_file
        if ! input_file=$(stage_get_path "$stage_name"); then
            continue
        fi

        local output_file="${input_file}.out"
        if [[ -f "$output_file" ]]; then
            mv "$output_file" "$input_file"
        fi
    done

    ui_info "Parallel transformation completed"
    return $failed
}

exec_pipeline() {
    # Execute a pipeline of commands on staged files
    # Args: $@ - pipeline stages (command templates)
    # Returns: 0 on success, non-zero on failure
    local stages=("$@")
    local stage_num=0

    for stage in "${stages[@]}"; do
        ((stage_num++))
        ui_header "Pipeline Stage $stage_num"

        if ! exec_stage_transform "$stage"; then
            ui_error "Pipeline failed at stage $stage_num"
            return 1
        fi
    done

    ui_success "Pipeline completed: $stage_num stages"
    return 0
}

exec_history() {
    # Show execution history
    # Args: none
    # Returns: 0 on success
    if [[ ${#EXEC_HISTORY[@]} -eq 0 ]]; then
        echo "No execution history"
        return 0
    fi

    echo "Execution History:"
    local i=1
    for entry in "${EXEC_HISTORY[@]}"; do
        echo "  $i. $entry"
        ((i++))
    done

    return 0
}

exec_set_log() {
    # Set log file for execution tracking
    # Args: $1 - log file path
    # Returns: 0 on success
    local log_file="$1"

    EXEC_LOG_FILE="$log_file"

    # Create log file with header
    {
        echo "=== CRY Execution Log ==="
        echo "Started: $(date)"
        echo ""
    } > "$log_file"

    ui_info "Logging to: $log_file"
    return 0
}

exec_dry_run() {
    # Enable or disable dry run mode
    # Args: $1 - enable (true/false)
    # Returns: 0 on success
    local enable="$1"

    EXEC_DRY_RUN="$enable"

    if [[ "$enable" == "true" ]]; then
        ui_info "Dry run mode enabled"
    else
        ui_info "Dry run mode disabled"
    fi

    return 0
}

exec_verbose() {
    # Enable or disable verbose mode
    # Args: $1 - enable (true/false)
    # Returns: 0 on success
    local enable="$1"

    EXEC_VERBOSE="$enable"

    if [[ "$enable" == "true" ]]; then
        ui_info "Verbose mode enabled"
    else
        ui_info "Verbose mode disabled"
    fi

    return 0
}

# Private functions

_exec_log() {
    # Log execution details to file
    # Args: $1 - status, $2 - description, $3 - command, $4 - exit code (optional)
    # Returns: 0 on success
    local status="$1"
    local description="$2"
    local cmd="$3"
    local exit_code="${4:-0}"

    if [[ -z "$EXEC_LOG_FILE" ]]; then
        return 0
    fi

    {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$status] $description"
        echo "  Command: $cmd"
        if [[ -n "$exit_code" ]] && [[ "$exit_code" != "0" ]]; then
            echo "  Exit Code: $exit_code"
        fi
        echo ""
    } >> "$EXEC_LOG_FILE"

    return 0
}

_exec_validate_command() {
    # Validate command before execution (basic safety checks)
    # Args: $@ - command and arguments
    # Returns: 0 if safe, 1 if potentially dangerous
    local cmd=("$@")

    # Check for dangerous commands
    local dangerous_patterns=("rm -rf /" "dd if=" "> /dev/" "mkfs" "format")

    for pattern in "${dangerous_patterns[@]}"; do
        if [[ "${cmd[*]}" == *"$pattern"* ]]; then
            ui_error "Potentially dangerous command detected: ${cmd[*]}"
            return 1
        fi
    done

    return 0
}

_exec_init() {
    # Initialize exec module
    # Returns: 0 on success
    return 0
}

# Auto-initialize
_exec_init
