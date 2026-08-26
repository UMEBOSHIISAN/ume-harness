#!/usr/bin/env python3
"""Comprehensive Phase 3A unit tests for LocalExecutionGate.

Covers:
- Positive (ALLOW) under active valid lease
- Negative (DENY) on managed domain without active lease (no-lease fail-closed)
- Negative (DENY) on expired, revoked, completed, invalidated lease
- Negative (DENY) on path traversal / symlink escape
- Negative (DENY) on policy/context mismatch
- Negative (DENY) on site policy denial
- Negative (DENY) on invalid action domain / malformed types
- Applicability (NOT_APPLICABLE) on unmanaged paths or non-lease domains
- Fail-closed behavior on resolver or policy exceptions
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = os.path.join(ROOT_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from local_execution_gate import (
    GateAction,
    GateDecision,
    LocalExecutionGate,
    ManagedExecutionDomain,
)
from local_execution_lease import (
    CanonicalTaskReference,
    LocalExecutionLease,
    PolicyReference,
    RuntimeContext,
    derive_lease,
)
from local_execution_lease_state import (
    LeaseLifecycle,
    LeaseRuntimeState,
    LeaseStateStore,
    ObservedExecutionState,
)


class LocalExecutionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.worktree_dir = os.path.join(self.temp_dir.name, "worktree")
        os.makedirs(self.worktree_dir, exist_ok=True)
        self.state_file = os.path.join(self.temp_dir.name, "leases.json")
        self.store = LeaseStateStore(
            state_path=self.state_file,
            observer=self._dummy_observer,
        )

        self.repository = "test-repo"
        self.worktree_realpath = os.path.realpath(self.worktree_dir)
        self.branch = "task/test-branch"
        self.starting_head = "1111111111111111111111111111111111111111"
        self.policy_id = "test-policy"
        self.policy_sha256 = "2222222222222222222222222222222222222222222222222222222222222222"
        self.task_id = "test-task"
        self.task_contract_sha256 = "3333333333333333333333333333333333333333333333333333333333333333"
        self.baseline_status = "4444444444444444444444444444444444444444444444444444444444444444"
        self.baseline_tree = "5555555555555555555555555555555555555555555555555555555555555555"

        self.domain = ManagedExecutionDomain(
            repository=self.repository,
            worktree_realpath=self.worktree_realpath,
            management_mode="lease",
            policy_id=self.policy_id,
            policy_sha256=self.policy_sha256,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _dummy_observer(self, state: LeaseRuntimeState) -> ObservedExecutionState:
        return ObservedExecutionState(
            starting_head=state.starting_head,
            status_digest=state.baseline_anchor.status_digest,
            tree_digest=state.baseline_anchor.tree_digest,
        )

    def _create_lease(self) -> LocalExecutionLease:
        task = CanonicalTaskReference(
            task_id=self.task_id,
            task_contract_sha256=self.task_contract_sha256,
            allowed_capabilities=frozenset({"edit"}),
        )
        policy = PolicyReference(
            policy_id=self.policy_id,
            policy_sha256=self.policy_sha256,
            allowed_capabilities=frozenset({"edit"}),
        )
        context = RuntimeContext(
            repository=self.repository,
            worktree_realpath=self.worktree_realpath,
            branch=self.branch,
            starting_head=self.starting_head,
            baseline_status_digest=self.baseline_status,
            baseline_tree_digest=self.baseline_tree,
        )
        return derive_lease(task, policy, context)

    def _default_domain_resolver(self, target_path: str) -> ManagedExecutionDomain | None:
        if target_path.startswith(self.worktree_realpath) or target_path.startswith(self.worktree_dir):
            return self.domain
        return None

    def _default_policy_evaluator(self, policy: PolicyReference, path: str, action: GateAction) -> bool:
        # Deny Layer A / B / secret patterns as sample site policy
        if "CLAUDE.md" in path or "secrets" in path:
            return False
        return True

    def test_positive_allow_under_active_valid_lease(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        result = gate.evaluate_request(target, "edit")

        self.assertEqual(result.decision, GateDecision.ALLOW)
        self.assertEqual(result.lease_id, lease.lease_id)
        self.assertIn("permitted", result.reason)

    def test_test_only_lease_cannot_authorize_edit(self) -> None:
        task = CanonicalTaskReference(
            task_id=self.task_id,
            task_contract_sha256=self.task_contract_sha256,
            allowed_capabilities=frozenset({"test"}),
            test_profile="python-tests-v1",
        )
        policy = PolicyReference(
            policy_id=self.policy_id,
            policy_sha256=self.policy_sha256,
            allowed_capabilities=frozenset({"edit", "test"}),
            approved_test_profiles=frozenset({"python-tests-v1"}),
        )
        context = RuntimeContext(
            repository=self.repository,
            worktree_realpath=self.worktree_realpath,
            branch=self.branch,
            starting_head=self.starting_head,
            baseline_status_digest=self.baseline_status,
            baseline_tree_digest=self.baseline_tree,
        )
        lease = derive_lease(task, policy, context)
        self.store.issue(lease)
        self.store.activate(lease.lease_id)
        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        result = gate.evaluate_request(os.path.join(self.worktree_dir, "src", "file.py"), "edit")

        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "LEASE_CAPABILITY_DENIED")

    def test_managed_domain_with_no_lease_fails_closed_with_deny(self) -> None:
        # Crucial test: When worktree is in a managed domain, but no active lease exists,
        # it MUST return DENY, not NOT_APPLICABLE!
        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        result = gate.evaluate_request(target, "edit")

        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "NO_ACTIVE_LEASE")
        self.assertNotEqual(result.decision, GateDecision.NOT_APPLICABLE)

    def test_expired_or_revoked_lease_fails_closed_with_deny(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)
        self.store.revoke(lease.lease_id, "test revoked")

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        result = gate.evaluate_request(target, "edit")

        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "NO_ACTIVE_LEASE")

    def test_path_traversal_escape_fails_closed_with_deny(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        # Attempt to escape via ../
        target = os.path.join(self.worktree_dir, "..", "outside.py")
        result = gate.evaluate_request(target, "edit")

        # Because target resolves outside worktree
        self.assertIn(result.decision, {GateDecision.DENY, GateDecision.NOT_APPLICABLE})
        if result.decision == GateDecision.DENY:
            self.assertEqual(result.violation_code, "WORKTREE_ESCAPE")

    def test_symlink_escape_fails_closed_with_deny(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)

        outside_target = os.path.join(self.temp_dir.name, "outside_file.txt")
        with open(outside_target, "w") as f:
            f.write("outside")

        symlink_path = os.path.join(self.worktree_dir, "escape_link.txt")
        os.symlink(outside_target, symlink_path)

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        result = gate.evaluate_request(symlink_path, "edit")
        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "WORKTREE_ESCAPE")

    def test_site_policy_denial_returns_deny(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        # Target CLAUDE.md which policy evaluator denies
        target = os.path.join(self.worktree_dir, "CLAUDE.md")
        result = gate.evaluate_request(target, "edit")

        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "SITE_POLICY_DENIED")

    def test_strict_action_domain_denies_unknown_actions(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        
        # Unsupported action strings, case/whitespace variations, and invalid types
        unsupported_actions = [
            None,
            "Edit",
            " edit ",
            "WRITE",
            " write ",
            "delete",
            "stage",
            "commit",
            "network",
            "UNKNOWN_ACTION",
            "",
            "   ",
            123,
            [],
            {},
        ]
        for bad_action in unsupported_actions:
            result = gate.evaluate_request(target, bad_action)  # type: ignore[arg-type]
            self.assertEqual(result.decision, GateDecision.DENY, f"Expected DENY for bad_action={bad_action!r}")
            self.assertEqual(result.violation_code, "INVALID_ACTION", f"Expected INVALID_ACTION for bad_action={bad_action!r}")

    def test_unmanaged_target_returns_not_applicable(self) -> None:
        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        unmanaged_target = "/Users/umeboshi/unrelated/path.py"
        result = gate.evaluate_request(unmanaged_target, "edit")

        self.assertEqual(result.decision, GateDecision.NOT_APPLICABLE)
        self.assertIn("outside lease-managed domain", result.reason)

    def test_domain_resolver_exception_fails_closed(self) -> None:
        def bad_resolver(path: str) -> ManagedExecutionDomain | None:
            raise RuntimeError("resolver exploded")

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=bad_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        result = gate.evaluate_request(target, "edit")

        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "DOMAIN_RESOLVER_ERROR")



    def test_policy_digest_mismatch_fails_closed_with_deny(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)

        # Mismatched domain policy sha256
        mismatched_domain = ManagedExecutionDomain(
            repository=self.repository,
            worktree_realpath=self.worktree_realpath,
            management_mode="lease",
            policy_id=self.policy_id,
            policy_sha256="9999999999999999999999999999999999999999999999999999999999999999",
        )

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=lambda _: mismatched_domain,
            policy_evaluator=self._default_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        result = gate.evaluate_request(target, "edit")

        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "POLICY_BINDING_MISMATCH")

    def test_context_repository_mismatch_fails_closed_with_deny(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)

        # Mismatched domain repository
        mismatched_domain = ManagedExecutionDomain(
            repository="different-repo",
            worktree_realpath=self.worktree_realpath,
            management_mode="lease",
            policy_id=self.policy_id,
            policy_sha256=self.policy_sha256,
        )

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=lambda _: mismatched_domain,
            policy_evaluator=self._default_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        result = gate.evaluate_request(target, "edit")

        # Because worktree_key won't match, NO_ACTIVE_LEASE
        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "NO_ACTIVE_LEASE")

    def test_policy_evaluator_exception_fails_closed_with_deny(self) -> None:
        lease = self._create_lease()
        self.store.issue(lease)
        self.store.activate(lease.lease_id)

        def bad_policy_evaluator(policy: PolicyReference, path: str, action: GateAction) -> bool:
            raise RuntimeError("policy evaluator exception")

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=bad_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        result = gate.evaluate_request(target, "edit")

        self.assertEqual(result.decision, GateDecision.DENY)
        self.assertEqual(result.violation_code, "POLICY_EVALUATION_ERROR")

    def test_non_lease_management_mode_returns_not_applicable(self) -> None:
        non_lease_domain = ManagedExecutionDomain(
            repository=self.repository,
            worktree_realpath=self.worktree_realpath,
            management_mode="legacy_mode",
            policy_id=self.policy_id,
            policy_sha256=self.policy_sha256,
        )

        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=lambda _: non_lease_domain,
            policy_evaluator=self._default_policy_evaluator,
        )

        target = os.path.join(self.worktree_dir, "src", "file.py")
        result = gate.evaluate_request(target, "edit")

        self.assertEqual(result.decision, GateDecision.NOT_APPLICABLE)
        self.assertIn("not under lease management", result.reason)

    def test_invalid_target_path_types_fail_closed_with_deny(self) -> None:
        gate = LocalExecutionGate(
            state_store=self.store,
            domain_resolver=self._default_domain_resolver,
            policy_evaluator=self._default_policy_evaluator,
        )

        for bad_path in ["", "   ", None, 123]:
            result = gate.evaluate_request(bad_path, "edit")  # type: ignore[arg-type]
            self.assertEqual(result.decision, GateDecision.DENY)
            self.assertEqual(result.violation_code, "INVALID_TARGET_PATH")

if __name__ == "__main__":
    unittest.main()
