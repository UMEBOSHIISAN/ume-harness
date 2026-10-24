# Authority boundary — thin development candidate

UME produces a proposal and presentation only. It does not issue or consume
permission, approval tokens, leases or external authority. Host permissions,
project rules and actual human authorization apply independently to each action.

Model candidate actions and their ALLOW/APPROVAL_REQUIRED/DENY labels are
provisional preview metadata. ALLOW means no additional preview question under
the selected pure table; it never means a tool has permission. A missing action
cannot be classified, so the preview is not a completeness/security guarantee.

The host owns sandboxing, worktrees, questions, approvals, sessions and lifecycle.
The two presentation hooks never return permissionDecision/updatedPermissions,
automatically answer questions or resume a rejected operation. Mothership and
external executors are separate systems; there is no runtime bridge here.

The former managed/Lease/Stop/token execution plane is retired. Existing old
connections require explicit disconnect with retained matching source/CLI;
installation does not migrate settings or delete user state.
