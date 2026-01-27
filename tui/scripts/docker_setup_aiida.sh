#!/bin/bash
# docker_setup_aiida.sh - Setup AiiDA using Docker Compose
#
# This script:
#   - Starts PostgreSQL and RabbitMQ via Docker Compose
#   - Waits for services to be healthy
#   - Creates AiiDA profile with database backend
#   - Configures localhost computer for local execution
#   - Starts AiiDA daemon (optional)
#
# Prerequisites:
#   - Docker and Docker Compose installed
#   - Python environment with AiiDA (or will be installed)
#
# Usage:
#   ./scripts/docker_setup_aiida.sh           # Full setup
#   ./scripts/docker_setup_aiida.sh --skip-computer  # Skip computer setup
#   ./scripts/docker_setup_aiida.sh --no-daemon      # Don't start daemon

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_step() { echo -e "${CYAN}[STEP]${NC} $*"; }

# Parse arguments
SKIP_COMPUTER=false
NO_DAEMON=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-computer)
            SKIP_COMPUTER=true
            shift
            ;;
        --no-daemon)
            NO_DAEMON=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-computer  Skip localhost computer setup"
            echo "  --no-daemon      Don't start AiiDA daemon"
            echo "  -h, --help       Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUI_DIR="$(dirname "$SCRIPT_DIR")"

cd "$TUI_DIR"

# =============================================================================
# Pre-flight Checks
# =============================================================================

log_step "Running pre-flight checks..."

# Check Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker first."
    log_info "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check Docker Compose (v1 or v2)
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    log_error "Docker Compose is not installed."
    exit 1
fi

# Check Docker daemon
if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running. Please start Docker."
    exit 1
fi

log_success "Docker is ready"

# =============================================================================
# Environment Setup
# =============================================================================

log_step "Setting up environment..."

# Check for .env file
if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        log_info "Creating .env from .env.example..."
        cp .env.example .env
        log_warn "Please review .env and change default passwords before production use!"
    else
        log_error ".env.example not found. Cannot create .env file."
        exit 1
    fi
fi

# Load environment variables with defaults
set -a  # Export all variables
source .env
set +a

# Set defaults if not defined in .env
POSTGRES_USER="${POSTGRES_USER:-aiida_user}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-changeme}"
POSTGRES_DB="${POSTGRES_DB:-aiida_crystal_tui}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
RABBITMQ_DEFAULT_USER="${RABBITMQ_DEFAULT_USER:-aiida_user}"
RABBITMQ_DEFAULT_PASS="${RABBITMQ_DEFAULT_PASS:-changeme}"
RABBITMQ_DEFAULT_VHOST="${RABBITMQ_DEFAULT_VHOST:-/aiida}"
RABBITMQ_PORT="${RABBITMQ_PORT:-5672}"
RABBITMQ_MANAGEMENT_PORT="${RABBITMQ_MANAGEMENT_PORT:-15672}"
AIIDA_PROFILE_NAME="${AIIDA_PROFILE_NAME:-crystal-tui}"
AIIDA_DAEMON_ENABLED="${AIIDA_DAEMON_ENABLED:-true}"

log_success "Environment loaded"

# =============================================================================
# Docker Services
# =============================================================================

log_step "Starting Docker Compose services..."

$COMPOSE_CMD up -d

# Wait for PostgreSQL with timeout
log_info "Waiting for PostgreSQL to be ready..."
TIMEOUT=60
COUNTER=0
until $COMPOSE_CMD exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    if [[ $COUNTER -ge $TIMEOUT ]]; then
        log_error "PostgreSQL did not become ready within ${TIMEOUT} seconds"
        $COMPOSE_CMD logs postgres
        exit 1
    fi
    sleep 1
    ((COUNTER++))
done
log_success "PostgreSQL is ready (took ${COUNTER}s)"

# Wait for RabbitMQ with timeout
log_info "Waiting for RabbitMQ to be ready..."
COUNTER=0
until $COMPOSE_CMD exec -T rabbitmq rabbitmq-diagnostics -q ping >/dev/null 2>&1; do
    if [[ $COUNTER -ge $TIMEOUT ]]; then
        log_error "RabbitMQ did not become ready within ${TIMEOUT} seconds"
        $COMPOSE_CMD logs rabbitmq
        exit 1
    fi
    sleep 1
    ((COUNTER++))
done
log_success "RabbitMQ is ready (took ${COUNTER}s)"

# =============================================================================
# AiiDA Installation Check
# =============================================================================

log_step "Checking AiiDA installation..."

if ! command -v verdi &> /dev/null; then
    log_warn "AiiDA (verdi) not found in current Python environment"
    log_info "Attempting to install AiiDA..."

    if command -v uv &> /dev/null; then
        uv pip install -e ".[aiida]"
    elif command -v pip &> /dev/null; then
        pip install -e ".[aiida]"
    else
        log_error "Neither uv nor pip found. Please install AiiDA manually:"
        echo "  pip install aiida-core"
        exit 1
    fi

    # Verify installation
    if ! command -v verdi &> /dev/null; then
        log_error "AiiDA installation failed. Please install manually."
        exit 1
    fi
fi

log_success "AiiDA is installed ($(verdi --version 2>/dev/null | head -1 || echo 'version unknown'))"

# =============================================================================
# AiiDA Profile Setup
# =============================================================================

log_step "Setting up AiiDA profile..."

if verdi profile show "$AIIDA_PROFILE_NAME" &>/dev/null; then
    log_warn "AiiDA profile '$AIIDA_PROFILE_NAME' already exists"
    log_info "To recreate, run: verdi profile delete $AIIDA_PROFILE_NAME"
else
    log_info "Creating AiiDA profile '$AIIDA_PROFILE_NAME'..."

    verdi quicksetup \
        --profile "$AIIDA_PROFILE_NAME" \
        --db-backend core.psql_dos \
        --db-host localhost \
        --db-port "$POSTGRES_PORT" \
        --db-name "$POSTGRES_DB" \
        --db-username "$POSTGRES_USER" \
        --db-password "$POSTGRES_PASSWORD" \
        --broker-protocol amqp \
        --broker-host localhost \
        --broker-port "$RABBITMQ_PORT" \
        --broker-username "$RABBITMQ_DEFAULT_USER" \
        --broker-password "$RABBITMQ_DEFAULT_PASS" \
        --broker-virtual-host "$RABBITMQ_DEFAULT_VHOST" \
        --email "user@crystal-tui.local" \
        --first-name "CRYSTAL" \
        --last-name "TUI" \
        --institution "Local Development" \
        --non-interactive

    verdi profile setdefault "$AIIDA_PROFILE_NAME"
    log_success "AiiDA profile created and set as default"
fi

# =============================================================================
# Localhost Computer Setup
# =============================================================================

if [[ "$SKIP_COMPUTER" == "false" ]]; then
    log_step "Setting up localhost computer..."

    COMPUTER_LABEL="localhost"

    if verdi computer show "$COMPUTER_LABEL" &>/dev/null; then
        log_warn "Computer '$COMPUTER_LABEL' already exists"
    else
        log_info "Creating localhost computer..."

        # Create computer configuration
        verdi computer setup \
            --label "$COMPUTER_LABEL" \
            --hostname "localhost" \
            --description "Local computer for CRYSTAL-TUI" \
            --transport core.local \
            --scheduler core.direct \
            --work-dir "$HOME/aiida_run" \
            --mpirun-command "mpirun -np {tot_num_mpiprocs}" \
            --mpiprocs-per-machine 4 \
            --non-interactive

        # Configure computer (no additional config needed for local)
        verdi computer configure core.local "$COMPUTER_LABEL" \
            --safe-interval 0 \
            --non-interactive

        log_success "Localhost computer configured"
    fi

    # Test computer
    log_info "Testing localhost computer..."
    if verdi computer test "$COMPUTER_LABEL" --print-traceback 2>/dev/null; then
        log_success "Computer test passed"
    else
        log_warn "Computer test had issues (may still work)"
    fi
fi

# =============================================================================
# AiiDA Daemon
# =============================================================================

if [[ "$NO_DAEMON" == "false" && "$AIIDA_DAEMON_ENABLED" == "true" ]]; then
    log_step "Starting AiiDA daemon..."

    if verdi daemon status &>/dev/null; then
        log_info "Daemon already running, restarting..."
        verdi daemon restart || true
    else
        verdi daemon start || log_warn "Could not start daemon"
    fi

    # Show daemon status
    verdi daemon status || true
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo "=========================================="
echo "  AiiDA Infrastructure Setup Complete"
echo "=========================================="
echo ""

log_step "Docker Services:"
$COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""

log_step "AiiDA Profile:"
verdi profile show "$AIIDA_PROFILE_NAME" 2>/dev/null || echo "  Profile: $AIIDA_PROFILE_NAME"
echo ""

log_step "Services:"
echo "  PostgreSQL:          localhost:$POSTGRES_PORT"
echo "  RabbitMQ Broker:     amqp://localhost:$RABBITMQ_PORT"
echo "  RabbitMQ Management: http://localhost:$RABBITMQ_MANAGEMENT_PORT"
echo "    Username: $RABBITMQ_DEFAULT_USER"
echo "    Password: (see .env file)"
echo ""

log_step "Next Steps:"
echo "  1. Register CRYSTAL codes:"
echo "     verdi code create core.code.installed --label crystal --computer localhost \\"
echo "       --filepath-executable \$(which crystalOMP) --default-calc-job-plugin crystal"
echo ""
echo "  2. Launch TUI:"
echo "     crystal-tui"
echo ""
echo "  3. View daemon logs:"
echo "     verdi daemon logshow"
echo ""
echo "  4. Stop infrastructure:"
echo "     ./scripts/teardown_aiida_infrastructure.sh"
echo ""

log_success "Setup complete!"
