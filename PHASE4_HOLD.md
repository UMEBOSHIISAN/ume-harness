# Phase 4 HOLD Status

> **Historical chronology only.** The dated counts and gate states below record
> earlier checkpoints and are not claims about current release bytes. Current
> final-freeze structure, test counts, byte identity, and lifecycle evidence are
> defined by `package_manifest.json`, `MANIFEST.md`, `README.md`, and
> `tests/test_release_lifecycle.py`.

> 更新: 2026-08-19
> 状態: **PHASE_4_HOLD**

## blocker

```yaml
blocker: CASE1_SAMPLING_CONTRACT_GATE_MODEL_SPLIT_CLAUDE_PASS_GEMMA_FAIL
```

> 旧blocker `CASE1_SAMPLING_CONTRACT_GATE_FAILED_BOTH_MODELS`（2026-08-19記録）は
> keyword方式（廃止済み）に対する測定結果。Rev.2実装（`design/clarification_impact_contract_v0.md`
> FROZEN・二層Gate: Structural Gate=単体テスト、Semantic Gate=本Sampling Contract）を
> 実装し、fresh runで再測定した結果（`tests/evidence/case1_sampling_contract_rev2_20260820/
> CLASSIFICATION_AND_GATE_RESULT.md`）:
>
> ```yaml
> Structural Gate: 42/42 単体テストPASS（ゼロ欠陥）
> Authority regression (Case3/4 fresh run): 6/6, false_negative=0, leak=0
> Semantic Gate (Case1 v2 Sampling Contract fresh run):
>   claude: pooled=0.0%(0/30), per_batch=[0%,0%,0%] -> Gate PASS（全条件達成）
>   gemma:  pooled=93.3%(28/30), per_batch=[90%,90%,100%] -> Gate FAIL
> ```
>
> Claudeは旧keyword方式(36.7%)から劇的に改善しGate完全達成。Gemmaは旧方式(30.0%)から
> 大幅悪化(93.3%)。原因はRev.2実装のバグではなくGemmaの構造化出力能力の限界と推定
> （Structural Gateは正しく機能しており、basisフィールドの空欄化等はUNKNOWNへ安全に
> 倒れている。質問文自体が漠然とした体裁・方法レベルの内容に終始する傾向がbasis契約に
> よってむしろ可視化された）。KNOWN_RESIDUAL_SEMANTIC_RISKとして事前に想定していた
> 領域の実測確認。
>
> **モデルによってGate結果が割れた。この状態でPhase 4（Package Assembly）へ進むか
> どうかはhuman判断が必要。cc-mainはこれ以上の実装変更を新規指示なしに行わない。**
>
> 2026-08-20 human裁定: **「Claude限定でPhase4進行（推奨）」を採用。** ume-harness v0の
> 対応モデルはClaude Sonnet 5のみとし、Gemmaは「現時点で未対応」と明記した上でPackage
> Assemblyへ進む。Gemma対応は別チケットとして切り出す。
>
> 同日、P0-A（stale package surface）も是正済み:
> - `package_manifest.json`を実構造（`runtime/{tool_policy,human_layer_adapter,
>   decision_state,stop_adapter}.py`等）に修正し、v0対応モデル状況を明記
> - `scripts/install.sh`/`uninstall.sh`/`health_check.py`・`adapters/claude-code/*`に
>   NOT_IMPLEMENTED通知を追加（削除はせず、非機能である事実を明示。Claude Code hookへの
>   実配線アダプタは別チケット）
> - `README.md`のパッケージ構成・クイックスタートを実態へ全面修正。加えて
>   **`tests/acceptance_record_claude.md`（provenance-invalidと判明済みの隔離ファイル）を
>   「20/20 PASS」の根拠として引用していた誤りを発見・修正**し、信頼できる証拠
>   （`tests/evidence/case1_sampling_contract_rev2_20260820/CLASSIFICATION_AND_GATE_RESULT.md`）
>   への参照に置き換えた
> - 単体テスト回帰なし確認済み（39/39・42/42 PASS）
>
> **P0-A・P0-Bともに解消。**
>
> 2026-08-20 human裁定「Phase 4 Package Assembly本体へGO」を受け、#510相当の
> distribution surface整備を実施・完了:
>
> - `MANIFEST.md`を実findと完全一致するよう再生成し、`tests/test_portable_core.py`の
>   drift検知テストを「宣言18件のハードコード文字列チェック」から「実findとの
>   完全一致（欠落・幽霊エントリともにゼロ）を機械検証」へ強化
> - `VERSION` / `NOTICE`（provenance） / `SUPPORT_MATRIX.md` / `schemas/
>   intent_interpreter_output.schema.json`（Rev.2契約のJSON Schema化） /
>   `examples/basic_usage.md`（実測データに基づく使用例） / `tests/evidence/INDEX.md`
>   （raw証跡への参照面）を新規作成
> - **重大発見・修正**: `QUARANTINE_NOTICE.md`に「Phase 4エントリ条件はUNMET」
>   「#510は解除まで着手しない」という、今回の裁定と矛盾する古い文言が残存していた。
>   解除条件3点の達成状況を明記し、現状（Phase4 GO）を反映する形に修正
> - `ux/japanese-human-layer/`配下の全ファイル（contracts/prompts/README）を精査。
>   `clarification_batcher.md`が旧フィールド名`unresolved_unknowns`を参照していたのを
>   `NormalizedInterpretation.surfaced_unknowns`へ訂正。README.mdの構成図から
>   `tests/`サブディレクトリが漏れていたのを追加
> - `contracts/*.md`（4本）は実装（`runtime/tool_policy.py`のTier×SideEffect表・
>   TokenStore単件消費）と整合していることを確認（修正不要）
> - 全体grep sweepで`unified_tool_classifier`等の残存参照・`20/20`・`claude-3-7-sonnet`等の
>   誤参照がないことを確認（残る言及は全て今回の訂正を説明する文脈のみ）
> - 最終regression: `test_portable_core.py` 39/39 PASS、`test_human_layer_adapter.py`
>   42/42 PASS（manifest完全一致検証を含む）
>
> **Semantic Core（Rev.2実装・Case1 v2契約・Authority Overlay）は一切変更していない。**
> Gemma対応はP1へ隔離済み（`SUPPORT_MATRIX.md`に明記）。Release / Friend PC移植判定は
> 本Package Assemblyの範囲外であり、別Gateとして扱う（勝手にreleaseしない）。
>
> **Assembly verification完了。**
>
> 2026-08-20 human裁定「Phase4 Package AssemblyをCLOSED。次Gateはfresh-machine
> portability trial」を受け、独立フレッシュagent（本会話の文脈を一切持たない
> general-purpose subagent）による評価を実施した。
>
> ```yaml
> Stage R0 (freeze): 39ファイルchecksum固定 → 評価後も完全一致（無傷確認）
> Stage R1-R2: README起点の理解 + test_portable_core.py/test_human_layer_adapter.py/
>              japanese-human-layer fixture test を独立再現 → 39/39, 42/42, 4/4 一致
> Stage R3: 有効タスクE2E（評価者自身がLLM役を担当）→ 質問1件が正しくASK、
>           2アクションが正しくAPPROVAL_REQUIRED
> Stage R4: 危険/曖昧タスクのfail-closed確認 → 削除・外部送信ともにHELD。
>           adversarial sub-check（candidate_actions省略時にrequired_human_approvalsが
>           空になる）を実演＝design docに既記載のKNOWN_RESIDUAL_SEMANTIC_RISKと一致
>           （新規バグではない）
>
> 評価者の判定: PORTABLE_WITH_INTERVENTION
> cc-mainによる独立検証: 主要な数値・主張（checksum一致・test数値・README非導線・
>   adversarial sub-check）を全てCONFIRMED。評価者の判定をそのまま採用
> ```
>
> 具体的な介入ポイント6件（呼び出し方法不明・LLM役の担い手不在・Tier選択導線なし・
> DESTRUCTIVE分類の暗黙性・keyword不一致・work_type=nullの意味）は
> `tests/evidence/PORTABILITY_TRIAL_20260820.md`に記録。
>
> **本Package Assembly／Portability Trialのスコープはここで完了。**
>
> ---
>
> ## Usability Closure（2026-08-20・完了）
>
> human裁定「判定PORTABLE_WITH_INTERVENTIONを採用（ただしfresh-context独立再現性と
> physical cross-machine portabilityは区別する）。次Phase=Usability Closure。
> P0（入口/adapter/tier隠蔽）を閉じ、P1（overwrite説明/lexical gap/work_type契約）も
> 閉じてから、実機第三者PCでのtrialへ進む」を受けて実装した。
>
> ```yaml
> P0-1_cli_entrypoint:
>   status: DONE
>   file: bin/ume-harness
>   test: tests/test_cli.py (13/13 PASS・LLM不使用)
>   note: >
>     --llm-output-file でオフラインテスト可能。ライブ利用は claude -p --model sonnet
>     を内部で呼ぶ（SUPPORT_MATRIX.md準拠・Claude Sonnet 5のみ対応）。
>
> P0-2_claude_code_adapter:
>   status: PreToolUse=DONE / Stop=NOT_IMPLEMENTABLE（構造的理由）
>   file: adapters/claude-code/pretooluse_hook.py
>   test: tests/test_claude_code_adapter.py (11/11 PASS・LLM不使用)
>   note: >
>     母艦の稼働中hook(~/.claude/hooks/unified_tool_classifier.py)を読み取り専用で
>     参照しI/O契約（exit 0=allow / exit 2=block）を確認した上で汎用化実装。
>     Stop hookは意味論的判断（タスク完了の理解）を要しPortable Core単体では
>     自動化できないため、正直にNOT_IMPLEMENTABLEと明記（過大な主張をしない）。
>
> P0-3_tier_hidden_from_ui:
>   status: DONE
>   note: bin/ume-harnessのargparseに--tierオプションを設けず、TIER_NORMAL固定。
>         test_cliでヘルプにtier文言が出ないことを機械検証。
>
> P1_overwrite_destructive_explained:    DONE（README「既知の制約」節）
> P1_lexical_gap_documented:             DONE（examples/basic_usage.md「観察」節 +
>                                         README「既知の制約」節から導線）
> P1_work_type_null_contract_explained:  DONE（README「既知の制約」節）
> candidate_action_omission:             KNOWN_RESIDUAL_SEMANTIC_RISKのまま維持。
>                                         Core patchはしていない（human裁定通り）
> ```
>
> Core semantics（`runtime/tool_policy.py`・`human_layer_adapter.py`の決定ロジック）・
> Case1 v2契約・Gemma対応は本Usability Closureで一切変更していない。
>
> 最終regression: `test_portable_core.py` 39/39・`test_human_layer_adapter.py` 42/42・
> `test_cli.py` 13/13・`test_claude_code_adapter.py` 11/11・
> `ux/japanese-human-layer/tests/test_human_layer.py` 4/4（合計109件PASS）。
>
> **次工程（未着手・別Gate）: 実際の第三者PC（このセッションの文脈を持たない
> 物理的に別の環境）へパッケージをコピーし、README起点・作者介入回数を計測する
> fresh-machine trialを実施する。これをもってphysical cross-machine portabilityを
> CONFIRMEDへ昇格できるかを判定する。実施後はSTOPし、結果を報告する。**
>
> ここでSTOP。

> ---
>
> ## Physical Cross-Machine Trial（2026-08-20・Gate定義のみ・未実施）
>
> human裁定「Usability ClosureをCLOSED。新機能/Core semantic/Case1/Gemma変更は禁止。
> Claude adapter capabilityは『PreToolUse boundary implemented/verified』『semantic Stop
> automation NOT_IMPLEMENTED』と明示維持。次Gate=Physical Cross-Machine Trial。実際の
> 第三者PCへfrozen packageを渡し、READMEのみを起点にsetup→CLI→Claude Code adapter→
> 5ケース（read-only / ASK / write approval / deletion HELD / external-send HELD）を実行。
> time_to_first_result / author_interventions / README外説明回数 / manual configuration /
> environment dependency / false allow / false blockを記録。終了後STOPし、
> FRIEND_DISTRIBUTABLE / DISTRIBUTABLE_WITH_INTERVENTION / NOT_DISTRIBUTABLEで判定」を
> Gate定義として記録。
>
> **BLOCKED（実行手段なし・human判断待ち）**:
> このセッション（cc-main）には、本会話の文脈から独立した「fresh-context subagent」を
> 同一機上で起動する手段はあっても、**物理的に別のPC/Macへアクセス・提供する手段がない**。
> 2026-08-20のFresh-Machine Portability Trial（`tests/evidence/PORTABILITY_TRIAL_20260820.md`）
> は同一機上のfresh-context subagentによる検証であり、human裁定により明示的に
> physical cross-machine portabilityの証明とは区別されている（本ファイル「Usability
> Closure」節参照）。
>
> よって本Gateの実施には以下のいずれかの human 判断が必要:
> 1. 実際に友人/第三者の物理PC（本セッションと無関係な環境）を用意し、そこへ
>    package一式（現Package Assembly + Usability Closure後のfrozen状態）を渡して
>    human自身または当該第三者が試験する（cc-mainは手順書/チェックリストの用意まで）
> 2. 上記が現時点で用意できない場合、本Gateを`BLOCKED: human_dependency`として
>    active_next.md/closeout候補へ計上し、用意でき次第再開する
>
> cc-mainは代替手段（同一機上の別subagentでの再現・シミュレーション等）を
> 「物理PC相当」として自己申告しない（Rule-6「ラベルは証拠ではない」）。
>
> ここでSTOP。

> 2026-08-19 human裁定によりn=5単発batchのGate運用を廃止し、`tests/case1_v2_sampling_contract.md`
> （FROZEN・データ取得前に確定）に基づきClaude/Gemma各30 trial（3 batch×10）で
> multi-batch validationを実施した。結果:
> `tests/evidence/case1_sampling_contract_20260819/CLASSIFICATION_AND_GATE_RESULT.md`
>
> ```yaml
> claude: pooled_rate=36.7%(11/30), per_batch=[30%,50%,30%] -> Gate FAIL
> gemma:  pooled_rate=30.0%(9/30),  per_batch=[20%,50%,20%] -> Gate FAIL
> authority_regression: PASS(0 false negative, 0 leak)
> ```
>
> 単発n=5で見えていた「Claude 1/5 PASS」はfavorable-varianceな外れ値batchだったことが
> 判明した。Human Layerパッチ自体は狙った3パターンには効いたが、同一意味カテゴリの
> 言い回しバリエーション（whack-a-mole問題）に追いつけていない。
> 2026-08-20 human裁定: Gateは変えない。keyword方式（lexical pruning）を設計上の
> 行き止まりと確定し廃止方針。代替として `design/clarification_impact_contract_v0.md`
> （DESIGN_ONLY・未実装）を作成。6次元impact構造（authority_boundary/mutation_target/
> destructive_effect/external_effect/requested_scope/costly_rollback）による
> 決定論的ASK/SUPPRESSルールへの置換を提案。
>
> 同日human裁定2点を反映済み:
> 1. authority/destructive/externalのkeywordクロスチェック案は**不採用**
>    （Clarification層内での分類器二重化になるため。Authority Overlayによる
>    層外の二重防御のみで安全性を担保する設計に確定）
> 2. `missing_information`フィールドはannotation専用・決定に不関与。
>    impact fieldsとの矛盾時はimpact fieldsが正本と明記
>
> stale package surface再調査（当初「実害ゼロ」から訂正）:
> `package_manifest.json`/`README.md`だけでなく`scripts/install.sh`/`uninstall.sh`/
> `health_check.py`/`adapters/claude-code/*`が全て同じ非実在パス
> （`runtime/hooks/unified_tool_classifier.py`等）を参照する**実consumer一式**と判明。
> install.shは`set -euo pipefail`により実行時は最初の`cp`で安全に失敗し
> ユーザーの実配置には触れない（fail-safe、CONFIRMED）。一方
> `~/.claude/settings.json`実読の結果、**本セッション自体を制御する
> live hooks（PreToolUse=unified_tool_classifier.py, Stop=unified_stop_router.py）が
> 実在し稼働中**であることも確認したが、これはume-harness/install.sh経由ではなく
> 別系統（agyによる直接デプロイ、commit 8301ddbbと時系列整合）と推定される
> （ASSUMPTION・provenance証拠なし）。詳細: `design/clarification_impact_contract_v0.md`
> 「発見事項」節。**Phase4再開前の別P0 blocker**として記録（本Gate blockerとは別建て）。
>
> **実装はまだ行っていない。co独立レビュー（GO/HOLD）を経てから着手する。**
>
> 2026-08-20 co独立レビュー結果（`tests/for_codex/20260820_clarification_impact_contract_review_result.md`）:
> **HOLD**。blocking defects 3件（B1: 全FALSE自己申告のsemantic false-negative未対策 /
> B2: malformed/missing impact valuesが無検証でSUPPRESS側へ落ち得る / B3:
> ClarificationCandidate自体の省略を検出できない）。human裁定「1→2で進める
> （CC設計改訂→co再監査）。coの3件は全部blockingとして妥当。人間が直接GOを出すのはダメ」
> を受け、`design/clarification_impact_contract_v0.md`をRev.2へ改訂:
> - ClarificationCandidate(optional)→ClarificationAssessment(必須root)へ変更、
>   `clarification_assessments`フィールド自体の構造的欠落をBLOCKとして検出（B3対応）
> - impact値は厳密3値("true"/"false"/"unknown"の文字列のみ)。欠落/null/JSON boolean/
>   型不一致は全てUNKNOWN相当とし、else節でfalse扱いにする経路を排除（B2対応）
> - FALSEにbasis契約を追加（kind=explicit_request+refs、またはkind=not_applicable+reason）。
>   basis無効ならFALSEをUNKNOWNへ強制昇格（B1対応・限定的措置と明記）
> - Authority Overlayが「Clarificationのsemantic false-negativeをbackstopする」という
>   Rev.1の誤った説明を撤回・訂正（co指摘どおり、Authority Overlayは危険な実行を独立に
>   止めるのみで、Clarification層の判断ミス自体は検出しない）
> - keyword crosscheckは引き続き不採用（Rev.1の裁定を維持）
> - Residual Risksを明記: 「LLMが気づかないこと自体」「形式的に有効だが意味的に誤った
>   basisの生成」は決定論コードでは解消できない、と正直に記載
>
> **CCはRev.2に対して自らGO/HOLDを出さない。co再監査待ち。実装はまだ行っていない。**
>
> 2026-08-20 co再監査結果（`tests/for_codex/20260820b_clarification_impact_contract_rereview_result.md`）:
> 2回目も**HOLD**。B2=closed（達成）、B1/B3=未closed（残存）。ただしB1/B3の内容は
> Rev.2自身がF節で自己申告していた既知の限界と一致（「LLMが意味的に誤ったbasisを
> 生成すること」「候補の見落とし」は決定論コードでは原理的に閉じられない）。
>
> human裁定（同日）: これ以上Core側へ条件分岐を追加してB1/B3を構造的に閉じようと
> しない（第4のCore改訂ラウンドは行わない）。Gateを**Structural Gate**（型・root存在・
> enum値・根拠の形式的完全性。ゼロ欠陥要求・単体テストで検証）と**Semantic Gate**
> （basisの意味的真偽・候補の見落とし。ゼロ欠陥を求めず、frozen Case1 v2 Sampling
> Contractで実測評価）の二層に再定義。B1/B3はKNOWN_RESIDUAL_SEMANTIC_RISKへ
> 再分類（`design/clarification_impact_contract_v0.md`「Gate Redefinition」節）。
> Rev.2はこの形で**FROZEN**・実装対象として確定。

更新履歴:
1. 旧理由「Case 1 failed」→ v1指標がmis-specifiedと判明（Semantic Audit）→
   `CASE1_ACCEPTANCE_V2_PENDING_PROSPECTIVE_VALIDATION`
2. fresh held-out validation実施 → 逆転結果（Claude FAIL / Gemma PASS）
3. 測定器自体の再現性検証（blinded evaluator reliability audit・2026-08-19）実施
   → Evaluator A（独立claude -p呼び出し）とEvaluator B（CC・ブラインド再判定）で
   **11/12（91.7%）一致**。唯一の不一致（Q7・Gemma trial3・UNKNOWN vs PRUNABLE）は
   どちらの判定でもGemmaのPASS結果を変えない。**Claude側10問は100%一致**。
   → 判定: **KEEP_V2_AS_GATE**（ontologyは測定器として再現性あり）
4. human裁定によりHuman Layer最小改善に着手許可（Clarification Pruning Rule拡張・
   `runtime/human_layer_adapter.py`のSTYLE_DETAIL/CONTENT_SCOPEパターン追加のみ。
   Case1 v2定義・閾値・Authority Overlayは無変更）。単体テスト39+28件全PASS
5. パッチ後fresh validation実施（2026-08-19・`tests/evidence/case1_v2_postpatch_20260819/`）:
   - Claude original prompt: **3/5 → 1/5 PRUNABLE_PRESENT（PASS）**。パッチで狙った
     3件のギャップ（体裁/粒度/方向性語彙の欠落）が解消されたことを確認
   - Gemma original prompt: **1/5(前回held-out) → 2/5（今回、FAIL）**。パッチの副作用
     ではなく（Gemma側の生成文言自体が変化）、閾値近傍でのn=5単発サンプルの分散を
     裏付ける結果
   - 未見paraphrase 2種（n=3ずつ）でも両モデルとも閾値近傍でブレる
   - Case3/4 authority regression: 6/6 authority_false_negative=0（無回帰。構造的に
     独立コードパスのため予想通り）
6. 現在の状態: **Human Layerパッチは意図した効果（Claudeの改善）を示したが、
   閾値近傍のn=5判定の分散が大きく、単発バッチでのPASS/FAIL確定はまだ不安定。
   Gemmaの「悪化」をどう扱うか、サンプルサイズを増やすか等はhuman判断が必要**

## 2レーン独立管理（統合しない）

```yaml
Lane A:
  name: Acceptance metric defect (Case 1 v1 → v2)
  status: v2仕様確定・fresh held-out validation実施中
  historical_v1_results: 変更しない（Gemma FAIL / Claude FAIL のまま保存）

Lane B:
  name: agy provenance-invalid record incident
  status: CLOSED_OPERATIONALLY（2026-08-19・agy #512で証拠不整合を認め取り下げ・Phase4 HOLD同意）
  root_cause: agy-reported = "内部シミュレーション/評価推論値の混入"（AGY-REPORTED、
              cc-mainによる独立確認はしていない。UNKNOWNのまま扱う）
  affected_file: tests/acceptance_record_claude.md（QUARANTINE_NOTICE.md参照・
                 永久保全・削除/上書き禁止・事故証拠として残す）
  independent_of: Lane A（Case1のmetric問題とは無関係。統合判断しない）
```

## Phase 4再開条件（両レーンとも解消が必要）

1. Lane A: Case 1 v2でのfresh held-out validation（Gemma×5・Claude×5、監査データとは別）が完了し、
   結果に基づいてPhase 3 verdictが再確定すること
2. Lane B: agyがacceptance_record_claude.md記載値のprovenanceを提示するか、
   UNSUPPORTED_EVIDENCEとして正式に取り下げられること
3. 上記を踏まえてhumanが再裁定すること

## 禁止事項（本HOLD解除まで）

- ~~Human Layer（`runtime/human_layer_adapter.py`のClarification Pruning Rule拡張のみ）の変更~~
  → 2026-08-19 human裁定によりスコープ限定で解除済み（実施済み・上記5参照）。
  **この例外は消費済みの1回限りの許可**であり、それ以外のHuman Layer/Portable Core変更
  （新規カテゴリ追加・閾値変更・Authority Overlay変更等）には再度human承認が必要
- Portable Core（`contracts/`）の変更（定義・閾値レベルは引き続き凍結）
- `#510`（agyのPackage Integrity Audit依頼）への着手
- 過去のCase1 v1結果・acceptance_record_claude.mdの書き換え・削除
- 監査データセット（Semantic Audit時の12質問・held-outデータ）を新規acceptance判定の根拠に再利用すること
- Phase 4 Package Assembly本体への着手（サンプル分散問題が未解決のため）
