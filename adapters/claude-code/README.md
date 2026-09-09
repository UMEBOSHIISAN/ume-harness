# Claude Code Adapter (ume-harness)

Claude Code と ume-harness Safety Core & Auto Translation Konjac を接続するアダプター群です。

## Local-work policy (v0.1.7 Technical Preview)

この文書は公開済みv0.1.7の仕様です。公開済みtagの選択、新規導入、旧版・ローカル
試用版からの切替は[READMEの更新手順](../../README.md#update)を正本とします。
まず別prefixへ導入・検証し、旧CLIで切断してから新版CLIへ接続します。
mainから更新したり、この文書の標準接続をv0.1.6以前へ適用したりしないでください。

標準接続はPermissionRequest／PostToolUseFailureの説明2本だけで、UMEの追加実行制限は
行いません。以下のLease・保護profile・defer/ask/deny/errorの説明は明示的なmanaged接続の範囲です。

通常プロジェクトの編集はClaude Code本体の権限に従います。Harnessは一般的な
`scripts/`やコード拡張子による追加承認を要求せず、通常作業にLeaseやGit管理を
必須にしません。既存の明示Lease制限、秘密情報・権限設定・control-plane保護は
維持します。コード編集が可能でも任意scriptの安全性や外部操作の権限は保証しません。

ホスト固有の管理ディレクトリは`<state_dir>/local_work_policy.json`で指定します。
例（例示パスは実際の管理ディレクトリへ置換）:

```json
{"schema_version":"local_work_policy.v1","protected_roots":["/absolute/managed-automation"]}
```

未設定時はbuilt-in保護だけです。既存の個人用hookを外す前に、実際の保護対象が
引き継がれることを確認してください。このリリースから稼働中の設定を自動変更しません。

PreToolUseは、通常処理をhostへ戻す`defer`、標準確認を要求する`ask`、禁止の`deny`、
評価異常の`error`を区別します。deferではforce-allowを返しません。ask/denyは
structured JSON、errorはblocking exit 2です。以前の「承認要求もexit 2」とは異なります。
PermissionRequestの説明は承認を代行せず、禁止を解除しません。

認証付きの既存作業では、`SERVICE_ACCOUNT_JSON=/absolute/file.json python3 script.py ...`
というパスの受渡しは、秘密情報を直接表示する操作と区別して標準確認へ戻します。
無条件許可ではなく、スクリプトのread-only保証でもありません。直接の秘密読取、
inlineコード、保護領域のscript、bypassモードは対象外です。
説明表示は引用符内の`;`や`|`をshell複合処理と誤解せず、`2>/dev/null`は
標準エラーの破棄として表示します。説明と実際のpermissionDecisionは別です。

重複登録と保護profileは、明示したファイルだけを読み取り診断できます。
インストールのbyte identity検証に成功するまでruntime診断コードは読み込みません。

```bash
python3 /path/to/install/scripts/health_check.py --installed-dir /path/to/install \
  --settings-path /path/to/.claude/settings.json --state-dir /path/to/state --json
```

登録一覧の成功は「ファイルを解析できた」という意味です。`findings`を確認してください。
他の設定階層・plugin・実行中hostへの反映・matcherの重なりは未確認と表示します。
重複や旧版hookの検出で設定を自動削除せず、profile診断もstateを作成しません。

以下のv0.1.6実機確認記録は旧版の証拠です。このリリースのfresh interactive hostでの
確認・拒否・通常編集の動作は別途検証が必要であり、旧版のE2E成功を継承しません。

## 提供フック一覧

1. **`PreToolUse` (`pretooluse_hook.py`)**
   - ツール実行直前の日本語意味訳をClaude hookのstructured `systemMessage`として返します。
   - Safety Core (Lease Gate / Tool Policy) によるtool単位のallow/block評価を実施します。

2. **`PermissionRequest` (`permission_request_hook.py`)**
   - 手動許可のタイミングに、structured `systemMessage`と公式`terminalSequence`を返します。
     CC 2.1.263のPermissionRequest経路では本文の`systemMessage`が画面へ届かないため、
     固定の短い日本語要約をOSC2ウィンドウタイトルにも返します。OSC777通知は対応端末用です。
     タイトル・通知の見え方は端末設定に依存し、確認ダイアログ内の日本語表示は保証しません。
     Apple Terminalの実画面ではタイトルが読めず、この経路は受入不合格です。
     元の引数・パスをタイトルへ再掲せず、許可・拒否・askのdecisionも返しません。
   - macOS通知は `UME_HARNESS_MACOS_NOTIFICATIONS=1 claude` で明示選択します。
     既存terminal-notifierに固定の日本語案内だけを渡し、操作内容の翻訳・承認は行いません。
     未導入・失敗時も追加拒否せず、1秒上限・再試行なしです。通常setupや他OSでは起動しません。
     依存・通知許可・表示の制約は[README](../../README.md#macosの日本語通知明示選択)を参照してください。

3. **`PostToolUseFailure` (`posttooluse_failure_hook.py`)**
   - コマンドやツールの実行が失敗した際に、`systemMessage`と`additionalContext`で
     過度な安心感を与えない事実ベースの案内を返します。

このv0.1.7では、標準2本のstructured presentationと、明示選択したmanaged接続の
PreToolUseをstatic・結合テストしています。旧v0.1.6の実機確認記録は歴史的な証拠であり、
このリリースへ自動継承しません。単体テストだけをlive表示証拠へ昇格させません。Translation KonjacはPresentation-onlyで、
失敗してもcanonical Safety Gateの評価をskipしません。

`AskUserQuestion`と`ExitPlanMode`は、generic hook envelopeとactivation/protected-closureを
検証した後、Claude自身のhost interactionへ返します。Claude固有のpayload schemaは
このadapterで複製せず、回答、`updatedInput`、permission decision、approval、authorityも
生成しません。`EnterPlanMode`は同じexact-name境界に置くdefensive compatibilityであり、
live ClaudeでのPreToolUse event発火は未確認です。interactive Claudeだけをphysical E2Eの
対象とし、non-interactive `claude -p`のhost interaction supportはclaimしません。

`ToolSearch`はClaudeのhost-ownedな遅延tool schema loaderとして、同じattestation後の
exact-name境界でのみblockせず返します。これはロードされたtoolの許可や実行を意味せず、
後続のtool invocationは別のPreToolUseで再判定されます。`Agent`や任意のMCP toolを
pass-throughするものではありません。

`LeaseStateStore`のexpected-state / concurrent / out-of-band mutation primitiveはClaude hostの
operation begin/completeには未結線です。Autonomous Stopもpredicateのみで、Stop hookはありません。
Lease stateは`test` capabilityと`test_profile`も保持しますが、profileを実行可能コマンドへ
変換するhost mappingはありません。したがってtest-only Leaseは任意のBashを許可しません。

## 設定方法

v0.1.7では次のコマンドで説明用2本だけを接続します。既存設定は保持され、
同じコマンドを再実行しても重複しません。
PATH上の旧版を呼ばないよう、実際に導入した新版CLIのフルパスを使ってください。
custom settingsは接続・切断の両方へ同じ`--settings-path`を渡します。

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" setup --yes
```

厳格なPreToolUseは、同じ新版CLIへ `setup --managed --yes` を渡して明示的に追加します。
`settings.json.fragment`は厳格接続のサンプルであり、標準setupの設定ではありません。
既存の厳格接続から説明だけへ変更する場合はdisconnect後に標準setupしてください。

次はv0.1.7自身の接続を切断する例です。旧版の移行時は[更新手順](../../README.md#update)の
旧CLIでdisconnectしてください。異なるprefixの新版CLIでは旧hookを切断できません。

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" setup --disconnect
```

切断対象はsetup自身が生成した次の3イベントのcanonical commandとの完全一致だけです。

- `PreToolUse`
- `PermissionRequest`
- `PostToolUseFailure`

他event、他matcher、他hook、およびcommand文字列に単に`ume-harness`を含むだけの
ユーザーhookは削除しません。設定JSONを解析できない場合、切断とuninstallは
payloadを残して安全停止します。

`settings.json.fragment` は生成形の参照用です。通常利用では手動マージしません。
