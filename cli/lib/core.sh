#!/bin/bash
# Module: core
# Description: Core module loader and initialization system for CRY_CLI
# Dependencies: none (this is the base module)

# Error handling
set -euo pipefail

# Module-level constants
MODULE_NAME="core"
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

# Private functions

_core_init() {
    # Initialize core module
    # Returns: 0 on success
    _CRY_LOADED_MODULES[$MODULE_NAME]=1
    return 0
}

# Auto-initialize
_core_init
