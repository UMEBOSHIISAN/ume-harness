#!/usr/bin/env python3
"""
test_portable_core.py — ume-harness Portable Core 静的テスト

Phase 2（静的テストのみ）。LLMは一切呼び出さない。
tool_policy の純粋な分類表と、公開アセット／リリース境界を検証する。

japanese-human-layer の実LLM behavioral test（Phase 3）はここに含めない
（fixture整合性テストと実LLM挙動テストを混同しない、という監査結果を反映）。
"""

import hashlib
import json
import os
import re
import struct
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))

import tool_policy as tp  # noqa: E402

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
    manifest_normalized = " ".join(manifest_text.split())
    security_normalized = " ".join(security_text.split())
    support_normalized = " ".join(support_matrix_text.split())
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
        "current candidate identity is explicit and VERSION stays package-compatible",
        "# Development candidate manifest — thin Japanese decision support" in manifest_text
        and "Unreleased engineering candidate, intentionally different from published v0.1.7." in manifest_text
        and version == package_manifest["version"],
    )
    check(
        "MANIFEST keeps publication and migration boundaries explicit",
        "No push, publication or live settings migration is implied." in manifest_normalized
        and "Only ume-harness-engineering is canonical" in manifest_normalized
        and "generated one-way mirror" in manifest_normalized,
    )
    check(
        "security/support documents describe thin behavior and separate historical evidence",
        "This policy describes the unreleased thin candidate" in security_normalized
        and "UME is a non-executing preview plus two presentation hooks." in security_normalized
        and "# Support Matrix — unreleased thin candidate" in support_normalized
        and "## f999276 physical baseline" in support_normalized
        and "Old managed E2E does not verify a retired feature in this changed candidate." in support_normalized,
    )


def test_positioning_assets_are_public_only_and_bounded():
    pkg_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    with open(os.path.join(pkg_root, "package_manifest.json"), encoding="utf-8") as f:
        package_manifest = json.load(f)
    release_payload = package_manifest["release"]["payload"]
    install_payload = package_manifest["install_payload"]
    assert package_manifest["version"] == "0.1.7"
    with open(os.path.join(pkg_root, "VERSION"), encoding="utf-8") as f:
        assert f.read().strip() == "0.1.7"

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
        if locale == "ja":
            assert diagram.count(">UMEの開発候補</text>") == 1
            assert ">別repoの接続候補</text>" in diagram
            assert ">明示handoff / 合成ローカル候補</text>" in diagram
            assert ">CURRENT</text>" not in diagram
            assert "DIRECTION / NOT_SHIPPED" not in diagram
        else:
            assert ">Human: holds the purpose</tspan>" in diagram
            assert ">and decides what to entrust</tspan>" in diagram
            assert ">Separately configured</tspan>" in diagram
            assert ">executor</tspan>" in diagram
            assert ">Separate verification</tspan>" in diagram
            assert ">path</tspan>" in diagram
            assert ">Separately configured executor</text>" not in diagram

            assert ">Solid = responsibility flow</tspan>" in diagram
            assert ">Dashed = explicit candidate route</tspan>" in diagram
            assert ">Outline = separately configured</tspan>" in diagram
            assert "Solid = implemented now    Dashed = not connected" not in diagram

        cards_path = os.path.join(pkg_root, f"assets/readme/{locale}/translation-konjac-cards.svg")
        with open(cards_path, encoding="utf-8") as stream:
            cards = stream.read()
        assert 'viewBox="0 0 720 980"' in cards
        assert "{service}" not in cards
        assert "{branch}" not in cards
        assert "{target}" not in cards
        assert "PermissionRequest" in cards
        assert "PostToolUseFailure" in cards
        if locale == "ja":
            assert "作業前preview" in cards
            assert "許可・拒否はホストで判断" in cards
            assert "エラー本文は再掲しません" in cards
            assert "External Action Authority" not in cards

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
    test_manifest_matches_explicit_release_closure()
    test_positioning_assets_are_public_only_and_bounded()
    test_japanese_human_layer_fixture_consistency()

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
