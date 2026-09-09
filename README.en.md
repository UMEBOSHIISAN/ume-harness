# UME-HARNESS

> v0.1.7 Technical Preview. Standard connection is presentation-only; the
> optional macOS permission notice is explicitly selected per process.
> Host-dependent display and the unconnected surfaces in the Support Matrix remain limitations.

[日本語](README.md) · [Technical Preview v0.1.7](https://github.com/UMEBOSHIISAN/ume-harness/releases/tag/v0.1.7) · [Previous v0.1.6](https://github.com/UMEBOSHIISAN/ume-harness/releases/tag/v0.1.6)

This README describes the published v0.1.7 release. v0.1.6 verification is
identified as historical evidence. The integrated Pillow update and documentation
corrections are also absent from the published v0.1.6 tag and distribution.

[![CI](https://github.com/UMEBOSHIISAN/ume-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/UMEBOSHIISAN/ume-harness/actions/workflows/ci.yml)

<p align="center">
  <img src="assets/brand/ume-harness-lockup.svg" alt="UME-HARNESS" width="640">
</p>

> **After you ask AI for help, can you see what comes next?**
>
> UME helps organize the work. You decide.

You want to say “make this better,” while understanding what might change.
UME-HARNESS is a local work harness designed around Japanese-language requests.

Before work proceeds, its preview CLI organizes a request into proposed work
and questions to resolve.

The standalone CLI presents a plan; it does not perform file operations.

The standard Claude Code integration adds Japanese explanatory messages to
permission requests and tool execution failures. Permission decisions follow
Claude Code's existing settings; UME adds no execution restrictions in this mode.
Additional restrictions require explicit `--managed` setup.
Ease of adoption for non-engineers remains under evaluation.

<p align="center">
  <picture>
    <source media="(prefers-reduced-motion: reduce)" srcset="assets/readme/en/ume-harness-human-layer-poster.png">
    <source media="(max-width: 600px)" srcset="assets/readme/en/ume-harness-human-layer-poster.png">
    <img src="assets/readme/en/ume-harness-human-layer.gif"
         alt="Human Layer turns an ordinary ambiguous request into visible scope and actions requiring confirmation, ending before file operations run."
         width="100%">
  </picture>
</p>

The GIF explains the standalone CLI preview surface.
Reduced-motion settings and screens up to 600px use the equivalent vertical static poster.

## PURPOSE

People should not need to write machine-perfect instructions before asking for
help. UME-HARNESS organizes an ordinary request into a scope that can be
reviewed before an AI coding agent begins local work.

It is a local-work plane for making visible what may proceed without
confirmation, what needs confirmation, and what has not run yet—without
requiring a person to micromanage everything or hand over all control.

## What changes in v0.1.7

- Standard setup connects two Japanese presentation hooks for permission requests and failures. Claude Code retains native permission decisions for ordinary work.
- Explanations avoid echoing raw command arguments and paths, and distinguish confirmation, refusal, and evaluation errors.
- Settings updates stop on detected conflicts, and forced replacement of an existing installation is refused.

Conservative Lease enforcement requires explicit `--managed` setup. Details and migration steps follow below.

## What changed in v0.1.6

The Claude Code adapter now handles the flow of loading tool definitions, asking
a question, and reviewing a work plan.

- `ToolSearch` returns control to Claude Code instead of being blocked as an unknown tool. Each subsequently invoked tool still receives its own permission check.
- Claude Code owns questions and plan approval through `AskUserQuestion` and `ExitPlanMode`. The harness does not answer or approve on your behalf.
- An installed v0.1.6 candidate was exercised through questions, plan review, reading, writing, and failure notification. The `EnterPlanMode` interaction was observed; emission of its PreToolUse event was not established.

See the [support matrix](SUPPORT_MATRIX.md) for the measured scope and features
that are not connected to the host lifecycle.

### Maintenance in this branch

Pillow changes from 11.3.0 to 12.3.0. It is a development dependency for generating
README images, not a dependency of normal installation or CLI execution. All
eight regenerated images are byte-identical to the previous outputs. This update
does not add work-execution or automatic-approval features.

## Current implementation

This release has two distinct surfaces.

### Human Layer preview CLI

It shows candidate actions that may proceed without confirmation, actions that
require your confirmation, and any questions that must be answered first.
The standalone CLI stops at preview/report and does not perform file operations.

The CLI calls `claude -p --model sonnet`; it does not pin an exact model version.
The distribution does not include raw runs needed to recheck interpretation
accuracy, so no accuracy guarantee is made. An offline path accepts stored JSON
without an API call.

### Claude Code Host Adapter

The adapter handles local leases and worktree, path, and capability boundaries
for Claude Code. Its three hooks and Lease Gate have static and integration tests.

Claude Code is the first integrated and validated Host Adapter. In v0.1.6,
interactive physical live E2E was demonstrated from installed exact candidate
bytes. Non-interactive `claude -p`, MCP execution, and arbitrary unknown-tool
pass-through remain outside this release's claims.

## Responsibility split with Mothership

UME-HARNESS turns human intent into a bounded local-work preview.
Mothership binds a human decision to bounded authority for one external action.

<p align="center">
  <img src="assets/readme/en/ume-stack-responsibility.svg"
       alt="Responsibility map in which UME-HARNESS bounds local work and Mothership handles consequential authority across an unimplemented dashed bridge."
       width="760">
</p>

The current public releases have no automatic runtime bridge. The dashed connection is not implemented.
UME-HARNESS holds no external consequential authority and does not automatically invoke Mothership.

## Preview Quick Start (published v0.1.7)

First follow [release selection and installation](#install). These examples use
the dedicated v0.1.7 prefix.

For the currently published v0.1.7, use:

```bash
git clone --branch v0.1.7 --depth 1 https://github.com/UMEBOSHIISAN/ume-harness.git
cd ume-harness
./scripts/install.sh
```

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" "Please summarize the material in this folder and improve the README if needed" \
  --context "The current folder contains three documents and README.md."
```

The normal path requires an authenticated Claude CLI and network access. It
sends the request and context to Claude for interpretation. The standalone CLI
does not perform the requested file operations or consequential actions.

Offline check without an LLM call:

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" --llm-output-file <path-to-json>
```

A historical input/output example is in [examples/basic_usage.md](examples/basic_usage.md).

## Explain tool activity in human language

Translation Konjac is a presentation-only layer that describes tool events in
human-readable language. The cards below explain reading, leaving the PC, and
deletion using meanings from the current language pack.

<p align="center">
  <img src="assets/readme/en/translation-konjac-cards.svg"
       alt="Three Translation Konjac cards explaining read-only activity, sending outside the PC, and deletion."
       width="100%">
</p>

This presentation does not issue permission or become External Action Authority.
In standard connection, an unclassified explanation does not decide permission,
refusal, or an additional confirmation. Whether confirmation is required remains
Claude Code's decision under its native permission settings.

## Install and connect Claude Code

<a id="install"></a>

### Select and install a published release

Prerequisites: Git, Bash and Python 3.9 or later; connecting requires Claude Code
itself. Installation is physically verified on macOS arm64; see the
[Support Matrix](SUPPORT_MATRIX.md) for other platforms.

Check the published tag and notes on [Releases](https://github.com/UMEBOSHIISAN/ume-harness/releases).
`main` need not match a published release. Do not use an existing checkout's
`git pull` or in-place `--force` replacement as the upgrade procedure.

On 2026-09-09, v0.1.7 is the recommended version. Check the tag, release name and
publication status rather than relying only on Latest. For v0.1.6 or earlier, use that tag's README;
the presentation-only default described here does not apply retroactively.

**The following is the v0.1.7 procedure.** For another version, follow that release's
instructions. Use an unused checkout directory and a separate
prefix; the old payload, CLI and CC connection remain in place during installation.

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

If any step fails, do not switch connections. Do not overwrite existing checkout
or prefix directories. Keep the trusted source checkout for diagnosis/removal.
Package installation does not change CC settings. Use the full CLI path to avoid
accidentally selecting an older version on PATH:

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" setup --preview
```

<a id="update"></a>

### Existing users: verify installation, then switch connections

Complete the separate-prefix installation above first. Pause CC work and avoid
other writers to the same settings while switching. This example assumes the old
CLI is `~/.local/bin/ume-harness` and settings are `~/.claude/settings.json`.
Substitute the actual old CLI/settings first for a custom or local-trial install.

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

This explicitly selects presentation-only. To retain managed enforcement, add
`--managed` to the new setup command. Default setup preserving existing managed
hooks does not mean they survive a workflow that disconnects or uninstalls them.
New users skip the old disconnect and run only the new setup below.

Verify setting recognition and actual work in the target CC session; registration
inventory alone does not prove event delivery. Restart CC if changes are not
reflected. Keep the old prefix until the new installation works. On failure,
inspect the current state; do not blindly restore a whole old settings backup or
repeat setup to overwrite a conflict.

### Connect and disconnect Claude Code

Package installation does not modify existing Claude Code settings.
Connection is explicit:

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" setup --yes
```

v0.1.7 defaults to two presentation-only hooks: permission
requests and failures. Ordinary Python, search and external reads retain Claude
Code's native permission handling; no UME execution gate is registered.
**Standard connection does not enforce execution restrictions.** It neither
enforces UME Lease/path constraints nor changes native permissions. Permission to
use a tool is not approval for this request's scope. Request text and operating
instructions still apply, but this connection alone does not guarantee prevention
of unrequested implementation or consequential actions. Managed checks cover only
their supported representations, not the full meaning of human intent.
Choose `ume-harness setup --managed --yes` explicitly for conservative Lease
enforcement. Default setup preserves an existing managed connection but never
restores a removed PreToolUse. Disconnect first to switch managed to presentation.

### Migrate an older three-hook connection

Installing or running default setup alone does not remove existing enforcement.
Follow [the update sequence](#update): old CLI disconnect, then new CLI setup.
For a same-prefix connection-only change, run default setup immediately after
disconnect. Omit `--managed` for presentation-only. Keep custom prefixes and
settings paths consistent throughout. Open a new CC session and check that the
registration diagnostic reports `presentation`; file inventory does not prove
that a running host reloaded its settings.

Only UME-owned hooks are removed. Other hooks, native permissions, personal
RUNBOOKs and local rules are neither disabled nor distributed. Environments with
other gates are not promised identical behavior.

The following disconnects the installed v0.1.7 connection itself. For migration
from an older installation, use the old CLI disconnect in [the update sequence](#update), not this command.

```bash
"$HOME/.local/ume-harness-v0.1.7/bin/ume-harness" setup --disconnect
```

Setup/disconnect owns only exact matches for the three canonical hook commands
it generated. It does not touch other events, matchers, or hooks, and stops if
the settings cannot be parsed and revalidated safely.

UME setup/disconnect writers (including uninstall's disconnect) use a persistent
sidecar with the `.ume-harness.lock` suffix beside the settings file. Contention
ends without applying the requested change; there is no automatic retry, merge,
or restoration of an old backup. Detected external changes before saving stop
the write. A mismatch detected after replacement is reported as an unconfirmed
post-commit outcome. Do not replace or remove the lock file.
This advisory lock does not control non-cooperating CC/editor writers. A race
window remains between the final comparison and replacement: do not edit the
same settings elsewhere during connection/disconnection. This applies only to
the short settings update, not ordinary CC tool execution.

### Diagnose and uninstall

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

Run this from the retained trusted source checkout. With an explicit `--prefix`,
diagnostics require an executable CLI file at that prefix and do not substitute
the payload CLI. Source/stage diagnostics without a prefix do not verify an
installed wrapper. These diagnostics do not establish that a running CC session
has reloaded its settings or that a live event will fire.

Trial candidates can share VERSION while having different diagnostic
file hashes. Remove an old trial using the retained trusted source checkout that
installed that candidate, not an arbitrary newer source. If the matching trusted
source is unavailable, stop; do not disable ownership checks or delete manually.

Only when removing an installation, run the external trusted source uninstaller
with the exact target prefix/version. Removal also disconnects that installation's
owned hooks. The installed uninstaller cannot attest its own ownership:

```bash
./scripts/uninstall.sh --version v0.1.7 \
  --prefix "$HOME/.local/ume-harness-v0.1.7" \
  --settings-path "$HOME/.claude/settings.json" --yes
```

Use the same custom settings path and prefix for setup and removal.
Uninstall verifies owned hooks and payload, preserves unrelated Claude settings,
and keeps `~/.ume-harness/state`.

For an isolated failure after payload promotion but before wrapper creation,
removing the cause, using the ownership-checked external uninstall, then ordinary
installation successfully recovered. Same-version `--force` replacement is refused.
This does not cover partial wrappers or unverified files. If ownership verification
refuses removal, do not bypass it with manual deletion or `--force`.

### Optional Japanese macOS notifications

Default setup does not invoke a native notifier. Presentation depends on the CC
host and terminal; Japanese text inside the CC 2.1.263 permission dialog is not
guaranteed. To receive a separate fixed Japanese permission notice, install or
use an existing [terminal-notifier](https://github.com/julienXX/terminal-notifier),
manually allow its macOS notifications, then launch normally connected CC with:

```bash
UME_HARNESS_MACOS_NOTIFICATIONS=1 claude
```

This is a per-process opt-in. Launch a new CC without the variable to disable it.
UME never installs the dependency or changes OS notification permissions. Only
`/opt/homebrew/bin/terminal-notifier` and `/usr/local/bin/terminal-notifier` are
considered, not arbitrary PATH or project executables. The prototype was observed
on macOS26.6.2, notifier3.1.0 and CC2.1.263; final-package acceptance is separate.

The fixed notice says CC needs a permission decision. It does not translate the
operation, classify its safety, repeat commands/paths/content or approve anything.
Choose allow/deny in the original CC dialog. Missing notifier, denied notification
permission and notification errors add no UME execution denial; delivery is bounded
to one second without retry. OS settings and Focus can hide notifications. No
notification does not imply permission or safety.

### Diagnostic and presentation scope

`connected_mode` inventories only the specified settings file.
`session_hook_recognition` and `actual_hook_event` separately remain unknown until
verified in the target CC session and actual permission/failure events. Inspect
that session's hooks; restart if changes are not reflected. Other settings sources
are outside this inventory.

The two presentation hooks do not explain every operation or every error.
Non-interactive/background operation and pre-execution refusals may not trigger
them. UME's `--managed` does not mean Claude organization-managed settings;
policies such as `allowManagedHooksOnly` may prevent user hooks from loading.

New presentation entries use Claude's native timeout mechanism with a UME default of three seconds, without retry.
Existing timeout values, including absence, are preserved and differences reported.
To adopt that bound for existing entries, inspect the target and disconnect then
run default setup. Other hooks and organization policies are not removed. The
local user's separately adjusted Stop/native-permission rules are not distributed.
See [Claude hooks](https://code.claude.com/docs/en/hooks) and
[settings](https://code.claude.com/docs/en/settings).

## Public package versus personal configuration

Standard setup adds only `PermissionRequest` and `PostToolUseFailure`.
`SessionStart`, `UserPromptSubmit`, front-door routing, personal rules/skills,
MCP integrations and local write gates are not shipped features of this package.
Existing personal configuration is preserved. A local conversation therefore does
not establish behavior of the public package alone. The `--managed` PreToolUse
hook is a separate explicit connection.

Claude Code's Bash sandbox constrains Bash and its child processes. Built-in
Write/Edit tools use Claude Code's `Edit` permission rules. Sandbox path limits
alone do not establish a write prohibition across every tool; standard Harness
setup does not add those prohibitions. Check actual settings, hook registration
and tool permissions separately. Do not test protection by writing or deleting
real configuration files or hook directories.
See [Bash sandbox](https://code.claude.com/docs/en/sandboxing) and
[Read/Edit permissions](https://code.claude.com/docs/en/permissions#read-and-edit).

Determine the active version from the invoked CLI's target, verified installed
bytes, and registered hook paths. Multiple version directories do not establish
concurrent activation. Check references and ownership before using the existing
uninstall procedure for an older version.

Read/Grep/Glob failures describe reading or searching. They do not invent an
`UNKNOWN` exit code or request mutation checks solely because that read failed.
Write and unknown-tool failures still leave mutation state unconfirmed.

## Current limitations

- UME-HARNESS is not an OS sandbox; it assumes a trusted host entrypoint.
- Standard connection does not enforce UME Lease/path restrictions; native host permissions remain in charge.
- `--managed` is conservative: general network, arbitrary Python and unknown-tool execution are not supported promises.
- Managed targets with multiple hard links are refused. Path checks are not race-free OS isolation.
- The standalone Human Layer CLI is preview/report only and does not execute local work.
- Resume after an approval-required Claude operation is not wired to a confirmation-token path.
- Expected-state, concurrent, and out-of-band mutation primitives are not wired into the Claude host lifecycle.
- The isolated lifecycle is measured on macOS arm64. Linux/POSIX is expected but unverified; Windows native is unsupported.
- Secret detection for OS pseudo-files is not comprehensive.
- Identity authentication, RBAC, external executors/verifiers, retries, and daemons are not provided.
- There is no Mothership ConsequenceProposal producer or runtime bridge.
- Non-engineers are a primary design audience, but adoption ease remains under evaluation.

## Source and release boundary

`ume-harness-engineering` is the only canonical source. Public `ume-harness` is
a generated release mirror built from an explicit closure; public-side edits
and public-to-engineering reverse synchronization are unsupported.

The machine-readable release closure is `release.payload` in
[package_manifest.json](package_manifest.json); [MANIFEST.md](MANIFEST.md)
is its readable listing. `scripts/release_promote.py` performs one-way staging,
identity generation, tests, and mirror comparison. It does not publish or push.

The installed payload has a frozen byte identity. Installation provenance still
assumes a trusted canonical/generated-release checkout and is not an independent
signature verifier.

## Technical documentation

The packaged Human Layer README, contracts, and prompts describe the design.
Their proceed/revise/cancel interaction, work execution, and post-work report
are not an implemented end-to-end standalone CLI workflow. For implemented
behavior, use “Current implementation” above and the [support matrix](SUPPORT_MATRIX.md).

- [Human Layer (published v0.1.6 design material)](ux/japanese-human-layer/README.md)
- [Claude Code adapter](adapters/claude-code/README.md)
- [Authority contract](contracts/authority_contract.md)
- [Tool policy](contracts/tool_policy.md)
- [Support matrix](SUPPORT_MATRIX.md)
- [Security boundary](SECURITY.md)
- [Release manifest](MANIFEST.md)

Run the complete local suite:

```bash
python3 -m pytest -q -p no:cacheprovider tests ux/japanese-human-layer/tests
```

## License

The project code is MIT; see [LICENSE](LICENSE) and [NOTICE](NOTICE). The bundled
Noto Sans JP font used to generate README assets remains under the
[SIL Open Font License 1.1](assets/readme/source/fonts/OFL-1.1.txt).
