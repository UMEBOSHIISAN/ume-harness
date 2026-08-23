#!/usr/bin/env python3
"""Phase 1 tests for the provider-independent LocalExecutionLease core."""

from __future__ import annotations

import hashlib
import os
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))

from local_execution_lease import (  # noqa: E402
    CanonicalTaskReference,
    LeaseDerivationError,
    LeaseValidationError,
    PolicyReference,
    RuntimeContext,
    derive_lease,
    validate_lease,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _task(*capabilities: str, test_profile: str | None = None) -> CanonicalTaskReference:
    if "test" in capabilities and test_profile is None:
        test_profile = "python-tests-v1"
    return CanonicalTaskReference(
        task_id="task-123",
        task_contract_sha256=_sha256("frontdoor-task-123"),
        allowed_capabilities=frozenset(capabilities),
        test_profile=test_profile,
    )


def _policy(
    *capabilities: str,
    approved_test_profiles: frozenset[str] | None = None,
) -> PolicyReference:
    if approved_test_profiles is None:
        approved_test_profiles = frozenset({"python-tests-v1"})
    return PolicyReference(
        policy_id="site-policy-v0",
        policy_sha256=_sha256("site-policy-v0"),
        allowed_capabilities=frozenset(capabilities),
        approved_test_profiles=approved_test_profiles,
    )


def _context() -> RuntimeContext:
    return RuntimeContext(
        repository="UMEBOSHIISAN/ume-harness",
        worktree_realpath="/tmp/dummy-worktree/local-execution-lease-v0",
        branch="task/local-execution-lease-v0",
        starting_head="a" * 40,
        baseline_status_digest=_sha256("clean-status"),
        baseline_tree_digest=_sha256("tree-at-start"),
    )


class LocalExecutionLeaseTests(unittest.TestCase):
    def test_derive_lease_intersects_task_policy_and_v0_ceiling(self):
        lease = derive_lease(
            _task("edit", "test"),
            _policy("edit", "test", "commit"),
            _context(),
        )

        self.assertEqual(lease.capabilities, frozenset({"edit", "test"}))
        self.assertFalse(lease.external_mutations)
        self.assertEqual(lease.task_contract_sha256, _task("edit", "test").task_contract_sha256)


    def test_policy_intersection_does_not_grant_capability_not_allowed_by_policy(self):
        lease = derive_lease(_task("edit", "test"), _policy("edit"), _context())

        self.assertEqual(lease.capabilities, frozenset({"edit"}))


    def test_task_request_for_deferred_capability_fails_closed(self):
        with self.assertRaisesRegex(LeaseDerivationError, "commit"):
            derive_lease(_task("edit", "commit"), _policy("edit", "commit"), _context())


    def test_every_deferred_capability_fails_closed(self):
        for capability in ("delete", "stage", "commit", "network", "secret", "hook", "external_mutation"):
            with self.subTest(capability=capability):
                with self.assertRaisesRegex(LeaseDerivationError, capability):
                    derive_lease(_task("edit", capability), _policy("edit", capability), _context())


    def test_test_capability_is_bound_to_an_approved_profile(self):
        lease = derive_lease(_task("test"), _policy("test"), _context())

        self.assertEqual(lease.capabilities, frozenset({"test"}))
        self.assertEqual(lease.test_profile, "python-tests-v1")


    def test_unapproved_test_profile_fails_closed(self):
        task = _task("test", test_profile="shell-v1")

        with self.assertRaisesRegex(LeaseDerivationError, "test profile"):
            derive_lease(task, _policy("test"), _context())


    def test_same_inputs_produce_same_lease_identity(self):
        first = derive_lease(_task("edit", "test"), _policy("edit", "test"), _context())
        second = derive_lease(_task("edit", "test"), _policy("edit", "test"), _context())

        self.assertEqual(first, second)
        self.assertEqual(first.lease_id, second.lease_id)


    def test_validation_rejects_task_digest_mismatch(self):
        task = _task("edit")
        lease = derive_lease(task, _policy("edit"), _context())
        changed_task = replace(task, task_contract_sha256=_sha256("different-task"))

        with self.assertRaisesRegex(LeaseValidationError, "task contract digest"):
            validate_lease(lease, changed_task, _policy("edit"), _context())


    def test_validation_rejects_policy_digest_mismatch(self):
        task = _task("edit")
        policy = _policy("edit")
        lease = derive_lease(task, policy, _context())
        changed_policy = replace(policy, policy_sha256=_sha256("different-policy"))

        with self.assertRaisesRegex(LeaseValidationError, "site policy"):
            validate_lease(lease, task, changed_policy, _context())


    def test_validation_rejects_runtime_binding_mismatch(self):
        task = _task("edit")
        context = _context()
        lease = derive_lease(task, _policy("edit"), context)
        changed_context = replace(context, branch="task/other")

        with self.assertRaisesRegex(LeaseValidationError, "runtime context"):
            validate_lease(lease, task, _policy("edit"), changed_context)


    def test_validation_rejects_external_mutation_capability(self):
        task = _task("edit")
        policy = _policy("edit")
        context = _context()
        lease = derive_lease(task, policy, context)
        forged = replace(
            lease,
            capabilities=frozenset({"edit", "external_mutation"}),
            external_mutations=True,
        )

        with self.assertRaisesRegex(LeaseValidationError, "external mutation|capability"):
            validate_lease(forged, task, policy, context)


    def test_malformed_capabilities_fail_closed_without_raw_type_error(self):
        task = replace(_task("edit"), allowed_capabilities=[{"not": "hashable"}])

        with self.assertRaisesRegex(LeaseDerivationError, "capabilities"):
            derive_lease(task, _policy("edit"), _context())


    def test_invalid_digest_is_rejected_at_derivation_boundary(self):
        task = replace(_task("edit"), task_contract_sha256="not-a-digest")

        with self.assertRaisesRegex(LeaseDerivationError, "sha256"):
            derive_lease(task, _policy("edit"), _context())


if __name__ == "__main__":
    unittest.main(verbosity=2)
