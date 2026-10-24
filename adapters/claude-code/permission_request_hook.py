#!/usr/bin/env python3
"""Claude Code PermissionRequest presentation hook.

The hook adds bounded Japanese context to Claude Code's native permission
prompt.  It never grants, denies, consumes approval, or emits notifications.
"""

from __future__ import annotations

import json
import os
import sys

sys.dont_write_bytecode = True

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
    if not isinstance(data, dict):
        return 0

    try:
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        cwd = data.get("cwd", os.getcwd())
        trans_res = konjac.translate_tool_event(tool_name, tool_input, cwd)
        banner = konjac.format_user_banner(trans_res, permission_context=True)
    except Exception:
        banner = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🇯🇵 ⚠️ この操作の日本語解説を生成できませんでした\n"
            "   ❓ 解説生成失敗 / 影響: 未判定\n"
            "   詳細と権限確認はClaude Code本体の画面を参照してください。\n"
            "   この解説は許可・拒否を決定しません。\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    if banner:
        sys.stdout.write(json.dumps({"systemMessage": banner}, ensure_ascii=False) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
