#!/usr/bin/env python3
"""posttooluse_failure_hook.py — Claude Code PostToolUseFailure Hook Adapter.

Triggered when a tool execution fails. Renders truthful, non-fabricating Japanese explanations
clarifying that the execution failed, that partial state changes are unconfirmed without check,
and recommending next verification steps (e.g. git status).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
import re

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

import common_language_pack as pack  # noqa: E402


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    banner = ""
    try:
        data = json.loads(raw)
    except Exception:
        return 0

    try:
        error_msg = data.get("error", "") or data.get("tool_response", {}).get("stderr", "")
        is_interrupt = bool(data.get("is_interrupt", False))
        
        # Native CC PostToolUseFailure schema embeds "Exit code N" in error string
        m = re.search(r"Exit code ([0-9]{1,3})(?![0-9])", error_msg)
        exit_code = m.group(1) if m else None
        tool_name = data.get("tool_name")

        if is_interrupt:
            tmpl = pack.JA_CONCEPT_PACK.get("error.interrupted", {})
            headline = tmpl.get("headline", "🛑 処理が途中で中断されました")
            badge = tmpl.get("badge", "⏹️ 中断 / 処理未完了")
        else:
            tmpl = pack.JA_CONCEPT_PACK.get("error.command_failed", {})
            if exit_code is not None:
                headline = tmpl.get("headline", "🔴 コマンドの実行が途中で失敗しました（終了コード: {exit_code}）").format(exit_code=exit_code)
            else:
                headline = "🔴 ツールの処理に失敗しました"
            badge = tmpl.get("badge", "⚠️ 処理未完了 / 変更状態を確認してください")

        # Error bodies may contain command text, credentials or customer data.
        # Omit them wholesale; even truncation or pattern redaction can leak.
        explanation = (
            "処理は完了していません。一部の変更が発生したかは、この表示だけでは判断できません。\n"
            "   現在のファイルの変更状態を確認してください。\n"
            "   エラー本文は再掲しません。詳細はClaude Code本体のエラー表示を確認してください。"
        )

        # Only exact built-in read/search names get read-only guidance. Never
        # echo an untrusted tool name or infer a process exit from a file error.
        if tool_name in ("Read", "Grep", "Glob"):
            operation = "読み取り" if tool_name == "Read" else "検索"
            headline = f"🔴 {operation}に失敗しました" if not is_interrupt else f"🛑 {operation}が中断されました"
            badge = f"⚠️ {operation}未完了"
            explanation = (
                f"{operation}結果を取得できませんでした。対象の指定やアクセス権限を確認してください。\n"
                "   エラー本文は再掲しません。詳細はClaude Code本体のエラー表示を確認してください。"
            )

        banner = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🇯🇵 {headline}\n"
            f"   {badge}\n"
            f"   詳細: {explanation}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    except Exception:
        # Fail-visible translation fallback
        banner = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🇯🇵 ⚠️ エラー解説の生成に失敗しました（Claude Code本体のエラー表示をご確認ください）\n"
            "   ❓ 解説生成失敗 / 影響: 未判定\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    if banner:
        sys.stdout.write(
            json.dumps(
                {
                    "systemMessage": banner,
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUseFailure",
                        "additionalContext": banner,
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
