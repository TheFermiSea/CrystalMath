# ADR-002: Rust TUI Secondary/Experimental Policy

**Status:** Accepted
**Date:** 2026-01-06
**Deciders:** Project maintainers
**Supersedes:** None
**Depends on:** ADR-001 (Python Textual as Primary TUI)

## Context

Per ADR-001, the Rust/Ratatui TUI is designated as secondary/experimental. This ADR establishes concrete policies for its maintenance, feature scope, and integration boundaries to provide clarity for developers and users.

The Rust TUI currently couples with Python via PyO3, which creates version fragility and high maintenance overhead. Until a stable IPC boundary is established, the Rust TUI's scope must be constrained to prevent further entanglement.

## Decision

### 1. Feature Scope (What Rust TUI Does)

The Rust TUI is explicitly limited to:

- **Monitoring**: Real-time job status, queue visualization, log streaming
- **Diagnostics**: Performance metrics, system health, connection status
- **Read-only operations**: Viewing jobs, results, cluster configurations

The Rust TUI **does not** handle:

- Job creation or configuration
- Template management
- Workflow orchestration
- Database mutations (other than UI state)
- User onboarding or setup wizards

### 2. Feature Freeze Rules

**Freeze conditions (until IPC boundary is defined):**

- No new screens or major UI components
- No new PyO3 bindings or Python API extensions
- No new dependencies in Cargo.toml (except security patches)
- No expansion of `bridge.rs` FFI surface

**Permitted changes:**

- Bug fixes for existing functionality
- Security patches and dependency updates
- Documentation updates
- Performance optimizations that don't expand scope
- Refactoring to prepare for IPC migration

### 3. Integration Boundary

**Current state (PyO3):** Rust embeds Python via PyO3 and calls `crystalmath.api` directly. This is fragile due to Python version coupling.

**Target state (IPC):** Rust communicates with a Python backend service over:

- Unix domain sockets (preferred for local)
- HTTP/JSON-RPC for remote scenarios
- Defined message schema with versioning

**Migration rule:** New Rust↔Python communication **must** use the IPC boundary. Existing PyO3 usage is frozen but not removed until full migration.

### 4. Maintenance Guarantees

| Aspect | Guarantee |
|--------|-----------|
| Build script | `scripts/build-tui.sh` will be maintained |
| Compilation | Must compile with stable Rust |
| Existing tests | ~103 tests must pass |
| Security patches | Applied within 7 days of disclosure |
| Breaking changes | Announced 30 days in advance |

**No guarantee of:**

- Feature parity with Python TUI
- Specific UX polish or accessibility features
- Support for new DFT codes (VASP, QE, etc.) without IPC

### 5. Promotion/Demotion Criteria

**Criteria to promote Rust TUI to co-primary:**

1. Stable IPC boundary implemented and documented
2. Feature parity for monitoring use cases
3. Independent release cycle (no Python version coupling)
4. Active maintainer commitment (>1 contributor)

**Criteria to deprecate Rust TUI:**

1. No active development for 6 months
2. IPC boundary not established within 12 months
3. Maintenance burden exceeds project capacity
4. Security vulnerabilities cannot be addressed

## Consequences

### Positive

- Clear expectations for contributors and users
- Prevents scope creep in Rust TUI
- Focuses resources on Python TUI as primary
- Provides path to promotion if IPC succeeds

### Negative / Tradeoffs

- Rust TUI users may be disappointed by limited features
- Some performance-focused users may prefer Rust
- Dual-UI maintenance overhead continues (but is bounded)

## Implementation Checklist

- [ ] Update CLAUDE.md with Rust TUI constraints
- [ ] Update README.md to clarify primary vs secondary
- [ ] Add deprecation warning to Rust TUI startup if appropriate
- [ ] Create crystalmath-as6l.11 for IPC boundary design

## Related Issues

- crystalmath-as6l.11: Define IPC boundary for Rust TUI — see [ADR-003](adr-003-ipc-boundary-design.md)
- crystalmath-as6l.18: Freeze Rust TUI feature work until IPC is defined
