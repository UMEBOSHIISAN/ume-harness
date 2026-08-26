# Autonomous Stop Contract (Portable)

> 目的: タスク完了後の無駄な確認ターン消費を根絶し、完了条件充足時に自律停止する。
> 適用範囲: ume-harness Core | 状態: ACCEPTANCE PREDICATE IMPLEMENTED / HOST STOP NOT WIRED
> 訂正（2026-08-18 human裁定）: 元の完了判定は「テスト全通・diff精査」という開発（コード）タスク
> 前提だった。Research/Organize等コードを伴わないタスクにも適用できるよう一般化する。

## 完了判定の5条件（Acceptance Criteria）

以下の5点が満たされた時点で、タスクは「完了（Done）」とみなす。

```
1. required_acceptance_criteria satisfied   依頼時に定義した完了条件を満たしている
2. required_verification completed          Work Typeに応じた検証が完了している
                                             （コード: テスト/diff。Research: 出典確認。
                                              Organize: 全件網羅性確認 等）
3. deliverables present                     成果物が実在する（空・欠落でない）
4. persistence confirmed where applicable   永続化が必要な性質のタスクなら、永続化を確認済み
                                             （該当しない性質のタスクは N/A と明示する）
5. unresolved_blockers = none                未解決のブロッカーが残っていない
```

## 完了時の自律停止アクション

- 上記5点が満たされた後、「他に何かありますか？」「次に何をしますか？」といった
  曖昧な質問ターンを挟んではならない
- 直ちに完了報告（result_presenter相当のフォーマット）を出力し、そのターンで自律停止する
- 1点でも未達なら、未達点と次の1手を明示して停止する（強引に「完了」と言わない）

## Host integration status

`runtime/stop_adapter.py`は上記5条件を評価する純粋なpredicateと結果renderingを実装・
単体テストしている。現行Claude setupが接続するのは`PreToolUse` / `PermissionRequest` /
`PostToolUseFailure`の3本であり、Claude `Stop` hookやタスク完了理解へは結線していない。
したがって自動host停止を`ENFORCED`とは主張しない。
