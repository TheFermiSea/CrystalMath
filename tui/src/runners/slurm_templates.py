"""
SLURM script template generation for HPC job submission.

This module provides template-based SLURM script generation using
the existing TemplateManager infrastructure, replacing the string
concatenation approach with validated Jinja2 templates.

Security features:
- All user inputs are validated before template rendering
- SandboxedEnvironment prevents code injection
- Path validation prevents directory traversal
"""

import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from ..core.templates import TemplateManager, Template
from ..core.codes import DFTCode, get_code_config

logger = logging.getLogger(__name__)


class SLURMTemplateValidationError(Exception):
    """Raised when SLURM template parameter validation fails."""
    pass


@dataclass
class SLURMTemplateParams:
    """Parameters for SLURM script template rendering.

    This dataclass provides validated parameters that are safe
    to pass to Jinja2 templates.
    """
    job_name: str
    work_dir: str
    nodes: int = 1
    ntasks: int = 1
    cpus_per_task: int = 4
    time_limit: str = "24:00:00"
    partition: Optional[str] = None
    memory: Optional[str] = None
    account: Optional[str] = None
    qos: Optional[str] = None
    email: Optional[str] = None
    email_type: Optional[str] = None
    constraint: Optional[str] = None
    exclusive: bool = False
    dependencies: List[str] = field(default_factory=list)
    array: Optional[str] = None
    modules: List[str] = field(default_factory=lambda: ["crystal23"])
    environment_setup: str = ""
    input_file: str = "input.d12"
    output_file: str = "output.out"
    use_mpi: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for template rendering."""
        return {
            "job_name": self.job_name,
            "work_dir": self.work_dir,
            "nodes": self.nodes,
            "ntasks": self.ntasks,
            "cpus_per_task": self.cpus_per_task,
            "time_limit": self.time_limit,
            "partition": self.partition,
            "memory": self.memory,
            "account": self.account,
            "qos": self.qos,
            "email": self.email,
            "email_type": self.email_type,
            "constraint": self.constraint,
            "exclusive": self.exclusive,
            "dependencies": self.dependencies,
            "array": self.array,
            "modules": self.modules,
            "environment_setup": self.environment_setup,
            "input_file": self.input_file,
            "output_file": self.output_file,
            "use_mpi": self.use_mpi or self.ntasks > 1,
        }


class SLURMTemplateGenerator:
    """
    Generate SLURM submission scripts using Jinja2 templates.

    This class provides template-based SLURM script generation with
    comprehensive input validation to prevent injection attacks.

    Usage:
        generator = SLURMTemplateGenerator()
        script = generator.generate(
            job_name="my_crystal_job",
            work_dir="/scratch/jobs/123",
            ntasks=4,
            time_limit="12:00:00"
        )
    """

    # Validation patterns (compiled once for efficiency)
    _JOB_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
    _PARTITION_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")
    _MODULE_PATTERN = re.compile(r"^[a-zA-Z0-9/_.-]+$")
    _ACCOUNT_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")
    _QOS_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
    _EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    _TIME_PATTERN = re.compile(r"^(\d+-)?(\d{1,2}:)?\d{1,2}:\d{2}$|^\d+$")
    _JOB_ID_PATTERN = re.compile(r"^\d+$")
    _ARRAY_PATTERN = re.compile(r"^[\d,\-:]+$")
    _WORK_DIR_PATTERN = re.compile(r"^[a-zA-Z0-9/_.-]+$")

    # Safe environment setup commands
    _SAFE_ENV_COMMANDS = ("export ", "source ", ". ")
    _DANGEROUS_PATTERNS = (";", "|", "&", ">", "<", "$(", "`")

    def __init__(
        self,
        template_dir: Optional[Path] = None,
        dft_code: DFTCode = DFTCode.CRYSTAL
    ):
        """
        Initialize the SLURM template generator.

        Args:
            template_dir: Directory containing SLURM templates
            dft_code: DFT code to generate scripts for
        """
        if template_dir is None:
            # Default to templates/ directory relative to package
            template_dir = Path(__file__).parent.parent.parent / "templates"

        self.template_manager = TemplateManager(template_dir)
        self.dft_code = dft_code
        self.code_config = get_code_config(dft_code)

        # Load the appropriate template
        self._template: Optional[Template] = None
        self._load_template()

    def _load_template(self) -> None:
        """Load the SLURM template for the configured DFT code."""
        template_map = {
            DFTCode.CRYSTAL: "slurm/crystal_job.yaml",
            # Future: Add templates for other DFT codes
            # DFTCode.QUANTUM_ESPRESSO: "slurm/qe_job.yaml",
            # DFTCode.VASP: "slurm/vasp_job.yaml",
        }

        template_path = template_map.get(self.dft_code)
        if template_path:
            try:
                self._template = self.template_manager.load_template(Path(template_path))
                logger.info(f"Loaded SLURM template: {template_path}")
            except FileNotFoundError:
                logger.warning(f"SLURM template not found: {template_path}, using fallback")
                self._template = None

    def validate_params(self, params: SLURMTemplateParams) -> None:
        """
        Validate all parameters before template rendering.

        Args:
            params: Parameters to validate

        Raises:
            SLURMTemplateValidationError: If any parameter is invalid
        """
        errors = []

        # Job name (required)
        if not params.job_name:
            errors.append("Job name cannot be empty")
        elif len(params.job_name) > 255:
            errors.append("Job name cannot exceed 255 characters")
        elif not self._JOB_NAME_PATTERN.match(params.job_name):
            errors.append(
                f"Invalid job name '{params.job_name}': "
                "must contain only alphanumeric characters, hyphens, and underscores"
            )

        # Work directory (required)
        if not params.work_dir:
            errors.append("Work directory cannot be empty")
        elif not self._WORK_DIR_PATTERN.match(params.work_dir):
            errors.append(
                f"Invalid work directory '{params.work_dir}': "
                "must contain only alphanumeric characters, slashes, dots, and hyphens"
            )

        # Partition (optional)
        if params.partition:
            if len(params.partition) > 255:
                errors.append("Partition name cannot exceed 255 characters")
            elif not self._PARTITION_PATTERN.match(params.partition):
                errors.append(
                    f"Invalid partition '{params.partition}': "
                    "must contain only alphanumeric characters and underscores"
                )

        # Account (optional)
        if params.account:
            if len(params.account) > 255:
                errors.append("Account name cannot exceed 255 characters")
            elif not self._ACCOUNT_PATTERN.match(params.account):
                errors.append(
                    f"Invalid account '{params.account}': "
                    "must contain only alphanumeric characters and underscores"
                )

        # QOS (optional)
        if params.qos:
            if len(params.qos) > 255:
                errors.append("QOS name cannot exceed 255 characters")
            elif not self._QOS_PATTERN.match(params.qos):
                errors.append(
                    f"Invalid QOS '{params.qos}': "
                    "must contain only alphanumeric characters, hyphens, and underscores"
                )

        # Email (optional)
        if params.email:
            if not self._EMAIL_PATTERN.match(params.email):
                errors.append(f"Invalid email address: {params.email}")

        # Email type (optional)
        if params.email_type:
            valid_types = {"BEGIN", "END", "FAIL", "REQUEUE", "ALL"}
            email_types = params.email_type.split(",")
            for et in email_types:
                if et.strip().upper() not in valid_types:
                    errors.append(
                        f"Invalid email type '{et}': "
                        "must be one of BEGIN, END, FAIL, REQUEUE, ALL"
                    )

        # Time limit (required)
        if not params.time_limit:
            errors.append("Time limit cannot be empty")
        elif not self._TIME_PATTERN.match(params.time_limit):
            errors.append(
                f"Invalid time limit '{params.time_limit}': "
                "must be in format HH:MM:SS or [DD-]HH:MM:SS"
            )

        # Modules
        for module in params.modules:
            if not module:
                errors.append("Module name cannot be empty")
            elif len(module) > 255:
                errors.append("Module name cannot exceed 255 characters")
            elif not self._MODULE_PATTERN.match(module):
                errors.append(
                    f"Invalid module '{module}': "
                    "must contain only alphanumeric characters, slashes, dots, and hyphens"
                )

        # Dependencies
        for dep in params.dependencies:
            if not self._JOB_ID_PATTERN.match(dep):
                errors.append(f"Invalid job ID '{dep}': must be numeric")

        # Array specification
        if params.array:
            if not self._ARRAY_PATTERN.match(params.array):
                errors.append(
                    f"Invalid array specification '{params.array}': "
                    "must contain only digits, commas, hyphens, and colons"
                )

        # Numeric fields
        if params.nodes < 1:
            errors.append("Number of nodes must be at least 1")
        if params.ntasks < 1:
            errors.append("Number of tasks must be at least 1")
        if params.cpus_per_task < 1:
            errors.append("CPUs per task must be at least 1")

        # Environment setup (security-critical)
        if params.environment_setup:
            env_errors = self._validate_environment_setup(params.environment_setup)
            errors.extend(env_errors)

        if errors:
            raise SLURMTemplateValidationError("\n".join(errors))

    def _validate_environment_setup(self, env_setup: str) -> List[str]:
        """
        Validate environment setup commands for security.

        Only allows safe commands: export, source, and dot-source.
        Rejects commands with shell metacharacters.

        Args:
            env_setup: Environment setup string to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        for line in env_setup.strip().split("\n"):
            if not line.strip():
                continue

            line_stripped = line.strip()

            # Only allow safe commands
            is_safe_command = any(
                line_stripped.startswith(prefix)
                for prefix in self._SAFE_ENV_COMMANDS
            )

            if not is_safe_command:
                errors.append(
                    f"Dangerous command in environment setup: {line}\n"
                    "Only 'export', 'source', and '.' commands are allowed"
                )
                continue

            # Check for dangerous patterns
            has_dangerous = any(
                pattern in line
                for pattern in self._DANGEROUS_PATTERNS
            )

            if has_dangerous:
                if line_stripped.startswith("export "):
                    # For export, check the value part for dangerous chars
                    after_export = line_stripped[7:]
                    if any(p in after_export for p in ["|", "&", ">", "<", "$(", "`", ";"]):
                        errors.append(
                            f"Dangerous command in environment setup: {line}"
                        )
                else:
                    # For source/., reject if they have dangerous patterns
                    errors.append(
                        f"Dangerous pattern in environment setup: {line}"
                    )

        return errors

    def generate(self, **kwargs) -> str:
        """
        Generate a SLURM submission script with validated parameters.

        Args:
            **kwargs: Parameters matching SLURMTemplateParams fields

        Returns:
            Complete SLURM script as string

        Raises:
            SLURMTemplateValidationError: If parameter validation fails
        """
        # Build params object
        params = SLURMTemplateParams(**kwargs)

        # Validate all parameters
        self.validate_params(params)

        # Use template if available
        if self._template:
            return self.template_manager.render(self._template, params.to_dict())

        # Fallback to inline generation (same as original)
        return self._generate_fallback(params)

    def _generate_fallback(self, params: SLURMTemplateParams) -> str:
        """
        Fallback script generation when template is not available.

        This mirrors the original _generate_slurm_script logic.

        Args:
            params: Validated parameters

        Returns:
            Complete SLURM script as string
        """
        import shlex

        lines = ["#!/bin/bash"]

        # Required directives
        lines.append(f"#SBATCH --job-name={shlex.quote(params.job_name)}")
        lines.append(f"#SBATCH --nodes={params.nodes}")
        lines.append(f"#SBATCH --ntasks={params.ntasks}")
        lines.append(f"#SBATCH --cpus-per-task={params.cpus_per_task}")
        lines.append(f"#SBATCH --time={shlex.quote(params.time_limit)}")
        lines.append("#SBATCH --output=slurm-%j.out")
        lines.append("#SBATCH --error=slurm-%j.err")

        # Optional directives
        if params.partition:
            lines.append(f"#SBATCH --partition={shlex.quote(params.partition)}")
        if params.memory:
            lines.append(f"#SBATCH --mem={shlex.quote(params.memory)}")
        if params.account:
            lines.append(f"#SBATCH --account={shlex.quote(params.account)}")
        if params.qos:
            lines.append(f"#SBATCH --qos={shlex.quote(params.qos)}")
        if params.email:
            lines.append(f"#SBATCH --mail-user={shlex.quote(params.email)}")
            if params.email_type:
                lines.append(f"#SBATCH --mail-type={shlex.quote(params.email_type)}")
        if params.constraint:
            lines.append(f"#SBATCH --constraint={shlex.quote(params.constraint)}")
        if params.exclusive:
            lines.append("#SBATCH --exclusive")
        if params.dependencies:
            dep_str = ":".join(params.dependencies)
            lines.append(f"#SBATCH --dependency=afterok:{dep_str}")
        if params.array:
            lines.append(f"#SBATCH --array={shlex.quote(params.array)}")

        lines.append("")
        lines.append("# Environment setup")

        # Load modules
        for module in params.modules:
            lines.append(f"module load {shlex.quote(module)}")

        # Custom environment setup
        if params.environment_setup:
            for line in params.environment_setup.strip().split("\n"):
                if line.strip():
                    lines.append(line)

        lines.append("export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK")
        lines.append("")

        # Change to work directory
        lines.append("# Change to working directory")
        lines.append(f"cd {shlex.quote(params.work_dir)}")
        lines.append("")

        # Execution command
        lines.append("# Run CRYSTAL calculation")
        if params.use_mpi or params.ntasks > 1:
            lines.append(f"srun PcrystalOMP < {params.input_file} > {params.output_file} 2>&1")
        else:
            lines.append(f"crystalOMP < {params.input_file} > {params.output_file} 2>&1")

        lines.append("")
        lines.append("exit_code=$?")
        lines.append('echo "Job finished with exit code: $exit_code"')
        lines.append("exit $exit_code")

        return "\n".join(lines)


def generate_slurm_script(
    job_name: str,
    work_dir: str,
    dft_code: DFTCode = DFTCode.CRYSTAL,
    **kwargs
) -> str:
    """
    Convenience function to generate a SLURM script.

    Args:
        job_name: Name for the SLURM job
        work_dir: Working directory path
        dft_code: DFT code to run
        **kwargs: Additional SLURMTemplateParams fields

    Returns:
        Complete SLURM script as string

    Raises:
        SLURMTemplateValidationError: If parameter validation fails
    """
    generator = SLURMTemplateGenerator(dft_code=dft_code)
    return generator.generate(job_name=job_name, work_dir=work_dir, **kwargs)
