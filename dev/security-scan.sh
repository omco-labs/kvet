#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

command -v trivy &> /dev/null || { echo "trivy not found. Install: https://trivy.dev/latest/getting-started/installation/"; exit 1; }

trivy fs --scanners vuln,secret,misconfig --severity CRITICAL,HIGH "$REPO_ROOT"
