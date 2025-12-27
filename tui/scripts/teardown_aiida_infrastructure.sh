#!/bin/bash
# teardown_aiida_infrastructure.sh - Cleanup AiiDA infrastructure
#
# This script:
#   - Stops AiiDA daemon
#   - Stops Docker Compose services (or native PostgreSQL/RabbitMQ)
#   - Optionally removes data volumes
#
# Usage:
#   ./scripts/teardown_aiida_infrastructure.sh [--remove-data]

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

REMOVE_DATA=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --remove-data)
            REMOVE_DATA=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--remove-data]"
            exit 1
            ;;
    esac
done

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUI_DIR="$(dirname "$SCRIPT_DIR")"

cd "$TUI_DIR"

# Stop AiiDA daemon
if command -v verdi &> /dev/null; then
    log_info "Stopping AiiDA daemon..."
    verdi daemon stop || log_warn "Daemon not running"
    log_success "AiiDA daemon stopped"
fi

# Check if using Docker Compose
if [[ -f docker-compose.yml ]]; then
    log_info "Stopping Docker Compose services..."

    if [[ "$REMOVE_DATA" == true ]]; then
        log_warn "Removing data volumes..."
        docker-compose down -v
        log_success "Docker Compose services stopped and volumes removed"
    else
        docker-compose down
        log_success "Docker Compose services stopped (data preserved)"
    fi
else
    log_info "Docker Compose not found, checking native services..."

    # Stop native services on macOS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &> /dev/null; then
            if brew services list | grep -q "postgresql.*started"; then
                log_info "Stopping PostgreSQL..."
                brew services stop postgresql@14
                log_success "PostgreSQL stopped"
            fi

            if brew services list | grep -q "rabbitmq.*started"; then
                log_info "Stopping RabbitMQ..."
                brew services stop rabbitmq
                log_success "RabbitMQ stopped"
            fi
        fi
    # Stop native services on Linux
    elif command -v systemctl &> /dev/null; then
        if systemctl is-active --quiet postgresql; then
            log_info "Stopping PostgreSQL..."
            sudo systemctl stop postgresql
            log_success "PostgreSQL stopped"
        fi

        if systemctl is-active --quiet rabbitmq-server; then
            log_info "Stopping RabbitMQ..."
            sudo systemctl stop rabbitmq-server
            log_success "RabbitMQ stopped"
        fi
    fi

    if [[ "$REMOVE_DATA" == true ]]; then
        log_warn "Data removal for native installations requires manual steps:"
        echo "  - PostgreSQL: sudo -u postgres dropdb aiida_crystal_tui"
        echo "  - AiiDA profile: verdi profile delete crystal-tui"
        echo "  - Credentials: rm ~/.crystal_tui/aiida_db_credentials"
    fi
fi

echo ""
log_success "Teardown complete"
echo ""

if [[ "$REMOVE_DATA" == false ]]; then
    echo "Note: Data volumes were preserved. To remove all data, run:"
    echo "  $0 --remove-data"
    echo ""
fi
