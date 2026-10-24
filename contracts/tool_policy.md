# Preview side-effect meaning

runtime/tool_policy.py contains pure enums and a lookup used by the non-executing
Human Layer. It is not a host gate or a shell-command classifier.

For the CLI's TIER_NORMAL preview: READ_ONLY/BOUNDED_WRITE are provisional work
candidates; EXTERNAL_MUTATION/DESTRUCTIVE/AUTHORITY_TOUCH/UNKNOWN need human
judgment before execution. The compatibility Tier table remains pure metadata;
it cannot grant or deny a real tool. Unknown table keys conservatively require
judgment. Candidate provenance survives compound-action splitting.

required_human_approvals is a list of suggested decisions, never a token or
permission receipt. Persistent approval/token storage and shell execution
classification were retired. Actual native permissions and human authority are
checked by the host, independently of these labels.
