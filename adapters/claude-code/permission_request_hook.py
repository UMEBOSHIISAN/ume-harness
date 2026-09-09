#!/usr/bin/env python3
"""permission_request_hook.py — Claude Code PermissionRequest Hook Adapter.

Triggered immediately before Claude Code prompts the user for manual permission approval.
Renders bounded Japanese explanations without repeating raw tool input.
This module renders Presentation-only context; it never grants, denies, or consumes authority.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
import subprocess

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

import translation_konjac as konjac  # noqa: E402


_MACOS_NOTIFICATION_ENV = "UME_HARNESS_MACOS_NOTIFICATIONS"
_MACOS_NOTIFIER_PATHS = (
    "/opt/homebrew/bin/terminal-notifier",
    "/usr/local/bin/terminal-notifier",
)
_MACOS_NOTIFICATION_TITLE = "UME-HARNESS 許可確認"
_MACOS_NOTIFICATION_BODY = (
    "Claude Codeが操作の許可を求めています。内容をCCの画面で確認し、"
    "許可または拒否を選んでください。この通知は承認を行いません。"
)


def _notify_macos() -> None:
    """Send one fixed opt-in notice without changing Claude Code authority."""
    if sys.platform != "darwin" or os.environ.get(_MACOS_NOTIFICATION_ENV) != "1":
        return

    try:
        notifier = next(
            (
                path
                for path in _MACOS_NOTIFIER_PATHS
                if os.path.isfile(path) and os.access(path, os.X_OK)
            ),
            None,
        )
        if notifier is None:
            return
        subprocess.run(
            [
                notifier,
                "-title",
                _MACOS_NOTIFICATION_TITLE,
                "-message",
                _MACOS_NOTIFICATION_BODY,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # A missing or unhealthy optional notifier must not affect CC's decision.
        return


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


def _terminal_title(effect_level: object) -> str:
    """Use a fixed, bounded title when a host drops the transcript message."""
    summary = _NOTIFICATION_MESSAGES.get(
        effect_level,
        _NOTIFICATION_MESSAGES[konjac.EffectLevel.UNKNOWN],
    ).split("。", 1)[0]
    return f"\x1b]2;{summary} | UME-HARNESS\x07"


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    banner = ""
    notification = _terminal_notification(konjac.EffectLevel.UNKNOWN)
    title = _terminal_title(konjac.EffectLevel.UNKNOWN)
    try:
        data = json.loads(raw)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0

    _notify_macos()

    try:
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        cwd = data.get("cwd", os.getcwd())
        
        trans_res = konjac.translate_tool_event(tool_name, tool_input, cwd)
        banner = konjac.format_user_banner(trans_res, permission_context=True)
        notification = _terminal_notification(trans_res.effect_level)
        title = _terminal_title(trans_res.effect_level)
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
        sys.stdout.write(json.dumps({
            "systemMessage": banner,
            "terminalSequence": notification + title,
        }, ensure_ascii=False) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
