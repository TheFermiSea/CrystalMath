---
phase: 02-quacc-integration
plan: 04
type: summary
status: complete
started: 2026-02-02
completed: 2026-02-02
commits:
  - hash: pending
    message: "fix(02-04): wrap cluster deserialization in ApiResponse"
---

# 02-04 Summary: End-to-End Integration Tests

## Objective

Create integration tests for quacc RPC handlers and complete the TUI data loading loop with async IPC calls.

## Deliverables

### Task 1: Integration Tests
Created `tests/quacc_integration.rs` with 7 tests verifying end-to-end RPC flow:
- `test_recipes_list_returns_valid_response` - Verifies recipes.list RPC
- `test_recipes_list_handles_no_quacc` - Graceful quacc not installed handling
- `test_clusters_list_returns_valid_response` - Verifies clusters.list RPC
- `test_jobs_list_returns_empty_initially` - Empty job list handling
- `test_jobs_list_with_status_filter` - Status filtering
- `test_jobs_list_with_limit` - Pagination/limit
- `test_all_quacc_handlers_registered` - Handler registry verification

### Task 2: Async Data Loading
Added async recipe loading in app.rs:
- `recipe_request_id` field for tracking RPC requests
- `request_load_recipes()` method sends recipes.list via IPC
- `poll_bridge_responses()` handles recipe RPC responses
- Recipe browser opens with loading state, populated async

### Task 3: Human Verification (Bug Fix)
During human verification, user reported:
- ERROR: "Failed to deserialize clusters: invalid type: map, expected a sequence"
- Garbled UI text (due to error state)

**Root Cause:**
The `fetch_clusters` RPC (used by existing cluster_manager) returns `{"ok": true, "data": [...]}` via Python's `_ok_response()` wrapper. The Rust code at `app.rs:1197` was deserializing directly as `Vec<ClusterConfig>` without unwrapping the `ApiResponse` envelope.

**Fix Applied:**
Changed cluster deserialization from:
```rust
serde_json::from_value::<Vec<ClusterConfig>>(value)
```
To:
```rust
serde_json::from_value::<ApiResponse<Vec<ClusterConfig>>>(value)
    .and_then(|api_response| api_response.into_result())
```

This properly unwraps the `{"ok": true, "data": [...]}` envelope before extracting the cluster list.

## Files Modified

| File | Change |
|------|--------|
| `tests/quacc_integration.rs` | New integration tests (7 tests) |
| `src/app.rs:15` | Added `ApiResponse` import |
| `src/app.rs:1197-1230` | Fixed cluster deserialization with ApiResponse wrapper |

## Test Results

```
running 7 tests
test test_jobs_list_returns_empty_initially ... ok
test test_recipes_list_returns_valid_response ... ok
test test_jobs_list_with_limit ... ok
test test_jobs_list_with_status_filter ... ok
test test_clusters_list_returns_valid_response ... ok
test test_recipes_list_handles_no_quacc ... ok
test test_all_quacc_handlers_registered ... ok

test result: ok. 7 passed; 0 failed; 0 ignored
```

## Decisions

| Decision | Rationale |
|----------|-----------|
| Use ApiResponse wrapper for fetch_clusters | Consistency with Python API envelope pattern |
| Keep recipes.list direct deserialization | recipes.list uses different response structure (not wrapped) |
| Separate error handling for API vs parse errors | Better debugging - distinguishes backend errors from deserialization issues |

## Key Learnings

1. **Two dispatch systems**: `api.py.dispatch()` (PyO3 bridge) vs `server/` JsonRpcServer (IPC socket) use different response formats
2. **ApiResponse envelope**: Methods in api.py's `_rpc_registry` return `{"ok": true, "data": ...}` wrapped responses
3. **Handler registry methods**: New handlers in `server/handlers/` return direct structures (no wrapper)

## Phase 2 Completion

With this plan complete, Phase 2 (quacc Integration) is finished:
- ✅ 02-01: Python quacc module (discovery, engines, config, store)
- ✅ 02-02: RPC handlers (recipes.list, clusters.list, jobs.list)
- ✅ 02-03: Rust models and recipe browser UI
- ✅ 02-04: Integration tests and bug fixes
