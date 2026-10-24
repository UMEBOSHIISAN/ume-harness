# Support Matrix — unreleased thin candidate

Published v0.1.7/old v0.1.6 behavior belongs to its own tag. The development
candidate removes custom execution enforcement; baseline evidence is separate.

| Surface | Candidate contract | Boundary |
|---|---|---|
| Japanese preview | Non-executing report, clarification-impact and compound-action meaning | Deterministic regressions; general interpretation quality/usability unknown |
| Online model transport | Native safe mode, empty tools/MCP, strict JSON consumer | f999 equivalent init observed empty tools/MCP; no normal-host inventory claim |
| Two presentation hooks | PermissionRequest/PostToolUseFailure, redacted Japanese, no permission decision/notification | Subprocess safety and isolated live PostToolUseFailure; interactive dialog unverified |
| Setup/disconnect | Two hooks; same-root retired hook hold/disconnect; foreign entries preserved | Ownership/concurrency tests; inventory is not live recognition |
| Install/identity | Explicit closure, actual wrapper, byte identity, no overwrite even with force | Isolated lifecycle; no signature authentication |
| Managed/Lease/PreToolUse/token/Stop | Retired | Host-native permissions, sandbox/worktrees/lifecycle apply |
| Notifications | Host-native only | No notifier subprocess or OSC/title fallback |
| Offline Mothership handoff | Explicit advisory JSON; separate Mothership owner performs exact review and retains evidence | No automatic bridge or authority from UME; installed E2E before the later Mothership input-read fix only |

## f999276 physical baseline — 2026-10-23

Source f9992760f005bd934099c0e4b6efe93ff15f75d4, tree
0ca46e7a48ba9f88a3ad1a53513df69129768827, install-byte digest
e0cad3889c9a4221dd427aeb7be5f55f99af1a65113113d4e9c4328de1d34398.
macOS arm64; Claude Code2.1.309; resolved model claude-sonnet-5-5.

- Exact installed preview completed a synthetic request without executing file work.
- Observable native equivalent: tools=[], MCP=[], skills=[], two builtin plugins.
  Output/budget/turn/debug instrumentation differed; not the exact CLI's own init.
- Synthetic onFailure:block/timeout10: missing command, timeout, invalid JSON object
  and invalid schema blocked Write; markers absent. Truncated output without its
  final brace passed as native plain text and created its marker.
- Initial installed managed E2E had an invalid protected-root fixture. Human
  authorized one correction: retry1 Read/Write succeeded, protected-root Write
  was denied, missing-file Read failed, Japanese failure notice was observed.
- One process/session reloaded native project settings: A, ConfigChange, B with
  two successful Reads. Synthetic observer hooks, not UME-specific reload proof.
- Normal settings.json was unchanged. Initial advisory changed .claude.json
  feature-cache keys. Later probes used macOS sandbox-exec write denial over
  real .claude/.claude.json. Whole-task zero-state-write is not claimed; native
  keychain refresh unmeasured.

Raw artifacts and independent review are retained in the assigned local task
record, outside public release. Old managed E2E does not verify a retired feature
in this changed candidate. Native command hooks accept some malformed output as
plain text: onFailure:block does not block every invalid output. Current UME
hooks are presentation-only and must not enforce authority.

## Thin candidate physical observations — 2026-10-23

A separate temporary prefix installed 28 files and passed byte identity, wrapper
and import diagnostics. Its exact online CLI returned PREVIEW_COMPLETE on one
synthetic request; the workspace still contained only the input README.

In one running native session, the first synthetic Read succeeded. The installed
thin CLI then added its two presentation hooks to an explicit synthetic project
settings file, preserving the observer hooks. ConfigChange was observed, followed
by a missing-file Read and the installed Japanese PostToolUseFailure system
notice in that same session. Both turns completed successfully; no API retry
event occurred. This establishes UME-specific reload for this bounded case.
Subsequent health-interface and setup-preview wording fixes did not change the
online interpretation or hook bytes; final byte diagnostics cover those fixes.
Normal settings.json remained byte-identical. A later .claude.json cache-time
change was also observed; attribution to the probe or concurrent host processes
was not established. Invoking the write-denial profile is not proof that all
host state remained unchanged.

## Remaining unknowns

- Interactive PermissionRequest/dialog/readability/approval flow.
- Positive MCP execution, admin-policy combinations, other reload scenarios and
  normal personal-configuration interaction.
- General semantic quality/beginner usability and comparison with native
  language/output styles/plan mode.
- Linux/POSIX runtime, Windows/WSL, other host versions. Windows native unsupported.
- Native JSON Schema under the measured zero-tool contract: one-turn probe exposed
  StructuredOutput and ended at the cap without final structured output. This
  does not establish that the native feature cannot work.

```bash
python3 -m pytest -q -p no:cacheprovider tests ux/japanese-human-layer/tests
```

Static/manifest/old semantic fixtures are not physical acceptance.
Official [hooks](https://code.claude.com/docs/en/hooks),
[CLI](https://code.claude.com/docs/en/cli-reference),
[settings](https://code.claude.com/docs/en/settings).
