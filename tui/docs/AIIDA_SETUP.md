# AiiDA Setup Guide

This guide covers setting up AiiDA infrastructure for CRYSTAL-TUI in different deployment scenarios.

## Quick Start (Docker Compose - Recommended)

The fastest way to get started is using Docker Compose:

```bash
cd tui/

# 1. Copy environment template
cp .env.example .env
# Edit .env to set strong passwords

# 2. Start infrastructure and create profile
./scripts/docker_setup_aiida.sh

# 3. Configure computers and codes
python -m src.aiida.setup.computers --localhost
python -m src.aiida.setup.codes --localhost

# 4. Launch TUI
crystal-tui
```

That's it! PostgreSQL and RabbitMQ are running in Docker, and AiiDA is configured.

---

## Docker Compose Details

### Services

The `docker-compose.yml` provides:

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| PostgreSQL | `postgres:14-alpine` | 5432 | AiiDA database |
| RabbitMQ | `rabbitmq:3-management-alpine` | 5672, 15672 | Message broker + management UI |

### Environment Variables

Configure via `.env` file (copy from `.env.example`):

```bash
# PostgreSQL
POSTGRES_USER=aiida_user
POSTGRES_PASSWORD=changeme_strong_password  # ⚠️ CHANGE THIS
POSTGRES_DB=aiida_crystal_tui
POSTGRES_PORT=5432

# RabbitMQ
RABBITMQ_DEFAULT_USER=aiida_user
RABBITMQ_DEFAULT_PASS=changeme_strong_password  # ⚠️ CHANGE THIS
RABBITMQ_DEFAULT_VHOST=/aiida
RABBITMQ_PORT=5672
RABBITMQ_MANAGEMENT_PORT=15672

# AiiDA
AIIDA_PROFILE_NAME=crystal-tui
AIIDA_DAEMON_ENABLED=true
```

### Data Persistence

Data is stored in Docker named volumes:
- `postgres_data` - Database files
- `rabbitmq_data` - Message broker data

**To remove all data**:
```bash
./scripts/teardown_aiida_infrastructure.sh --remove-data
```

---

## Manual Installation (Native Services)

For production deployments or if you prefer native services:

### Prerequisites

- Python 3.10+
- PostgreSQL 12+
- RabbitMQ (optional but recommended for daemon)

### macOS Installation

```bash
# Install dependencies
brew install postgresql@14 rabbitmq

# Start services
brew services start postgresql@14
brew services start rabbitmq

# Run setup script
./scripts/setup_aiida_infrastructure.sh
```

### Linux Installation (Debian/Ubuntu)

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y postgresql postgresql-contrib rabbitmq-server

# Start services
sudo systemctl start postgresql
sudo systemctl start rabbitmq-server

# Run setup script
./scripts/setup_aiida_infrastructure.sh
```

### Linux Installation (RHEL/Fedora)

```bash
# Install dependencies
sudo dnf install -y postgresql-server rabbitmq-server

# Initialize and start PostgreSQL
sudo postgresql-setup --initdb
sudo systemctl start postgresql
sudo systemctl start rabbitmq-server

# Run setup script
./scripts/setup_aiida_infrastructure.sh
```

---

## Post-Installation

### Verify Installation

```bash
# Check services
docker-compose ps  # If using Docker
# OR
brew services list  # macOS
# OR
sudo systemctl status postgresql rabbitmq-server  # Linux

# Check AiiDA
verdi status
verdi profile show crystal-tui
verdi daemon status
```

### Configure Computers

AiiDA needs at least one "Computer" configured:

```bash
# Localhost for testing
python -m src.aiida.setup.computers --localhost

# Remote SSH cluster
python -m src.aiida.setup.computers \
    --hostname cluster.university.edu \
    --username myuser \
    --scheduler slurm

# List computers
verdi computer list
```

### Register Codes

Tell AiiDA where to find CRYSTAL23 executables:

```bash
# Localhost
python -m src.aiida.setup.codes \
    --computer localhost \
    --label crystalOMP \
    --executable /path/to/crystalOMP

# Remote cluster
python -m src.aiida.setup.codes \
    --computer my-cluster \
    --label PcrystalOMP \
    --executable /home/user/CRYSTAL23/bin/PcrystalOMP

# List codes
verdi code list
```

---

## Troubleshooting

### Port Already in Use

If ports 5432 or 5672 are already in use:

```bash
# Option 1: Change ports in .env
POSTGRES_PORT=5433
RABBITMQ_PORT=5673

# Option 2: Stop conflicting services
brew services stop postgresql  # macOS
sudo systemctl stop postgresql  # Linux
```

### AiiDA Daemon Won't Start

Check RabbitMQ is running:

```bash
# Docker
docker-compose ps rabbitmq

# Native
brew services list | grep rabbitmq  # macOS
sudo systemctl status rabbitmq-server  # Linux

# Test connection
verdi daemon status
verdi profile show crystal-tui
```

### Database Connection Failed

Verify credentials in `.env` match AiiDA profile:

```bash
# Show profile config
verdi profile show crystal-tui

# Test database connection directly
psql -h localhost -U aiida_user -d aiida_crystal_tui
```

### Permission Denied on Volumes

On Linux with SELinux/AppArmor:

```bash
# Add :z suffix to volumes in docker-compose.yml
volumes:
  - postgres_data:/var/lib/postgresql/data:z
  - rabbitmq_data:/var/lib/rabbitmq:z
```

---

## Development vs Production

### Development Setup

- Use Docker Compose
- Default passwords are acceptable
- Daemon can be disabled for synchronous execution
- Data can be ephemeral

### Production Setup

- Use native services or managed cloud databases
- **Strong passwords required**
- Enable TLS for PostgreSQL connections
- Configure RabbitMQ with authentication
- Implement backup strategy for PostgreSQL
- Monitor daemon with systemd or supervisord

Example production-ready PostgreSQL connection:

```bash
verdi quicksetup \
    --db-host prod-db.example.com \
    --db-port 5432 \
    --db-username aiida_prod \
    --db-password <strong-password> \
    --db-name aiida_crystal \
    --broker-protocol amqps \  # TLS enabled
    --broker-host prod-mq.example.com \
    ...
```

---

## Migration from SQLite

If you have existing CRYSTAL-TUI data in SQLite:

```bash
# Backup existing database
cp ~/.crystal_tui/jobs.db ~/.crystal_tui/jobs.db.backup

# Run migration
python -m src.aiida.migration \
    --sqlite-db ~/.crystal_tui/jobs.db \
    --aiida-profile crystal-tui \
    --dry-run  # Test first

# Actual migration (no --dry-run)
python -m src.aiida.migration \
    --sqlite-db ~/.crystal_tui/jobs.db \
    --aiida-profile crystal-tui
```

**Note**: Migration is experimental. Review migrated data carefully.

---

## Useful Commands

```bash
# AiiDA daemon
verdi daemon start
verdi daemon stop
verdi daemon status
verdi daemon restart

# Process management
verdi process list          # List running processes
verdi process show <PK>     # Show process details
verdi process kill <PK>     # Kill a process

# Database queries
verdi node show <PK>        # Show node details
verdi data ls               # List data nodes

# Profiles
verdi profile list
verdi profile setdefault crystal-tui
verdi profile delete <name>

# Cleanup
verdi storage maintain      # Database maintenance
verdi daemon logshow        # View daemon logs
```

---

## Next Steps

After setup is complete:

1. **Test submission**: Create a simple calculation through the TUI
2. **Monitor daemon**: `verdi daemon logshow`
3. **Check provenance**: `verdi process list`
4. **Explore data**: `verdi data ls`

See the main [TUI documentation](../README.md) for usage instructions.

---

## Support

- **AiiDA Documentation**: https://aiida.readthedocs.io/
- **CRYSTAL-TUI Issues**: https://github.com/TheFermiSea/CrystalMath/issues
- **AiiDA Community**: https://aiida.net/community/

---

**Last Updated**: 2025-12-24
