#!/bin/bash

# Cross-platform shell script to set up a virtual environment and run a specified Python script
# Usage: ./run_agent.sh <python_script_path>

# Check if Python script path is provided
if [ $# -ne 1 ]; then
  echo "Usage: $0 <python_script_path>" >&2
  exit 1
fi
PYTHON_SCRIPT="$1"

# Determine project directory from script location
SCRIPT_DIR=$(dirname "$(realpath "$0" 2>/dev/null || readlink -f "$0" 2>/dev/null || echo "$0")")
PROJECT_DIR="$SCRIPT_DIR"
echo "Project directory: $PROJECT_DIR"
echo "Python script to run: $PYTHON_SCRIPT"

# Change to project directory
cd "$PROJECT_DIR" || {
  echo "Error: Could not change to directory $PROJECT_DIR" >&2
  exit 1
}

# Remove .venv if it exists, otherwise do nothing
if [ -d ".venv" ]; then
  echo "Removing existing .venv directory..."
  rm -rf ".venv"
else
  echo ".venv directory not present, continuing..."
fi

# Detect operating system
OS=$(uname -s)
case "$OS" in
  Linux*) PLATFORM="linux" ;;
  Darwin*) PLATFORM="macos" ;;
  CYGWIN*|MINGW*|MSYS*) PLATFORM="windows" ;;
  *) echo "Error: Unsupported OS: $OS" >&2; exit 1 ;;
esac

# Set virtual environment paths
if [ "$PLATFORM" = "windows" ]; then
  VENV_DIR="$PROJECT_DIR/.venv/Scripts"
  VENV_PYTHON="$VENV_DIR/python.exe"
  UV_EXEC="$VENV_DIR/uv.exe"
  PYTHON_SCRIPT=$(echo "$PYTHON_SCRIPT" | sed 's|/|\\|g')
else
  VENV_DIR="$PROJECT_DIR/.venv/bin"
  VENV_PYTHON="$VENV_DIR/python"
  UV_EXEC="$VENV_DIR/uv"
fi

# Validate Python script exists
if [ ! -f "$PROJECT_DIR/$PYTHON_SCRIPT" ]; then
  echo "Error: Python script $PYTHON_SCRIPT not found in $PROJECT_DIR" >&2
  exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$PROJECT_DIR/.venv" ]; then
  if [ ! -w "$PROJECT_DIR" ]; then
    echo "Error: No write permission in $PROJECT_DIR. Cannot create .venv directory." >&2
    exit 1
  fi
  echo "Creating virtual environment in $PROJECT_DIR/.venv..."
  python3 -m venv .venv 2>&1 | tee "$PROJECT_DIR/venv_creation.log" || {
    echo "Error: Failed to create virtual environment. See venv_creation.log for details." >&2
    exit 1
  }
fi

# Install uv in the virtual environment if not present
if ! "$VENV_PYTHON" -m uv --version >/dev/null 2>&1; then
  echo "Installing uv in virtual environment..."
  pip install uv || {
    echo "Error: Failed to install uv" >&2
    exit 1
  }
fi

# Run uv sync
echo "Running uv sync in $PROJECT_DIR..."
uv sync || {
  echo "Error: uv sync failed" >&2
  exit 1
}

# Run the Python script with uv
echo "Running $PYTHON_SCRIPT..."
uv run "$PYTHON_SCRIPT" || {
  echo "Error: Failed to run $PYTHON_SCRIPT" >&2
  exit 1
}

echo "Script executed successfully."