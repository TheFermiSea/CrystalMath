---
name: epic-closure-validation
enabled: true
event: bash
action: block
conditions:
  - field: command
    operator: regex_match
    pattern: bd\s+close\s+[a-z]+-[a-z0-9]+|bd\s+update\s+.*--status\s*=?\s*closed
---

# BLOCKED: Epic Closure Requires Validation

**You cannot close a bd issue/epic until you verify the following:**

## Pre-Closure Checklist

Before closing any epic, you MUST confirm:

### 1. All Child Issues Closed
```bash
bd show <epic-id>  # Check all linked issues are closed
```

### 2. Cross-Validation Complete
- [ ] Codex review passed (via `mcp__pal__clink --cli_name=codex`)
- [ ] Gemini review passed (via `mcp__pal__clink --cli_name=gemini`)
- [ ] Any issues found were addressed and re-validated

### 3. Documentation Updated
- [ ] `CLAUDE.md` updated with architecture/workflow changes
- [ ] `AGENTS.md` updated if agent patterns changed
- [ ] `GEMINI.md` updated if applicable

## To Proceed

1. First verify all items above are complete
2. Run `bd list --parent=<epic-id>` to confirm all child issues closed
3. If validation/docs issues don't exist, create them now (see epic-creation-workflow rule)
4. Once verified, explicitly state: "All epic closure requirements verified" and retry

**This block exists to ensure quality and documentation standards are maintained.**
