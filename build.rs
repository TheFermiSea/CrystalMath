use std::path::Path;
use std::process::Command;

fn main() {
    // Tell Cargo to re-run this script if the environment definitions change
    println!("cargo:rerun-if-changed=pyproject.toml");
    println!("cargo:rerun-if-changed=uv.lock");
    println!("cargo:rerun-if-env-changed=VIRTUAL_ENV");
    println!("cargo:rerun-if-env-changed=PYO3_PYTHON");

    // 1. Honor an explicit PYO3_PYTHON override if a developer explicitly sets it
    if std::env::var("PYO3_PYTHON").is_ok() {
        return;
    }

    // 2. Try to query uv dynamically to find the active Python interpreter
    if let Ok(output) = Command::new("uv").args(["python", "find"]).output() {
        if output.status.success() {
            let path_str = String::from_utf8_lossy(&output.stdout).trim().to_string();
            let python_path = Path::new(&path_str);
            if python_path.exists() {
                println!("cargo:rustc-env=PYO3_PYTHON={}", python_path.display());
                return;
            }
        }
    }

    // 3. Fallback: Check standard VIRTUAL_ENV environment paths (active shell venv)
    if let Ok(venv) = std::env::var("VIRTUAL_ENV") {
        // Handle platform specific binary layouts automatically
        let python_bin = if cfg!(windows) {
            "Scripts/python.exe"
        } else {
            "bin/python"
        };
        let fallback_path = Path::new(&venv).join(python_bin);
        if fallback_path.exists() {
            println!("cargo:rustc-env=PYO3_PYTHON={}", fallback_path.display());
            return;
        }
    }

    // 4. Final Fallback: Emit a warning but let the default toolchain try to resolve it
    println!("cargo:warning=build.rs: Neither uv python find nor VIRTUAL_ENV found. Falling back to default system Python.");
}
