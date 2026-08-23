#!/usr/bin/env bash
# uninstall.sh — Safe Portable Harness Prefix Uninstaller
#
# Removes ume-harness installation from:
#   ${PREFIX}/lib/ume-harness/v0.1.0/
#   ${PREFIX}/bin/ume-harness
#
# Boundary & Safety Guarantees:
#   - Removes only ume-harness owned files
#   - User state (~/.ume-harness/state) is preserved by default
#   - No Claude Code host configuration is modified or deleted
set -euo pipefail

VERSION="v0.1.0"
PREFIX="${HOME}/.local"
YES=false

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  --prefix <DIR>    Installation prefix (default: ~/.local)"
    echo "  --version <VER>   Target version to remove (default: v0.1.0)"
    echo "  -y, --yes         Non-interactive confirmation"
    echo "  -h, --help        Show this help message"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --version)
            VERSION="$2"
            if ! [[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                echo "❌ Invalid version format: '$VERSION' (expected vX.Y.Z)" >&2
                exit 1
            fi
            shift 2
            ;;
        -y|--yes)
            YES=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "❌ Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# 1. Path Safety Guards
if [ -z "${PREFIX}" ] || [ "${PREFIX}" = "/" ] || [ "${PREFIX}" = "/usr" ] || [ "${PREFIX}" = "/System" ] || [ "${PREFIX}" = "/bin" ]; then
    echo "❌ Unsafe or invalid prefix: '${PREFIX}'" >&2
    exit 1
fi

LIB_DIR="${PREFIX}/lib/ume-harness/${VERSION}"
BIN_DIR="${PREFIX}/bin"

echo "=== Umeboshi Portable Harness Uninstaller ==="
echo "Prefix:    ${PREFIX}"
echo "Lib Dir:   ${LIB_DIR}"
echo "Bin Dir:   ${BIN_DIR}"
echo "Version:   ${VERSION}"

if [ ! -d "${LIB_DIR}" ] && [ ! -e "${BIN_DIR}/ume-harness" ]; then
    echo "⚠️ No installation found at ${LIB_DIR}. Nothing to remove."
    exit 0
fi

# 2. Ownership Verification
if [ -d "${LIB_DIR}" ]; then
    if [ ! -f "${LIB_DIR}/package_manifest.json" ]; then
        echo "❌ Safety Check Failed: ${LIB_DIR} does not contain package_manifest.json (not an authentic ume-harness install)." >&2
        exit 1
    fi
fi

if [ "${YES}" = false ]; then
    read -p "Are you sure you want to remove ume-harness ${VERSION}? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

# 3. Safe Removal of Owned Payload
if [ -d "${LIB_DIR}" ]; then
    echo "-> Removing library payload: ${LIB_DIR}..."
    rm -rf "${LIB_DIR}"
    # Remove parent ume-harness directory if empty
    rmdir "${PREFIX}/lib/ume-harness" 2>/dev/null || true
    rmdir "${PREFIX}/lib" 2>/dev/null || true
fi

# 4. Safe Removal of CLI Entrypoint
if [ -e "${BIN_DIR}/ume-harness" ]; then
    if grep -q "ume-harness" "${BIN_DIR}/ume-harness" 2>/dev/null; then
        echo "-> Removing CLI wrapper: ${BIN_DIR}/ume-harness..."
        rm -f "${BIN_DIR}/ume-harness"
        rmdir "${BIN_DIR}" 2>/dev/null || true
    else
        echo "⚠️ Skipping ${BIN_DIR}/ume-harness (file not recognized as ume-harness wrapper)."
    fi
fi

echo ""
echo "=== Uninstall Completed Successfully ==="
echo "Note: User state directory (~/.ume-harness/state) was preserved."
echo "No host application settings were modified."
