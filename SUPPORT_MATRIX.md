# Support Matrix (v0.1.4 generated public release mirror / 2026-09-02)

`supported`を単一ラベルで扱わず、Semantic Interpretation、Claude Host Adapter、
Platformの3面に分ける。単体テスト結果をphysical host proofへ昇格させず、releaseから
到達できないraw evidenceの数値は現行claimに使わない。

## Semantic Interpretation

| Surface | Status | Release-reachable evidence |
|---|---|---|
| Deterministic Core（Tier / SideEffect / Clarification / Lease primitives） | **tested** | `tests/test_portable_core.py`, `tests/test_human_layer_adapter.py`, Lease/Gate test群 |
| Claude Sonnet 5 intent interpretation | **configured / current release-grade semantic result unknown** | `bin/ume-harness`は`claude -p --model sonnet`を呼ぶ。測定契約は`tests/case1_v2_sampling_contract.md` |
| Gemma 4:12b-it-qat | **unsupported in v0** | CLI経路なし。恒久support claimを裏付けるcurrent raw evidenceなし |
| その他のモデル | **untested** | — |

`PHASE4_HOLD.md`には後続runの歴史記録があるが、そのraw `tests/evidence/` artifactは
現行release closureに存在しない。また、配布中の`tests/case1_v2_sampling_contract.md`が
記録する36.7% / 30.0%の旧runと、従来表の0/30 / 28/30は一致していなかった。
そのため0/30・28/30を現行releaseの再現可能なsupport evidenceとしては掲示しない。

## Claude Code Host Adapter

| Capability | Status | Evidence / boundary |
|---|---|---|
| PreToolUse path/Tier・persisted edit capability・worktree enforcement | **implemented / unit+integration tested** | `adapters/claude-code/lease_gate_runner.py`, `tests/test_claude_code_adapter.py` |
| Persisted test profile → constrained command execution | **not wired** | Stateは保持するがClaude command-profile mappingなし。test-only Leaseは任意Bashを許可しない |
| PreToolUse / PermissionRequest / PostToolUseFailure structured presentation | **implemented / static adapter tested** | 3 hook scriptsとadapter tests |
| Physical live Claude 3-hook presentation | **pending exact-candidate E2E** | Static fixturesはlive Claude UI evidenceではない |
| Lease expected-state / concurrent / out-of-band host enforcement | **not wired / experimental** | Core state machineryのみ実装。Claude operation lifecycleは未接続 |
| Autonomous Claude Stop | **not wired** | acceptance predicateのみ実装。Stop hookなし |
| Local approval-token resume | **not wired** | `APPROVAL_REQUIRED`はblockするがtoken consume/resume経路なし |

## Platform

| Platform | Status | Boundary |
|---|---|---|
| macOS arm64 | **physically demonstrated** | isolated HOME/PREFIX lifecycleを実機実行 |
| Linux / POSIX | **expected / unverified** | Bash/Python実装だが、このrelease evidenceに実機証明なし |
| Windows native | **unsupported** | Bash、`fcntl`、`os.O_DIRECTORY`依存。WSLは未検証 |

## Reproduction commands

```bash
python3 tests/test_portable_core.py
python3 tests/test_human_layer_adapter.py
python3 tests/test_cli.py
python3 tests/test_claude_code_adapter.py
pytest -q tests ux/japanese-human-layer/tests
```

上記Structural GateはLLM不要。Semantic Gateを再主張する場合は、
`tests/case1_v2_sampling_contract.md`どおりfresh 3 batch × 10 trial/modelを実施し、
raw evidenceをreleaseから辿れる形で保持する。Physical Claude host supportは、exact candidate
commitとrelease digestに対する3-hook live E2Eを別途必要とする。
