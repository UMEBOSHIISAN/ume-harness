#!/usr/bin/env python3
"""Provider-independent Phase 3A generic gate evaluation for LocalExecutionLease.

This module owns the generic, host-independent 3-value decision evaluation
(ALLOW / DENY / NOT_APPLICABLE) for bounded execution requests.

Invariants:
- Does NOT own task semantics (Frontdoor) or authority SSOT (Mothership).
- Does NOT hardcode site policies or protected zones (consumed via policy evaluator).
- Prevents managed-domain fallback leaks (managed domain + no lease => DENY).
- Caller cannot supply or override worktree identity (derived via domain resolver).
- Strict action domain: unsupported/malformed actions fail closed with DENY.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass
from typing import Callable

from local_execution_lease import LocalExecutionLease, PolicyReference
from local_execution_lease_state import (
    LeaseLifecycle,
    LeaseStateCorruptError,
    LeaseStateError,
    LeaseStateStore,
    _canonical_digest,
)


class GateAction(str, enum.Enum):
    EDIT = "edit"
    WRITE = "write"


class GateDecision(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class GateEvaluationResult:
    decision: GateDecision
    reason: str
    lease_id: str | None = None
    violation_code: str | None = None


@dataclass(frozen=True)
class ManagedExecutionDomain:
    """Local runtime fact describing a worktree bound to Lease management."""

    repository: str
    worktree_realpath: str
    management_mode: str
    policy_id: str
    policy_sha256: str


def _normalize_target_path(path: str) -> tuple[str, str] | None:
    """Returns (normalized_abs_path, canonical_realpath) or None if invalid."""
    if not isinstance(path, str) or not path.strip():
        return None
    abs_path = os.path.abspath(path.strip())
    real_path = os.path.realpath(abs_path)
    return abs_path, real_path


def _is_path_inside(child_path: str, parent_dir: str) -> bool:
    """Determines whether child_path is within parent_dir (both canonicalized)."""
    try:
        rel = os.path.relpath(child_path, parent_dir)
        return rel == "." or (not rel.startswith("..") and not os.path.isabs(rel))
    except (ValueError, Exception):
        return False


class LocalExecutionGate:
    """Host-independent gate evaluation engine."""

    def __init__(
        self,
        state_store: LeaseStateStore,
        domain_resolver: Callable[[str], ManagedExecutionDomain | None],
        policy_evaluator: Callable[[PolicyReference, str, GateAction], bool],
    ) -> None:
        if not isinstance(state_store, LeaseStateStore):
            raise TypeError("state_store must be a LeaseStateStore instance")
        if not callable(domain_resolver):
            raise TypeError("domain_resolver must be callable")
        if not callable(policy_evaluator):
            raise TypeError("policy_evaluator must be callable")
        self._state_store = state_store
        self._domain_resolver = domain_resolver
        self._policy_evaluator = policy_evaluator

    def evaluate_request(
        self,
        target_path: str,
        action: GateAction | str,
    ) -> GateEvaluationResult:
        """Evaluates an execution request against Lease and Site Policy."""
        # 1. Strict action domain validation
        normalized_action: GateAction
        if isinstance(action, GateAction):
            normalized_action = action
        elif isinstance(action, str):
            try:
                normalized_action = GateAction(action)
            except ValueError:
                return GateEvaluationResult(
                    decision=GateDecision.DENY,
                    reason=f"unsupported or malformed action: {action!r}",
                    violation_code="INVALID_ACTION",
                )
        else:
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason="action has an invalid type",
                violation_code="INVALID_ACTION",
            )

        # 2. Target path validation
        paths = _normalize_target_path(target_path)
        if paths is None:
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason="target_path must be a non-empty string",
                violation_code="INVALID_TARGET_PATH",
            )
        abs_path, real_path = paths

        # 3. Domain resolution
        try:
            domain = self._domain_resolver(real_path)
            if domain is None and real_path != abs_path:
                domain = self._domain_resolver(abs_path)
        except Exception as exc:
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason=f"domain resolver failed: {exc}",
                violation_code="DOMAIN_RESOLVER_ERROR",
            )

        if domain is None:
            return GateEvaluationResult(
                decision=GateDecision.NOT_APPLICABLE,
                reason="target path is outside lease-managed domain",
            )

        if not isinstance(domain, ManagedExecutionDomain) or domain.management_mode != "lease":
            return GateEvaluationResult(
                decision=GateDecision.NOT_APPLICABLE,
                reason="execution domain is not under lease management",
            )

        # 4. Worktree boundary / escape check
        worktree_realpath = os.path.realpath(domain.worktree_realpath)
        if not _is_path_inside(real_path, worktree_realpath):
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason="target path escapes worktree boundary",
                violation_code="WORKTREE_ESCAPE",
            )

        # 5. Control-plane protection: <worktree>/.ume-harness/** is structurally non-writable
        control_plane_dir = os.path.realpath(os.path.join(worktree_realpath, ".ume-harness"))
        if real_path == control_plane_dir or _is_path_inside(real_path, control_plane_dir):
            if action in (GateAction.EDIT, GateAction.WRITE):
                return GateEvaluationResult(
                    decision=GateDecision.DENY,
                    reason="target path is within protected control plane (.ume-harness)",
                    violation_code="PROTECTED_ZONE_VIOLATION",
                )

        # 5. Lease lookup & validation in state store
        worktree_key = _canonical_digest(
            {
                "repository": domain.repository,
                "worktree_realpath": domain.worktree_realpath,
            }
        )

        try:
            with self._state_store._locked_document() as document:
                now = self._state_store._now()
                self._state_store._expire_due(document, now)
                active_state = None
                for raw_state in document.get("leases", []):
                    if raw_state.get("worktree_key") == worktree_key:
                        if raw_state.get("lifecycle") == LeaseLifecycle.ACTIVE.value:
                            active_state = raw_state
                            break
        except (LeaseStateCorruptError, LeaseStateError) as exc:
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason=f"lease state store error: {exc}",
                violation_code="STATE_STORE_ERROR",
            )
        except Exception as exc:
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason=f"unexpected state error: {exc}",
                violation_code="STATE_STORE_ERROR",
            )

        if active_state is None:
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason="no valid active lease found for managed domain",
                violation_code="NO_ACTIVE_LEASE",
            )

        lease_id = active_state.get("lease_id")

        if (
            active_state.get("policy_id") != domain.policy_id
            or active_state.get("policy_sha256") != domain.policy_sha256
        ):
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason="lease policy binding does not match managed domain",
                lease_id=lease_id,
                violation_code="POLICY_BINDING_MISMATCH",
            )

        if (
            active_state.get("repository") != domain.repository
            or active_state.get("worktree_realpath") != domain.worktree_realpath
        ):
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason="lease context binding does not match managed domain",
                lease_id=lease_id,
                violation_code="CONTEXT_BINDING_MISMATCH",
            )

        # 6. Site Policy evaluation (delegated to policy_evaluator)
        policy_ref = PolicyReference(
            policy_id=domain.policy_id,
            policy_sha256=domain.policy_sha256,
            allowed_capabilities=frozenset({"edit", "test"}),
        )

        try:
            is_permitted = self._policy_evaluator(policy_ref, real_path, normalized_action)
        except Exception as exc:
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason=f"site policy evaluation failed: {exc}",
                lease_id=lease_id,
                violation_code="POLICY_EVALUATION_ERROR",
            )

        if not is_permitted:
            return GateEvaluationResult(
                decision=GateDecision.DENY,
                reason="action denied by site policy",
                lease_id=lease_id,
                violation_code="SITE_POLICY_DENIED",
            )

        return GateEvaluationResult(
            decision=GateDecision.ALLOW,
            reason="operation permitted under active lease",
            lease_id=lease_id,
        )


def create_default_gate(
    state_path: str | os.PathLike[str] | None = None,
    domain_resolver: Callable[[str], ManagedExecutionDomain | None] | None = None,
    policy_evaluator: Callable[[PolicyReference, str, GateAction], bool] | None = None,
) -> LocalExecutionGate:
    """Helper to instantiate LocalExecutionGate with optional overrides."""
    store = LeaseStateStore(state_path=state_path)
    resolver = domain_resolver or (lambda _: None)
    evaluator = policy_evaluator or (lambda _policy, _path, _action: True)
    return LocalExecutionGate(
        state_store=store,
        domain_resolver=resolver,
        policy_evaluator=evaluator,
    )


__all__ = [
    "GateAction",
    "GateDecision",
    "GateEvaluationResult",
    "LocalExecutionGate",
    "ManagedExecutionDomain",
    "create_default_gate",
]
