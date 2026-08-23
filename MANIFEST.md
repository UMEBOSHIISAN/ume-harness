# Package Manifest (ume-harness) — Usability Closure時点

> 正本の作り方: `find <pkg_root> -type f -not -path "*/__pycache__/*" -not -path "*/logs/*"
> -not -path "*/tests/evidence/*" -not -path "*/tests/for_codex/*" | sort` の実行結果を
> そのまま転記したもの。手集計・記憶からの記載は禁止（2026-08-18 human裁定「実findを
> 正本にする」を継承）。`tests/test_portable_core.py::test_manifest_matches_real_find`が
> 本リストと実findの完全一致（欠落・幽霊エントリともにゼロ）を強制検証する。
>
> 除外規則（配布物surfaceの定義。固定・機械的）:
> - `__pycache__/*.pyc`（Python実行副産物）
> - `logs/`（Codex dispatch実行ログ）
> - `tests/evidence/`（実測raw証跡。件数が多く配布物には含めない。参照は
>   `tests/evidence/INDEX.md`から行う）
> - `tests/for_codex/`（Codex dispatch scratch。タスクmdと結果md）

生成日時: 2026-08-20（Usability Closure・bin/ume-harness・pretooluse_hook.py・
test_cli.py・test_claude_code_adapter.py追加後に再生成）
ファイル総数: 48

```
adapters/claude-code/lease_gate_runner.py
adapters/claude-code/pretooluse_hook.py
adapters/claude-code/README.md
adapters/claude-code/settings.json.fragment
bin/ume-harness
contracts/authority_contract.md
contracts/autonomous_stop.md
contracts/task_intake.md
contracts/tool_policy.md
design/clarification_impact_contract_v0.md
examples/basic_usage.md
LICENSE
MANIFEST.md
NOTICE
package_manifest.json
README.md
runtime/activation_updater.py
runtime/decision_state.py
runtime/human_layer_adapter.py
runtime/local_execution_gate.py
runtime/local_execution_lease.py
runtime/local_execution_lease_state.py
runtime/stop_adapter.py
runtime/tool_policy.py
schemas/intent_interpreter_output.schema.json
scripts/health_check.py
scripts/install.sh
scripts/uninstall.sh
SUPPORT_MATRIX.md
tests/case1_acceptance_v2_spec.md
tests/case1_v2_sampling_contract.md
tests/test_claude_code_adapter.py
tests/test_cli.py
tests/test_human_layer_adapter.py
tests/test_local_execution_gate.py
tests/test_local_execution_lease.py
tests/test_local_execution_lease_state.py
tests/test_portable_core.py
ux/japanese-human-layer/contracts/human_request_contract.md
ux/japanese-human-layer/fixtures/expected_behavior.jsonl
ux/japanese-human-layer/fixtures/vague_requests_ja.jsonl
ux/japanese-human-layer/prompts/clarification_batcher.md
ux/japanese-human-layer/prompts/execution_preview.md
ux/japanese-human-layer/prompts/intent_interpreter.md
ux/japanese-human-layer/prompts/result_presenter.md
ux/japanese-human-layer/README.md
ux/japanese-human-layer/tests/test_human_layer.py
VERSION
```

## 内訳

| ディレクトリ | ファイル数 | 内容 |
|---|---|---|
| ルート | 9 | README/LICENSE/MANIFEST/package_manifest/PHASE4_HOLD/QUARANTINE_NOTICE/VERSION/NOTICE/SUPPORT_MATRIX |
| `bin/` | 1 | ★単一CLI入口（実装済み・テスト済み） |
| `contracts/` | 4 | Portable Core契約書（authority/autonomous_stop/task_intake/tool_policy） |
| `design/` | 1 | Clarification Impact Contract v0（Rev.2・FROZEN） |
| `runtime/` | 8 | Portable Core & Lease Gate実装（tool_policy/decision_state/stop_adapter/human_layer_adapter/local_execution_lease/local_execution_lease_state/local_execution_gate/activation_updater） |
| `schemas/` | 1 | LLM出力contractのJSON Schema |
| `examples/` | 1 | 実測データに基づく使用例 |
| `adapters/claude-code/` | 4 | PreToolUse hook + LeaseGateRunner（実装済み・テスト済み）+ README + settings fragment |
| `scripts/` | 3 | インストール・診断・アンインストール（install.sh/health_check.py/uninstall.sh 実装・検証済み） |
| `tests/`（ルート直下） | 10 | 単体テスト7本（Core/HumanLayer/CLI/ClaudeCodeAdapter/LocalExecutionLease/LocalExecutionLeaseState/LocalExecutionGate）+ Case1 v2契約2本（FROZEN）+ 隔離済み記録1本 |
| `ux/japanese-human-layer/` | 9 | 日本人非エンジニア向けUX層 |

## Structural Gate 検証結果（2026-08-23実行確認）

```
python3 tests/test_portable_core.py          -> 39 passed, 0 failed
python3 tests/test_human_layer_adapter.py    -> 42 passed, 0 failed
python3 tests/test_cli.py                    -> 13 passed, 0 failed（LLM不使用）
python3 tests/test_claude_code_adapter.py    -> 44 passed, 0 failed（LLM不使用）
pytest tests/ ux/japanese-human-layer/tests/ -> 110 passed
```

manifest整合性（本ファイルと実findの完全一致を機械検証）・tool_policy tier決定表・
decision_state パス解決・stop_adapter 5条件判定・japanese-human-layer
既存fixtureテスト・Clarification Impact Contract v0 Rev.2構造検証・CLI headline_state
導出・Claude Code PreToolUse adapter（Lease Gate、Bash構文解析、Read/Writeスコープ逸脱遮断、
コントロールプレーン防護）を静的にカバー。**実LLM呼び出しは一切なし**。

## Semantic Gate 検証結果（2026-08-20実行確認・fresh run）

```yaml
claude-sonnet-5:      pooled PRUNABLE_PRESENT = 0/30 (0.0%)  -> PASS
gemma4:12b-it-qat:    pooled PRUNABLE_PRESENT = 28/30 (93.3%) -> FAIL（v0では未対応）
authority regression (Case3/4): 6/6, false_negative=0, leak=0 -> PASS
```

## Fresh-Machine & Cross-Machine Portability 検証結果（2026-08-23確認）

```yaml
評価: PORTABLE_REPRODUCIBLE（独立フレッシュagentおよび物理別ノードMac miniでの再現を確認）
範囲: fresh-context independent reproduction（CONFIRMED）
      physical cross-machine portability（CONFIRMED）
```

詳細: `SUPPORT_MATRIX.md` および `tests/case1_v2_sampling_contract.md`。

## v0 スコープ外（次工程）

```
Gemma対応                              P1（別チケット）
Claude Code Stop hook自動配線           NOT_IMPLEMENTABLE（構造的理由）
Turnkey自律実行オーケストレーション       将来拡張
Session Budget Advisor                 v0.1.1以降（Claude UX拡張）
```
