"""End-to-end integration tests for AiiDA integration.

These tests require:
- Docker and Docker Compose installed
- AiiDA installed (`pip install -e ".[aiida]"`)
- Running `./scripts/docker_setup_aiida.sh` first

Run with: pytest tests/test_aiida_e2e.py --aiida

The --aiida flag is required to run these tests to avoid running them
in regular CI where AiiDA infrastructure may not be available.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

# Skip all tests in this module unless AIIDA_E2E=1 environment variable is set
pytestmark = pytest.mark.skipif(
    not os.environ.get("AIIDA_E2E", "").lower() in ("1", "true", "yes"),
    reason="E2E tests require AIIDA_E2E=1 environment variable and running AiiDA infrastructure",
)


@pytest.fixture(scope="module")
def docker_services():
    """Ensure Docker Compose services are running."""
    # Check if services are running
    result = subprocess.run(
        ["docker-compose", "ps", "-q"],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        pytest.skip("Docker Compose services not running. Run ./scripts/docker_setup_aiida.sh first")

    yield

    # Services are left running for reuse across test sessions


@pytest.fixture(scope="module")
def aiida_profile(docker_services):
    """Ensure AiiDA profile exists and is configured."""
    try:
        from aiida import load_profile

        profile = load_profile("crystal-tui")
        return profile
    except Exception as e:
        pytest.skip(f"AiiDA profile 'crystal-tui' not available: {e}")


@pytest.fixture
def sample_input():
    """Sample CRYSTAL23 input file."""
    return """CRYSTAL
0 0 0
12 3
1 0 3  2.0  1.0
1 1 3  8.0  1.0
1 1 3  2.0  1.0
8 2
1 0 3  2.0  1.0
1 1 3  6.0  1.0
ENDCRYSTAL23 - E2E Integration Test Input

This input defines a simple MgO crystal structure.
"""


class TestAiiDAInfrastructure:
    """Test AiiDA infrastructure setup."""

    def test_docker_services_running(self):
        """Test that PostgreSQL and RabbitMQ are running."""
        # Check PostgreSQL
        result = subprocess.run(
            ["docker-compose", "exec", "-T", "postgres", "pg_isready", "-U", "aiida_user"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
        )
        assert result.returncode == 0, "PostgreSQL is not ready"

        # Check RabbitMQ
        result = subprocess.run(
            ["docker-compose", "exec", "-T", "rabbitmq", "rabbitmq-diagnostics", "-q", "ping"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
        )
        assert result.returncode == 0, "RabbitMQ is not ready"

    def test_aiida_profile_exists(self, aiida_profile):
        """Test that AiiDA profile is configured."""
        assert aiida_profile is not None
        assert aiida_profile.name == "crystal-tui"

    def test_aiida_daemon_status(self, aiida_profile):
        """Test AiiDA daemon status."""
        from aiida.engine.daemon.client import get_daemon_client

        client = get_daemon_client()
        # Note: Daemon may not be running, which is OK for sync tests
        # Just verify the client can be created
        assert client is not None


class TestQueryAdapter:
    """Test AiiDAQueryAdapter with real AiiDA."""

    def test_create_and_list_jobs(self, aiida_profile, sample_input):
        """Test creating and listing jobs."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter(profile_name="crystal-tui")

        # Create a job
        job_id = adapter.create_job(
            name="E2E Test Job",
            input_content=sample_input,
        )

        assert job_id is not None
        assert isinstance(job_id, int)

        # List jobs
        jobs = adapter.list_jobs()
        assert len(jobs) > 0

        # Find our job
        created_job = None
        for job in jobs:
            if job["id"] == job_id:
                created_job = job
                break

        assert created_job is not None
        assert created_job["name"] == "E2E Test Job"

    def test_get_job_details(self, aiida_profile, sample_input):
        """Test retrieving job details."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        # Create a job
        job_id = adapter.create_job(name="Detail Test", input_content=sample_input)

        # Get job details
        job = adapter.get_job(job_id)

        assert job is not None
        assert job["id"] == job_id
        assert job["name"] == "Detail Test"
        assert "runner_type" in job
        assert job["runner_type"] == "aiida"

    def test_update_job(self, aiida_profile, sample_input):
        """Test updating job metadata."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        # Create and update job
        job_id = adapter.create_job(name="Update Test", input_content=sample_input)

        results = {"energy": -100.5, "converged": True}
        success = adapter.update_job(job_id, results_json=json.dumps(results))

        assert success

        # Verify update
        job = adapter.get_job(job_id)
        assert job["results_json"] is not None

    def test_delete_job(self, aiida_profile, sample_input):
        """Test soft-deleting a job."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        # Create and delete job
        job_id = adapter.create_job(name="Delete Test", input_content=sample_input)
        success = adapter.delete_job(job_id)

        assert success

    def test_get_job_count(self, aiida_profile):
        """Test counting jobs."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        count = adapter.get_job_count()
        assert isinstance(count, int)
        assert count >= 0


class TestMigration:
    """Test database migration from SQLite to AiiDA."""

    def test_migration_dry_run(self, aiida_profile, tmp_path):
        """Test migration in dry-run mode."""
        from src.aiida.migration import DatabaseMigrator
        import sqlite3

        # Create temporary SQLite database
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                name TEXT,
                status TEXT,
                input_content TEXT,
                created_at TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT INTO jobs (id, name, status, input_content)
            VALUES (1, 'Test Job', 'completed', 'CRYSTAL\nEND')
        """)
        conn.commit()
        conn.close()

        # Run migration in dry-run mode
        migrator = DatabaseMigrator(
            sqlite_path=db_path,
            aiida_profile="crystal-tui",
            dry_run=True,
        )

        stats = migrator.migrate_all()

        assert stats["jobs_found"] == 1
        assert stats["jobs_migrated"] == 1
        assert stats["jobs_failed"] == 0

    def test_migration_actual(self, aiida_profile, tmp_path):
        """Test actual migration (creates real nodes)."""
        from src.aiida.migration import DatabaseMigrator
        import sqlite3

        # Create temporary SQLite database
        db_path = tmp_path / "test_actual.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                name TEXT,
                status TEXT,
                input_content TEXT,
                results_json TEXT
            )
        """)
        conn.execute("""
            INSERT INTO jobs (id, name, status, input_content, results_json)
            VALUES (1, 'Migration Test', 'completed', 'CRYSTAL\nEND', '{"energy": -100.0}')
        """)
        conn.commit()
        conn.close()

        # Run actual migration
        migrator = DatabaseMigrator(
            sqlite_path=db_path,
            aiida_profile="crystal-tui",
            dry_run=False,
        )

        stats = migrator.migrate_all()

        assert stats["jobs_found"] == 1
        assert stats["jobs_migrated"] == 1
        assert stats["jobs_failed"] == 0

        # Verify migration
        verification = migrator.verify_migration()
        assert verification["migrated_nodes"] >= 1


class TestParser:
    """Test CRYSTAL23 output parser."""

    @pytest.fixture
    def sample_output(self):
        """Sample CRYSTAL23 output."""
        return """
CRYSTAL23 - SCF CALCULATION

CYC   ETOT(AU)      DETOT        CONV
  1  -100.123456   1.0E+00      N
  2  -100.234567   1.1E-01      Y

== SCF ENDED - CONVERGENCE ON ENERGY      E(AU)  -100.234567

TOTAL ENERGY(DFT)(AU) (  2) -100.234567

EEEEEEEE TERMINATION  DATE 01 01 2024 TIME 12:00:00.0
        """

    def test_parse_manual(self, aiida_profile, sample_output):
        """Test manual parsing without CRYSTALpytools."""
        from src.aiida.calcjobs.parser import Crystal23Parser
        from unittest.mock import MagicMock

        # Create mock parser
        parser = Crystal23Parser(MagicMock())
        parser.logger = MagicMock()

        results = parser._parse_manual(sample_output)

        assert results["parser"] == "manual"
        assert results["completed"] is True
        assert results["scf_converged"] is True
        assert "final_energy_hartree" in results
        assert results["final_energy_hartree"] == -100.234567


class TestFullWorkflow:
    """Test complete end-to-end workflows."""

    def test_create_submit_monitor(self, aiida_profile, sample_input):
        """Test creating, submitting, and monitoring a job.

        Note: This test creates a draft job but doesn't actually submit
        to a real CRYSTAL23 code (which would require setup).
        """
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        # Create job
        job_id = adapter.create_job(
            name="E2E Workflow Test",
            input_content=sample_input,
        )

        assert job_id is not None

        # Get status (should be 'draft' since we haven't submitted)
        job = adapter.get_job(job_id)
        assert job is not None
        assert "status" in job

        # Update with results (simulate completion)
        results = {
            "energy": -276.89,
            "converged": True,
            "scf_iterations": 3,
        }
        success = adapter.update_job(job_id, results_json=json.dumps(results))
        assert success

        # Verify results stored
        updated_job = adapter.get_job(job_id)
        assert updated_job["results_json"] is not None


class TestDockerInfrastructure:
    """Test Docker infrastructure management."""

    def test_docker_compose_config(self):
        """Test that docker-compose.yml exists and is valid."""
        compose_file = Path(__file__).parent.parent / "docker-compose.yml"
        assert compose_file.exists()

        # Validate YAML
        import yaml
        with open(compose_file) as f:
            config = yaml.safe_load(f)

        assert "services" in config
        assert "postgres" in config["services"]
        assert "rabbitmq" in config["services"]

    def test_env_example_exists(self):
        """Test that .env.example exists."""
        env_file = Path(__file__).parent.parent / ".env.example"
        assert env_file.exists()

        # Check required variables
        content = env_file.read_text()
        assert "POSTGRES_USER" in content
        assert "POSTGRES_PASSWORD" in content
        assert "RABBITMQ_DEFAULT_USER" in content
        assert "AIIDA_PROFILE_NAME" in content

    def test_setup_script_exists(self):
        """Test that Docker setup script exists and is executable."""
        script = Path(__file__).parent.parent / "scripts/docker_setup_aiida.sh"
        assert script.exists()
        assert os.access(script, os.X_OK), "Script should be executable"

    def test_teardown_script_exists(self):
        """Test that teardown script exists and is executable."""
        script = Path(__file__).parent.parent / "scripts/teardown_aiida_infrastructure.sh"
        assert script.exists()
        assert os.access(script, os.X_OK), "Script should be executable"


class TestDocumentation:
    """Test that documentation is complete."""

    def test_setup_docs_exist(self):
        """Test that AiiDA setup documentation exists."""
        docs = Path(__file__).parent.parent / "docs/AIIDA_SETUP.md"
        assert docs.exists()

        content = docs.read_text()
        assert "Quick Start" in content
        assert "Docker Compose" in content
        assert "Troubleshooting" in content
        assert "verdi" in content  # AiiDA CLI commands documented

    def test_readme_mentions_aiida(self):
        """Test that README mentions AiiDA integration."""
        readme = Path(__file__).parent.parent / "README.md"
        if readme.exists():
            content = readme.read_text()
            # Should mention AiiDA or link to docs
            assert "AiiDA" in content or "aiida" in content or "AIIDA_SETUP" in content


# Cleanup helpers for test data
@pytest.fixture(scope="session", autouse=True)
def cleanup_test_nodes():
    """Clean up test nodes after all tests."""
    yield

    # Optional: Clean up nodes created during tests
    # This can be done by marking them with extras during creation
    # and deleting them here
    pass
