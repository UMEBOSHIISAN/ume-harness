#!/usr/bin/env python3
"""
test_human_layer_adapter.py — human_layer_adapter.py 静的テスト
(Clarification Impact Contract v0 Rev.2・FROZEN)

最重要不変条件1: LLMがrequired_human_approvalsを空で返しても、candidate_actionsに
DESTRUCTIVE/EXTERNAL_MUTATION/AUTHORITY_TOUCH相当の操作が含まれていれば、
Core側で強制的にapproval_requiredへ上書きする（Phase 3bで実測した2/5の
authority false negativeの再発防止）。

最重要不変条件2（Rev.2・Structural Gate）: clarification_assessments の
構造的異常（フィールド欠落・型不一致・不正enum・根拠なしFALSE・questionなきASK）は
全てfail-safe（ASKまたはBLOCK）に倒れ、無検証でSUPPRESSへ落ちない。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))
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


# --- helper: 全次元を一括で組み立てる ---
def all_dims(value: str, basis=None) -> dict:
    return {dim: value for dim in hla.DIMENSIONS}, {dim: basis for dim in hla.DIMENSIONS}


def make_assessment(question, impact: dict, basis: dict | None = None) -> dict:
    return {"question": question, "missing_information": "test", "impact": impact, "basis": basis or {}}


VALID_EXPLICIT = {"kind": "explicit_request", "refs": ["raw_requestに明記"]}
VALID_NOT_APPLICABLE = {"kind": "not_applicable", "reason": "この次元は該当しない"}


# =========================================================================
# Authority Overlay（Rev.1から不変・変更禁止対象）
# =========================================================================

def test_destructive_action_always_forces_approval_even_if_llm_said_none():
    print("\n[critical] LLMがapprovals=[]でもDESTRUCTIVE(削除)は強制的にAPPROVAL_REQUIREDになる")
    llm_output = {
        "work_type": "EDIT_CREATE",
        "inferred_intent": "不要なファイルを削除する",
        "inferred_deliverable": "不要なファイルが削除されたフォルダ状態",
        "candidate_actions": ["file_a.tmp を削除する", "notes.txt を確認する"],
        "clarification_assessments": [],
    }
    result = hla.normalize(llm_output)
    check(
        "削除アクションが required_human_approvals に強制的に含まれる",
        any("削除" in a for a in result.required_human_approvals),
        f"got {result.required_human_approvals}",
    )


def test_destructive_action_even_when_llm_labels_it_as_allowed():
    print("\n[critical] LLMが削除を allowed_actions 側に誤分類していても Core は無視して強制する")
    llm_output = {
        "work_type": "EDIT_CREATE",
        "inferred_intent": "不要なファイルの削除",
        "inferred_deliverable": "整理済みフォルダ",
        "candidate_actions": ["作業フォルダ内のファイルの読み込みと削除"],
        "clarification_assessments": [],
    }
    result = hla.normalize(llm_output)
    check(
        "1つのcandidate_action文字列に「削除」を含むだけでも approval_required に上がる",
        len(result.required_human_approvals) == 1,
        f"got {result.required_human_approvals}",
    )


def test_external_send_always_forces_approval():
    print("\n[critical] 外部送信は強制的にAPPROVAL_REQUIREDになる")
    llm_output = {
        "work_type": "EDIT_CREATE",
        "inferred_intent": "まとめを作成し先方へ送る",
        "inferred_deliverable": "まとめ文面",
        "candidate_actions": ["まとめ文面を作成する", "先方にメールで送信する"],
        "clarification_assessments": [],
    }
    result = hla.normalize(llm_output)
    check(
        "送信アクションが approval_required に含まれる",
        any("送信" in a for a in result.required_human_approvals),
        f"got {result.required_human_approvals}",
    )
    check(
        "作成アクション（BOUNDED_WRITE・TIER_NORMAL）は approval不要のまま",
        not any("作成" in a for a in result.required_human_approvals),
        f"got {result.required_human_approvals}",
    )


def test_read_only_action_no_approval():
    print("\n[tool_policy連携] 読み取りのみのcandidate_actionは approval不要")
    llm_output = {
        "work_type": "RESEARCH",
        "inferred_intent": "資料を調査する",
        "inferred_deliverable": "調査結果の要約",
        "candidate_actions": ["フォルダ内のファイルを閲覧する", "内容を確認する"],
        "clarification_assessments": [],
    }
    result = hla.normalize(llm_output)
    check("approval_required が空", result.required_human_approvals == [], f"got {result.required_human_approvals}")


def test_unknown_action_fails_closed_to_approval():
    print("\n[fail-closed] 分類できないcandidate_actionは安全側(approval要求)に倒れる")
    llm_output = {
        "work_type": "ORGANIZE",
        "inferred_intent": "謎の作業",
        "inferred_deliverable": "不明",
        "candidate_actions": ["よしなにやる"],
        "clarification_assessments": [],
    }
    result = hla.normalize(llm_output)
    check(
        "分類不能でも approval_required に入る（無言でスルーしない）",
        len(result.required_human_approvals) == 1,
        f"got {result.required_human_approvals}",
    )


# =========================================================================
# Root validation and compound candidate provenance
# =========================================================================

def test_non_object_root_returns_blocked_normalized_interpretation():
    print("\n[root validation] 非objectのLLM出力は例外ではなくBLOCK結果になる")
    result = hla.normalize(None)
    check("NormalizedInterpretationを返す", isinstance(result, hla.NormalizedInterpretation))
    check("clarification_blocked = True", result.clarification_blocked is True)
    check("root型エラーの機械可読noteがある", "INVALID_ROOT_TYPE" in result.validation_notes)


def test_missing_required_root_fields_returns_validation_notes():
    print("\n[root validation] 必須root field欠落はBLOCKと機械可読noteになる")
    result = hla.normalize({"work_type": None, "clarification_assessments": []})
    check("clarification_blocked = True", result.clarification_blocked is True)
    expected = {
        "MISSING_REQUIRED_FIELD:inferred_intent",
        "MISSING_REQUIRED_FIELD:inferred_deliverable",
        "MISSING_REQUIRED_FIELD:candidate_actions",
    }
    check("欠落field名がnoteに残る", expected.issubset(set(result.validation_notes)), repr(result.validation_notes))


def test_wrong_type_root_fields_return_validation_notes_without_classifying_actions():
    print("\n[root validation] candidate_actionsのnull/数値要素は例外ではなくBLOCKになる")
    cases = (
        ({"candidate_actions": None}, "INVALID_FIELD_TYPE:candidate_actions"),
        ({"candidate_actions": [7]}, "INVALID_FIELD_ITEM_TYPE:candidate_actions[0]"),
        ({"inferred_intent": 7}, "INVALID_FIELD_TYPE:inferred_intent"),
        ({"inferred_deliverable": 7}, "INVALID_FIELD_TYPE:inferred_deliverable"),
    )
    for overrides, expected_note in cases:
        payload = {
            "work_type": None,
            "inferred_intent": "x",
            "inferred_deliverable": "x",
            "candidate_actions": [],
            "clarification_assessments": [],
        }
        payload.update(overrides)
        result = hla.normalize(payload)
        check("clarification_blocked = True", result.clarification_blocked is True)
        check("不正root fieldのnoteがある", expected_note in result.validation_notes, repr(result.validation_notes))
        check("不正root fieldでは分類しない", result.action_overlay == [])


def test_null_work_type_remains_valid_and_unresolved():
    print("\n[root validation] work_type=nullは既存互換のUNRESOLVEDとして受理する")
    result = hla.normalize({
        "work_type": None,
        "inferred_intent": "x",
        "inferred_deliverable": "x",
        "candidate_actions": [],
        "clarification_assessments": [],
    })
    check("work_type=None", result.work_type is None)
    check("classification_status=UNRESOLVED", result.classification_status == "UNRESOLVED")
    check("形式エラーでBLOCKしない", result.clarification_blocked is False)
    check("validation noteなし", result.validation_notes == [])


def test_posting_is_external_mutation_and_requires_approval():
    print("\n[compound/action] 投稿はEXTERNAL_MUTATIONとして承認要求になる")
    result = hla.normalize({
        "work_type": "EDIT_CREATE",
        "inferred_intent": "READMEを直して投稿する",
        "inferred_deliverable": "更新済みREADME",
        "candidate_actions": ["Slackに投稿する"],
        "clarification_assessments": [],
    })
    check("投稿を外部変更として分類", result.action_overlay[0].side_effect == tp.SideEffect.EXTERNAL_MUTATION)
    check("投稿に承認が必要", result.required_human_approvals == ["Slackに投稿する"])


def test_japanese_compound_keeps_source_and_does_not_inherit_write_allow():
    print("\n[compound/action] して分割後もsource_actionを保持し未知部分はALLOWを継承しない")
    source = "READMEを修正してよしなにする"
    result = hla.normalize({
        "work_type": "EDIT_CREATE",
        "inferred_intent": source,
        "inferred_deliverable": "README",
        "candidate_actions": [source],
        "clarification_assessments": [],
    })
    check("2つの候補へ分割", [d.action_text for d in result.action_overlay] == ["READMEを修正する", "よしなにする"])
    check("全分割候補が元candidateを参照", all(d.source_action == source for d in result.action_overlay))
    check("既知の修正部分はALLOW", result.action_overlay[0].decision == tp.Decision.ALLOW)
    check("未知部分は承認要求へfail-closed", result.action_overlay[1].side_effect == tp.SideEffect.UNKNOWN and result.action_overlay[1].decision == tp.Decision.APPROVAL_REQUIRED)
    check("未知部分を含む元candidateが承認要求に残る", "よしなにする" in result.required_human_approvals)


def test_case_marker_toshite_preserves_bounded_write_candidate():
    source = "結果を報告書として作成する"
    result = hla.normalize({
        "work_type": "EDIT_CREATE",
        "inferred_intent": source,
        "inferred_deliverable": "報告書",
        "candidate_actions": [source],
        "clarification_assessments": [],
    })
    assert [d.action_text for d in result.action_overlay] == [source]
    assert result.action_overlay[0].side_effect == tp.SideEffect.BOUNDED_WRITE
    assert result.action_overlay[0].source_action == source
    assert result.required_human_approvals == []


def test_case_marker_before_sequential_action_preserves_external_approval():
    for source in (
        "結果を報告書として作成して送信する",
        "結果を報告書として作成してから送信する",
    ):
        overlay = hla.compute_authority_overlay([source])
        assert [d.action_text for d in overlay] == ["結果を報告書として作成する", "送信する"]
        assert all(d.source_action == source for d in overlay)
        assert overlay[0].decision == tp.Decision.ALLOW
        assert overlay[1].side_effect == tp.SideEffect.EXTERNAL_MUTATION
        assert overlay[1].decision == tp.Decision.APPROVAL_REQUIRED


def test_compound_conjunction_allowlist_splits_comma_then_and_ampersand():
    print("\n[compound/action] allowlist上のcomma/then/and/ampersandだけを分割する")
    for source in (
        "READMEを修正する、Slackに投稿する",
        "READMEを修正する, Slackに投稿する",
        "READMEを修正する Then Slackに投稿する",
        "READMEを修正する AND Slackに投稿する",
        "READMEを修正する & Slackに投稿する",
    ):
        result = hla.normalize({
            "work_type": "EDIT_CREATE",
            "inferred_intent": source,
            "inferred_deliverable": "README",
            "candidate_actions": [source],
            "clarification_assessments": [],
        })
        check("allowlistが2候補に分割", len(result.action_overlay) == 2, source)
        check("投稿側は承認要求", result.action_overlay[-1].side_effect == tp.SideEffect.EXTERNAL_MUTATION, source)


def test_ascii_comma_without_whitespace_is_not_split():
    print("\n[compound/action] whitespaceなしASCII commaはCSV風candidateとして分割しない")
    source = "file_a.csv,file_b.csv"
    result = hla.normalize({
        "work_type": "RESEARCH",
        "inferred_intent": "対象を確認する",
        "inferred_deliverable": "一覧",
        "candidate_actions": [source],
        "clarification_assessments": [],
    })
    check("CSV風candidateを1件のまま保持", [d.action_text for d in result.action_overlay] == [source])
    check("元candidateをsource_actionに保持", result.action_overlay[0].source_action == source)


def test_ascii_comma_unknown_trailing_action_fails_closed():
    print("\n[compound/action] ASCII comma後の未知操作は兄弟のALLOWを継承しない")
    source = "edit README, notify somebody"
    result = hla.normalize({
        "work_type": "EDIT_CREATE",
        "inferred_intent": source,
        "inferred_deliverable": "README",
        "candidate_actions": [source],
        "clarification_assessments": [],
    })
    check("ASCII comma+spaceで2候補", [d.action_text for d in result.action_overlay] == ["edit README", "notify somebody"])
    check("後半UNKNOWNは承認要求", result.action_overlay[-1].side_effect == tp.SideEffect.UNKNOWN and result.action_overlay[-1].decision == tp.Decision.APPROVAL_REQUIRED)
    check("後半の元candidateを保持", result.action_overlay[-1].source_action == source)


def test_destructive_component_remains_most_restrictive_after_split():
    print("\n[compound/action] compound内の破壊操作は分割後もDESTRUCTIVEを保持する")
    source = "READMEを修正してファイルを削除する"
    result = hla.normalize({
        "work_type": "EDIT_CREATE",
        "inferred_intent": source,
        "inferred_deliverable": "README",
        "candidate_actions": [source],
        "clarification_assessments": [],
    })
    check("破壊操作の分類を保持", any(d.side_effect == tp.SideEffect.DESTRUCTIVE for d in result.action_overlay))
    check("破壊操作は承認要求", any("削除" in action for action in result.required_human_approvals))
    check("source_actionを保持", all(d.source_action == source for d in result.action_overlay))


# =========================================================================
# Clarification Impact Contract v0 Rev.2 — Structural Gate
# =========================================================================

def test_assessments_field_missing_blocks():
    print("\n[B3 structural] clarification_assessments フィールド自体が欠落 → BLOCK")
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [],
    })
    check("clarification_blocked = True", result.clarification_blocked is True)
    check("surfaced/pruned は空", result.surfaced_unknowns == [] and result.pruned_unknowns == [])


def test_assessments_field_null_blocks():
    print("\n[B3 structural] clarification_assessments が null → BLOCK")
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": None,
    })
    check("clarification_blocked = True", result.clarification_blocked is True)


def test_assessments_field_wrong_type_blocks():
    print("\n[B3 structural] clarification_assessments が非list型(文字列) → BLOCK")
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": "特に不明点はない",
    })
    check("clarification_blocked = True", result.clarification_blocked is True)


def test_empty_assessments_list_is_valid_clean_state():
    print("\n[design] 空リスト[] は正当な主張として受理される（BLOCKでもASKでもない）")
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [],
    })
    check("clarification_blocked = False", result.clarification_blocked is False)
    check("surfaced/pruned とも空", result.surfaced_unknowns == [] and result.pruned_unknowns == [])


def test_impact_value_missing_field_normalizes_to_unknown_and_asks():
    print("\n[B2] impactの一部フィールドが欠落 → UNKNOWN扱い → ASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    del impact["mutation_target"]  # 欠落
    basis = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS if d != "mutation_target"}
    a = make_assessment("質問文", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる（欠落フィールドがUNKNOWN扱い）", result.surfaced_unknowns == ["質問文"], f"got {result.surfaced_unknowns}")
    check("BLOCKにはならない", result.clarification_blocked is False)


def test_impact_value_null_normalizes_to_unknown():
    print("\n[B2] impact値がnull → UNKNOWN扱い → ASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["destructive_effect"] = None
    basis = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS if d != "destructive_effect"}
    a = make_assessment("質問文", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる", result.surfaced_unknowns == ["質問文"])


def test_impact_value_json_boolean_is_invalid_normalizes_to_unknown():
    print("\n[B2] impact値がJSON native boolean(true/false) → 文字列でないため無効 → UNKNOWN → ASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["requested_scope"] = False   # Python/JSON の native boolean（文字列"false"ではない）
    basis = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS if d != "requested_scope"}
    a = make_assessment("質問文", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる（native booleanは無効値としてUNKNOWN扱い）", result.surfaced_unknowns == ["質問文"])


def test_impact_value_garbage_string_normalizes_to_unknown():
    print("\n[B2] impact値が不正な文字列('yes'等) → UNKNOWN扱い → ASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["costly_rollback"] = "yes"
    basis = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS if d != "costly_rollback"}
    a = make_assessment("質問文", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる", result.surfaced_unknowns == ["質問文"])


def test_false_without_basis_upgrades_to_unknown_and_asks():
    print("\n[B1 structural] FALSE + basis欠落 → UNKNOWNへ昇格 → ASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    a = make_assessment("質問文", impact, basis=None)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる（無根拠FALSEは通らない）", result.surfaced_unknowns == ["質問文"])


def test_false_with_invalid_basis_kind_upgrades_to_unknown():
    print("\n[B1 structural] FALSE + basis.kindが不正な値 → UNKNOWNへ昇格 → ASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    basis = {d: {"kind": "because_i_said_so"} for d in hla.DIMENSIONS}
    a = make_assessment("質問文", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる", result.surfaced_unknowns == ["質問文"])


def test_false_with_empty_refs_upgrades_to_unknown():
    print("\n[B1 structural] FALSE + explicit_requestだがrefsが空リスト → 無効 → UNKNOWN → ASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    basis = {d: {"kind": "explicit_request", "refs": []} for d in hla.DIMENSIONS}
    a = make_assessment("質問文", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる", result.surfaced_unknowns == ["質問文"])


def test_false_with_empty_reason_upgrades_to_unknown():
    print("\n[B1 structural] FALSE + not_applicableだがreasonが空文字 → 無効 → UNKNOWN → ASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    basis = {d: {"kind": "not_applicable", "reason": "   "} for d in hla.DIMENSIONS}
    a = make_assessment("質問文", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる", result.surfaced_unknowns == ["質問文"])


def test_false_with_valid_explicit_request_basis_is_accepted():
    print("\n[C] FALSE + 有効な basis(explicit_request) → FALSEとして成立")
    impact = {d: "false" for d in hla.DIMENSIONS}
    basis = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS}
    a = make_assessment(None, impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("SUPPRESSになる（question=Noneでも許容される）", result.surfaced_unknowns == [], f"got {result.surfaced_unknowns}")
    check("pruned_unknowns に1件記録される（無言で消さない）", len(result.pruned_unknowns) == 1)
    check("BLOCKにはならない", result.clarification_blocked is False)


def test_false_with_valid_not_applicable_basis_is_accepted():
    print("\n[C] FALSE + 有効な basis(not_applicable) → FALSEとして成立")
    impact = {d: "false" for d in hla.DIMENSIONS}
    basis = {d: dict(VALID_NOT_APPLICABLE) for d in hla.DIMENSIONS}
    a = make_assessment(None, impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("SUPPRESSになる", result.surfaced_unknowns == [])


def test_all_dimensions_false_with_valid_basis_suppresses():
    print("\n[E] 全6次元がFALSE(有効basis付き) → SUPPRESS")
    impact = {d: "false" for d in hla.DIMENSIONS}
    basis = {d: dict(VALID_EXPLICIT) if i % 2 == 0 else dict(VALID_NOT_APPLICABLE)
             for i, d in enumerate(hla.DIMENSIONS)}
    a = make_assessment(None, impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("SUPPRESSになる", result.surfaced_unknowns == [])
    check("pruned_unknowns に記録される", len(result.pruned_unknowns) == 1)


def test_any_true_forces_ask_regardless_of_others():
    print("\n[E] 1次元でもTRUEがあれば他が全部FALSE(有効basis)でもASK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["mutation_target"] = "true"
    basis = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS if d != "mutation_target"}
    a = make_assessment("これは対象を変えるので聞くべき", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる", result.surfaced_unknowns == ["これは対象を変えるので聞くべき"])


def test_explicit_unknown_forces_ask():
    print("\n[E] LLMが明示的にunknownと申告した場合もASK（fail-safe）")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["authority_boundary"] = "unknown"
    basis = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS if d != "authority_boundary"}
    a = make_assessment("承認境界が不明", impact, basis)
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("ASKになる", result.surfaced_unknowns == ["承認境界が不明"])


def test_ask_decision_without_question_blocks():
    print("\n[D] ASK判定なのにquestionが欠落/空 → SUPPRESSへ黙って倒さずBLOCK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["destructive_effect"] = "true"
    a = make_assessment("", impact, {})   # 空文字
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("clarification_blocked = True", result.clarification_blocked is True)
    check("surfaced_unknowns には入らない（空質問を人間に見せない）", result.surfaced_unknowns == [])


def test_ask_decision_with_missing_question_key_blocks():
    print("\n[D] ASK判定でquestionキー自体が無い → BLOCK")
    impact = {d: "false" for d in hla.DIMENSIONS}
    impact["external_effect"] = "true"
    a = {"missing_information": "x", "impact": impact, "basis": {}}   # questionキーなし
    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a],
    })
    check("clarification_blocked = True", result.clarification_blocked is True)


def test_missing_information_does_not_influence_decision():
    print("\n[design] missing_information の内容を変えても決定(ASK/SUPPRESS)は変わらない（annotation専用）")
    impact = {d: "false" for d in hla.DIMENSIONS}
    basis = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS}
    a1 = {"question": None, "missing_information": "authority", "impact": impact, "basis": basis}
    a2 = {"question": None, "missing_information": "presentation", "impact": impact, "basis": basis}
    r1 = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a1],
    })
    r2 = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a2],
    })
    check(
        "missing_informationの値に関わらず同じ決定になる（両方SUPPRESS）",
        r1.surfaced_unknowns == r2.surfaced_unknowns == [],
    )


def test_multiple_assessments_mixed_decisions():
    print("\n[E] 複数assessmentが混在する場合、それぞれ独立に評価される")
    impact_ask = {d: "false" for d in hla.DIMENSIONS}
    impact_ask["requested_scope"] = "true"
    impact_suppress = {d: "false" for d in hla.DIMENSIONS}
    basis_suppress = {d: dict(VALID_EXPLICIT) for d in hla.DIMENSIONS}

    a_ask = make_assessment("範囲が変わるので聞く", impact_ask, {})
    a_suppress = make_assessment(None, impact_suppress, basis_suppress)

    result = hla.normalize({
        "work_type": "EDIT_CREATE", "inferred_intent": "x", "inferred_deliverable": "x",
        "candidate_actions": [], "clarification_assessments": [a_ask, a_suppress],
    })
    check("ASK対象のみsurfacedに入る", result.surfaced_unknowns == ["範囲が変わるので聞く"])
    check("SUPPRESS対象は1件prunedに入る", len(result.pruned_unknowns) == 1)
    check("BLOCKは発生しない", result.clarification_blocked is False)


# =========================================================================
# work_type 正規化（Rev.1から不変）
# =========================================================================

def test_work_type_normalization_valid_value():
    print("\n[work_type] 正規の3値はそのままRESOLVEDになる")
    wt, status = hla.normalize_work_type("EDIT_CREATE")
    check("work_type保持", wt == "EDIT_CREATE")
    check("status=RESOLVED", status == "RESOLVED")


def test_work_type_normalization_rejects_unresolved_as_4th_value():
    print("\n[work_type] 'unresolved'という逸脱値は4番目のwork_typeとして許可しない")
    wt, status = hla.normalize_work_type("unresolved")
    check("work_type=None（4番目の値にしない）", wt is None, f"got {wt}")
    check("status=UNRESOLVEDへ分離", status == "UNRESOLVED", f"got {status}")


def test_work_type_normalization_rejects_pipe_notation():
    print("\n[work_type] パイプ表記の残骸も無効値としてNoneへ落とす")
    wt, status = hla.normalize_work_type("ORGANIZE | EDIT_CREATE")
    check("work_type=None", wt is None, f"got {wt}")
    check("status=UNRESOLVED", status == "UNRESOLVED")


def main():
    test_destructive_action_always_forces_approval_even_if_llm_said_none()
    test_destructive_action_even_when_llm_labels_it_as_allowed()
    test_external_send_always_forces_approval()
    test_read_only_action_no_approval()
    test_unknown_action_fails_closed_to_approval()
    test_non_object_root_returns_blocked_normalized_interpretation()
    test_missing_required_root_fields_returns_validation_notes()
    test_wrong_type_root_fields_return_validation_notes_without_classifying_actions()
    test_null_work_type_remains_valid_and_unresolved()
    test_posting_is_external_mutation_and_requires_approval()
    test_japanese_compound_keeps_source_and_does_not_inherit_write_allow()
    test_case_marker_toshite_preserves_bounded_write_candidate()
    test_case_marker_before_sequential_action_preserves_external_approval()
    test_compound_conjunction_allowlist_splits_comma_then_and_ampersand()
    test_ascii_comma_without_whitespace_is_not_split()
    test_ascii_comma_unknown_trailing_action_fails_closed()
    test_destructive_component_remains_most_restrictive_after_split()

    test_assessments_field_missing_blocks()
    test_assessments_field_null_blocks()
    test_assessments_field_wrong_type_blocks()
    test_empty_assessments_list_is_valid_clean_state()
    test_impact_value_missing_field_normalizes_to_unknown_and_asks()
    test_impact_value_null_normalizes_to_unknown()
    test_impact_value_json_boolean_is_invalid_normalizes_to_unknown()
    test_impact_value_garbage_string_normalizes_to_unknown()
    test_false_without_basis_upgrades_to_unknown_and_asks()
    test_false_with_invalid_basis_kind_upgrades_to_unknown()
    test_false_with_empty_refs_upgrades_to_unknown()
    test_false_with_empty_reason_upgrades_to_unknown()
    test_false_with_valid_explicit_request_basis_is_accepted()
    test_false_with_valid_not_applicable_basis_is_accepted()
    test_all_dimensions_false_with_valid_basis_suppresses()
    test_any_true_forces_ask_regardless_of_others()
    test_explicit_unknown_forces_ask()
    test_ask_decision_without_question_blocks()
    test_ask_decision_with_missing_question_key_blocks()
    test_missing_information_does_not_influence_decision()
    test_multiple_assessments_mixed_decisions()

    test_work_type_normalization_valid_value()
    test_work_type_normalization_rejects_unresolved_as_4th_value()
    test_work_type_normalization_rejects_pipe_notation()

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
