#!/usr/bin/env python3
"""
test_portable_core.py — ume-harness Portable Core 静的テスト

Phase 2（静的テストのみ）。LLMは一切呼び出さない。
contracts/tool_policy.md・contracts/authority_contract.md・contracts/autonomous_stop.md の
仕様どおりに runtime/ が実装されているかを検証する。

japanese-human-layer の実LLM behavioral test（Phase 3）はここに含めない
（fixture整合性テストと実LLM挙動テストを混同しない、という監査結果を反映）。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))

import tool_policy as tp  # noqa: E402
import stop_adapter as sa  # noqa: E402

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


def test_tier_secrets_always_deny():
    print("\n[tool_policy] TIER_SECRETS は副作用クラスに関わらず一律DENY")
    for se in tp.SideEffect:
        d = tp.decide(tp.Tier.TIER_SECRETS, se)
        check(f"TIER_SECRETS x {se.value} = DENY", d == tp.Decision.DENY, f"got {d}")


def test_tier_constitution_readonly_allowed_else_deny():
    print("\n[tool_policy] TIER_CONSTITUTION は READ_ONLY のみ ALLOW、他は DENY")
    check(
        "READ_ONLY = ALLOW",
        tp.decide(tp.Tier.TIER_CONSTITUTION, tp.SideEffect.READ_ONLY) == tp.Decision.ALLOW,
    )
    for se in [tp.SideEffect.BOUNDED_WRITE, tp.SideEffect.DESTRUCTIVE, tp.SideEffect.AUTHORITY_TOUCH]:
        d = tp.decide(tp.Tier.TIER_CONSTITUTION, se)
        check(f"{se.value} = DENY", d == tp.Decision.DENY, f"got {d}")


def test_tier_runtime_code_no_forced_delegation():
    print("\n[tool_policy] TIER_RUNTIME_CODE の既定は explicit approval であり、DENY(delegate強制)ではない")
    d = tp.decide(tp.Tier.TIER_RUNTIME_CODE, tp.SideEffect.BOUNDED_WRITE)
    check(
        "BOUNDED_WRITE = APPROVAL_REQUIRED (not DENY)",
        d == tp.Decision.APPROVAL_REQUIRED,
        f"got {d} — human裁定(1)違反: delegate必須をCoreへ固定してはいけない",
    )


def test_unknown_side_effect_fail_closed():
    print("\n[tool_policy] 分類不能な操作は全Tierで APPROVAL_REQUIRED または DENY（無言のALLOWにはしない）")
    for tier in tp.Tier:
        d = tp.decide(tier, tp.SideEffect.UNKNOWN)
        check(
            f"{tier.value} x UNKNOWN != ALLOW",
            d != tp.Decision.ALLOW,
            f"got {d}",
        )


def test_classify_command_side_effect():
    print("\n[tool_policy] classify_command_side_effect() の動詞分類")
    check("rm -> DESTRUCTIVE", tp.classify_command_side_effect(["rm"]) == tp.SideEffect.DESTRUCTIVE)
    check("send -> EXTERNAL_MUTATION", tp.classify_command_side_effect(["send"]) == tp.SideEffect.EXTERNAL_MUTATION)
    check(
        "edit_settings -> AUTHORITY_TOUCH",
        tp.classify_command_side_effect(["edit_settings"]) == tp.SideEffect.AUTHORITY_TOUCH,
    )
    check("read -> READ_ONLY", tp.classify_command_side_effect(["read"]) == tp.SideEffect.READ_ONLY)
    check("(empty) -> UNKNOWN", tp.classify_command_side_effect([]) == tp.SideEffect.UNKNOWN)
    check("mystery_verb -> UNKNOWN", tp.classify_command_side_effect(["mystery_verb"]) == tp.SideEffect.UNKNOWN)


def test_token_store_consumes_single_earliest_token():
    print("\n[tool_policy] TokenStore.consume() は最も早く期限切れになる1件だけを消費する")
    with tempfile.TemporaryDirectory() as d:
        store_path = os.path.join(d, "tokens.json")
        now = int(time.time())
        import json

        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tokens": [
                        {"action": "impl_write", "scope_target": "a", "expires_epoch": now + 1000, "uses_remaining": 3},
                        {"action": "impl_write", "scope_target": "b", "expires_epoch": now + 10, "uses_remaining": 5},
                    ]
                },
                f,
            )
        store = tp.TokenStore(store_path)
        ok = store.consume("impl_write")
        check("consume() returns True when a valid token exists", ok is True)

        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        earliest = next(t for t in data["tokens"] if t["scope_target"] == "b")
        other = next(t for t in data["tokens"] if t["scope_target"] == "a")
        check(
            "earliest-expiring token was decremented",
            earliest["uses_remaining"] == 4,
            f"got {earliest['uses_remaining']}",
        )
        check(
            "other token untouched (no mass-decrement bug)",
            other["uses_remaining"] == 3,
            f"got {other['uses_remaining']}",
        )


def test_token_store_expired_token_not_consumed():
    print("\n[tool_policy] 期限切れトークンは消費されない")
    with tempfile.TemporaryDirectory() as d:
        store_path = os.path.join(d, "tokens.json")
        now = int(time.time())
        import json

        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(
                {"tokens": [{"action": "impl_write", "scope_target": "a", "expires_epoch": now - 10, "uses_remaining": 3}]},
                f,
            )
        store = tp.TokenStore(store_path)
        ok = store.consume("impl_write")
        check("consume() returns False for expired-only tokens", ok is False)


def test_decision_state_path_resolution():
    print("\n[decision_state] path resolution: env var優先・既定は ~/.ume-harness/state")
    import importlib
    ds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime")
    sys.path.insert(0, ds_path)
    import decision_state as ds
    importlib.reload(ds)

    old = os.environ.pop("UME_HARNESS_STATE_DIR", None)
    try:
        default_dir = ds.resolve_state_dir()
        check(
            "default resolves under ~/.ume-harness/state (no Claude-Code-specific slug)",
            default_dir == os.path.expanduser("~/.ume-harness/state"),
            f"got {default_dir}",
        )
        check(
            "no personal username-embedded segment (-Users- pattern) in default path",
            "-Users-" not in default_dir,
            f"got {default_dir}",
        )

        os.environ["UME_HARNESS_STATE_DIR"] = "/tmp/custom-ume-harness-state"
        custom_dir = ds.resolve_state_dir()
        check("env var override honored", custom_dir == "/tmp/custom-ume-harness-state", f"got {custom_dir}")
    finally:
        if old is not None:
            os.environ["UME_HARNESS_STATE_DIR"] = old
        else:
            os.environ.pop("UME_HARNESS_STATE_DIR", None)


def test_decision_state_record_and_read_roundtrip():
    print("\n[decision_state] record -> compaction-context のラウンドトリップ")
    with tempfile.TemporaryDirectory() as d:
        os.environ["UME_HARNESS_STATE_DIR"] = d
        try:
            import importlib
            ds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime")
            sys.path.insert(0, ds_path)
            import decision_state as ds
            importlib.reload(ds)

            reg = ds.load_registry()
            reg["tasks"]["t1"] = {
                "status": "READY",
                "hold_reason": None,
                "blocked_dependencies": [],
                "last_human_decision": {
                    "decision_id": "dec_1",
                    "action": "approve_edit",
                    "summary": "test",
                    "scope_target": "foo.md",
                    "scope_digest": "abc",
                    "issued_at": "now",
                    "authority_lifecycle": "REVALIDATION_REQUIRED_AFTER_COMPACTION",
                },
            }
            reg["active_task_id"] = "t1"
            ds.save_registry_atomic(reg)

            reloaded = ds.load_registry()
            check(
                "registry persists active_task_id",
                reloaded.get("active_task_id") == "t1",
                f"got {reloaded.get('active_task_id')}",
            )
            check(
                "registry file lives under isolated state dir (not personal path)",
                os.path.exists(os.path.join(d, "decision_registry.json")),
            )
        finally:
            os.environ.pop("UME_HARNESS_STATE_DIR", None)


def test_stop_adapter_all_conditions_met():
    print("\n[stop_adapter] 5条件すべて満たせば STOP_COMPLETE")
    c = sa.AcceptanceCheck(
        required_acceptance_criteria_satisfied=True,
        required_verification_completed=True,
        deliverables_present=True,
        persistence_confirmed_or_na=True,
        unresolved_blockers=[],
    )
    check("evaluate() == STOP_COMPLETE", c.evaluate() == sa.AcceptanceStatus.STOP_COMPLETE)
    check("unmet_points() empty", c.unmet_points() == [])


def test_stop_adapter_missing_condition_blocks():
    print("\n[stop_adapter] 1点でも未達なら CONTINUE_BLOCKED（強引にSTOPしない）")
    c = sa.AcceptanceCheck(
        required_acceptance_criteria_satisfied=True,
        required_verification_completed=False,
        deliverables_present=True,
        persistence_confirmed_or_na=True,
        unresolved_blockers=["waiting on human input"],
    )
    check("evaluate() == CONTINUE_BLOCKED", c.evaluate() == sa.AcceptanceStatus.CONTINUE_BLOCKED)
    check("unmet_points() reports both issues", len(c.unmet_points()) == 2, f"got {c.unmet_points()}")


def test_manifest_matches_explicit_release_closure():
    print("\n[manifest] MANIFEST.md は明示release closureと一致し、ambient filesystemに依存しない")
    pkg_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    with open(os.path.join(pkg_root, "package_manifest.json"), encoding="utf-8") as f:
        package_manifest = json.load(f)
    release_payload = package_manifest["release"]["payload"]
    assert len(release_payload) == len(set(release_payload)), "release.payload contains duplicates"

    manifest_path = os.path.join(pkg_root, "MANIFEST.md")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_text = f.read()
    m = re.search(r"```\n(.*?)\n```", manifest_text, re.DOTALL)
    declared_files = [line.strip() for line in (m.group(1).splitlines() if m else []) if line.strip()]
    check(
        "MANIFEST.md の宣言ファイルが package_manifest release.payload と順序を含め一致",
        declared_files == release_payload,
        f"manifest_only={sorted(set(declared_files) - set(release_payload))} "
        f"closure_only={sorted(set(release_payload) - set(declared_files))}",
    )
    generated = package_manifest["release"]["generated_identity_file"]
    missing_source_files = [
        rel for rel in release_payload
        if rel != generated and not os.path.isfile(os.path.join(pkg_root, rel))
    ]
    check(
        "明示closureのsource filesがすべて存在",
        not missing_source_files,
        f"missing={missing_source_files}",
    )
    check("generated identityがclosure内に1件だけ存在", release_payload.count(generated) == 1)


def test_japanese_human_layer_fixture_consistency():
    print("\n[ux] japanese-human-layer 既存fixture整合性テストを呼び出す（Layer 1のみ・LLM不使用）")
    layer_test = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "ux", "japanese-human-layer", "tests", "test_human_layer.py"
    )
    result = subprocess.run([sys.executable, layer_test], capture_output=True, text=True)
    check(
        "japanese-human-layer fixture consistency test exits 0",
        result.returncode == 0,
        f"stderr={result.stderr[-300:]}",
    )
    check(
        "reports 4 PASSED cases",
        "All 4 Acceptance Cases PASSED" in result.stdout,
    )
    print("  NOTE: これは Layer 1（fixture自己整合性）のみ。実LLM挙動テスト(Layer 2)はPhase 3で別途実施。")


def main():
    test_tier_secrets_always_deny()
    test_tier_constitution_readonly_allowed_else_deny()
    test_tier_runtime_code_no_forced_delegation()
    test_unknown_side_effect_fail_closed()
    test_classify_command_side_effect()
    test_token_store_consumes_single_earliest_token()
    test_token_store_expired_token_not_consumed()
    test_decision_state_path_resolution()
    test_decision_state_record_and_read_roundtrip()
    test_stop_adapter_all_conditions_met()
    test_stop_adapter_missing_condition_blocks()
    test_manifest_matches_explicit_release_closure()
    test_japanese_human_layer_fixture_consistency()

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
