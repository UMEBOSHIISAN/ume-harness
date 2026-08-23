# Tool Policy Contract (Portable)

> Scope: ume-harness runtime | State: ENFORCED
> 目的: あらゆるツール呼び出し（ファイル操作・コマンド実行・外部送信等）を5クラスへ分類し、
> Authority Tier（authority_contract.md §3）と組み合わせて許可/承認要求/拒否を決定する。

## 5つの副作用クラス

```
READ_ONLY           読み取りのみ。副作用なし
BOUNDED_WRITE        境界内のファイル作成・編集（TIER_NORMAL相当領域への書込）
EXTERNAL_MUTATION    外部システムへの送信・通信（API呼び出し・メール送信・公開等）
DESTRUCTIVE          削除・破壊的操作（元に戻せない、または戻すコストが高い）
AUTHORITY_TOUCH      権限構造そのものへの操作（設定ファイル・ガード・トークンストア）
```

## 分類 × Tier の決定表

| 副作用クラス | TIER_NORMAL | TIER_RUNTIME_CODE | TIER_GOVERNANCE | TIER_SECRETS | TIER_CONSTITUTION |
|---|---|---|---|---|---|
| READ_ONLY | ALLOW | ALLOW | ALLOW | **DENY**（読み取りも拒否） | ALLOW |
| BOUNDED_WRITE | ALLOW | APPROVAL_REQUIRED | APPROVAL_REQUIRED | DENY | DENY |
| EXTERNAL_MUTATION | APPROVAL_REQUIRED | APPROVAL_REQUIRED | APPROVAL_REQUIRED | DENY | DENY |
| DESTRUCTIVE | APPROVAL_REQUIRED | APPROVAL_REQUIRED | APPROVAL_REQUIRED | DENY | DENY |
| AUTHORITY_TOUCH | APPROVAL_REQUIRED | APPROVAL_REQUIRED | APPROVAL_REQUIRED | DENY | DENY |
| unknown side-effect（分類不能） | APPROVAL_REQUIRED（fail-closed） | 同左 | 同左 | DENY | DENY |

`unknown side-effect` は「stop（一旦止めて人間に聞く）」を既定にする。分類器が判断できない
操作を安全側へ倒す（fail-closedの原則。個人実装の `is_hooks_write_intent()` 系の教訓＝
分類が甘いと read-only まで誤って拒否する事故を招くため、判定不能時は
「拒否」ではなく「承認要求」に倒し、無限に拒否し続けない設計にする）。

## v0で十分な最小セット（human裁定 2026-08-18）

```
read                     → allow
approved scope内 write   → allow
delete                   → explicit approval
external send            → explicit approval
publish / purchase       → explicit approval
unknown side-effect      → stop（人間に確認）
```

## LocalExecutionLease V0 overlay

`LOCAL_EXECUTION_LEASE_V0` は `IMPLEMENTED / ENFORCED` であり、Portable Coreおよび
Claude Code アダプタ（`lease_gate_runner.py`）において作業ツリー内外の判定overlayとして稼働している。

### Ownership boundary

このTool Policyはlocal executionのallow / approval-required / deny判定だけを所有する。
HumanIntent、canonical task contract、Evidence、Verification、Approval、Receipt、
External Action Authorityの意味論を所有または複製しない。

判定入力に含められるtask identityやdigestは、Agent Frontdoor / WGMが所有するcanonical
contractへの参照としてのみ扱う。Tool Policy自身がtask scopeを再構成したり、検証済みと
いうラベルを発行したり、外部authorityへ昇格させたりしてはならない。

Frontdoorはtask boundary、WGMはevidence / verification relationship、Mothershipは
Decision / External Action Authority、host gateはenforcementを所有する。ume-harnessの
provider adapterはこれらを接続するだけで、別のSSOTを作らない。

`ACTIVE` 化後に限り、validな `LocalExecutionLease` が以下をすべて満たす場合、
Leaseにbindされたworktree内のbounded repository-local edit/createとapproved constrained
testについて、`TIER_RUNTIME_CODE` の既定の `APPROVAL_REQUIRED` を、Leaseのcapability ceiling
の範囲内で `ALLOW` に投影できる。

- canonical task contract digestが一致する
- repository / worktree realpath / branch / starting HEADが一致する
- baseline anchorとcurrent expected execution stateが整合する
- expiry / lifecycle / revocationが有効である
- protected-zone policyに違反しない
- concurrent / out-of-band mutationが検出されていない

validなLeaseが存在しない、または一つでも検証に失敗した場合は、既存の
`APPROVAL_REQUIRED` または `DENY` のfail-closed判定を維持する。Leaseは削除、stage、commit、
任意shell、network、secret、hook authority、external mutationを許可しない。

`LocalWorkspacePreparation` はこのoverlayの入力となる作業環境証拠を準備するだけであり、
Human AuthorityでもExternal Action Authorityでもない。PreparationまたはLeaseの成功は、
push、PR creation、PR merge、deploy、publish、sendの承認へ伝播しない。

Phase 1〜3の実装完了に伴い、task / policy / runtime contextのbinding、V0 capability ceiling、
expiry / lifecycle / revoke、protected-zone、current expected execution state、concurrent / out-of-band mutation
検知、およびhost gate enforcement（`pretooluse_hook.py`）が決定論的に機能し、
有効な `LocalExecutionLease` の存在下でのみ安全なローカル編集を許可する。

## Portable / Drop / Adapter-only の対応（監査結果の反映）

- **Portable**: 5クラス分類・Tier決定表・fail-closed原則・トークン消費モデル
- **Drop**（Coreに含めない）: WooCommerce固有secretパターン・X API固有ロジック・
  production host固有判定・pm2固有プロセス制御・crontab/launchctl固有ガード
- **Adapter-only**: 利用者自身のビジネスAPIのsecretパターン、本番ホスト一覧、
  プロセスマネージャ、スケジューラ変更対象は `adapters/<host>/policy_extension` で追加定義する
