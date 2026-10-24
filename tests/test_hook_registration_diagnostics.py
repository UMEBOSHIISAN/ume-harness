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
    command = h.get_retired_hook_commands(str(root))["PreToolUse"]
    foreign = str(tmp_path / "ume-harness/v1.2.2/adapters/claude-code/pretooluse_hook.py")
    data = settings(command, command, foreign)
    before = copy.deepcopy(data)
    report = h.inspect_hook_registrations(data, str(root), settings_path=str(tmp_path / ".claude/settings.json"))
    assert data == before
    assert report["findings"] == []
    assert [r["retired"] for r in report["registrations"]] == [True, True, False]
    assert report["live_effective_settings"] == "unknown"
    assert report["matcher_overlap"] == "not evaluated"
    assert report["connected_mode"] == "legacy_hold"
    assert report["additional_host_controls"]


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
    data = settings(h.get_retired_hook_commands(str(tmp_path / "with space"))["PreToolUse"])
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert h.inspect_settings_file(str(path), str(tmp_path / "with space"))["registrations"][0]["retired"]
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


@pytest.mark.parametrize("mode,expected", [
    ("absent", True), ("disconnected", True), ("presentation", True),
    ("managed", False), ("legacy_hold", False), ("unknown", False),
])
def test_health_explicit_inventory_after_identity(tmp_path, monkeypatch, capsys, mode, expected):
    monkeypatch.setattr(health, "verify_release_identity", lambda _: (True, "fixture verified"))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="IMPORT_OK" if len(calls) == 1 else json.dumps({"scope": "file inventory only", "connected_mode": mode, "findings": []}), stderr="")
    monkeypatch.setattr(health.subprocess, "run", run)
    health.main(["--installed-dir", str(tmp_path), "--settings-path", str(tmp_path / "settings.json"), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert len(calls) == 2
    assert calls[1][-2:] == [str(tmp_path / "settings.json"), str(tmp_path)]
    assert next(c for c in checks if c["name"] == "Hook Registration File Inventory")["passed"] is expected


def test_retired_state_option_rejected_before_diagnostics(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("retired option must stop before inspecting any state or package")
    monkeypatch.setattr(health, "run_diagnostics", forbidden)
    with pytest.raises(SystemExit) as exc:
        health.main(["--state-dir", "/nonexistent/retired-state"])
    assert exc.value.code == 2
    assert "unrecognized arguments: --state-dir" in capsys.readouterr().err


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


def test_cli_setup_and_disconnect_preserve_unrelated(tmp_path):
    path = tmp_path / "settings.json"
    initial = {"theme": "dark", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/user/stop"}]}]}}
    path.write_text(json.dumps(initial))
    env = dict(os.environ, HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1",
               PATH=os.environ.get("PATH", ""))
    args = [sys.executable, "-B", str(ROOT / "bin/ume-harness"), "setup", "--settings-path", str(path)]
    proc = subprocess.run(args + ["--yes"], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(path.read_text())
    assert set(data["hooks"]) == {"Stop", "PermissionRequest", "PostToolUseFailure"}
    proc = subprocess.run(args + ["--disconnect"], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(path.read_text()) == initial


@pytest.mark.parametrize("events,mode", [
    ([], "disconnected"), (["PermissionRequest"], "partial"),
    (["PermissionRequest", "PostToolUseFailure"], "presentation"),
    (["PreToolUse", "PermissionRequest", "PostToolUseFailure"], "legacy_hold"),
    (["PermissionRequest", "PermissionRequest", "PostToolUseFailure"], "conflict"),
])
def test_inventory_connected_mode(tmp_path, events, mode):
    commands = dict(h.get_adapter_hook_commands(str(ROOT)))
    commands.update(h.get_retired_hook_commands(str(ROOT)))
    data = {"hooks": {}}
    for event in events:
        data["hooks"].setdefault(event, []).append({"matcher": "*", "hooks": [{"type": "command", "command": commands[event]}]})
    report = h.inspect_hook_registrations(data, str(ROOT), settings_path=str(tmp_path / "settings.json"))
    assert report["connected_mode"] == mode
    assert report["live_effective_settings"] == "unknown"
    assert h.inspect_settings_file(str(tmp_path / "missing.json"), str(ROOT))["connected_mode"] == "absent"


@pytest.mark.parametrize("kind,passed", [("absent", True), ("disconnected", True), ("presentation", True), ("legacy_hold", False), ("partial", False), ("conflict", False)])
def test_health_registration_uses_real_inventory(tmp_path, monkeypatch, capsys, kind, passed):
    monkeypatch.setattr(health, "verify_release_identity", lambda _: (True, "isolated source fixture"))
    path = tmp_path / "settings.json"
    events = {"absent": [], "disconnected": [], "partial": ["PermissionRequest"],
              "presentation": ["PermissionRequest", "PostToolUseFailure"],
              "legacy_hold": ["PreToolUse", "PermissionRequest", "PostToolUseFailure"],
              "conflict": ["PermissionRequest", "PermissionRequest", "PostToolUseFailure"]}[kind]
    data = {"hooks": {}}
    commands = dict(h.get_adapter_hook_commands(str(ROOT)))
    commands.update(h.get_retired_hook_commands(str(ROOT)))
    for event in events:
        data["hooks"].setdefault(event, []).append({"matcher": "*", "hooks": [{"type": "command", "command": commands[event]}]})
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


def test_cli_preview_is_read_only_and_shows_selected_hooks(tmp_path):
    path = tmp_path / "settings.json"
    proc = subprocess.run([sys.executable, "-B", str(ROOT / "bin/ume-harness"), "setup", "--preview", "--settings-path", str(path)],
                          env=dict(os.environ, HOME=str(tmp_path)), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "pretooluse_hook.py" not in proc.stdout
    assert "permission_request_hook.py" in proc.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("event", ["PermissionRequest", "PostToolUseFailure"])
def test_duplicate_any_owned_event_is_conflict(tmp_path, event):
    commands = h.get_adapter_hook_commands(str(ROOT))
    data = {"hooks": {name: [{"matcher": "*", "hooks": [{"type": "command", "command": command}]}] for name, command in commands.items()}}
    data["hooks"][event].append(copy.deepcopy(data["hooks"][event][0]))
    assert h.inspect_hook_registrations(data, str(ROOT), settings_path="fixture")["connected_mode"] == "conflict"


def test_new_presentation_hooks_have_short_native_timeout(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))
    assert ok, message
    data = json.loads(path.read_text())
    for event in ("PermissionRequest", "PostToolUseFailure"):
        assert data["hooks"][event][0]["hooks"][0]["timeout"] == 3


def test_standard_result_disclaims_semantic_authority(tmp_path):
    path = tmp_path / "settings.json"
    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))
    assert ok
    assert "追加実行制限やpath制限を強制しません" in message
    assert "依頼範囲" in message and "保証しません" in message
    assert "権限設定は変更しません" in message


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


def test_setup_conflict_is_reported_without_mutation(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    data = json.loads(path.read_text())
    data["hooks"]["PermissionRequest"].append(copy.deepcopy(data["hooks"]["PermissionRequest"][0]))
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


def test_managed_retirement_is_stable_and_side_effect_free(tmp_path, monkeypatch):
    """A retired managed request must stop before host checks, path reads, or locks."""
    monkeypatch.setattr(h, "get_default_settings_path",
                        lambda: pytest.fail("retired managed setup must not resolve a default path"))
    monkeypatch.setattr(h, "_read_settings_snapshot",
                        lambda *args, **kwargs: pytest.fail("retired managed setup must not inspect settings"))
    monkeypatch.setattr(h, "_install_hooks_to_settings_locked",
                        lambda *args, **kwargs: pytest.fail("retired managed setup must not enter the writer"))
    settings_path = tmp_path / "new" / "settings.json"

    ok, message = h.install_hooks_to_settings(str(ROOT), str(settings_path), managed=True)

    assert not ok
    assert message == "managed setup is retired; disconnect the old connection with its old CLI, then run setup without --managed"
    assert not settings_path.parent.exists()
    assert not Path(str(settings_path) + ".ume-harness.lock").exists()


def test_same_root_retired_pretooluse_holds_setup_before_lock_without_script(tmp_path):
    """A same-root retired entry is held even when its old payload is absent."""
    root = tmp_path / "old-prefix"
    adapter = root / "adapters" / "claude-code"
    adapter.mkdir(parents=True)
    for filename in ("permission_request_hook.py", "posttooluse_failure_hook.py"):
        (adapter / filename).write_text("# presentation fixture\n")
    retired = str(adapter / "pretooluse_hook.py")
    settings_path = tmp_path / "new" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": retired}]}]
    }}))
    before = settings_path.read_bytes()

    ok, message = h.install_hooks_to_settings(str(root), str(settings_path))

    assert not ok
    assert "old CLI" in message and "--disconnect" in message
    assert settings_path.read_bytes() == before
    assert not Path(str(settings_path) + ".ume-harness.lock").exists()


def test_locked_writer_holds_if_retired_entry_appears_after_preflight(tmp_path, monkeypatch):
    """The writer rechecks retirement after acquiring the settings lock."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": {}}))
    original = h.inspect_hook_registrations
    calls = []

    def racing_inventory(data, pkg_root, *, settings_path):
        inventory = original(data, pkg_root, settings_path=settings_path)
        calls.append(inventory)
        if len(calls) == 2:
            inventory["retired_pretooluse"] = True
        return inventory

    monkeypatch.setattr(h, "inspect_hook_registrations", racing_inventory)
    before = path.read_bytes()

    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))

    assert not ok
    assert "old CLI" in message and "--disconnect" in message
    assert len(calls) == 2
    assert path.read_bytes() == before


def test_disconnect_removes_same_root_retired_pretooluse_without_old_script(tmp_path):
    """Explicit disconnect can remove only the exact retired entry after migration."""
    root = tmp_path / "old-prefix"
    adapter = root / "adapters" / "claude-code"
    adapter.mkdir(parents=True)
    for filename in ("permission_request_hook.py", "posttooluse_failure_hook.py"):
        (adapter / filename).write_text("# presentation fixture\n")
    retired = str(adapter / "pretooluse_hook.py")
    foreign = {"type": "command", "command": "/user/foreign-pretooluse"}
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": retired}, foreign]}]
    }}))

    ok, message = h.disconnect_hooks_from_settings(str(root), str(settings_path))

    assert ok, message
    after = json.loads(settings_path.read_text())
    assert after["hooks"]["PreToolUse"][0]["hooks"] == [foreign]
    assert retired not in settings_path.read_text()


def test_fresh_setup_registers_only_two_presentation_hooks(tmp_path):
    path = tmp_path / "settings.json"

    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))

    assert ok, message
    data = json.loads(path.read_text())
    assert set(data["hooks"]) == {"PermissionRequest", "PostToolUseFailure"}
    assert all(
        event_hooks[0]["hooks"][0]["timeout"] == 3
        for event_hooks in (data["hooks"]["PermissionRequest"], data["hooks"]["PostToolUseFailure"])
    )


def test_foreign_pretooluse_is_preserved_and_reported_as_unknown_host_control(tmp_path):
    path = tmp_path / "settings.json"
    foreign_command = str(tmp_path / "other-prefix" / "adapters" / "claude-code" / "pretooluse_hook.py")
    initial = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": foreign_command}]}]}}
    path.write_text(json.dumps(initial))

    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))

    assert ok, message
    data = json.loads(path.read_text())
    assert any(item["command"] == foreign_command
               for group in data["hooks"]["PreToolUse"] for item in group["hooks"])
    assert "他の設定" in message and "未確認" in message


def test_existing_presentation_timeout_metadata_is_byte_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    assert h.install_hooks_to_settings(str(ROOT), str(path))[0]
    data = json.loads(path.read_text())
    data["hooks"]["PermissionRequest"][0]["hooks"][0].pop("timeout")
    data["hooks"]["PostToolUseFailure"][0]["hooks"][0]["timeout"] = 123
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    before = path.read_bytes()

    ok, message = h.install_hooks_to_settings(str(ROOT), str(path))

    assert ok, message
    assert path.read_bytes() == before
    assert "既存timeout" in message and "未確認" in message
