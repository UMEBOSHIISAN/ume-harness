# Authority Contract (Portable)

> Scope: All agents operating under ume-harness | State: ENFORCED
> Purpose: Prevention of unauthorized privilege escalation or arbitrary execution. Violation = STOP.
> Derived from a production Authority Contract that was already vocabulary-generic in its core
> rules (Rule-1〜6). Only the tier default for runtime code and the token surface were adjusted
> for portability (see §3, §4).

> **LOCAL_EXECUTION_LEASE_V0 state:** `IMPLEMENTED / ENFORCED`
>
> Local execution lease verification and worktree boundary enforcement are
> active in the portable runtime and Claude Code adapter.
>
> **Threat Model & Trust Prerequisite:**
> - Installed host entrypoint (`pretooluse_hook.py`) is a **trusted host prerequisite**.
> - Arbitrary / manual same-UID replacement of the installed entrypoint file itself is **OUT OF SCOPE**.
> - Closure verification enforces runtime artifact integrity under this trusted entrypoint assumption.

## Rule-1〜6（そのまま採用・原文がすでに汎用だった）

- **Rule-1**: Do not upgrade `UNKNOWN` to `ASSUMPTION` / `CONFIRMED` / `ACTION` without explicit repository evidence.
- **Rule-2**: `BLOCKED` = STOP. Exploring alternative unauthorized routes, tool escalations, or bypasses is strictly forbidden.
- **Rule-3**: Editing or execution in an **Execution Gate** area requires explicit human approval tokens (see §4).
- **Rule-4**: Vague words like "go", "hurry", or "proceed" are invalid approvals. Only canonical tokens count (§4).
- **Rule-5**: Success does not validate unauthorized action (No "act first, apologize/justify later" pattern).
- **Rule-6**: Labels are not evidence (Always verify the source-of-truth file instead of relying on a label).

## §2 Execution Gate Areas（汎用形）

デプロイ設定 / スケジューラ（cron・systemd・launchd相当）/ SSH設定 / ランタイム設定ファイル
（settings.json・config.toml相当）/ 自動化スクリプト群 / CI/CD / サービス定義。

「自動化スクリプト群」の実体パスは配布先の環境に依存するため、Core契約では定義しない。
アダプタ側（`adapters/<host>/config`）で1箇所だけ定義する。

## §2.5 Local Workspace Preparation / Local Execution Lease V0

本節のPolicyは `IMPLEMENTED / ENFORCED` であり、Portable CoreおよびClaude Codeアダプタにおいて
作業ツリー境界・ファイル操作制御として有効化されている。

### Ownership boundary (P0 prerequisite)

このPolicyは、既存のcanonical contractをume-harness内に複製しない。

- Agent Frontdoorが `HumanIntent` のtask境界とcanonical task contractを所有する。
- Workflow Governance Model (WGM) がEvidence、Claim、Action Proposal、Approval、Execution Receipt、Verificationの関係を所有する。WGMは実行エンジンではない。
- Mothership Routerはadvisory routing / dry-run manifestだけを所有し、authorityやexecutionを生成しない。
- MothershipはDecision SurfaceとExternal Action Authorityの境界を所有するが、local worker executionを所有しない。
- ume-harnessはcanonical task/evidence/verification/authority contractの所有者ではなく、canonical task boundaryを参照してlocal workspaceとlocal executionを制御する。
- host gateはruntime enforcementを行い、Claude/Codex adapterは接続形式だけを担当する。どちらもcanonical semanticsを定義しない。

ume-harnessはFrontdoor/WGMが発行・検証したtask identityとdigestを参照できるが、
独自のTaskContract、Verification、Approval、Receipt、External Authorityを発行・再定義してはならない。
Local Execution Leaseのbind対象はcanonical taskへの参照であり、新しいtask SSOTではない。

### Local Workspace Preparation

`LocalWorkspacePreparation` は Human Authority ではない。明示された
canonical task boundary（Frontdoorのtask identity / contract digestと、必要なWGMの
validated context）から機械的に導出され、Lease発行前の隔離された作業環境だけを準備する。

許可されるのは、canonical task referenceにbindされた以下のlocal操作だけである。

- exact base commitからの新規local branch作成
- そのbranch用のisolated worktree作成
- repository / branch / HEAD / realpathの決定論的検証

branch identityはprovider-neutralな `task/<task-slug>-<task-contract-sha12>` 形式を
用いる。configured worktree rootは、対象repository外、provider非依存、owner管理下、
通常task用に一時的でなく、realpath検証およびsymlink/path-escape検証を通過しなければならない。
runtimeの既定値は `~/.ume-harness/worktrees/` とするが、これはPolicy上の固定絶対パスではない。

Preparationはsource file、`.gitignore`、既存branch、既存worktree、hook、policy、secretを
変更してはならない。branch/worktreeの削除、reset、rebase、amend、stage、commit、network、
push、PR、merge、deploy、publish、sendも許可しない。

### Local Execution Lease

`LocalExecutionLease` は Human Authority ではない。canonical task reference、repository、
worktree realpath、branch、starting HEAD、baseline anchor、capability ceiling、
protected-zone policy、expiryに対する機械導出capabilityである。

V0で許可されるのは、bounded repository-local edit/createとapproved constrained testのみ。
Leaseは、Policyで禁止されたcapabilityを追加できず、別worktreeへ移行できず、期限を自動延長できない。
Lease、Preparation結果、local execution成功、receipt、AI review結果のいずれも、
External Action Authorityを構成しない。

`LocalWorkspacePreparation` と `LocalExecutionLease` は、push、PR creation、PR merge、
deploy、publish、sendへauthorityを伝播させない。これらは常に別のHuman approval境界である。

`EDIT_APPROVED:<path>` は移行期間のmachine-internal compatibility表現に限り、
このPolicyのcanonical authorityではない。

`LocalExecutionLease` の導出（Phase 1）、状態管理（Phase 2: LeaseStateStore）、
および作業ツリー境界・コントロールプレーン防護（Phase 3: LocalExecutionGate / LeaseGateRunner）は
実装および単体・結合テスト済みである。未実装の自動worktreeプロビジョニング等は
今後の拡張項目（P1）として分離されている。

## §3 Authority Tier Model（5層・役割ベース）

```
TIER_CONSTITUTION   人間専用・AI書込は永久に不可（プロジェクトの憲法/方針文書）
TIER_SECRETS        誰も自動書込不可（.env / credentials / keys 等）
TIER_GOVERNANCE     承認token必須（期限+残回数付き・action別発行）
TIER_RUNTIME_CODE   既定 = explicit approval required（人間の明示承認が必要）
                     delegation（別workerへの委譲を正路とする運用）は Core の既定ではなく
                     adapter の任意オプション（optional adapter policy）として提供する
TIER_NORMAL          自由に書込可（docs / tasks / memory 相当）
```

> 訂正（2026-08-18 human裁定）: 元になった個人実装では `TIER_RUNTIME_CODE` の既定動作が
> 「別worker（Codex相当）への委譲が正路」という特定の運用思想に固定されていた。これは
> Portable Core が他人の開発フローを縛ることになるため、Core の既定は
> 「明示承認が必要」に留め、委譲パターンは選択制の adapter オプションへ切り出した。

## §4 Canonical Authority Token（内部表現・エンドユーザーへ直接露出しない）

トークンは **内部実装の表現形式**であり、非エンジニア向けUXでは一切露出しない
（そのまま `EDIT_APPROVED:/foo/bar` を人間に打たせる設計は不採用）。

```
EDIT_APPROVED:<path>
EXECUTION_GATE_APPROVED:<path>
DEPLOY_APPROVED:<target>
AUTONOMY_APPROVED:<class>:<level>:<review_date>
```

### Human UX → Canonical Token 変換フロー

```
人間向け自然語 approval（例:「このファイルを変更して進めますか？」[進める][やめる]）
        ↓ ux/ adapter が仲介
canonical authority token（例: EDIT_APPROVED:<path>）
        ↓
Core（tool_policy.py）が検証・消費
```

Core 自体はトークン文字列の生成・検証・消費のみを扱う。自然語⇄トークンの変換は
必ず UX アダプタ層の責務とする（Core に自然語処理ロジックを混ぜない）。

## §5 Token データモデル

```json
{
  "action": "impl_write | governance_write | ...",
  "scope_target": "対象パスまたは対象識別子",
  "expires_epoch": 0,
  "uses_remaining": 0
}
```

一致するトークンが複数あっても、**最も早く期限切れになる1件だけ**を消費する
（全件を一括減算する実装は「1回の使用で他の未使用トークンまで無効化する」バグを生む。
元実装でも一度この不具合が実際に発生し修正された経緯があるため、Core仕様として明記する）。

## §6 Adoption / Activation Gate

`LocalExecutionLease` の導出（Phase 1）、状態管理（Phase 2: `LeaseStateStore`）、
および作業ツリー境界・コントロールプレーン防護（Phase 3: `LocalExecutionGate` / `LeaseGateRunner`）は
実装および単体・結合テスト済みであり、`IMPLEMENTED / ENFORCED` として稼働する。
自動 worktree プロビジョニング等の拡張は次期マイルストーンとして分離されている。
