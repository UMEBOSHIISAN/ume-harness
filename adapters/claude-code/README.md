# Claude Code Adapter (ume-harness)

Claude Code と ume-harness Safety Core & Auto Translation Konjac を接続するアダプター群です。

## 提供フック一覧

1. **`PreToolUse` (`pretooluse_hook.py`)**
   - ツール実行直前にプッシュ型で日本語意味訳を自動表示します。
   - Safety Core (Lease Gate / Tool Policy) による自律停止・実行ゲート評価を実施します。

2. **`PermissionRequest` (`permission_request_hook.py`)**
   - ユーザーへ手動許可プロンプトが表示される直前に、構造化された詳細解説バナーを表示します。

3. **`PostToolUseFailure` (`posttooluse_failure_hook.py`)**
   - コマンドやツールの実行が失敗した際に、過度な安心感を与えず事実に基づくトラブルシューティング案内を表示します。

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
