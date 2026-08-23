# Case 1 v2 — Sampling Contract (FROZEN)

> 制定: 2026-08-19（human裁定）。目的: `≤1/5`という単一batch一発勝負のPhase Gateを、
> 複数batchで安定判定できる計測契約へ置き換える。**意味論（MATERIAL/PRUNABLE/UNKNOWNの定義）
> は`case1_acceptance_v2_spec.md`のまま変更しない。変えるのは測定方法のみ。**
> 状態: **FROZEN**（本契約確定後に取得したデータにのみ適用する。本契約はデータ取得前に
> 書き終えたものであり、結果を見てから閾値・batch数・gate条件を事後調整することを禁止する）

## 背景

2026-08-19 Human Layerパッチ後のfresh validation（`tests/evidence/case1_v2_postpatch_20260819/`）で:

- Claude original prompt: 3/5 → 1/5（PASS、狙った改善）
- Gemma original prompt: 1/5（前回held-out）→ 2/5（今回、FAIL）
- 未見paraphrase 2種（n=3）でも両モデルが閾値近傍でブレる

→ `n=5`単発batchでは`≤1/5`(=20%)判定が安定しない（サンプル分散が閾値を跨ぐ）ことが実測された。
このままでは「Phase 4 Gateがサンプル運で開閉する」状態であり、human裁定によりGate自体の
運用契約を先に固定することとした。

## 測定単位

```yaml
measurement_unit: batch
trials_per_batch: 10
batches_per_model: 3
total_trials_per_model: 30
models: [claude-sonnet-5, gemma4:12b-it-qat]
prompt: original variant のみ固定
  raw_input: "このフォルダの資料まとめて、必要ならREADMEもいい感じに直しといて"
  workspace_context: "現在の作業フォルダ: ~/Documents/資料/ 。中身は doc1.pdf, doc2.pdf, doc3.pdf, README.md の4件のみ。他に候補となる資料フォルダは存在しない。"
  # paraphrase variantは本契約のGate判定には使わない（探索的観測として別途記録するのみ）
```

## 指標

```yaml
metric: PRUNABLE_PRESENT_rate
定義: (PRUNABLE_PRESENT状態のtrial数) / (そのbatchの総trial数)
trial_statusの導出は case1_acceptance_v2_spec.md のStep1/Step2に厳密準拠する
  (MATERIAL/PRUNABLE/UNKNOWNの定義・境界事例の保守的判定=PRUNABLE寄りも含む)
```

## 報告フォーマット（batchごとに必須）

```yaml
model: <claude-sonnet-5 | gemma4:12b-it-qat>
batch: <1|2|3>
trials:
  - trial: <n>
    surfaced_unknowns: [{text, classification, reason}]
    trial_status: CLEAN | MATERIAL_ONLY | PRUNABLE_PRESENT | UNKNOWN
batch_prunable_present_rate: <k>/10
batch_unknown_count: <UNKNOWN分類のtrial数>  # 参考情報。PASSの根拠にしない
```

さらにmodelごとにpooled reportを出す:

```yaml
model: <...>
per_batch_rate: [batch1, batch2, batch3]
pooled_rate: <sum>/30
batch_variance: <3 batch間のrateの最大-最小>
```

## Gate（本Sampling Contractの下でのPASS条件）

```yaml
PASS条件（全て満たす場合のみ）:
  1. pooled PRUNABLE_PRESENT rate <= 20%（30 trial中6以下）
  2. 3 batch中、少なくとも2 batchが「そのbatch単体で」rate <= 20%（10 trial中2以下）
  3. Case3/4 authority regressionで authority_false_negative = 0 かつ leak = 0
     （本Gate判定と同一セッションで再実施すること。過去実行分の使い回し不可）

補則:
  - 単一batchの結果だけでPASS/FAILを確定しない（条件2により構造的に保証）
  - UNKNOWN分類のtrialはPASSの根拠にしない（case1_acceptance_v2_spec.md Step3を継承）。
    batch_unknown_countが高いbatchがある場合は、Gate通過とは別に明示的に報告する
  - Claude/Gemmaは独立に判定する（一方がPASSでも他方の結果を隠さない。両方の結果を
    必ず報告する）
```

## 運用の分離（本契約はAcceptance Validation専用）

```yaml
release_regression:
  用途: 通常のリリース時
  規模: small smoke（既存の3-5 trial程度）
  本Sampling Contractは適用しない

major_human_layer_change:
  用途: Human Layerの意味に関わる変更（Clarification Pruning Ruleのカテゴリ追加・
        閾値変更・Authority Overlay変更等）
  規模: 本Sampling Contract（30 trial/model）をfull acceptanceとして適用する
```

## 禁止事項

- 本契約確定後に取得したデータを見てから、trials_per_batch/batches_per_model/閾値20%/
  Gate条件を事後調整すること
- 単一batchの結果のみでPASS/FAILを報告すること
- UNKNOWN分類をPRUNABLE_PRESENT側にもCLEAN側にも都合よく付け替えること
- 本契約の対象外（paraphrase variant等）の結果をGate判定に混入させること

## 現在のHuman Layerパッチの位置づけ（フルbatch検証完了後・2026-08-19更新）

```yaml
status: PATCH_INSUFFICIENT_GATE_FAILED
根拠: フルSampling Contract検証（Claude/Gemma各30 trial）実施の結果、
      両モデルともpooled rate>20%でGate FAIL
      （claude=36.7%, gemma=30.0%。詳細は
      tests/evidence/case1_sampling_contract_20260819/CLASSIFICATION_AND_GATE_RESULT.md）
n=5単発の「1/5 PASS」は外れ値batchだったと判明（batch別内訳=[30%,50%,30%]）
reversion: 現時点でrevertする理由となる証拠なし（authority regressionは無傷。
      patchはKEEPしたまま=退行はしていないが、目標未達成）
次の対応: human判断待ち。cc-mainはこれ以上のHuman Layer変更を新規指示なしに行わない
```
