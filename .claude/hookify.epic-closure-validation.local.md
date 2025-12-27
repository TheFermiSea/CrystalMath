---
name: epic-closure-validation
enabled: true
event: bash
action: block
conditions:
  - field: command
    operator: regex_match
    # Only match EPIC closures (IDs without dots), NOT child tasks (IDs with .N suffix)
    # Epics:      crystalmath-7mw, crystalmath-cn9    → BLOCKED
    # Child tasks: crystalmath-7mw.1, crystalmath-cn9.3 → ALLOWED
    pattern: bd\s+close\s+[a-z]+-[a-z0-9]+(?!\.[0-9])(\s|$)
---

# BLOCKED: Epic Closure Requires Validation

**This hook ONLY blocks epic closures.** Child task closures (`crystalmath-xxx.N`) are allowed.

## What's Blocked vs Allowed

| Command | Result | Reason |
|---------|--------|--------|
| `bd close crystalmath-7mw` | BLOCKED | Epic closure requires validation |
| `bd close crystalmath-7mw.1` | ALLOWED | Child task, no validation needed |
| `bd close crystalmath-7mw.1 -d "notes"` | ALLOWED | Child task with description |

---

## Epic Pre-Closure Checklist

Before closing an **epic**, you MUST verify:

### 1. All Child Issues Closed
```bash
bd list --parent=<epic-id>  # Verify all children are closed
bd show <epic-id>           # Check epic status and children
```

### 2. Cross-Validation Complete
- [ ] Codex review passed: `mcp__pal__clink` with `cli_name=codex`
- [ ] Gemini review passed: `mcp__pal__clink` with `cli_name=gemini`
- [ ] Any issues found were fixed and re-validated

### 3. Documentation Updated
- [ ] `CLAUDE.md` - Architecture/workflow changes documented
- [ ] `AGENTS.md` - Agent patterns updated (if applicable)
- [ ] Project-specific docs updated

---

## How to Proceed with Epic Closure

1. Complete all validation steps above
2. Confirm with: **"All epic closure requirements verified for `<epic-id>`"**
3. The hook will be bypassed for the explicit closure

**Tip:** Use `bd close <epic-id> -d "Validated: Codex/Gemini approved, docs updated"` to document the validation.
