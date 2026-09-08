"""Read-only registration diagnostics; all settings are synthetic."""
import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


h = load("runtime/hook_setup_service.py")
health = load("scripts/health_check.py")


def settings(*commands):
    return {"hooks": {"PreToolUse": [{"matcher": "Write", "hooks": [
        {"type": "command", "command": c} for c in commands]}]}}


def test_inventory_preserves_ownership_and_input(tmp_path):
    root = tmp_path / "ume-harness/v1.2.3"
    command = h.get_adapter_hook_commands(str(root))["PreToolUse"]
    legacy = str(tmp_path / ".claude/hooks/unified_tool_classifier.py")
    other = str(tmp_path / "ume-harness/v1.2.2/adapters/claude-code/pretooluse_hook.py")
    data = settings(command, command, "python3 " + legacy, other)
    before = copy.deepcopy(data)
    report = h.inspect_hook_registrations(data, str(root), settings_path=str(tmp_path / ".claude/settings.json"))
    assert data == before
    assert report["findings"] == ["duplicate_current_pretooluse", "legacy_current_coexistence", "multiple_version_pretooluse"]
    assert [r["owned"] for r in report["registrations"]] == [True, True, False, False]
    assert report["live_effective_settings"] == "unknown"
    assert report["matcher_overlap"] == "not evaluated"
    assert report["connected_mode"] == "conflict"


def test_same_legacy_basename_elsewhere_is_unrelated(tmp_path):
    command = str(tmp_path / "unrelated/unified_tool_classifier.py")
    report = h.inspect_hook_registrations(settings(command), str(tmp_path),
                                          settings_path=str(tmp_path / ".claude/settings.local.json"))
    assert report["registrations"][0]["classification"] == "unrelated"
    assert report["findings"] == []


@pytest.mark.parametrize("event,filename,expected", [
    ("PreToolUse", "pretooluse_hook.py", "other_version_reference"),
    ("PermissionRequest", "permission_request_hook.py", "other_version_reference"),
    ("PostToolUseFailure", "posttooluse_failure_hook.py", "other_version_reference"),
    ("PreToolUse", "permission_request_hook.py", "unrelated"),
    ("PermissionRequest", "pretooluse_hook.py", "unrelated"),
])
def test_release_candidate_version_requires_matching_event(tmp_path, event, filename, expected):
    command = str(tmp_path / "ume-harness/v1.2.3-rc.1/adapters/claude-code" / filename)
    data = settings(command)
    data["hooks"][event] = data["hooks"].pop("PreToolUse")
    report = h.inspect_hook_registrations(data, str(tmp_path / "current"), settings_path="fixture")
    assert report["registrations"][0]["classification"] == expected
    assert not report["registrations"][0]["owned"]


@pytest.mark.parametrize("command", ["echo '/tmp/unified_tool_classifier.py'", "bash -c 'python3 /tmp/unified_tool_classifier.py'", "python3 $ROOT/unified_tool_classifier.py", "'unterminated"])
def test_ambiguous_commands_never_claim_ownership(command, tmp_path):
    report = h.inspect_hook_registrations(settings(command), str(tmp_path), settings_path="fixture")
    assert report["registrations"][0]["classification"] == "ambiguous"
    assert not report["registrations"][0]["owned"]


def test_file_inventory_is_read_only_and_handles_missing(tmp_path):
    path = tmp_path / "settings.json"
    assert not h.inspect_settings_file(str(path), str(tmp_path))["file_exists"]
    data = settings(h.get_adapter_hook_commands(str(tmp_path / "with space"))["PreToolUse"])
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert h.inspect_settings_file(str(path), str(tmp_path / "with space"))["registrations"][0]["owned"]
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("data", [{"hooks": []}, {"hooks": {"PreToolUse": {}}}, {"hooks": {"PreToolUse": [None]}}])
def test_invalid_structure_rejected(data, tmp_path):
    with pytest.raises(ValueError):
        h.inspect_hook_registrations(data, str(tmp_path), settings_path="fixture")


def test_health_never_imports_before_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(health, "verify_release_identity", lambda _: (False, "fixture mismatch"))
    def forbidden(*args, **kwargs):
        pytest.fail("subprocess before identity verification")
    monkeypatch.setattr(health.subprocess, "run", forbidden)
    health.run_diagnostics(str(tmp_path), json_output=True, settings_path=str(tmp_path / "settings.json"))
    checks = json.loads(capsys.readouterr().out)["checks"]
    record = next(c for c in checks if c["name"] == "Hook Registration File Inventory")
    assert not record["passed"]
    assert "Skipped" in record["detail"]


def test_health_explicit_inventory_after_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(health, "verify_release_identity", lambda _: (True, "fixture verified"))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="IMPORT_OK" if len(calls) == 1 else json.dumps({"scope": "file inventory only", "connected_mode": "disconnected", "findings": []}), stderr="")
    monkeypatch.setattr(health.subprocess, "run", run)
    health.main(["--installed-dir", str(tmp_path), "--settings-path", str(tmp_path / "settings.json"), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert len(calls) == 2
    assert calls[1][-2:] == [str(tmp_path / "settings.json"), str(tmp_path)]
    assert next(c for c in checks if c["name"] == "Hook Registration File Inventory")["passed"]


def test_health_without_settings_does_not_inventory(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(health, "verify_release_identity", lambda _: (True, "fixture verified"))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="IMPORT_OK", stderr="")
    monkeypatch.setattr(health.subprocess, "run", run)
    health.run_diagnostics(str(tmp_path), json_output=True)
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert len(calls) == 1
    assert all(c["name"] != "Hook Registration File Inventory" for c in checks)


def test_invalid_file_and_symlink_rejected_without_changes(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{invalid")
    with pytest.raises(ValueError):
        h.inspect_settings_file(str(path), str(tmp_path))
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="symlinks"):
        h.inspect_settings_file(str(link), str(tmp_path))
    assert path.read_text() == "{invalid"


@pytest.mark.parametrize("profile,passed", [(None, True), ("{invalid", False),
    ('{"schema_version":"local_work_policy.v1","protected_roots":[]}', True)])
def test_health_profile_uses_real_validator_without_state_writes(tmp_path, monkeypatch, capsys, profile, passed):
    # Removing profile validation would wrongly accept malformed policy.
    monkeypatch.setattr(health, "verify_release_identity", lambda _: (True, "isolated source fixture"))
    state = tmp_path / "state"
    if profile is not None:
        state.mkdir()
        (state / "local_work_policy.json").write_text(profile)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    health.main(["--installed-dir", str(ROOT), "--state-dir", str(state), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]
    check = next(c for c in checks if c["name"] == "Local Work Policy Profile")
    assert check["passed"] is passed
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


def test_health_profile_never_imports_before_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(health, "verify_release_identity", lambda _: (False, "fixture mismatch"))
    def forbidden(*args, **kwargs):
        pytest.fail("profile import before verified identity")
    monkeypatch.setattr(health.subprocess, "run", forbidden)
    health.main(["--installed-dir", str(ROOT), "--state-dir", str(tmp_path), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]
    check = next(c for c in checks if c["name"] == "Local Work Policy Profile")
    assert not check["passed"] and "Skipped" in check["detail"]


def test_default_setup_never_restores_pretooluse_and_is_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    data = json.loads(path.read_text())
    assert set(data["hooks"]) == {"PermissionRequest", "PostToolUseFailure"}
    before = path.read_bytes()
    files = sorted(tmp_path.iterdir())
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    assert path.read_bytes() == before
    assert sorted(tmp_path.iterdir()) == files


@pytest.mark.parametrize("same_prefix", [False, True])
def test_explicit_upgrade_disconnect_then_setup_matches_fresh_profile(tmp_path, same_prefix):
    """Dropping old ownership or restoring PreToolUse breaks upgrade parity."""
    old_root = str(ROOT) if same_prefix else str(tmp_path / "old/lib/ume-harness/v0.1.5")
    path = tmp_path / "settings.json"
    native = {"defaultMode": "default", "deny": ["Read(**/.env)"]}
    unrelated = {"matcher": "*", "hooks": [{"type": "command", "command": "/user/custom-gate"}]}
    data = {"permissions": native, "hooks": {"PreToolUse": [unrelated]}}
    for event, command in h.get_adapter_hook_commands(old_root).items():
        data["hooks"].setdefault(event, []).append(
            {"matcher": "*", "hooks": [{"type": "command", "command": command}]})
    path.write_text(json.dumps(data))
    ok, reason = h.disconnect_hooks_from_settings(old_root, str(path))
    assert ok, reason
    args = [sys.executable, "-B", str(ROOT / "bin/ume-harness"), "setup", "--yes", "--settings-path", str(path)]
    proc = subprocess.run(args, capture_output=True, text=True, check=True)
    upgraded = json.loads(path.read_text())
    assert upgraded["permissions"] == native
    assert upgraded["hooks"]["PreToolUse"] == [unrelated]
    report = h.inspect_settings_file(str(path), str(ROOT))
    assert report["connected_mode"] == "presentation"
    assert not report["findings"]
    fresh = tmp_path / "fresh.json"
    assert h.install_hooks_to_settings(str(ROOT), str(fresh))[0]
    expected = json.loads(fresh.read_text())
    for event in ("PermissionRequest", "PostToolUseFailure"):
        assert upgraded["hooks"][event] == expected["hooks"][event]
    before = path.read_bytes()
    subprocess.run(args, capture_output=True, text=True, check=True)
    assert path.read_bytes() == before


def test_explicit_managed_restores_third_hook_then_default_preserves_it(tmp_path):
    path = tmp_path / "settings.json"
    assert h.install_hooks_to_settings(str(ROOT), str(path), managed=True)[0]
    data = json.loads(path.read_text())
    assert set(data["hooks"]) == {"PreToolUse", "PermissionRequest", "PostToolUseFailure"}
    before = path.read_bytes()
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    assert path.read_bytes() == before
    del data["hooks"]["PreToolUse"]
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    assert path.read_bytes() == before
    assert h.install_hooks_to_settings(str(ROOT), str(path), managed=True)[0]
    assert "PreToolUse" in json.loads(path.read_text())["hooks"]


@pytest.mark.parametrize("managed", [False, True])
def test_cli_setup_optin_and_disconnect_preserve_unrelated(tmp_path, managed):
    path = tmp_path / "settings.json"
    initial = {"theme": "dark", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/user/stop"}]}]}}
    path.write_text(json.dumps(initial))
    env = dict(os.environ, HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    args = [sys.executable, "-B", str(ROOT / "bin/ume-harness"), "setup", "--settings-path", str(path)]
    proc = subprocess.run(args + ["--yes"] + (["--managed"] if managed else []), env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(path.read_text())
    assert ("PreToolUse" in data["hooks"]) is managed
    assert set(data["hooks"]) == ({"Stop", "PermissionRequest", "PostToolUseFailure", "PreToolUse"} if managed else {"Stop", "PermissionRequest", "PostToolUseFailure"})
    proc = subprocess.run(args + ["--disconnect"], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(path.read_text()) == initial


@pytest.mark.parametrize("events,mode", [
    ([], "disconnected"), (["PermissionRequest"], "partial"),
    (["PermissionRequest", "PostToolUseFailure"], "presentation"),
    (["PreToolUse", "PermissionRequest", "PostToolUseFailure"], "managed"),
    (["PermissionRequest", "PermissionRequest", "PostToolUseFailure"], "conflict"),
])
def test_inventory_connected_mode(tmp_path, events, mode):
    commands = h.get_adapter_hook_commands(str(ROOT))
    data = {"hooks": {}}
    for event in events:
        data["hooks"].setdefault(event, []).append({"matcher": "*", "hooks": [{"type": "command", "command": commands[event]}]})
    report = h.inspect_hook_registrations(data, str(ROOT), settings_path=str(tmp_path / "settings.json"))
    assert report["connected_mode"] == mode
    assert report["live_effective_settings"] == "unknown"
    assert h.inspect_settings_file(str(tmp_path / "missing.json"), str(ROOT))["connected_mode"] == "absent"


@pytest.mark.parametrize("kind,passed", [("absent", True), ("disconnected", True), ("presentation", True), ("managed", True), ("partial", False), ("conflict", False)])
def test_health_registration_uses_real_inventory(tmp_path, monkeypatch, capsys, kind, passed):
    monkeypatch.setattr(health, "verify_release_identity", lambda _: (True, "isolated source fixture"))
    path = tmp_path / "settings.json"
    events = {"absent": [], "disconnected": [], "partial": ["PermissionRequest"],
              "presentation": ["PermissionRequest", "PostToolUseFailure"],
              "managed": ["PreToolUse", "PermissionRequest", "PostToolUseFailure"],
              "conflict": ["PermissionRequest", "PermissionRequest", "PostToolUseFailure"]}[kind]
    data = {"hooks": {}}
    for event in events:
        data["hooks"].setdefault(event, []).append({"matcher": "*", "hooks": [{"type": "command", "command": h.get_adapter_hook_commands(str(ROOT))[event]}]})
    if kind != "absent":
        path.write_text(json.dumps(data))
    health.main(["--installed-dir", str(ROOT), "--settings-path", str(path), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]
    check = next(c for c in checks if c["name"] == "Hook Registration File Inventory")
    assert check["passed"] is passed
    assert json.loads(check["detail"])["connected_mode"] == kind


def test_default_repairs_single_presentation_hook_without_execution_hook(tmp_path):
    path = tmp_path / "settings.json"
    data = {"hooks": {"PermissionRequest": [{"matcher": "*", "hooks": [
        {"type": "command", "command": h.get_adapter_hook_commands(str(ROOT))["PermissionRequest"], "timeout": 123}]}]}}
    path.write_text(json.dumps(data))
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    after = json.loads(path.read_text())
    assert set(after["hooks"]) == {"PermissionRequest", "PostToolUseFailure"}
    assert after["hooks"]["PermissionRequest"] == data["hooks"]["PermissionRequest"]


@pytest.mark.parametrize("managed", [False, True])
def test_cli_preview_is_read_only_and_shows_selected_hooks(tmp_path, managed):
    path = tmp_path / "settings.json"
    proc = subprocess.run([sys.executable, "-B", str(ROOT / "bin/ume-harness"), "setup", "--preview", "--settings-path", str(path)] + (["--managed"] if managed else []),
                          env=dict(os.environ, HOME=str(tmp_path)), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert ("pretooluse_hook.py" in proc.stdout) is managed
    assert "permission_request_hook.py" in proc.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("event", ["PreToolUse", "PermissionRequest", "PostToolUseFailure"])
def test_duplicate_any_owned_event_is_conflict(tmp_path, event):
    commands = h.get_adapter_hook_commands(str(ROOT))
    data = {"hooks": {name: [{"matcher": "*", "hooks": [{"type": "command", "command": command}]}] for name, command in commands.items()}}
    data["hooks"][event].append(copy.deepcopy(data["hooks"][event][0]))
    assert h.inspect_hook_registrations(data, str(ROOT), settings_path="fixture")["connected_mode"] == "conflict"


def test_new_presentation_hooks_have_short_native_timeout(tmp_path):
    path = tmp_path / "settings.json"
    ok, message = h.install_hooks_to_settings(str(ROOT), str(path), managed=True)
    assert ok, message
    data = json.loads(path.read_text())
    for event in ("PermissionRequest", "PostToolUseFailure"):
        assert data["hooks"][event][0]["hooks"][0]["timeout"] == 3
    assert "timeout" not in data["hooks"]["PreToolUse"][0]["hooks"][0]


def test_standard_result_disclaims_semantic_authority(tmp_path):
    path = tmp_path / "settings.json"
    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))
    assert ok
    assert "Lease・path制限を強制しません" in message
    assert "依頼範囲" in message and "保証しません" in message
    assert "権限設定は変更しません" in message


def test_default_result_identifies_preserved_managed_connection(tmp_path):
    path = tmp_path / "settings.json"
    assert h.install_hooks_to_settings(str(ROOT), str(path), managed=True)[0]
    before = path.read_bytes()
    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))
    assert ok
    assert "説明だけには移行していません" in message
    assert "--disconnect" in message
    assert path.read_bytes() == before


def test_existing_timeout_is_preserved_and_reported_not_normalized(tmp_path):
    path = tmp_path / "settings.json"
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    data = json.loads(path.read_text())
    data["hooks"]["PermissionRequest"][0]["hooks"][0].pop("timeout", None)
    data["hooks"]["PostToolUseFailure"][0]["hooks"][0]["timeout"] = 123
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))
    assert ok and path.read_bytes() == before
    assert "既存timeout" in message and "未確認" in message


def test_inventory_separates_file_session_and_actual_event(tmp_path):
    path = tmp_path / "settings.json"
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    report = h.inspect_settings_file(str(path), str(ROOT))
    assert report["connected_mode"] == "presentation"
    assert report["session_hook_recognition"] == "unknown"
    assert report["actual_hook_event"] == "unknown"


def test_setup_conflict_is_reported_without_mutation(tmp_path):
    path = tmp_path / "settings.json"
    assert h.install_hooks_to_settings(str(ROOT), str(path), managed=True)[0]
    data = json.loads(path.read_text())
    data["hooks"]["PreToolUse"].append(copy.deepcopy(data["hooks"]["PreToolUse"][0]))
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))
    assert not ok
    assert "conflict" in message and "変更していません" in message
    assert path.read_bytes() == before


@pytest.mark.parametrize("event", ["PermissionRequest", "PostToolUseFailure"])
@pytest.mark.parametrize("timeout", [None, 123], ids=["absent-timeout", "custom-timeout"])
def test_legacy_command_normalization_preserves_entry_and_group(tmp_path, event, timeout):
    root = tmp_path / "package with spaces"
    paths = h.get_adapter_hook_paths(str(root))
    for hook_path in paths.values():
        target = Path(hook_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# synthetic hook fixture\n")
    commands = h.get_adapter_hook_commands(str(root))
    entry = {"type": "command", "command": paths[event], "statusMessage": "custom status"}
    if timeout is not None:
        entry["timeout"] = timeout
    unrelated = {"type": "command", "command": "/user/custom", "timeout": 9}
    data = {
        "permissions": {"defaultMode": "default"},
        "hooks": {
            name: [{"matcher": "*", "hooks": [{"type": "command", "command": commands[name]}]}]
            for name in ("PermissionRequest", "PostToolUseFailure")
        },
    }
    data["hooks"][event] = [{"matcher": "Read", "custom_metadata": "preserve",
                             "hooks": [unrelated, entry]}]
    # Even an exact path in a different event is outside normalization ownership.
    data["hooks"]["Stop"] = [{"hooks": [copy.deepcopy(entry)]}]
    expected = copy.deepcopy(data)
    expected["hooks"][event][0]["hooks"][1]["command"] = commands[event]
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))

    ok, message = h.install_hooks_to_settings(str(root), str(path))
    assert ok, message
    assert json.loads(path.read_text()) == expected
    assert "既存timeout" in message

    before = path.read_bytes()
    files = sorted(tmp_path.iterdir())
    assert h.install_hooks_to_settings(str(root), str(path))[0]
    assert path.read_bytes() == before
    assert sorted(tmp_path.iterdir()) == files
