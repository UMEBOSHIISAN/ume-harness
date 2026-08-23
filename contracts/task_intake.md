# Task Intake Contract (Portable — Decision Batching)

> 目的: タスク着手後の「細切れ確認」「都度の承認往復」を根絶し、着手前に1回で必要な判断を確定させる。
> 適用範囲: ume-harness Core | 状態: ENFORCED
> 由来: 元実装（task_intake_contract.md）は個人パス・個人語彙を含まない、既に汎用的な内容
> だったため、そのまま採用する（監査で DROP 対象なしと判定済み）。

## 着手前3大抽出項目（Intake Extraction）

タスク着手時（または提案時）、コードを書く/実行する前に必ず以下の3項目を構造化して抽出する。

```
1. required_human_decisions   人間の方針決定が必要な項目
2. required_approvals         Execution Gate / 変更が必要な保護対象（authority_contract.md参照）
3. unresolved_unknowns        リポジトリ・入力内に証拠がなく、人間に確認すべき前提
```

## 一括提示の規律（Decision Batching Rule）

- **一括提示**: 未解決の `required_human_decisions` / `required_approvals` がある場合、
  作業途中で1つずつ質問せず、着手前の最初のターンでまとめて1画面で提示する
- **細切れ質問の禁止**: 複数ターンに分けて連続質問することは禁止
- **即時実行の条件**: 上記3項目がすべて解決済み（または事前合意済み）の場合は、
  追加の質問ターンを挟まず直ちに実行へ入る
