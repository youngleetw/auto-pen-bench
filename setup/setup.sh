#!/bin/bash

# Function to check if a command is available
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if Docker is installed; if not, install it
if ! command_exists docker; then
    echo "Installing Docker..."
    sudo apt update
    sudo apt install -y docker.io
fi

# Check if Docker Compose is installed; if not, install it
if ! command_exists docker-compose && ! docker compose version >/dev/null 2>&1; then
    echo "Installing Docker Compose..."
    sudo apt update
    sudo apt install -y docker-compose
fi

# Check if Python 3 is installed; if not, install it
if ! command_exists python3; then
    echo "Installing Python 3..."
    sudo apt update
    sudo apt install -y python3
fi

# Check if uv is installed; if not, install it
if ! command_exists uv; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

mkdir -p benchmark/machines/kali/tmp_script

echo "AUTOPENBENCH=$(pwd)/benchmark" > .env
echo "KALISCRIPTS=$(pwd)/benchmark/machines/kali/tmp_script" >> .env

# Prefer uv from PATH, then fallback to the default install location.
UV_BIN="${UV_BIN:-$(command -v uv || true)}"
if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
fi

if [ -z "$UV_BIN" ]; then
    echo "uv binary not found after installation attempt."
    exit 1
fi

if [ ! -d .venv ]; then
    "$UV_BIN" venv .venv
fi

"$UV_BIN" pip install --python .venv/bin/python -e .
