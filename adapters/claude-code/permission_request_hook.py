#!/usr/bin/env python3
"""permission_request_hook.py — Claude Code PermissionRequest Hook Adapter.

Triggered immediately before Claude Code prompts the user for manual permission approval.
Renders full, structured Japanese explanations with clear locality and risk boundaries.
This module renders Presentation-only context; it never grants, denies, or consumes authority.
"""

from __future__ import annotations

import json
import os
import sys

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

import translation_konjac as konjac  # noqa: E402


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        data = json.loads(raw)
    except Exception:
        return 0

    try:
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        cwd = data.get("cwd", os.getcwd())
        
        trans_res = konjac.translate_tool_event(tool_name, tool_input, cwd)
        banner = konjac.format_user_banner(trans_res, permission_context=True)
        if banner:
            sys.stderr.write(banner)
    except Exception:
        sys.stderr.write(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🇯🇵 ⚠️ この操作の日本語解説を生成できませんでした\n"
            "   ❓ 解説生成失敗 / 影響: 未判定\n"
            "   詳細: 安全のため、表示されている技術コマンドを直接ご確認ください。\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
