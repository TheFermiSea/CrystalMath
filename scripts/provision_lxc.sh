#!/bin/bash
# scripts/provision_lxc.sh
# Provisions a Debian/Ubuntu LXC for CrystalMath development
# Run this INSIDE the LXC container as root (or with sudo)

set -e

echo ">>> Updating system packages..."
apt-get update && apt-get upgrade -y
apt-get install -y \
    curl git build-essential pkg-config libssl-dev \
    python3 python3-pip python3-venv \
    sqlite3 tmux vim jq tree unzip

echo ">>> Installing Rust..."
if ! command -v rustc &> /dev/null; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
else
    echo "Rust already installed."
fi

echo ">>> Installing uv (Python package manager)..."
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.cargo/env"
else
    echo "uv already installed."
fi

echo ">>> Installing Bats (Bash Automated Testing System)..."
if ! command -v bats &> /dev/null; then
    git clone https://github.com/bats-core/bats-core.git /tmp/bats-core
    /tmp/bats-core/install.sh /usr/local
    rm -rf /tmp/bats-core
else
    echo "Bats already installed."
fi

echo ">>> Verifying dependencies..."
rustc --version
uv --version
bats --version

echo ">>> Setup complete! You can now clone the repo (if not already present) and run setup commands."
echo "    Recommended next steps for CrystalMath:"
echo "    1. cd tui && uv venv && source .venv/bin/activate && uv pip install -e \".[dev]\""
echo "    2. cd ../python && uv pip install -e ."
echo "    3. cd .. && ./scripts/build-tui.sh"
