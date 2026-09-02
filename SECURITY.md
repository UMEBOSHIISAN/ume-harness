# Security Policy

## Supported Versions

Only the latest generated public release mirror is supported. The `VERSION` file on the public `main` branch identifies
the current source release. Older versions do not receive security fixes unless the maintainers announce otherwise.

`ume-harness-engineering` is the sole canonical source. The public `ume-harness` repository is a one-way generated
release mirror and is not a supported source for direct edits or reverse synchronization.

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability. Use
[GitHub Private Vulnerability Reporting](https://github.com/UMEBOSHIISAN/ume-harness/security/advisories/new).

Include the affected version or commit, platform, reachable surface, security impact, and the smallest safe reproduction
you can provide. Do not submit access tokens, credentials, private paths, personal data, customer data, or unrelated
repository contents. Redact sensitive values and use synthetic fixtures where possible.

## System and Scope

UME-HARNESS provides deterministic local work governance for AI coding agents. This policy covers:

- the local Tool Policy, Authority Overlay, LocalExecutionLease, Lease state, and worktree/path/Tier gates;
- the Claude Code host adapter and its bounded `PreToolUse`, `PermissionRequest`, and `PostToolUseFailure` surfaces;
- install, byte verification, hook setup/disconnect, uninstall, explicit release closure, and release identity handling;
- strict local parsing and validation performed by the generated public release mirror.

Mothership owns consequential external Action Authority. UME-HARNESS does not own external execution, production
connectors, credentials, deployment authority, or cross-plane routing.

## Threat Model and Trust Boundaries

Task text, model-produced candidate actions, tool invocation payloads, paths, shell command text, repository contents,
and persisted Lease records can be malformed or attacker-influenced inputs. The gate must not silently broaden authority
from those inputs.

The local operating-system account, the installed host entrypoint, presentation-only imports loaded before gate
verification, and the owner-controlled state directory are trusted host prerequisites. Release provenance depends on the
canonical repository, explicit promotion closure, and generated release identity.

## Security Invariants

- Unknown or malformed side effects fail closed to `APPROVAL_REQUIRED` or `DENY`; they never become silent `ALLOW`.
- Recognized secret paths remain denied, including reads, and a Lease never grants secret or external-mutation
  capability. OS pseudo-file coverage is limited as documented below.
- An active Lease cannot authorize work outside its bound real worktree or inside protected `.ume-harness/**` control
  paths.
- Path traversal, ambiguous multi-worktree selection, unsupported shell composition, and unproven command/path scope do
  not bypass the host gate.
- Install and release verification accept only the explicit regular-file closure with the expected identity; symlinked
  closure components are rejected.
- Setup, disconnect, and uninstall modify or remove only exact UME-HARNESS-owned hook commands and fail closed when
  ownership or settings bytes cannot be proven.
- Local preparation, a Lease, test results, presentation output, or a successful local operation never becomes external
  Action Authority.

## Reportable Findings and Severity Context

Please report realistic, reproducible paths that violate an invariant, including:

- an in-scope tool invocation that reads secrets or escapes the active worktree without the required stop or denial;
- a write to `.ume-harness/**`, an unapproved destructive action, or an external mutation accepted as locally allowed;
- shell or path parsing that converts attacker-controlled input into broader execution or filesystem authority;
- altered, omitted, substituted, or symlinked release/install bytes accepted as the declared release identity;
- setup, disconnect, or uninstall overwriting or deleting user-owned settings, hooks, files, or directories;
- malformed persisted state being accepted as a valid Lease without the trusted-host compromise excluded below.

Severity depends on reachability and demonstrated impact. A practical secret read, arbitrary command execution, external
mutation, protected control-plane write, or trustworthy-release substitution is generally more severe than a denial of
service or excessive approval prompt with no authority expansion.

## Out of Scope and Accepted Risk

The following are outside the v0 security boundary by design:

- a malicious or already-compromised same-UID process replacing the trusted installed entrypoint or rewriting local
  state and recomputing public digests;
- root/administrator compromise, a malicious operating system, or physical compromise of the host;
- model quality, prompt quality, or omission of a hazardous operation from `candidate_actions` when no in-scope runtime
  gate bypass is demonstrated;
- features explicitly documented as not wired: observer-backed begin/complete enforcement, autonomous Stop hooks,
  test-profile-to-command mapping, and approval-token resume;
- Mothership, external executors, production connectors, customer/domain policy, and other independently owned systems.

These exclusions do not suppress a report that reaches an in-scope bypass without first requiring the excluded
compromise.

## Known Limitations and Compensating Controls

The Authority Overlay can classify only actions present in `candidate_actions`; semantic omission remains a known
residual risk. Actual Claude Code tool invocations are evaluated separately by the deterministic host gate.

`LeaseStateStore` contains expected-state and concurrent/out-of-band mutation primitives, but the current Claude adapter
does not call the observer-backed operation lifecycle. A stored `test_profile` does not map to an executable command
allowlist, and an unknown test command remains approval-required. Native Windows is unsupported; Linux/POSIX remains
expected but unverified for the current release evidence.

When a valid activation state exists, v0.1.4 attests the explicit protected-runtime closure before protected authority
modules execute. Without activation state, the legacy path does not enforce that closure attestation. The trusted host
entrypoint and presentation-only imports loaded before gate verification remain prerequisites; this is not universal
attestation of every ambient or imported module.

Secret-path classification is not complete for operating-system pseudo-files. `/proc/<pid>/environ` forms are denied,
but other `/proc` and `/dev/fd` descriptor paths are not guaranteed to be classified as secrets. Linux/POSIX remains
unverified.

Direct installation from an untrusted or modified checkout is not an independent provenance guarantee. Use a trusted
canonical or generated-release checkout; independent anchors are enforced by release-promotion and owned-install
verification gates.

## Response and Disclosure Process

Maintainers will acknowledge the report, reproduce it against the canonical source, assess reachability and impact,
and coordinate a fix and disclosure through the private advisory. Fixes are made in the canonical engineering
repository, verified through the release identity and test gates, and then promoted one way to the public mirror.

No response-time or fix-time SLA is promised. Please avoid public disclosure until a fix is available or a disclosure
date has been mutually agreed. The maintainers may request additional synthetic evidence and may publish an advisory or
CVE when appropriate.
