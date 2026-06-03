//! End-to-end test for the IPC-backed `BridgeService` (`IpcBridgeHandle`).
//!
//! Exercises the full PyO3->IPC cutover path (ADR-006):
//! `IpcBridgeHandle` -> worker thread -> `IpcClient::connect_or_start` (which
//! auto-spawns the real `crystalmath-server`) -> `call_rpc` over the socket ->
//! `route_rpc_response` -> typed `BridgeResponse`.
//!
//! Self-skips when `crystalmath-server` is unavailable or
//! `CRYSTALMATH_SKIP_IPC_TESTS` is set (mirrors tests/ipc_integration.rs).

use std::path::PathBuf;
use std::time::{Duration, Instant};

use crystalmath_tui::bridge::{BridgeResponse, BridgeService};
use crystalmath_tui::bridge_ipc::IpcBridgeHandle;

fn should_skip() -> bool {
    std::env::var("CRYSTALMATH_SKIP_IPC_TESTS").is_ok()
}

/// Ensure the venv's `crystalmath-server` is reachable (adds it to PATH so the
/// client's `find_server_binary` / auto-spawn can locate it).
fn server_available() -> bool {
    let venv_server =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(".venv/bin/crystalmath-server");
    if venv_server.exists() {
        if let Ok(path) = std::env::var("PATH") {
            let venv_bin = venv_server.parent().unwrap();
            std::env::set_var("PATH", format!("{}:{}", venv_bin.display(), path));
        }
        return true;
    }
    std::process::Command::new("which")
        .arg("crystalmath-server")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn unique_socket(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "crystalmath-bridge-test-{}-{}.sock",
        name,
        std::process::id()
    ))
}

/// Block until a response arrives or the deadline passes.
fn wait_for_response(bridge: &IpcBridgeHandle, timeout: Duration) -> Option<BridgeResponse> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Some(resp) = bridge.poll_response() {
            return Some(resp);
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    None
}

/// The keystone test: a fetch_jobs request routed entirely over IPC produces a
/// typed `BridgeResponse::Jobs` with the echoed request_id and an Ok result.
#[test]
fn test_ipc_bridge_fetch_jobs_roundtrip() {
    if should_skip() {
        eprintln!("skip: CRYSTALMATH_SKIP_IPC_TESTS set");
        return;
    }
    if !server_available() {
        eprintln!("skip: crystalmath-server not available");
        return;
    }

    let socket = unique_socket("fetch_jobs");
    let _ = std::fs::remove_file(&socket);

    let bridge = IpcBridgeHandle::spawn(socket.clone()).expect("spawn IpcBridgeHandle");

    // The worker lazily connects (and auto-spawns the server) on this first request.
    bridge
        .request_fetch_jobs(0)
        .expect("request_fetch_jobs should enqueue");

    let resp = wait_for_response(&bridge, Duration::from_secs(20))
        .expect("expected a BridgeResponse within 20s (server spawn + fetch)");

    match resp {
        BridgeResponse::Jobs { request_id, result } => {
            assert_eq!(request_id, 0, "request_id should be echoed back unchanged");
            let jobs = result.expect("fetch_jobs should succeed against the live server");
            eprintln!("IPC bridge fetched {} job(s) over the socket", jobs.len());
        }
        _ => panic!("expected BridgeResponse::Jobs from a fetch_jobs request"),
    }

    drop(bridge);
    let _ = std::fs::remove_file(&socket);
}

/// A second request on the same handle reuses the connection (proves the worker
/// keeps one client alive across requests).
#[test]
fn test_ipc_bridge_sequential_requests() {
    if should_skip() {
        eprintln!("skip: CRYSTALMATH_SKIP_IPC_TESTS set");
        return;
    }
    if !server_available() {
        eprintln!("skip: crystalmath-server not available");
        return;
    }

    let socket = unique_socket("sequential");
    let _ = std::fs::remove_file(&socket);
    let bridge = IpcBridgeHandle::spawn(socket.clone()).expect("spawn IpcBridgeHandle");

    for id in 0..3usize {
        bridge.request_fetch_jobs(id).expect("enqueue fetch_jobs");
        let resp = wait_for_response(&bridge, Duration::from_secs(20))
            .unwrap_or_else(|| panic!("no response for request {id}"));
        match resp {
            BridgeResponse::Jobs { request_id, result } => {
                assert_eq!(request_id, id);
                assert!(result.is_ok(), "fetch_jobs {id} should succeed");
            }
            _ => panic!("expected BridgeResponse::Jobs for request {id}"),
        }
    }

    drop(bridge);
    let _ = std::fs::remove_file(&socket);
}

/// Regression for Finding #2: dropping one `IpcBridgeHandle` must kill ONLY the
/// crystalmath-server it spawned (keyed by its own socket), never a server another
/// live handle started on a different socket.
///
/// Before the fix, `Drop` called the process-global `shutdown_spawned_servers()`,
/// which drained and killed EVERY spawned server. So dropping `bridge_a` here would
/// kill `bridge_b`'s server, and the subsequent request on `bridge_b` would fail.
/// This test runs both handles within a single test so it deterministically
/// reproduces the cross-handle kill without relying on cargo's parallel scheduler.
#[test]
fn test_drop_one_bridge_does_not_kill_another() {
    if should_skip() {
        eprintln!("skip: CRYSTALMATH_SKIP_IPC_TESTS set");
        return;
    }
    if !server_available() {
        eprintln!("skip: crystalmath-server not available");
        return;
    }

    let socket_a = unique_socket("isolation-a");
    let socket_b = unique_socket("isolation-b");
    let _ = std::fs::remove_file(&socket_a);
    let _ = std::fs::remove_file(&socket_b);

    let bridge_a = IpcBridgeHandle::spawn(socket_a.clone()).expect("spawn bridge A");
    let bridge_b = IpcBridgeHandle::spawn(socket_b.clone()).expect("spawn bridge B");

    // Drive one request on each handle so each worker spawns its OWN server bound
    // to its OWN socket (distinct entries in the spawned-server registry).
    bridge_a.request_fetch_jobs(0).expect("enqueue A");
    assert!(
        matches!(
            wait_for_response(&bridge_a, Duration::from_secs(20)),
            Some(BridgeResponse::Jobs { result: Ok(_), .. })
        ),
        "bridge A's first request should succeed against its own server"
    );

    bridge_b.request_fetch_jobs(0).expect("enqueue B");
    assert!(
        matches!(
            wait_for_response(&bridge_b, Duration::from_secs(20)),
            Some(BridgeResponse::Jobs { result: Ok(_), .. })
        ),
        "bridge B's first request should succeed against its own server"
    );

    // Drop A. This must tear down ONLY A's server, leaving B's untouched.
    drop(bridge_a);

    // B must still be able to talk to its server. If Drop killed B's server too,
    // the worker would have to (and could) auto-respawn — but the regression we are
    // guarding is that B's *running* server is not killed out from under it. Either
    // way, the request must succeed; the bug manifested as an Err result.
    bridge_b
        .request_fetch_jobs(1)
        .expect("enqueue B after dropping A");
    match wait_for_response(&bridge_b, Duration::from_secs(20)) {
        Some(BridgeResponse::Jobs { request_id, result }) => {
            assert_eq!(request_id, 1);
            result.expect("bridge B must still succeed after bridge A is dropped");
        }
        other => panic!("expected BridgeResponse::Jobs from bridge B, got {other:?}"),
    }

    drop(bridge_b);
    let _ = std::fs::remove_file(&socket_a);
    let _ = std::fs::remove_file(&socket_b);
}
