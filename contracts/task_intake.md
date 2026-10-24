# Task intake — decision-support preview

The preview organizes proposed work, clarification questions with material
impact, and suggested human decisions. It should not make a person choose
technical diagnostics already answerable from available context.

The current CLI ends after the report. It does not start a worker, enforce
host-wide question batching, issue authority, or monitor execution/lifecycle.
Internal debug fields keep their existing names for compatibility:

| Field | Meaning |
|---|---|
| work_type/classification_status | Interpretation category and resolution state |
| required_human_approvals | Suggested pre-execution human decisions, not grants |
| surfaced_unknowns | Material clarification questions |
| pruned_unknowns | Questions removed by deterministic impact processing |
| clarification_blocked | Invalid assessment structure; processing stopped |
| headline_state | Preview/clarification/processing state, not execution status |

Malformed input stops as a processing failure. A valid unresolved work type may
remain null. Model-proposed approvals never overrule deterministic action meaning.
