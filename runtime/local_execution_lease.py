#!/usr/bin/env python3
"""Pure Phase 1 core for the derived LocalExecutionLease capability.

This module owns Lease derivation and validation semantics for ume-harness's
bounded local task and execution-policy inputs. It does not own host enforcement,
filesystem inspection, lifecycle state, external governance evidence, or
consequential external authority; the latter belongs to Mothership.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass


LEASE_VERSION = "local-execution-lease.v0"
V0_CAPABILITY_CEILING = frozenset({"edit", "test"})
KNOWN_CAPABILITIES = frozenset(
    {
        "edit",
        "test",
        "delete",
        "stage",
        "commit",
        "network",
        "secret",
        "hook",
        "external_mutation",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class LeaseDerivationError(ValueError):
    """Raised when canonical inputs cannot produce a safe V0 Lease."""


class LeaseValidationError(ValueError):
    """Raised when a Lease no longer matches its canonical inputs."""


@dataclass(frozen=True)
class CanonicalTaskReference:
    """Reference to a validated bounded local task identity, not a replacement SSOT."""

    task_id: str
    task_contract_sha256: str
    allowed_capabilities: frozenset[str]
    test_profile: str | None = None


@dataclass(frozen=True)
class PolicyReference:
    """Reference to the site policy projection used for Lease derivation."""

    policy_id: str
    policy_sha256: str
    allowed_capabilities: frozenset[str]
    approved_test_profiles: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RuntimeContext:
    """Immutable execution-origin context supplied by the host/runtime boundary."""

    repository: str
    worktree_realpath: str
    branch: str
    starting_head: str
    baseline_status_digest: str
    baseline_tree_digest: str


@dataclass(frozen=True)
class LocalExecutionLease:
    """Derived V0 capability; it is neither task nor authority SSOT."""

    lease_id: str
    lease_version: str
    task_id: str
    task_contract_sha256: str
    policy_id: str
    policy_sha256: str
    repository: str
    worktree_realpath: str
    branch: str
    starting_head: str
    baseline_status_digest: str
    baseline_tree_digest: str
    capabilities: frozenset[str]
    test_profile: str | None
    external_mutations: bool


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise LeaseDerivationError(f"{name} must be a non-empty trimmed string")
    return value


def _require_sha256(name: str, value: object) -> str:
    value = _require_text(name, value)
    if not _SHA256_RE.fullmatch(value):
        raise LeaseDerivationError(f"{name} must be a lowercase sha256 digest")
    return value


def _require_git_sha(name: str, value: object) -> str:
    value = _require_text(name, value)
    if not _GIT_SHA1_RE.fullmatch(value):
        raise LeaseDerivationError(f"{name} must be a full lowercase git SHA")
    return value


def _normalise_capabilities(name: str, value: object) -> frozenset[str]:
    if not isinstance(value, (set, frozenset, tuple, list)):
        raise LeaseDerivationError(f"{name} must be a collection of capability names")
    try:
        capabilities = frozenset(value)
    except (TypeError, ValueError) as exc:
        raise LeaseDerivationError(f"{name} contains an invalid capability name") from exc
    if any(not isinstance(capability, str) or not capability for capability in capabilities):
        raise LeaseDerivationError(f"{name} contains an invalid capability name")
    unknown = capabilities - KNOWN_CAPABILITIES
    if unknown:
        raise LeaseDerivationError(f"unknown capability: {sorted(unknown)[0]}")
    return capabilities


def _normalise_profiles(name: str, value: object) -> frozenset[str]:
    if not isinstance(value, (set, frozenset, tuple, list)):
        raise LeaseDerivationError(f"{name} must be a collection of profile names")
    try:
        profiles = frozenset(value)
    except (TypeError, ValueError) as exc:
        raise LeaseDerivationError(f"{name} contains an invalid profile name") from exc
    if any(not isinstance(profile, str) or not _PROFILE_RE.fullmatch(profile) for profile in profiles):
        raise LeaseDerivationError(f"{name} contains an invalid profile name")
    return profiles


def _normalise_optional_profile(name: str, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _PROFILE_RE.fullmatch(value):
        raise LeaseDerivationError(f"{name} must be a valid profile name")
    return value


def _validate_inputs(
    task: CanonicalTaskReference,
    policy: PolicyReference,
    context: RuntimeContext,
) -> tuple[frozenset[str], frozenset[str]]:
    if not isinstance(task, CanonicalTaskReference):
        raise LeaseDerivationError("task must be a CanonicalTaskReference")
    if not isinstance(policy, PolicyReference):
        raise LeaseDerivationError("policy must be a PolicyReference")
    if not isinstance(context, RuntimeContext):
        raise LeaseDerivationError("context must be a RuntimeContext")

    _require_text("task_id", task.task_id)
    _require_sha256("task_contract_sha256", task.task_contract_sha256)
    task_capabilities = _normalise_capabilities("task capabilities", task.allowed_capabilities)
    task_test_profile = _normalise_optional_profile("task test profile", task.test_profile)
    deferred = task_capabilities - V0_CAPABILITY_CEILING
    if deferred:
        raise LeaseDerivationError(f"capability denied by V0 ceiling: {sorted(deferred)[0]}")

    _require_text("policy_id", policy.policy_id)
    _require_sha256("policy_sha256", policy.policy_sha256)
    policy_capabilities = _normalise_capabilities(
        "policy capabilities", policy.allowed_capabilities
    )
    approved_test_profiles = _normalise_profiles(
        "approved test profiles", policy.approved_test_profiles
    )
    if "test" in task_capabilities:
        if task_test_profile is None:
            raise LeaseDerivationError("test capability requires a test profile")
        if task_test_profile not in approved_test_profiles:
            raise LeaseDerivationError("test profile is not approved by policy")
    elif task_test_profile is not None:
        raise LeaseDerivationError("test profile requires the test capability")

    _require_text("repository", context.repository)
    worktree = _require_text("worktree_realpath", context.worktree_realpath)
    if not os.path.isabs(worktree) or os.path.normpath(worktree) != worktree:
        raise LeaseDerivationError("worktree_realpath must be an absolute normalized path")
    if any(part == ".." for part in worktree.split(os.sep)):
        raise LeaseDerivationError("worktree_realpath must not contain path traversal")
    _require_text("branch", context.branch)
    _require_git_sha("starting_head", context.starting_head)
    _require_sha256("baseline_status_digest", context.baseline_status_digest)
    _require_sha256("baseline_tree_digest", context.baseline_tree_digest)
    return task_capabilities, policy_capabilities


def _lease_payload(
    task: CanonicalTaskReference,
    policy: PolicyReference,
    context: RuntimeContext,
    capabilities: frozenset[str],
    test_profile: str | None,
) -> dict[str, object]:
    return {
        "lease_version": LEASE_VERSION,
        "task_id": task.task_id,
        "task_contract_sha256": task.task_contract_sha256,
        "policy_id": policy.policy_id,
        "policy_sha256": policy.policy_sha256,
        "repository": context.repository,
        "worktree_realpath": context.worktree_realpath,
        "branch": context.branch,
        "starting_head": context.starting_head,
        "baseline_status_digest": context.baseline_status_digest,
        "baseline_tree_digest": context.baseline_tree_digest,
        "capabilities": sorted(capabilities),
        "test_profile": test_profile,
        "external_mutations": False,
    }


def _lease_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_lease_identity(lease: LocalExecutionLease) -> str:
    """Recompute the immutable Lease identity from every identity-bound field."""
    if not isinstance(lease, LocalExecutionLease):
        raise LeaseValidationError("lease has an invalid type")
    return _lease_id(
        {
            "lease_version": lease.lease_version,
            "task_id": lease.task_id,
            "task_contract_sha256": lease.task_contract_sha256,
            "policy_id": lease.policy_id,
            "policy_sha256": lease.policy_sha256,
            "repository": lease.repository,
            "worktree_realpath": lease.worktree_realpath,
            "branch": lease.branch,
            "starting_head": lease.starting_head,
            "baseline_status_digest": lease.baseline_status_digest,
            "baseline_tree_digest": lease.baseline_tree_digest,
            "capabilities": sorted(lease.capabilities),
            "test_profile": lease.test_profile,
            "external_mutations": lease.external_mutations,
        }
    )


def derive_lease(
    task: CanonicalTaskReference,
    policy: PolicyReference,
    context: RuntimeContext,
) -> LocalExecutionLease:
    """Derive the deterministic intersection of task, policy, and V0 ceiling."""

    task_capabilities, policy_capabilities = _validate_inputs(task, policy, context)
    capabilities = task_capabilities & policy_capabilities & V0_CAPABILITY_CEILING
    test_profile = task.test_profile if "test" in capabilities else None
    payload = _lease_payload(task, policy, context, capabilities, test_profile)
    return LocalExecutionLease(
        lease_id=_lease_id(payload),
        lease_version=LEASE_VERSION,
        task_id=task.task_id,
        task_contract_sha256=task.task_contract_sha256,
        policy_id=policy.policy_id,
        policy_sha256=policy.policy_sha256,
        repository=context.repository,
        worktree_realpath=context.worktree_realpath,
        branch=context.branch,
        starting_head=context.starting_head,
        baseline_status_digest=context.baseline_status_digest,
        baseline_tree_digest=context.baseline_tree_digest,
        capabilities=capabilities,
        test_profile=test_profile,
        external_mutations=False,
    )


def validate_lease(
    lease: LocalExecutionLease,
    task: CanonicalTaskReference,
    policy: PolicyReference,
    context: RuntimeContext,
) -> bool:
    """Validate that a Lease remains exactly bound to its canonical inputs."""

    if not isinstance(lease, LocalExecutionLease):
        raise LeaseValidationError("lease has an invalid type")
    try:
        _validate_inputs(task, policy, context)
    except LeaseDerivationError as exc:
        raise LeaseValidationError(str(exc)) from exc

    if lease.task_id != task.task_id or lease.task_contract_sha256 != task.task_contract_sha256:
        raise LeaseValidationError("task contract digest or identity mismatch")
    if lease.policy_id != policy.policy_id or lease.policy_sha256 != policy.policy_sha256:
        raise LeaseValidationError("site policy digest or identity mismatch")
    if any(
        (
            lease.repository != context.repository,
            lease.worktree_realpath != context.worktree_realpath,
            lease.branch != context.branch,
            lease.starting_head != context.starting_head,
            lease.baseline_status_digest != context.baseline_status_digest,
            lease.baseline_tree_digest != context.baseline_tree_digest,
        )
    ):
        raise LeaseValidationError("runtime context binding mismatch")
    if lease.external_mutations is not False:
        raise LeaseValidationError("external mutation capability is forbidden")

    try:
        expected = derive_lease(task, policy, context)
    except LeaseDerivationError as exc:
        raise LeaseValidationError(str(exc)) from exc
    if lease.capabilities != expected.capabilities:
        raise LeaseValidationError("capability intersection mismatch")
    if lease.test_profile != expected.test_profile:
        raise LeaseValidationError("test profile binding mismatch")
    if lease.lease_id != expected.lease_id or lease.lease_version != LEASE_VERSION:
        raise LeaseValidationError("lease identity mismatch")
    return True


__all__ = [
    "CanonicalTaskReference",
    "LEASE_VERSION",
    "KNOWN_CAPABILITIES",
    "LeaseDerivationError",
    "LeaseValidationError",
    "LocalExecutionLease",
    "PolicyReference",
    "RuntimeContext",
    "V0_CAPABILITY_CEILING",
    "compute_lease_identity",
    "derive_lease",
    "validate_lease",
]
