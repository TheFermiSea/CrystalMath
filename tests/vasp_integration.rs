//! Integration tests for VASP generation RPC handlers.
//!
//! These tests verify the Rust TUI can communicate with Python
//! VASP generation handlers via IPC.
//!
//! # Requirements
//!
//! These tests require:
//! - crystalmath Python package installed
//! - pymatgen installed for full functionality
//!
//! ```bash
//! uv pip install -e python/
//! uv pip install pymatgen
//! ```
//!
//! # Running
//!
//! ```bash
//! cargo test --test vasp_integration -- --test-threads=1 --nocapture
//! ```
//!
//! # Behavior
//!
//! Tests will verify error handling when pymatgen is not installed.
//! Full VASP generation requires pymatgen.

use std::path::PathBuf;
use std::time::Duration;

use serde_json::json;
use tokio::time::timeout;

use crystalmath_tui::ipc::{ensure_server_running, IpcClient};

/// Generate a unique socket path for this test to avoid conflicts.
fn test_socket_path(test_name: &str) -> PathBuf {
    let pid = std::process::id();
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    PathBuf::from(format!(
        "/tmp/crystalmath-vasp-test-{}-{}-{}.sock",
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
    // Check if in venv (look for .venv/bin/crystalmath-server)
    let venv_server = std::path::Path::new(".venv/bin/crystalmath-server");
    if venv_server.exists() {
        return true;
    }

    // Check PATH
    std::process::Command::new("crystalmath-server")
        .arg("--help")
        .output()
        .is_ok()
}

/// Setup for IPC tests: start server and create client.
async fn setup_ipc(test_name: &str) -> Option<(IpcClient, PathBuf)> {
    if should_skip_ipc_tests() {
        println!("Skipping IPC test: CRYSTALMATH_SKIP_IPC_TESTS is set");
        return None;
    }

    if !server_available() {
        println!("Skipping IPC test: crystalmath-server not available");
        println!("Install with: uv pip install -e python/");
        return None;
    }

    let socket_path = test_socket_path(test_name);

    // Start server with longer timeout
    let server_timeout = Duration::from_secs(10);
    match timeout(
        server_timeout,
        tokio::task::spawn_blocking({
            let socket_path = socket_path.clone();
            move || ensure_server_running(&socket_path)
        }),
    )
    .await
    {
        Ok(Ok(Ok(()))) => {}
        Ok(Ok(Err(e))) => {
            println!("Skipping IPC test: Failed to start server: {}", e);
            cleanup_socket(&socket_path);
            return None;
        }
        Ok(Err(e)) => {
            println!("Skipping IPC test: Join error: {}", e);
            cleanup_socket(&socket_path);
            return None;
        }
        Err(_) => {
            println!("Skipping IPC test: Server startup timed out");
            cleanup_socket(&socket_path);
            return None;
        }
    }

    // Connect client
    let client = match IpcClient::connect(&socket_path).await {
        Ok(c) => c,
        Err(e) => {
            println!("Skipping IPC test: Failed to connect: {}", e);
            cleanup_socket(&socket_path);
            return None;
        }
    };

    Some((client, socket_path))
}

/// Test that vasp.generate_from_mp returns a proper response or error.
#[tokio::test]
async fn test_vasp_generate_from_mp_returns_response() {
    let Some((mut client, socket_path)) = setup_ipc("vasp_generate").await else {
        return;
    };

    let params = json!({
        "mp_id": "mp-149",  // Silicon
        "config_json": r#"{"preset": "static", "kppra": 1000}"#
    });

    let result = client.call("vasp.generate_from_mp", params).await;

    cleanup_socket(&socket_path);

    // Should return a response (either success or error about missing pymatgen)
    let api_response = result.expect("Should get response from server");

    // Either success with VASP inputs or error about missing dependency
    if api_response["ok"] == true {
        // Success - check for VASP inputs
        assert!(api_response["data"]["poscar"].is_string());
        assert!(api_response["data"]["incar"].is_string());
        assert!(api_response["data"]["kpoints"].is_string());
        println!("VASP generation succeeded (pymatgen available)");
    } else {
        // Error - should mention pymatgen
        let error_msg = api_response["error"]["message"]
            .as_str()
            .unwrap_or_default();
        assert!(
            error_msg.contains("pymatgen") || error_msg.contains("structure"),
            "Error should mention pymatgen: {}",
            error_msg
        );
        println!("VASP generation returned expected error (pymatgen not available)");
    }
}

/// Test that structures.preview returns a proper response or error.
#[tokio::test]
async fn test_structure_preview_returns_response() {
    let Some((mut client, socket_path)) = setup_ipc("structure_preview").await else {
        return;
    };

    let params = json!({
        "source_type": "mp_id",
        "source_data": "mp-149"
    });

    let result = client.call("structures.preview", params).await;

    cleanup_socket(&socket_path);

    let api_response = result.expect("Should get response from server");

    if api_response["ok"] == true {
        // Success - check for preview fields
        assert!(api_response["data"]["formula"].is_string());
        assert!(api_response["data"]["num_sites"].is_number());
        println!("Structure preview succeeded");
    } else {
        // Error expected without pymatgen/MP API key
        println!(
            "Structure preview returned error (expected): {}",
            api_response["error"]["message"]
        );
    }
}

/// Test that structures.import_poscar parses POSCAR correctly.
#[tokio::test]
async fn test_import_poscar_parses_structure() {
    let Some((mut client, socket_path)) = setup_ipc("import_poscar").await else {
        return;
    };

    // Simple Si POSCAR
    let poscar_content = r#"Si
1.0
5.43 0.0 0.0
0.0 5.43 0.0
0.0 0.0 5.43
Si
2
Direct
0.0 0.0 0.0
0.25 0.25 0.25
"#;

    let params = json!({
        "poscar_content": poscar_content
    });

    let result = client.call("structures.import_poscar", params).await;

    cleanup_socket(&socket_path);

    let api_response = result.expect("Should get response from server");

    if api_response["ok"] == true {
        // Success - check parsed structure
        let data = &api_response["data"];
        assert!(data["formula"].as_str().unwrap().contains("Si"));
        assert_eq!(data["num_sites"], 2);
        println!("POSCAR import succeeded");
    } else {
        // Error expected without pymatgen
        let error_msg = api_response["error"]["message"]
            .as_str()
            .unwrap_or_default();
        assert!(
            error_msg.contains("pymatgen"),
            "Error should mention pymatgen: {}",
            error_msg
        );
        println!("POSCAR import returned expected error (pymatgen not available)");
    }
}

/// Test VaspPreset cycling.
#[test]
fn test_vasp_preset_cycling() {
    use crystalmath_tui::models::VaspPreset;

    let preset = VaspPreset::Relax;
    assert_eq!(preset.next(), VaspPreset::Static);
    assert_eq!(VaspPreset::Static.next(), VaspPreset::Bands);
    assert_eq!(VaspPreset::Bands.next(), VaspPreset::Dos);
    assert_eq!(VaspPreset::Dos.next(), VaspPreset::Convergence);
    assert_eq!(VaspPreset::Convergence.next(), VaspPreset::Relax);
}

/// Test VaspGenerationConfig defaults.
#[test]
fn test_vasp_config_defaults() {
    use crystalmath_tui::models::{VaspGenerationConfig, VaspPreset};

    let config = VaspGenerationConfig::default();
    assert_eq!(config.preset, VaspPreset::Relax);
    assert_eq!(config.kppra, 1000);
    assert!(config.encut.is_none());
}

/// Test VaspPreset Display impl.
#[test]
fn test_vasp_preset_display() {
    use crystalmath_tui::models::VaspPreset;

    assert_eq!(format!("{}", VaspPreset::Relax), "Geometry Relaxation");
    assert_eq!(format!("{}", VaspPreset::Static), "Static Calculation");
    assert_eq!(format!("{}", VaspPreset::Bands), "Band Structure");
    assert_eq!(format!("{}", VaspPreset::Dos), "Density of States");
    assert_eq!(format!("{}", VaspPreset::Convergence), "Convergence Test");
}
