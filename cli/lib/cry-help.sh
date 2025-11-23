#!/usr/bin/env bash
# cry-help.sh - Interactive help system for CRYSTAL23
# Extracted from runcrystal.monolithic lines 120-224
# Dependencies: cry-ui.sh (for ui_banner), cry-config.sh (for theme colors)

# Enable strict mode for better error handling
set -euo pipefail

# Show tutorial file with soft-wrap
show_tutorial() {
    local TOPIC="$1"
    # Look for the file in the dedicated tutorial directory
    local FILE="$TUTORIAL_DIR/$TOPIC"

    if [ ! -f "$FILE" ]; then
        gum style --foreground "$C_ERR" "Error: Tutorial file not found: $FILE"
        echo "Please ensure tutorials are installed in $TUTORIAL_DIR"
        return
    fi

    # Use soft-wrap to fix the display issue
    gum pager --soft-wrap < "$FILE"
}

# Display the main help menu with interactive navigation
help_show_main() {
    if ! $HAS_GUM; then
        echo "Error: UI tools missing (gum required)."
        exit 1
    fi

    ui_banner
    gum style --align center --foreground "$C_DIM" "Select a topic below."

    while true; do
        CHOICE=$(gum choose \
            "1. Quick Start Guide" \
            "2. Understanding Parallelism" \
            "3. Automatic Scratch Management" \
            "4. Intel Xeon Optimizations" \
            "5. Common Issues" \
            "6. External Knowledge Base" \
            "7. Exit")

        case "$CHOICE" in
            "1. Quick Start Guide"*)
                show_tutorial "usage.md"
                ;;
            "2. Understanding Parallelism"*)
                show_tutorial "parallelism.md"
                ;;
            "3. Automatic Scratch"*)
                show_tutorial "scratch.md"
                ;;
            "4. Intel Xeon Optimizations"*)
                show_tutorial "intel_opts.md"
                ;;
            "5. Common Issues"*)
                show_tutorial "troubleshooting.md"
                ;;
            "6. External Knowledge Base"*)
                # Integration point for cry-docs future tool
                if [ ! -d "$TUTORIAL_DIR" ] || [ -z "$(ls -A "$TUTORIAL_DIR" 2>/dev/null)" ]; then
                    gum style \
                        --foreground "$C_ERR" \
                        --border double \
                        --padding "1" \
                        "Tutorials not installed in:" \
                        "$TUTORIAL_DIR" \
                        " " \
                        "Please run the scraper script to populate."
                else
                    # Interactive search through markdown documentation
                    SELECTION=$(find "$TUTORIAL_DIR" -type f -name "*.md" | \
                        sed "s|$TUTORIAL_DIR/||" | \
                        gum filter --header "Search Knowledge Base...")
                    if [ -n "$SELECTION" ]; then
                        gum pager < "$TUTORIAL_DIR/$SELECTION"
                    fi
                fi
                ;;
            "7. Exit"*)
                exit 0
                ;;
        esac
    done
}
