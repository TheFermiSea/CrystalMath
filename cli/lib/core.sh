#!/bin/bash
# Module: core
# Description: Core module loader and initialization system for CRY_CLI
# Dependencies: none (this is the base module)

# Error handling
set -euo pipefail

# Module-level constants (non-readonly to avoid conflicts)
MODULE_NAME="core"
MODULE_VERSION="1.0.0"
readonly LIB_DIR="${LIB_DIR:-$(dirname "${BASH_SOURCE[0]}")}"

# Track loaded modules
declare -A _CRY_LOADED_MODULES=()

# Public functions

cry_require() {
    # Load a module if not already loaded
    # Args: $1 - module name (without .sh extension)
    # Returns: 0 on success, 1 if module not found, 2 if module fails to load
    local module_name="$1"
    local module_file="${LIB_DIR}/${module_name}.sh"

    # Check if already loaded
    if [[ -n "${_CRY_LOADED_MODULES[$module_name]:-}" ]]; then
        return 0
    fi

    # Check if module exists
    if [[ ! -f "$module_file" ]]; then
        echo "ERROR: Module not found: $module_name" >&2
        return 1
    fi

    # Source the module
    if ! source "$module_file"; then
        echo "ERROR: Failed to load module: $module_name" >&2
        return 2
    fi

    # Mark as loaded
    _CRY_LOADED_MODULES[$module_name]=1

    return 0
}

cry_require_all() {
    # Load all standard CRY_CLI modules
    # Args: none
    # Returns: 0 on success, non-zero on failure
    local modules=(
        "cry-ui"
        "cry-parallel"
        "cry-scratch"
        "cry-stage"
        "cry-exec"
        "cry-help"
    )

    local failed=0
    for module in "${modules[@]}"; do
        if ! cry_require "$module"; then
            ((failed++))
        fi
    done

    return $failed
}

cry_module_loaded() {
    # Check if a module is loaded
    # Args: $1 - module name
    # Returns: 0 if loaded, 1 if not
    local module_name="$1"
    [[ -n "${_CRY_LOADED_MODULES[$module_name]:-}" ]]
}

cry_list_modules() {
    # List all loaded modules
    # Args: none
    # Returns: 0 on success
    if [[ ${#_CRY_LOADED_MODULES[@]} -eq 0 ]]; then
        echo "No modules loaded"
        return 0
    fi

    echo "Loaded modules:"
    for module in "${!_CRY_LOADED_MODULES[@]}"; do
        echo "  - $module"
    done

    return 0
}

# Private functions

_core_init() {
    # Initialize core module
    # Returns: 0 on success
    _CRY_LOADED_MODULES[$MODULE_NAME]=1
    return 0
}

# Auto-initialize
_core_init
