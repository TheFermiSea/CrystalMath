# SLURM Security Guide for Developers

## Quick Reference: Input Validation

### Using SLURMRunner Securely

```python
from src.runners.slurm_runner import SLURMRunner, SLURMJobConfig, SLURMValidationError

# Create runner
runner = SLURMRunner(connection_manager, cluster_id=1)

# Create config with user input
config = SLURMJobConfig(
    job_name=user_provided_name,  # VALIDATED: alphanumeric, -, _ only
    partition=user_partition,      # VALIDATED: alphanumeric, _ only
    modules=user_modules,          # VALIDATED: alphanumeric, /, -, . only
    email=user_email,              # VALIDATED: RFC email format
    time_limit=user_time,          # VALIDATED: HH:MM:SS or DD-HH:MM:SS
)

try:
    # Validation happens automatically in _generate_slurm_script()
    script = runner._generate_slurm_script(config, "/scratch/work")
except SLURMValidationError as e:
    # Handle invalid input
    print(f"Invalid configuration: {e}")
    # Show user an error message
```

## Validation Methods

All validation methods are static and can be used independently:

```python
# Validate individual fields
try:
    SLURMRunner._validate_job_name("my-job")  # OK
    SLURMRunner._validate_partition("compute")  # OK
    SLURMRunner._validate_module("intel/2023")  # OK
    SLURMRunner._validate_email("user@example.com")  # OK
except SLURMValidationError as e:
    print(f"Validation error: {e}")

# Validate entire config
runner = SLURMRunner(...)
try:
    runner._validate_config(config)
except SLURMValidationError as e:
    print(f"Configuration error: {e}")
```

## What Gets Validated?

### Automatically Validated in _generate_slurm_script()

✓ Job name format and length
✓ Partition name validity
✓ Module names (each module)
✓ Account name format
✓ QOS name format
✓ Email address format
✓ Time limit format
✓ Job dependencies (numeric IDs)
✓ Array specification format
✓ Work directory path (no injection)
✓ Environment setup (no dangerous commands)
✓ Email notification types
✓ Numeric field bounds (nodes >= 1, tasks >= 1, etc.)

### What's Allowed vs Blocked

| Field | Allowed Characters | Blocked Patterns |
|-------|------------------|---------|
| job_name | `a-z A-Z 0-9 - _` | `; \| & $ (\` ` ` |
| partition | `a-z A-Z 0-9 _` | `; \| & $ (` ` ` |
| module | `a-z A-Z 0-9 / - . _` | `; \| & $ (\` ` ` |
| account | `a-z A-Z 0-9 _` | `; \| & $ (\` ` ` |
| qos | `a-z A-Z 0-9 - _` | `; \| & $ (\` ` ` |
| email | RFC 5321 format | Shell metacharacters |
| dependency | `0-9` only | `-` `; \| & $ (\` ` ` |
| array | `0-9 , - :` | `; \| & $ (\` ` ` |
| env_setup | `export X=val`, `source`, `.` | Command chaining, substitution |

## Example: Safe Configuration Flow

```python
# 1. Get user input
user_job_name = request.json['job_name']  # User input from API/UI

# 2. Create config
config = SLURMJobConfig(
    job_name=user_job_name,
    partition=user_partition,
    modules=["crystal23"],  # Default module, user can't inject
    time_limit="24:00:00",
)

# 3. Try to generate script
try:
    script = runner._generate_slurm_script(config, "/scratch/work")
except SLURMValidationError as e:
    # User provided invalid input
    return {"error": f"Invalid job configuration: {str(e)}"}, 400

# 4. Script is now guaranteed safe
# SBATCH directives are properly escaped
# No shell metacharacters in user-controlled fields
```

## Error Handling

### Common Validation Errors

```python
try:
    runner._validate_job_name("test; rm -rf /")
except SLURMValidationError:
    # Invalid job name: 'test; rm -rf /'
    # must contain only alphanumeric characters, hyphens, and underscores
    pass

try:
    runner._validate_partition("compute && bad")
except SLURMValidationError:
    # Invalid partition 'compute && bad'
    # must contain only alphanumeric characters and underscores
    pass

try:
    runner._validate_email("user@; cat /etc")
except SLURMValidationError:
    # Invalid email address: user@; cat /etc
    pass

try:
    runner._validate_time_limit("01:00; rm")
except SLURMValidationError:
    # Invalid time limit '01:00; rm'
    # must be in format HH:MM:SS or [DD-]HH:MM:SS
    pass
```

## Best Practices

### 1. Always Use SLURMJobConfig
```python
# GOOD: Uses validation
config = SLURMJobConfig(job_name=user_input)
script = runner._generate_slurm_script(config, work_dir)

# BAD: Bypasses validation
script = f"#SBATCH --job-name={user_input}"  # VULNERABLE!
```

### 2. Catch Validation Errors
```python
# GOOD: Handle validation errors
try:
    script = runner._generate_slurm_script(config, work_dir)
except SLURMValidationError as e:
    logger.warning(f"Invalid config: {e}")
    return error_response(str(e))

# BAD: Ignore validation errors
script = runner._generate_slurm_script(config, work_dir)  # May fail
```

### 3. Use Pre-defined Default Values
```python
# GOOD: Secure defaults
config = SLURMJobConfig(
    job_name=user_name,
    modules=["crystal23"],  # Hardcoded trusted modules
    partition=user_choice,
)

# BAD: User controls everything
config = SLURMJobConfig(
    job_name=user_name,
    modules=user_modules,  # Could inject malicious modules
    partition=user_partition,
)
```

### 4. Log Validation Failures
```python
import logging

logger = logging.getLogger(__name__)

try:
    script = runner._generate_slurm_script(config, work_dir)
except SLURMValidationError as e:
    logger.warning(
        f"Rejected invalid SLURM config",
        extra={
            "job_name": config.job_name,
            "partition": config.partition,
            "error": str(e),
        }
    )
```

## Testing Your Integration

```python
import pytest
from src.runners.slurm_runner import SLURMJobConfig, SLURMValidationError

def test_user_job_name_validation():
    """Test that user-provided job names are validated."""

    # Valid names should work
    config = SLURMJobConfig(job_name="user_job_123")
    runner._validate_config(config)  # Should not raise

    # Invalid names should raise
    with pytest.raises(SLURMValidationError):
        config = SLURMJobConfig(job_name="user; rm -rf /")
        runner._validate_config(config)

    # Empty names should raise
    with pytest.raises(SLURMValidationError):
        config = SLURMJobConfig(job_name="")
        runner._validate_config(config)
```

## Frequently Asked Questions

### Q: Can users specify any partition they want?
**A:** Partitions must match `^[a-zA-Z0-9_]+$`. You should validate against available partitions in your system and whitelist them separately if needed.

### Q: What if a user needs complex environment setup?
**A:** Use `source` or `.` to load a script:
```python
config = SLURMJobConfig(
    environment_setup="source /opt/crystal/complex_setup.sh"
)
```
The path is validated to ensure it doesn't contain shell metacharacters.

### Q: Can users specify custom modules?
**A:** Yes, module names support `intel/2023` or `gcc-11` style names, but cannot contain shell metacharacters. If you want to restrict modules, maintain a separate allowlist.

### Q: How strict are the validation rules?
**A:** Very strict - they use whitelist (allow-only) approach rather than blacklist. If something isn't explicitly allowed, it's rejected. This is more secure but may reject some edge cases.

### Q: Can I bypass validation for trusted input?
**A:** Not recommended. The validation is fast (regex matching). Always validate user input. However, if you have truly trusted input (hardcoded strings), you can construct the script directly without validation.

---

## Summary

The SLURM runner now:
- ✓ Validates all user input before using it
- ✓ Rejects anything that looks like command injection
- ✓ Provides clear error messages
- ✓ Uses defense-in-depth with both validation and escaping
- ✓ Is fully tested against injection attacks

**Never construct SLURM scripts with string concatenation.** Always use `SLURMJobConfig` and `_generate_slurm_script()`.
