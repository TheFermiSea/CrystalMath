# runcrystal Refactoring Plan

## Project Overview

**Epic:** CRY_CLI-oxy - Refactor runcrystal into modular architecture

Transform the monolithic 372-line runcrystal script into a production-grade modular CLI tool with separate lib/ modules, shared UI components, and comprehensive testing.

**Current Status:**
- Total Tasks: 24
- Ready to Start: 10
- Blocked: 14
- In Progress: 0

## Architecture Design

Based on analysis from gemini-2.5-pro and codex, the refactored system will use:

### Module Structure

```
bin/runcrystal          # Main script (<100 lines, thin orchestrator)
lib/
  ├── cry-config.sh     # Configuration & environment (CRY23_ROOT, paths, theme)
  ├── cry-logging.sh    # Logging infrastructure (cry_log, cry_fatal, cry_warn)
  ├── core.sh           # Module loader (cry_require with error handling)
  ├── cry-ui.sh         # Visual components (banner, cards, theme system)
  ├── cry-parallel.sh   # Parallelism logic (MPI/OpenMP resource allocation)
  ├── cry-scratch.sh    # Scratch space lifecycle management
  ├── cry-stage.sh      # File staging utilities (input/output copying)
  ├── cry-exec.sh       # Calculation execution (command building, running)
  └── cry-help.sh       # Help system (interactive menu)
tests/
  ├── helpers.bash      # Test utilities and mocks
  ├── mocks/            # Fake binaries for testing
  └── *.bats            # Unit and integration tests
```

### Key Design Patterns

1. **State Management:** CRY_JOB associative array passed by reference
2. **Error Handling:** Modules return exit codes, main script uses trap-based cleanup
3. **UI Abstraction:** Theme registry allows cry-docs to reuse components
4. **Testability:** Mock external commands via CRY_CMD_* variables

## Implementation Phases

### Phase 1: Foundation (4 tasks, all ready)
**Focus:** Core infrastructure that all modules depend on

- [CRY_CLI-ikl] Create project directory structure ✓ Ready
- [CRY_CLI-6sp] Implement lib/cry-config.sh (blocked by CRY_CLI-ikl)
- [CRY_CLI-lcc] Implement lib/cry-logging.sh (blocked by CRY_CLI-ikl)
- [CRY_CLI-ejy] Implement module loader cry_require (blocked by config + logging)

**Success Criteria:** Directory structure created, config/logging/loader modules functional

### Phase 2: Core Modules (6 tasks)
**Focus:** Business logic extracted from monolithic script

- [CRY_CLI-be3] Implement lib/cry-ui.sh - Visual components
- [CRY_CLI-3cv] Implement lib/cry-parallel.sh - Parallelism logic
- [CRY_CLI-hyl] Implement lib/cry-scratch.sh - Scratch management
- [CRY_CLI-ib2] Implement lib/cry-stage.sh - File staging
- [CRY_CLI-a2j] Implement lib/cry-exec.sh - Calculation execution
- [CRY_CLI-wwa] Implement lib/cry-help.sh - Help system

**Dependencies:** All blocked by Phase 1 completion

**Success Criteria:** Each module independently testable, preserves original functionality

### Phase 3: Integration (2 tasks)
**Focus:** Assemble modules into new runcrystal

- [CRY_CLI-6vn] Refactor main bin/runcrystal script (blocked by all Phase 2)
- [CRY_CLI-5nx] Move runcrystal to bin/ (blocked by CRY_CLI-6vn)

**Success Criteria:** Main script <100 lines, zero functionality regression

### Phase 4: Testing (7 tasks)
**Focus:** Ensure quality and prevent regressions

- [CRY_CLI-7jf] Set up testing framework (bats) ✓ Ready
- [CRY_CLI-nim] Write unit tests for cry-config ✓ Ready
- [CRY_CLI-pq3] Write unit tests for cry-ui ✓ Ready
- [CRY_CLI-rzw] Write unit tests for cry-parallel ✓ Ready
- [CRY_CLI-pc3] Write unit tests for cry-scratch ✓ Ready
- [CRY_CLI-dmt] Write unit tests for cry-stage ✓ Ready
- [CRY_CLI-z00] Write integration tests ✓ Ready

**Success Criteria:** >80% test coverage, all tests pass

### Phase 5: Documentation (4 tasks)
**Focus:** Enable maintainability

- [CRY_CLI-22s] Add shellcheck to CI ✓ Ready
- [CRY_CLI-7e1] Write module documentation (blocked by modules)
- [CRY_CLI-6o9] Update CLAUDE.md ✓ Ready
- [CRY_CLI-ps0] Create CONTRIBUTING.md ✓ Ready

**Success Criteria:** All code documented, shellcheck passes

## Immediate Next Steps

**You can start work on these tasks right now:**

1. **CRY_CLI-ikl** - Create project directory structure (highest priority, unblocks Phase 1)
2. **CRY_CLI-oxy** - Epic (coordinate overall effort)

**Test-focused work (can be done in parallel):**

3. **CRY_CLI-7jf** - Set up testing framework
4. **CRY_CLI-nim through CRY_CLI-z00** - Write tests (requires modules to exist, but framework can be set up now)

**Documentation work:**

5. **CRY_CLI-22s** - Add shellcheck to CI
6. **CRY_CLI-6o9** - Update CLAUDE.md
7. **CRY_CLI-ps0** - Create CONTRIBUTING.md

## Dependency Highlights

**Critical Path:**
```
Directory Structure (ikl) →
  Config (6sp) →
    Loader (ejy) →
      UI (be3) →
        All Core Modules (3cv, hyl, ib2, a2j, wwa) →
          Main Script Refactor (6vn) →
            Move to bin/ (5nx) →
              Integration Tests (z00)
```

**Parallel Tracks:**
- Testing framework and unit tests can be developed alongside module creation
- Documentation can proceed in parallel with implementation

## Risk Mitigation

### Anti-Patterns Fixed

1. **Global variable soup** → CRY_JOB associative array
2. **Stateful directory changes** → Explicit dir arguments to functions
3. **Missing cleanup guarantee** → trap-based cleanup in main script
4. **Error propagation unclear** → Modules return codes, main decides

### Testing Strategy

- **Unit tests:** Each module tested in isolation with mocks
- **Integration tests:** Full workflow with fake CRYSTAL23 binaries
- **Regression prevention:** Preserve all original functionality

## Usage

```bash
# Check what's ready to work on
bd ready

# Show details of a task
bd show CRY_CLI-ikl

# Start working on a task
bd update CRY_CLI-ikl --status in_progress

# Complete a task
bd close CRY_CLI-ikl --reason "Directory structure created"

# See project statistics
bd stats

# View dependency tree
bd dep tree CRY_CLI-oxy
```

## Success Metrics

- [ ] All modules created and independently testable
- [ ] Main runcrystal script <100 lines
- [ ] Zero functionality regression (all original features work)
- [ ] Test coverage >80%
- [ ] All shellcheck warnings resolved
- [ ] Documentation complete (module docs + CONTRIBUTING.md)
- [ ] cry-docs can reuse UI components (validates abstraction)

## Notes for Future Sessions

This refactoring uses beads (bd) for persistent task tracking across sessions. The dependency graph ensures work happens in the correct order. When resuming work:

1. Run `bd ready` to see available tasks
2. Run `bd blocked` to understand what's waiting
3. Run `bd stats` for overall project health
4. Check this REFACTORING_PLAN.md for context

All task details, design notes, and acceptance criteria are stored in the .beads database.
