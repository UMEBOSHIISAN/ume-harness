#!/usr/bin/env bash
# install.sh — Fail-Safe Portable Harness Prefix Installer
#
# Installs the 30-file Generic Install Payload into:
#   ${PREFIX}/lib/ume-harness/v0.1.0/
#   ${PREFIX}/bin/ume-harness
#
# Boundary Guarantee:
#   PACKAGE INSTALL != HOST INTEGRATION ACTIVATION
#   This installer installs standard adapter assets but does NOT modify ~/.claude
#   or activate any host integration automatically.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="v0.1.0"
PREFIX="${HOME}/.local"
FORCE=false
DRY_RUN=false

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  --prefix <DIR>    Installation prefix (default: ~/.local)"
    echo "  --force           Overwrite existing installation of same version"
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
STAGING_DIR="${PREFIX}/lib/ume-harness/.staging_$$"

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

PAYLOAD_COUNT=$(python3 -c "import json; print(len(json.load(open('${MANIFEST_FILE}'))['install_payload']))")
if [ "${PAYLOAD_COUNT}" -ne 30 ]; then
    echo "❌ Manifest Mismatch: package_manifest.json declares ${PAYLOAD_COUNT} payload files (expected 30)." >&2
    exit 1
fi

PAYLOAD_LIST=()
while IFS= read -r line; do
    [ -n "$line" ] && PAYLOAD_LIST+=("$line")
done < <(python3 -c "import json; [print(x) for x in json.load(open('${MANIFEST_FILE}'))['install_payload']]")

for rel in "${PAYLOAD_LIST[@]}"; do
    if [ ! -f "${SOURCE_DIR}/${rel}" ]; then
        echo "❌ Missing source payload file: ${SOURCE_DIR}/${rel}" >&2
        exit 1
    fi
done
echo "All 30 source payload files verified."

if [ "${DRY_RUN}" = true ]; then
    echo "Dry run complete. No changes made."
    exit 0
fi

# 3. Collision Checks
if [ -d "${LIB_DIR}" ] && [ "${FORCE}" = false ]; then
    echo "❌ Target version ${VERSION} already exists at ${LIB_DIR}. Use --force to replace." >&2
    exit 1
fi

if [ -e "${BIN_DIR}/ume-harness" ] && [ "${FORCE}" = false ]; then
    # Check if existing CLI is owned by ume-harness
    if ! grep -q "ume-harness" "${BIN_DIR}/ume-harness" 2>/dev/null; then
        echo "❌ Collision: Unrelated file exists at ${BIN_DIR}/ume-harness. Use --force to overwrite." >&2
        exit 1
    fi
fi

# 4. Safe Staging Installation
echo "-> Staging payload in ${STAGING_DIR}..."
rm -rf "${STAGING_DIR}"
mkdir -p "${STAGING_DIR}"

cleanup() {
    rm -rf "${STAGING_DIR}"
}
trap cleanup EXIT

for rel in "${PAYLOAD_LIST[@]}"; do
    dest="${STAGING_DIR}/${rel}"
    mkdir -p "$(dirname "${dest}")"
    cp "${SOURCE_DIR}/${rel}" "${dest}"
done

# Copy scripts/health_check.py as diagnostic utility into installed lib
mkdir -p "${STAGING_DIR}/scripts"
cp "${SOURCE_DIR}/scripts/health_check.py" "${STAGING_DIR}/scripts/health_check.py"
chmod +x "${STAGING_DIR}/scripts/health_check.py"

# Include standard domain canary
if [ -f "${SOURCE_DIR}/domain_descriptor.json" ]; then
    cp "${SOURCE_DIR}/domain_descriptor.json" "${STAGING_DIR}/domain_descriptor.json"
else
    # Create standard isolated canary descriptor
    cat << 'CANARY_EOF' > "${STAGING_DIR}/domain_descriptor.json"
{
  "domain_id": "ume-harness",
  "version": "0.1.0",
  "environment": "portable",
  "root_identity_model": "sha256_canonical_json_v1"
}
CANARY_EOF
fi

chmod +x "${STAGING_DIR}/bin/ume-harness"
chmod +x "${STAGING_DIR}/adapters/claude-code/lease_gate_runner.py"
chmod +x "${STAGING_DIR}/adapters/claude-code/pretooluse_hook.py"

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
cat << WRAPPER_EOF > "${BIN_DIR}/ume-harness"
#!/usr/bin/env bash
# ume-harness launcher wrapper
exec python3 "${LIB_DIR}/bin/ume-harness" "\$@"
WRAPPER_EOF
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
echo "(No host configurations were altered. Manual settings merge is required for integration)."
