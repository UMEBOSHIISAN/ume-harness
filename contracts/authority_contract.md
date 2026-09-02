# Authority Contract (Portable)

> Scope: All agents operating under ume-harness | State: ENFORCED
> Purpose: Prevention of unauthorized privilege escalation or arbitrary execution. Violation = STOP.
> Derived from a production Authority Contract that was already vocabulary-generic in its core
> rules (Rule-1〜6). Only the tier default for runtime code and the token surface were adjusted
> for portability (see §3, §4).

> **LOCAL_EXECUTION_LEASE_V0 state:** `CORE IMPLEMENTED / CLAUDE PRETOOLUSE PARTIALLY WIRED`
>
> Lease derivation, capability persistence, lifecycle state, path-to-Tier resolution,
> and worktree boundary enforcement are implemented and tested. The Claude Code
> `PreToolUse` adapter wires path/Tier, persisted `edit` capability, and worktree checks.
> Persisted `test` / `test_profile` has no Claude command-profile mapping and therefore
> does not authorize arbitrary Bash commands. The
> observer-driven expected-state / concurrent / out-of-band transition machinery
> exists in `LeaseStateStore`, but is not wired into the Claude host lifecycle.
>
> **Threat Model & Trust Prerequisite:**
> - Installed host entrypoint (`pretooluse_hook.py`) is a **trusted host prerequisite**.
> - Arbitrary / manual same-UID replacement of the installed entrypoint file itself is **OUT OF SCOPE**.
> - Persisted Lease records bind lifecycle and capability fields into a record digest for corruption
>   detection. This is not a cryptographic boundary against an adversarial same-UID process that can
>   rewrite the state file and recompute public digests; the secured local account/state directory is
>   a trusted host prerequisite.
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

本節のPolicy、Lease導出・状態primitive、capability ceiling、および作業ツリー境界・
path/Tier制御は実装・テスト済みである。Claude Codeアダプタでは`PreToolUse`時の
persisted `edit` capability / path / worktree判定が結線されている。`test` capabilityと
`test_profile`はstateへ保存されるが、Claude command-profile mappingは未結線である。
`LeaseStateStore`のobserver駆動
expected-state / concurrent / out-of-band検知は実装・単体テスト済みだが、Claude hostの
operation begin/complete lifecycleには未結線（experimental）である。

### Ownership boundary (P0 prerequisite)

ume-harnessは、自身のLocal Work Planeにおけるsemantic ownerである。

- ume-harnessはlocal work-intake、bounded local task / preflight、clarification / confirmation batching、candidate local-action classification、local execution policy、LocalExecutionLease、worktree / tool enforcement、およびlocal verification factsを所有する。
- 外部から互換性のためにtask identityやdigestが供給される場合、それらはbounded local task referenceとして扱うinput metadataに限られ、Harness内の新しいSSOTにはならない。外部供給データ自体の所有権も移転しない。
- Agent Frontdoorのようなhistorical external producerはcompatible referenceを供給できるが、Harness runtimeはAgent Frontdoorを必要としない。
- historicalなWorkflow Governance Model (WGM) / Mothership Routerとの関係はcompatibility / historyであり、現在のtop-level architectureやruntime dependencyではない。
- Mothershipはconsequential Decision SurfaceとExternal Action Authorityの境界を所有するが、local worker executionを所有しない。
- External bounded executorはactual external effectを実行し、`ExternalActionReceipt`を生成する。別のread-only Verifierが`ExternalActionVerification`を生成する。Mothershipによるpost-action evidenceの受領・照合・検証は、現行runtime behaviorとして本契約ではclaimしない。
- host gateはHarness-owned local semanticsをruntimeでenforceし、Claude/Codex adapterは接続形式だけを担当する。どちらもLocalExecutionLeaseから外部authorityを生成・伝播しない。

LocalExecutionLeaseのbind対象はvalidated bounded local task identityへの参照であり、
新しいtask SSOTでも、Mothershipのconsequential authorityでもない。

### Consequential boundary (v0)

The shared semantic model is:

```text
OBSERVE → PROPOSE → APPROVE → EXECUTE → VERIFY
```

For this repository, `PROPOSE` is limited to a local work preview. Local human
confirmation and site-policy eligibility are conceptually separate
prerequisites; neither creates or carries External Action Authority. The
implemented `LocalExecutionGate` evaluates lease, worktree, domain/path, and
an injected `policy_evaluator`. The current Claude adapter blocks
`APPROVAL_REQUIRED`, but confirmation-token issue/consume/resume for the same
operation remains unwired. This contract therefore does not claim a combined
approved gate path. The lease, gate, local work result, and local verification
facts do not create or carry External Action Authority.

There is no `ConsequenceProposal` producer in v0. Harness has local intent,
task, policy, and lease facts only; it must not infer an exact external
operation, target, or mutable preconditions from them. Mothership owns the
external consequence-proposal intake schema. Harness does not produce an
external executor receipt or an independent external verification record.

Any future external-action workflow is separately owned: a consumed exact
authority is passed to a bounded `Executor`, which emits an
`ExternalActionReceipt`; an independent read-only `Verifier` emits an
`ExternalActionVerification`. Harness owns neither producer.

The shared Source Health, Evidence Spine, Run Lineage, and Agent Decision
components remain separate references and are not runtime dependencies of
this release. UME Presence remains presentation-only with `authority = NONE`;
this contract does not claim a machine-enforced prohibition on Presence
producing verified execution state (`UNKNOWN` in this conformance scope).

### Local Workspace Preparation

`LocalWorkspacePreparation` は Human Authority ではない。明示された
bounded local task identity / referenceと、必要なlocal policy / runtime contextから
機械的に導出され、Lease発行前の隔離された作業環境だけを準備する。

許可されるのは、bounded local task referenceにbindされた以下のlocal操作だけである。

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

`LocalExecutionLease` は Human Authority ではない。bounded local task reference、repository、
worktree realpath、branch、starting HEAD、baseline anchor、capability ceiling、
protected-zone policy、expiryに対する機械導出capabilityである。

V0 capability ceilingが表現するのはbounded repository-local edit/createとapproved constrained
testのみである。現行Claude hostがLeaseによって自動許可へ投影するのは`edit` capabilityだけで、
`test_profile`を具体的なcommand allowlistへ変換する経路は未結線である。
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

Any adapter option described as local workflow delegation is not External
Action Authority delegation. For v0, consequential authority delegation is
forbidden: no agent-to-agent authority inheritance or delegation token exists.

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

The current meanings are deliberately narrow and compatibility-oriented:

- `EDIT_APPROVED:<path>` — `COMPATIBILITY_ONLY` for local work.
- `EXECUTION_GATE_APPROVED:<path>` — `LOCAL_ONLY_SEMANTIC` for local gate handling.
- `DEPLOY_APPROVED:<target>` — `DEPRECATED_FOR_NEW_CODE` for new Harness code;
  it is not a Harness external-authority path.
- `AUTONOMY_APPROVED:<class>:<level>:<review_date>` —
  `DEPRECATED_FOR_NEW_CODE` for new Harness code; it is not a Harness
  external-authority path.

These names are retained where compatibility requires them; do not delete or
promote them into a canonical external-authority mechanism. Local approval,
local policy eligibility, and LocalExecutionLease remain distinct from
external consequence authority. A future identity/role provider, human
ceremony adapter, domain policy/action profile, executor, verifier, external
audit anchor, or obligation handler is an extension point, not part of this
contract.

### Human UX → Canonical Token 変換フロー（アーキテクチャ境界）

```
人間向け自然語 approval（例:「このファイルを変更して進めますか？」[進める][やめる]）
        ↓ ux/ adapter が仲介
canonical authority token（例: EDIT_APPROVED:<path>）
        ↓
Core（tool_policy.py）が検証・消費
```

Core 自体はトークン文字列の生成・検証・消費のみを扱う。自然語⇄トークンの変換は
必ず UX アダプタ層の責務とする（Core に自然語処理ロジックを混ぜない）。現行Claude
adapterは`APPROVAL_REQUIRED`をblockするが、承認tokenの発行・消費から同一operationを
再開するend-to-end経路は未結線である。Human approvalだけを実行能力として扱ってはならない。

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

`LocalExecutionLease` の導出、状態管理（`LeaseStateStore`）、capability ceiling、
および作業ツリー境界・コントロールプレーン・path/Tier防護
（`LocalExecutionGate` / `LeaseGateRunner`）は実装および単体・結合テスト済みである。
Claude `PreToolUse`にはこれらのpre-operation判定が結線されている。一方、trusted observerを
用いたoperation begin/complete、expected-state更新、concurrent / out-of-band mutation検知は
Core primitiveとして実装済みだがClaude hostには未結線であり、enforcement claimに含めない。
`activation_updater.py`も実装済みの手動primitiveであり、`setup`は`activation.json`を作成しない。
アダプタのclosure検証は既存の有効なactivation stateがある場合だけ実行される。
