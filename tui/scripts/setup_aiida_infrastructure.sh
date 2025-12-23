#!/bin/bash
# setup_aiida_infrastructure.sh - Install and configure AiiDA infrastructure
#
# This script installs and configures:
#   - PostgreSQL 14+
#   - RabbitMQ (optional but recommended)
#   - AiiDA core with crystal-tui profile
#
# Requirements:
#   - macOS with Homebrew OR Linux with apt/dnf
#   - Python 3.10+ environment
#
# Usage:
#   ./scripts/setup_aiida_infrastructure.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Detect OS
detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macos"
    elif [[ -f /etc/debian_version ]]; then
        echo "debian"
    elif [[ -f /etc/redhat-release ]]; then
        echo "redhat"
    else
        echo "unknown"
    fi
}

OS=$(detect_os)
log_info "Detected OS: $OS"

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Python version
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found. Please install Python 3.10+"
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log_info "Python version: $PYTHON_VERSION"

    # Check Homebrew on macOS
    if [[ "$OS" == "macos" ]]; then
        if ! command -v brew &> /dev/null; then
            log_error "Homebrew not found. Please install from https://brew.sh"
            exit 1
        fi
        log_success "Homebrew found"
    fi
}

# Install PostgreSQL
install_postgresql() {
    log_info "Installing PostgreSQL..."

    if command -v psql &> /dev/null; then
        log_success "PostgreSQL already installed"
        return 0
    fi

    case "$OS" in
        macos)
            brew install postgresql@14
            brew services start postgresql@14

            # Add to PATH if needed
            if ! command -v psql &> /dev/null; then
                export PATH="/opt/homebrew/opt/postgresql@14/bin:$PATH"
                echo 'export PATH="/opt/homebrew/opt/postgresql@14/bin:$PATH"' >> ~/.zshrc
            fi
            ;;
        debian)
            sudo apt-get update
            sudo apt-get install -y postgresql postgresql-contrib
            sudo systemctl start postgresql
            sudo systemctl enable postgresql
            ;;
        redhat)
            sudo dnf install -y postgresql-server postgresql-contrib
            sudo postgresql-setup --initdb
            sudo systemctl start postgresql
            sudo systemctl enable postgresql
            ;;
        *)
            log_error "Unsupported OS for automatic PostgreSQL installation"
            log_warn "Please install PostgreSQL 12+ manually"
            return 1
            ;;
    esac

    log_success "PostgreSQL installed and started"
}

# Install RabbitMQ (optional)
install_rabbitmq() {
    log_info "Installing RabbitMQ (optional but recommended)..."

    if command -v rabbitmq-server &> /dev/null; then
        log_success "RabbitMQ already installed"
        return 0
    fi

    read -p "Install RabbitMQ for AiiDA daemon? (recommended) [Y/n] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        case "$OS" in
            macos)
                brew install rabbitmq
                brew services start rabbitmq
                ;;
            debian)
                sudo apt-get install -y rabbitmq-server
                sudo systemctl start rabbitmq-server
                sudo systemctl enable rabbitmq-server
                ;;
            redhat)
                sudo dnf install -y rabbitmq-server
                sudo systemctl start rabbitmq-server
                sudo systemctl enable rabbitmq-server
                ;;
            *)
                log_warn "Please install RabbitMQ manually"
                return 1
                ;;
        esac
        log_success "RabbitMQ installed and started"
    else
        log_warn "Skipping RabbitMQ. AiiDA will run without daemon (manual process launch)"
    fi
}

# Create PostgreSQL database for AiiDA
create_aiida_database() {
    log_info "Creating AiiDA database..."

    DB_NAME="aiida_crystal_tui"
    DB_USER="aiida_user"
    DB_PASS="crystal_tui_$(openssl rand -hex 8)"

    # Check if database exists
    if psql -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
        log_warn "Database '$DB_NAME' already exists"
        return 0
    fi

    # Create database and user
    case "$OS" in
        macos)
            createdb "$DB_NAME" 2>/dev/null || true
            psql -d postgres -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || true
            psql -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null || true
            ;;
        *)
            sudo -u postgres createdb "$DB_NAME" 2>/dev/null || true
            sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || true
            sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null || true
            ;;
    esac

    log_success "Database '$DB_NAME' created"

    # Save credentials
    CREDS_FILE="$HOME/.crystal_tui/aiida_db_credentials"
    mkdir -p "$HOME/.crystal_tui"
    cat > "$CREDS_FILE" << EOF
# AiiDA PostgreSQL credentials (auto-generated)
# DO NOT COMMIT THIS FILE
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASS=$DB_PASS
DB_HOST=localhost
DB_PORT=5432
EOF
    chmod 600 "$CREDS_FILE"
    log_success "Database credentials saved to $CREDS_FILE"
}

# Install AiiDA Python packages
install_aiida_python() {
    log_info "Installing AiiDA Python packages..."

    # Check if we're in a virtual environment
    if [[ -z "${VIRTUAL_ENV:-}" ]]; then
        log_warn "Not in a virtual environment. It's recommended to use a venv."
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Please activate a virtual environment and run this script again"
            exit 0
        fi
    fi

    # Install crystal-tui with AiiDA dependencies
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    TUI_DIR="$(dirname "$SCRIPT_DIR")"

    if command -v uv &> /dev/null; then
        log_info "Using uv for installation..."
        uv pip install -e "$TUI_DIR[aiida,dev]"
    else
        log_info "Using pip for installation..."
        pip install -e "$TUI_DIR[aiida,dev]"
    fi

    log_success "AiiDA Python packages installed"
}

# Configure AiiDA profile
configure_aiida_profile() {
    log_info "Configuring AiiDA profile..."

    # Load database credentials
    CREDS_FILE="$HOME/.crystal_tui/aiida_db_credentials"
    if [[ ! -f "$CREDS_FILE" ]]; then
        log_error "Database credentials not found. Run database setup first."
        return 1
    fi
    source "$CREDS_FILE"

    PROFILE_NAME="crystal-tui"

    # Check if profile exists
    if verdi profile show "$PROFILE_NAME" &>/dev/null; then
        log_warn "AiiDA profile '$PROFILE_NAME' already exists"
        return 0
    fi

    # Check if RabbitMQ is available
    BROKER_ARGS=""
    if command -v rabbitmq-server &> /dev/null; then
        BROKER_ARGS="--broker-protocol amqp --broker-host localhost --broker-port 5672"
    else
        log_warn "RabbitMQ not found. Daemon features will be limited."
    fi

    # Create profile using quicksetup
    log_info "Running verdi quicksetup..."
    verdi quicksetup \
        --profile "$PROFILE_NAME" \
        --db-backend core.psql_dos \
        --db-host localhost \
        --db-port 5432 \
        --db-name "$DB_NAME" \
        --db-username "$DB_USER" \
        --db-password "$DB_PASS" \
        --email "user@crystal-tui.local" \
        --first-name "CRYSTAL" \
        --last-name "TUI" \
        --institution "Local" \
        $BROKER_ARGS \
        --non-interactive

    # Set as default profile
    verdi profile setdefault "$PROFILE_NAME"

    log_success "AiiDA profile '$PROFILE_NAME' created and set as default"
}

# Start AiiDA daemon
start_aiida_daemon() {
    log_info "Starting AiiDA daemon..."

    if ! command -v rabbitmq-server &> /dev/null; then
        log_warn "RabbitMQ not installed. Daemon requires RabbitMQ."
        log_warn "You can still submit jobs, but they won't run automatically."
        return 0
    fi

    verdi daemon start
    log_success "AiiDA daemon started"

    # Show daemon status
    verdi daemon status
}

# Verify installation
verify_installation() {
    log_info "Verifying installation..."

    echo ""
    echo "=========================================="
    echo "Installation Verification"
    echo "=========================================="

    # PostgreSQL
    if command -v psql &> /dev/null; then
        PG_VERSION=$(psql --version | head -1)
        log_success "PostgreSQL: $PG_VERSION"
    else
        log_error "PostgreSQL: NOT FOUND"
    fi

    # RabbitMQ
    if command -v rabbitmq-server &> /dev/null; then
        log_success "RabbitMQ: Installed"
    else
        log_warn "RabbitMQ: Not installed (optional)"
    fi

    # AiiDA
    if command -v verdi &> /dev/null; then
        AIIDA_VERSION=$(verdi --version 2>/dev/null || echo "unknown")
        log_success "AiiDA: $AIIDA_VERSION"
    else
        log_error "AiiDA: NOT FOUND"
    fi

    # Profile
    if verdi profile show crystal-tui &>/dev/null; then
        log_success "AiiDA Profile: crystal-tui"
    else
        log_error "AiiDA Profile: NOT CONFIGURED"
    fi

    # Daemon
    if verdi daemon status &>/dev/null 2>&1; then
        log_success "AiiDA Daemon: Running"
    else
        log_warn "AiiDA Daemon: Not running"
    fi

    echo ""
    echo "=========================================="
    echo "Setup Complete!"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "  1. Configure computers: python -m src.aiida.setup.computers"
    echo "  2. Register codes: python -m src.aiida.setup.codes"
    echo "  3. Run TUI: crystal-tui"
    echo ""
}

# Main installation flow
main() {
    echo ""
    echo "=========================================="
    echo "CRYSTAL-TOOLS TUI - AiiDA Infrastructure Setup"
    echo "=========================================="
    echo ""

    check_prerequisites
    install_postgresql
    install_rabbitmq
    create_aiida_database
    install_aiida_python
    configure_aiida_profile
    start_aiida_daemon
    verify_installation
}

# Run main
main "$@"
