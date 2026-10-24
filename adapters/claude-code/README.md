# Claude Code presentation adapter — unreleased thin candidate

The active adapter registers only PermissionRequest and PostToolUseFailure.
It returns bounded Japanese systemMessage/failure context, never native permission
decisions, authority tokens, answers, execution or resume. Raw arguments, paths,
queries and error bodies are omitted. Use native language/output styles for
response localization and native notifications for attention signals.

The former PreToolUse/Lease runner is retired. setup --managed returns nonzero
before any host call/settings mutation. Normal setup holds on an exact same-root
legacy PreToolUse command, even if that script is missing. Explicit disconnect
can remove the exact old registration; foreign/other-prefix hooks remain untouched.
Keep old prefixes and trusted source until disconnect. There is no auto-migration.

New presentation entries use native 3-second timeouts; existing metadata/timeouts
remain unchanged. Setup/disconnect use exact command ownership, a stable settings
lock and pre/post-save verification. No retry/merge/rollback. Inventory is only
file state; other settings/native policy/hooks may still apply.

See root README for separate-prefix install, explicit migration and diagnostics.
Package install does not connect hooks. Manual settings.json.fragment contains
only the same two presentation hooks. Explanation failure must not add a denial.
Native stdout treats truncated objects lacking a closing brace as plain text;
these hooks must not serve as an authorization gate.

f999276 synthetic real-host evidence was collected on macOS arm64 / Claude2.1.309;
its managed enforcement is historical and no longer a candidate feature.
Interactive PermissionRequest UI/readability and general host/platform behavior
remain unverified. Source tests/direct hook calls do not prove that UI.
