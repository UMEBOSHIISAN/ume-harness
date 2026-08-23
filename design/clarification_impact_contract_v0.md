# Clarification Impact Contract v0（Rev.2・FROZEN・実装対象）

> 状態: **FROZEN**（2026-08-20 human裁定）。co再監査でもB1/B3が「未closed」と判定されたが、
> human裁定によりこれ以上Core側へ条件分岐を追加してB1/B3を構造的に閉じようとする試みは
> **禁止**。Rev.2はこの形のまま実装対象として凍結する。理由はGate Redefinition節を参照。
>
> 経緯: Rev.1はco独立レビューでHOLD・3件のblocking defect（B1/B2/B3）。Rev.2改訂後の
> 再監査でもHOLD・B2のみclosed、B1/B3は「残存」（`tests/for_codex/
> 20260820b_clarification_impact_contract_rereview_result.md`参照）。ただしB1/B3として
> 指摘された内容は、Rev.2自身がF節Residual Risksとして**自己申告済み**の限界と同一であり、
> 「LLMの意味理解に起因する問題であり、Core側の決定論コードだけでは原理的に完全解消できない」
> という性質を持つ。これ以上の条件分岐追加は安全性向上より複雑化・第二分類器化のリスクが
> 大きいとhumanが裁定し、Gate自体を二層に再定義した（下記）。

## Rev.1 → Rev.2 changelog（何を・なぜ変えたか）

```yaml
co_blocking_defects（全て妥当・全て対応）:
  B1: LLMが6 impactを全FALSEと自己申告した場合、semantic false-negativeを
      防ぐ構造が無かった（Authority Overlayはこれをbackstopしない、という
      Rev.1の説明も不正確だった → 本改訂で訂正）
  B2: missing/invalid impact values（欠落フィールド・不正enum・型不一致）が
      無検証でSUPPRESS側へ落ち得た
  B3: ClarificationCandidate自体をLLMが省略した場合の検出・fail-safe規約が
      無かった

対応方針（human裁定）:
  - 条件分岐を3個足す形の場当たり対応をしない
  - ClarificationCandidateを「optionalな生成物」として扱う設計自体をやめ、
    ClarificationAssessmentを「毎回必須で出力される構造」に変更する（B3対応）
  - 許可値を厳密に3値(true/false/unknown)のみとし、それ以外は全てUNKNOWN
    相当として扱う。normalize処理でfalseへのなし崩し変換を禁止する（B2対応）
  - FALSEを「無料の自己申告」にせず、各次元のFALSEに根拠(basis)を要求する。
    basisが欠落・不正ならUNKNOWNへ昇格させる（B1対応。ただしこれは
    「LLMの誤った申告を完全に防ぐ」ものではなく、あくまで
    「無根拠なFALSEを構造的に通さない」という限定的な対策であることを
    Fで明記する）
  - keyword/regexクロスチェックは再導入しない（Rev.1の却下判断を維持）
  - missing_informationはannotation専用のまま変更しない
```

---

## Gate Redefinition（2026-08-20 human裁定・FROZEN）

co再監査は、B1/B3を「Rev.2でも未closed」と判定した。この判定自体は妥当
（CONFIRMED）。しかしB1/B3の実体は以下のとおりであり、**これ以上Core側の
決定論コードだけで完全に閉じようとするのは原理的に狙うべきではない**。

```yaml
B1（全FALSE自己申告のsemantic false-negative）:
  例: LLMが "false" + `basis: {kind: not_applicable, reason: "read-onlyなので該当しない"}`
      という形式的に完璧だが事実と異なる根拠を6次元全てに付けた場合、
      Coreはbasisの「形式」しか検証しないため、これを弾けない
  これを完全に検出しようとすると:
    Core が basis の意味的真偽を判定する必要がある
    → そのためには「実際の対象操作が本当にread-onlyか」を再度意味理解する
      第二の分類器が必要になる
    → Rev.1で却下した keyword crosscheck の問題（誰がverifierを検証するのか）が
      形を変えて復活する

B3（Assessment省略のrecall問題）:
  例: `clarification_assessments: []` が「本当に候補ゼロ」なのか
      「LLMが見落とした」のかは、構造だけでは区別できない
  「最低1件書け」という制約にすると、今度は本当に該当なしのケースで
  架空のassessmentを強制することになり、別の歪みを生む
  これは schema validation の問題ではなく、モデルの **recall（気づく能力）の問題**
```

### 二層Gate（Structural Gate / Semantic Gate）

上記の性質の違いに基づき、Gateを2種類に分離する。**1つの基準で両方を測ろうと
したことが、co再監査が「HOLDのまま」から抜け出せなかった構造的原因だった。**

```yaml
STRUCTURAL_GATE:
  対象: 型・root存在・enum値・根拠の形式的完全性・schema違反・authority境界
  例: clarification_assessments キー欠落/null/非list / impact値が3値以外 /
      FALSEなのにbasisが無い・kindが不正 / questionが空なのにASK
  要求水準: ゼロ欠陥（決定論コードで検証可能なため、妥協しない）
  検証方法: 単体テスト（tests/test_human_layer_adapter.py・LLM呼び出し不要）
  現状: co再監査でB2 = closed = true（達成済み）

SEMANTIC_GATE:
  対象: LLMの意味理解に依存する欠陥（basisの内容が事実と一致しているか・
        本来問うべき候補に気づいているか）
  例: B1（尤もらしいが誤ったbasis）・B3（候補の見落とし）
  要求水準: ゼロ欠陥を求めない（原理的に到達不可能なため）。
            実測レートで評価する
  検証方法: 既存の frozen Case1 v2 Sampling Contract
            （`tests/case1_v2_sampling_contract.md`・無変更のまま再利用）
  現状: KNOWN_RESIDUAL_SEMANTIC_RISK（未測定・実装後にfresh runで測定する）
```

### B1/B3の再分類（FROZEN）

```yaml
B1: STRUCTURAL部分（無根拠FALSEの構造的通過） → closed（basis contractで対応済み）
    SEMANTIC部分（basisの意味的真偽） → KNOWN_RESIDUAL_SEMANTIC_RISK
      （Core側では対応しない。3×10 Sampling Contractで実測する）

B3: STRUCTURAL部分（rootフィールド自体の欠落） → closed（fail-safe BLOCKで対応済み）
    SEMANTIC部分（空リスト/部分省略が正当かどうかの判別） → KNOWN_RESIDUAL_SEMANTIC_RISK
      （Core側では対応しない。3×10 Sampling Contractで実測する）
```

**「closed=true」をこれ以上coに要求しない。** B1/B3のSEMANTIC部分は、Core側の
決定論コードの守備範囲外であるとhumanが裁定した。これは基準を緩めたのではなく、
**違う種類の故障を、違う測定器（単体テスト vs 実測サンプリング）で測る**という
Gate設計の訂正である。

### この裁定の直接の帰結

- Rev.2のCore側ロジック（A〜G）へのこれ以上の変更は禁止（第4のCore改訂ラウンドは行わない）
- Rev.2を**この形のまま実装する**（次はH）
- 実装後、frozen Case1 v2 Sampling Contract（3 batch×10 trial×Claude/Gemma）を
  fresh runで実行し、SEMANTIC_GATEの実態を測定する
- Case3/4 authority regressionも同一セッションで再実施する
  （intent_interpreter.mdのプロンプト全体が変わるため）
- Phase 4（Package Assembly）は上記実測が終わるまで引き続きHOLD

---

## 発見事項（Rev.1から変更なし・再掲）

設計に着手する前に、パッケージ直下の`package_manifest.json`・`README.md`・`adapters/`・
`scripts/`を確認した。当初「実害ゼロ」と報告したが、human裁定「consumer影響はUNKNOWN
のまま断定するな」を受けて再調査し、以下のとおり訂正した（co独立レビューでも
`7_stale_package_surface.verdict = CONFIRMED`として独立確認済み）。

### CONFIRMED

```yaml
finding_1: STALE_PACKAGE_MANIFEST_MISMATCH
  package_manifest.json / README.md の作成日時: 2026-08-18 12:39
  参照パス runtime/hooks/unified_tool_classifier.py 等は
  ume-harness パッケージ内には実在しない（find で確認・0件）

finding_2: REAL_CONSUMER_EXISTS
  scripts/install.sh, scripts/uninstall.sh, scripts/health_check.py,
  adapters/claude-code/README.md, adapters/claude-code/settings.json.fragment
  が全て同じ非実在パスを参照する実consumer一式である

finding_3: INSTALL.SH FAILS SAFE
  scripts/install.sh は set -euo pipefail の下で最初のcpが即座に失敗し
  exitする。ユーザーの実`~/.claude/hooks/`には一切書き込まれない

finding_4: LIVE_HOOKS_ARE_REAL_BUT_INDEPENDENT
  ~/.claude/settings.json実読の結果、PreToolUse/Stop hookとして
  unified_tool_classifier.py/unified_stop_router.pyが本セッションを
  現在進行形で制御している実物と確認。ただしume-harness/install.sh経由ではなく
  別系統（agyによる直接デプロイと推定・ASSUMPTION）
```

### 独立blockerとしての扱い（human裁定・変更なし）

```yaml
P0-A: stale package surface closure（本設計とは独立）
P0-B: Clarification Impact implementation readiness（本設計文書の対象）
```

両方閉じるまでPhase 4 prospective runを始めない。P0-Aは本設計文書では修正しない。

---

## A. Revised Schema（改訂スキーマ）

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class ImpactValue(str, Enum):
    """許可値は厳密に3値の文字列のみ。JSONのnative boolean（true/false）は
    このEnumのいずれの値とも一致しないため、自動的にINVALID扱いになる
    （既存 tool_policy.py の SideEffect/Tier/Decision と同じ str-Enum流儀に
    統一。JSON boolean と文字列enumの不一致問題(co指摘B2)を、変換を書かず
    「文字列以外は最初から一致しない」という設計で構造的に潰す）。"""
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

class BasisKind(str, Enum):
    """FALSEの根拠種別。この2種のみ許可（B1対応・Cで詳述）。"""
    EXPLICIT_REQUEST = "explicit_request"   # 依頼文/workspace_contextに明示的根拠がある
    NOT_APPLICABLE = "not_applicable"       # この次元がこの候補の性質上そもそも該当しない

@dataclass
class Basis:
    kind: Optional[str]           # BasisKindのいずれか。それ以外は無効
    refs: Optional[list[str]]     # kind=explicit_requestの場合必須（非空文字列のリスト）
    reason: Optional[str]         # kind=not_applicableの場合必須（非空文字列）

@dataclass
class ClarificationImpact:
    """6次元。全フィールド必須。値は厳密にImpactValueの3値のみ有効。"""
    authority_boundary: Optional[str]
    mutation_target: Optional[str]
    destructive_effect: Optional[str]
    external_effect: Optional[str]
    requested_scope: Optional[str]
    costly_rollback: Optional[str]

@dataclass
class ClarificationBasis:
    """impactの各FALSE値に対応するbasis。TRUE/UNKNOWNには不要（Cで詳述）。"""
    authority_boundary: Optional[Basis]
    mutation_target: Optional[Basis]
    destructive_effect: Optional[Basis]
    external_effect: Optional[Basis]
    requested_scope: Optional[Basis]
    costly_rollback: Optional[Basis]

@dataclass
class ClarificationAssessment:
    """LLM出力の必須rootオブジェクト（Dで詳述）。question はCoreがSUPPRESSを
    解決した場合のみnull許容。ASK解決時にquestionが欠落/不正ならBLOCK。"""
    question: Optional[str]
    missing_information: Optional[str]   # annotation専用。決定に不関与（Rev.1から変更なし）
    impact: ClarificationImpact
    basis: ClarificationBasis
```

### LLM出力スキーマ（`unresolved_facts`を置換）

```yaml
clarification_assessments: list[ClarificationAssessment]   # フィールド自体が必須
  # 空リスト[] = 「検討した結果、聞くべきことはない」という正当な主張
  # フィールド欠落・null・非リスト型 = 構造的異常 → fail-safe（Dで詳述）
```

`unresolved_facts: list[str]`（自由記述の文字列）から`clarification_assessments:
list[ClarificationAssessment]`（構造化必須オブジェクトのリスト）へ全面置換する。

---

## B. Strict Normalization / Validation Table（co指摘B2対応）

各次元の値は以下の表に従って検証する。**「else節でfalse扱いにする」を一切行わない。**

| 入力 | 判定 |
|---|---|
| 文字列 `"true"` | `ImpactValue.TRUE` として有効 |
| 文字列 `"false"` | `ImpactValue.FALSE` として有効（ただしCのbasis検証を通過する必要あり） |
| 文字列 `"unknown"` | `ImpactValue.UNKNOWN` として有効 |
| フィールド欠落（キー自体が無い） | **INVALID → UNKNOWN相当** |
| `null` | **INVALID → UNKNOWN相当** |
| JSON native boolean（`true`/`false`） | **INVALID → UNKNOWN相当**（文字列でないため） |
| 数値・空文字列・その他の文字列（`"FALSE"`, `"yes"`, `"0"`等） | **INVALID → UNKNOWN相当** |
| オブジェクト・配列 | **INVALID → UNKNOWN相当** |

`clarification_assessments`フィールド自体、および各`ClarificationAssessment`の
`impact`/`basis`サブオブジェクトについても同じ原則: **欠落・null・型不一致は
全て「安全側」＝ASKを要求する状態に倒す。** 「わからなければfalse」という
经路は設計上存在しない。

---

## C. FALSE Basis Contract（co指摘B1対応・限定的措置であることを明記）

**FALSEを無根拠な自己申告のまま受理しない。** 各次元がFALSEの場合、対応する
`basis`が以下のいずれかの形で有効でなければ、そのFALSEはUNKNOWNへ昇格する。

```yaml
basis.kind == "explicit_request":
  必須: refs が非空文字列のリスト（依頼文/workspace_contextの該当箇所への参照）
  例:
    impact.requested_scope: "false"
    basis.requested_scope: {kind: explicit_request, refs: ["raw_request全体が対象を明示"]}

basis.kind == "not_applicable":
  必須: reason が非空文字列（この次元がそもそも該当しない理由）
  例:
    impact.destructive_effect: "false"
    basis.destructive_effect: {kind: not_applicable, reason: "候補actionに削除・上書き相当の操作を含まない"}

それ以外（kind欠落・kind不正・refs/reason欠落や空）:
  → basis無効 → 対応するimpact値はUNKNOWNへ強制的に昇格する
```

**basisはClarification層内の第二の分類器ではない。** Rev.1で却下した
「keyword/regexクロスチェック」との違いを明確にする:

```yaml
却下したもの（keyword crosscheck）:
  Core側が独自にキーワード一致でimpact値を「再計算」する
  → LLMの申告を上書きする第二の判定ロジック

今回導入するもの（basis contract）:
  Core側はimpact値を一切再計算しない。LLMが申告したFALSEに
  「形式的に有効な根拠オブジェクトが添付されているか」だけを検証する
  → 判定ロジックではなく、入力の構造的完全性チェック
  → basisの中身（refsの参照先が本当に妥当か等）の意味的な正しさは検証しない
```

### 明記すべき限界（human裁定により必須）

**basis contractは「無根拠なFALSEを構造的に弾く」ものであり、「LLMが尤もらしい
間違ったbasisを生成すること」までは防げない。** 例えば
`basis: {kind: not_applicable, reason: "この操作に外部送信は含まれない"}`が
形式的に有効でも、その中身が事実と異なる可能性は残る。これは決定論コードだけでは
解消できない**残存リスク**であり、Fで明記する。「basisがあるから安全になった」
とは主張しない。

---

## D. Candidate / Assessment Lifecycle（co指摘B3対応）

```text
LLM (intent_interpreter.md)
  ↓
出力: work_type, inferred_intent, inferred_deliverable, candidate_actions,
      clarification_assessments: list[ClarificationAssessment]  ← 必須フィールド
  ↓
Core: 構造検証
  clarification_assessments キー自体が欠落/null/非リスト型か？
    YES → CLARIFICATION_ASSESSMENT_MISSING 状態
          → fail-safe: 人間へ「解釈が不完全なため確認が必要」を提示（BLOCK相当）
          → 個別のASK/SUPPRESSには進まない
    NO  → 各要素を B の検証表 + C の basis contract に通す
  ↓
各要素についてEの決定規則を適用 → ASK or SUPPRESS
  ↓
ASKと決定された要素について、questionが有効な非空文字列か？
  NO → fail closed（BLOCK。空質問を人間に見せない・SUPPRESSへ黙って倒さない）
  YES → surfaced_unknowns へ追加
SUPPRESSと決定された要素は pruned_unknowns へ追加（無言で消さない・Rev.1から変更なし）
```

**重要**: これは「LLMが個々の不明点を漏らさず全部言う」ことまでは保証しない
（真にLLMが気づかなかった曖昧性は、依然として気づかれないまま）。保証するのは
「`clarification_assessments`という構造そのものが存在しない・壊れている」という
**構造的省略**を検出することのみ。この区別をFで明記する。

---

## E. Deterministic ASK/SUPPRESS Pseudocode

```python
def normalize_impact_value(raw) -> ImpactValue:
    """B表を実装。else節でFALSEに倒さない。"""
    if raw == "true":
        return ImpactValue.TRUE
    if raw == "false":
        return ImpactValue.FALSE
    if raw == "unknown":
        return ImpactValue.UNKNOWN
    return ImpactValue.UNKNOWN  # 欠落/null/boolean/型不一致/その他 すべてここ


def is_valid_basis(basis: Optional[Basis]) -> bool:
    if basis is None:
        return False
    if basis.kind == BasisKind.EXPLICIT_REQUEST.value:
        return bool(basis.refs) and all(isinstance(r, str) and r.strip() for r in basis.refs)
    if basis.kind == BasisKind.NOT_APPLICABLE.value:
        return bool(basis.reason) and basis.reason.strip() != ""
    return False


def validate_dimension(raw_value, raw_basis: Optional[Basis]) -> ImpactValue:
    value = normalize_impact_value(raw_value)
    if value == ImpactValue.FALSE:
        if not is_valid_basis(raw_basis):
            return ImpactValue.UNKNOWN   # C: 無根拠FALSEはUNKNOWNへ昇格
    return value


DIMENSIONS = [
    "authority_boundary", "mutation_target", "destructive_effect",
    "external_effect", "requested_scope", "costly_rollback",
]


class AssessmentDecision(str, Enum):
    ASK = "ASK"
    SUPPRESS = "SUPPRESS"
    BLOCK = "BLOCK"   # 構造的異常（D: assessment欠落 / question欠落）


def clarification_impact_policy(assessment: Optional[ClarificationAssessment]) -> AssessmentDecision:
    if assessment is None:
        return AssessmentDecision.BLOCK   # B3: 構造的省略はBLOCK

    validated = {
        dim: validate_dimension(
            getattr(assessment.impact, dim, None),
            getattr(assessment.basis, dim, None),
        )
        for dim in DIMENSIONS
    }

    if any(v == ImpactValue.TRUE for v in validated.values()):
        decision = AssessmentDecision.ASK
    elif any(v == ImpactValue.UNKNOWN for v in validated.values()):
        decision = AssessmentDecision.ASK   # fail-safe
    else:
        decision = AssessmentDecision.SUPPRESS   # 全次元が「検証済みFALSE」

    if decision == AssessmentDecision.ASK:
        if not assessment.question or not assessment.question.strip():
            return AssessmentDecision.BLOCK   # D: ASKなのにquestionが無い＝壊れた出力
    return decision


def clarification_assessments_policy(raw_assessments) -> AssessmentDecision | list[...]:
    """トップレベル。リストの構造そのものを先に検証する。"""
    if raw_assessments is None or not isinstance(raw_assessments, list):
        return AssessmentDecision.BLOCK   # D: フィールド自体の構造的欠落
    return [clarification_impact_policy(a) for a in raw_assessments]
```

`missing_information`はいずれの関数にも引数として渡していない（Rev.1の方針を
維持: annotation専用・決定ロジックから構造的に排除）。

---

## F. Residual Risks（正直な限界の明記・human裁定により必須）

```yaml
resolved_by_this_design（構造的に解消したもの）:
  - malformed/missing impact values が無検証でSUPPRESSへ落ちる経路（B2）
  - clarification_assessments フィールド自体の構造的欠落を検出できない状態（B3の一部）
  - 無根拠なFALSE自己申告がそのまま通る経路（B1の一部・構造面のみ）

NOT resolved（決定論コードだけでは解消できない・実測でしか確認できない）:
  - LLMが個々の不明点に**気づかない**こと自体（構造は「気づいたことを漏らさず
    処理する」ことしか保証しない。「何に気づくべきか」はモデル性能の問題）
  - LLMが形式的に有効だが意味的に誤ったbasisを生成すること
    （例: 実際はdestructiveな操作なのに"not_applicable"と尤もらしく主張する）
  - basisのrefs/reasonが依頼文の実際の内容と整合しているかの意味検証
    （Core側はrefsが「非空文字列のリストか」しか見ない。参照先の正しさは見ない）

明示的に主張しないこと:
  - 「basisがあるから安全になった」とは言わない。構造上のfail-open経路を
    減らしただけであり、semantic false-negative率は実測（3×10 Sampling
    Contract再実行）でしか確認できない
  - Authority Overlayが本設計のsemantic false-negativeをbackstopするとは
    言わない（Rev.1の誤った説明の訂正。次項参照）
```

### Authority Overlayとの関係の訂正（Rev.1からの重要な訂正）

Rev.1は以下のように書いていた（誤り。撤回する）:

> ~~LLMが過小申告(false)しても、実際に危険な行為に至る場合は、その行為自体が
> compute_authority_overlayで独立に再チェックされる（二重の安全網）~~

co独立レビューの指摘どおり、これは不正確だった。正しくは:

```yaml
Authority Overlay:
  対象: candidate_actions（実行しようとしている行為）
  防ぐもの: 未承認のDESTRUCTIVE/EXTERNAL_MUTATION/AUTHORITY_TOUCH実行

Clarification Impact Contract:
  対象: unresolved_facts（LLMが認識した不明点）
  防がないもの: Clarificationのsemantic false-negative自体
    （LLMが「本当は聞くべきだった」ことに気づかなかった、または
    気づいたが誤ってFALSEと申告したケース）

関係:
  Authority Overlayは、Clarificationのfalse-negativeが**結果として**
  危険な行為の実行に至った場合にのみ、その実行自体を独立に止める。
  Clarification層の判断ミスそのものを検出・修正するものではない。
  両者は責務が異なる別々の防御であり、「Clarificationが間違っても
  Authority Overlayがあるから大丈夫」という主張はしない。
```

---

## G. Exact Minimal Implementation Delta（Rev.2版）

```yaml
変更対象:
  ux/japanese-human-layer/prompts/intent_interpreter.md:
    unresolved_facts: list[str] を廃止し、
    clarification_assessments: list[ClarificationAssessment] （Aのスキーマ）を
    必須出力として要求する。プロンプト内で「このフィールドは省略できない。
    聞くべきことがなければ空リストを返す」ことを明示する

  runtime/human_layer_adapter.py:
    追加:
      ImpactValue, BasisKind, Basis, ClarificationImpact, ClarificationBasis,
      ClarificationAssessment, AssessmentDecision
      normalize_impact_value(), is_valid_basis(), validate_dimension(),
      clarification_impact_policy(), clarification_assessments_policy()
    削除（Rev.1で予告済み・変更なし）:
      UnknownCategory, _CATEGORY_PATTERNS, _CATEGORY_PRIORITY,
      _ALWAYS_KEEP_CATEGORIES, _ALWAYS_PRUNE_CATEGORIES,
      classify_unknown_category(), has_concrete_resolvable_context(),
      should_surface_unknown(), 旧prune_unresolved_facts()
    変更:
      normalize() が clarification_assessments_policy() を呼ぶよう更新。
      AssessmentDecision.BLOCK が返った場合の扱いをNormalizedInterpretationに
      新フィールド（例: clarification_blocked: bool）として追加するか、
      classification_status を再利用して表現するかは実装時に確定する

  tests/test_human_layer_adapter.py:
    pruning関連の既存テストを新schema入力へ全面書き換え。加えて以下を新規追加:
      - clarification_assessments キー欠落 → BLOCK
      - impact値が欠落/null/boolean/不正文字列 → UNKNOWN扱い → ASK
      - FALSE + basis欠落 → UNKNOWNへ昇格 → ASK
      - FALSE + 有効なbasis(explicit_request/not_applicable) → SUPPRESS成立
      - 全次元FALSE+全basis有効 → SUPPRESS
      - decision=ASKだがquestion欠落/空 → BLOCK

非変更対象（ハード制約・Rev.1から変更なし）:
  runtime/tool_policy.py 全体
  compute_authority_overlay() / classify_candidate_action() / forced_required_approvals()
  Case1 v2 意味論・閾値（case1_acceptance_v2_spec.md）
  Sampling Contract（case1_v2_sampling_contract.md）
  missing_information の annotation専用ステータス
```

---

## H. Review History（完了・凍結の根拠）

```yaml
round_1:
  target: Rev.1
  reviewer: co
  verdict: HOLD
  blocking_defects: [B1, B2, B3]
  result_path: tests/for_codex/20260820_clarification_impact_contract_review_result.md

round_2:
  target: Rev.2
  reviewer: co
  verdict: HOLD
  B1: closed=false（semantic部分残存・constatedとおりstructural部分は対応済み）
  B2: closed=true
  B3: closed=false（semantic部分残存・structural部分は対応済み）
  new_defects: none
  result_path: tests/for_codex/20260820b_clarification_impact_contract_rereview_result.md

human_ruling_20260820:
  decision: >
    B1/B3のsemantic部分をこれ以上Core側の条件分岐で閉じようとしない。
    Gate Redefinition節のとおり二層Gateへ再定義し、Rev.2をこの形でFREEZEし実装する。
    第4のCore改訂ラウンド・第3のco独立レビューは行わない。
  authority: human（CC/coいずれも自らGOを宣言していない。人間が直接裁定した）
```

**本文書はFROZEN。実装フェーズへ移行する。** これ以上のA〜Gへの変更は、
Semantic Gate（3×10 Sampling Contract）の実測結果を踏まえた別途の
human裁定なしには行わない。

## 実装状況（完了・2026-08-20）

Rev.2は`runtime/human_layer_adapter.py`・`ux/japanese-human-layer/prompts/intent_interpreter.md`
へ実装済み（A〜Gに厳密準拠。追加の条件分岐・keyword/regex経路の再導入なし）。

```yaml
Structural Gate: 42/42 単体テストPASS（tests/test_human_layer_adapter.py）
Authority Regression (Case3/4 fresh run): 6/6, false_negative=0, leak=0
  (tests/evidence/case34_rev2_regression_20260820/)
Semantic Gate (Case1 v2 Sampling Contract fresh run):
  claude: pooled=0.0%(0/30) -> PASS
  gemma:  pooled=93.3%(28/30) -> FAIL
  (tests/evidence/case1_sampling_contract_rev2_20260820/CLASSIFICATION_AND_GATE_RESULT.md)
```

**モデルによってGate結果が割れた（Claude PASS / Gemma FAIL）。** Phase 4
（Package Assembly）はこの状態を踏まえたhuman判断があるまで引き続きHOLD。
