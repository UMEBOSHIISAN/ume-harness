#!/usr/bin/env python3
"""Canonical Claude Code Lease Gate Runner & Authenticated Verifier.

Single Source of Truth for Claude Code enforcement:
1. Validates authenticated protected-runtime closure against activation root digest.
2. Evaluates atomic activation state (disabled / canary / active).
3. Enforces read and write scope escape rules under active LocalExecutionLease.
4. Enforces control-plane protection (<worktree>/.ume-harness/**).
5. Enforces deterministic side effect classification (Bash shell composition & injection protection).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
from typing import Any

# Add runtime directory to sys.path
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

import local_execution_gate as leg  # noqa: E402
import local_execution_lease_state as lels  # noqa: E402
import tool_policy as tp  # noqa: E402

_DESTRUCTIVE_CMD_RE = re.compile(r"\b(rm\s+-[rf]+\w*|git\s+reset\s+--hard|drop\s+table|mkfs)\b", re.IGNORECASE)
_EXTERNAL_CMD_RE = re.compile(r"\b(ssh\s|git\s+push|curl\s+[^|]*-[Xd]|curl\s+[^|]*--data)\b", re.IGNORECASE)

_DISALLOWED_SHELL_CHARS = set(";&|`$><\n\r")
_SAFE_COMMANDS = {"ls", "pwd", "cat", "head", "tail", "wc"}
_SAFE_GIT_SUBCOMMANDS = {"status", "diff", "log", "branch", "show"}

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


def _emit(decision: str, reason: str, violation_code: str | None = None, lease_id: str | None = None) -> int:
    result = {
        "decision": decision,
        "reason": reason,
        "violation_code": violation_code,
        "lease_id": lease_id,
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def compute_closure_root_digest(install_dir: str) -> tuple[str | None, str | None]:
    mapping: dict[str, str] = {}
    for rel_f in CLOSURE_FILES:
        p = os.path.join(install_dir, rel_f)
        if not os.path.exists(p):
            return None, f"MISSING_CLOSURE_FILE:{rel_f}"
        with open(p, "rb") as f:
            mapping[rel_f] = hashlib.sha256(f.read()).hexdigest()

    can_bytes = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(can_bytes).hexdigest(), None


def is_safe_readonly_command(cmd_str: str) -> bool:
    s = cmd_str.strip()
    if not s:
        return False
    if any(c in _DISALLOWED_SHELL_CHARS for c in s):
        return False
    try:
        tokens = shlex.split(s)
    except Exception:
        return False
    if not tokens:
        return False
    base_cmd = tokens[0]
    if base_cmd in _SAFE_COMMANDS:
        return True
    if base_cmd == "git" and len(tokens) >= 2:
        subcmd = tokens[1]
        if subcmd in _SAFE_GIT_SUBCOMMANDS:
            if not any(t.startswith(("--output", "-o")) for t in tokens[2:]):
                return True
    return False


def classify_side_effect(tool_name: str, tool_input: dict) -> tp.SideEffect:
    if tool_name in ("Glob", "Grep", "WebSearch", "Read"):
        return tp.SideEffect.READ_ONLY
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return tp.SideEffect.BOUNDED_WRITE
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if _DESTRUCTIVE_CMD_RE.search(cmd):
            return tp.SideEffect.DESTRUCTIVE
        if _EXTERNAL_CMD_RE.search(cmd):
            return tp.SideEffect.EXTERNAL_MUTATION
        if is_safe_readonly_command(cmd):
            return tp.SideEffect.READ_ONLY
        return tp.SideEffect.UNKNOWN
    if tool_name in ("WebFetch", "SendMessage"):
        return tp.SideEffect.EXTERNAL_MUTATION
    return tp.SideEffect.UNKNOWN


def get_active_lease_worktree(state_store: lels.LeaseStateStore | None) -> str | None:
    """Returns the worktree_realpath of any active lease in the store, or None if no active lease exists."""
    if state_store is None:
        return None
    try:
        with state_store._locked_document() as doc:
            now = state_store._now()
            state_store._expire_due(doc, now)
            for raw in doc.get("leases", []):
                if raw.get("lifecycle") == lels.LeaseLifecycle.ACTIVE.value:
                    return raw.get("worktree_realpath")
    except Exception:
        pass
    return None


def default_domain_resolver(real_path: str) -> leg.ManagedExecutionDomain | None:
    """Discovers .ume-harness/domain.json upwards from real_path."""
    curr = real_path if os.path.isdir(real_path) else os.path.dirname(real_path)
    while curr and curr != "/":
        desc = os.path.join(curr, ".ume-harness", "domain.json")
        if os.path.exists(desc):
            try:
                with open(desc, "r", encoding="utf-8") as f:
                    d = json.load(f)
                return leg.ManagedExecutionDomain(
                    repository=d.get("repository", os.path.basename(curr)),
                    worktree_realpath=os.path.realpath(d.get("worktree_realpath", curr)),
                    management_mode=d.get("management_mode", "lease"),
                    policy_id=d.get("policy_id", "ume-harness-site-policy-v0"),
                    policy_sha256=d.get("policy_sha256", ""),
                )
            except Exception:
                return None
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return None


def check_read_scope_escape(tool_name: str, tool_input: dict, active_worktree: str) -> str | None:
    """Checks if a read tool or bash read command targets files outside the active lease worktree."""
    if tool_name in ("Read", "Glob", "Grep"):
        target = tool_input.get("file_path") or tool_input.get("filePath") or tool_input.get("path")
        if target:
            real_target = os.path.realpath(os.path.abspath(target))
            if not leg._is_path_inside(real_target, active_worktree):
                return f"read target path escapes active lease worktree boundary ({active_worktree})"
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        try:
            tokens = shlex.split(cmd.strip())
        except Exception:
            return None
        if not tokens:
            return None
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            target = token if os.path.isabs(token) else os.path.join(active_worktree, token)
            real_target = os.path.realpath(os.path.abspath(target))
            if not leg._is_path_inside(real_target, active_worktree):
                return f"command argument '{token}' escapes active lease worktree boundary ({active_worktree})"
    return None


def evaluate_invocation(
    data: dict,
    gate: leg.LocalExecutionGate | None = None,
    install_dir: str | None = None,
    state_dir: str | None = None,
) -> tuple[int, str | None]:
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    state_dir = state_dir or os.environ.get("UME_HARNESS_STATE_DIR") or os.path.expanduser("~/.ume-harness/state")
    install_dir = install_dir or os.environ.get("UME_HARNESS_INSTALL_DIR") or _PKG_ROOT

    # 1. Verification of activation & closure integrity if activation state exists
    activation_file = os.path.join(state_dir, "activation.json")
    if os.path.exists(activation_file):
        try:
            with open(activation_file, "r", encoding="utf-8") as af:
                act = json.load(af)
            act_mode = act.get("mode", "disabled")
            if act_mode == "disabled":
                return 2, "[ume-harness Lease Gate] lease gate is disabled by administrator (DISABLED_BY_ADMIN)\n"
            if act_mode not in ("canary", "active"):
                return 2, f"[ume-harness Lease Gate] unsupported activation mode: {act_mode} (UNSUPPORTED_ACTIVATION_MODE)\n"
            expected_root = act.get("runtime_root_digest")
            if expected_root and os.path.exists(install_dir):
                actual_root, err = compute_closure_root_digest(install_dir)
                if err or actual_root != expected_root:
                    return 2, f"[ume-harness Lease Gate] runtime tamper or digest mismatch detected (ACTIVATION_TAMPER)\n"
        except Exception as e:
            return 2, f"[ume-harness Lease Gate] activation error: {e} (ACTIVATION_ERROR)\n"

    if gate is None:
        try:
            gate = leg.create_default_gate(domain_resolver=default_domain_resolver)
        except Exception:
            gate = None

    active_worktree = get_active_lease_worktree(gate._state_store) if gate is not None else None

    # 2. Read scope escape check under active lease
    if active_worktree is not None and tool_name in ("Read", "Glob", "Grep", "Bash"):
        escape_reason = check_read_scope_escape(tool_name, tool_input, active_worktree)
        if escape_reason is not None:
            return 2, f"[ume-harness Lease Gate] {escape_reason} (SCOPE_ESCAPE)\n"

    # 3. Gate evaluation for Edit/Write/NotebookEdit
    if tool_name in ("Edit", "Write", "NotebookEdit") and gate is not None:
        file_path = tool_input.get("file_path") or tool_input.get("filePath") or tool_input.get("notebook_path")
        if file_path:
            action = leg.GateAction.WRITE if tool_name == "Write" else leg.GateAction.EDIT
            gate_res = gate.evaluate_request(file_path, action)
            if gate_res.decision == leg.GateDecision.ALLOW:
                return 0, None
            if gate_res.decision == leg.GateDecision.DENY:
                return 2, f"[ume-harness Lease Gate] {gate_res.reason} ({gate_res.violation_code})\n"
            if gate_res.decision == leg.GateDecision.NOT_APPLICABLE:
                if active_worktree is not None:
                    return 2, f"[ume-harness Lease Gate] target path escapes active lease worktree boundary ({active_worktree}) (SCOPE_ESCAPE)\n"

    side_effect = classify_side_effect(tool_name, tool_input)
    decision = tp.decide(tp.Tier.TIER_NORMAL, side_effect)

    if decision == tp.Decision.ALLOW:
        return 0, None

    return 2, f"[ume-harness] このツール呼び出し（{tool_name}）は {side_effect.value} に分類され、承認が必要です。\n"


def evaluate_host_path(
    target_path: str,
    action: str = "edit",
    install_dir: str | None = None,
    state_dir: str | None = None,
    worktrees_root: str | None = None,
) -> int:
    """CLI evaluation wrapper for single host path (backwards compatibility)."""
    tool_name = "Write" if action == "write" else "Edit"
    code, err = evaluate_invocation(
        {"tool_name": tool_name, "tool_input": {"file_path": target_path}},
        install_dir=install_dir,
        state_dir=state_dir,
    )
    if code == 0:
        return _emit("ALLOW", "execution allowed under active lease")
    return _emit("DENY", err.strip() if err else "execution denied", "DENIED")


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Code Lease Gate Runner")
    parser.add_argument("--evaluate-path", help="Target file path to evaluate")
    parser.add_argument("--action", default="edit", help="Action string (edit or write)")
    parser.add_argument("--install-dir", help="Override installed runtime directory")
    parser.add_argument("--state-dir", help="Override state directory")
    parser.add_argument("--worktrees-root", help="Override worktrees root directory")
    args = parser.parse_args()

    if args.evaluate_path:
        return evaluate_host_path(
            target_path=args.evaluate_path,
            action=args.action,
            install_dir=args.install_dir,
            state_dir=args.state_dir,
            worktrees_root=args.worktrees_root,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
