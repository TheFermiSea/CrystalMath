#!/usr/bin/env bash
# cry-logging.sh - Logging infrastructure for CRY_CLI
# Provides structured logging with levels, timestamps, and color output

# Default log level (can be overridden by CRY_LOG_LEVEL env var)
: "${CRY_LOG_LEVEL:=info}"

# Get numeric log level value
_cry_log_level_value() {
    local level="$1"
    case "$level" in
        debug) echo 0 ;;
        info)  echo 1 ;;
        warn)  echo 2 ;;
        error) echo 3 ;;
        *)     echo -1 ;;
    esac
}

# Get color code for log level
_cry_log_color() {
    local level="$1"
    case "$level" in
        debug) echo "\033[0;36m" ;;  # Cyan
        info)  echo "\033[0;32m" ;;  # Green
        warn)  echo "\033[0;33m" ;;  # Yellow
        error) echo "\033[0;31m" ;;  # Red
        *)     echo "\033[0m" ;;     # Reset
    esac
}

# Check if terminal supports colors
_cry_supports_color() {
    [[ -t 2 ]] && [[ "${TERM:-}" != "dumb" ]] && command -v tput >/dev/null 2>&1
}

# Get current timestamp in ISO 8601 format
_cry_timestamp() {
    date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%SZ"
}

# Validate log level
_cry_valid_level() {
    local level="$1"
    case "$level" in
        debug|info|warn|error) return 0 ;;
        *) return 1 ;;
    esac
}

# Main logging function
# Usage: cry_log LEVEL MESSAGE...
cry_log() {
    local level="$1"
    shift
    local message="$*"

    # Validate log level
    if ! _cry_valid_level "$level"; then
        echo "[ERROR] Invalid log level: $level" >&2
        return 1
    fi

    # Check if this message should be logged based on CRY_LOG_LEVEL
    local current_level_value
    local threshold_level_value
    current_level_value=$(_cry_log_level_value "$level")
    threshold_level_value=$(_cry_log_level_value "$CRY_LOG_LEVEL")

    if [[ $current_level_value -lt $threshold_level_value ]]; then
        return 0  # Message filtered out
    fi

    # Format log message
    local timestamp
    timestamp=$(_cry_timestamp)
    local level_upper
    level_upper=$(echo "$level" | tr '[:lower:]' '[:upper:]')

    # Apply colors if supported
    if _cry_supports_color; then
        local color
        local reset
        color=$(_cry_log_color "$level")
        reset="\033[0m"
        echo -e "${color}[$timestamp] [$level_upper]${reset} $message" >&2
    else
        echo "[$timestamp] [$level_upper] $message" >&2
    fi

    return 0
}

# Fatal error logging - returns exit code without calling exit
# Usage: cry_fatal MESSAGE [EXIT_CODE]
cry_fatal() {
    local message="$1"
    local exit_code="${2:-1}"

    cry_log error "$message"
    return "$exit_code"
}

# Warning logging convenience function
# Usage: cry_warn MESSAGE...
cry_warn() {
    cry_log warn "$*"
}

# Info logging convenience function
# Usage: cry_info MESSAGE...
cry_info() {
    cry_log info "$*"
}

# Debug logging convenience function
# Usage: cry_debug MESSAGE...
cry_debug() {
    cry_log debug "$*"
}

# Export functions for use by other scripts
export -f cry_log
export -f cry_fatal
export -f cry_warn
export -f cry_info
export -f cry_debug
