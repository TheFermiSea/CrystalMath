---
name: epic-creation-workflow
enabled: true
event: bash
conditions:
  - field: command
    operator: regex_match
    pattern: bd\s+create\s+.*\[epic\]|bd\s+create\s+--type\s*=?\s*epic
---

# Epic Creation Workflow Required

You are creating a bd epic. **Before proceeding**, you MUST create two mandatory blocked issues:

## 1. Cross-Validation Issue (Create First)

```bash
bd create "[task] Cross-validate epic completion with Codex/Gemini" \
  --blocked-by="ALL_OTHER_EPIC_ISSUES" \
  --labels="validation,quality,blocked"
```

**Purpose:** After all implementation tasks are done, use `mcp__pal__clink` to:
- Run Codex review: `clink --cli_name=codex --prompt="Review the implementation for [epic description]"`
- Run Gemini review: `clink --cli_name=gemini --prompt="Review the implementation for [epic description]"`
- If issues found: reopen/create issues and fix them
- Only close when both Codex and Gemini approve

## 2. Documentation Update Issue (Create Second)

```bash
bd create "[task] Update project documentation (CLAUDE.md, AGENTS.md, GEMINI.md)" \
  --blocked-by="CROSS_VALIDATION_ISSUE" \
  --labels="documentation,blocked"
```

**Purpose:** After cross-validation passes:
- Update `CLAUDE.md` with any architecture/workflow changes
- Update `AGENTS.md` if agent patterns changed
- Update `GEMINI.md` if applicable
- Only close after docs are updated and verified

## Workflow Summary

```
Epic Created
    │
    ├── Implementation Tasks (user-defined)
    │       │
    │       ▼ (all closed)
    │
    ├── Cross-Validation Task (blocked until above done)
    │       │
    │       ▼ (Codex + Gemini approve)
    │
    └── Documentation Update Task (blocked until validation done)
            │
            ▼ (docs updated)

Epic Can Be Closed
```

**ACTION REQUIRED:** Create both issues now before continuing with epic creation.
