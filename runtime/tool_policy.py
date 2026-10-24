#!/usr/bin/env python3
"""Pure side-effect/tier classification for the offline preview.

This module describes suggested human decisions for preview output.  It does
not inspect commands, persist approvals, execute work, or grant host
permission.
"""

from __future__ import annotations

from enum import Enum


class SideEffect(str, Enum):
    READ_ONLY = "READ_ONLY"
    BOUNDED_WRITE = "BOUNDED_WRITE"
    EXTERNAL_MUTATION = "EXTERNAL_MUTATION"
    DESTRUCTIVE = "DESTRUCTIVE"
    AUTHORITY_TOUCH = "AUTHORITY_TOUCH"
    UNKNOWN = "UNKNOWN"


class Tier(str, Enum):
    TIER_CONSTITUTION = "TIER_CONSTITUTION"
    TIER_SECRETS = "TIER_SECRETS"
    TIER_GOVERNANCE = "TIER_GOVERNANCE"
    TIER_RUNTIME_CODE = "TIER_RUNTIME_CODE"
    TIER_NORMAL = "TIER_NORMAL"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENY = "DENY"


# Tier x SideEffect is a preview classification table.  It is not a host
# permission decision and has no execution path.
_DECISION_TABLE: dict[Tier, dict[SideEffect, Decision]] = {
    Tier.TIER_NORMAL: {
        SideEffect.READ_ONLY: Decision.ALLOW,
        SideEffect.BOUNDED_WRITE: Decision.ALLOW,
        SideEffect.EXTERNAL_MUTATION: Decision.APPROVAL_REQUIRED,
        SideEffect.DESTRUCTIVE: Decision.APPROVAL_REQUIRED,
        SideEffect.AUTHORITY_TOUCH: Decision.APPROVAL_REQUIRED,
        SideEffect.UNKNOWN: Decision.APPROVAL_REQUIRED,
    },
    Tier.TIER_RUNTIME_CODE: {
        SideEffect.READ_ONLY: Decision.ALLOW,
        SideEffect.BOUNDED_WRITE: Decision.APPROVAL_REQUIRED,
        SideEffect.EXTERNAL_MUTATION: Decision.APPROVAL_REQUIRED,
        SideEffect.DESTRUCTIVE: Decision.APPROVAL_REQUIRED,
        SideEffect.AUTHORITY_TOUCH: Decision.APPROVAL_REQUIRED,
        SideEffect.UNKNOWN: Decision.APPROVAL_REQUIRED,
    },
    Tier.TIER_GOVERNANCE: {
        SideEffect.READ_ONLY: Decision.ALLOW,
        SideEffect.BOUNDED_WRITE: Decision.APPROVAL_REQUIRED,
        SideEffect.EXTERNAL_MUTATION: Decision.APPROVAL_REQUIRED,
        SideEffect.DESTRUCTIVE: Decision.APPROVAL_REQUIRED,
        SideEffect.AUTHORITY_TOUCH: Decision.APPROVAL_REQUIRED,
        SideEffect.UNKNOWN: Decision.APPROVAL_REQUIRED,
    },
    Tier.TIER_SECRETS: {
        SideEffect.READ_ONLY: Decision.DENY,
        SideEffect.BOUNDED_WRITE: Decision.DENY,
        SideEffect.EXTERNAL_MUTATION: Decision.DENY,
        SideEffect.DESTRUCTIVE: Decision.DENY,
        SideEffect.AUTHORITY_TOUCH: Decision.DENY,
        SideEffect.UNKNOWN: Decision.DENY,
    },
    Tier.TIER_CONSTITUTION: {
        SideEffect.READ_ONLY: Decision.ALLOW,
        SideEffect.BOUNDED_WRITE: Decision.DENY,
        SideEffect.EXTERNAL_MUTATION: Decision.DENY,
        SideEffect.DESTRUCTIVE: Decision.DENY,
        SideEffect.AUTHORITY_TOUCH: Decision.DENY,
        SideEffect.UNKNOWN: Decision.DENY,
    },
}


def decide(tier: Tier, side_effect: SideEffect) -> Decision:
    """Return the preview label for one tier/effect pair.

    Unknown inputs remain fail-closed as ``APPROVAL_REQUIRED``.  The result is
    descriptive preview data; the host owns all actual permission decisions.
    """
    row = _DECISION_TABLE.get(tier)
    if row is None:
        return Decision.APPROVAL_REQUIRED
    return row.get(side_effect, Decision.APPROVAL_REQUIRED)
