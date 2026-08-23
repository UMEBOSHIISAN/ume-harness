# Claude Code Adapter for ume-harness

このアダプタは、Portable Core（`runtime/local_execution_gate.py`, `runtime/tool_policy.py`）を
Claude Code CLI（`~/.claude/`）の PreToolUse hookとして接続し、決定論的な実行権限制御と
作業ツリー境界保護（Lease Gate）を提供する。

## 実装構成

```yaml
pretooluse_hook.py:
  status: IMPLEMENTED（Thin Host I/O Shim）
  対象: Claude CodeのPreToolUse hook (stdin JSON ➔ Exit 0 / Exit 2)
  動作: stdin から tool_name / tool_input を受け取り、lease_gate_runner.py に委譲

lease_gate_runner.py:
  status: IMPLEMENTED（Canonical Authenticated Verifier / Lease Gate）
  テスト: tests/test_claude_code_adapter.py 44/44 PASS
  機能:
    1. 15-Artifact Runtime Closure の完全性検証（改ざん時は ACTIVATION_TAMPER / Exit 2）
    2. Active Lease 下の作業ツリー境界保護（Read / Write / cat / head / grep スコープ逸脱をブロック）
    3. コントロールプレーン保護（<worktree>/.ume-harness/** への書き込みをブロック）
    4. Bash シェル構文解析と合成攻撃防護（;, &&, ||, $(), 反復クォート, リダイレクト等を fail-closed で遮断）
    5. 決定論的 SideEffect 分類（ALLOW 以外は APPROVAL_REQUIRED / Exit 2）

stop_hook:
  status: NOT_IMPLEMENTABLE（構造的な理由・今後も自動化しない設計判断）
  理由: runtime/stop_adapter.pyのAcceptanceCheckは「required_acceptance_criteria_
        satisfied」等の真偽値を呼び出し側が既に知っている前提のライブラリである。
        Claude CodeのStop hookのstdinには、この意味論的判断（タスクが実際に
        完了したか）を決定論的に導出できる情報が含まれない。これはLLM自身の
        意味理解を要する判断であり、Portable Core（決定論的ロジックのみ）の
        守備範囲外。
```

## 脅威モデルと信頼前提 (Threat Model)

- **Trusted Host Entrypoint Prerequisite**: インストールされた `pretooluse_hook.py` は信頼されたホスト前提として動作します。同一 UID プロセスや手動によるエントリポイントファイルの直接改変・置換はスコープ外です。
- **In-Scope (防護対象)**: Claude Code / Lease 媒介の作業ツリー外アクセス（Read/Write）、シェル合成・インジェクション攻撃、`.ume-harness/**` 改ざん、非承認の外部送信（`git push`, `ssh` 等）、ランタイムクロージャ改ざん。

## セットアップ

1. `./scripts/install.sh` を実行して `~/.local` にパッケージを配備します。
2. `settings.json.fragment` を参考に、`~/.claude/settings.json` の `hooks.PreToolUse` に以下を手動マージします：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.local/lib/ume-harness/v0.1.0/adapters/claude-code/pretooluse_hook.py"
          }
        ]
      }
    ]
  }
}
```

## 動作契約

```
stdin:  {"tool_name": "...", "tool_input": {...}, ...}
exit 0: 許可（stdout/stderrなし）
exit 2: 拒否 / 承認要求（stderrに理由）
```
