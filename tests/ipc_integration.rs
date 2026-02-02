//! Integration tests for IPC client-server communication.
//!
//! These tests verify the full IPC stack: Rust client communicating with
//! Python crystalmath-server over Unix domain sockets using JSON-RPC 2.0.
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
//! cargo test --test ipc_integration -- --nocapture
//! ```
//!
//! # CI Configuration
//!
//! Tests can be skipped in CI environments without Python by setting
//! `CRYSTALMATH_SKIP_IPC_TESTS=1`.

use std::path::PathBuf;
use std::time::Duration;

use crystalmath_tui::ipc::{default_socket_path, ensure_server_running, IpcClient};

/// Generate a unique socket path for this test to avoid conflicts.
fn test_socket_path(test_name: &str) -> PathBuf {
    let pid = std::process::id();
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    PathBuf::from(format!(
        "/tmp/crystalmath-test-{}-{}-{}.sock",
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
    let venv_server = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(".venv/bin/crystalmath-server");
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

/// Test: Basic ping roundtrip with latency measurement.
///
/// Verifies that:
/// - Server can be started via ensure_server_running()
/// - Client can connect to the server
/// - ping() returns a valid response with pong=true
/// - Roundtrip latency is under 100ms for local IPC
#[tokio::test]
async fn test_ping_roundtrip() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("ping_roundtrip");

    // Start server
    ensure_server_running(&socket_path).expect("Server should start");

    // Connect
    let mut client = IpcClient::connect(&socket_path)
        .await
        .expect("Should connect to server");

    // Ping
    let latency = client.ping().await.expect("Ping should succeed");
    println!("Ping latency: {:?}", latency);

    // Verify latency is reasonable (< 100ms for local IPC)
    assert!(
        latency < Duration::from_millis(100),
        "Ping too slow: {:?}",
        latency
    );

    cleanup_socket(&socket_path);
}

/// Test: Verify ping latency meets < 10ms target (success criteria).
///
/// Per ADR-003, IPC roundtrip should average under 10ms for simple
/// requests like system.ping.
#[tokio::test]
async fn test_ping_latency_under_10ms() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("ping_latency");

    ensure_server_running(&socket_path).expect("Server should start");

    let mut client = IpcClient::connect(&socket_path)
        .await
        .expect("Should connect");

    // Warm up: first ping may include connection setup costs
    let _ = client.ping().await;

    // Measure multiple pings for statistical significance
    let mut total = Duration::ZERO;
    let iterations = 10;

    for i in 0..iterations {
        let latency = client.ping().await.expect("Ping should succeed");
        println!("Ping {}: {:?}", i + 1, latency);
        total += latency;
    }

    let avg = total / iterations;
    println!("Average ping latency: {:?}", avg);

    // Success criteria: average < 10ms
    assert!(
        avg < Duration::from_millis(10),
        "Average latency {:?} exceeds 10ms target",
        avg
    );

    cleanup_socket(&socket_path);
}

/// Test: connect_or_start() auto-starts server if not running.
///
/// Verifies the zero-config experience:
/// - Server is not running initially
/// - connect_or_start() spawns it automatically
/// - Connection succeeds and ping works
#[tokio::test]
async fn test_connect_or_start() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("connect_or_start");

    // Ensure server is not running (clean slate)
    let _ = std::fs::remove_file(&socket_path);
    assert!(!socket_path.exists(), "Socket should not exist initially");

    // connect_or_start should auto-start the server
    let mut client = IpcClient::connect_or_start(&socket_path)
        .await
        .expect("connect_or_start should succeed");

    // Verify working via ping
    let latency = client.ping().await.expect("Ping should work");
    assert!(latency < Duration::from_secs(1), "Latency too high");

    cleanup_socket(&socket_path);
}

/// Test: Stale socket cleanup and recovery.
///
/// When a server crashes without cleanup, the socket file remains but
/// connections are refused. ensure_server_running() should detect this
/// and start a fresh server.
///
/// Note: This test creates a real Unix socket that refuses connections,
/// simulating a crashed server scenario.
#[tokio::test]
async fn test_stale_socket_cleanup() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("stale_socket");

    // Create a real Unix socket that doesn't accept connections
    // (simulates a server that crashed after binding but before accepting)
    {
        use std::os::unix::net::UnixListener;
        let listener = UnixListener::bind(&socket_path).expect("Create stale socket");
        // Don't accept - just drop the listener without cleanup
        drop(listener);
        // The socket file remains but connection will be refused
    }

    assert!(socket_path.exists(), "Stale socket should exist");

    // Verify connection is refused (simulating crashed server)
    let refused = std::os::unix::net::UnixStream::connect(&socket_path);
    assert!(
        refused.is_err(),
        "Connection should be refused to stale socket"
    );
    println!(
        "Stale socket connection error (expected): {:?}",
        refused.err()
    );

    // ensure_server_running should detect stale and start fresh
    ensure_server_running(&socket_path).expect("Should handle stale socket");

    // Should be able to connect now
    let client = IpcClient::connect(&socket_path).await;
    assert!(
        client.is_ok(),
        "Should connect after stale cleanup: {:?}",
        client.err()
    );

    cleanup_socket(&socket_path);
}

/// Test: Connection timeout behavior.
///
/// Verifies that attempting to connect to a non-existent socket
/// fails appropriately rather than hanging forever.
#[tokio::test]
async fn test_connect_to_nonexistent_socket() {
    // This test doesn't require the server to be installed
    let socket_path = PathBuf::from("/tmp/nonexistent-crystalmath-test-12345.sock");

    // Ensure it doesn't exist
    let _ = std::fs::remove_file(&socket_path);

    // Connection should fail (not hang)
    let result = tokio::time::timeout(
        Duration::from_secs(2),
        IpcClient::connect(&socket_path),
    )
    .await;

    match result {
        Ok(Ok(_)) => panic!("Should not connect to nonexistent socket"),
        Ok(Err(e)) => {
            println!("Expected error: {:?}", e);
            // Should be a connection error, not a timeout
        }
        Err(_) => panic!("Should not timeout - connection should fail fast"),
    }
}

/// Test: Verify default socket path resolution.
///
/// Not a full integration test, but verifies the socket path
/// follows expected patterns.
#[test]
fn test_default_socket_path_format() {
    let path = default_socket_path();
    println!("Default socket path: {:?}", path);

    // Should be absolute or in /tmp
    assert!(
        path.is_absolute() || path.starts_with("/tmp"),
        "Socket path should be absolute: {:?}",
        path
    );

    // Should have the expected filename
    let filename = path.file_name().unwrap().to_str().unwrap();
    assert!(
        filename.contains("crystalmath"),
        "Filename should contain 'crystalmath': {}",
        filename
    );
}

/// Test: Multiple sequential calls work correctly.
///
/// Verifies that the IPC connection handles multiple requests
/// without state corruption.
#[tokio::test]
async fn test_multiple_sequential_calls() {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test (CRYSTALMATH_SKIP_IPC_TESTS set)");
        return;
    }
    if !server_available() {
        println!("Skipping IPC test (crystalmath-server not in PATH)");
        return;
    }

    let socket_path = test_socket_path("sequential_calls");

    ensure_server_running(&socket_path).expect("Server should start");

    let mut client = IpcClient::connect(&socket_path)
        .await
        .expect("Should connect");

    // Multiple pings in sequence
    for i in 0..5 {
        let latency = client.ping().await;
        assert!(latency.is_ok(), "Ping {} should succeed: {:?}", i, latency.err());
    }

    cleanup_socket(&socket_path);
}
