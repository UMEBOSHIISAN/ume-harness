# Claude Code Adapter (ume-harness)

Claude Code と ume-harness Safety Core & Auto Translation Konjac を接続するアダプター群です。

## 提供フック一覧

1. **`PreToolUse` (`pretooluse_hook.py`)**
   - ツール実行直前の日本語意味訳をClaude hookのstructured `systemMessage`として返します。
   - Safety Core (Lease Gate / Tool Policy) によるtool単位のallow/block評価を実施します。

2. **`PermissionRequest` (`permission_request_hook.py`)**
   - ユーザーへ手動許可プロンプトが表示される直前に、structured `systemMessage`と
     公式`terminalSequence`通知で詳細解説を提示します。どちらもPresentation-onlyで、
     許可・拒否・askのdecisionは返しません。

3. **`PostToolUseFailure` (`posttooluse_failure_hook.py`)**
   - コマンドやツールの実行が失敗した際に、`systemMessage`と`additionalContext`で
     過度な安心感を与えない事実ベースの案内を返します。

3本のstructured outputとPreToolUse deny（exit 2）はstatic adapter test済みです。
v0.1.6では、isolated install済みexact candidate bytesによるinteractive Claude UI 3-hook
E2Eも実機確認済みです。単体テストだけをlive表示証拠へ昇格させません。Translation KonjacはPresentation-onlyで、
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

インストール後、次のコマンドで3本のフックを接続します。既存設定は保持され、
同じコマンドを再実行しても重複しません。

```bash
ume-harness setup --yes
```

切断は次のコマンドです。

```bash
ume-harness setup --disconnect
```

切断対象はsetup自身が生成した次の3イベントのcanonical commandとの完全一致だけです。

- `PreToolUse`
- `PermissionRequest`
- `PostToolUseFailure`

他event、他matcher、他hook、およびcommand文字列に単に`ume-harness`を含むだけの
ユーザーhookは削除しません。設定JSONを解析できない場合、切断とuninstallは
payloadを残して安全停止します。

`settings.json.fragment` は生成形の参照用です。通常利用では手動マージしません。
