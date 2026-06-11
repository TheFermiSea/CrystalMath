#!/bin/bash
set -e

echo "================================================================="
echo "🛠️ Repairing Syntax Errors and Indentation Anomalies..."
echo "================================================================="

python3 -c "
import os

# --- Fix 1: Repair slurm_runner.py script string literal ---
runner_path = 'python/crystalmath/integrations/slurm_runner.py'
if os.path.exists(runner_path):
    with open(runner_path, 'r') as f:
        content = f.read()
    
    if 'def generate_sbatch_script' in content:
        # Truncate the broken appended function block
        content = content.split('def generate_sbatch_script')[0]
        
        clean_func = \"\"\"def generate_sbatch_script(config_dict: dict, execution_commands: list[str]) -> str:
    \\\"\\\"\\\"
    Programmatically builds clean, standardized #SBATCH script headers from 
    dictionary configurations instead of brittle raw text block formats.
    \\\"\\\"\\\"
    script_lines = ['#!/bin/bash']
    
    # Process standard headers deterministically
    for key, val in config_dict.items():
        normalized_key = key.replace('_', '-')
        script_lines.append(f'#SBATCH --{normalized_key}={val}')
        
    script_lines.append('') # Spatial padding
    script_lines.extend(execution_commands)
    return '\\n'.join(script_lines)
\"\"\"
        with open(runner_path, 'w') as f:
            f.write(content + clean_func)
        print('✅ slurm_runner.py string literals fixed.')

# --- Fix 2: Purge faulty unindented exceptions from api.py ---
api_path = 'python/crystalmath/api.py'
if os.path.exists(api_path):
    with open(api_path, 'r') as f:
        lines = f.readlines()
        
    cleaned_lines = []
    skip_count = 0
    purged_count = 0
    
    for i, line in enumerate(lines):
        if skip_count > 0:
            skip_count -= 1
            continue
            
        if 'Database/Controller startup failure initialization crash' in line:
            if i + 1 < len(lines) and 'DB Initialization Failed' in lines[i+1]:
                skip_count = 1  # Skip this line and the following raise line
                purged_count += 1
                continue
                
        cleaned_lines.append(line)
        
    with open(api_path, 'w') as f:
        f.writelines(cleaned_lines)
    print(f'✅ api.py cleared: Removed {purged_count} malformed exception blocks.')
"

echo "================================================================="
echo "🧼 Re-running Compliance and Code Formatting Suite..."
echo "================================================================="
uv run black python/crystalmath/
uv run ruff check python/crystalmath/ --fix --unsafe-fixes
