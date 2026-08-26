#!/usr/bin/env python3
"""
test_cli.py — bin/ume-harness の静的テスト（P0-1・Usability Closure）

LLM呼び出しを一切行わない（--llm-output-file相当の直接関数呼び出しのみ）。
render_report()の決定論的レンダリングと、headline_state導出の優先順位
（HELD > ASK > APPROVAL_REQUIRED > PREVIEW_COMPLETE）を検証する。
内部語彙（human_request_contract.md §3禁止リスト）が出力に含まれないことも検証する。
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))

_CLI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "ume-harness")
import importlib.util as _ilu  # noqa: E402
from importlib.machinery import SourceFileLoader as _SourceFileLoader  # noqa: E402
_loader = _SourceFileLoader("ume_harness_cli", _CLI_PATH)
_spec = _ilu.spec_from_loader("ume_harness_cli", _loader)
cli = _ilu.module_from_spec(_spec)
_loader.exec_module(cli)

import human_layer_adapter as hla  # noqa: E402
import tool_policy as tp  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")
        assert condition, f"{name}: {detail}"


FORBIDDEN_VOCAB = [
    "task_class", "risk_tags", "scope_digest", "authority_touch", "execution_effect",
    "canonical decision", "manifest", "HOLD", "classifier", "gate", "verification=PASS",
    "TIER_NORMAL", "SideEffect", "APPROVAL_REQUIRED",
]


def test_preview_complete_state_when_nothing_needs_approval():
    print("\n[headline] 質問なし・承認不要 → PREVIEW_COMPLETE")
    llm_output = {
        "work_type": "RESEARCH", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": ["資料を確認する"], "clarification_assessments": [],
    }
    result = hla.normalize(llm_output, tier=tp.Tier.TIER_NORMAL)
    report, headline = cli.render_report(result)
    check("headline == PREVIEW_COMPLETE", headline == "PREVIEW_COMPLETE", f"got {headline}")
    check("exit code 0", cli._EXIT_CODES[headline] == 0)


def test_ask_state_takes_priority_over_approval_required():
    print("\n[headline] 質問あり かつ 承認要求あり → ASK優先（バッチ提示の原則）")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["mutation_target"] = "true"
    a = {"question": "対象は何ですか？", "missing_information": "x", "impact": impact, "basis": {}}
    llm_output = {
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": ["ファイルを削除する"], "clarification_assessments": [a],
    }
    result = hla.normalize(llm_output, tier=tp.Tier.TIER_NORMAL)
    report, headline = cli.render_report(result)
    check("headline == ASK", headline == "ASK", f"got {headline}")
    check("質問と承認要求の両方が本文に含まれる（バッチ提示）",
          "対象は何ですか" in report and "ファイルを削除する" in report)


def test_approval_required_state_when_only_approvals_pending():
    print("\n[headline] 質問なし・承認要求あり → APPROVAL_REQUIRED")
    llm_output = {
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": ["先方にメールで送信する"], "clarification_assessments": [],
    }
    result = hla.normalize(llm_output, tier=tp.Tier.TIER_NORMAL)
    report, headline = cli.render_report(result)
    check("headline == APPROVAL_REQUIRED", headline == "APPROVAL_REQUIRED", f"got {headline}")
    check("exit code 2", cli._EXIT_CODES[headline] == 2)


def test_held_state_when_clarification_structurally_blocked():
    print("\n[headline] clarification_assessments欠落 → HELD（fail-safe）")
    llm_output = {
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [],
    }
    result = hla.normalize(llm_output, tier=tp.Tier.TIER_NORMAL)
    report, headline = cli.render_report(result)
    check("headline == HELD", headline == "HELD", f"got {headline}")
    check("exit code 3", cli._EXIT_CODES[headline] == 3)


def test_report_never_leaks_forbidden_vocabulary():
    print("\n[human_request_contract §3] 内部語彙が自然語レポートに一切出ない")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["destructive_effect"] = "true"
    a = {"question": "本当に消しますか？", "missing_information": "x", "impact": impact, "basis": {}}
    llm_output = {
        "work_type": "ORGANIZE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": ["ファイルを削除する", "先方に送信する", "資料を確認する"],
        "clarification_assessments": [a],
    }
    result = hla.normalize(llm_output, tier=tp.Tier.TIER_NORMAL)
    report, _ = cli.render_report(result)
    leaked = [w for w in FORBIDDEN_VOCAB if w in report]
    check("禁止語彙が0件", leaked == [], f"leaked={leaked}")


def test_tier_is_never_exposed_as_user_facing_argument():
    print("\n[P0-3] CLIのargparseにtier選択オプションが存在しない（内部固定・非公開）")
    proc = subprocess.run([sys.executable, _CLI_PATH, "--help"], capture_output=True, text=True)
    check("--tier オプションが存在しない", "--tier" not in proc.stdout)
    check("TIER という文字列がヘルプに出ない（内部語彙の露出防止）", "TIER" not in proc.stdout.upper() or "tier" not in proc.stdout.lower())


def test_cli_end_to_end_offline_via_subprocess():
    print("\n[E2E] --llm-output-file 経由でCLI全体をサブプロセスとして実行（API呼び出しなし）")
    import json
    import tempfile
    llm_output = {
        "work_type": "RESEARCH", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": ["資料を確認する"], "clarification_assessments": [],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(llm_output, tf, ensure_ascii=False)
        temp_path = tf.name
    try:
        proc = subprocess.run(
            [sys.executable, _CLI_PATH, "--llm-output-file", temp_path],
            capture_output=True, text=True,
        )
        check("exit code 0（PREVIEW_COMPLETE）", proc.returncode == 0, f"got {proc.returncode} stderr={proc.stderr[:200]}")
        check("自然語レポートが出力される", "依頼の内容整理" in proc.stdout)
    finally:
        os.unlink(temp_path)


def main():
    test_preview_complete_state_when_nothing_needs_approval()
    test_ask_state_takes_priority_over_approval_required()
    test_approval_required_state_when_only_approvals_pending()
    test_held_state_when_clarification_structurally_blocked()
    test_report_never_leaks_forbidden_vocabulary()
    test_tier_is_never_exposed_as_user_facing_argument()
    test_cli_end_to_end_offline_via_subprocess()

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
