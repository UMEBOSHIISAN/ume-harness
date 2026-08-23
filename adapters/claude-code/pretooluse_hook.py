#!/usr/bin/env python3
"""pretooluse_hook.py — Thin Claude Code PreToolUse Host I/O Adapter.

Contract:
1. Reads stdin JSON {"tool_name": "...", "tool_input": {...}, ...}
2. Delegates invocation evaluation to the canonical authenticated lease_gate_runner.
3. Sets process exit code:
   - 0 for ALLOW
   - 2 for DENY / APPROVAL_REQUIRED (+ writes reason to stderr)
"""

from __future__ import annotations

import json
import os
import sys

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ADAPTER_DIR = os.path.join(_PKG_ROOT, "adapters", "claude-code")
if _ADAPTER_DIR not in sys.path:
    sys.path.insert(0, _ADAPTER_DIR)

import lease_gate_runner as runner  # noqa: E402


def evaluate_invocation(
    data: dict,
    gate: Any = None,
    install_dir: str | None = None,
    state_dir: str | None = None,
) -> tuple[int, str | None]:
    """Compatibility delegate to canonical lease_gate_runner."""
    return runner.evaluate_invocation(data, gate=gate, install_dir=install_dir, state_dir=state_dir)


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        data = json.loads(raw)
    except Exception as e:
        sys.stderr.write(f"[ume-harness pretooluse_hook] invalid JSON input: {e}\n")
        return 2

    exit_code, error_msg = runner.evaluate_invocation(data)
    if error_msg:
        sys.stderr.write(error_msg)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
