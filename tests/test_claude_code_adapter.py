#!/usr/bin/env python3
"""Standalone tests for the retained Claude Code presentation hooks.

Host permissions, execution, sandboxing, and notifications belong to Claude
Code.  These tests cover only the bounded Japanese context emitted by UME.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADAPTER_DIR = os.path.join(ROOT_DIR, "adapters", "claude-code")

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")
        assert condition, f"{name}: {detail}"


def run_hook(name: str, payload: dict) -> subprocess.CompletedProcess:
    hook_path = os.path.join(_ADAPTER_DIR, name)
    return subprocess.run(
        [sys.executable, hook_path],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def test_permission_request_hook() -> None:
    print("\n[Permission Request Hook] PermissionRequest で日本語バナーだけを表示する")
    proc = run_hook("permission_request_hook.py", {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin feature-x"},
    })
    check("PermissionRequest hook -> exit 0", proc.returncode == 0)
    check("PermissionRequest stdout is JSON", proc.stdout.lstrip().startswith("{"), f"stdout={proc.stdout!r}")
    output = json.loads(proc.stdout)
    check("PermissionRequest outputs bounded Japanese context", "ここからPCの外へ出ます" in output["systemMessage"] and "外部送信" in output["systemMessage"])
    check("PermissionRequest emits no native permission decision", "hookSpecificOutput" not in output)
    check("PermissionRequest emits no legacy terminal sequence", set(output) == {"systemMessage"}, repr(output))
    check("PermissionRequest success stderr is empty", proc.stderr == "", f"stderr={proc.stderr!r}")

    secret_proc = run_hook("permission_request_hook.py", {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "curl -H 'Authorization: Bearer super-secret' https://example.com"},
    })
    secret_output = json.loads(secret_proc.stdout)
    check("PermissionRequest presentation omits raw secret-bearing input", "super-secret" not in json.dumps(secret_output, ensure_ascii=False))


def test_posttooluse_failure_hook() -> None:
    print("\n[PostToolUse Failure Hook] 失敗時に事実ベースの日本語解説を表示する")
    proc = run_hook("posttooluse_failure_hook.py", {
        "hook_event_name": "PostToolUseFailure",
        "error": "Exit code 127\n/bin/sh: command not found: unknown_bin",
        "is_interrupt": False,
        "duration_ms": 50,
    })
    check("PostToolUseFailure hook -> exit 0", proc.returncode == 0)
    check("PostToolUseFailure stdout is JSON", proc.stdout.lstrip().startswith("{"), f"stdout={proc.stdout!r}")
    output = json.loads(proc.stdout)
    check("PostToolUseFailure parses native exit code", "終了コード: 127" in output["systemMessage"])
    check("PostToolUseFailure outputs truthful status", "途中で失敗しました" in output["systemMessage"] and "変更状態を確認" in output["systemMessage"])
    hook_output = output.get("hookSpecificOutput", {})
    check("PostToolUseFailure event name is canonical", hook_output.get("hookEventName") == "PostToolUseFailure")
    check("PostToolUseFailure adds Claude context", hook_output.get("additionalContext") == output["systemMessage"])
    check("PostToolUseFailure success stderr is empty", proc.stderr == "", f"stderr={proc.stderr!r}")


def main() -> None:
    test_permission_request_hook()
    test_posttooluse_failure_hook()
    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
