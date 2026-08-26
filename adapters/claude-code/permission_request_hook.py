#!/usr/bin/env python3
"""permission_request_hook.py — Claude Code PermissionRequest Hook Adapter.

Triggered immediately before Claude Code prompts the user for manual permission approval.
Renders full, structured Japanese explanations with clear locality and risk boundaries.
This module renders Presentation-only context; it never grants, denies, or consumes authority.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

import translation_konjac as konjac  # noqa: E402


_NOTIFICATION_PREFIX = "\x1b]777;notify;ume-harness;"
_NOTIFICATION_MESSAGES = {
    konjac.EffectLevel.READ_ONLY: "🇯🇵 閲覧操作の許可確認です。詳細はClaude Code画面をご確認ください。",
    konjac.EffectLevel.LOCAL_WRITE: "🇯🇵 PC内ファイル変更の許可確認です。詳細はClaude Code画面をご確認ください。",
    konjac.EffectLevel.TEST_EXECUTION: "🇯🇵 PC内テスト実行の許可確認です。詳細はClaude Code画面をご確認ください。",
    konjac.EffectLevel.EXTERNAL_TRANSMIT: "🇯🇵 外部送信・反映操作の許可確認です。詳細はClaude Code画面をご確認ください。",
    konjac.EffectLevel.DESTRUCTIVE: "🇯🇵 削除・破壊的操作の許可確認です。詳細はClaude Code画面をご確認ください。",
    konjac.EffectLevel.UNKNOWN: "🇯🇵 影響未判定の操作について許可確認が必要です。Claude Code画面をご確認ください。",
}


def _terminal_notification(effect_level: object) -> str:
    """Return a bounded OSC notification that never includes raw tool input."""
    summary = _NOTIFICATION_MESSAGES.get(
        effect_level,
        _NOTIFICATION_MESSAGES[konjac.EffectLevel.UNKNOWN],
    )
    return f"{_NOTIFICATION_PREFIX}{summary}\x07"


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    banner = ""
    notification = _terminal_notification(konjac.EffectLevel.UNKNOWN)
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
        notification = _terminal_notification(trans_res.effect_level)
    except Exception:
        banner = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🇯🇵 ⚠️ この操作の日本語解説を生成できませんでした\n"
            "   ❓ 解説生成失敗 / 影響: 未判定\n"
            "   詳細: 安全のため、表示されている技術コマンドを直接ご確認ください。\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    if banner:
        sys.stdout.write(json.dumps({
            "systemMessage": banner,
            "terminalSequence": notification,
        }, ensure_ascii=False) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
