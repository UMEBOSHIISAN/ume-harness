# UME-HARNESS

> v0.1.7 Technical Preview: 通常のローカル編集をClaude Code本体の権限へ戻し、確認・禁止・
> 評価エラーを区別します。標準接続は説明専用で、macOS通知は明示選択です。
> ホスト・端末依存の表示や、Support Matrixに記載した未接続範囲は引き続き制約です。
> ローカルの使用感は、個人設定を含まない公開パッケージ単独の動作保証ではありません。
> 以下のv0.1.6実機確認は旧版の記録であり、このリリースの動作保証ではありません。
> 詳細は `adapters/claude-code/README.md` を参照してください。

[English](README.en.md) · [Technical Preview v0.1.7](https://github.com/UMEBOSHIISAN/ume-harness/releases/tag/v0.1.7) · [旧版 v0.1.6](https://github.com/UMEBOSHIISAN/ume-harness/releases/tag/v0.1.6)

このREADMEは公開済みv0.1.7の説明です。v0.1.6の検証結果は旧版の記録として区別します。
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

## v0.1.7で変わること

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

このリリースには、役割の異なる二つのsurfaceがあります。

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

## Preview Quick Start（公開済みv0.1.7）

```bash
git clone --branch v0.1.7 --depth 1 https://github.com/UMEBOSHIISAN/ume-harness.git
cd ume-harness
./scripts/install.sh

```

まず[公開版の取得・インストール](#install)を行ってください。以下はv0.1.7を
専用prefixへ導入して使う例です。

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" "このフォルダの資料まとめて、必要ならREADMEもいい感じに直しといて" \
  --context "現在の作業フォルダには資料3件とREADME.mdがあります。"
```

この通常経路には、Claude CLIの認証とネットワーク接続が必要です。
解釈のため、依頼文とcontextをClaudeへ送ります。standalone CLI自体は、
依頼されたファイル操作や外部結果は実行しません。

LLMを呼ばないオフライン確認:

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" --llm-output-file <path-to-json>
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

<a id="install"></a>

### 公開版を選んでインストール

前提はGit、Bash、Python 3.9以降です。Claude Codeへの接続にはClaude Code本体も必要です。
実機で確認した導入環境はmacOS arm64です。他OSの状況は[Support Matrix](SUPPORT_MATRIX.md)を参照してください。

[Releases](https://github.com/UMEBOSHIISAN/ume-harness/releases)で、更新先の公開済みtagと
Release notesを確認してください。`main`は公開Releaseと同一とは限りません。
既存checkoutの`git pull`や`--force`置換は更新手順に使いません。

2026-09-09時点の推奨版はv0.1.7です。Latestだけで選ばず、Release名・tag・公開状態を確認してください。
v0.1.6以前を導入する場合は、そのtagのREADMEに従います。このページの
「説明だけ」の標準接続はv0.1.7の仕様で、旧版へ遡って適用されません。

**以下はv0.1.7の手順です。** 別版を選ぶ場合は、そのReleaseの手順を優先します。
空いている作業ディレクトリで実行します。
専用prefixへ新規導入するため、旧版のpayload・CLI・CC接続はこの段階では残ります。

```bash
(
  set -eu
  UME_RELEASE_TAG=v0.1.7
  UME_PREFIX="$HOME/.local/ume-harness-$UME_RELEASE_TAG"
  git clone --branch "$UME_RELEASE_TAG" --single-branch \
    https://github.com/UMEBOSHIISAN/ume-harness.git "ume-harness-$UME_RELEASE_TAG"
  cd "ume-harness-$UME_RELEASE_TAG"
  test "$(cat VERSION)" = "${UME_RELEASE_TAG#v}"
  ./scripts/install.sh --prefix "$UME_PREFIX"
  test -x "$UME_PREFIX/bin/ume-harness"
  python3 ./scripts/health_check.py \
    --installed-dir "$UME_PREFIX/lib/ume-harness/$UME_RELEASE_TAG" --prefix "$UME_PREFIX"
)
```

どこかで失敗したら、その先の接続切替へ進みません。同じ名前のcheckout/prefixが
既にある場合は上書きせず、対象を確認してください。source checkoutは診断・取り外しに
使うため保持します。Package installだけではCCの設定を変更しません。

CLIは当面フルパスで使います。PATH上の旧版との取り違えを避けるためです。

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" setup --preview
```

<a id="update"></a>

### 既存利用者の更新：導入確認後に接続を切り替える

まず上の手順で新prefixへの導入を完了します。CCの作業を区切り、同じ設定を別の
処理で編集しない状態で切り替えてください。以下は旧CLIが`~/.local/bin/ume-harness`、
対象設定が`~/.claude/settings.json`の場合です。custom prefix/settingsを使っている場合は、
実際の旧CLIと設定へ置き換えてから実行します。ローカル試用版からの切替も同じです。

```bash
(
  set -eu
  UME_OLD_CLI="$HOME/.local/bin/ume-harness"
  UME_NEW_CLI="$HOME/.local/ume-harness-v0.1.7/bin/ume-harness"
  UME_SETTINGS="$HOME/.claude/settings.json"
  test -x "$UME_OLD_CLI"
  test -x "$UME_NEW_CLI"
  "$UME_OLD_CLI" setup --disconnect --settings-path "$UME_SETTINGS"
  "$UME_NEW_CLI" setup --yes --settings-path "$UME_SETTINGS"
)
```

これは**説明だけへ移る明示的な選択**です。managedを維持する場合は、新版setupへ
明示的に`--managed`を付けます。通常setupによる既存managed保持は、disconnectや
uninstallを含む更新手順全体の保持を意味しません。

新規利用者は旧CLIのdisconnectを行わず、次節の新版setupだけを実行します。
切替後は対象CCセッションで設定の認識と実際の作業を確認してください。登録診断だけでは
実発火の証明になりません。反映しない場合はCCを再起動します。新版が使えると確認するまで
旧prefixは取り外しません。失敗時は現状を診断し、旧settingsバックアップを丸ごと戻したり、
setupを繰り返して上書きしたりしないでください。

### Claude Codeへ接続・切断

Package installだけでは既存のClaude Code設定を変更しません。接続は明示的に行います。

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" setup --yes
```

v0.1.7の標準接続は、確認時と失敗時の日本語説明2本だけです。
**標準接続は実行を制限する機能ではありません。** UMEのLease・path制限は強制せず、
Claude Codeの既存権限設定も変更しません。ツールを使えることと、今回人間が依頼した
範囲であることは別です。依頼文・運用指示は維持しますが、依頼範囲外の実装・重大操作を
本接続だけで防止する保証はありません。managedも検査できる範囲に限られ、意図全体は保証しません。
通常のPython・検索・外部読み取りの判断はClaude Code本体に任せ、追加の実行ゲートを登録しません。
明示的に厳格なLease判定を使う場合だけ `ume-harness setup --managed --yes` を選びます。
既存の厳格接続は通常setupで解除されません。説明だけへ変更するときは一度disconnectしてから通常setupします。
外したPreToolUseを通常setupが勝手に復活させることはありません。

### 旧版から「説明だけ」へ移行する

旧版の3本接続は、インストールや通常setupだけでは外れません。
[更新手順](#update)の「旧CLIで切断→新版CLIで接続」に従ってください。
同じ版・同じprefixで接続だけ変更する場合も、disconnectの直後に通常setupします。
custom prefix/settingsを揃え、説明だけにする場合は`--managed`を付けません。
新しいCCセッションを開き、診断の接続状態が `presentation` であることを確認します。
これは登録ファイルの検査であり、実際のセッションが設定を再読した証明ではありません。

移行が変更するのはUME所有hookだけです。他のhook、native権限、個人のRUNBOOKや
ローカルルールは自動解除・配布しません。他のgateが残る環境で同じ挙動を保証するものではありません。

次は導入済みv0.1.7自身の接続を切断する例です。旧版の移行時には使わず、
[更新手順](#update)にある旧CLIのdisconnectを使ってください。

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" setup --disconnect
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
(
  set -eu
  test -x "$HOME/.local/ume-harness-v0.1.7/bin/ume-harness"
  python3 ./scripts/health_check.py \
    --installed-dir "$HOME/.local/ume-harness-v0.1.7/lib/ume-harness/v0.1.7" \
    --prefix "$HOME/.local/ume-harness-v0.1.7" \
    --settings-path "$HOME/.claude/settings.json"
)
```

上記は保持した信頼できるsource checkout内で実行します。`--prefix`を明示した診断は、
そのprefixのCLIが実行可能なファイルであることを必須とし、payload内CLIでは代替しません。
prefixを指定しないsource/stage診断は導入先wrapperの確認にはなりません。
この診断は登録・導入バイトを確認するもので、実セッションの設定再読込やイベント発火までは証明しません。

取り外す場合だけ、同じsource checkoutから対象prefix/versionを明示します。
これは接続済みの対象UME hookも切断します。導入先内のuninstallは自己所有証明に
使えないため、外部の信頼できるsource checkoutのものを使ってください。

```bash
./scripts/uninstall.sh --version v0.1.7 \
  --prefix "$HOME/.local/ume-harness-v0.1.7" \
  --settings-path "$HOME/.claude/settings.json" --yes
```

custom settings pathやprefixを使った場合は、setupとdisconnect/uninstallで同じ値を指定してください。
uninstallはowned hooksとpayloadを検証し、無関係なClaude設定と `~/.ume-harness/state` を保持します。

試用候補は、同じVERSIONでも診断ファイルのハッシュが異なる場合があります。
旧候補の取り外しには、その候補を導入したときの保持済みsource checkoutのuninstallを使います。
新版sourceで旧候補の所有確認が通るとは限りません。対応する信頼できるsourceがない場合は停止し、
所有確認の無効化や手動削除で回避しないでください。

新規導入がpayload配置後・CLI作成前に失敗したケースでは、失敗原因を解消し、上記の
所有確認付きuninstallで残留物を取り外してから通常installする復旧を隔離検証しています。
同一版への`--force`置換は拒否します。途中まで書かれたCLIや所有確認できないファイルまで
自動修復できる保証はありません。所有確認で止まったら、手動削除・`--force`で回避しません。

### macOSの日本語通知（明示選択）

通常setupだけではmacOSの通知ツールを呼びません。標準の説明表示はCC・端末によって
見え方が異なり、CC 2.1.263の許可ダイアログ内に日本語本文を追加する保証はありません。
許可待ちを日本語のデスクトップ通知でも知らせたい場合は、既存の
[terminal-notifier](https://github.com/julienXX/terminal-notifier)を用意し、macOSの
「システム設定 → 通知」でその通知を許可したうえで、通常setup済みのCCを次のように起動します。

```bash
UME_HARNESS_MACOS_NOTIFICATIONS=1 claude
```

有効化はその起動プロセスに限ります。無効にするには変数を付けず、新しいCCを起動します。
ハーネスは依存ツールのインストールやOSの通知許可を自動変更しません。
利用する実行先は `/opt/homebrew/bin/terminal-notifier` または
`/usr/local/bin/terminal-notifier` です。任意のPATHや作業フォルダからは探しません。
試験環境はmacOS 26.6.2、terminal-notifier 3.1.0、CC 2.1.263です。

通知は「CCが許可を求めている」という固定の案内です。操作内容の翻訳や安全性判定ではなく、
コマンド・パス・本文は再掲しません。許可・拒否は元のCC画面で行ってください。
未導入・通知拒否・送信失敗でもUMEから新たな拒否を返さず、通知処理は1秒で打ち切り、再試行しません。
通知はOS設定や集中モードで見えない場合があります。通知がないことは許可や安全の証明ではありません。
この経路は、macOSの通知許可と端末設定に依存します。通知がない場合も、元のCC画面で判断してください。

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
