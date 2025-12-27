# AiiDA Integration Testing Guide

This guide covers testing the AiiDA integration for CRYSTAL-TUI.

## Test Suite Overview

The AiiDA integration has three levels of testing:

### 1. Unit Tests (Mock-based)

**Location**: `tests/test_aiida_*.py`
**Dependencies**: None (uses mocks)
**Purpose**: Test individual components in isolation

- `test_aiida_query_adapter.py` - 35+ tests for QueryBuilder adapter
- `test_aiida_migration.py` - 30+ tests for SQLite → AiiDA migration
- `test_aiida_parser.py` - 40+ tests for CRYSTAL23 output parsing
- `test_aiida_submitter.py` - 30+ tests for job submission

**Running unit tests**:

```bash
cd tui/
uv run pytest tests/test_aiida_*.py -v
```

**Expected results**: ~135 tests, mix of passed/failed (some mocks need refinement)

### 2. E2E Integration Tests (Real AiiDA)

**Location**: `tests/test_aiida_e2e.py`
**Dependencies**: Docker, AiiDA installed, infrastructure running
**Purpose**: Test complete workflows with real AiiDA

**Setup**:

```bash
# 1. Start Docker infrastructure
./scripts/docker_setup_aiida.sh

# 2. Install AiiDA dependencies
uv pip install -e ".[aiida]"

# 3. Run E2E tests
uv run pytest tests/test_aiida_e2e.py --aiida -v
```

**Test categories**:
- Infrastructure tests (Docker, PostgreSQL, RabbitMQ)
- Query adapter integration
- Database migration end-to-end
- Parser integration
- Full workflow tests
- Documentation validation

### 3. Manual Testing Checklist

For features not covered by automated tests:

#### AiiDA Profile Setup

```bash
# Verify profile exists
verdi profile show crystal-tui

# Expected output:
# - Profile: crystal-tui
# - Database: PostgreSQL (localhost:5432)
# - Broker: RabbitMQ (localhost:5672)
# - Storage: /home/user/.aiida/repository/
```

#### Computer Configuration

```bash
# Configure localhost computer
python -m src.aiida.setup.computers --localhost

# Verify
verdi computer list
verdi computer show localhost

# Test connection
verdi computer test localhost
```

#### Code Registration

```bash
# Register CRYSTAL23 code
python -m src.aiida.setup.codes \
    --computer localhost \
    --label crystalOMP \
    --executable /path/to/CRYSTAL23/bin/crystalOMP

# Verify
verdi code list
verdi code show crystalOMP@localhost
```

#### Job Submission (Manual)

```python
# In Python shell
from src.aiida.submitter import AiiDASubmitter

submitter = AiiDASubmitter(profile_name="crystal-tui")

# Create simple test input
input_content = """CRYSTAL
0 0 0
12 3
1 0 3  2.0  1.0
1 1 3  8.0  1.0
1 1 3  2.0  1.0
8 2
1 0 3  2.0  1.0
1 1 3  6.0  1.0
END
"""

# Submit job
job_id = submitter.submit_job(
    code_label="crystalOMP@localhost",
    input_content=input_content,
    job_name="Manual Test",
)

print(f"Submitted job: {job_id}")

# Monitor status
status = submitter.get_job_status(job_id)
print(f"Status: {status}")
```

#### QueryAdapter Testing

```python
from src.aiida.query_adapter import AiiDAQueryAdapter

adapter = AiiDAQueryAdapter(profile_name="crystal-tui")

# List all jobs
jobs = adapter.list_jobs()
print(f"Total jobs: {len(jobs)}")

# Filter by status
running_jobs = adapter.list_jobs(status="running")
print(f"Running: {len(running_jobs)}")

# Get job details
job = adapter.get_job(job_id)
print(f"Job details: {job}")

# Get job count
count = adapter.get_job_count()
print(f"Total count: {count}")
```

#### Migration Testing

```bash
# Dry run migration
python -m src.aiida.migration \
    --sqlite-db ~/.crystal_tui/jobs.db \
    --dry-run

# Actual migration
python -m src.aiida.migration \
    --sqlite-db ~/.crystal_tui/jobs.db

# Verify migration
python -m src.aiida.migration --verify
```

---

## Test Data

### Sample CRYSTAL23 Input

```crystal
CRYSTAL
0 0 0
12 3
1 0 3  2.0  1.0
1 1 3  8.0  1.0
1 1 3  2.0  1.0
8 2
1 0 3  2.0  1.0
1 1 3  6.0  1.0
END

MgO test structure for AiiDA integration testing.
```

### Sample Output (for parser tests)

```
CRYSTAL23 - SCF CALCULATION

CYC   ETOT(AU)      DETOT        CONV
  1  -276.123456   1.0E+00      N
  2  -276.234567   1.1E-01      N
  3  -276.345678   1.1E-02      Y

== SCF ENDED - CONVERGENCE ON ENERGY

TOTAL ENERGY(DFT)(AU) (  3) -276.345678

DIRECT BAND GAP:   7.83 EV

EEEEEEEE TERMINATION  DATE 25 12 2024 TIME 12:00:00.0
```

---

## Common Testing Scenarios

### Scenario 1: Fresh Installation Test

```bash
# 1. Start infrastructure
./scripts/docker_setup_aiida.sh

# 2. Configure computer and code
python -m src.aiida.setup.computers --localhost
python -m src.aiida.setup.codes --localhost

# 3. Create test job
python3 <<EOF
from src.aiida.query_adapter import AiiDAQueryAdapter

adapter = AiiDAQueryAdapter()
job_id = adapter.create_job(
    name="Installation Test",
    input_content="CRYSTAL\n0 0 0\nEND"
)
print(f"Created job: {job_id}")
EOF

# 4. Verify in AiiDA
verdi process list
verdi node show <job_id>
```

### Scenario 2: Migration from SQLite

```bash
# 1. Backup SQLite database
cp ~/.crystal_tui/jobs.db ~/.crystal_tui/jobs.db.backup

# 2. Test migration (dry run)
python -m src.aiida.migration --dry-run

# 3. Run actual migration
python -m src.aiida.migration

# 4. Verify migrated data
python -m src.aiida.migration --verify

# 5. Check AiiDA nodes
verdi node list -a
```

### Scenario 3: Daemon-based Execution

```bash
# 1. Start daemon
verdi daemon start

# 2. Submit job via submitter
python3 <<EOF
from src.aiida.submitter import AiiDASubmitter

submitter = AiiDASubmitter()
job_id = submitter.submit_job(
    code_label="crystalOMP@localhost",
    input_content="CRYSTAL\n0 0 0\nEND"
)
EOF

# 3. Monitor daemon logs
verdi daemon logshow

# 4. Check process status
verdi process list -a
verdi process show <job_id>
```

---

## Troubleshooting Tests

### Unit Tests Failing

**Issue**: Import errors or mock failures

**Solution**:
- Check that `tests/conftest.py` exists (provides AiiDA mocks)
- Verify Python 3.10+ is being used
- Run `uv pip install -e ".[dev]"` to ensure test dependencies

### E2E Tests Skipped

**Issue**: E2E tests show as "skipped"

**Cause**: Missing `--aiida` flag or infrastructure not running

**Solution**:

```bash
# Check infrastructure
docker-compose ps

# If not running, start it
./scripts/docker_setup_aiida.sh

# Run with flag
uv run pytest tests/test_aiida_e2e.py --aiida -v
```

### AiiDA Profile Errors

**Issue**: `ProfileNotFoundError: crystal-tui`

**Solution**:

```bash
# List profiles
verdi profile list

# If missing, recreate
./scripts/docker_setup_aiida.sh

# Set as default
verdi profile setdefault crystal-tui
```

### PostgreSQL Connection Refused

**Issue**: Tests fail with connection errors

**Solution**:

```bash
# Check Docker services
docker-compose ps

# Check PostgreSQL specifically
docker-compose exec postgres pg_isready -U aiida_user

# If not running, restart
docker-compose restart postgres

# Wait for health check
until docker-compose exec -T postgres pg_isready -U aiida_user; do sleep 1; done
```

### RabbitMQ Not Ready

**Issue**: Daemon won't start, broker errors

**Solution**:

```bash
# Check RabbitMQ
docker-compose exec rabbitmq rabbitmq-diagnostics ping

# Restart if needed
docker-compose restart rabbitmq

# Verify connection in profile
verdi profile show crystal-tui | grep broker
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: AiiDA Tests

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Install dependencies
        run: |
          cd tui
          uv pip install -e ".[dev]"
      - name: Run unit tests
        run: |
          cd tui
          uv run pytest tests/test_aiida_*.py -v --tb=short

  e2e-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:14-alpine
        env:
          POSTGRES_USER: aiida_user
          POSTGRES_PASSWORD: test_password
          POSTGRES_DB: aiida_crystal_tui
        ports:
          - 5432:5432
      rabbitmq:
        image: rabbitmq:3-management-alpine
        ports:
          - 5672:5672
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Install AiiDA
        run: |
          cd tui
          uv pip install -e ".[aiida]"
      - name: Setup AiiDA profile
        run: |
          verdi quicksetup \
            --profile crystal-tui \
            --db-host localhost \
            --db-port 5432 \
            --db-name aiida_crystal_tui \
            --db-username aiida_user \
            --db-password test_password \
            --broker-host localhost \
            --non-interactive
      - name: Run E2E tests
        run: |
          cd tui
          uv run pytest tests/test_aiida_e2e.py --aiida -v
```

---

## Test Coverage

Target coverage goals:

- **Query Adapter**: 80%+
- **Migration**: 75%+
- **Parser**: 85%+
- **Submitter**: 70%+

Generate coverage report:

```bash
cd tui/
uv run pytest tests/test_aiida_*.py --cov=src.aiida --cov-report=html
open htmlcov/index.html
```

---

## Best Practices

1. **Always use fixtures** for AiiDA profile to ensure proper cleanup
2. **Mock external dependencies** in unit tests (don't call real CRYSTAL23)
3. **Test both success and failure paths** for robust coverage
4. **Use descriptive test names** that explain what is being tested
5. **Keep E2E tests fast** by using minimal test data
6. **Clean up test nodes** after E2E tests to avoid database bloat

---

## Additional Resources

- [AiiDA Documentation](https://aiida.readthedocs.io/)
- [Pytest Documentation](https://docs.pytest.org/)
- [CRYSTAL-TUI Testing Guide](../tests/README.md)
- [Docker Compose Reference](../docker-compose.yml)

---

**Last Updated**: 2025-12-25
