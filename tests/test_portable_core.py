#!/usr/bin/env python3
"""
test_portable_core.py — ume-harness Portable Core 静的テスト

Phase 2（静的テストのみ）。LLMは一切呼び出さない。
contracts/tool_policy.md・contracts/authority_contract.md・contracts/autonomous_stop.md の
仕様どおりに runtime/ が実装されているかを検証する。

japanese-human-layer の実LLM behavioral test（Phase 3）はここに含めない
（fixture整合性テストと実LLM挙動テストを混同しない、という監査結果を反映）。
"""

import hashlib
import json
import multiprocessing
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))

import tool_policy as tp  # noqa: E402
import stop_adapter as sa  # noqa: E402


def _consume_token_with_load_delay(store_path, start_barrier, result_queue):
    """Synchronize consumers so an unlocked read-modify-write is observable."""
    store = tp.TokenStore(store_path)
    original_load = store._load

    def delayed_load():
        data = original_load()
        time.sleep(0.2)
        return data

    store._load = delayed_load
    start_barrier.wait()
    try:
        result_queue.put(("result", store.consume("impl_write", "scope")))
    except Exception as exc:  # pragma: no cover - surfaced by the parent assertion
        result_queue.put(("error", repr(exc)))

PASS = 0
FAIL = 0

POSITIONING_ASSETS = (
    "assets/readme/ja/ume-harness-human-layer.gif",
    "assets/readme/ja/ume-harness-human-layer-poster.png",
    "assets/readme/en/ume-harness-human-layer.gif",
    "assets/readme/en/ume-harness-human-layer-poster.png",
    "assets/readme/ja/ume-stack-responsibility.svg",
    "assets/readme/en/ume-stack-responsibility.svg",
    "assets/readme/ja/translation-konjac-cards.svg",
    "assets/readme/en/translation-konjac-cards.svg",
)


def _gif_metadata(path):
    """Return dimensions, frame count, duration ms, and frame delays for a GIF."""
    with open(path, "rb") as stream:
        data = stream.read()
    assert data[:6] in (b"GIF87a", b"GIF89a"), path
    dimensions = struct.unpack("<HH", data[6:10])
    packed = data[10]
    offset = 13
    if packed & 0x80:
        offset += 3 * (2 ** ((packed & 0x07) + 1))

    delays = []
    pending_delay = 0

    def skip_sub_blocks(start):
        while True:
            size = data[start]
            start += 1
            if size == 0:
                return start
            start += size

    while offset < len(data):
        marker = data[offset]
        offset += 1
        if marker == 0x3B:
            break
        if marker == 0x21:
            label = data[offset]
            offset += 1
            if label == 0xF9:
                block_size = data[offset]
                assert block_size == 4, path
                pending_delay = struct.unpack("<H", data[offset + 2:offset + 4])[0] * 10
                offset += 1 + block_size
                assert data[offset] == 0, path
                offset += 1
            else:
                offset = skip_sub_blocks(offset)
            continue
        assert marker == 0x2C, (path, marker)
        local_packed = data[offset + 8]
        offset += 9
        if local_packed & 0x80:
            offset += 3 * (2 ** ((local_packed & 0x07) + 1))
        offset += 1
        offset = skip_sub_blocks(offset)
        delays.append(pending_delay)
        pending_delay = 0

    return dimensions, len(delays), sum(delays), frozenset(delays)


def _asset_contract(path):
    """Parse the flat JSON-compatible values used by the asset TOML contract."""
    with open(path, encoding="utf-8") as stream:
        text = stream.read()
    entries = re.finditer(
        r"(?ms)^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)(?=^[A-Za-z_][A-Za-z0-9_]*\s*=|\Z)",
        text,
    )
    return {match.group(1): json.loads(match.group(2).strip()) for match in entries}


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


def test_token_store_rejects_unscoped_token_for_scoped_consume():
    print("\n[tool_policy] scopeなしの保存tokenはscoped consumeのwildcardにならない")
    with tempfile.TemporaryDirectory() as d:
        store_path = os.path.join(d, "tokens.json")
        now = int(time.time())
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tokens": [
                        {
                            "action": "impl_write",
                            "scope_target": None,
                            "expires_epoch": now + 1000,
                            "uses_remaining": 1,
                        }
                    ]
                },
                f,
            )

        store = tp.TokenStore(store_path)
        check(
            "scoped consume rejects null-scope token",
            store.consume("impl_write", "scope") is False,
        )
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        check(
            "rejected null-scope token remains unused",
            data["tokens"][0]["uses_remaining"] == 1,
        )


def test_token_store_rejects_malformed_documents_without_authorizing():
    print("\n[tool_policy] malformed token storeは例外経由でもALLOWしない")
    malformed_documents = [
        ("{not-json", "invalid JSON"),
        ([], "non-object root"),
        ({"tokens": {}}, "tokens is not an array"),
        (
            {
                "tokens": [
                    {
                        "action": "impl_write",
                        "scope_target": "scope",
                        "expires_epoch": "future",
                        "uses_remaining": 1,
                    }
                ]
            },
            "invalid expiry type",
        ),
        (
            {
                "tokens": [
                    {
                        "action": "impl_write",
                        "scope_target": "scope",
                        "expires_epoch": int(time.time()) + 1000,
                        "uses_remaining": -1,
                    }
                ]
            },
            "negative remaining uses",
        ),
    ]

    with tempfile.TemporaryDirectory() as d:
        for document, label in malformed_documents:
            store_path = os.path.join(d, f"{label.replace(' ', '_')}.json")
            with open(store_path, "w", encoding="utf-8") as f:
                if isinstance(document, str):
                    f.write(document)
                else:
                    json.dump(document, f)
            check(
                f"{label} fails closed",
                tp.TokenStore(store_path).consume("impl_write", "scope") is False,
            )


def test_token_store_rejects_symlink_and_hardlink_aliases():
    print("\n[tool_policy] token storeのsymlink/hardlink別名はlock迂回になるため拒否する")
    now = int(time.time()) + 1000

    with tempfile.TemporaryDirectory() as d:
        real_path = os.path.join(d, "tokens.json")
        alias_path = os.path.join(d, "tokens-symlink.json")
        with open(real_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tokens": [
                        {
                            "action": "impl_write",
                            "scope_target": "scope",
                            "expires_epoch": now,
                            "uses_remaining": 1,
                        }
                    ]
                },
                f,
            )
        os.symlink(real_path, alias_path)
        check(
            "symlink alias fails closed",
            tp.TokenStore(alias_path).consume("impl_write", "scope") is False,
        )
        with open(real_path, "r", encoding="utf-8") as f:
            check("symlink alias leaves canonical token untouched", json.load(f)["tokens"][0]["uses_remaining"] == 1)

    with tempfile.TemporaryDirectory() as d:
        real_path = os.path.join(d, "tokens.json")
        alias_path = os.path.join(d, "tokens-hardlink.json")
        with open(real_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tokens": [
                        {
                            "action": "impl_write",
                            "scope_target": "scope",
                            "expires_epoch": now,
                            "uses_remaining": 1,
                        }
                    ]
                },
                f,
            )
        os.link(real_path, alias_path)
        check(
            "hardlink alias fails closed",
            tp.TokenStore(alias_path).consume("impl_write", "scope") is False,
        )
        with open(real_path, "r", encoding="utf-8") as f:
            check("hardlink alias leaves canonical token untouched", json.load(f)["tokens"][0]["uses_remaining"] == 1)


def test_token_store_one_shot_consume_is_concurrency_safe():
    print("\n[tool_policy] 同一one-shot tokenは並行consumeでも1回だけ成功する")
    if "fork" not in multiprocessing.get_all_start_methods():
        print("  SKIP  fork-based race fixture is unavailable on this platform")
        return

    ctx = multiprocessing.get_context("fork")
    with tempfile.TemporaryDirectory() as d:
        store_path = os.path.join(d, "tokens.json")
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tokens": [
                        {
                            "action": "impl_write",
                            "scope_target": "scope",
                            "expires_epoch": int(time.time()) + 1000,
                            "uses_remaining": 1,
                        }
                    ]
                },
                f,
            )

        workers = 4
        start_barrier = ctx.Barrier(workers)
        result_queue = ctx.Queue()
        processes = [
            ctx.Process(
                target=_consume_token_with_load_delay,
                args=(store_path, start_barrier, result_queue),
            )
            for _ in range(workers)
        ]
        for process in processes:
            process.start()

        results = []
        for _ in processes:
            kind, value = result_queue.get(timeout=10)
            assert kind == "result", value
            results.append(value)
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0

        check(
            "exactly one concurrent consume succeeds",
            sum(result is True for result in results) == 1,
            f"results={results}",
        )
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        check(
            "one-shot token is exhausted once",
            data["tokens"][0]["uses_remaining"] == 0,
        )


def test_token_store_post_commit_durability_failure_does_not_report_false():
    print("\n[tool_policy] rename後のfsync失敗でも消費済みtokenを未消費と誤報しない")
    with tempfile.TemporaryDirectory() as d:
        store_path = os.path.join(d, "tokens.json")
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tokens": [
                        {
                            "action": "impl_write",
                            "scope_target": "scope",
                            "expires_epoch": int(time.time()) + 1000,
                            "uses_remaining": 2,
                        }
                    ]
                },
                f,
            )

        original_fsync = os.fsync

        def fail_directory_fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("directory durability unavailable")
            return original_fsync(fd)

        original_store_fsync = tp.os.fsync
        tp.os.fsync = fail_directory_fsync
        try:
            consumed = tp.TokenStore(store_path).consume("impl_write", "scope")
        finally:
            tp.os.fsync = original_store_fsync

        check("logical consume remains successful after committed rename", consumed is True)
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        check("committed token decrement is preserved", data["tokens"][0]["uses_remaining"] == 1)


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
    with open(os.path.join(pkg_root, "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    with open(os.path.join(pkg_root, "SECURITY.md"), encoding="utf-8") as f:
        security_text = f.read()
    with open(os.path.join(pkg_root, "SUPPORT_MATRIX.md"), encoding="utf-8") as f:
        support_matrix_text = f.read()
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
    check(
        "MANIFEST.md のversionと実測test countがcurrent releaseに一致",
        f"# Release Manifest (ume-harness v{version})" in manifest_text
        and f"Measured against the v{version} release-candidate bytes" in manifest_text
        and "  -> 318 passed" in manifest_text,
    )
    check(
        "配布security/support文書のversionがcurrent releaseに一致",
        f"v{version} attests the explicit protected-runtime closure" in security_text
        and f"# Support Matrix (v{version} generated public release mirror / 2026-09-04)" in support_matrix_text,
    )


def test_positioning_assets_are_public_only_and_bounded():
    pkg_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    with open(os.path.join(pkg_root, "package_manifest.json"), encoding="utf-8") as f:
        package_manifest = json.load(f)
    release_payload = package_manifest["release"]["payload"]
    install_payload = package_manifest["install_payload"]
    assert package_manifest["version"] == "0.1.5"
    with open(os.path.join(pkg_root, "VERSION"), encoding="utf-8") as f:
        assert f.read().strip() == "0.1.5"

    for relative in POSITIONING_ASSETS:
        assert os.path.isfile(os.path.join(pkg_root, relative)), relative
        assert relative in release_payload, relative
        assert relative not in install_payload, relative
    for relative in (
        "README.en.md",
        "assets/readme/source/asset-build.toml",
        "assets/readme/source/fonts/NotoSansJP-Regular.ttf",
        "assets/readme/source/fonts/OFL-1.1.txt",
        "assets/readme/source/generate_ume_harness_assets.py",
        "assets/readme/source/requirements-assets.txt",
    ):
        assert relative in release_payload, relative
        assert relative not in install_payload, relative

    contract_path = os.path.join(pkg_root, "assets/readme/source/asset-build.toml")
    contract = _asset_contract(contract_path)
    assert sorted(contract["outputs"]) == sorted(POSITIONING_ASSETS)
    assert contract["normal_weight"] == 400
    assert contract["bold_weight"] == 700
    font_path = os.path.join(pkg_root, "assets/readme/source", contract["font"])
    with open(font_path, "rb") as stream:
        assert hashlib.sha256(stream.read()).hexdigest() == contract["font_sha256"]

    for locale in ("ja", "en"):
        gif = os.path.join(pkg_root, f"assets/readme/{locale}/ume-harness-human-layer.gif")
        dimensions, frames, duration_ms, delays = _gif_metadata(gif)
        assert dimensions == (contract["width"], contract["height"])
        assert frames == contract["frame_count"]
        assert duration_ms == contract["duration_ms"]
        assert delays == frozenset((120, 130))
        assert os.path.getsize(gif) < contract["max_gif_bytes"]

        poster = os.path.join(pkg_root, f"assets/readme/{locale}/ume-harness-human-layer-poster.png")
        with open(poster, "rb") as stream:
            header = stream.read(24)
        assert header[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", header[16:24]) == (
            contract["poster_width"],
            contract["poster_height"],
        )

        diagram_path = os.path.join(pkg_root, f"assets/readme/{locale}/ume-stack-responsibility.svg")
        with open(diagram_path, encoding="utf-8") as stream:
            diagram = stream.read()
        assert 'viewBox="0 0 720 1120"' in diagram
        assert diagram.count("stroke-dasharray=") == 2
        assert diagram.count('data-role="bridge"') == 1
        assert diagram.count('data-role="external"') == 2
        if locale == "en":
            assert ">Human: holds the purpose</tspan>" in diagram
            assert ">and decides what to entrust</tspan>" in diagram
            assert ">Separately configured</tspan>" in diagram
            assert ">executor</tspan>" in diagram
            assert ">Separate verification</tspan>" in diagram
            assert ">path</tspan>" in diagram
            assert ">Separately configured executor</text>" not in diagram

            assert ">Solid = implemented now</tspan>" in diagram
            assert ">Dashed = not connected</tspan>" in diagram
            assert ">Outline = separately configured</tspan>" in diagram
            assert "Solid = implemented now    Dashed = not connected" not in diagram

        cards_path = os.path.join(pkg_root, f"assets/readme/{locale}/translation-konjac-cards.svg")
        with open(cards_path, encoding="utf-8") as stream:
            cards = stream.read()
        assert 'viewBox="0 0 720 980"' in cards
        assert "{service}" not in cards
        assert "{branch}" not in cards
        assert "{target}" not in cards
        if locale == "ja":
            with open(
                os.path.join(pkg_root, "common-language/packs/ja-JP/p0_concepts.json"),
                encoding="utf-8",
            ) as stream:
                concepts = json.load(stream)["concepts"]
            assert "PCの外へ出る（表示例）" in cards
            assert "削除（表示例）" in cards
            assert concepts["git.status"]["headline"] in cards
            assert (
                concepts["git.push.normal"]["headline"].format(
                    service="GitHub", branch="作業ブランチ"
                )
                in cards
            )
            assert concepts["fs.delete"]["headline"].format(target="選択した対象") in cards

    generator_path = os.path.join(pkg_root, "assets/readme/source/generate_ume_harness_assets.py")
    with open(generator_path, encoding="utf-8") as stream:
        generator = stream.read()
    assert "tomllib" in generator
    assert "NORMAL_WEIGHT" in generator
    assert "MIN_PYTHON" in generator
    assert "FRAME_COUNT * 1000 != FPS * DURATION_MS" in generator
    assert '"request": "この資料をまとめて、\\n必要ならREADMEも\\nいい感じに直しといて"' in generator
    assert '"request": "Please organize the\\nmaterial and improve\\nthe README if useful."' in generator


def test_manual_runner_invokes_positioning_asset_check():
    source_path = os.path.abspath(__file__)
    with open(source_path, encoding="utf-8") as stream:
        source = stream.read()
    main_body = source.rsplit("\ndef main():", 1)[1]
    assert "test_positioning_assets_are_public_only_and_bounded()" in main_body


def test_three_plane_public_truth():
    print("\n[docs] Japanese-first positioning separates current surfaces and the unwired bridge")
    pkg_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    with open(os.path.join(pkg_root, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    english_path = os.path.join(pkg_root, "README.en.md")
    assert os.path.isfile(english_path), "README.en.md"
    with open(english_path, encoding="utf-8") as f:
        english = f.read()
    with open(os.path.join(pkg_root, "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    normalized = " ".join(readme.split())
    english_normalized = " ".join(english.split())
    first_screen = "\n".join(readme.splitlines()[:55])
    check(
        "README begins with ordinary Japanese value language",
        "日本語で、雑に頼める。" in first_screen
        and "やること・確認すること・しないこと" in first_screen,
    )
    check(
        "README names Japanese-first Harness before internal contract terms",
        "Japanese-first Harness" in first_screen
        and "Authority Overlay" not in first_screen
        and "Clarification Impact Contract" not in first_screen,
    )
    check(
        "standalone CLI is explicitly preview-only",
        "standalone CLIはファイル操作を実行しません。" in readme
        and "The standalone CLI presents a plan; it does not perform file operations." in english,
    )
    check(
        "Quick Start discloses Claude transport and distinguishes requested side effects",
        "## Preview Quick Start" in readme
        and "Claude CLIの認証とネットワーク接続が必要" in readme
        and "依頼文とcontextをClaudeへ送ります" in readme
        and "依頼されたファイル操作や外部結果は実行しません" in readme
        and "## Preview Quick Start" in english
        and "authenticated Claude CLI and network access" in english
        and "sends the request and context to Claude" in english
        and "does not perform the requested file operations or consequential actions" in english,
    )
    check(
        "Human Layer CLI and Claude Code Host Adapter are separate current surfaces",
        "### 日本語Human Layer preview CLI" in readme
        and "### Claude Code Host Adapter" in readme
        and "### Human Layer preview CLI" in english
        and "### Claude Code Host Adapter" in english,
    )
    check(
        "responsibility bridge is explicitly unwired in both languages",
        "現在の公開release同士に自動runtime bridgeはありません。破線部分は未実装です。" in normalized
        and "The current public releases have no automatic runtime bridge. The dashed connection is not implemented."
        in english_normalized,
    )
    check(
        "Mothership remains a complementary responsibility plane",
        "UME-HARNESSは人間の意図を範囲の決まったローカル作業へ整理します。" in normalized
        and "Mothershipは人間の判断を範囲の決まった外部結果へ結び付けます。" in normalized,
    )
    check(
        "one GIF and one poster are referenced per locale",
        readme.count("assets/readme/ja/ume-harness-human-layer.gif") == 1
        and readme.count("assets/readme/ja/ume-harness-human-layer-poster.png") == 2
        and english.count("assets/readme/en/ume-harness-human-layer.gif") == 1
        and english.count("assets/readme/en/ume-harness-human-layer-poster.png") == 2
        and 'media="(max-width: 600px)"' in readme
        and 'media="(prefers-reduced-motion: reduce)"' in readme
        and 'media="(max-width: 600px)"' in english
        and 'media="(prefers-reduced-motion: reduce)"' in english,
    )
    check(
        "README declares Technical Preview status",
        "Technical Preview" in readme and "Technical Preview" in english,
    )
    check(
        "README does not overclaim non-engineer safety",
        "非エンジニアが自然な日本語で安全に仕事を任せられる" not in readme,
    )
    check(
        "README discloses beginner usability validation status",
        "非エンジニア向けの導入容易性は現在検証中です。" in readme
        and "Ease of adoption for non-engineers remains under evaluation." in english,
    )
    check(
        "README preserves canonical-source and generated-mirror boundary",
        ("public " + chr(96) + "ume-harness" + chr(96) + "は明示closureから生成するrelease mirror") in readme,
    )
    check(
        "README exposes public CI and current release",
        "https://github.com/UMEBOSHIISAN/ume-harness/actions/workflows/ci.yml/badge.svg" in readme
        and f"https://github.com/UMEBOSHIISAN/ume-harness/releases/tag/v{version}" in readme,
    )
    check(
        "README and NOTICE distinguish project MIT code from the OFL font",
        "project code is MIT" in english
        and "Noto Sans JP" in english
        and "SIL Open Font License 1.1" in english
        and "プロジェクトのコードはMIT" in readme
        and "SIL Open Font License 1.1" in readme,
    )

    with open(os.path.join(pkg_root, "NOTICE"), encoding="utf-8") as f:
        notice = f.read()
    check(
        "NOTICE records the pinned Noto Sans JP provenance",
        "Noto Sans JP" in notice
        and "295d98a7a0c17c68f1341eaeea354e7960ea70d3" in notice
        and "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f" in notice
        and "SIL Open Font License 1.1" in notice,
    )
    check(
        "github profile is not used as Harness identity above current implementation",
        "github.merge_pr" not in readme[:readme.index("## 現在の実装")],
    )


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
    test_token_store_post_commit_durability_failure_does_not_report_false()
    test_token_store_rejects_unscoped_token_for_scoped_consume()
    test_token_store_rejects_malformed_documents_without_authorizing()
    test_token_store_rejects_symlink_and_hardlink_aliases()
    test_token_store_one_shot_consume_is_concurrency_safe()
    test_decision_state_path_resolution()
    test_decision_state_record_and_read_roundtrip()
    test_stop_adapter_all_conditions_met()
    test_stop_adapter_missing_condition_blocks()
    test_manifest_matches_explicit_release_closure()
    test_positioning_assets_are_public_only_and_bounded()
    test_three_plane_public_truth()
    test_japanese_human_layer_fixture_consistency()

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
