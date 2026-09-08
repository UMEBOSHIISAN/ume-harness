# UME-HARNESS

> 開発候補: 通常のローカル編集をClaude Code本体の権限へ戻す変更と、確認・禁止・
> 評価エラーを区別する変更を含みます。この候補は未公開です。
> 前段階の候補はローカル試用中ですが、v0.1.7最終候補の実機確認は未完了です。
> ローカルの使用感は、個人設定を含まない公開パッケージ単独の動作保証ではありません。
> 以下のv0.1.6実機確認は旧版の記録であり、この候補の動作保証ではありません。
> 詳細は `adapters/claude-code/README.md` を参照してください。

[English](README.en.md) · Technical Preview · v0.1.7（未公開候補） · [旧版 v0.1.6](https://github.com/UMEBOSHIISAN/ume-harness/releases/tag/v0.1.6)

このREADMEはv0.1.7開発候補の説明です。v0.1.6の検証結果は旧版の記録として区別します。
統合したPillow更新と説明文の修正も、公開済みv0.1.6のタグや配布ファイルには含まれません。

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

## v0.1.7候補で変わること

- 標準接続は、確認・失敗時の日本語説明2本です。通常の操作の権限判断はClaude Code本体に任せます。
- 日本語説明にコマンドの引数やパスをそのまま出さず、確認・拒否・評価エラーを区別します。
- 設定更新の競合を検出して停止し、既存インストールへの強制上書きを拒否します。

厳格なLease制限は明示的な `--managed` 接続で使います。詳細と移行手順は以下に記載します。

## v0.1.6で変わったこと

Claude Codeでツールを読み込み、質問に答え、作業計画を確認する一連の操作を扱えるようになりました。

- `ToolSearch`によるツール定義の読み込みを、未知のツールとして止めずにClaude Codeへ返します。読み込んだツールの実行は、その都度別に権限を確認します。
- `AskUserQuestion`と`ExitPlanMode`の質問・計画承認はClaude Code自身が扱います。Harnessが回答や承認を代行することはありません。
- インストールしたv0.1.6の実機テストで、質問・計画確認・読み取り・書き込み・失敗通知までの流れを確認しました。`EnterPlanMode`の操作は確認済みですが、そのPreToolUseイベントの発火までは確認していません。

検証範囲と未接続の機能は[Support matrix](SUPPORT_MATRIX.md)に記載しています。

### このブランチの保守更新

Pillowを11.3.0から12.3.0へ更新しました。PillowはREADME画像を生成する開発用依存関係で、
通常のインストールやCLI実行には使いません。生成し直した8点の画像は従来と同一です。
この更新で利用者向けの実行機能や自動承認機能が増えるわけではありません。

## 現在の実装

この候補には、役割の異なる二つのsurfaceがあります。

### 日本語Human Layer preview CLI

日本語の依頼を、確認なしで進めてよい内容と、実行前にあなたの確認が必要な操作として表示します。
質問が残る場合は、作業を始める前にまとめて表示します。
standalone CLIは「まだ実行されていません」と表示し、preview/reportまでで停止します。

CLIは`claude -p --model sonnet`を呼びます。モデルの固定バージョンは指定していません。
解釈精度を再検証するための生データは配布物に含まれないため、精度の保証はありません。
保存済みJSONを使うオフライン経路もあります。

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

## Preview Quick Start（公開済みv0.1.6）

```bash
git clone --branch v0.1.6 --depth 1 https://github.com/UMEBOSHIISAN/ume-harness.git
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
標準接続では、未判定という説明から許可・拒否・追加確認を決定しません。
確認が必要かどうかはClaude Code本体の権限設定と判断に従います。

## インストールとClaude Code接続

### 候補版のインストール

以下は検証済みのv0.1.7候補checkout内で実行する手順です。上のQuick Startは
旧版v0.1.6を取得するため、この候補の接続・診断手順とは組み合わせないでください。
候補は未公開で、公開配布用の取得コマンドはまだありません。

```bash
./scripts/install.sh
```

デフォルトでは `~/.local` にインストールします。commandが見つからない場合:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

v0.1.6からv0.1.7候補へ更新する場合は、新しいsource checkoutから旧releaseを検証して取り外し、
その後に新releaseをインストールします。同一版も含め、既存インストールへの
`--force`置換は変更前に拒否します。別prefixへの新規導入は可能です。
uninstallはUME所有hookの切断も伴います。通常setupが既存managed接続を保持する
という説明は、uninstallを含む更新手順全体の保持を意味しません。

```bash
./scripts/uninstall.sh --version v0.1.6 --settings-path "${HOME}/.claude/settings.json" --yes
./scripts/install.sh
```

### Claude Codeへ接続・切断

Package installだけでは既存のClaude Code設定を変更しません。接続は明示的に行います。

```bash
ume-harness setup --yes
```

開発候補版の標準接続は、確認時と失敗時の日本語説明2本だけです。
**標準接続は実行を制限する機能ではありません。** UMEのLease・path制限は強制せず、
Claude Codeの既存権限設定も変更しません。ツールを使えることと、今回人間が依頼した
範囲であることは別です。依頼文・運用指示は維持しますが、依頼範囲外の実装・重大操作を
本接続だけで防止する保証はありません。managedも検査できる範囲に限られ、意図全体は保証しません。
通常のPython・検索・外部読み取りの判断はClaude Code本体に任せ、追加の実行ゲートを登録しません。
明示的に厳格なLease判定を使う場合だけ `ume-harness setup --managed --yes` を選びます。
既存の厳格接続は通常setupで解除されません。説明だけへ変更するときは一度disconnectしてから通常setupします。
外したPreToolUseを通常setupが勝手に復活させることはありません。

### 旧版から「説明だけ」へ移行する

旧版の3本接続を使っていた場合、インストールや通常setupだけでは実行ゲートは外れません。
次版への更新では、**旧版を取り外す前に、旧版CLIで明示的に切断**してください。

```bash
"$HOME/.local/bin/ume-harness" setup --disconnect
```

その後、上記の旧版uninstall・新版installを行い、新版で `ume-harness setup --yes` を実行します。
同じ版・同じprefixで接続だけ変更する場合は、disconnectの直後に通常setupします。
custom prefixやsettings pathは全手順で一致させてください。`--managed`は付けません。
新しいCCセッションを開き、診断の接続状態が `presentation` であることを確認します。
これは登録ファイルの検査であり、実際のセッションが設定を再読した証明ではありません。

移行が変更するのはUME所有hookだけです。他のhook、native権限、個人のRUNBOOKや
ローカルルールは自動解除・配布しません。他のgateが残る環境で同じ挙動を保証するものではありません。

切断:

```bash
ume-harness setup --disconnect
```

setup/disconnectが所有するのは、setup自身が生成した3本のcanonical hook commandとの完全一致だけです。
他event、他matcher、他hookには触れません。設定を安全に解析・再検証できなければ停止します。

setup／disconnect（uninstallからの切断を含む）のUME設定更新同士は、設定の隣に置く
固定の `.ume-harness.lock` suffixのファイルで排他します。競合時は未反映で終了し、
自動再試行・自動マージ・古いバックアップへの自動復元はしません。
保存前に検出した外部変更は上書きせず停止します。保存後に不一致を検出した場合は、
反映後の確認不能として報告します。ロックファイルは置換・削除しません。
このロックに協調しないCC・エディタ等の任意タイミングの更新まで防ぐ保証はありません。
最後の比較と置換の間にも競合窓があるため、接続・切断中は同じ設定を別の処理で編集しないでください。
これは短い設定更新だけの排他であり、日常のCCツール実行に制限を追加するものではありません。

### 診断・アンインストール

```bash
python3 ~/.local/lib/ume-harness/v0.1.7/scripts/health_check.py
# またはrepository内から
python3 ./scripts/health_check.py

./scripts/uninstall.sh --settings-path "${HOME}/.claude/settings.json" --yes
```

custom settings pathやprefixを使った場合は、setupとdisconnect/uninstallで同じ値を指定してください。
uninstallはowned hooksとpayloadを検証し、無関係なClaude設定と `~/.ume-harness/state` を保持します。

### 診断と表示の範囲

診断の `connected_mode` は指定した設定ファイルの登録状態です。
`session_hook_recognition`（対象CCでの認識）と `actual_hook_event`（実際の発火）は
別々に未確認と表示します。対象セッションのhook設定と実際の確認・失敗イベントで
確かめてください。反映されない場合は再起動します。他の設定元はこの検査の範囲外です。

説明は対象イベントが発火した場合だけ届きます。全操作・全エラーの日本語化ではなく、
非対話・バックグラウンド実行や、実行前の拒否などでは届かない場合があります。
UMEの `--managed` はCCの組織管理設定とは無関係です。組織側の
`allowManagedHooksOnly` 等によってユーザーhookが読み込まれない場合もあります。

新規の説明hookにはCC標準のtimeout機構を使い、UMEの既定値として3秒を指定します。自動再試行はしません。
既存エントリのtimeout（未指定も含む）は変更せず、標準値と異なる場合は結果に明示します。
既存接続を3秒へ揃える場合は、対象を確認してdisconnect→通常setupしてください。
これは組織設定やユーザー独自hookの解除ではありません。
利用者PCで調整した公開対象外のStopルール・native権限はパッケージに移植しません。

仕様参照: [Claude Code hooks](https://code.claude.com/docs/en/hooks)、
[設定](https://code.claude.com/docs/en/settings)。

## 公開パッケージと個人設定の違い

標準接続でこのパッケージが追加するのは `PermissionRequest` と `PostToolUseFailure` の2本です。
`SessionStart`、`UserPromptSubmit`、front-door分類、個人用のrules・skills・MCP・write-gateは
本パッケージの機能ではありません。既存の個人設定をそのまま保持するため、ローカルの会話だけで
公開パッケージ単体の動作を判定しないでください。`--managed` の `PreToolUse` は別の明示的接続です。

Claude CodeのBash sandboxはBashとその子プロセスを制限します。組み込みのWrite／Editには
Claude Codeの `Edit` 権限ルールが適用されます。sandboxのパス制限だけで全ツールの書き込みを
禁止したとは判断できません。標準接続がこれらの禁止設定を追加することもありません。
保護対象の確認には、実際の設定・hookの登録・ツールごとの権限を照合してください。
本物の設定やhookフォルダへの書き込み・削除を発火テストに使わないでください。
仕様: [Bash sandbox](https://code.claude.com/docs/en/sandboxing)、
[Read／Edit権限](https://code.claude.com/docs/en/permissions#read-and-edit)。

版の確認では、フォルダ名の一覧ではなく、実行するCLIの参照先・診断のバイト照合・設定に登録された
hookの参照先を確認します。複数の版が残っていても、同時に動いているとは限りません。
古い版は現行の参照がないことと所有権を確認してから、既存のuninstall手順で扱います。

Read／Grep／Globの失敗は読み取り・検索の失敗として説明します。取得できなかった終了コードを
`UNKNOWN`として表示したり、その操作だけを根拠に変更状態の確認を求めたりしません。
書き込みや不明なツールの失敗では、変更の有無を断定しません。

## 現在の制約

- UME-HARNESSはOS sandboxではありません。trusted host entrypointを前提にします。
- 標準接続ではUMEのLease/path制限を強制しません。Claude Code本体の権限設定を保持します。
- `--managed`は保守的な追加制限です。ネットワーク・任意Python・未知toolの一般実行を保証しません。
- 厳格モードでは複数hardlinkのある対象を拒否します。path検査は競合更新に対するOS隔離ではありません。
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

配布物に含まれるHuman LayerのREADME・契約・プロンプトは設計資料です。
そこにある「進める／修正する／やめる」の対話、作業の実行、完了後の報告は、
現行standalone CLIが提供する一連の操作ではありません。実装済みの動作は上の
「現在の実装」と[Support matrix](SUPPORT_MATRIX.md)を参照してください。

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
