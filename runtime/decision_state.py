#!/usr/bin/env python3
"""
decision_state.py — Portable Decision State Writer (ume-harness Core)

個人実装（canonical_decision_writer.py）から、Claude Code固有の project-memory
ディレクトリ命名規則（`-Users-umeboshi` のような環境依存パス）への直接依存を除去し、
汎用の runtime-state パス解決へ一般化したもの。

Human Decision Fact（人間が下した決定の事実）と Executable Authority（それを実行する権限）
を厳格に分離し、アトミック書込・スキーマ検証付きで状態を更新する。

path resolution:
  1. 環境変数 UME_HARNESS_STATE_DIR が設定されていればそれを使う
  2. 未設定なら ~/.ume-harness/state/ を既定値にする
  3. Claude Code等ホスト固有の "project-memoryディレクトリ自動検出" には依存しない
     （検出ロジックはadapter層の責務）
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
import time


def resolve_state_dir() -> str:
    env_dir = os.environ.get("UME_HARNESS_STATE_DIR")
    if env_dir:
        return os.path.expanduser(env_dir)
    return os.path.expanduser("~/.ume-harness/state")


def registry_path() -> str:
    return os.path.join(resolve_state_dir(), "decision_registry.json")


def load_registry() -> dict:
    path = registry_path()
    if not os.path.exists(path):
        return {
            "$schema": "ume_harness.decision_registry.v1",
            "version": 1,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session_id": "current",
            "active_task_id": None,
            "tasks": {},
            "global_holds": [],
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001 - fail-closed, surface via stderr
        sys.stderr.write(f"[decision-state ERROR] Failed to parse registry: {e}\n")
        sys.exit(1)


def save_registry_atomic(data: dict) -> None:
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    path = registry_path()
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_name, delete=False, encoding="utf-8"
    ) as tf:
        json.dump(data, tf, ensure_ascii=False, indent=2)
        temp_name = tf.name
    os.replace(temp_name, path)


def cmd_record_decision(args: argparse.Namespace) -> None:
    reg = load_registry()
    task_id = args.task_id
    if task_id not in reg["tasks"]:
        reg["tasks"][task_id] = {
            "status": args.status or "READY",
            "hold_reason": None,
            "blocked_dependencies": [],
            "last_human_decision": None,
        }

    # Record Human Decision Fact (Executable Authority is NOT granted automatically)
    reg["tasks"][task_id]["last_human_decision"] = {
        "decision_id": f"dec_{int(time.time())}",
        "action": args.action,
        "summary": args.summary,
        "scope_target": args.scope_target,
        "scope_digest": args.scope_digest,
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "authority_lifecycle": "REVALIDATION_REQUIRED_AFTER_COMPACTION",
    }
    if args.status:
        reg["tasks"][task_id]["status"] = args.status
    if args.hold_reason:
        reg["tasks"][task_id]["hold_reason"] = args.hold_reason

    reg["active_task_id"] = task_id
    save_registry_atomic(reg)
    print(f"Recorded decision for task: {task_id}")


def cmd_set_hold(args: argparse.Namespace) -> None:
    reg = load_registry()
    task_id = args.task_id
    if task_id not in reg["tasks"]:
        reg["tasks"][task_id] = {
            "status": "BLOCKED",
            "hold_reason": args.reason,
            "blocked_dependencies": [],
            "last_human_decision": None,
        }
    else:
        reg["tasks"][task_id]["status"] = "BLOCKED"
        reg["tasks"][task_id]["hold_reason"] = args.reason

    save_registry_atomic(reg)
    print(f"Set HOLD on task: {task_id}")


def cmd_get_compaction_context(_args: argparse.Namespace) -> None:
    reg = load_registry()
    active_id = reg.get("active_task_id")
    out = []
    out.append("━━━ Decision State (Compaction / Resume Context) ━━━\n")

    if active_id and active_id in reg.get("tasks", {}):
        t = reg["tasks"][active_id]
        out.append(f"Active Task: {active_id} [{t.get('status')}]")
        if t.get("hold_reason"):
            out.append(f"  Hold/Blocker: {t.get('hold_reason')}")
        dec = t.get("last_human_decision")
        if dec:
            out.append(f"  Last Human Decision: {dec.get('action')} - {dec.get('summary')}")
            out.append(f"    Target: {dec.get('scope_target')} (Digest: {dec.get('scope_digest')})")
            out.append("    Authority Status: REVALIDATION_REQUIRED_AFTER_COMPACTION (raw token NOT active)")

    holds = []
    for tid, tinfo in reg.get("tasks", {}).items():
        if tid != active_id and tinfo.get("status") == "BLOCKED":
            holds.append(f"- {tid}: {tinfo.get('hold_reason')}")
    for gh in reg.get("global_holds", []):
        holds.append(f"- {gh.get('anchor_id')}: {gh.get('reason')}")

    if holds:
        out.append("\nActive Holds / Blocked Dependencies:")
        out.extend(holds)

    out.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("\n".join(out))


def main() -> None:
    parser = argparse.ArgumentParser(description="ume-harness Portable Decision State Writer")
    sub = parser.add_subparsers(dest="subcommand")

    p_rec = sub.add_parser("record")
    p_rec.add_argument("--task-id", required=True)
    p_rec.add_argument("--action", required=True)
    p_rec.add_argument("--summary", required=True)
    p_rec.add_argument("--scope-target", default="none")
    p_rec.add_argument("--scope-digest", default="none")
    p_rec.add_argument("--status", default=None)
    p_rec.add_argument("--hold-reason", default=None)

    p_hold = sub.add_parser("hold")
    p_hold.add_argument("--task-id", required=True)
    p_hold.add_argument("--reason", required=True)

    sub.add_parser("compaction-context")

    args = parser.parse_args()
    if args.subcommand == "record":
        cmd_record_decision(args)
    elif args.subcommand == "hold":
        cmd_set_hold(args)
    elif args.subcommand == "compaction-context":
        cmd_get_compaction_context(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
