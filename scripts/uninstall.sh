#!/usr/bin/env bash
# uninstall.sh — Safe Portable Harness Prefix Uninstaller
#
# Removes ume-harness installation from:
#   ${PREFIX}/lib/ume-harness/v0.1.4/
#   ${PREFIX}/bin/ume-harness
#
# Boundary & Safety Guarantees:
#   - Removes only ume-harness owned files
#   - Disconnects only the three exact canonical Claude Code hook commands
#   - User state (~/.ume-harness/state) is preserved by default
#   - Aborts before payload deletion if Claude settings cannot be verified
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="v0.1.4"
PREFIX="${HOME}/.local"
SETTINGS_PATH="${HOME}/.claude/settings.json"
YES=false

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  --prefix <DIR>    Installation prefix (default: ~/.local)"
    echo "  --version <VER>   Target version to remove (default: v0.1.4)"
    echo "  --settings-path <FILE> Claude settings path (default: ~/.claude/settings.json)"
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
        --settings-path)
            SETTINGS_PATH="$2"
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
if [ -z "${SETTINGS_PATH}" ]; then
    echo "❌ Invalid empty settings path." >&2
    exit 1
fi

LIB_DIR="${PREFIX}/lib/ume-harness/${VERSION}"
BIN_DIR="${PREFIX}/bin"

echo "=== Umeboshi Portable Harness Uninstaller ==="
echo "Prefix:    ${PREFIX}"
echo "Lib Dir:   ${LIB_DIR}"
echo "Bin Dir:   ${BIN_DIR}"
echo "Version:   ${VERSION}"
echo "Settings:  ${SETTINGS_PATH}"

INSTALL_FOUND=true
if [ ! -d "${LIB_DIR}" ] && [ ! -e "${BIN_DIR}/ume-harness" ]; then
    INSTALL_FOUND=false
    echo "⚠️ No payload found at ${LIB_DIR}; checking for dangling owned hooks."
fi

# 2. Ownership Verification
if [ -d "${LIB_DIR}" ]; then
    if [ ! -f "${LIB_DIR}/package_manifest.json" ]; then
        echo "❌ Safety Check Failed: ${LIB_DIR} does not contain package_manifest.json (not an authentic ume-harness install)." >&2
        exit 1
    fi
    OWNERSHIP_VERIFIER="${SOURCE_DIR}/scripts/health_check.py"
    if [ ! -f "${OWNERSHIP_VERIFIER}" ]; then
        echo "❌ Safety Check Failed: external install ownership verifier is unavailable; refusing removal." >&2
        exit 1
    fi
    if ! python3 "${OWNERSHIP_VERIFIER}" \
        --installed-dir "${LIB_DIR}" \
        --owned-install-only >/dev/null; then
        echo "❌ Safety Check Failed: Unproven install payload at ${LIB_DIR}. User-owned or changed bytes were preserved." >&2
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

# 3. Ownership-Scoped Claude Hook Disconnect
# Trust only the helper shipped beside the uninstaller being executed. The
# target prefix may contain an older helper with incompatible exit semantics.
HOOK_HELPER="${SOURCE_DIR}/runtime/hook_setup_service.py"
if [ ! -f "${HOOK_HELPER}" ]; then
    echo "❌ Safety Check Failed: hook ownership helper is unavailable; refusing removal." >&2
    exit 1
fi
EXPECTED_OWNERSHIP_PROTOCOL="ume-harness-ownership.v1"
if ! ACTUAL_OWNERSHIP_PROTOCOL=$(python3 "${HOOK_HELPER}" protocol-version --pkg-root "${LIB_DIR}" 2>/dev/null); then
    echo "❌ Safety Check Failed: hook ownership helper protocol could not be verified; refusing removal." >&2
    exit 1
fi
if [ "${ACTUAL_OWNERSHIP_PROTOCOL}" != "${EXPECTED_OWNERSHIP_PROTOCOL}" ]; then
    echo "❌ Safety Check Failed: unsupported hook ownership helper protocol; refusing removal." >&2
    exit 1
fi

is_owned_cli_wrapper() {
    local wrapper_path="$1"
    python3 "${HOOK_HELPER}" verify-cli-wrapper \
        --pkg-root "${LIB_DIR}" \
        --wrapper-path "${wrapper_path}"
}

echo "-> Disconnecting exact owned Claude Code hooks before removing payload..."
if ! python3 "${HOOK_HELPER}" disconnect-for-uninstall --pkg-root "${LIB_DIR}" --settings-path "${SETTINGS_PATH}"; then
    echo "❌ Safety Check Failed: owned hooks could not be proven disconnected. Installation was preserved." >&2
    exit 1
fi

if [ "${INSTALL_FOUND}" = false ]; then
    echo "=== Uninstall Completed Successfully ==="
    echo "No payload was present; exact owned hook commands were checked and disconnected."
    exit 0
fi

# 4. Safe Removal of CLI Entrypoint
# Verify with the installed ownership helper before removing its payload.
if [ -e "${BIN_DIR}/ume-harness" ] || [ -L "${BIN_DIR}/ume-harness" ]; then
    if is_owned_cli_wrapper "${BIN_DIR}/ume-harness"; then
        echo "-> Removing CLI wrapper: ${BIN_DIR}/ume-harness..."
        rm -f "${BIN_DIR}/ume-harness"
        rmdir "${BIN_DIR}" 2>/dev/null || true
    else
        echo "⚠️ Skipping ${BIN_DIR}/ume-harness (file not recognized as ume-harness wrapper)."
    fi
fi

# 5. Safe Removal of Owned Payload
if [ -d "${LIB_DIR}" ]; then
    echo "-> Removing library payload: ${LIB_DIR}..."
    rm -rf "${LIB_DIR}"
    # Remove parent ume-harness directory if empty
    rmdir "${PREFIX}/lib/ume-harness" 2>/dev/null || true
    rmdir "${PREFIX}/lib" 2>/dev/null || true
fi

echo ""
echo "=== Uninstall Completed Successfully ==="
echo "Note: User state directory (~/.ume-harness/state) was preserved."
echo "Only exact ume-harness-owned Claude hook commands were disconnected."
