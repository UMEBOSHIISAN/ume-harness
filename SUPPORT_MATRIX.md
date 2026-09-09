# Support Matrix (v0.1.7 Technical Preview)

Historical baseline: v0.1.6 generated public release mirror / 2026-09-05.

Development connection profiles: default `setup` is presentation-only (two
hooks); `setup --managed` explicitly adds conservative PreToolUse enforcement.
The enforcement rows below describe that opt-in profile, not ordinary native CC.
Neither static success nor valid registration inventory proves live host reload.

Published-release selection and side-by-side upgrade instructions are maintained
in [README](README.md#update) / [English README](README.en.md#update). Preserve
old installations until new-prefix
installation and explicit connection switching have been verified.

Explicit-prefix diagnostics require the selected prefix's actual CLI wrapper;
missing, non-executable, and directory entrypoints fail without a payload CLI
fallback (`test_health_explicit_prefix_cannot_fall_back_to_payload_cli`).
No-prefix source/staging diagnostics do not prove an installed prefix works. Isolated recovery
after promotion/before wrapper creation was demonstrated via external trusted
uninstall and ordinary reinstall; partial-wrapper recovery is not claimed.

> v0.1.7のlocal-work policy変更を含みます。以下のv0.1.6の検証記録は歴史的な
> baselineです。fresh hostの表示・権限設定・実イベントは、記載した環境と範囲に限って扱います。

機能の基準は2026-09-05のv0.1.6です。説明文の照合・訂正日: 2026-09-08。

`supported`を単一ラベルで扱わず、Semantic Interpretation、Claude Host Adapter、
Platformの3面に分ける。単体テスト結果をphysical host proofへ昇格させず、releaseから
到達できないraw evidenceの数値は現行claimに使わない。

## Semantic Interpretation

| Surface | Status | Release-reachable evidence |
|---|---|---|
| Deterministic Core（Tier / SideEffect / Clarification / Lease primitives） | **tested** | `tests/test_portable_core.py`, `tests/test_human_layer_adapter.py`, Lease/Gate test群 |
| Claude CLI `sonnet` alias intent interpretation | **configured / current release-grade semantic result unknown** | `bin/ume-harness`は`claude -p --model sonnet`を呼ぶ（exact model versionは固定しない）。測定契約は`tests/case1_v2_sampling_contract.md` |
| Gemma 4:12b-it-qat | **unsupported in v0** | CLI経路なし。恒久support claimを裏付けるcurrent raw evidenceなし |
| その他のモデル | **untested** | — |

`PHASE4_HOLD.md`には後続runの歴史記録があるが、そのraw `tests/evidence/` artifactは
現行release closureに存在しない。また、配布中の`tests/case1_v2_sampling_contract.md`が
記録する36.7% / 30.0%の旧runと、従来表の0/30 / 28/30は一致していなかった。
そのため0/30・28/30を現行releaseの再現可能なsupport evidenceとしては掲示しない。

## Human Layer design versus implemented CLI

`ux/japanese-human-layer/README.md`、contracts、promptsは配布時の設計資料です。
その「3択」「作業完了時の結果報告」を実行可能なCLI機能として扱わないでください。
`bin/ume-harness`は依頼の解釈と決定論的な内容整理を表示し、そこで終了します。
回答を集めて作業を開始するループ、ファイル操作、作業完了の検証は実装していません。
fixturesの自己整合性テストは、モデル精度や作業の実行成功を証明しません。

## Optional macOS notification boundary

`UME_HARNESS_MACOS_NOTIFICATIONS=1` explicitly enables an existing native notifier
for the fixed Japanese PermissionRequest notice. Default off, macOS only, no
automatic dependency installation or OS permission changes, no approval actions.
The isolated prototype was human-observed before the native Yes/No choice on
CC2.1.263/macOS26.6.2/terminal-notifier3.1.0. This is not operation translation or
proof of the final generated package. Native notification permission is required;
missing/failed delivery is non-blocking and bounded without retries. Apple Terminal
OSC2-title readability failed the earlier human test and is not a supported UI claim.

## Claude Code Host Adapter

| Capability | Status | Evidence / boundary |
|---|---|---|
| PreToolUse path/Tier・persisted edit capability・worktree enforcement | **implemented / unit+integration tested** | `adapters/claude-code/lease_gate_runner.py`, `tests/test_claude_code_adapter.py` |
| Persisted test profile → constrained command execution | **not wired** | Stateは保持するがClaude command-profile mappingなし。test-only Leaseは任意Bashを許可しない |
| PreToolUse / PermissionRequest / PostToolUseFailure structured presentation | **implemented / static adapter tested** | 3 hook scriptsとadapter tests |
| AskUserQuestion / ExitPlanMode host-interaction path | **implemented / static adapter tested** | activation/closure attestation後にexact名だけをClaudeへ返す。回答・許可・authorityは生成しない |
| ToolSearch host capability discovery | **implemented / static adapter tested** | Claudeの遅延tool schema loaderだけをexact名で返す。ロード後の実tool invocationは別PreToolUseで再判定し、許可を継承しない |
| EnterPlanMode host-interaction path | **defensive compatibility / static runner tested** | built-in toolとしてexact名を扱うが、live ClaudeがPreToolUse eventを発火することは未確認 |
| Physical interactive Claude 3-hook + host interaction | **physically demonstrated** | An installed exact candidate lineage was exercised with ToolSearch, EnterPlanMode, AskUserQuestion, ExitPlanMode, Read, Write, and PostToolUseFailure; evidence is kept outside the source tree |
| Non-interactive `claude -p` host interaction | **not claimed** | Harnessは回答、`updatedInput`、approval、authorityを合成しない |
| Lease expected-state / concurrent / out-of-band host enforcement | **not wired / experimental** | Core state machineryのみ実装。Claude operation lifecycleは未接続 |
| Autonomous Claude Stop | **not wired** | acceptance predicateのみ実装。Stop hookなし |
| Local approval-token resume | **not wired** | `APPROVAL_REQUIRED`はblockするがtoken consume/resume経路なし |

## 2026-09-08 user-reported trial (partial evidence)

A user-supplied fresh Claude transcript shows the Japanese PostToolUseFailure
message after a Read failure. It also reports a scratch-file Write, a Write into
a personal hook directory, a sandbox-denied Bash removal, and human cleanup.
This is evidence of the observed failure presentation, not proof that public
Harness owns the local SessionStart/front-door/rules or enforces all file tools.
The package's default presentation profile has no PreToolUse enforcement.
The reported Read wording was misleading and is corrected in this release.

Protected-path mutation is not an accepted smoke-test procedure. The permission
Static tests do not claim a complete allow/ask/deny matrix for every host.
Local rules and native permission policy are separate from the public package
acceptance; no blanket “no duplicate gates” or “safe across all tools” claim follows.

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
raw evidenceをreleaseから辿れる形で保持する。Physical claimは、exact candidate commitと
installed release digestに対するinteractive 3-hook live E2Eの範囲に限る。非対話`claude -p`、
MCP実行、未知toolのpass-throughはclaimしない。
