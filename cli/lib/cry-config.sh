#!/usr/bin/env bash
# cry-config.sh - Central configuration module for CRY_CLI
# Provides path exports, color themes, and configuration management

# Enable strict mode for better error handling
set -euo pipefail

# Prevent multiple sourcing
[[ -n "${CRY_CONFIG_LOADED:-}" ]] && return 0
if [[ -n "${ZSH_VERSION:-}" ]]; then
    typeset -gr CRY_CONFIG_LOADED=1
else
    declare -r CRY_CONFIG_LOADED=1
fi

#===============================================================================
# Core Configuration
#===============================================================================

cry_config_init() {
    # Core paths with environment variable override support
    : "${CRY23_ROOT:="$HOME/CRYSTAL23"}"
    : "${CRY_VERSION:="v1.0.1"}"
    : "${CRY_ARCH:="Linux-ifort_i64_omp"}"
    : "${CRY_SCRATCH_BASE:="$HOME/tmp_crystal"}"

    # Derived paths
    CRY_BIN_DIR="$CRY23_ROOT/bin/$CRY_ARCH/$CRY_VERSION"
    BIN_DIR="$CRY_BIN_DIR"  # Backward compatibility alias
    SCRATCH_BASE="$CRY_SCRATCH_BASE"  # Backward compatibility alias

    # User-space paths
    : "${CRY_USER_BIN:="$HOME/.local/bin"}"
    : "${CRY_USER_MAN:="$HOME/.local/share/man/man1"}"

    # Tutorial paths - default to share/tutorials in project root
    # cry-config.sh is in lib/, so go up one level to project root
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
    : "${CRY_TUTORIAL_DIR:="$PROJECT_ROOT/share/tutorials"}"
    TUTORIAL_DIR="$CRY_TUTORIAL_DIR"  # Backward compatibility alias

    # Export all configuration variables
    export CRY23_ROOT CRY_VERSION CRY_ARCH CRY_BIN_DIR BIN_DIR CRY_SCRATCH_BASE SCRATCH_BASE
    export CRY_USER_BIN CRY_USER_MAN CRY_TUTORIAL_DIR TUTORIAL_DIR

    # Load optional configuration file
    _cry_load_config_file

    # Initialize file staging maps
    _cry_init_stage_maps
}

#===============================================================================
# Theme Colors (ANSI Codes for Gum)
#===============================================================================

if [[ -n "${ZSH_VERSION:-}" ]]; then
    typeset -gr C_PRIMARY="39"   # Sapphire Blue
    typeset -gr C_SEC="86"       # Teal
    typeset -gr C_WARN="214"     # Orange
    typeset -gr C_ERR="196"      # Red
    typeset -gr C_TEXT="255"     # White
    typeset -gr C_DIM="240"      # Gray
else
    declare -r C_PRIMARY="39"
    declare -r C_SEC="86"
    declare -r C_WARN="214"
    declare -r C_ERR="196"
    declare -r C_TEXT="255"
    declare -r C_DIM="240"
fi

# Export theme colors for subshells
export C_PRIMARY C_SEC C_WARN C_ERR C_TEXT C_DIM

#===============================================================================
# File Staging Maps
#===============================================================================

# Map of source:destination pairs for staging files to work directory
if [[ -n "${ZSH_VERSION:-}" ]]; then
    typeset -gA STAGE_MAP=(
        [gui]="fort.34"
        [f9]="fort.20"
        [f98]="fort.98"
        [hessopt]="HESSOPT.DAT"
        [born]="BORN.DAT"
    )

    # Map of work_file:output_file pairs for retrieving results
    typeset -gA RETRIEVE_MAP=(
        [fort.9]="f9"
        [fort.98]="f98"
        [HESSOPT.DAT]="hessopt"
        [OPTINFO.DAT]="optinfo"
        [FREQINFO.DAT]="freqinfo"
    )
elif [[ "${BASH_VERSINFO:-0}" -ge 4 ]]; then
    # Bash 4.0+ supports associative arrays
    declare -A STAGE_MAP=(
        ["gui"]="fort.34"
        ["f9"]="fort.20"
        ["f98"]="fort.98"
        ["hessopt"]="HESSOPT.DAT"
        ["born"]="BORN.DAT"
    )

    # Map of work_file:output_file pairs for retrieving results
    declare -A RETRIEVE_MAP=(
        ["fort.9"]="f9"
        ["fort.98"]="f98"
        ["HESSOPT.DAT"]="hessopt"
        ["OPTINFO.DAT"]="optinfo"
        ["FREQINFO.DAT"]="freqinfo"
    )
else
    # Fallback: Use colon-delimited strings for bash < 4.0
    # Format: "key:value;key:value;..."
    STAGE_MAP="gui:fort.34;f9:fort.20;f98:fort.98;hessopt:HESSOPT.DAT;born:BORN.DAT"
    RETRIEVE_MAP="fort.9:f9;fort.98:f98;HESSOPT.DAT:hessopt;OPTINFO.DAT:optinfo;FREQINFO.DAT:freqinfo"
fi

#===============================================================================
# Helper Functions
#===============================================================================

cry_config_get() {
    # Get value of a configuration variable
    # Usage: cry_config_get VAR_NAME
    local var_name="$1"

    if [[ -z "$var_name" ]]; then
        echo "Error: Variable name required" >&2
        return 1
    fi

    # Use indirect variable expansion (compatible with bash and zsh)
    if [[ -n "${ZSH_VERSION:-}" ]]; then
        # zsh syntax
        printf '%s\n' "${(P)var_name}"
    else
        # bash syntax
        printf '%s\n' "${!var_name}"
    fi
}

_cry_load_config_file() {
    # Load optional configuration file
    local config_file="${CRY_CONFIG_FILE:-$HOME/.config/cry/cry.conf}"

    if [[ -f "$config_file" ]]; then
        # Source config file in subshell to prevent pollution
        # Only export variables that start with CRY_ or C_
        while IFS='=' read -r key value; do
            # Skip comments and empty lines
            [[ "$key" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$key" ]] && continue

            # Only allow CRY_ or C_ prefixed variables
            if [[ "$key" =~ ^(CRY_|C_) ]]; then
                # Remove quotes from value if present
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"

                # Export the variable
                export "$key=$value"
            fi
        done < "$config_file"
    fi
}

_cry_init_stage_maps() {
    # Initialize file staging maps
    # This function can be extended to load custom mappings from config

    # Export maps for use in other modules
    export STAGE_MAP
    export RETRIEVE_MAP
}

_cry_show_map() {
    # Display a map in human-readable format
    local map_name="$1"

    if [[ -n "${ZSH_VERSION:-}" ]]; then
        # zsh associative array
        local -A map_ref
        eval "map_ref=(\"\${(@kv)$map_name}\")"
        for key in "${(@k)map_ref}"; do
            printf "  %-20s -> %s\n" "$key" "${map_ref[$key]}"
        done | sort
    elif [[ "${BASH_VERSINFO:-0}" -ge 4 ]]; then
        # bash 4.0+ associative array
        eval "local keys=(\"\${!$map_name[@]}\")"
        for key in "${keys[@]}"; do
            eval "local value=\"\${$map_name[\$key]}\""
            printf "  %-20s -> %s\n" "$key" "$value"
        done | sort
    else
        # bash 3.x fallback: parse colon-delimited string
        eval "local map_string=\"\$$map_name\""
        IFS=';' read -ra pairs <<< "$map_string"
        for pair in "${pairs[@]}"; do
            IFS=':' read -r key value <<< "$pair"
            printf "  %-20s -> %s\n" "$key" "$value"
        done | sort
    fi
}

cry_stage_map_get() {
    # Get value from STAGE_MAP (works with all shell versions)
    local key="$1"

    if [[ -n "${ZSH_VERSION:-}" ]] || [[ "${BASH_VERSINFO:-0}" -ge 4 ]]; then
        printf '%s\n' "${STAGE_MAP[$key]}"
    else
        # Parse string format
        IFS=';' read -ra pairs <<< "$STAGE_MAP"
        for pair in "${pairs[@]}"; do
            IFS=':' read -r k v <<< "$pair"
            if [[ "$k" == "$key" ]]; then
                printf '%s\n' "$v"
                return 0
            fi
        done
        return 1
    fi
}

cry_retrieve_map_get() {
    # Get value from RETRIEVE_MAP (works with all shell versions)
    local key="$1"

    if [[ -n "${ZSH_VERSION:-}" ]] || [[ "${BASH_VERSINFO:-0}" -ge 4 ]]; then
        printf '%s\n' "${RETRIEVE_MAP[$key]}"
    else
        # Parse string format
        IFS=';' read -ra pairs <<< "$RETRIEVE_MAP"
        for pair in "${pairs[@]}"; do
            IFS=':' read -r k v <<< "$pair"
            if [[ "$k" == "$key" ]]; then
                printf '%s\n' "$v"
                return 0
            fi
        done
        return 1
    fi
}

cry_config_validate() {
    # Validate configuration paths and dependencies
    local errors=0

    # Check if CRYSTAL23 directory exists
    if [[ ! -d "$CRY23_ROOT" ]]; then
        echo "Error: CRYSTAL23 directory not found: $CRY23_ROOT" >&2
        ((errors++))
    fi

    # Check if binary directory exists
    if [[ ! -d "$CRY_BIN_DIR" ]]; then
        echo "Error: Binary directory not found: $CRY_BIN_DIR" >&2
        ((errors++))
    fi

    # Check if crystal executable exists
    if [[ ! -x "$CRY_BIN_DIR/crystal" ]]; then
        echo "Error: crystal executable not found or not executable: $CRY_BIN_DIR/crystal" >&2
        ((errors++))
    fi

    return "$errors"
}

cry_config_show() {
    # Display current configuration
    cat <<EOF
CRY_CLI Configuration:
  CRY23_ROOT:        $CRY23_ROOT
  CRY_VERSION:       $CRY_VERSION
  CRY_ARCH:          $CRY_ARCH
  CRY_BIN_DIR:       $CRY_BIN_DIR
  CRY_SCRATCH_BASE:  $CRY_SCRATCH_BASE
  CRY_USER_BIN:      $CRY_USER_BIN
  CRY_USER_MAN:      $CRY_USER_MAN
  CRY_TUTORIAL_DIR:  $CRY_TUTORIAL_DIR

Theme Colors:
  C_PRIMARY:         $C_PRIMARY (Sapphire Blue)
  C_SEC:             $C_SEC (Teal)
  C_WARN:            $C_WARN (Orange)
  C_ERR:             $C_ERR (Red)
  C_TEXT:            $C_TEXT (White)
  C_DIM:             $C_DIM (Gray)

File Staging Mappings:
$(_cry_show_map STAGE_MAP)

File Retrieval Mappings:
$(_cry_show_map RETRIEVE_MAP)
EOF
}

#===============================================================================
# Module Initialization
#===============================================================================

# Auto-initialize on source (can be disabled with CRY_NO_AUTO_INIT=1)
if [[ -z "${CRY_NO_AUTO_INIT:-}" ]]; then
    cry_config_init
fi
