#!/bin/bash
# docker_setup_aiida.sh - Setup AiiDA using Docker Compose
#
# This script:
#   - Starts PostgreSQL and RabbitMQ via Docker Compose
#   - Waits for services to be healthy
#   - Creates AiiDA profile
#   - Configures computers and codes
#
# Usage:
#   ./scripts/docker_setup_aiida.sh

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUI_DIR="$(dirname "$SCRIPT_DIR")"

cd "$TUI_DIR"

# Check for .env file
if [[ ! -f .env ]]; then
    log_info "Creating .env from .env.example..."
    cp .env.example .env
    log_warn "Please review .env and change default passwords!"
fi

# Start Docker Compose services
log_info "Starting Docker Compose services..."
docker-compose up -d

# Wait for services to be healthy
log_info "Waiting for PostgreSQL to be ready..."
until docker-compose exec -T postgres pg_isready -U aiida_user >/dev/null 2>&1; do
    sleep 1
done
log_success "PostgreSQL is ready"

log_info "Waiting for RabbitMQ to be ready..."
until docker-compose exec -T rabbitmq rabbitmq-diagnostics -q ping >/dev/null 2>&1; do
    sleep 1
done
log_success "RabbitMQ is ready"

# Load environment variables
source .env

# Check if AiiDA is installed
if ! command -v verdi &> /dev/null; then
    log_warn "AiiDA not found in Python environment"
    log_info "Installing AiiDA..."
    if command -v uv &> /dev/null; then
        uv pip install -e ".[aiida]"
    else
        pip install -e ".[aiida]"
    fi
fi

# Check if profile exists
if verdi profile show "${AIIDA_PROFILE_NAME}" &>/dev/null; then
    log_warn "AiiDA profile '${AIIDA_PROFILE_NAME}' already exists"
else
    log_info "Creating AiiDA profile..."
    verdi quicksetup \
        --profile "${AIIDA_PROFILE_NAME}" \
        --db-backend core.psql_dos \
        --db-host localhost \
        --db-port "${POSTGRES_PORT}" \
        --db-name "${POSTGRES_DB}" \
        --db-username "${POSTGRES_USER}" \
        --db-password "${POSTGRES_PASSWORD}" \
        --broker-protocol amqp \
        --broker-host localhost \
        --broker-port "${RABBITMQ_PORT}" \
        --broker-username "${RABBITMQ_DEFAULT_USER}" \
        --broker-password "${RABBITMQ_DEFAULT_PASS}" \
        --broker-virtual-host "${RABBITMQ_DEFAULT_VHOST}" \
        --email "user@crystal-tui.local" \
        --first-name "CRYSTAL" \
        --last-name "TUI" \
        --institution "Local" \
        --non-interactive

    verdi profile setdefault "${AIIDA_PROFILE_NAME}"
    log_success "AiiDA profile created and set as default"
fi

# Start daemon if enabled
if [[ "${AIIDA_DAEMON_ENABLED}" == "true" ]]; then
    log_info "Starting AiiDA daemon..."
    verdi daemon start || log_warn "Daemon already running"
    log_success "AiiDA daemon started"
fi

# Show status
echo ""
echo "=========================================="
echo "AiiDA Infrastructure Status"
echo "=========================================="
echo ""
docker-compose ps
echo ""
verdi profile show "${AIIDA_PROFILE_NAME}"
echo ""
verdi daemon status || true
echo ""
log_success "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Configure computers: python -m src.aiida.setup.computers --localhost"
echo "  2. Register codes: python -m src.aiida.setup.codes --localhost"
echo "  3. Run TUI: crystal-tui"
echo ""
echo "Services:"
echo "  - PostgreSQL: localhost:${POSTGRES_PORT}"
echo "  - RabbitMQ Management: http://localhost:${RABBITMQ_MANAGEMENT_PORT}"
echo "  - RabbitMQ Broker: amqp://localhost:${RABBITMQ_PORT}"
echo ""
