#!/usr/bin/env bash
# Install the kvet CLI from this checkout (kvet is not published on PyPI).
#
# Prefers `uv tool install`, falling back to pipx, then pip. The resulting
# `kvet` binary is fully independent from any installed upstream `vet`
# (separate binary name, tool venv, and XDG config/cache/state paths), so both
# tools can coexist on the same host.
set -euo pipefail

REPO_ROOT="$(git -C "$(cd "$(dirname "$0")" && pwd)" rev-parse --show-toplevel)"

if command -v uv >/dev/null 2>&1; then
    echo "Installing kvet with uv from ${REPO_ROOT} ..."
    uv tool install --from "${REPO_ROOT}" kvet --reinstall
elif command -v pipx >/dev/null 2>&1; then
    echo "Installing kvet with pipx from ${REPO_ROOT} ..."
    pipx install --force "${REPO_ROOT}"
else
    echo "Installing kvet with pip from ${REPO_ROOT} ..."
    python3 -m pip install --user "${REPO_ROOT}"
fi

echo
if command -v kvet >/dev/null 2>&1; then
    echo "kvet installed at: $(command -v kvet)"
    kvet --version
else
    echo "kvet was installed, but is not on PATH yet." >&2
    echo "Ensure your tool bin directory (e.g. ~/.local/bin) is on PATH, then run: kvet --version" >&2
    exit 1
fi
