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
declare -g EXEC_LOG_FILE="${EXEC_LOG_FILE:-}"

# Public functions

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

    # Validate EXE_PATH is a real executable (security check)
    if [[ ! -x "${job_ref[EXE_PATH]}" ]]; then
        ui_error "exec_crystal_run: EXE_PATH is not an executable: ${job_ref[EXE_PATH]}"
        return 1
    fi

    # Build command array based on execution mode (avoiding eval for security)
    local -a cmd_array=()
    local cmd_display
    if [[ "${job_ref[MODE]}" == "Serial/OpenMP" ]]; then
        # Serial/OpenMP mode: direct execution
        # Note: OUTPUT to staging directory, stage_retrieve will rename to ${file_prefix}.out
        cmd_array=("${job_ref[EXE_PATH]}")
        cmd_display="${job_ref[EXE_PATH]} < INPUT > OUTPUT"
    else
        # Parallel/MPI mode: use mpirun
        if [[ -z "${job_ref[MPI_RANKS]:-}" ]]; then
            ui_error "exec_crystal_run: MPI_RANKS required for Parallel/MPI mode"
            return 1
        fi

        # Validate MPI_RANKS is a positive integer (security check)
        if ! [[ "${job_ref[MPI_RANKS]}" =~ ^[0-9]+$ ]] || [[ "${job_ref[MPI_RANKS]}" -lt 1 ]]; then
            ui_error "exec_crystal_run: MPI_RANKS must be a positive integer: ${job_ref[MPI_RANKS]}"
            return 1
        fi

        # Determine MPI binary location
        local mpi_bin
        if [[ -n "${I_MPI_ROOT:-}" ]]; then
            mpi_bin="${I_MPI_ROOT}/bin/mpirun"
        else
            mpi_bin="mpirun"
        fi

        cmd_array=("$mpi_bin" "-np" "${job_ref[MPI_RANKS]}" "${job_ref[EXE_PATH]}")
        cmd_display="$mpi_bin -np ${job_ref[MPI_RANKS]} ${job_ref[EXE_PATH]} < INPUT > OUTPUT"
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

    # Execute in background using array expansion (secure - no eval)
    # Redirect stdin from INPUT and stdout to OUTPUT
    "${cmd_array[@]}" < INPUT > OUTPUT 2>&1 &
    pid=$!

    if $has_gum; then
        # Use gum spinner with PID monitoring
        # Note: macOS tail doesn't support --pid, so we use a bash while loop
        gum spin --spinner globe --title "Computing... (Tail: OUTPUT)" -- bash -c "while kill -0 $pid 2>/dev/null; do sleep 0.1; done"
    fi

    # Wait for background process to complete
    wait $pid
    exit_code=$?

    # Log result and perform error analysis if failed
    if [[ $exit_code -eq 0 ]]; then
        _exec_log "SUCCESS" "CRYSTAL23 calculation" "$cmd_display"
    else
        _exec_log "FAILED" "CRYSTAL23 calculation" "$cmd_display" "$exit_code"
        cry_log error "Calculation failed with exit code: $exit_code"

        # Run error analysis
        local output_file="OUTPUT"
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
