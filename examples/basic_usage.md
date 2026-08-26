# 使用例（historical reference）

> この入出力は過去のfresh runから保存されたhistorical referenceであり、経緯は
> `PHASE4_HOLD.md`に記録されている。元の`tests/evidence/` raw artifactは現行release
> closureに含まれないため、このファイル単独をcurrent model performanceや再現可能な
> acceptance evidenceとして使わない。fixtureのCase 1期待値とも一致しないことを明示する。

## 入力

```
raw_request: このフォルダの資料まとめて、必要ならREADMEもいい感じに直しといて
workspace_context: 現在の作業フォルダ: ~/Documents/資料/ 。中身は doc1.pdf, doc2.pdf, doc3.pdf, README.md の4件のみ。他に候補となる資料フォルダは存在しない。
```

## Step 1: 保存されたhistorical LLM出力

```json
{
  "work_type": null,
  "inferred_intent": "資料フォルダの中身を整理・集約し、READMEも合わせて更新したい",
  "inferred_deliverable": "不明",
  "candidate_actions": [
    "doc1.pdf, doc2.pdf, doc3.pdfの内容を読み込む",
    "資料の内容をまとめた新規文書を作成する",
    "既存ファイルを整理する（リネーム・移動・統合）",
    "README.mdの内容を編集する"
  ],
  "clarification_assessments": [
    {
      "question": "「資料まとめて」とは、資料の内容を要約した新しい文書を作ることか、それとも既存の3つのPDFファイル自体を整理・統合（リネーム・移動・結合など）することか、どちらを意図していますか？",
      "missing_information": "mutation_target",
      "impact": {
        "authority_boundary": "unknown",
        "mutation_target": "true",
        "destructive_effect": "true",
        "external_effect": "false",
        "requested_scope": "true",
        "costly_rollback": "unknown"
      },
      "basis": {
        "external_effect": {"kind": "not_applicable", "reason": "どちらの解釈でも作業はローカルの指定フォルダ内で完結し、外部への送信・公開は依頼文に含まれていない"}
      }
    },
    {
      "question": "README.mdを「いい感じに直す」とは具体的に何を指しますか（誤字修正程度の軽微な変更か、内容の全面的な書き直しか）？",
      "missing_information": "requested_scope",
      "impact": {
        "authority_boundary": "unknown",
        "mutation_target": "false",
        "destructive_effect": "false",
        "external_effect": "false",
        "requested_scope": "true",
        "costly_rollback": "false"
      },
      "basis": {
        "mutation_target": {"kind": "explicit_request", "refs": ["workspace_context: README.mdは既存ファイルとして一覧に含まれている"]},
        "destructive_effect": {"kind": "not_applicable", "reason": "テキストドキュメントの内容編集はそれ自体が破壊的操作には該当しない"},
        "external_effect": {"kind": "not_applicable", "reason": "README編集に外部送信・公開は依頼文に含まれていない"},
        "costly_rollback": {"kind": "not_applicable", "reason": "テキストファイルの編集内容は差分として容易に復元・巻き戻し可能であり、深刻な後戻りコストは生じない"}
      }
    }
  ]
}
```

## Step 2: Core側の決定論的処理（`runtime/human_layer_adapter.py::normalize()`の実出力）

```python
import human_layer_adapter as hla
result = hla.normalize(llm_output)  # 上記JSONをそのまま渡した実行結果
```

```text
work_type: None
classification_status: UNRESOLVED   # LLMがwork_typeを決めなかったため
required_human_approvals:
  - 'doc1.pdf, doc2.pdf, doc3.pdfの内容を読み込む'
  - '既存ファイルを整理する（リネーム・移動・統合）'
surfaced_unknowns:
  - 「資料まとめて」とは...どちらを意図していますか？
  - README.mdを「いい感じに直す」とは...どちらですか？
pruned_unknowns: []
clarification_blocked: False

action_overlay:
  'doc1.pdf...の内容を読み込む'           -> UNKNOWN     -> APPROVAL_REQUIRED
  '資料の内容をまとめた新規文書を作成する'   -> BOUNDED_WRITE -> ALLOW
  '既存ファイルを整理する（...）'          -> UNKNOWN     -> APPROVAL_REQUIRED
  'README.mdの内容を編集する'             -> BOUNDED_WRITE -> ALLOW
```

## 観察（既知の挙動・Rev.2の対象外）

`Authority Overlay`（`runtime/human_layer_adapter.py::classify_candidate_action`）の
keyword一致は、「読み込む」（動詞の連用形）が`_READ_ONLY_KEYWORDS`の「読み込み」
（名詞形）と厳密文字列一致しないため`UNKNOWN`に分類され、fail-closedで
`APPROVAL_REQUIRED`になる。これは**Case1 v2 Sampling Contractの対象外**
（Authority Overlayは2026-08-19以前から凍結対象・本Package Assemblyでも変更禁止）
であり、実際に危険側（過剰承認要求）に倒れているため安全上の問題はないが、
UXとしては「読み込むだけの操作」にまで承認を求める点でやや厳しい。将来の
改善候補としてP1バックログに記録する（本v0では変更しない）。

`clarification_assessments`の2件はいずれも`impact`に`"true"`を含むため
（`mutation_target`/`requested_scope`）、`missing_information`の内容（annotation）に
関わらず決定論的に`ASK`となり、`surfaced_unknowns`へ入る。`basis`が付与されている
`false`次元（`external_effect`, `destructive_effect`, `costly_rollback`）は、
形式的に有効なため`false`のまま採用され、決定には寄与しない
（Cの「FALSE Basis Contract」参照）。
