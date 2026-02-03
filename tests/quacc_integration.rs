//! Integration tests for quacc RPC handlers.
//!
//! These tests verify the Rust TUI can communicate with Python
//! quacc handlers via IPC. Tests run against a real server instance.
//!
//! # Requirements
//!
//! These tests require the crystalmath Python package to be installed:
//! ```bash
//! uv pip install -e python/
//! ```
//!
//! # Running
//!
//! ```bash
//! cargo test --test quacc_integration -- --test-threads=1 --nocapture
//! ```
//!
//! # Behavior
//!
//! Tests will pass regardless of whether quacc is installed:
//! - If quacc is installed: recipes list will contain VASP recipes
//! - If quacc is not installed: recipes list will be empty with an error message
//!
//! This ensures the integration tests verify the RPC flow works even when
//! the optional quacc dependency is missing.

use std::path::PathBuf;
use std::time::Duration;

use serde_json::json;
use tokio::time::timeout;

use crystalmath_tui::ipc::{ensure_server_running, IpcClient};
use crystalmath_tui::models::{ClustersListResponse, QuaccJobsListResponse, RecipesListResponse};

/// Generate a unique socket path for this test to avoid conflicts.
fn test_socket_path(test_name: &str) -> PathBuf {
    let pid = std::process::id();
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    PathBuf::from(format!(
        "/tmp/crystalmath-quacc-test-{}-{}-{}.sock",
        test_name, pid, timestamp
    ))
}

/// Clean up socket file after test.
fn cleanup_socket(path: &PathBuf) {
    let _ = std::fs::remove_file(path);
}

/// Check if IPC tests should be skipped (e.g., in CI without Python).
fn should_skip_ipc_tests() -> bool {
    std::env::var("CRYSTALMATH_SKIP_IPC_TESTS").is_ok()
}

/// Check if crystalmath-server is available (PATH or venv).
fn server_available() -> bool {
    // First check PATH
    if std::process::Command::new("which")
        .arg("crystalmath-server")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
    {
        return true;
    }

    // Also check the local venv
    let venv_server =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(".venv/bin/crystalmath-server");
    if venv_server.exists() {
        // Add venv to PATH for this process
        if let Ok(path) = std::env::var("PATH") {
            let venv_bin = venv_server.parent().unwrap();
            std::env::set_var("PATH", format!("{}:{}", venv_bin.display(), path));
        }
        return true;
    }

    false
}

/// Test: recipes.list returns valid response structure.
///
/// Verifies that:
/// - Server can handle recipes.list RPC call
/// - Response deserializes to RecipesListResponse
/// - Structure is valid regardless of quacc installation status
#[tokio::test]
async fn test_recipes_list_returns_valid_response() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("recipes_list");

    let result = async {
        ensure_server_running(&socket_path).expect("Server should start");
        let mut client = IpcClient::connect_with_retry(&socket_path, 5)
            .await
            .expect("Should connect to server");

        let response = client.call("recipes.list", json!({})).await?;
        let parsed: RecipesListResponse = serde_json::from_value(response)?;

        // Should have a valid structure regardless of quacc installation
        // Either we have recipes OR we have an error OR both are empty/none
        println!(
            "recipes.list response: {} recipes, version={:?}, error={:?}",
            parsed.recipes.len(),
            parsed.quacc_version,
            parsed.error
        );

        // If quacc is installed, we should have some recipes
        if parsed.quacc_version.is_some() && parsed.error.is_none() {
            assert!(
                !parsed.recipes.is_empty(),
                "quacc installed but no recipes found"
            );
            // Verify recipe structure
            let recipe = &parsed.recipes[0];
            assert!(!recipe.name.is_empty(), "Recipe name should not be empty");
            assert!(
                recipe.fullname.contains("quacc"),
                "Recipe fullname should contain 'quacc'"
            );
            assert!(
                recipe.recipe_type == "job" || recipe.recipe_type == "flow",
                "Recipe type should be 'job' or 'flow', got: {}",
                recipe.recipe_type
            );
        }

        Ok::<_, anyhow::Error>(())
    }
    .await;

    cleanup_socket(&socket_path);
    result.expect("Test failed");
}

/// Test: recipes.list handles gracefully when quacc is not installed.
///
/// This test verifies graceful degradation:
/// - Response should include an error message but not fail
/// - RPC call itself should succeed (it's quacc that's missing, not the handler)
#[tokio::test]
async fn test_recipes_list_handles_no_quacc() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("recipes_no_quacc");

    let result = async {
        ensure_server_running(&socket_path).expect("Server should start");
        let mut client = IpcClient::connect_with_retry(&socket_path, 5)
            .await
            .expect("Should connect to server");

        let response = client.call("recipes.list", json!({})).await?;
        let parsed: RecipesListResponse = serde_json::from_value(response)?;

        // Either we have recipes (quacc installed) or we have an error (not installed)
        // Either way, the RPC call should succeed
        if parsed.quacc_version.is_none() {
            println!(
                "quacc not installed - error: {:?}, recipes: {}",
                parsed.error,
                parsed.recipes.len()
            );
            // When quacc is not installed, we expect:
            // - error message explaining why, OR
            // - empty recipes list
            assert!(
                parsed.error.is_some() || parsed.recipes.is_empty(),
                "Expected error or empty recipes when quacc not installed"
            );
        } else {
            println!(
                "quacc installed - version: {:?}, recipes: {}",
                parsed.quacc_version,
                parsed.recipes.len()
            );
        }

        Ok::<_, anyhow::Error>(())
    }
    .await;

    cleanup_socket(&socket_path);
    result.expect("Test failed");
}

/// Test: clusters.list returns valid response structure.
///
/// Verifies that:
/// - Server can handle clusters.list RPC call
/// - Response deserializes to ClustersListResponse
/// - workflow_engine field is present
#[tokio::test]
async fn test_clusters_list_returns_valid_response() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("clusters_list");

    let result = async {
        ensure_server_running(&socket_path).expect("Server should start");
        let mut client = IpcClient::connect_with_retry(&socket_path, 5)
            .await
            .expect("Should connect to server");

        let response = client.call("clusters.list", json!({})).await?;
        let parsed: ClustersListResponse = serde_json::from_value(response)?;

        // Should always have workflow_engine status
        println!(
            "clusters.list response: {} clusters, quacc_installed={}, engine={:?}",
            parsed.clusters.len(),
            parsed.workflow_engine.quacc_installed,
            parsed.workflow_engine.configured
        );

        // Verify structure - even without quacc, the structure should be valid
        // configured may be None, installed may be empty, quacc_installed may be false
        // All are valid states

        Ok::<_, anyhow::Error>(())
    }
    .await;

    cleanup_socket(&socket_path);
    result.expect("Test failed");
}

/// Test: jobs.list returns empty list initially.
///
/// Verifies that:
/// - Server can handle jobs.list RPC call
/// - Response deserializes to QuaccJobsListResponse
/// - Initially empty (no jobs submitted yet)
#[tokio::test]
async fn test_jobs_list_returns_empty_initially() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("jobs_list");

    let result = async {
        ensure_server_running(&socket_path).expect("Server should start");
        let mut client = IpcClient::connect_with_retry(&socket_path, 5)
            .await
            .expect("Should connect to server");

        let response = client.call("jobs.list", json!({})).await?;
        let parsed: QuaccJobsListResponse = serde_json::from_value(response)?;

        println!(
            "jobs.list response: {} jobs, total={}",
            parsed.jobs.len(),
            parsed.total
        );

        // Initially should be empty (no jobs submitted yet)
        assert_eq!(parsed.total, 0, "Expected 0 total jobs initially");
        assert!(parsed.jobs.is_empty(), "Expected empty jobs list initially");

        Ok::<_, anyhow::Error>(())
    }
    .await;

    cleanup_socket(&socket_path);
    result.expect("Test failed");
}

/// Test: jobs.list with status filter parameter.
///
/// Verifies that:
/// - Server accepts status filter parameter
/// - Response is valid (may be empty)
#[tokio::test]
async fn test_jobs_list_with_status_filter() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("jobs_list_filter");

    let result = async {
        ensure_server_running(&socket_path).expect("Server should start");
        let mut client = IpcClient::connect_with_retry(&socket_path, 5)
            .await
            .expect("Should connect to server");

        // Filter by status - should not error even with no jobs
        let response = client
            .call("jobs.list", json!({"status": "running"}))
            .await?;
        let parsed: QuaccJobsListResponse = serde_json::from_value(response)?;

        println!(
            "jobs.list(status=running) response: {} jobs",
            parsed.jobs.len()
        );

        // Should return empty list (no running jobs)
        assert_eq!(parsed.total, 0, "Expected 0 running jobs");

        Ok::<_, anyhow::Error>(())
    }
    .await;

    cleanup_socket(&socket_path);
    result.expect("Test failed");
}

/// Test: jobs.list with limit parameter.
///
/// Verifies that:
/// - Server accepts limit parameter
/// - Response respects the limit
#[tokio::test]
async fn test_jobs_list_with_limit() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("jobs_list_limit");

    let result = async {
        ensure_server_running(&socket_path).expect("Server should start");
        let mut client = IpcClient::connect_with_retry(&socket_path, 5)
            .await
            .expect("Should connect to server");

        let response = client.call("jobs.list", json!({"limit": 10})).await?;
        let parsed: QuaccJobsListResponse = serde_json::from_value(response)?;

        println!(
            "jobs.list(limit=10) response: {} jobs, total={}",
            parsed.jobs.len(),
            parsed.total
        );

        // Limit should be respected (though with 0 jobs, this is trivially true)
        assert!(parsed.jobs.len() <= 10, "Jobs list should respect limit");

        Ok::<_, anyhow::Error>(())
    }
    .await;

    cleanup_socket(&socket_path);
    result.expect("Test failed");
}

/// Test: All quacc handlers are registered and callable.
///
/// Verifies that:
/// - All expected handlers exist and are callable
/// - Each returns valid JSON object
/// - No timeouts or protocol errors
#[tokio::test]
async fn test_all_quacc_handlers_registered() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("all_handlers");

    let result = async {
        ensure_server_running(&socket_path).expect("Server should start");
        let mut client = IpcClient::connect_with_retry(&socket_path, 5)
            .await
            .expect("Should connect to server");

        // Verify each handler exists and returns valid JSON
        let handlers = vec![
            ("recipes.list", json!({})),
            ("clusters.list", json!({})),
            ("jobs.list", json!({})),
        ];

        for (method, params) in handlers {
            println!("Testing handler: {}", method);
            let response = timeout(Duration::from_secs(5), client.call(method, params.clone()))
                .await
                .unwrap_or_else(|_| panic!("{} timed out", method))
                .unwrap_or_else(|e| panic!("{} failed: {}", method, e));

            // Should be valid JSON object
            assert!(
                response.is_object(),
                "{} did not return object, got: {:?}",
                method,
                response
            );
            println!("  {} returned valid object", method);
        }

        Ok::<_, anyhow::Error>(())
    }
    .await;

    cleanup_socket(&socket_path);
    result.expect("Test failed");
}
