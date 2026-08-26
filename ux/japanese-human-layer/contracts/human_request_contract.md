# Human Request Contract (Japanese Non-Engineer Layer)

> 目的: 日本人の非エンジニアによる曖昧な自然言語リクエストを、内部語彙を露出させずに構造化し、安全に Harness Core へ橋渡しする入出力契約。
> 適用範囲: Japanese Human Layer | 状態: INPUT/PREVIEW CONTRACT ENFORCED / EXECUTION PIPELINE NOT WIRED

## 1. 3つの Work Type 定義

本レイヤーは、日常の非エンジニア業務を以下の 3 つの Work Type に分類して処理する。

```markdown
1. **A. 調べる (Research)**
   - 目的: 調査、要約、根拠の特定、回答の生成
   - 完了検証 (Verification): 出典（一次情報）の有無、根拠と回答の論理的整合性確認

2. **B. 作る・直す (Create / Edit)**
   - 目的: ファイル作成、既存ドキュメント・コードの加筆修正
   - 完了検証 (Verification): 対象ファイルの差分精査、誤字・リンク切れの有無、成果物の実在確認

3. **C. 整理する (Organize)**
   - 目的: 散らかったファイルやデータの分類、棚卸し、提案
   - 完了検証 (Verification): 対象全件の網羅性、分類先の一意性、未処理・例外の有無確認
```

## 2. 入出力パイプライン（ライフサイクル）

```text
[日本語の依頼] 
      ↓ 1. intent_interpreter (意図・Work Type・制約の推定)  【v0.1.0 CLI実装済み】
[推定結果 ＆ 不足情報] 
      ↓ 2. clarification_batcher (未確定事項の一括確認)    【v0.1.0 CLI実装済み】
[自然語 Execution Preview] 
      ↓ 3. execution_preview (「やること / しないこと」の提示) 【v0.1.0 CLI実装済み】
[人間承認]                                                   【conceptual / host未結線】
      ↓ 4. 人間による確認・承認
[Harness Core Task Intake & Lease Execution]                 【conceptual / host未結線】
      ↓ 5. Task Intake ➔ LocalExecutionLease 発行・有効化 ➔ Worker 実行 (PreToolUse 防護)
[Work Type 別 Verification]                                  【conceptual / host未結線】
      ↓ 6. 出典/成果物/件数の確認
[自然語 Result]                                              【conceptual / host未結線】
      ↓ 7. result_presenter (「やったこと / 触っていないもの」の報告)
[自律停止 (Autonomous Stop)]                                 【predicateのみ / host未結線】
```

※ v0.1.0 CLI（`bin/ume-harness`）が担当するのはStep 1〜3（意図解釈・質問集約・
実行前プレビュー）の決定論的判定とレポート生成だけです。Step 4以降を自動的に接続する
worker execution / verification / result / Stop orchestratorは現行packageにありません。
PreToolUse hookは、別途発行・有効化されたLeaseに対するtool境界を防護しますが、
このpipeline自体を開始・完了するものではありません。

## 3. UI 語彙の隠蔽規則 (Forbidden Technical Vocabulary)

以下の内部語彙は、非エンジニア向け UI / メッセージに一切露出させてはならない。

- ❌ `task_class`, `risk_tags`, `scope_digest`, `authority_touch`, `execution_effect`
- ❌ `canonical decision`, `manifest`, `HOLD`, `classifier`, `gate`, `verification=PASS`

**自然言語への翻訳例**:
- `AUTHORITY_TOUCH=true (外部送信)` ➔ 「外部サービスへの送信を含みます。送信前に内容を確認します。」
- `DESTRUCTIVE=true (削除)` ➔ 「不要ファイルの削除を含みます。削除対象の一覧を確認します。」
- `Verification PASS` ➔ 「必要なファイルが正しく更新され、元データに影響がないことを確認しました。」
