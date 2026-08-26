#!/usr/bin/env python3
"""Phase 2 tests for LocalExecutionLease runtime state."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))

from local_execution_lease import (  # noqa: E402
    CanonicalTaskReference,
    PolicyReference,
    RuntimeContext,
    derive_lease,
)
from local_execution_lease_state import (  # noqa: E402
    LeaseConflictError,
    LeaseExpiredError,
    LeaseInvalidatedError,
    LeaseLifecycle,
    LeaseOutOfBandError,
    LeaseStateCorruptError,
    LeaseStateStore,
    LeaseTransitionError,
    ObservedExecutionState,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lease(worktree: str = "/tmp/ume-harness-phase2-worktree", task_id: str = "task-123"):
    task = CanonicalTaskReference(
        task_id=task_id,
        task_contract_sha256=_sha256(f"task:{task_id}"),
        allowed_capabilities=frozenset({"edit"}),
    )
    policy = PolicyReference(
        policy_id="site-policy-v0",
        policy_sha256=_sha256("site-policy-v0"),
        allowed_capabilities=frozenset({"edit"}),
    )
    context = RuntimeContext(
        repository="UMEBOSHIISAN/ume-harness",
        worktree_realpath=worktree,
        branch=f"task/{task_id}",
        starting_head="a" * 40,
        baseline_status_digest=_sha256("clean-status"),
        baseline_tree_digest=_sha256("tree-at-start"),
    )
    return derive_lease(task, policy, context)


def _baseline(lease) -> ObservedExecutionState:
    return ObservedExecutionState(
        starting_head=lease.starting_head,
        status_digest=lease.baseline_status_digest,
        tree_digest=lease.baseline_tree_digest,
    )


def _changed_state(lease, label: str) -> ObservedExecutionState:
    return ObservedExecutionState(
        starting_head=lease.starting_head,
        status_digest=_sha256(f"status:{label}"),
        tree_digest=_sha256(f"tree:{label}"),
    )


class _Clock:
    def __init__(self, value: int = 1_000):
        self.value = value

    def __call__(self) -> int:
        return self.value


class _Observer:
    def __init__(self, current: ObservedExecutionState):
        self.current = current

    def __call__(self, _state):
        return self.current


def _competing_issue(path: str, lease, queue) -> None:
    try:
        LeaseStateStore(path).issue(lease)
    except LeaseConflictError:
        queue.put("conflict")
    except Exception as exc:  # pragma: no cover - makes unexpected child failures visible
        queue.put(f"unexpected:{type(exc).__name__}:{exc}")
    else:
        queue.put("issued")


class LocalExecutionLeaseStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tempdir.name, "leases.json")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_issue_binds_immutable_baseline_and_bounded_expiry(self):
        lease = _lease()
        state = LeaseStateStore(self.state_path).issue(lease)

        self.assertEqual(state.lifecycle, LeaseLifecycle.ISSUED)
        self.assertEqual(state.baseline_anchor, _baseline(lease))
        self.assertEqual(state.expected_execution_state, _baseline(lease))
        self.assertGreater(state.expires_at, state.issued_at)
        self.assertNotEqual(state.delta_chain_digest, "")

    def test_issue_persists_capability_ceiling_and_test_profile(self):
        task = CanonicalTaskReference(
            task_id="test-only-task",
            task_contract_sha256=_sha256("task:test-only-task"),
            allowed_capabilities=frozenset({"test"}),
            test_profile="python-tests-v1",
        )
        policy = PolicyReference(
            policy_id="site-policy-v0",
            policy_sha256=_sha256("site-policy-v0"),
            allowed_capabilities=frozenset({"edit", "test"}),
            approved_test_profiles=frozenset({"python-tests-v1"}),
        )
        context = RuntimeContext(
            repository="UMEBOSHIISAN/ume-harness",
            worktree_realpath="/tmp/ume-harness-phase2-worktree",
            branch="task/test-only-task",
            starting_head="a" * 40,
            baseline_status_digest=_sha256("clean-status"),
            baseline_tree_digest=_sha256("tree-at-start"),
        )
        lease = derive_lease(task, policy, context)

        state = LeaseStateStore(self.state_path).issue(lease)
        payload = json.loads(Path(self.state_path).read_text(encoding="utf-8"))

        self.assertEqual(state.capabilities, frozenset({"test"}))
        self.assertEqual(state.test_profile, "python-tests-v1")
        self.assertEqual(payload["leases"][0]["capabilities"], ["test"])
        self.assertEqual(payload["leases"][0]["test_profile"], "python-tests-v1")

    def test_missing_persisted_capabilities_fail_closed(self):
        lease = _lease()
        store = LeaseStateStore(self.state_path)
        store.issue(lease)
        payload = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        payload["leases"][0].pop("capabilities", None)
        payload["leases"][0].pop("test_profile", None)
        Path(self.state_path).write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(LeaseStateCorruptError):
            store.get(lease.lease_id)

    def test_valid_shaped_capability_tampering_breaks_lease_identity(self):
        task = CanonicalTaskReference(
            task_id="test-only-task",
            task_contract_sha256=_sha256("task:test-only-task"),
            allowed_capabilities=frozenset({"test"}),
            test_profile="python-tests-v1",
        )
        policy = PolicyReference(
            policy_id="site-policy-v0",
            policy_sha256=_sha256("site-policy-v0"),
            allowed_capabilities=frozenset({"edit", "test"}),
            approved_test_profiles=frozenset({"python-tests-v1"}),
        )
        context = RuntimeContext(
            repository="UMEBOSHIISAN/ume-harness",
            worktree_realpath="/tmp/ume-harness-phase2-worktree",
            branch="task/test-only-task",
            starting_head="a" * 40,
            baseline_status_digest=_sha256("clean-status"),
            baseline_tree_digest=_sha256("tree-at-start"),
        )
        lease = derive_lease(task, policy, context)
        store = LeaseStateStore(self.state_path)
        store.issue(lease)
        payload = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        payload["leases"][0]["capabilities"] = ["edit"]
        payload["leases"][0]["test_profile"] = None
        Path(self.state_path).write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(LeaseStateCorruptError, "lease identity mismatch"):
            store.get(lease.lease_id)

    def test_lifecycle_tampering_breaks_record_integrity(self):
        lease = _lease()
        observer = _Observer(_baseline(lease))
        store = LeaseStateStore(self.state_path, observer=observer)
        store.issue(lease)
        store.activate(lease.lease_id)
        store.revoke(lease.lease_id, "human revoked")
        payload = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        record = payload["leases"][0]

        self.assertIn("record_digest", record)
        record["lifecycle"] = LeaseLifecycle.ACTIVE.value
        record["lifecycle_history"] = [
            LeaseLifecycle.ISSUED.value,
            LeaseLifecycle.ACTIVE.value,
        ]
        record["terminal_reason"] = None
        Path(self.state_path).write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(LeaseStateCorruptError, "record integrity mismatch"):
            store.get(lease.lease_id)

    def test_activation_requires_exact_baseline_and_marks_mismatch_invalid(self):
        lease = _lease()
        observer = _Observer(_changed_state(lease, "out-of-band-before-activation"))
        store = LeaseStateStore(self.state_path, observer=observer)
        store.issue(lease)

        with self.assertRaises(LeaseOutOfBandError):
            store.activate(lease.lease_id)

        self.assertEqual(store.get(lease.lease_id).lifecycle, LeaseLifecycle.INVALIDATED)

    def test_activation_keeps_baseline_and_expected_state_separate_from_later_edit(self):
        lease = _lease()
        observer = _Observer(_baseline(lease))
        store = LeaseStateStore(self.state_path, observer=observer)
        store.issue(lease)
        after = _changed_state(lease, "first-edit")
        store.activate(lease.lease_id)
        operation = store.begin_operation(lease.lease_id)
        observer.current = after

        state = store.complete_operation(lease.lease_id, operation.operation_id)

        self.assertEqual(state.lifecycle, LeaseLifecycle.ACTIVE)
        self.assertEqual(state.baseline_anchor, _baseline(lease))
        self.assertEqual(state.expected_execution_state, after)
        self.assertEqual(state.revision, 3)

    def test_only_one_nonterminal_lease_can_exist_per_worktree(self):
        first = _lease(task_id="task-one")
        second = _lease(task_id="task-two")
        store = LeaseStateStore(self.state_path)
        store.issue(first)

        with self.assertRaises(LeaseConflictError):
            store.issue(second)

    def test_competing_processes_can_issue_only_one_lease(self):
        lease = _lease()
        queue = multiprocessing.get_context("fork").Queue()
        processes = [
            multiprocessing.get_context("fork").Process(
                target=_competing_issue,
                args=(self.state_path, lease, queue),
            )
            for _ in range(2)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=5)

        results = [queue.get(timeout=2) for _ in processes]
        self.assertEqual(sorted(results), ["conflict", "issued"])
        self.assertTrue(all(process.exitcode == 0 for process in processes))

    def test_delta_chain_is_deterministic_from_observed_transitions(self):
        lease = _lease()
        first_after = _changed_state(lease, "first-edit")
        second_after = _changed_state(lease, "second-edit")

        def run_transitions(path: str) -> str:
            observer = _Observer(_baseline(lease))
            store = LeaseStateStore(path, observer=observer)
            store.issue(lease)
            store.activate(lease.lease_id)
            first = store.begin_operation(lease.lease_id)
            observer.current = first_after
            store.complete_operation(lease.lease_id, first.operation_id)
            second = store.begin_operation(lease.lease_id)
            observer.current = second_after
            return store.complete_operation(lease.lease_id, second.operation_id).delta_chain_digest

        first_path = os.path.join(self.tempdir.name, "first.json")
        second_path = os.path.join(self.tempdir.name, "second.json")
        self.assertEqual(run_transitions(first_path), run_transitions(second_path))

    def test_resume_with_open_operation_invalidates_after_ambiguous_interruption(self):
        lease = _lease()
        observer = _Observer(_baseline(lease))
        store = LeaseStateStore(self.state_path, observer=observer)
        store.issue(lease)
        store.activate(lease.lease_id)
        store.begin_operation(lease.lease_id)

        with self.assertRaises(LeaseInvalidatedError):
            store.resume(lease.lease_id)

        self.assertEqual(store.get(lease.lease_id).lifecycle, LeaseLifecycle.INVALIDATED)

    def test_resume_with_unexplained_delta_invalidates_fail_closed(self):
        lease = _lease()
        observer = _Observer(_baseline(lease))
        store = LeaseStateStore(self.state_path, observer=observer)
        store.issue(lease)
        unexpected = _changed_state(lease, "out-of-band")
        store.activate(lease.lease_id)
        observer.current = unexpected

        with self.assertRaises(LeaseOutOfBandError):
            store.resume(lease.lease_id)

        self.assertEqual(store.get(lease.lease_id).lifecycle, LeaseLifecycle.INVALIDATED)

    def test_starting_head_change_is_rejected_and_invalidates_operation(self):
        lease = _lease()
        observer = _Observer(_baseline(lease))
        store = LeaseStateStore(self.state_path, observer=observer)
        store.issue(lease)
        changed_head = replace(_changed_state(lease, "head-change"), starting_head="b" * 40)
        store.activate(lease.lease_id)
        operation = store.begin_operation(lease.lease_id)
        observer.current = changed_head

        with self.assertRaises(LeaseOutOfBandError):
            store.complete_operation(lease.lease_id, operation.operation_id)

        self.assertEqual(store.get(lease.lease_id).lifecycle, LeaseLifecycle.INVALIDATED)

    def test_expiry_is_checked_inside_state_transition_and_is_not_extended(self):
        clock = _Clock()
        lease = _lease()
        store = LeaseStateStore(self.state_path, clock=clock, observer=_Observer(_baseline(lease)))
        issued = store.issue(lease)
        self.assertEqual(issued.expires_at, issued.issued_at + 600)
        clock.value = issued.expires_at

        with self.assertRaises(LeaseExpiredError):
            store.activate(lease.lease_id)

        expired = store.get(lease.lease_id)
        self.assertEqual(expired.lifecycle, LeaseLifecycle.EXPIRED)
        self.assertEqual(expired.expires_at, issued.expires_at)

    def test_revoke_is_terminal_and_cannot_be_reactivated(self):
        lease = _lease()
        store = LeaseStateStore(self.state_path, observer=_Observer(_baseline(lease)))
        store.issue(lease)
        revoked = store.revoke(lease.lease_id, "human-revoked")

        self.assertEqual(revoked.lifecycle, LeaseLifecycle.REVOKED)
        with self.assertRaises(LeaseTransitionError):
            store.activate(lease.lease_id)

    def test_completion_requires_expected_state_and_preserves_terminal_receipt(self):
        lease = _lease()
        store = LeaseStateStore(self.state_path, observer=_Observer(_baseline(lease)))
        store.issue(lease)
        store.activate(lease.lease_id)
        completed = store.complete(lease.lease_id)

        self.assertEqual(completed.lifecycle, LeaseLifecycle.COMPLETED)
        with self.assertRaises(LeaseTransitionError):
            store.complete(lease.lease_id)

    def test_tampered_worktree_key_fails_closed_before_conflict_checks(self):
        lease = _lease()
        store = LeaseStateStore(self.state_path)
        store.issue(lease)
        payload = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        payload["leases"][0]["worktree_key"] = "f" * 64
        Path(self.state_path).write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(LeaseStateCorruptError):
            store.get(lease.lease_id)

    def test_tampered_terminal_lifecycle_fails_closed_without_valid_transition_history(self):
        lease = _lease()
        store = LeaseStateStore(self.state_path)
        store.issue(lease)
        payload = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        payload["leases"][0]["lifecycle"] = "COMPLETED"
        payload["leases"][0]["terminal_reason"] = "completed"
        Path(self.state_path).write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(LeaseStateCorruptError):
            store.get(lease.lease_id)

    def test_corrupt_state_fails_closed_without_fabricating_lease_state(self):
        Path(self.state_path).write_text("{not-json", encoding="utf-8")

        with self.assertRaises(LeaseStateCorruptError):
            LeaseStateStore(self.state_path).get("missing")

    def test_state_file_does_not_expose_external_authority_capability(self):
        lease = _lease()
        store = LeaseStateStore(self.state_path)
        store.issue(lease)
        payload = json.loads(Path(self.state_path).read_text(encoding="utf-8"))

        self.assertNotIn("external_authority", payload)
        self.assertNotIn("push", json.dumps(payload))
        self.assertNotIn("merge", json.dumps(payload))


if __name__ == "__main__":
    unittest.main(verbosity=2)
