#!/usr/bin/env python3
"""Canonical atomic activation state updater for LocalExecutionLease."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

def get_state_dir() -> str:
    return os.path.realpath(os.environ.get("UME_HARNESS_STATE_DIR") or os.path.expanduser("~/.ume-harness/state"))

STATE_DIR = get_state_dir()
ACTIVATION_FILE = os.path.join(STATE_DIR, "activation.json")
LOCK_FILE = os.path.join(STATE_DIR, "activation.lock")

VALID_MODES = {"disabled", "canary", "active"}
SCHEMA_VERSION = "local-execution-lease-activation.v0"
PINNED_POLICY_SHA256 = "4b7b686d08014a60124ad9024f0c4392e2ebf443b7f2f1fc4d88e8941cfb5443"

CLOSURE_FILES = [
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


class ActivationError(Exception):
    """Base error for activation state operations."""


class GenerationConflictError(ActivationError):
    """Raised when an expected generation mismatch occurs during CAS."""


def compute_installed_root_digest(install_dir: str | None = None) -> str:
    """Compute the canonical SHA-256 root digest of the explicit protected-runtime closure."""
    if install_dir is None:
        # Default to parent directory of runtime/
        install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mapping: dict[str, str] = {}
    for rel in CLOSURE_FILES:
        p = os.path.join(install_dir, rel)
        if not os.path.exists(p):
            raise ActivationError(f"missing closure file in protected runtime: {rel}")
        with open(p, "rb") as f:
            mapping[rel] = hashlib.sha256(f.read()).hexdigest()
    canonical_b = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_b).hexdigest()


def read_activation_state() -> dict[str, Any] | None:
    """Read and validate the current activation state file (read-only)."""
    if not os.path.exists(ACTIVATION_FILE):
        return None
    try:
        with open(ACTIVATION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data.get("schema") != SCHEMA_VERSION:
            return None
        if data.get("mode") not in VALID_MODES:
            return None
        return data
    except Exception:
        return None


def atomic_update_activation(
    new_mode: str,
    expected_generation: int | None = None,
    install_dir: str | None = None,
    policy_sha256: str = PINNED_POLICY_SHA256,
) -> int:
    """Atomically update the activation state under an exclusive lock with directory fsync."""
    if new_mode not in VALID_MODES:
        raise ActivationError(f"invalid activation mode: {new_mode}, expected one of {sorted(VALID_MODES)}")

    os.makedirs(STATE_DIR, exist_ok=True)
    runtime_root_digest = compute_installed_root_digest(install_dir)

    with open(LOCK_FILE, "w", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            current_gen = 0
            if os.path.exists(ACTIVATION_FILE):
                try:
                    with open(ACTIVATION_FILE, "r", encoding="utf-8") as f:
                        curr_data = json.load(f)
                        if isinstance(curr_data, dict):
                            current_gen = int(curr_data.get("generation", 0))
                except Exception:
                    current_gen = 0

            if expected_generation is not None and current_gen != expected_generation:
                raise GenerationConflictError(
                    f"CAS mismatch: expected generation {expected_generation}, found {current_gen}"
                )

            next_gen = current_gen + 1
            record = {
                "schema": SCHEMA_VERSION,
                "mode": new_mode,
                "generation": next_gen,
                "runtime_root_digest": runtime_root_digest,
                "policy_sha256": policy_sha256,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            tmp_path = os.path.join(STATE_DIR, f"activation.json.tmp.{os.getpid()}")
            with open(tmp_path, "w", encoding="utf-8") as tmp_f:
                json.dump(record, tmp_f, indent=2, ensure_ascii=False)
                tmp_f.write("\n")
                tmp_f.flush()
                os.fsync(tmp_f.fileno())

            os.replace(tmp_path, ACTIVATION_FILE)

            # Ensure parent directory entry is committed to storage
            dir_fd = os.open(STATE_DIR, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

            return next_gen
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: activation_updater.py <mode> [expected_gen]")
        sys.exit(1)
    mode = sys.argv[1]
    exp = int(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        gen = atomic_update_activation(mode, expected_generation=exp)
        print(f"ACTIVATION_UPDATED: mode={mode} generation={gen}")
    except Exception as exc:
        print(f"ACTIVATION_ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
