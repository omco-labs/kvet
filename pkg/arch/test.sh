#!/usr/bin/env bash
set -euo pipefail

# builds Arch package from working tree, installs it, runs a few non-llm kvet commands, tests uninstall

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONTAINER_NAME="kvet-pkgbuild-test-$$"

cleanup() {
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# arch container w/ read-only mounted code
docker run --name "$CONTAINER_NAME" -d -v "$REPO_ROOT":/repo:ro archlinux:base-devel sleep 600

run() {
    docker exec "$CONTAINER_NAME" bash -c "$1"
}

run "pacman -Syu --noconfirm python git"

# prep build env
run "
    useradd -m builder &&
    mkdir /build && cp /repo/pkg/arch/PKGBUILD /repo/pkg/arch/kvet.install /build/ &&

    tar -czf /build/kvet-current.tar.gz -C /repo --transform='s,^\.,kvet-current,' \
        --exclude='.git' --exclude='pkg/arch/test.sh' . &&

    sed -i 's|^source=.*|source=(\"kvet-current.tar.gz\")|' /build/PKGBUILD &&
    sed -i 's|\$srcdir/kvet-\$pkgver|\$srcdir/kvet-current|' /build/PKGBUILD &&

    chown -R builder:builder /build
"

# build + install
run "su - builder -c 'cd /build && makepkg -sf --noconfirm'"
run "pacman -U --noconfirm /build/kvet-*-any.pkg.tar.zst"

# basic non-llm commands
run "command -v kvet"
run "kvet --help"
run "kvet --version"
run "kvet --list-issue-codes"

# uninstall
run "pacman -R --noconfirm kvet"

if run "command -v kvet" 2>/dev/null; then
    echo "FAIL: kvet still found after uninstall"
    exit 1
fi

if run "test -d /opt/kvet"; then
    echo "FAIL: /opt/kvet still exists after uninstall"
    exit 1
fi
