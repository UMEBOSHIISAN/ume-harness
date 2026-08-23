#!/usr/bin/env python3
"""
health_check.py — Environment & Installation Diagnostics for ume-harness

Operates on an INSTALLED package prefix (not repository dev state).
Validates:
1. Python version >= 3.9
2. Exact 30 generic install payload components existence and permissions
3. package_manifest.json integrity
4. Executable CLI entrypoint
5. Runtime module import isolation from installed lib
6. 15-artifact operational closure verification using installed domain_descriptor.json
7. Standard adapter assets presence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys


EXPECTED_ROOT_DIGEST = "bf87e3a39be5d928e4c4e3985225411f17dee9d9cae5e86c97a5152650fea065"

CLOSURE_15_FILES = [
    "domain_descriptor.json",
    "contracts/authority_contract.md",
    "contracts/tool_policy.md",
    "contracts/autonomous_stop.md",
    "contracts/task_intake.md",
    "runtime/local_execution_gate.py",
    "runtime/local_execution_lease.py",
    "runtime/local_execution_lease_state.py",
    "runtime/tool_policy.py",
    "runtime/decision_state.py",
    "runtime/human_layer_adapter.py",
    "runtime/stop_adapter.py",
    "runtime/activation_updater.py",
    "adapters/claude-code/lease_gate_runner.py",
    "adapters/claude-code/pretooluse_hook.py",
]


def run_diagnostics(installed_dir: str, prefix_dir: str | None = None, json_output: bool = False) -> int:
    installed_dir = os.path.abspath(installed_dir)
    if prefix_dir:
        prefix_dir = os.path.abspath(prefix_dir)
    else:
        prefix_dir = os.path.dirname(os.path.dirname(os.path.dirname(installed_dir)))

    checks: list[tuple[str, bool, str]] = []

    # 1. Python version >= 3.9
    py_ver = sys.version_info
    py_ok = py_ver >= (3, 9)
    checks.append(("Python >= 3.9", py_ok, f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"))

    # 2. Installed directory exists
    dir_ok = os.path.isdir(installed_dir)
    checks.append(("Installed Directory Exists", dir_ok, installed_dir))
    if not dir_ok:
        _print_summary(checks, json_output)
        return 1

    # 3. package_manifest.json and declared payload
    manifest_path = os.path.join(installed_dir, "package_manifest.json")
    manifest_ok = os.path.isfile(manifest_path)
    payload_files: list[str] = []
    if manifest_ok:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                mdata = json.load(f)
            payload_files = mdata.get("install_payload", [])
            manifest_ok = len(payload_files) == 30
        except Exception as e:
            manifest_ok = False
            checks.append(("Package Manifest Integrity", False, f"Error reading manifest: {e}"))
    checks.append(("Package Manifest (30 payload files)", manifest_ok, f"{len(payload_files)} declared files"))

    # 4. Check all 30 payload files exist
    missing_files = []
    for rel in payload_files:
        fpath = os.path.join(installed_dir, rel)
        if not os.path.exists(fpath):
            missing_files.append(rel)
    payload_ok = (len(missing_files) == 0 and len(payload_files) == 30)
    detail_payload = f"All {len(payload_files)} present" if payload_ok else f"Missing: {missing_files}"
    checks.append(("30-File Generic Payload Complete", payload_ok, detail_payload))

    # 5. Executable CLI entrypoint
    cli_candidates = [
        os.path.join(prefix_dir, "bin", "ume-harness"),
        os.path.join(installed_dir, "bin", "ume-harness"),
    ]
    cli_ok = False
    cli_found = "None"
    for cand in cli_candidates:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            cli_ok = True
            cli_found = cand
            break
    checks.append(("CLI Executable Entrypoint", cli_ok, cli_found))

    # 6. Runtime Module Import Isolation
    import_ok = False
    import_detail = ""
    try:
        sub_env = os.environ.copy()
        sub_env["PYTHONPATH"] = f"{os.path.join(installed_dir, 'runtime')}:{os.path.join(installed_dir, 'ux', 'japanese-human-layer')}"
        trace_code = """
import sys
import local_execution_gate
import tool_policy
import human_layer_adapter
import stop_adapter
import activation_updater
print("IMPORT_OK")
"""
        proc = subprocess.run(
            [sys.executable, "-c", trace_code],
            env=sub_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and "IMPORT_OK" in proc.stdout:
            import_ok = True
            import_detail = "Imported cleanly from installed prefix"
        else:
            import_detail = f"Failed: {proc.stderr[:200]}"
    except Exception as e:
        import_detail = f"Exception: {e}"
    checks.append(("Runtime Module Import Isolation", import_ok, import_detail))

    # 7. Operational Closure & Source Identity Verification
    closure_ok = False
    closure_detail = ""
    closure_14 = [f for f in CLOSURE_15_FILES if f != "domain_descriptor.json"]
    source_missing = [f for f in closure_14 if not os.path.exists(os.path.join(installed_dir, f))]
    if source_missing:
        closure_detail = f"Missing source closure files: {source_missing}"
    else:
        domain_desc = os.path.join(installed_dir, "domain_descriptor.json")
        if os.path.exists(domain_desc):
            try:
                mapping = {}
                for rel in CLOSURE_15_FILES:
                    p = os.path.join(installed_dir, rel)
                    with open(p, "rb") as fh:
                        mapping[rel] = hashlib.sha256(fh.read()).hexdigest()
                can = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                calc_root = hashlib.sha256(can).hexdigest()
                if calc_root == EXPECTED_ROOT_DIGEST:
                    closure_ok = True
                    closure_detail = f"Standard 15-Artifact Root Matches: {calc_root[:16]}..."
                else:
                    closure_ok = False
                    closure_detail = f"Root Digest Mismatch: expected {EXPECTED_ROOT_DIGEST[:16]}..., got {calc_root[:16]}..."
            except Exception as e:
                closure_ok = False
                closure_detail = f"Closure error: {e}"
        else:
            closure_ok = False
            closure_detail = "Missing domain_descriptor.json in installed runtime"
    checks.append(("Operational Closure & Source Identity", closure_ok, closure_detail))

    # 8. Standard Adapter Assets
    adapter_files = [
        "adapters/claude-code/lease_gate_runner.py",
        "adapters/claude-code/pretooluse_hook.py",
        "adapters/claude-code/settings.json.fragment",
        "adapters/claude-code/README.md",
    ]
    adapter_missing = [a for a in adapter_files if not os.path.exists(os.path.join(installed_dir, a))]
    adapters_ok = (len(adapter_missing) == 0)
    checks.append(("Standard Adapter Assets (Assets Only)", adapters_ok, "All present" if adapters_ok else f"Missing: {adapter_missing}"))

    return _print_summary(checks, json_output)


def _print_summary(checks: list[tuple[str, bool, str]], json_output: bool) -> int:
    all_passed = all(c[1] for c in checks)
    if json_output:
        res = {
            "all_passed": all_passed,
            "checks": [{"name": c[0], "passed": c[1], "detail": c[2]} for c in checks],
        }
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("=== Umeboshi Harness Installation Health Check ===")
        for name, passed, detail in checks:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"[{status}] {name:<35} : {detail}")
        print("=" * 55)
        if all_passed:
            print("🎉 All diagnostics PASSED! Installed harness is verified GREEN.")
        else:
            print("⚠️ Diagnostic failures found. Installation is incomplete or degraded.")
    return 0 if all_passed else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostics for installed ume-harness package")
    parser.add_argument("--installed-dir", default=None, help="Path to installed version directory (e.g. ~/.local/lib/ume-harness/v0.1.0)")
    parser.add_argument("--prefix", default=None, help="Installation prefix (e.g. ~/.local)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args(argv)

    installed_dir = args.installed_dir
    if not installed_dir:
        self_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isfile(os.path.join(self_parent, "domain_descriptor.json")) or os.path.isfile(os.path.join(self_parent, "package_manifest.json")):
            installed_dir = self_parent
        else:
            prefix = args.prefix or os.path.expanduser("~/.local")
            installed_dir = os.path.join(prefix, "lib", "ume-harness", "v0.1.0")

    return run_diagnostics(installed_dir, prefix_dir=args.prefix, json_output=args.json)


if __name__ == "__main__":
    sys.exit(main())
