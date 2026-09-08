# UME-HARNESS

[日本語](README.md) · Technical Preview · [v0.1.6](https://github.com/UMEBOSHIISAN/ume-harness/releases/tag/v0.1.6)

Released functionality below refers to v0.1.6. This branch also contains a Pillow
build-dependency update and documentation corrections; those changes are not
part of the published v0.1.6 tag or distribution.

[![CI](https://github.com/UMEBOSHIISAN/ume-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/UMEBOSHIISAN/ume-harness/actions/workflows/ci.yml)

<p align="center">
  <img src="assets/brand/ume-harness-lockup.svg" alt="UME-HARNESS" width="640">
</p>

> Start with an ordinary, imperfect request.
>
> Before work proceeds, make visible what may proceed without confirmation,
> what needs confirmation, and what has not run yet.

UME-HARNESS is a local work harness designed around Japanese-language requests
for AI coding agents.

It currently provides a standalone Human Layer preview CLI and a
Claude Code Host Adapter for explaining and bounding local work.

The standalone CLI presents a plan; it does not perform file operations.
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

The current release has two distinct surfaces.

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

## Preview Quick Start

```bash
git clone --branch v0.1.6 --depth 1 https://github.com/UMEBOSHIISAN/ume-harness.git
cd ume-harness
./scripts/install.sh

~/.local/bin/ume-harness "Please summarize the material in this folder and improve the README if needed" \
  --context "The current folder contains three documents and README.md."
```

The normal path requires an authenticated Claude CLI and network access. It
sends the request and context to Claude for interpretation. The standalone CLI
does not perform the requested file operations or consequential actions.

Offline check without an LLM call:

```bash
~/.local/bin/ume-harness --llm-output-file <path-to-json>
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
When an operation cannot be classified safely, the system returns it for confirmation.

## Install and connect Claude Code

### Install

```bash
git clone --branch v0.1.6 --depth 1 https://github.com/UMEBOSHIISAN/ume-harness.git
cd ume-harness
./scripts/install.sh
```

The default prefix is `~/.local`. If the command is not on `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

To update from v0.1.5 to v0.1.6, use the new source checkout to verify and
remove the old release before installing the new one. `--force` is not a
cross-version update path.

```bash
./scripts/uninstall.sh --version v0.1.5 --settings-path "${HOME}/.claude/settings.json" --yes
./scripts/install.sh
```

### Connect and disconnect Claude Code

Package installation does not modify existing Claude Code settings.
Connection is explicit:

```bash
ume-harness setup --yes
```

Disconnect:

```bash
ume-harness setup --disconnect
```

Setup/disconnect owns only exact matches for the three canonical hook commands
it generated. It does not touch other events, matchers, or hooks, and stops if
the settings cannot be parsed and revalidated safely.

### Diagnose and uninstall

```bash
python3 ~/.local/lib/ume-harness/v0.1.6/scripts/health_check.py
# or, from the repository
python3 ./scripts/health_check.py

./scripts/uninstall.sh --settings-path "${HOME}/.claude/settings.json" --yes
```

Use the same custom settings path and prefix for setup and removal.
Uninstall verifies owned hooks and payload, preserves unrelated Claude settings,
and keeps `~/.ume-harness/state`.

## Current limitations

- UME-HARNESS is not an OS sandbox; it assumes a trusted host entrypoint.
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
