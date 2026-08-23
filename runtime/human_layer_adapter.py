#!/usr/bin/env python3
"""
human_layer_adapter.py — Deterministic Normalization Adapter (ume-harness Core)

2026-08-18 human裁定（Phase 3b→3c）: 12Bクラスのローカルモデルに「意図解釈」と
「Authority判定」と「確認要否判定」を全部やらせる設計は指示追従の限界に当たった
（Case3で2/5のauthority false negative、Case1で確認要否の指示無視を実測）。

対処方針: LLM(または他の自然語UX層)の責務を intent / deliverable / candidate_actions /
clarification_assessments の抽出までに縮小し、以下の決定論的処理をCore側に移す。

  1. Authority Overlay: candidate_actions を tool_policy.py の5クラスへ分類し、
     tool_policy.decide() の結果で required_human_approvals を**強制**する。
     LLMが approval不要と言おうが空リストで返そうが、DESTRUCTIVE / EXTERNAL_MUTATION /
     AUTHORITY_TOUCH は無条件で APPROVAL_REQUIRED として上書きする
     （「対象特定 ≠ 削除権限」の分離を保証する）。
  2. Clarification Impact判定: clarification_assessments（構造化必須フィールド）の
     各要素を6次元のimpact(true/false/unknown)で評価し、ASK/SUPPRESS/BLOCKを
     決定論的に導出する（設計書: design/clarification_impact_contract_v0.md Rev.2）。
  3. work_type と 解決状態の分離: `work_type` は3値 (RESEARCH/EDIT_CREATE/ORGANIZE)
     または None のみ。「UNRESOLVED」を第4のwork_typeにはしない。解決できたかどうかは
     別フィールド `classification_status` (RESOLVED/UNRESOLVED) で表現する。

2026-08-19〜20 経緯（keyword方式の廃止）: unresolved_facts(自由記述文字列)を
keywordマッチでカテゴリ分類してprune/keepする方式(UnknownCategory等)を実装・
実測したが、3×10 Sampling Contractで両モデルともGate FAIL（whack-a-mole構造。
表層の言い回しが毎trial微妙に変わり、keyword一致が追いつかない）。co独立レビュー
2ラウンドを経て、Clarification Impact Contract v0 Rev.2（本ファイル）へ置換した。
keyword方式のコードは削除済み（証跡は tests/evidence/ に恒久保全）。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tool_policy as tp  # noqa: E402

VALID_WORK_TYPES = {"RESEARCH", "EDIT_CREATE", "ORGANIZE"}

# --- Authority Overlay: candidate_action(自然語) -> SideEffect 分類キーワード ---
# 優先順位: DESTRUCTIVE > AUTHORITY_TOUCH > EXTERNAL_MUTATION > BOUNDED_WRITE > READ_ONLY
_DESTRUCTIVE_KEYWORDS = ["削除", "消去", "消す", "破棄", "上書き", "フォーマット", "delete", "remove"]
_AUTHORITY_TOUCH_KEYWORDS = ["設定変更", "権限変更", "ポリシー変更", "承認の変更", "policy", "permission"]
_EXTERNAL_MUTATION_KEYWORDS = [
    "送信", "送付", "公開", "発送", "メール", "購入", "支払い",
    "publish", "post", "send", "purchase", "pay",
]
_BOUNDED_WRITE_KEYWORDS = ["作成", "編集", "修正", "更新", "まとめ", "追記", "write", "edit", "create"]
_READ_ONLY_KEYWORDS = ["閲覧", "読み込み", "確認", "調査", "検索", "read", "view", "search"]


def classify_candidate_action(action_text: str) -> tp.SideEffect:
    text = action_text.lower()
    if any(k.lower() in text for k in _DESTRUCTIVE_KEYWORDS):
        return tp.SideEffect.DESTRUCTIVE
    if any(k.lower() in text for k in _AUTHORITY_TOUCH_KEYWORDS):
        return tp.SideEffect.AUTHORITY_TOUCH
    if any(k.lower() in text for k in _EXTERNAL_MUTATION_KEYWORDS):
        return tp.SideEffect.EXTERNAL_MUTATION
    if any(k.lower() in text for k in _BOUNDED_WRITE_KEYWORDS):
        return tp.SideEffect.BOUNDED_WRITE
    if any(k.lower() in text for k in _READ_ONLY_KEYWORDS):
        return tp.SideEffect.READ_ONLY
    return tp.SideEffect.UNKNOWN


@dataclass
class ActionDecision:
    action_text: str
    side_effect: tp.SideEffect
    decision: tp.Decision


def compute_authority_overlay(
    candidate_actions: list[str], tier: tp.Tier = tp.Tier.TIER_NORMAL
) -> list[ActionDecision]:
    """LLMの申告(required_human_approvals等)を一切信用せず、candidate_actionsを
    Core側で独立に再分類し、tier x side_effectの決定表からdecisionを導く。
    fail-closed: UNKNOWN分類はdecide()内で APPROVAL_REQUIRED になる。

    重要（Clarification Impact Contractとの責務分離・design/clarification_impact_contract_v0.md
    Gate Redefinition節参照）: この関数はClarification層のsemantic false-negativeを
    backstopしない。Clarification層の判断ミス（Assessment自体の見落とし・basisの
    意味的誤り）が結果として危険な行為の実行に至った場合にのみ、その実行自体を
    独立に止める。両者は責務が異なる別々の防御であり、「Clarificationが間違っても
    Authority Overlayがあるから大丈夫」という主張はしない。"""
    results = []
    for action in candidate_actions:
        se = classify_candidate_action(action)
        d = tp.decide(tier, se)
        results.append(ActionDecision(action_text=action, side_effect=se, decision=d))
    return results


def forced_required_approvals(candidate_actions: list[str], tier: tp.Tier = tp.Tier.TIER_NORMAL) -> list[str]:
    """APPROVAL_REQUIREDと判定されたactionのみを返す。LLMが空リストで
    approvalを返していても、この関数の出力が正（overlay="強制"）。"""
    overlay = compute_authority_overlay(candidate_actions, tier)
    return [d.action_text for d in overlay if d.decision == tp.Decision.APPROVAL_REQUIRED]


# --- Clarification Impact Contract v0 Rev.2 ---
# 設計書: design/clarification_impact_contract_v0.md（FROZEN）
# Structural Gate（本ファイルが担当・ゼロ欠陥要求）: 型・root存在・enum値・
#   根拠の形式的完全性。Semantic Gate（3×10 Sampling Contractで実測評価・
#   本ファイルの対象外）: basisの意味的真偽・候補の見落とし（KNOWN_RESIDUAL_SEMANTIC_RISK）。

DIMENSIONS = (
    "authority_boundary",
    "mutation_target",
    "destructive_effect",
    "external_effect",
    "requested_scope",
    "costly_rollback",
)


class ImpactValue(str, Enum):
    """許可値は厳密に3値の文字列のみ。JSON native boolean（true/false）は
    このEnumのいずれとも一致しないため自動的にINVALID扱いになる
    （tool_policy.py の SideEffect/Tier/Decision と同じ str-Enum流儀に統一）。"""
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class BasisKind(str, Enum):
    EXPLICIT_REQUEST = "explicit_request"
    NOT_APPLICABLE = "not_applicable"


class AssessmentDecision(str, Enum):
    ASK = "ASK"
    SUPPRESS = "SUPPRESS"
    BLOCK = "BLOCK"   # 構造的異常（assessment欠落・question欠落）


def normalize_impact_value(raw) -> ImpactValue:
    """B: Strict Normalization Table。else節でFALSEに倒さない。
    欠落/null/JSON native boolean/型不一致/未知の文字列は全てUNKNOWNへ倒す。"""
    if raw == "true":
        return ImpactValue.TRUE
    if raw == "false":
        return ImpactValue.FALSE
    if raw == "unknown":
        return ImpactValue.UNKNOWN
    return ImpactValue.UNKNOWN


def is_valid_basis(raw_basis) -> bool:
    """C: FALSE Basis Contract。basisの意味的な正しさ(refs/reasonの内容が事実と
    一致しているか)は検証しない（Semantic Gateの管轄・KNOWN_RESIDUAL_SEMANTIC_RISK）。
    ここで検証するのは形式的完全性のみ（Structural Gate）。"""
    if not isinstance(raw_basis, dict):
        return False
    kind = raw_basis.get("kind")
    if kind == BasisKind.EXPLICIT_REQUEST.value:
        refs = raw_basis.get("refs")
        return isinstance(refs, list) and len(refs) > 0 and all(
            isinstance(r, str) and r.strip() for r in refs
        )
    if kind == BasisKind.NOT_APPLICABLE.value:
        reason = raw_basis.get("reason")
        return isinstance(reason, str) and reason.strip() != ""
    return False


def validate_dimension(raw_value, raw_basis) -> ImpactValue:
    """FALSEは有効なbasisを伴わない限りUNKNOWNへ強制的に昇格する。"""
    value = normalize_impact_value(raw_value)
    if value == ImpactValue.FALSE and not is_valid_basis(raw_basis):
        return ImpactValue.UNKNOWN
    return value


@dataclass
class AssessedClarification:
    """clarification_assessments 1件分の評価結果。"""
    question: str | None
    decision: AssessmentDecision
    raw: dict = field(default_factory=dict)


def evaluate_clarification_assessment(raw_assessment) -> AssessedClarification:
    """D: Candidate/Assessment Lifecycle + E: Deterministic ASK/SUPPRESS。
    missing_informationはここでは一切参照しない（annotation専用・決定に不関与）。"""
    if not isinstance(raw_assessment, dict):
        return AssessedClarification(question=None, decision=AssessmentDecision.BLOCK, raw={})

    impact = raw_assessment.get("impact")
    basis = raw_assessment.get("basis")
    if not isinstance(impact, dict):
        impact = {}
    if not isinstance(basis, dict):
        basis = {}

    validated = {
        dim: validate_dimension(impact.get(dim), basis.get(dim))
        for dim in DIMENSIONS
    }

    if any(v == ImpactValue.TRUE for v in validated.values()):
        decision = AssessmentDecision.ASK
    elif any(v == ImpactValue.UNKNOWN for v in validated.values()):
        decision = AssessmentDecision.ASK   # fail-safe
    else:
        decision = AssessmentDecision.SUPPRESS   # 全次元が検証済みFALSE

    question = raw_assessment.get("question")
    if decision == AssessmentDecision.ASK:
        if not isinstance(question, str) or not question.strip():
            # ASKなのにquestionが無い＝壊れた出力。SUPPRESSへ黙って倒さずBLOCK。
            return AssessedClarification(question=None, decision=AssessmentDecision.BLOCK, raw=raw_assessment)

    return AssessedClarification(question=question, decision=decision, raw=raw_assessment)


def evaluate_clarification_assessments(raw_assessments) -> list[AssessedClarification]:
    """トップレベル。clarification_assessments フィールド自体の構造を先に検証する。
    欠落/null/非list型は構造的省略としてBLOCKする（B3のstructural部分）。"""
    if raw_assessments is None or not isinstance(raw_assessments, list):
        return [AssessedClarification(question=None, decision=AssessmentDecision.BLOCK, raw={})]
    if not raw_assessments:
        return []   # 空リストは正当な主張（「聞くべきことはない」）として受理する
    return [evaluate_clarification_assessment(a) for a in raw_assessments]


# --- work_type / classification_status 分離 ---
def normalize_work_type(raw_work_type) -> tuple[str | None, str]:
    """raw_work_type が3値のいずれかならそのまま採用しRESOLVED。
    それ以外（None・空文字・"unresolved"等の逸脱値・パイプ区切り等）は
    work_type=None・classification_status=UNRESOLVEDへ正規化する。
    UNRESOLVEDを第4のwork_type値として許可しない。"""
    if raw_work_type in VALID_WORK_TYPES:
        return raw_work_type, "RESOLVED"
    return None, "UNRESOLVED"


@dataclass
class NormalizedInterpretation:
    work_type: str | None
    classification_status: str
    inferred_intent: str
    inferred_deliverable: str
    required_human_approvals: list[str]
    surfaced_unknowns: list[str]
    pruned_unknowns: list[str] = field(default_factory=list)
    action_overlay: list[ActionDecision] = field(default_factory=list)
    clarification_blocked: bool = False
    blocked_clarification_notes: list[str] = field(default_factory=list)


def normalize(
    llm_output: dict, tier: tp.Tier = tp.Tier.TIER_NORMAL, workspace_context: str = ""
) -> NormalizedInterpretation:
    """LLM生出力（work_type, inferred_intent, inferred_deliverable,
    candidate_actions, clarification_assessments）を受け取り、Authority Overlay +
    Clarification Impact判定 + work_type正規化を適用した結果を返す。
    workspace_contextは現バージョンでは未使用（Rev.1のCONTENT_SCOPE条件付きprune
    ロジックと共に廃止。引数はプロトタイプ互換のため残す）。"""
    work_type, status = normalize_work_type(llm_output.get("work_type"))
    candidate_actions = llm_output.get("candidate_actions", [])
    raw_assessments = llm_output.get("clarification_assessments")

    overlay = compute_authority_overlay(candidate_actions, tier)
    approvals = [d.action_text for d in overlay if d.decision == tp.Decision.APPROVAL_REQUIRED]

    evaluated = evaluate_clarification_assessments(raw_assessments)

    surfaced: list[str] = []
    pruned: list[str] = []
    blocked_notes: list[str] = []
    blocked = False
    for item in evaluated:
        if item.decision == AssessmentDecision.ASK:
            surfaced.append(item.question)
        elif item.decision == AssessmentDecision.SUPPRESS:
            pruned.append(
                item.question or item.raw.get("missing_information") or "(no description)"
            )
        else:  # BLOCK
            blocked = True
            note = (
                item.raw.get("question")
                or item.raw.get("missing_information")
                or "clarification_assessments structurally invalid"
            )
            blocked_notes.append(note)

    return NormalizedInterpretation(
        work_type=work_type,
        classification_status=status,
        inferred_intent=llm_output.get("inferred_intent", ""),
        inferred_deliverable=llm_output.get("inferred_deliverable", ""),
        required_human_approvals=approvals,
        surfaced_unknowns=surfaced,
        pruned_unknowns=pruned,
        action_overlay=overlay,
        clarification_blocked=blocked,
        blocked_clarification_notes=blocked_notes,
    )
