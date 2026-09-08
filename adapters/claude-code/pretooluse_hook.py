#!/usr/bin/env python3
"""pretooluse_hook.py — Thin Claude Code PreToolUse Host I/O Adapter.

Contract:
1. Reads stdin JSON {"tool_name": "...", "tool_input": {...}, ...}
2. Delegates invocation evaluation to the canonical authenticated lease_gate_runner.
3. Sets process exit code:
   - 0 without a permission verdict for defer
   - 0 with structured PreToolUse JSON for ask / deny
   - 2 for evaluation errors (+ writes reason to stderr)
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
from typing import Any

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ADAPTER_DIR = os.path.join(_PKG_ROOT, "adapters", "claude-code")
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

import lease_gate_runner as runner  # noqa: E402
import translation_konjac as konjac  # noqa: E402


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
        sys.stderr.write(
            "[ume-harness pretooluse_hook] empty stdin rejected (INVALID_HOOK_INPUT)\n"
        )
        return 2
    try:
        data = json.loads(raw)
    except Exception as e:
        sys.stderr.write(f"[ume-harness pretooluse_hook] invalid JSON input: {e}\n")
        return 2

    # Evaluate exactly once. Presentation must never infer or alter this verdict.
    try:
        result = runner.evaluate_invocation_result(data)
        if (
            not isinstance(result.decision, str)
            or result.decision not in {"defer", "ask", "deny", "error"}
            or not isinstance(result.reason, str)
            or not isinstance(result.code, str)
        ):
            raise ValueError("invalid invocation result")
    except Exception as e:
        sys.stderr.write(f"[ume-harness pretooluse_hook] evaluation failed: {e}\n")
        return 2

    if result.decision == "error":
        sys.stderr.write(
            f"[ume-harness pretooluse_hook] {result.reason} ({result.code})\n"
        )
        return 2
    if result.decision == "defer":
        # Native permissions still apply. Avoid misleading Harness permission cards.
        return 0

    banner = ""

    # 1. Presentation-only Translation Konjac rendering.
    # This path never decides permission; the canonical result above is authoritative.
    try:
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        cwd = data.get("cwd", os.getcwd())
        
        trans_res = konjac.translate_tool_event(tool_name, tool_input, cwd)
        # PermissionRequest systemMessage output is accepted by Claude Code but may be
        # covered immediately by the interactive permission dialog.  Render the same
        # detailed, presentation-only card during PreToolUse for any operation that is
        # not read-only, without changing or pre-answering the host permission decision.
        permission_context = True
        banner = konjac.format_user_banner(trans_res, permission_context=permission_context)
    except Exception:
        banner = (
            "  ↳ 🇯🇵 ⚠️ この操作の日本語解説を生成できませんでした（影響: 未判定・技術表示をご確認ください）\n"
        )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": result.decision,
            "permissionDecisionReason": result.reason,
        },
    }
    if banner:
        output["systemMessage"] = banner
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
