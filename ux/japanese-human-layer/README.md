# Japanese Non-Engineer Layer for Umeboshi Harness

日本人の非エンジニアが、日常の雑で曖昧な日本語で AI に安全に仕事を依頼できる「Human UX 変換層」です。
下回りの **Umeboshi Harness Core（権限・状態管理・検証）** はそのまま稼働し、その表面で自然言語と構造化タスクの橋渡しを行います。

---

## 🌟 特徴

1. **曖昧な日本語をそのまま受け入れ**:
   - 「これいい感じにしといて」「前みたいにお願い」「この辺片付けといて」などの言葉を正常系として処理します。
2. **内部専門用語の完全隠蔽**:
   - `scope_digest`, `authority_touch`, `canonical decision`, `verification=PASS` などの専門用語を画面に出さず、自然な日本語でやり取りします。
3. **「やること / しないこと」の自然語プレビュー**:
   - 実行前に、勝手な削除や外部送信をしないことを明確にし、3択（進める / 修正する / やめる）で提示します。
4. **一括質問（Decision Batching）**:
   - 不足している情報は途中で小出しに質問せず、最初に 1 回でまとめて確認します。
5. **Work Type 別の完了確認と安心な結果報告**:
   - 作業完了時に「変更していないもの（元データ等）」を明記し、安全に終了します。

---

## 📁 構成

```text
japanese-human-layer/
├── README.md
├── contracts/
│   └── human_request_contract.md       # 入出力規約と 3つの Work Type 定義
├── prompts/
│   ├── intent_interpreter.md           # 曖昧な日本語の意図推定 + clarification_assessments出力
│   ├── clarification_batcher.md        # 不足事項の一括質問フォーマット
│   ├── execution_preview.md            # 「やること / しないこと」の自然語プレビュー
│   └── result_presenter.md             # 「やったこと / 触っていないもの」の結果報告
├── fixtures/
│   ├── vague_requests_ja.jsonl         # 曖昧な入力テストケース
│   └── expected_behavior.jsonl         # 期待される動作データセット
└── tests/
    └── test_human_layer.py             # fixture自己整合性テスト（Layer 1・LLM不使用）
```

`intent_interpreter.md`のLLM出力を実際に決定論的処理へ通す実装は
`../../runtime/human_layer_adapter.py`（Clarification Impact Contract v0 Rev.2）。
本ディレクトリのfixtureテストはプロンプト定義とfixtureの整合性のみを検証し、
実LLM挙動・Authority Overlay・Clarification判定は`../../tests/test_human_layer_adapter.py`
（Structural Gate）と`../../tests/case1_v2_sampling_contract.md`（Semantic Gate）で検証する。

---

## 🧪 受入テスト（Fixture整合性のみ・Layer 1）

```bash
# ume-harnessパッケージルートから実行する場合:
python3 ux/japanese-human-layer/tests/test_human_layer.py
```
- Case 1: 「資料まとめてREADME直して」➔ 質問なし・編集Preview・自然語報告
- Case 2: 「前みたいにこれお願い」➔ 捏造なし・1回で一括確認
- Case 3: 「いらんやつ消しといて」➔ 勝手削除阻止・候補一覧の承認要求
- Case 4: 「まとめて先方に送っといて」➔ 宛先一括確認・作成と送信の権限分離
