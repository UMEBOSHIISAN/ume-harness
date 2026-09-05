# UME-HARNESS

[English](README.en.md) · Technical Preview · [v0.1.6](https://github.com/UMEBOSHIISAN/ume-harness/releases/tag/v0.1.6)

このmain上のREADMEには、歴史的なv0.1.6 Release後の未公開の公開面・導入改善が含まれます。公開済みv0.1.6の配布bytesは書き換えません。

[![CI](https://github.com/UMEBOSHIISAN/ume-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/UMEBOSHIISAN/ume-harness/actions/workflows/ci.yml)

<p align="center">
  <img src="assets/brand/ume-harness-lockup.svg" alt="UME-HARNESS" width="640">
</p>

> 日本語で、雑に頼める。
>
> 作業へ進む前に、
> 「確認できる範囲」と「確認が必要な操作」を見える形にする。

UME-HARNESSは、日本語の曖昧な依頼を
範囲の見えるローカル作業案へ整理する
日本語を中心に設計したハーネスです。

現在は、日本語Human Layerのpreview CLIと、
Claude Codeのlocal workを説明・制限するHost Adapterを提供します。

standalone CLIはファイル操作を実行しません。
非エンジニア向けの導入容易性は現在検証中です。

<p align="center">
  <picture>
    <source media="(prefers-reduced-motion: reduce)" srcset="assets/readme/ja/ume-harness-human-layer-poster.png">
    <source media="(max-width: 600px)" srcset="assets/readme/ja/ume-harness-human-layer-poster.png">
    <img src="assets/readme/ja/ume-harness-human-layer.gif"
         alt="曖昧な日本語の依頼を、確認できる範囲と確認が必要な操作へ整理し、まだファイル操作を実行していないと示すHuman Layerの図解。"
         width="100%">
  </picture>
</p>

このGIFはstandalone CLIのpreview体験を説明するものです。
動きを抑える設定または600px以下の画面では、同じ意味の縦型静止ポスターを表示します。

## PURPOSE

人間は最初から、機械向けの完全な指示を書く必要はありません。
UME-HARNESSは、普通の日本語で受けた依頼を、AI coding agentが作業を始める前に
確認できる範囲へ整理します。

人間が全部を細かく操作するのでも、AIへ全部を明け渡すのでもなく、
今回確認できる範囲、確認が必要な操作、まだ実行していないことを先に見える形にするためのローカル作業面です。

## 現在の実装

現在のreleaseには、役割の異なる二つのsurfaceがあります。

### 日本語Human Layer preview CLI

日本語の依頼を、確認なしで進めてよい内容と、実行前にあなたの確認が必要な操作として表示します。
質問が残る場合は、作業を始める前にまとめて表示します。
standalone CLIは「まだ実行されていません」と表示し、preview/reportまでで停止します。

CLIはClaude Sonnet 5を呼ぶ構成ですが、現行releaseからraw semantic runへ到達できないため、
モデル精度を保証しません。保存済みfixtureを使うオフライン経路もあります。

### Claude Code Host Adapter

Claude Codeのlocal lease、worktree、path、capability境界を扱います。
PreToolUse、PermissionRequest、PostToolUseFailureの3 hookとLease Gateをstatic・結合テストしています。

Claude Codeは最初の統合・検証済みHost Adapterです。v0.1.6では、isolated install済みexact
candidate bytesによるinteractive physical live E2Eを確認済みです。非対話`claude -p`、MCP実行、
未知toolのpass-throughはこのreleaseの主張に含めません。

## Mothershipとの責務分担

UME-HARNESSは人間の意図を範囲の見えるローカル作業案へ整理します。
Mothershipは人間の判断をひとつの外部操作に対する限定Authorityへ結び付けます。

<p align="center">
  <img src="assets/readme/ja/ume-stack-responsibility.svg"
       alt="UME-HARNESSがローカル作業を整え、未実装の破線を経てMothershipが外部結果の権限を扱う責務分担図。"
       width="760">
</p>

現在の公開版同士に自動接続はありません。破線部分は未実装です。
UME-HARNESSは外部のConsequential Authorityを持たず、Mothershipを自動で呼び出しません。

## Preview Quick Start

```bash
git clone https://github.com/UMEBOSHIISAN/ume-harness.git
cd ume-harness
./scripts/install.sh

~/.local/bin/ume-harness "このフォルダの資料まとめて、必要ならREADMEもいい感じに直しといて" \
  --context "現在の作業フォルダには資料3件とREADME.mdがあります。"
```

この通常経路には、Claude CLIの認証とネットワーク接続が必要です。
解釈のため、依頼文とcontextをClaudeへ送ります。standalone CLI自体は、
依頼されたファイル操作や外部結果は実行しません。

LLMを呼ばないオフライン確認:

```bash
~/.local/bin/ume-harness --llm-output-file <path-to-json>
```

historicalな入出力例は[examples/basic_usage.md](examples/basic_usage.md)にあります。

## 日本語で操作を説明する

Translation Konjacは、tool eventを人間向けの日本語へ言い換えるpresentation-onlyの層です。
たとえば「読む」「PCの外へ出る」「削除する」を、現在のlanguage packにある言葉で説明します。

<p align="center">
  <img src="assets/readme/ja/translation-konjac-cards.svg"
       alt="読み取り、PC外への送信、削除を日本語で説明するTranslation Konjacの三つのカード。"
       width="100%">
</p>

この表示は権限を発行せず、External Action Authorityにもなりません。
判断できない操作は、勝手に進めず確認へ戻します。

## インストールとClaude Code接続

### インストール

```bash
git clone https://github.com/UMEBOSHIISAN/ume-harness.git
cd ume-harness
./scripts/install.sh
```

デフォルトでは `~/.local` にインストールします。commandが見つからない場合:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

v0.1.5からv0.1.6へ更新する場合は、新しいsource checkoutから旧releaseを検証して取り外し、
その後に新releaseをインストールします。`--force`はcross-version更新には使いません。

```bash
./scripts/uninstall.sh --version v0.1.5 --settings-path "${HOME}/.claude/settings.json" --yes
./scripts/install.sh
```

### Claude Codeへ接続・切断

Package installだけでは既存のClaude Code設定を変更しません。接続は明示的に行います。

```bash
ume-harness setup --yes
```

切断:

```bash
ume-harness setup --disconnect
```

setup/disconnectが所有するのは、setup自身が生成した3本のcanonical hook commandとの完全一致だけです。
他event、他matcher、他hookには触れません。設定を安全に解析・再検証できなければ停止します。

### 診断・アンインストール

```bash
python3 ~/.local/lib/ume-harness/v0.1.6/scripts/health_check.py
# またはrepository内から
python3 ./scripts/health_check.py

./scripts/uninstall.sh --settings-path "${HOME}/.claude/settings.json" --yes
```

custom settings pathやprefixを使った場合は、setupとdisconnect/uninstallで同じ値を指定してください。
uninstallはowned hooksとpayloadを検証し、無関係なClaude設定と `~/.ume-harness/state` を保持します。

## 現在の制約

- UME-HARNESSはOS sandboxではありません。trusted host entrypointを前提にします。
- standalone Human Layer CLIはpreview/reportのみで、ローカル作業を実行しません。
- Claude adapterのapproval-required operationを再開するconfirmation token経路は未接続です。
- expected-state、concurrent、out-of-band mutation検知primitiveはありますが、Claude host lifecycleには未接続です。
- macOS arm64のisolated lifecycleを確認済みです。Linux/POSIXはexpected/unverified、Windows nativeはunsupportedです。
- OS pseudo-fileのsecret検出は網羅的ではありません。
- identity authentication、RBAC、external executor/verifier、retry、daemonは提供しません。
- MothershipとのConsequenceProposal producerやruntime bridgeはありません。
- 非エンジニアを主要な設計対象にしていますが、導入容易性はまだ実測評価中です。

## Sourceとreleaseの境界

`ume-harness-engineering`だけがcanonical sourceです。
public `ume-harness`は明示closureから生成するrelease mirrorであり、公開側の手修正や
publicからengineeringへの逆同期はサポートしません。

機械的なrelease closureは[package_manifest.json](package_manifest.json)の `release.payload`、
表示用一覧は[MANIFEST.md](MANIFEST.md)です。`scripts/release_promote.py`はcanonicalからpublic stageへの
一方向copy、identity生成、test、mirror比較だけを行い、publishやpushは行いません。

installed payloadはfrozen byte identityで検査されます。ただしinstall provenanceは、
trusted canonical/generated-release checkoutを前提とし、独立した署名検証ではありません。

## 技術資料

- [Human Layer（公開済みv0.1.6の設計資料）](ux/japanese-human-layer/README.md)
- [Claude Code adapter](adapters/claude-code/README.md)
- [Authority contract](contracts/authority_contract.md)
- [Tool policy](contracts/tool_policy.md)
- [Support matrix](SUPPORT_MATRIX.md)
- [Security boundary](SECURITY.md)
- [Release manifest](MANIFEST.md)

テスト:

```bash
python3 -m pytest -q -p no:cacheprovider tests ux/japanese-human-layer/tests
```

## License

プロジェクトのコードはMITです。詳細は [LICENSE](LICENSE) と [NOTICE](NOTICE) を参照してください。
README asset生成用に同梱するNoto Sans JPは
[SIL Open Font License 1.1](assets/readme/source/fonts/OFL-1.1.txt)です。
