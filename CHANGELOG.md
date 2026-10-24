# Changelog

## [0.2.0] - 2026-10-24

### テーマ: 日本語の判断支援へ縮小する Technical Preview

**作業案と必要な判断を短く返す補助層に絞りました。v0.1.7との互換性を保つ更新ではありません。**
0.xの開発段階での互換性変更としてminorを更新します。既存v0.1.7のtag・Releaseは保持します。

#### 1. 実行・権限管理をホスト標準へ戻す

**今まで**: 独自managed/Lease、PreToolUse、承認token、Stop/継続状態、独自通知を配布していました。

**今後**: 作業前preview、PermissionRequest/PostToolUseFailureの日本語説明、接続・byte診断を残します。
previewは実行許可になりません。`ume-harness setup --managed` は設定変更前に非0で終了します。
旧接続は信頼できる旧source・prefixを保持して旧CLIの `setup --disconnect` で明示的に切断し、
別prefixに新規導入してください。自動移行・既存prefixの上書きは行いません。

#### 2. 明示的なオフライン引き継ぎ

**今まで**: `--json` は説明文の後にデバッグ情報を出す形式でした。

**今後**: `ume-harness --handoff-json --request '隔離したPRを確認する' --llm-output-file input.json`
で `ume.preview-handoff.v0` の単一JSONを返します。モデル呼出し・操作実行・権限発行は行いません。
UTF-8出力と通常ファイルの限定読取りを使い、symlinkや特殊ファイルを拒否します。
Mothership連携は別の明示的な入口を要し、自動接続はありません。

#### 3. 説明・配布の整合

**今まで**: READMEや図に、引退した実行管理機能との境界が残っていました。

**今後**: 日英README、GIF・静止画・責任分担図を現在の範囲へ更新しました。
`python3 scripts/health_check.py --installed-dir . --identity-only --json` で配布byte identityを確認できます。
この照合は署名認証や、実セッションでのhook発火の証明ではありません。

#### 4. 検証と未確認事項

**今まで**: 旧managedの実機測定と現在の縮小版の検証を混同し得ました。

**今後**: [Support Matrix](SUPPORT_MATRIX.md)に対象revision・合成データ・未確認範囲を分けて記録します。
対話PermissionRequest、他OS、一般的な日本語精度・使いやすさ、後続Mothership修正を含む導入E2Eは未確認です。
通常設定への導入・実canary・初見の人による受入を実施済みとは扱いません。

## Earlier releases

v0.1.7以前の変更と当時の動作は、各[既存Release](https://github.com/UMEBOSHIISAN/ume-harness/releases)とtagを参照してください。
