#!/usr/bin/env bash
# install.sh — Fail-Safe Portable Harness Prefix Installer
#
# Installs the explicit Generic Install Payload into:
#   ${PREFIX}/lib/ume-harness/v0.1.3/
#   ${PREFIX}/bin/ume-harness
#
# Boundary Guarantee:
#   PACKAGE INSTALL != HOST INTEGRATION ACTIVATION
#   This installer installs standard adapter assets but does NOT modify ~/.claude
#   or activate any host integration automatically.
set -euo pipefail

# Installer helpers must not create runtime cache bytes inside a target prefix
# before ownership verification (including when PYTHONPYCACHEPREFIX points there).
export PYTHONDONTWRITEBYTECODE=1

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="v0.1.3"
PREFIX="${HOME}/.local"
FORCE=false
DRY_RUN=false

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  --prefix <DIR>    Installation prefix (default: ~/.local)"
    echo "  --force           Replace a verified ume-harness installation of the same version"
    echo "  --dry-run         Show actions without performing changes"
    echo "  -h, --help        Show this help message"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
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

# 1. Path & Prefix Validation
if [ -z "${PREFIX}" ] || [ "${PREFIX}" = "/" ] || [ "${PREFIX}" = "/usr" ] || [ "${PREFIX}" = "/System" ] || [ "${PREFIX}" = "/bin" ]; then
    echo "❌ Unsafe or invalid prefix: '${PREFIX}'" >&2
    exit 1
fi

LIB_DIR="${PREFIX}/lib/ume-harness/${VERSION}"
BIN_DIR="${PREFIX}/bin"
STAGING_PARENT="${PREFIX}/lib/ume-harness"
STAGING_DIR=""
OWNERSHIP_HELPER="${SOURCE_DIR}/runtime/hook_setup_service.py"

emit_cli_wrapper() {
    python3 "${OWNERSHIP_HELPER}" emit-cli-wrapper --pkg-root "${LIB_DIR}"
}

is_owned_cli_wrapper() {
    local wrapper_path="$1"
    python3 "${OWNERSHIP_HELPER}" verify-cli-wrapper \
        --pkg-root "${LIB_DIR}" \
        --wrapper-path "${wrapper_path}"
}

is_owned_payload() {
    python3 "${SOURCE_DIR}/scripts/health_check.py" \
        --installed-dir "${LIB_DIR}" \
        --owned-install-only >/dev/null
}

echo "=== Umeboshi Portable Harness Installer ==="
echo "Source:  ${SOURCE_DIR}"
echo "Prefix:  ${PREFIX}"
echo "Lib Dir: ${LIB_DIR}"
echo "Bin Dir: ${BIN_DIR}"
echo "Force:   ${FORCE}"

# 2. Source Payload Validation from package_manifest.json
echo "-> Validating source payload from package_manifest.json..."
MANIFEST_FILE="${SOURCE_DIR}/package_manifest.json"
if [ ! -f "${MANIFEST_FILE}" ]; then
    echo "❌ Missing package_manifest.json in ${SOURCE_DIR}" >&2
    exit 1
fi

PAYLOAD_COUNT=$(python3 -c 'import json, sys; print(len(json.load(open(sys.argv[1]))["install_payload"]))' "${MANIFEST_FILE}")
if [ "${PAYLOAD_COUNT}" -le 0 ]; then
    echo "❌ Manifest Mismatch: package_manifest.json contains no install_payload files." >&2
    exit 1
fi

PAYLOAD_LIST=()
while IFS= read -r line; do
    [ -n "$line" ] && PAYLOAD_LIST+=("$line")
done < <(python3 -c 'import json, sys; [print(x) for x in json.load(open(sys.argv[1]))["install_payload"]]' "${MANIFEST_FILE}")

for rel in "${PAYLOAD_LIST[@]}"; do
    if [ ! -f "${SOURCE_DIR}/${rel}" ]; then
        echo "❌ Missing source payload file: ${SOURCE_DIR}/${rel}" >&2
        exit 1
    fi
done
echo "All ${PAYLOAD_COUNT} source payload files verified."

echo "-> Comparing source bytes with the frozen release identity..."
python3 "${SOURCE_DIR}/scripts/health_check.py" \
    --installed-dir "${SOURCE_DIR}" \
    --identity-only

if [ "${DRY_RUN}" = true ]; then
    echo "Dry run complete. No changes made."
    exit 0
fi

# 3. Collision Checks
if [ -L "${LIB_DIR}" ] || { [ -e "${LIB_DIR}" ] && [ ! -d "${LIB_DIR}" ]; }; then
    echo "❌ Collision: Unsafe non-directory path exists at ${LIB_DIR}. Refusing to follow or replace it." >&2
    exit 1
fi

if [ -d "${LIB_DIR}" ]; then
    if [ "${FORCE}" = false ]; then
        echo "❌ Target version ${VERSION} already exists at ${LIB_DIR}. Use --force to replace a verified installation." >&2
        exit 1
    fi
    if ! is_owned_payload; then
        echo "❌ Collision: Unproven version directory exists at ${LIB_DIR}. Refusing to replace user-owned bytes." >&2
        exit 1
    fi
fi

if [ -L "${BIN_DIR}/ume-harness" ] || { [ -e "${BIN_DIR}/ume-harness" ] && [ ! -f "${BIN_DIR}/ume-harness" ]; }; then
    echo "❌ Collision: Unsafe non-regular path exists at ${BIN_DIR}/ume-harness. Refusing to follow or replace it." >&2
    exit 1
fi

if [ -e "${BIN_DIR}/ume-harness" ]; then
    if ! is_owned_cli_wrapper "${BIN_DIR}/ume-harness"; then
        echo "❌ Collision: Unrelated file exists at ${BIN_DIR}/ume-harness. Refusing to overwrite user-owned bytes." >&2
        exit 1
    fi
fi

# 4. Safe Staging Installation
if [ -L "${STAGING_PARENT}" ] || { [ -e "${STAGING_PARENT}" ] && [ ! -d "${STAGING_PARENT}" ]; }; then
    echo "❌ Collision: Unsafe staging parent exists at ${STAGING_PARENT}. Refusing to follow or replace it." >&2
    exit 1
fi
mkdir -p "${STAGING_PARENT}"
STAGING_DIR="$(mktemp -d "${STAGING_PARENT}/.staging.XXXXXX")"
echo "-> Staging payload in ${STAGING_DIR}..."

cleanup() {
    if [ -n "${STAGING_DIR}" ] && [ -d "${STAGING_DIR}" ] && [ ! -L "${STAGING_DIR}" ]; then
        rm -rf "${STAGING_DIR}"
    fi
}
trap cleanup EXIT

for rel in "${PAYLOAD_LIST[@]}"; do
    dest="${STAGING_DIR}/${rel}"
    mkdir -p "$(dirname "${dest}")"
    cp "${SOURCE_DIR}/${rel}" "${dest}"
done

chmod +x "${STAGING_DIR}/bin/ume-harness"
chmod +x "${STAGING_DIR}/adapters/claude-code/lease_gate_runner.py"
chmod +x "${STAGING_DIR}/adapters/claude-code/pretooluse_hook.py"
chmod +x "${STAGING_DIR}/adapters/claude-code/permission_request_hook.py"
chmod +x "${STAGING_DIR}/adapters/claude-code/posttooluse_failure_hook.py"
chmod +x "${STAGING_DIR}/scripts/health_check.py"
chmod +x "${STAGING_DIR}/scripts/uninstall.sh"

# 5. Atomic Promotion to Version Directory
echo "-> Promoting staging to ${LIB_DIR}..."
mkdir -p "$(dirname "${LIB_DIR}")"
if [ -d "${LIB_DIR}" ]; then
    rm -rf "${LIB_DIR}"
fi
mv "${STAGING_DIR}" "${LIB_DIR}"

# 6. Install CLI entrypoint
echo "-> Installing CLI to ${BIN_DIR}/ume-harness..."
mkdir -p "${BIN_DIR}"
emit_cli_wrapper > "${BIN_DIR}/ume-harness"
chmod 755 "${BIN_DIR}/ume-harness"

# 7. Run Installed Health Check
echo "-> Running installed diagnostics..."
python3 "${LIB_DIR}/scripts/health_check.py" --installed-dir "${LIB_DIR}" --prefix "${PREFIX}"

echo ""
echo "=== Installation Completed Successfully! ==="
echo "Installed version: ${VERSION}"
echo "CLI binary:        ${BIN_DIR}/ume-harness"
echo "Package library:   ${LIB_DIR}"
echo ""
echo "Notice: Standard Claude Code adapter assets are available at:"
echo "  ${LIB_DIR}/adapters/claude-code/"
echo "Package installation did not alter host settings."
echo "Connect explicitly with: ${BIN_DIR}/ume-harness setup"
