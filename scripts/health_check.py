#!/usr/bin/env python3
"""Verify an installed ume-harness payload against its frozen release identity."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from typing import Any


EXPECTED_ROOT_DIGEST = "07aa3b52a452b3dad53c9ecf4125adc86aff360534566cb4fadbb601a8648c38"
IDENTITY_ALGORITHM = "sha256-canonical-path-map-v1"
IDENTITY_SELF_EXCLUSIONS = frozenset({"scripts/health_check.py"})
MANDATORY_RELEASE_FILES = frozenset({
    "runtime/translation_konjac.py",
    "runtime/hook_setup_service.py",
    "runtime/common_language_pack.py",
    "common-language/packs/ja-JP/p0_concepts.json",
    "common-language/schema/concept_pack.schema.json",
    "adapters/claude-code/pretooluse_hook.py",
    "adapters/claude-code/permission_request_hook.py",
    "adapters/claude-code/posttooluse_failure_hook.py",
})


def _is_safe_relative_path(path: Any) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and not os.path.isabs(path)
        and path == os.path.normpath(path)
        and path != ".."
        and not path.startswith(f"..{os.sep}")
    )


def _read_regular_file(path: str) -> bytes:
    """Read an untrusted closure member without following or blocking on special files."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"release closure member is not a regular file: {path}")
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read()
    finally:
        os.close(fd)


def _sha256_regular_file(path: str) -> str:
    return hashlib.sha256(_read_regular_file(path)).hexdigest()


def _read_closure_member(root: str, relative_path: str) -> bytes:
    """Read one closure file without accepting symlinked path components."""
    current = os.path.abspath(root)
    parts = relative_path.split(os.sep)
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        metadata = os.lstat(current)
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(
                f"release closure path contains a symlink component: {relative_path}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(
                f"release closure parent is not a directory: {relative_path}"
            )
    return _read_regular_file(current)


def calculate_release_identity(root: str, closure: list[str]) -> str:
    """Hash the exact bytes at each explicit closure path into one root identity."""
    mapping: dict[str, str] = {}
    for rel in closure:
        if not _is_safe_relative_path(rel):
            raise ValueError(f"unsafe release closure path: {rel!r}")
        mapping[rel] = hashlib.sha256(_read_closure_member(root, rel)).hexdigest()
    canonical = json.dumps(
        mapping,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_manifest(installed_dir: str) -> dict[str, Any]:
    path = os.path.join(installed_dir, "package_manifest.json")
    data = json.loads(_read_regular_file(path).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("package_manifest.json root must be an object")
    return data


def _validate_manifest_contract(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    payload = manifest.get("install_payload")
    identity = manifest.get("release_identity")
    if not isinstance(payload, list) or not payload:
        raise ValueError("install_payload must be a non-empty array")
    if not isinstance(identity, dict):
        raise ValueError("release_identity must be an object")
    closure = identity.get("closure")
    if identity.get("algorithm") != IDENTITY_ALGORITHM:
        raise ValueError(f"release_identity.algorithm must be {IDENTITY_ALGORITHM}")
    if not isinstance(closure, list) or not closure:
        raise ValueError("release_identity.closure must be a non-empty array")
    if any(not _is_safe_relative_path(path) for path in payload + closure):
        raise ValueError("manifest contains an unsafe path")
    if len(payload) != len(set(payload)) or len(closure) != len(set(closure)):
        raise ValueError("manifest path lists must not contain duplicates")
    missing_required = sorted(MANDATORY_RELEASE_FILES - set(closure))
    if missing_required:
        raise ValueError(f"mandatory release closure files missing: {missing_required}")
    expected_payload = set(closure) | set(IDENTITY_SELF_EXCLUSIONS)
    if set(payload) != expected_payload:
        raise ValueError(
            "install_payload must equal release_identity.closure plus the health-check trust anchor"
        )
    return payload, closure


def verify_release_identity(installed_dir: str) -> tuple[bool, str]:
    try:
        manifest = _load_manifest(installed_dir)
        _payload, closure = _validate_manifest_contract(manifest)
        actual = calculate_release_identity(installed_dir, closure)
    except Exception as e:
        return False, f"identity verification error: {e}"

    if actual != EXPECTED_ROOT_DIGEST:
        return False, f"expected={EXPECTED_ROOT_DIGEST} actual={actual}"
    return True, f"expected={EXPECTED_ROOT_DIGEST} actual={actual}"


def _load_owned_release_anchors() -> dict[str, str]:
    """Load immutable install anchors from the separate release gate source."""
    gate_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "release_promote.py")
    tree = ast.parse(_read_regular_file(gate_path).decode("utf-8"), filename=gate_path)
    anchors: Any = None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "OWNED_INSTALL_HEALTH_ANCHORS":
            anchors = ast.literal_eval(node.value)
            break
    if not isinstance(anchors, dict) or not anchors:
        raise ValueError("release gate does not define owned install health anchors")
    if any(
        not isinstance(root, str)
        or not isinstance(health_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", root) is None
        or re.fullmatch(r"[0-9a-f]{64}", health_sha) is None
        for root, health_sha in anchors.items()
    ):
        raise ValueError("release gate contains an invalid owned install health anchor")
    return dict(anchors)


def verify_owned_install(installed_dir: str) -> tuple[bool, str]:
    """Verify exact owned install closure before a destructive same-version replacement."""
    installed_dir = os.path.realpath(os.path.abspath(installed_dir))
    verifier_path = os.path.realpath(os.path.abspath(__file__))
    try:
        verifier_is_installed_copy = os.path.commonpath((verifier_path, installed_dir)) == installed_dir
    except ValueError:
        verifier_is_installed_copy = False
    if verifier_is_installed_copy:
        return False, (
            "owned install verification requires an external verifier; "
            "the installed health-check copy cannot attest its own excluded bytes"
        )

    try:
        manifest = _load_manifest(installed_dir)
        payload, closure = _validate_manifest_contract(manifest)
        expected_files = set(payload)
        expected_dirs: set[str] = set()
        for rel in payload:
            parent = os.path.dirname(rel)
            while parent:
                expected_dirs.add(parent)
                parent = os.path.dirname(parent)

        actual_files: set[str] = set()
        actual_dirs: set[str] = set()
        unsafe_paths: list[str] = []
        for current_root, dirnames, filenames in os.walk(installed_dir, followlinks=False):
            for name in dirnames:
                path = os.path.join(current_root, name)
                rel = os.path.relpath(path, installed_dir)
                actual_dirs.add(rel)
                if not stat.S_ISDIR(os.lstat(path).st_mode):
                    unsafe_paths.append(rel)
            for name in filenames:
                path = os.path.join(current_root, name)
                rel = os.path.relpath(path, installed_dir)
                actual_files.add(rel)
                metadata = os.lstat(path)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    unsafe_paths.append(rel)
    except Exception as exc:
        return False, f"owned install verification error: {exc}"

    unexpected_files = sorted(actual_files - expected_files)
    missing_files = sorted(expected_files - actual_files)
    unexpected_dirs = sorted(actual_dirs - expected_dirs)
    if unsafe_paths or unexpected_files or missing_files or unexpected_dirs:
        return False, (
            "install closure mismatch: "
            f"unsafe={sorted(unsafe_paths)} missing={missing_files} "
            f"unexpected_files={unexpected_files} unexpected_dirs={unexpected_dirs}"
        )

    try:
        actual_root = calculate_release_identity(installed_dir, closure)
        expected_health_sha = _load_owned_release_anchors().get(actual_root)
        if expected_health_sha is None:
            return False, f"unrecognized owned release identity: {actual_root}"
        actual_health_sha = _sha256_regular_file(
            os.path.join(installed_dir, "scripts/health_check.py")
        )
        if actual_health_sha != expected_health_sha:
            return False, (
                "health-check trust anchor mismatch: "
                f"expected={expected_health_sha} actual={actual_health_sha}"
            )
    except Exception as exc:
        return False, f"owned install identity error: {exc}"

    return True, (
        f"exact owned install closure: {len(expected_files)} files; identity={actual_root}"
    )


def run_diagnostics(installed_dir: str, prefix_dir: str | None = None, json_output: bool = False) -> int:
    installed_dir = os.path.abspath(installed_dir)
    if prefix_dir:
        prefix_dir = os.path.abspath(prefix_dir)
    else:
        prefix_dir = os.path.dirname(os.path.dirname(os.path.dirname(installed_dir)))

    checks: list[tuple[str, bool, str]] = []
    py_ver = sys.version_info
    checks.append(("Python >= 3.9", py_ver >= (3, 9), f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"))

    dir_ok = os.path.isdir(installed_dir)
    checks.append(("Installed Directory Exists", dir_ok, installed_dir))
    if not dir_ok:
        return _print_summary(checks, json_output)

    payload_files: list[str] = []
    manifest_ok = False
    manifest_detail = ""
    try:
        manifest = _load_manifest(installed_dir)
        payload_files, _closure = _validate_manifest_contract(manifest)
        manifest_ok = True
        manifest_detail = f"{len(payload_files)} declared install files"
    except Exception as e:
        manifest_detail = str(e)
    checks.append(("Package Manifest Contract", manifest_ok, manifest_detail))

    missing_files = [
        rel for rel in payload_files
        if not os.path.isfile(os.path.join(installed_dir, rel))
    ]
    payload_ok = manifest_ok and not missing_files
    checks.append((
        "Install Payload Complete",
        payload_ok,
        f"All {len(payload_files)} present" if payload_ok else f"Missing: {missing_files}",
    ))

    cli_candidates = [
        os.path.join(prefix_dir, "bin", "ume-harness"),
        os.path.join(installed_dir, "bin", "ume-harness"),
    ]
    cli_found = next(
        (path for path in cli_candidates if os.path.isfile(path) and os.access(path, os.X_OK)),
        None,
    )
    checks.append(("CLI Executable Entrypoint", cli_found is not None, cli_found or "None"))

    identity_ok, identity_detail = verify_release_identity(installed_dir)
    checks.append(("Release Byte Identity", identity_ok, identity_detail))

    import_ok = False
    if not identity_ok:
        import_detail = f"Skipped until release byte identity passes: {identity_detail}"
    else:
        import_detail = ""
        try:
            sub_env = os.environ.copy()
            sub_env["PYTHONDONTWRITEBYTECODE"] = "1"
            sub_env["PYTHONPATH"] = (
                f"{os.path.join(installed_dir, 'runtime')}:"
                f"{os.path.join(installed_dir, 'ux', 'japanese-human-layer')}"
            )
            trace_code = """
import activation_updater
import common_language_pack
import hook_setup_service
import human_layer_adapter
import local_execution_gate
import stop_adapter
import tool_policy
import translation_konjac
print("IMPORT_OK")
"""
            proc = subprocess.run(
                [sys.executable, "-c", trace_code],
                cwd=os.path.join(installed_dir, "runtime"),
                env=sub_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            import_ok = proc.returncode == 0 and "IMPORT_OK" in proc.stdout
            import_detail = "Imported from installed prefix" if import_ok else f"Failed: {proc.stderr[:200]}"
        except Exception as e:
            import_detail = f"Exception: {e}"
    checks.append(("Runtime Module Import Isolation", import_ok, import_detail))

    adapter_files = [
        "adapters/claude-code/lease_gate_runner.py",
        "adapters/claude-code/pretooluse_hook.py",
        "adapters/claude-code/permission_request_hook.py",
        "adapters/claude-code/posttooluse_failure_hook.py",
        "adapters/claude-code/settings.json.fragment",
        "adapters/claude-code/README.md",
    ]
    adapter_missing = [
        rel for rel in adapter_files
        if not os.path.isfile(os.path.join(installed_dir, rel))
    ]
    checks.append((
        "Claude Adapter Assets",
        not adapter_missing,
        "All present" if not adapter_missing else f"Missing: {adapter_missing}",
    ))
    hook_files = [
        "adapters/claude-code/pretooluse_hook.py",
        "adapters/claude-code/permission_request_hook.py",
        "adapters/claude-code/posttooluse_failure_hook.py",
    ]
    non_executable_hooks = [
        rel for rel in hook_files
        if not os.path.isfile(os.path.join(installed_dir, rel))
        or not os.access(os.path.join(installed_dir, rel), os.X_OK)
    ]
    checks.append((
        "Claude Hook Executability",
        not non_executable_hooks,
        "All executable" if not non_executable_hooks else f"Not executable: {non_executable_hooks}",
    ))
    return _print_summary(checks, json_output)


def _print_summary(checks: list[tuple[str, bool, str]], json_output: bool) -> int:
    all_passed = all(passed for _name, passed, _detail in checks)
    if json_output:
        print(json.dumps({
            "all_passed": all_passed,
            "checks": [
                {"name": name, "passed": passed, "detail": detail}
                for name, passed, detail in checks
            ],
        }, indent=2, ensure_ascii=False))
    else:
        print("=== Umeboshi Harness Installation Health Check ===")
        for name, passed, detail in checks:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"[{status}] {name:<35} : {detail}")
        print("=" * 55)
        if all_passed:
            print("🎉 All diagnostics PASSED. Installed release bytes match the frozen identity.")
        else:
            print("⚠️ Diagnostic failures found. Installation is incomplete, changed, or degraded.")
    return 0 if all_passed else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostics for installed ume-harness package")
    parser.add_argument("--installed-dir", default=None, help="Installed version directory")
    parser.add_argument("--prefix", default=None, help="Installation prefix")
    parser.add_argument("--identity-only", action="store_true", help="Verify only explicit release bytes")
    parser.add_argument(
        "--owned-install-only",
        action="store_true",
        help="Verify release bytes and exact install closure for safe replacement",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args(argv)

    installed_dir = args.installed_dir
    if not installed_dir:
        self_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isfile(os.path.join(self_parent, "package_manifest.json")):
            installed_dir = self_parent
        else:
            prefix = args.prefix or os.path.expanduser("~/.local")
            installed_dir = os.path.join(prefix, "lib", "ume-harness", "v0.1.5")

    if args.identity_only:
        passed, detail = verify_release_identity(os.path.abspath(installed_dir))
        return _print_summary([("Release Byte Identity", passed, detail)], args.json)
    if args.owned_install_only:
        passed, detail = verify_owned_install(os.path.abspath(installed_dir))
        return _print_summary([("Owned Install Closure", passed, detail)], args.json)
    return run_diagnostics(installed_dir, prefix_dir=args.prefix, json_output=args.json)


if __name__ == "__main__":
    sys.exit(main())
