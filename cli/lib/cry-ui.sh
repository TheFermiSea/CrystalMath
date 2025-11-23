#!/usr/bin/env bash
# Module: cry-ui
# Description: Visual components and terminal UI utilities with theme support
# Dependencies: cry-config.sh (for theme colors)

# Enable strict mode for better error handling
set -euo pipefail

# Prevent multiple sourcing
if [[ -n "${CRY_UI_LOADED:-}" ]]; then
    return 0
fi

# Mark as loaded
if [[ -n "${ZSH_VERSION:-}" ]]; then
    typeset -gr CRY_UI_LOADED=1
else
    declare -r CRY_UI_LOADED=1
fi

# Module-level constants (non-readonly to avoid conflicts with other modules)
MODULE_NAME="cry-ui"
MODULE_VERSION="1.0.0"

# User-space paths for gum installation
readonly USER_BIN="${CRY_USER_BIN:-$HOME/.local/bin}"
readonly USER_MAN="${CRY_USER_MAN:-$HOME/.local/share/man/man1}"

# Gum availability flag (set by ui_init)
HAS_GUM=false

# UI symbols
readonly UI_SYMBOL_CHECK="✓"
readonly UI_SYMBOL_CROSS="✗"
readonly UI_SYMBOL_ARROW="→"
readonly UI_SYMBOL_BULLET="•"
readonly UI_SYMBOL_SPINNER=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")

#===============================================================================
# Public Functions - Core UI Components
#===============================================================================

ui_init() {
    # Initialize UI module - bootstrap gum if missing
    # Returns: 0 on success

    # Check if gum is already available
    if [[ -f "$USER_BIN/gum" ]]; then
        export PATH="$USER_BIN:$PATH"
        HAS_GUM=true
        return 0
    fi

    if command -v gum &> /dev/null; then
        HAS_GUM=true
        return 0
    fi

    # Auto-bootstrap gum if network is available
    if ! ping -q -c 1 -W 1 github.com &> /dev/null; then
        echo ">> No network connection. UI features disabled." >&2
        return 0
    fi

    echo ">> Bootstrapping: 'gum' UI tool not found."
    echo ">> Installing to global user space ($USER_BIN)..."
    mkdir -p "$USER_BIN" "$USER_MAN"

    local TMP_INSTALL_DIR
    TMP_INSTALL_DIR=$(mktemp -d)

    if command -v go &> /dev/null; then
        # Use go install if available
        go install github.com/charmbracelet/gum@latest
        export PATH=$PATH:$(go env GOPATH)/bin
        HAS_GUM=true
    else
        # Download prebuilt binary
        local GUM_VER="0.14.5"
        local URL="https://github.com/charmbracelet/gum/releases/download/v${GUM_VER}/gum_${GUM_VER}_Linux_x86_64.tar.gz"

        if curl -L -o "$TMP_INSTALL_DIR/gum.tar.gz" "$URL" --silent; then
            tar -xzf "$TMP_INSTALL_DIR/gum.tar.gz" -C "$TMP_INSTALL_DIR"

            local FOUND_BIN FOUND_MAN
            FOUND_BIN=$(find "$TMP_INSTALL_DIR" -type f -name gum | head -n 1)
            FOUND_MAN=$(find "$TMP_INSTALL_DIR" -type f -name "gum.1" | head -n 1)

            if [[ -f "$FOUND_BIN" ]]; then
                mv "$FOUND_BIN" "$USER_BIN/"
                chmod +x "$USER_BIN/gum"
                [[ -f "$FOUND_MAN" ]] && mv "$FOUND_MAN" "$USER_MAN/"
                export PATH="$USER_BIN:$PATH"
                HAS_GUM=true
            else
                echo ">> Error: Failed to install gum. UI disabled." >&2
            fi
        else
            echo ">> Error: Failed to download gum. UI disabled." >&2
        fi
    fi

    rm -rf "$TMP_INSTALL_DIR"
    return 0
}

ui_banner() {
    # Display ASCII art banner for CRYSTAL23
    # Returns: 0 on success

    if ! $HAS_GUM; then
        echo "CRYSTAL 23"
        return 0
    fi

    cat << "EOF" | gum style --foreground ${C_PRIMARY:-39}
   ____________  ________________    __   ___  _____
  / ____/ __ \ \/ / ___/_  __/   |  / /  |__ \|__  /
 / /   / /_/ /\  /\__ \ / / / /| | / /   __/ / /_ <
/ /___/ _, _/ / /___/ // / / ___ |/ /___/ __/___/ /
\____/_/ |_| /_//____//_/ /_/  |_/_____/____/____/
EOF
    return 0
}

ui_card() {
    # Display a bordered card with title and content lines
    # Args: $1 - title, $2+ - body lines
    # Returns: 0 on success

    local title="$1"
    shift

    if $HAS_GUM; then
        gum style --border rounded --margin "1 0" --padding "0 2" --border-foreground ${C_PRIMARY:-39} \
            "$(gum style --foreground ${C_SEC:-86} --bold "$title")" \
            "" \
            "$@"
    else
        echo "--- $title ---"
        for line in "$@"; do
            echo "$line"
        done
        echo "-----------------"
    fi

    return 0
}

ui_status_line() {
    # Display a label: value status line
    # Args: $1 - label, $2 - value
    # Returns: 0 on success

    local label="$1"
    local value="$2"

    if $HAS_GUM; then
        echo "$(gum style --foreground ${C_DIM:-240} "$label:") $(gum style --foreground ${C_TEXT:-255} --bold "$value")"
    else
        echo "$label: $value"
    fi

    return 0
}

ui_file_found() {
    # Display a "file found" message
    # Args: $1 - file path
    # Returns: 0 on success

    local file_path="$1"

    if $HAS_GUM; then
        echo "$(gum style --foreground ${C_SEC:-86} "✓ Found:") $file_path"
    else
        echo "[OK] Found: $file_path"
    fi

    return 0
}

ui_success() {
    # Display a success message
    # Args: $1 - message text
    # Returns: 0 on success

    local message="$1"

    if $HAS_GUM; then
        echo "$(gum style --foreground ${C_SEC:-86} "$UI_SYMBOL_CHECK") $message"
    else
        echo "$UI_SYMBOL_CHECK $message"
    fi

    return 0
}

ui_error() {
    # Display an error message
    # Args: $1 - message text
    # Returns: 0 on success

    local message="$1"

    if $HAS_GUM; then
        echo "$(gum style --foreground ${C_ERR:-196} --bold "ERROR:") $message" >&2
    else
        echo "ERROR: $message" >&2
    fi

    return 0
}

ui_warning() {
    # Display a warning message
    # Args: $1 - message text
    # Returns: 0 on success

    local message="$1"

    if $HAS_GUM; then
        echo "$(gum style --foreground ${C_WARN:-214} --bold "WARNING:") $message"
    else
        echo "WARNING: $message"
    fi

    return 0
}

ui_info() {
    # Display an info message
    # Args: $1 - message text
    # Returns: 0 on success

    local message="$1"

    if $HAS_GUM; then
        echo "$(gum style --foreground ${C_PRIMARY:-39} "$UI_SYMBOL_ARROW") $message"
    else
        echo "$UI_SYMBOL_ARROW $message"
    fi

    return 0
}

ui_progress() {
    # Display a progress indicator
    # Args: $1 - current step, $2 - total steps, $3 - description
    # Returns: 0 on success

    local current="$1"
    local total="$2"
    local description="${3:-}"

    local percentage=$(( current * 100 / total ))
    local bar_width=40
    local filled=$(( current * bar_width / total ))
    local empty=$(( bar_width - filled ))

    printf "\r["
    printf "%${filled}s" | tr ' ' '='
    printf "%${empty}s" | tr ' ' ' '
    printf "] %3d%% %s" "$percentage" "$description"

    if [[ $current -eq $total ]]; then
        echo ""
    fi

    return 0
}

ui_spinner_start() {
    # Start a spinner animation (runs in background)
    # Args: $1 - message text
    # Returns: PID of spinner process

    local message="$1"
    local i=0

    (
        while true; do
            printf "\r%s %s" "${UI_SYMBOL_SPINNER[$i]}" "$message"
            i=$(( (i + 1) % ${#UI_SYMBOL_SPINNER[@]} ))
            sleep 0.1
        done
    ) &

    echo $!
    return 0
}

ui_spinner_stop() {
    # Stop a spinner animation
    # Args: $1 - spinner PID, $2 - success/failure (optional)
    # Returns: 0 on success
    local spinner_pid="$1"
    local result="${2:-success}"

    kill "$spinner_pid" 2>/dev/null || true
    wait "$spinner_pid" 2>/dev/null || true
    printf "\r"

    if [[ "$result" == "success" ]]; then
        ui_success "Done"
    else
        ui_error "Failed"
    fi

    return 0
}

ui_spin() {
    # Execute a command with a spinner or progress indicator
    # Args: $1 - title/message, $2 - command to execute
    # Returns: command exit status

    local title="$1"
    local command="$2"

    if $HAS_GUM; then
        gum spin --spinner dot --title "$title" -- bash -c "$command"
        return $?
    else
        # Fallback without gum - just run command with simple output
        echo ">> $title..."
        eval "$command"
        return $?
    fi
}

ui_prompt() {
    # Display a prompt and get user input
    # Args: $1 - prompt text, $2 - default value (optional)
    # Returns: 0 on success, prints input to stdout

    local prompt="$1"
    local default="${2:-}"
    local input

    if $HAS_GUM; then
        if [[ -n "$default" ]]; then
            gum input --placeholder "$default" --prompt "$prompt: " --value "$default"
        else
            gum input --prompt "$prompt: "
        fi
    else
        if [[ -n "$default" ]]; then
            read -rp "$prompt [$default]: " input
            echo "${input:-$default}"
        else
            read -rp "$prompt: " input
            echo "$input"
        fi
    fi

    return 0
}

ui_confirm() {
    # Display a yes/no confirmation prompt
    # Args: $1 - prompt text, $2 - default (y/n, optional)
    # Returns: 0 for yes, 1 for no

    local prompt="$1"
    local default="${2:-n}"
    local response

    if $HAS_GUM; then
        gum confirm "$prompt" && return 0 || return 1
    else
        if [[ "$default" == "y" ]]; then
            read -rp "? $prompt [Y/n]: " response
            response="${response:-y}"
        else
            read -rp "? $prompt [y/N]: " response
            response="${response:-n}"
        fi
        [[ "$response" =~ ^[Yy]$ ]]
    fi
}

ui_list() {
    # Display a formatted list
    # Args: $@ - list items
    # Returns: 0 on success

    for item in "$@"; do
        echo "  $UI_SYMBOL_BULLET $item"
    done

    return 0
}

ui_table_header() {
    # Display a table header
    # Args: $@ - column headers
    # Returns: 0 on success

    local cols=("$@")
    local col_width=20

    for col in "${cols[@]}"; do
        printf "%-${col_width}s" "$col"
    done
    printf "\n"

    for col in "${cols[@]}"; do
        printf "%${col_width}s" | tr ' ' '-'
    done
    printf "\n"

    return 0
}

ui_table_row() {
    # Display a table row
    # Args: $@ - column values
    # Returns: 0 on success
    local cols=("$@")
    local col_width=20

    for col in "${cols[@]}"; do
        printf "%-${col_width}s" "$col"
    done
    printf "\n"

    return 0
}

ui_section_header() {
    # Display a bold section header for explain mode
    # Args: $1 - section text
    # Returns: 0 on success
    local section_text="$1"

    if $HAS_GUM; then
        gum style --foreground ${C_SEC:-86} --bold "$section_text"
    else
        echo "$section_text"
    fi

    return 0
}

#===============================================================================
# Private Helper Functions
#===============================================================================

_ui_get_terminal_width() {
    # Get the current terminal width
    # Returns: terminal width or 80 as default
    tput cols 2>/dev/null || echo 80
}

#===============================================================================
# Module Initialization
#===============================================================================

# Auto-initialize on source (checks for gum and sets HAS_GUM flag)
ui_init
