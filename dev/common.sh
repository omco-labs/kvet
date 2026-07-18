#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if command -v podman &> /dev/null; then
    RUNTIME="podman"
elif command -v docker &> /dev/null; then
    RUNTIME="docker"
else
    echo "No containerization program detected. Please install podman (preferred) or docker."
    exit 1
fi

[ -f "$REPO_ROOT/.env" ] || { echo '.env file not found, please create one before proceeding'; exit 1; }
set -a; source "$REPO_ROOT/.env"; set +a

IMAGE_NAME="kvet"
