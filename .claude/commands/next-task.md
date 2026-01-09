---
description: Select and claim the next available task from the crystalmath integration project
arguments: []
---

# Next Task Selection

Find and claim the next available task from the CrystalMath workflow integration project.

## Steps

1. **Check current progress**
   ```bash
   cat PROGRESS.json | jq '{phase: .current_phase, task: .current_task}'
   ```

2. **Find ready tasks from beads**
   ```bash
   bd ready | grep crystalmath
   ```

3. **Show task details**
   For the first ready task, show its full details:
   ```bash
   bd show <task-id>
   ```

4. **Read the meta-prompt**
   Based on the task number, read the corresponding prompt section:
   - Tasks 1.x → Phase 1: Research
   - Tasks 2.x → Phase 2: Architecture
   - Tasks 3.x → Phase 3: Implementation
   - Tasks 4.x → Phase 4: Documentation

   ```bash
   cat prompts/META-PROMPT-WORKFLOW-INTEGRATION.md | grep -A 50 "Prompt <X.Y>"
   ```

5. **Claim the task**
   ```bash
   bd update <task-id> --status in_progress
   ```

6. **Update PROGRESS.json**
   Update the current_task field to the claimed task ID.

7. **Select appropriate agent**
   Based on the task phase, recommend using:
   - Phase 1 → `research-agent`
   - Phase 2 → `architect-agent`
   - Phase 3 → `implement-agent`
   - Phase 4 → `docs-agent`

## Output

Report:
- Task ID and title
- Phase and prompt reference
- Recommended agent
- Key deliverables from the prompt
