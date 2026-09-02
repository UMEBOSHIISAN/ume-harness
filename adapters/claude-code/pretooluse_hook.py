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

import sys

sys.dont_write_bytecode = True

import json
import os

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

    banner = ""

    # 1. Presentation-only Translation Konjac rendering.
    # This path never decides permission; the canonical gate below is evaluated independently.
    try:
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        cwd = data.get("cwd", os.getcwd())
        permission_mode = data.get("permission_mode", "auto")
        
        trans_res = konjac.translate_tool_event(tool_name, tool_input, cwd)
        # PermissionRequest systemMessage output is accepted by Claude Code but may be
        # covered immediately by the interactive permission dialog.  Render the same
        # detailed, presentation-only card during PreToolUse for any operation that is
        # not read-only, without changing or pre-answering the host permission decision.
        permission_context = (
            permission_mode == "ask"
            or trans_res.effect_level != konjac.EffectLevel.READ_ONLY
        )
        banner = konjac.format_user_banner(trans_res, permission_context=permission_context)
    except Exception:
        banner = (
            "  ↳ 🇯🇵 ⚠️ この操作の日本語解説を生成できませんでした（影響: 未判定・技術表示をご確認ください）\n"
        )

    # 2. Canonical Safety Gate Evaluation
    exit_code, error_msg = runner.evaluate_invocation(data)
    if exit_code == 0 and banner:
        sys.stdout.write(json.dumps({"systemMessage": banner}, ensure_ascii=False) + "\n")
    elif banner:
        sys.stderr.write(banner)
    if error_msg:
        sys.stderr.write(error_msg)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
