# AiiDA Backend Integration

This guide focuses on the Python code needed to replace your custom `workflow.py` with AiiDA, exposing a clean API for Rust.

## 1. The Controller Facade (`python/crystalmath/api.py`)

This class is the single point of entry for the Rust application. It initializes the AiiDA environment and handles data retrieval.

```python
import json
from typing import List, Optional
import aiida
from aiida import orm
from aiida.engine import submit
from aiida.common import NotExistent

from .models import JobStatus, JobSubmission, JobDetails, JobState
from .aiida_plugin.calcjobs.crystal23 import Crystal23Calculation


class CrystalController:
    def __init__(self, profile_name: str = 'default'):
        """Initialize AiiDA profile."""
        try:
            aiida.load_profile(profile_name)
        except Exception as e:
            print(f"Error loading AiiDA profile: {e}")

    def get_jobs_json(self) -> str:
        """
        Returns a JSON string of all jobs matching the schema.
        Rust calls this method directly.
        """
        qb = orm.QueryBuilder()
        qb.append(
            orm.CalcJob,
            project=['id', 'uuid', 'label', 'attributes.process_state', 'attributes.exit_status']
        )
        qb.order_by({orm.CalcJob: {'ctime': 'desc'}})
        
        results = []
        for pk, uuid, label, state, exit_status in qb.all():
            # Determine simplified state
            if state == 'finished':
                ui_state = JobState.COMPLETED if exit_status == 0 else JobState.FAILED
            elif state == 'excepted' or state == 'killed':
                ui_state = JobState.FAILED
            elif state == 'running' or state == 'waiting':
                ui_state = JobState.RUNNING
            else:
                ui_state = JobState.CREATED

            job = JobStatus(
                pk=pk,
                uuid=uuid,
                name=label or f"Job {pk}",
                state=ui_state,
                progress_percent=0.0,  # TODO: Parse progress from output nodes if running
            )
            results.append(job.model_dump())
            
        return json.dumps(results)

    def submit_job_json(self, json_payload: str) -> int:
        """
        Accepts a JSON payload from Rust, validates it, and submits an AiiDA job.
        """
        try:
            data = JobSubmission.model_validate_json(json_payload)
            
            # Load the computer/code
            # In production, these should be looked up via ID or Name
            code = orm.load_code("crystal@localhost") 
            
            builder = Crystal23Calculation.get_builder()
            builder.code = code
            builder.metadata.label = data.name
            builder.metadata.options.resources = {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 1
            }
            
            # Map parameters to AiiDA Dict
            builder.crystal.parameters = orm.Dict(dict=data.parameters)
            
            # Handle Structure (pseudo-code)
            # if data.structure_path:
            #     structure = orm.StructureData(pymatgen_structure=...)
            #     builder.crystal.structure = structure
            
            node = submit(builder)
            return node.pk
            
        except Exception as e:
            # Propagate error string back to Rust
            raise RuntimeError(f"Submission failed: {str(e)}")

    def get_job_details_json(self, pk: int) -> str:
        """Fetch detailed results for the Results Tab."""
        try:
            node = orm.load_node(pk)
            
            # Retrieve output parameters if available
            output_params = (
                node.outputs.output_parameters.get_dict()
                if 'output_parameters' in node.outputs
                else {}
            )
            
            # Get stdout logs
            stdout = ""
            if 'retrieved' in node.outputs:
                try:
                    stdout = node.outputs.retrieved.get_object_content('_scheduler-stdout.txt')
                except:
                    pass

            details = JobDetails(
                pk=pk,
                final_energy=output_params.get('energy'),
                convergence_met=output_params.get('converged', False),
                warnings=[], 
                stdout_tail=stdout.splitlines()[-50:]  # Last 50 lines
            )
            return details.model_dump_json()
        except NotExistent:
            return "{}"
```

## 2. Replacing the Workflow Engine

Your `tui/src/core/workflow.py` implemented a custom DAG. AiiDA handles this natively using **WorkChains**.

### Example: A Simple Relaxation WorkChain

`python/crystalmath/aiida_plugin/workchains/relax.py`

```python
from aiida.engine import WorkChain, ToContext
from aiida.orm import Dict, StructureData
from ..calcjobs.crystal23 import Crystal23Calculation


class CrystalRelaxWorkChain(WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.expose_inputs(Crystal23Calculation, namespace='crystal')
        spec.outline(
            cls.run_optimization,
            cls.inspect_results,
        )
        spec.output('final_structure', valid_type=StructureData)

    def run_optimization(self):
        """Run the geometry optimization."""
        inputs = self.exposed_inputs(Crystal23Calculation, 'crystal')
        # Force optimization flags
        params = inputs.crystal.parameters.get_dict()
        params['OPTGEOM'] = {} 
        inputs.crystal.parameters = Dict(dict=params)
        
        running = self.submit(Crystal23Calculation, **inputs)
        return ToContext(work=running)

    def inspect_results(self):
        """Check convergence and output final structure."""
        work = self.ctx.work
        if not work.is_finished_ok:
            return self.exit_codes.ERROR_CALCULATION_FAILED
            
        self.out('final_structure', work.outputs.output_structure)
```

In Rust, you simply invoke this WorkChain via `submit(CrystalRelaxWorkChain, ...)` inside your controller.
