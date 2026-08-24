#!/usr/bin/env python3
"""posttooluse_failure_hook.py — Claude Code PostToolUseFailure Hook Adapter.

Triggered when a tool execution fails. Renders truthful, non-fabricating Japanese explanations
clarifying that the execution failed, that partial state changes are unconfirmed without check,
and recommending next verification steps (e.g. git status).
"""

from __future__ import annotations

import json
import os
import re
import sys

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

import common_language_pack as pack  # noqa: E402


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        data = json.loads(raw)
    except Exception:
        return 0

    try:
        error_msg = data.get("error", "") or data.get("tool_response", {}).get("stderr", "")
        is_interrupt = bool(data.get("is_interrupt", False))
        
        # Native CC PostToolUseFailure schema embeds "Exit code N" in error string
        m = re.search(r"Exit code (\d+)", error_msg)
        exit_code = m.group(1) if m else "UNKNOWN"

        if is_interrupt:
            tmpl = pack.JA_CONCEPT_PACK.get("error.interrupted", {})
            headline = tmpl.get("headline", "🛑 処理が途中で中断されました")
            badge = tmpl.get("badge", "⏹️ 中断 / 処理未完了")
            explanation = tmpl.get("explanation", "処理が途中で停止しました。")
        else:
            tmpl = pack.JA_CONCEPT_PACK.get("error.command_failed", {})
            headline = tmpl.get("headline", "🔴 コマンドの実行が途中で失敗しました（終了コード: {exit_code}）").format(exit_code=exit_code)
            badge = tmpl.get("badge", "⚠️ 処理未完了 / 変更状態を確認してください")
            detail = error_msg.strip()[:140] + ("..." if len(error_msg.strip()) > 140 else "") if error_msg else "詳細エラーなし"
            explanation = tmpl.get("explanation", "").format(error_detail=detail)

        banner = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🇯🇵 {headline}\n"
            f"   {badge}\n"
            f"   詳細: {explanation}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        sys.stderr.write(banner)
    except Exception:
        # Fail-visible translation fallback
        sys.stderr.write(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🇯🇵 ⚠️ エラー解説の生成に失敗しました（技術エラー表示をご確認ください）\n"
            "   ❓ 解説生成失敗 / 影響: 未判定\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
