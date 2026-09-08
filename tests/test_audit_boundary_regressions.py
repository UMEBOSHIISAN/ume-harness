"""Managed-mode boundary regressions; all data and authority are synthetic."""
import os
import subprocess

import pytest
from test_local_work_policy import env, runner


def lease_gate(env):
    runner._load_runtime_modules()
    from local_execution_lease import CanonicalTaskReference, PolicyReference, RuntimeContext, derive_lease
    store = runner.lels.LeaseStateStore(
        state_path=str(env[1] / "lease.json"), clock=lambda: 1000,
        observer=lambda scope: scope.baseline_anchor)
    lease = derive_lease(
        CanonicalTaskReference("audit", "3" * 64, frozenset({"edit"})),
        PolicyReference("policy", "2" * 64, frozenset({"edit"})),
        RuntimeContext("repo", str(env[0]), "task/audit", "1" * 40, "4" * 64, "5" * 64))
    store.issue(lease)
    store.activate(lease.lease_id)
    return runner.leg.LocalExecutionGate(store, lambda _: None, lambda *_: True), store, lease


def verdict(env, tool, payload, gate=None, cwd=None):
    return runner.evaluate_invocation_result(
        {"tool_name": tool, "tool_input": payload, "cwd": str(cwd or env[0]),
         "permission_mode": "default"}, gate, str(env[2]), str(env[1]))


def test_lexical_alias_is_protected_in_literal_search(env):
    (env[0] / "ordinary.txt").write_text("SYNTHETIC\n")
    (env[0] / ".env").symlink_to(env[0] / "ordinary.txt")
    assert verdict(env, "Bash", {"command": "grep SYNTHETIC .env"}).decision == "deny"


def test_cdpath_cannot_change_a_proven_managed_read(env):
    gate, _, _ = lease_gate(env)
    (env[0] / "child").mkdir()
    outside = env[0].parent / "outside"
    (outside / "child").mkdir(parents=True)
    (outside / "child/report.txt").write_text("SYNTHETIC_OUTSIDE\n")
    command = "cd child && grep SYNTHETIC report.txt"
    actual = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", command],
        cwd=env[0], env={"PATH": "/usr/bin:/bin", "CDPATH": str(outside)},
        capture_output=True, text=True, check=True)
    assert "SYNTHETIC_OUTSIDE" in actual.stdout
    assert verdict(env, "Bash", {"command": command}, gate).decision == "deny"
    assert verdict(env, "Bash", {"command": "cd ./child && grep x report.txt"}, gate).decision == "defer"


def test_revoked_lease_covers_shell_targets_discovered_after_classification(env):
    gate, store, lease = lease_gate(env)
    store.revoke(lease.lease_id, "synthetic revocation")
    outside = env[0].parent / "outside"
    outside.mkdir()
    result = verdict(env, "Bash", {"command": "python3 " + str(env[0] / "ordinary.py")}, gate, outside)
    assert result.decision == "deny"
    assert result.code == "NO_ACTIVE_LEASE"


@pytest.mark.parametrize("tool,payload", [
    ("Read", {"file_path": "alias.txt"}),
    ("Bash", {"command": "grep x alias.txt"}),
])
def test_managed_read_does_not_attest_hardlink_provenance(env, tool, payload):
    gate, _, _ = lease_gate(env)
    outside = env[0].parent / "outside.txt"
    outside.write_text("SYNTHETIC\n")
    os.link(outside, env[0] / "alias.txt")
    result = verdict(env, tool, payload, gate)
    assert result.decision == "deny"
    assert result.code == "UNVERIFIABLE_FILE_ALIAS"


def test_managed_single_link_read_still_defers(env):
    gate, _, _ = lease_gate(env)
    (env[0] / "ordinary.txt").write_text("SYNTHETIC\n")
    assert verdict(env, "Read", {"file_path": "ordinary.txt"}, gate).decision == "defer"


@pytest.mark.parametrize("form", ["python3 run.py --input={path}", "INPUT={path} python3 run.py"])
def test_embedded_revoked_target_never_becomes_native_ask(env, form):
    gate, store, lease = lease_gate(env)
    store.revoke(lease.lease_id, "synthetic revocation")
    outside = env[0].parent / "outside"
    outside.mkdir()
    command = form.format(path=env[0] / "ordinary.txt")
    result = verdict(env, "Bash", {"command": command}, gate, outside)
    assert result.decision == "deny"
    assert result.code == "NO_ACTIVE_LEASE"


def test_unresolved_cd_cannot_ask_around_revoked_domain(env):
    gate, store, lease = lease_gate(env)
    store.revoke(lease.lease_id, "synthetic revocation")
    outside = env[0].parent / "outside"
    outside.mkdir()
    result = verdict(env, "Bash", {"command": "cd project && python3 ordinary.py"}, gate, outside)
    assert result.decision == "deny"


def test_native_grep_retains_named_alias(env):
    (env[0] / "ordinary.txt").write_text("SYNTHETIC\n")
    (env[0] / ".env").symlink_to(env[0] / "ordinary.txt")
    assert verdict(env, "Grep", {"pattern": "SYNTHETIC", "path": ".env"}).decision == "deny"


@pytest.mark.parametrize("tail", ["python3 run.py --input=../../project/ordinary.txt",
                                  "INPUT=../../project/ordinary.txt python3 run.py"])
def test_embedded_target_follows_explicit_cd_candidates(env, tail):
    gate, store, lease = lease_gate(env)
    store.revoke(lease.lease_id, "synthetic revocation")
    outside = env[0].parent / "outside"
    (outside / "child").mkdir(parents=True)
    assert verdict(env, "Bash", {"command": "cd ./child && " + tail}, gate, outside).decision == "deny"
