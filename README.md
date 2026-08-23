# Umeboshi Harness (Portable Edition)

> **Deterministic Decision / Authority Core + Claude Code Bounded-Execution Adapter**
> 日本人の非エンジニアが自然な日本語で安全に仕事を任せられる、オープンソースの
> 意思決定ロジック基盤および作業ツリー実行権限制御アダプタ。

## 📌 現在のステータス（v0.1.0・2026-08-23）

- **製品の位置づけ**:
  本パッケージは「決定論的意思決定・権限管理コア」および「Claude Code 向け作業ツリー実行境界アダプタ（Lease Gate）」です。
  **※ 完全自動で外部操作まで完結する Turnkey 秘書アプリや、無人自律実行エンジンではありません。**
- **対応モデル**: **Claude Sonnet 5 のみ。** 詳細・実測数値は `SUPPORT_MATRIX.md`。
  Gemma 4:12bは現時点で未対応（P1別チケット）。
- **単一CLI入口**: `ume-harness`（`bin/ume-harness`）。日本語の依頼文を渡すと、
  Authority Overlay + Clarification Impact Contractの判定結果を自然語で表示する。
- **Claude Code 境界保護アダプタ**: `adapters/claude-code/pretooluse_hook.py` + `lease_gate_runner.py`。
  Active Lease 下の作業ツリー境界保護（Read/Write スコープ逸脱遮断）、Bash 合成攻撃防御、
  `.ume-harness/**` コントロールプレーン保護を単体テスト済み（44/44 PASS）。
- **インストーラ・ライフサイクル**: `scripts/install.sh`, `scripts/health_check.py`, `scripts/uninstall.sh` 実装・検証済み。

---

## 🌟 主な特徴

1. **日本人の非エンジニア向け UX（Japanese Human Layer）**:
   「これいい感じにしといて」「前みたいにお願い」といった曖昧な指示を安全に解釈。
   専門用語を画面に出さず、「やること / しないこと」を自然語で提示。
2. **一括確認（Decision Batching）**:
   不足情報を細切れに質問せず、最初に1回でまとめて確認。
3. **Authority Overlay & Local Execution Lease**:
   危険な削除コマンドや外部送信を自動検知し、人間の明示承認なしには実行させない。
   Active Lease 下では作業ツリー外への Read/Write および `.ume-harness/**` 改ざんを決定論的に遮断する（`contracts/authority_contract.md`）。
4. **Clarification Impact Contract**:
   「人間に確認すべきか」を、6次元の構造化impact判定＋fail-safe原則で決定論的に導出
   （`design/clarification_impact_contract_v0.md`）。

---

## 🛡️ 脅威モデルと信頼前提 (Threat Model)

- **Trusted Host Entrypoint Prerequisite**: インストールされた Claude Code エントリポイント（`pretooluse_hook.py`）は信頼されたホスト前提として動作します。同一 UID プロセスや手動によるエントリポイント自体の直接改変・置換は防御対象外です。
- **In-Scope (防護対象)**:
  - Active Lease 下での Claude Code による作業ツリー外ファイルアクセス（Read / Write / cat / head / grep スコープ逸脱）
  - シェルインジェクションおよびコマンド合成攻撃（`;`, `&&`, `||`, `$()`, リダイレクト等）
  - `<worktree>/.ume-harness/**` コントロールプレーン領域の改ざん
  - 非承認の外部副作用（`git push`, `ssh` 等）および破壊的操作（`rm -rf` 等）
  - 15-Artifact Runtime Closure の完全性改ざん検知

---

## 🚀 インストールとクイックスタート

### 1. インストール

```bash
git clone https://github.com/UMEBOSHIISAN/ume-harness.git
cd ume-harness
./scripts/install.sh
```

デフォルトで `~/.local`（実行ファイル: `~/.local/bin/ume-harness`）にインストールされます。

#### PATH の確認
インストール後に `ume-harness` コマンドが見つからない場合は、以下を実行してください：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

### 2. 重要: Package Install ≠ Claude Code Host Activation

`install.sh` は `ume-harness` 本体と標準アダプタ資産を配備しますが、**既存の `~/.claude/settings.json` やフックを自動変更・上書きすることはありません**。

Claude Code と連携させる場合は、[`adapters/claude-code/README.md`](adapters/claude-code/README.md) を参照して手動で設定を行ってください。

---

### 3. CLI の使用（対話1回分の依頼を処理する）

```bash
# Claude Sonnet 5（claude CLI）が必要
ume-harness "このフォルダの資料まとめて、必要ならREADMEもいい感じに直しといて" \
  --context "現在の作業フォルダ: ~/Documents/資料/ 。中身は doc1.pdf, doc2.pdf, doc3.pdf, README.md の4件のみ。"
```

実際の入出力例（架空データではなく実測）: `examples/basic_usage.md`

オフラインテスト（API呼び出しなし。既存のLLM出力JSONを直接渡す）:
```bash
ume-harness --llm-output-file <path-to-json>
```

---

### 4. 診断とアンインストール

インストール状態の診断（ヘルスチェック）:
```bash
python3 ~/.local/lib/ume-harness/v0.1.0/scripts/health_check.py
# または、リポジトリ内から:
python3 ./scripts/health_check.py
```

アンインストール（リポジトリ内から実行）:
```bash
./scripts/uninstall.sh
```

---

### 5. テスト実行

```bash
python3 tests/test_portable_core.py          # 39 passed
python3 tests/test_human_layer_adapter.py    # 42 passed
python3 tests/test_cli.py                    # 13 passed（LLM不使用）
python3 tests/test_claude_code_adapter.py    # 44 passed（LLM不使用）
pytest tests/ ux/japanese-human-layer/tests/ # 110 passed
```

### さらに詳しく

- 意思決定ロジックの詳細契約: `contracts/authority_contract.md` / `contracts/tool_policy.md`
- 日本語UXレイヤーの詳細: `ux/japanese-human-layer/README.md`
- 対応モデル・実測根拠: `SUPPORT_MATRIX.md`
- Rev.2設計の全文（FROZEN）: `design/clarification_impact_contract_v0.md`

---

## ⚠️ 既知の制約（Known Limitations）

```yaml
overwrite_is_destructive:
  内容: 既存ファイルの内容を上書きする操作は DESTRUCTIVE に分類される
        （削除と同じ扱い＝承認要求）。安全側の設計であり意図的。
  影響: 「更新」のつもりでも承認が求められる場合がある

lexical_keyword_matching:
  内容: Authority Overlayの候補action分類は単純な部分文字列一致であり、形態素解析はしない
        （例: 「読み込む」は「読み込み」というkeywordと厳密一致しないためUNKNOWN扱いになる）
  影響: fail-closedのため安全上の問題はないが、動詞の活用形によって過剰に
        承認要求されることがある
  実例: examples/basic_usage.md「観察」節

work_type_null:
  内容: LLMがwork_type（RESEARCH/EDIT_CREATE/ORGANIZE）を確信を持って選べない場合、
        `work_type: null` + `classification_status: "UNRESOLVED"` になる
  影響: これはエラーではない。ASK/APPROVAL_REQUIRED判定には影響しない
        （work_typeは分類の記録用であり、Clarification Impact判定はimpactフィールドのみで決まる）

candidate_action_omission (KNOWN_RESIDUAL_SEMANTIC_RISK):
  内容: Authority Overlayは`candidate_actions`にLLMが実際に列挙したactionしか検査できない。
        LLMが危険な操作（削除・送信等）をcandidate_actionsに一切含めなかった場合、
        Core側にはそれを検出する手段がない
  影響: これはバグではなく、Structural Gateでは原理的に閉じられないsemantic
        omissionとして設計時から明記されている（`design/clarification_impact_contract_v0.md`
        「Gate Redefinition」節）。keyword crosscheck等でCore側から再検出する対策は、
        設計判断として意図的に不採用（第二分類器化のリスクの方が大きいため）
  検証: `tests/evidence/PORTABILITY_TRIAL_20260820.md`でadversarial sub-checkとして
        実演・確認済み
```

---

## 📁 パッケージ構成

構成の正本は`MANIFEST.md`（実findとの完全一致を`test_portable_core.py`が機械検証）。

```text
ume-harness/
├── README.md / LICENSE / NOTICE / VERSION / MANIFEST.md / package_manifest.json
├── PHASE4_HOLD.md / QUARANTINE_NOTICE.md / SUPPORT_MATRIX.md
│
├── bin/ume-harness                     # ★単一CLI入口（実装済み・テスト済み）
│
├── contracts/                          # 規約・入出力契約（4本）
├── runtime/                            # 決定ロジックライブラリ（tool_policy.py /
│                                         human_layer_adapter.py / decision_state.py /
│                                         stop_adapter.py）
├── schemas/                            # LLM出力contractのJSON Schema
├── examples/                           # 実測データに基づく使用例
├── design/                             # Rev.2設計書（FROZEN）
│
├── ux/japanese-human-layer/            # 日本語UXプロンプト＋fixture
│
├── adapters/claude-code/               # PreToolUse hook（実装済み）+ Stop hook説明
│                                         （NOT_IMPLEMENTABLE理由の明記）
├── scripts/                            # インストール・診断・アンインストール（install/health_check/uninstall）
│
└── tests/                              # 単体テスト5本 + Case1 v2契約2本（FROZEN）+
                                          隔離済み記録1本 + evidence/（実測証跡・INDEX.md参照）
```

**受入検証は `tests/case1_v2_sampling_contract.md`（Sampling Contract Rev.2: Claude Sonnet 5 pooled 0% prunable present / 0/6 false negatives）および単体・結合テスト全通により検証済み。**

---

## 📜 ライセンス
本プロジェクトは **MIT License** の下で公開されています。詳細は`LICENSE`・`NOTICE`参照。
