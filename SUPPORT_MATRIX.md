# Support Matrix (v0.1.0 / 2026-08-24 final-freeze bytes)

> 「対応している」の意味: Structural Gate（単体テスト・ゼロ欠陥要求）と
> Semantic Gate（`tests/case1_v2_sampling_contract.md`・pooled PRUNABLE_PRESENT≤20%
> かつ3batch中2batch以上が単体≤20%）の両方を実測でPASSしたモデルのみを
> `supported`とする。それ以外は`unsupported`（=「試していない」ではなく
> 「試して基準未達だった」ことを明示する）。

| Model | Structural Gate | Semantic Gate (pooled) | Authority Regression | Status | Evidence |
|---|---|---|---|---|---|
| Claude Sonnet 5 | PASS (244 pytest + 7 subtests) | PASS (0/30 = 0.0%) | PASS (0/6 false negative) | **supported** | `tests/case1_v2_sampling_contract.md` (Sampling Contract Rev.2) |
| Gemma 4:12b-it-qat | PASS (構造検証はモデル非依存) | FAIL (28/30 = 93.3%) | 未測定（Semantic Gate FAIL時点でP1へ隔離） | **unsupported (v0)** | `tests/case1_v2_sampling_contract.md` (Semantic Gate FAIL) |
| その他のモデル | 未測定 | 未測定 | 未測定 | untested | — |

## v0スコープの境界

- **Claude Sonnet 5のみが「動作を保証する」対象。** 他モデルでの使用は自己責任
  （Structural Gate自体はモデル非依存でPASSするため、実行時に構造的エラーは
  起きないが、不要な確認質問が頻発する可能性が高い）。
- **final-freeze lifecycle**: isolated HOME/PREFIXでinstall → setup → offline use →
  byte verify → disconnect → uninstallを再現し、dangling stateがないことを機械検証する。
- Authority Overlay（削除・外部送信等の実行権限判定）および Lease Gate はモデルに依存しない
  決定論的ロジックであり、対応モデルに関わらず常に有効（`runtime/local_execution_gate.py`, `runtime/tool_policy.py`）。

## 再測定の再現手順

```bash
# Structural Gate（LLM不要）
python3 tests/test_portable_core.py          # 40 passed
python3 tests/test_human_layer_adapter.py    # 42 passed
python3 tests/test_claude_code_adapter.py    # 51 passed
pytest -q tests ux/japanese-human-layer/tests # 244 passed, 7 subtests passed

# Semantic Gate（要 claude CLI / Ollama。tests/case1_v2_sampling_contract.md準拠）
# 3 batch x 10 trial x 対象モデル。fresh runのみ有効（過去データ再利用禁止）。
```
