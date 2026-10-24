# Security policy

ume-harness-engineering is the sole canonical source. Public ume-harness is a
one-way generated release mirror. This policy describes the unreleased thin
candidate; published versions retain the policy/behavior at their tags.

## Report privately

Use [GitHub Private Vulnerability Reporting](https://github.com/UMEBOSHIISAN/ume-harness/security/advisories/new).
Include affected commit, platform, reachable behavior, demonstrated impact and
minimal synthetic reproduction. Do not submit credentials/private/customer data.

## Current boundary

UME is a non-executing preview plus two presentation hooks. It does not enforce
native permissions, secret/path access, sandbox/worktrees or external authority.
Managed/Lease/PreToolUse/token/Stop execution code is retired. Do not use preview
candidate_actions or their labels as tool permission or as a complete risk list.

Report in-scope malformed-input processing, raw sensitive input leaking into
Japanese presentation, unexpected hook decisions/side effects, unproven package
bytes accepted as trusted identity, or setup/uninstall modifying foreign state.

Install/release verification checks an explicit regular-file closure and rejects
symlinked members. Setup/disconnect/uninstall use exact command ownership and
hold on unproven settings/ownership. Locks only coordinate cooperating writers;
a race window with arbitrary writers remains. Existing installs are not replaced.
Old connections must be disconnected before removing their prefix. User state is
preserved, not silently migrated/deleted.

Trusted local account, host/admin policy and trusted canonical/generated source
acquisition are prerequisites. Byte identity is not an independent signature or
a same-UID compromise boundary. Native hooks can treat truncated JSON as plain
text; presentation hooks are not fail-closed authorization controls. Admin-policy
hooks may remain active even in safe mode. Native keychain refresh is not controlled
by this package. Model semantic quality/omission, host sandbox behavior, other
systems and independently modified same-UID code are outside this package's scope.

Maintainers assess reproducible impact against canonical source and coordinate a
fix/disclosure privately. No response/fix SLA is promised. No push/publication or
security guarantee is implied by this development policy.
