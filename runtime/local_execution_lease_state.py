#!/usr/bin/env python3
"""Provider-independent Phase 2 runtime state for LocalExecutionLease.

This module owns lifecycle and observed-state transitions only.  It does not
inspect the filesystem, intercept tools, run commands, or grant external
authority.  Host adapters are responsible for supplying observations and will
be added in a later phase.
"""

from __future__ import annotations

import contextlib
import enum
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from local_execution_lease import (
    LEASE_VERSION,
    LocalExecutionLease,
    V0_CAPABILITY_CEILING,
    compute_lease_identity,
)


LEASE_STATE_SCHEMA = "ume_harness.local_execution_leases.v0"
LEASE_STATE_VERSION = 4
DEFAULT_LEASE_TTL_SECONDS = 600
STATE_FILENAME = "local_execution_leases.v0.json"
LOCK_FILENAME = "local_execution_leases.v0.lock"


class LeaseStateError(RuntimeError):
    """Base class for fail-closed runtime-state errors."""


class LeaseStateCorruptError(LeaseStateError):
    """Raised when the persisted state cannot be trusted."""


class LeaseObservationUnavailableError(LeaseStateError):
    """Raised when no trusted runtime observation provider is bound."""


class LeaseNotFoundError(LeaseStateError):
    """Raised when a lease identity is not present in the state store."""


class LeaseConflictError(LeaseStateError):
    """Raised when a new lease conflicts with an existing lease."""


class LeaseTransitionError(LeaseStateError):
    """Raised when a lifecycle transition is not permitted."""


class LeaseExpiredError(LeaseTransitionError):
    """Raised when a lease has reached its expiry boundary."""


class LeaseInvalidatedError(LeaseTransitionError):
    """Raised when a lease is quarantined after an unsafe observation."""


class LeaseOutOfBandError(LeaseInvalidatedError):
    """Raised when an observation cannot be explained by the expected state."""


class LeaseLifecycle(str, enum.Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


_NONTERMINAL = frozenset({LeaseLifecycle.ISSUED, LeaseLifecycle.ACTIVE})
_TERMINAL = frozenset(
    {
        LeaseLifecycle.COMPLETED,
        LeaseLifecycle.REVOKED,
        LeaseLifecycle.EXPIRED,
        LeaseLifecycle.INVALIDATED,
    }
)


def _validate_lifecycle_history(
    history: tuple[LeaseLifecycle, ...],
    lifecycle: LeaseLifecycle,
) -> None:
    if not history or history[0] != LeaseLifecycle.ISSUED or history[-1] != lifecycle:
        raise LeaseStateCorruptError("lifecycle history does not end at current lifecycle")
    if lifecycle == LeaseLifecycle.ISSUED and history != (LeaseLifecycle.ISSUED,):
        raise LeaseStateCorruptError("issued Lease has an invalid lifecycle history")
    if lifecycle == LeaseLifecycle.ACTIVE and history != (
        LeaseLifecycle.ISSUED,
        LeaseLifecycle.ACTIVE,
    ):
        raise LeaseStateCorruptError("active Lease has an invalid lifecycle history")
    if lifecycle == LeaseLifecycle.COMPLETED and history != (
        LeaseLifecycle.ISSUED,
        LeaseLifecycle.ACTIVE,
        LeaseLifecycle.COMPLETED,
    ):
        raise LeaseStateCorruptError("completed Lease has an invalid lifecycle history")
    if lifecycle in {LeaseLifecycle.REVOKED, LeaseLifecycle.EXPIRED, LeaseLifecycle.INVALIDATED}:
        allowed = {
            (LeaseLifecycle.ISSUED, lifecycle),
            (LeaseLifecycle.ISSUED, LeaseLifecycle.ACTIVE, lifecycle),
        }
        if history not in allowed:
            raise LeaseStateCorruptError("terminal Lease has an invalid lifecycle history")


@dataclass(frozen=True)
class ObservedExecutionState:
    """The smallest host observation used by the Phase 2 state machine."""

    starting_head: str
    status_digest: str
    tree_digest: str


@dataclass(frozen=True)
class LeaseOperation:
    """Opaque operation handle returned after an observed pre-state is stored."""

    operation_id: str
    lease_id: str
    before_state: ObservedExecutionState


@dataclass(frozen=True)
class LeaseRuntimeState:
    """Persisted lifecycle state for one derived Lease."""

    lease_id: str
    task_id: str
    task_contract_sha256: str
    policy_id: str
    policy_sha256: str
    repository: str
    worktree_realpath: str
    branch: str
    starting_head: str
    capabilities: frozenset[str]
    test_profile: str | None
    worktree_key: str
    lifecycle: LeaseLifecycle
    lifecycle_history: tuple[LeaseLifecycle, ...]
    issued_at: int
    expires_at: int
    baseline_anchor: ObservedExecutionState
    expected_execution_state: ObservedExecutionState
    delta_chain_digest: str
    revision: int
    open_operation_id: str | None
    open_operation_started_at: int | None
    terminal_reason: str | None


def resolve_state_dir() -> str:
    configured = os.environ.get("UME_HARNESS_STATE_DIR")
    if configured:
        return os.path.expanduser(configured)
    return os.path.expanduser("~/.ume-harness/state")


def default_state_path() -> str:
    return os.path.join(resolve_state_dir(), STATE_FILENAME)


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise LeaseTransitionError(f"{name} must be a non-empty trimmed string")
    return value


def _require_digest(name: str, value: object, length: int) -> str:
    value = _require_text(name, value)
    if len(value) != length or any(char not in "0123456789abcdef" for char in value):
        raise LeaseTransitionError(f"{name} must be a lowercase hexadecimal digest")
    return value


def _validate_observed(value: object, error_type: type[LeaseStateError] = LeaseTransitionError) -> ObservedExecutionState:
    if not isinstance(value, ObservedExecutionState):
        raise error_type("observed execution state has an invalid type")
    _require_digest("starting_head", value.starting_head, 40)
    _require_digest("status_digest", value.status_digest, 64)
    _require_digest("tree_digest", value.tree_digest, 64)
    return value


def _observed_payload(value: ObservedExecutionState) -> dict[str, str]:
    return {
        "starting_head": value.starting_head,
        "status_digest": value.status_digest,
        "tree_digest": value.tree_digest,
    }


def _same_observation(left: ObservedExecutionState, right: ObservedExecutionState) -> bool:
    return left == right


def _worktree_key(lease: LocalExecutionLease) -> str:
    return _canonical_digest(
        {
            "repository": lease.repository,
            "worktree_realpath": lease.worktree_realpath,
        }
    )


def _baseline_for(lease: LocalExecutionLease) -> ObservedExecutionState:
    return ObservedExecutionState(
        starting_head=lease.starting_head,
        status_digest=lease.baseline_status_digest,
        tree_digest=lease.baseline_tree_digest,
    )


def _genesis_delta_digest(lease: LocalExecutionLease, baseline: ObservedExecutionState) -> str:
    return _canonical_digest(
        {
            "kind": "baseline",
            "lease_id": lease.lease_id,
            "state": _observed_payload(baseline),
        }
    )


def _transition_delta_digest(
    previous_chain: str,
    before: ObservedExecutionState,
    after: ObservedExecutionState,
    revision: int,
) -> str:
    return _canonical_digest(
        {
            "kind": "observed-transition",
            "previous_chain": previous_chain,
            "revision": revision,
            "before": _observed_payload(before),
            "after": _observed_payload(after),
        }
    )


def _state_record_payload(state: LeaseRuntimeState) -> dict[str, Any]:
    return {
        "lease_id": state.lease_id,
        "task_id": state.task_id,
        "task_contract_sha256": state.task_contract_sha256,
        "policy_id": state.policy_id,
        "policy_sha256": state.policy_sha256,
        "repository": state.repository,
        "worktree_realpath": state.worktree_realpath,
        "branch": state.branch,
        "starting_head": state.starting_head,
        "capabilities": sorted(state.capabilities),
        "test_profile": state.test_profile,
        "worktree_key": state.worktree_key,
        "lifecycle": state.lifecycle.value,
        "lifecycle_history": [entry.value for entry in state.lifecycle_history],
        "issued_at": state.issued_at,
        "expires_at": state.expires_at,
        "baseline_anchor": _observed_payload(state.baseline_anchor),
        "expected_execution_state": _observed_payload(state.expected_execution_state),
        "delta_chain_digest": state.delta_chain_digest,
        "revision": state.revision,
        "open_operation_id": state.open_operation_id,
        "open_operation_started_at": state.open_operation_started_at,
        "terminal_reason": state.terminal_reason,
    }


def _state_payload(state: LeaseRuntimeState) -> dict[str, Any]:
    payload = _state_record_payload(state)
    payload["record_digest"] = _canonical_digest(
        {"kind": "lease-runtime-state", "record": payload}
    )
    return payload


def _state_from_payload(payload: object) -> LeaseRuntimeState:
    if not isinstance(payload, dict):
        raise LeaseStateCorruptError("lease record must be an object")

    try:
        lifecycle = LeaseLifecycle(payload["lifecycle"])
        history_payload = payload["lifecycle_history"]
        if not isinstance(history_payload, list):
            raise LeaseStateCorruptError("lifecycle history must be a list")
        lifecycle_history = tuple(LeaseLifecycle(entry) for entry in history_payload)
        baseline_payload = payload["baseline_anchor"]
        expected_payload = payload["expected_execution_state"]
        if not isinstance(baseline_payload, dict) or not isinstance(expected_payload, dict):
            raise LeaseStateCorruptError("state observations must be objects")
        baseline = ObservedExecutionState(
            starting_head=baseline_payload["starting_head"],
            status_digest=baseline_payload["status_digest"],
            tree_digest=baseline_payload["tree_digest"],
        )
        expected = ObservedExecutionState(
            starting_head=expected_payload["starting_head"],
            status_digest=expected_payload["status_digest"],
            tree_digest=expected_payload["tree_digest"],
        )
        capabilities_payload = payload["capabilities"]
        if not isinstance(capabilities_payload, list):
            raise LeaseStateCorruptError("capabilities must be a list")
        if len(capabilities_payload) != len(set(capabilities_payload)):
            raise LeaseStateCorruptError("capabilities contain duplicates")
        capabilities = frozenset(capabilities_payload)
        record_digest = payload["record_digest"]
        state = LeaseRuntimeState(
            lease_id=payload["lease_id"],
            task_id=payload["task_id"],
            task_contract_sha256=payload["task_contract_sha256"],
            policy_id=payload["policy_id"],
            policy_sha256=payload["policy_sha256"],
            repository=payload["repository"],
            worktree_realpath=payload["worktree_realpath"],
            branch=payload["branch"],
            starting_head=payload["starting_head"],
            capabilities=capabilities,
            test_profile=payload["test_profile"],
            worktree_key=payload["worktree_key"],
            lifecycle=lifecycle,
            lifecycle_history=lifecycle_history,
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
            baseline_anchor=baseline,
            expected_execution_state=expected,
            delta_chain_digest=payload["delta_chain_digest"],
            revision=payload["revision"],
            open_operation_id=payload["open_operation_id"],
            open_operation_started_at=payload["open_operation_started_at"],
            terminal_reason=payload["terminal_reason"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LeaseStateCorruptError("lease record has an invalid shape") from exc

    try:
        if not state.lease_id or not isinstance(state.lease_id, str):
            raise LeaseStateCorruptError("lease_id is invalid")
        if not state.task_id or not isinstance(state.task_id, str):
            raise LeaseStateCorruptError("task_id is invalid")
        _require_text("repository", state.repository)
        worktree = _require_text("worktree_realpath", state.worktree_realpath)
        if not os.path.isabs(worktree) or os.path.normpath(worktree) != worktree:
            raise LeaseStateCorruptError("worktree_realpath is not absolute and normalized")
        _require_text("branch", state.branch)
        _require_digest("task_contract_sha256", state.task_contract_sha256, 64)
        _require_digest("policy_sha256", state.policy_sha256, 64)
        _require_digest("starting_head", state.starting_head, 40)
        _require_digest("delta_chain_digest", state.delta_chain_digest, 64)
        _require_digest("record_digest", record_digest, 64)
        if any(not isinstance(capability, str) or not capability for capability in state.capabilities):
            raise LeaseStateCorruptError("capabilities contain an invalid name")
        if state.capabilities - V0_CAPABILITY_CEILING:
            raise LeaseStateCorruptError("capabilities exceed the V0 ceiling")
        if state.test_profile is not None and (
            not isinstance(state.test_profile, str)
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", state.test_profile) is None
        ):
            raise LeaseStateCorruptError("test_profile is invalid")
        if ("test" in state.capabilities) != (state.test_profile is not None):
            raise LeaseStateCorruptError("test capability/profile binding is invalid")
        expected_worktree_key = _canonical_digest(
            {"repository": state.repository, "worktree_realpath": state.worktree_realpath}
        )
        if state.worktree_key != expected_worktree_key:
            raise LeaseStateCorruptError("worktree identity key mismatch")
        if not isinstance(state.issued_at, int) or isinstance(state.issued_at, bool):
            raise LeaseStateCorruptError("issued_at is invalid")
        if not isinstance(state.expires_at, int) or isinstance(state.expires_at, bool):
            raise LeaseStateCorruptError("expires_at is invalid")
        if state.expires_at <= state.issued_at:
            raise LeaseStateCorruptError("expiry must be after issuance")
        if not isinstance(state.revision, int) or state.revision < 0:
            raise LeaseStateCorruptError("revision is invalid")
        _validate_lifecycle_history(state.lifecycle_history, state.lifecycle)
        _validate_observed(state.baseline_anchor, LeaseStateCorruptError)
        _validate_observed(state.expected_execution_state, LeaseStateCorruptError)
        if state.baseline_anchor.starting_head != state.starting_head:
            raise LeaseStateCorruptError("baseline anchor head mismatch")
        if state.expected_execution_state.starting_head != state.starting_head:
            raise LeaseStateCorruptError("expected state head mismatch")
        persisted_lease = LocalExecutionLease(
            lease_id=state.lease_id,
            lease_version=LEASE_VERSION,
            task_id=state.task_id,
            task_contract_sha256=state.task_contract_sha256,
            policy_id=state.policy_id,
            policy_sha256=state.policy_sha256,
            repository=state.repository,
            worktree_realpath=state.worktree_realpath,
            branch=state.branch,
            starting_head=state.starting_head,
            baseline_status_digest=state.baseline_anchor.status_digest,
            baseline_tree_digest=state.baseline_anchor.tree_digest,
            capabilities=state.capabilities,
            test_profile=state.test_profile,
            external_mutations=False,
        )
        if compute_lease_identity(persisted_lease) != state.lease_id:
            raise LeaseStateCorruptError("lease identity mismatch")
        expected_record_digest = _canonical_digest(
            {"kind": "lease-runtime-state", "record": _state_record_payload(state)}
        )
        if record_digest != expected_record_digest:
            raise LeaseStateCorruptError("record integrity mismatch")
        if state.lifecycle in _TERMINAL and state.open_operation_id is not None:
            raise LeaseStateCorruptError("terminal lease cannot have an open operation")
        if state.open_operation_id is None and state.open_operation_started_at is not None:
            raise LeaseStateCorruptError("operation timestamp without operation")
        if state.open_operation_id is not None and not state.open_operation_started_at:
            raise LeaseStateCorruptError("operation is missing its start time")
    except LeaseStateCorruptError:
        raise
    except LeaseStateError as exc:
        raise LeaseStateCorruptError(str(exc)) from exc
    return state


def _new_document() -> dict[str, Any]:
    return {
        "$schema": LEASE_STATE_SCHEMA,
        "version": LEASE_STATE_VERSION,
        "leases": [],
    }


def _validate_document(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LeaseStateCorruptError("state document must be an object")
    if payload.get("$schema") != LEASE_STATE_SCHEMA or payload.get("version") != LEASE_STATE_VERSION:
        raise LeaseStateCorruptError("state document schema/version mismatch")
    records = payload.get("leases")
    if not isinstance(records, list):
        raise LeaseStateCorruptError("state document leases must be a list")

    seen_ids: set[str] = set()
    active_worktrees: set[str] = set()
    validated: list[dict[str, Any]] = []
    for record in records:
        state = _state_from_payload(record)
        if state.lease_id in seen_ids:
            raise LeaseStateCorruptError("duplicate lease identity")
        seen_ids.add(state.lease_id)
        if state.lifecycle in _NONTERMINAL:
            if state.worktree_key in active_worktrees:
                raise LeaseStateCorruptError("multiple nonterminal leases for one worktree")
            active_worktrees.add(state.worktree_key)
        validated.append(_state_payload(state))
    return {"$schema": LEASE_STATE_SCHEMA, "version": LEASE_STATE_VERSION, "leases": validated}


class LeaseStateStore:
    """Atomic, same-host runtime state store for Phase 2 Lease lifecycle.

    Lifecycle methods obtain observations from the provider bound at
    construction time.  They deliberately do not accept pre/post state values
    from the worker operation itself.  Phase 2 supplies the provider seam;
    Phase 3 will bind it to the host execution gate's real observation path.
    """

    def __init__(
        self,
        state_path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], float] | None = None,
        observer: Callable[[LeaseRuntimeState], ObservedExecutionState] | None = None,
    ) -> None:
        self.state_path = os.path.abspath(os.fspath(state_path or default_state_path()))
        self.lock_path = f"{self.state_path}.lock"
        self._clock = clock or time.time
        if observer is not None and not callable(observer):
            raise LeaseStateError("runtime observer must be callable")
        self._observer = observer

    def _now(self) -> int:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise LeaseStateError("runtime clock returned an invalid value")
        return int(value)

    def _observe(self, state: LeaseRuntimeState) -> ObservedExecutionState:
        if self._observer is None:
            raise LeaseObservationUnavailableError(
                "Phase 2 Lease transitions require a bound runtime observer"
            )
        try:
            observed = self._observer(state)
        except LeaseStateError:
            raise
        except Exception as exc:  # noqa: BLE001 - observer failure is fail-closed
            raise LeaseStateError("runtime observation failed") from exc
        try:
            return _validate_observed(observed)
        except LeaseStateError as exc:
            raise LeaseStateError("runtime observer returned an invalid observation") from exc

    def _ensure_directory(self) -> None:
        directory = os.path.dirname(self.state_path) or "."
        os.makedirs(directory, mode=0o700, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError as exc:
            raise LeaseStateError("cannot secure Lease state directory") from exc

    def _reject_symlink_or_nonfile(self, path: str, label: str) -> None:
        if not os.path.lexists(path):
            return
        if os.path.islink(path) or not os.path.isfile(path):
            raise LeaseStateCorruptError(f"{label} is not a regular file")

    @contextlib.contextmanager
    def _locked_document(self) -> Iterator[dict[str, Any]]:
        self._ensure_directory()
        self._reject_symlink_or_nonfile(self.lock_path, "Lease lock")
        try:
            lock_file = open(self.lock_path, "a+", encoding="utf-8")
        except OSError as exc:
            raise LeaseStateError("cannot open Lease lock") from exc
        try:
            os.chmod(self.lock_path, 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            document = self._load_locked()
            yield document
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    def _load_locked(self) -> dict[str, Any]:
        self._reject_symlink_or_nonfile(self.state_path, "Lease state")
        if not os.path.exists(self.state_path):
            return _new_document()
        try:
            with open(self.state_path, "r", encoding="utf-8") as state_file:
                payload = json.load(state_file)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LeaseStateCorruptError("cannot read Lease state") from exc
        return _validate_document(payload)

    def _save_locked(self, document: dict[str, Any]) -> None:
        document = _validate_document(document)
        directory = os.path.dirname(self.state_path) or "."
        self._reject_symlink_or_nonfile(self.state_path, "Lease state")
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=directory,
                prefix=".local-execution-leases-",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as state_file:
                temporary_path = state_file.name
                os.chmod(temporary_path, 0o600)
                json.dump(document, state_file, ensure_ascii=False, sort_keys=True, indent=2)
                state_file.write("\n")
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temporary_path, self.state_path)
            temporary_path = None
            os.chmod(self.state_path, 0o600)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise LeaseStateError("cannot durably save Lease state") from exc
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    def _expire_due(self, document: dict[str, Any], now: int) -> bool:
        changed = False
        for index, raw_state in enumerate(document["leases"]):
            state = _state_from_payload(raw_state)
            if state.lifecycle not in _NONTERMINAL or now < state.expires_at:
                continue
            document["leases"][index] = _state_payload(
                LeaseRuntimeState(
                    **{
                        **state.__dict__,
                        "lifecycle": LeaseLifecycle.EXPIRED,
                        "lifecycle_history": state.lifecycle_history + (LeaseLifecycle.EXPIRED,),
                        "open_operation_id": None,
                        "open_operation_started_at": None,
                        "terminal_reason": "expired",
                        "revision": state.revision + 1,
                    }
                )
            )
            changed = True
        return changed

    @staticmethod
    def _find(document: dict[str, Any], lease_id: str) -> tuple[int, LeaseRuntimeState]:
        for index, raw_state in enumerate(document["leases"]):
            state = _state_from_payload(raw_state)
            if state.lease_id == lease_id:
                return index, state
        raise LeaseNotFoundError("Lease identity is not present")

    @staticmethod
    def _replace(document: dict[str, Any], index: int, state: LeaseRuntimeState) -> None:
        document["leases"][index] = _state_payload(state)

    @staticmethod
    def _validate_lease(lease: object) -> LocalExecutionLease:
        if not isinstance(lease, LocalExecutionLease):
            raise LeaseStateError("Lease has an invalid type")
        if lease.external_mutations is not False:
            raise LeaseStateError("external mutation capability is forbidden")
        if not lease.lease_id or not lease.task_id or not lease.repository:
            raise LeaseStateError("Lease binding is incomplete")
        return lease

    @staticmethod
    def _invalidate(
        document: dict[str, Any],
        index: int,
        state: LeaseRuntimeState,
        reason: str,
    ) -> LeaseRuntimeState:
        invalidated = LeaseRuntimeState(
            **{
                **state.__dict__,
                "lifecycle": LeaseLifecycle.INVALIDATED,
                "lifecycle_history": state.lifecycle_history + (LeaseLifecycle.INVALIDATED,),
                "open_operation_id": None,
                "open_operation_started_at": None,
                "terminal_reason": reason,
                "revision": state.revision + 1,
            }
        )
        LeaseStateStore._replace(document, index, invalidated)
        return invalidated

    def issue(self, lease: LocalExecutionLease) -> LeaseRuntimeState:
        lease = self._validate_lease(lease)
        baseline = _baseline_for(lease)
        _validate_observed(baseline)
        now = self._now()
        with self._locked_document() as document:
            changed = self._expire_due(document, now)
            worktree_key = _worktree_key(lease)
            for raw_state in document["leases"]:
                state = _state_from_payload(raw_state)
                if state.lease_id == lease.lease_id:
                    raise LeaseConflictError("Lease identity already exists")
                if state.worktree_key == worktree_key and state.lifecycle in _NONTERMINAL:
                    raise LeaseConflictError("worktree already has a nonterminal Lease")
            state = LeaseRuntimeState(
                lease_id=lease.lease_id,
                task_id=lease.task_id,
                task_contract_sha256=lease.task_contract_sha256,
                policy_id=lease.policy_id,
                policy_sha256=lease.policy_sha256,
                repository=lease.repository,
                worktree_realpath=lease.worktree_realpath,
                branch=lease.branch,
                starting_head=lease.starting_head,
                capabilities=lease.capabilities,
                test_profile=lease.test_profile,
                worktree_key=worktree_key,
                lifecycle=LeaseLifecycle.ISSUED,
                lifecycle_history=(LeaseLifecycle.ISSUED,),
                issued_at=now,
                expires_at=now + DEFAULT_LEASE_TTL_SECONDS,
                baseline_anchor=baseline,
                expected_execution_state=baseline,
                delta_chain_digest=_genesis_delta_digest(lease, baseline),
                revision=0,
                open_operation_id=None,
                open_operation_started_at=None,
                terminal_reason=None,
            )
            document["leases"].append(_state_payload(state))
            self._save_locked(document)
            return state

    def get(self, lease_id: str) -> LeaseRuntimeState:
        _require_text("lease_id", lease_id)
        now = self._now()
        with self._locked_document() as document:
            changed = self._expire_due(document, now)
            _, state = self._find(document, lease_id)
            if changed:
                self._save_locked(document)
            return state

    def activate(self, lease_id: str) -> LeaseRuntimeState:
        now = self._now()
        with self._locked_document() as document:
            changed = self._expire_due(document, now)
            index, state = self._find(document, lease_id)
            if changed:
                self._save_locked(document)
            if state.lifecycle == LeaseLifecycle.EXPIRED:
                raise LeaseExpiredError("Lease expired before activation")
            if state.lifecycle != LeaseLifecycle.ISSUED:
                raise LeaseTransitionError("Lease is not awaiting activation")
            current_state = self._observe(state)
            if not _same_observation(state.baseline_anchor, current_state):
                invalidated = self._invalidate(document, index, state, "baseline mismatch")
                self._save_locked(document)
                raise LeaseOutOfBandError(
                    f"baseline mismatch; Lease invalidated at revision {invalidated.revision}"
                )
            active = LeaseRuntimeState(
                **{
                    **state.__dict__,
                    "lifecycle": LeaseLifecycle.ACTIVE,
                    "lifecycle_history": state.lifecycle_history + (LeaseLifecycle.ACTIVE,),
                    "revision": state.revision + 1,
                }
            )
            self._replace(document, index, active)
            self._save_locked(document)
            return active

    def begin_operation(self, lease_id: str) -> LeaseOperation:
        now = self._now()
        with self._locked_document() as document:
            changed = self._expire_due(document, now)
            index, state = self._find(document, lease_id)
            if changed:
                self._save_locked(document)
            if state.lifecycle == LeaseLifecycle.EXPIRED:
                raise LeaseExpiredError("Lease expired before operation")
            if state.lifecycle != LeaseLifecycle.ACTIVE:
                raise LeaseTransitionError("Lease is not active")
            if state.open_operation_id is not None:
                raise LeaseTransitionError("Lease already has an open operation")
            current_state = self._observe(state)
            if not _same_observation(state.expected_execution_state, current_state):
                invalidated = self._invalidate(document, index, state, "unexpected pre-operation delta")
                self._save_locked(document)
                raise LeaseOutOfBandError(
                    f"unexpected pre-operation delta; Lease invalidated at revision {invalidated.revision}"
                )
            operation_id = uuid.uuid4().hex
            active = LeaseRuntimeState(
                **{
                    **state.__dict__,
                    "open_operation_id": operation_id,
                    "open_operation_started_at": now,
                    "revision": state.revision + 1,
                }
            )
            self._replace(document, index, active)
            self._save_locked(document)
            return LeaseOperation(operation_id, lease_id, current_state)

    def complete_operation(
        self,
        lease_id: str,
        operation_id: str,
    ) -> LeaseRuntimeState:
        _require_text("operation_id", operation_id)
        now = self._now()
        with self._locked_document() as document:
            changed = self._expire_due(document, now)
            index, state = self._find(document, lease_id)
            if changed:
                self._save_locked(document)
            if state.lifecycle == LeaseLifecycle.EXPIRED:
                raise LeaseExpiredError("Lease expired before operation completion")
            if state.lifecycle != LeaseLifecycle.ACTIVE:
                raise LeaseTransitionError("Lease is not active")
            if state.open_operation_id != operation_id:
                raise LeaseTransitionError("operation handle does not match open operation")
            after_state = self._observe(state)
            if after_state.starting_head != state.starting_head:
                invalidated = self._invalidate(document, index, state, "starting HEAD changed")
                self._save_locked(document)
                raise LeaseOutOfBandError(
                    f"starting HEAD changed; Lease invalidated at revision {invalidated.revision}"
                )
            revision = state.revision + 1
            completed = LeaseRuntimeState(
                **{
                    **state.__dict__,
                    "expected_execution_state": after_state,
                    "delta_chain_digest": _transition_delta_digest(
                        state.delta_chain_digest,
                        state.expected_execution_state,
                        after_state,
                        revision,
                    ),
                    "open_operation_id": None,
                    "open_operation_started_at": None,
                    "revision": revision,
                }
            )
            self._replace(document, index, completed)
            self._save_locked(document)
            return completed

    def resume(self, lease_id: str) -> LeaseRuntimeState:
        now = self._now()
        with self._locked_document() as document:
            changed = self._expire_due(document, now)
            index, state = self._find(document, lease_id)
            if changed:
                self._save_locked(document)
            if state.lifecycle == LeaseLifecycle.EXPIRED:
                raise LeaseExpiredError("Lease expired before resume")
            if state.lifecycle != LeaseLifecycle.ACTIVE:
                raise LeaseTransitionError("Lease is not resumable")
            if state.open_operation_id is not None:
                invalidated = self._invalidate(document, index, state, "open operation after interruption")
                self._save_locked(document)
                raise LeaseInvalidatedError(
                    f"open operation after interruption; Lease invalidated at revision {invalidated.revision}"
                )
            current_state = self._observe(state)
            if not _same_observation(state.expected_execution_state, current_state):
                invalidated = self._invalidate(document, index, state, "unexplained resume delta")
                self._save_locked(document)
                raise LeaseOutOfBandError(
                    f"unexplained resume delta; Lease invalidated at revision {invalidated.revision}"
                )
            return state

    def complete(self, lease_id: str) -> LeaseRuntimeState:
        now = self._now()
        with self._locked_document() as document:
            changed = self._expire_due(document, now)
            index, state = self._find(document, lease_id)
            if changed:
                self._save_locked(document)
            if state.lifecycle == LeaseLifecycle.EXPIRED:
                raise LeaseExpiredError("Lease expired before completion")
            if state.lifecycle != LeaseLifecycle.ACTIVE:
                raise LeaseTransitionError("Lease is not active")
            if state.open_operation_id is not None:
                raise LeaseTransitionError("cannot complete with an open operation")
            current_state = self._observe(state)
            if not _same_observation(state.expected_execution_state, current_state):
                invalidated = self._invalidate(document, index, state, "unexplained completion delta")
                self._save_locked(document)
                raise LeaseOutOfBandError(
                    f"unexplained completion delta; Lease invalidated at revision {invalidated.revision}"
                )
            completed = LeaseRuntimeState(
                **{
                    **state.__dict__,
                    "lifecycle": LeaseLifecycle.COMPLETED,
                    "lifecycle_history": state.lifecycle_history + (LeaseLifecycle.COMPLETED,),
                    "revision": state.revision + 1,
                }
            )
            self._replace(document, index, completed)
            self._save_locked(document)
            return completed

    def revoke(self, lease_id: str, reason: str) -> LeaseRuntimeState:
        _require_text("reason", reason)
        now = self._now()
        with self._locked_document() as document:
            changed = self._expire_due(document, now)
            index, state = self._find(document, lease_id)
            if changed:
                self._save_locked(document)
            if state.lifecycle == LeaseLifecycle.EXPIRED:
                raise LeaseExpiredError("Lease already expired")
            if state.lifecycle not in _NONTERMINAL:
                raise LeaseTransitionError("terminal Lease cannot be revoked")
            revoked = LeaseRuntimeState(
                **{
                    **state.__dict__,
                    "lifecycle": LeaseLifecycle.REVOKED,
                    "lifecycle_history": state.lifecycle_history + (LeaseLifecycle.REVOKED,),
                    "open_operation_id": None,
                    "open_operation_started_at": None,
                    "terminal_reason": reason,
                    "revision": state.revision + 1,
                }
            )
            self._replace(document, index, revoked)
            self._save_locked(document)
            return revoked


__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "LEASE_STATE_SCHEMA",
    "LeaseConflictError",
    "LeaseExpiredError",
    "LeaseInvalidatedError",
    "LeaseLifecycle",
    "LeaseNotFoundError",
    "LeaseObservationUnavailableError",
    "LeaseOperation",
    "LeaseOutOfBandError",
    "LeaseRuntimeState",
    "LeaseStateCorruptError",
    "LeaseStateError",
    "LeaseStateStore",
    "LeaseTransitionError",
    "ObservedExecutionState",
    "default_state_path",
    "resolve_state_dir",
]
