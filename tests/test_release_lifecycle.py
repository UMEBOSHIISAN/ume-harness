#!/usr/bin/env python3
"""Final-freeze regressions for release identity, lifecycle, and one-way promotion."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERSION = "v0.1.0"
CANONICAL_REPOSITORY = "https://github.com/UMEBOSHIISAN/ume-harness-engineering.git"
PUBLIC_MIRROR_REPOSITORY = "https://github.com/UMEBOSHIISAN/ume-harness.git"
OWNED_EVENTS = ("PreToolUse", "PermissionRequest", "PostToolUseFailure")


def _run(args, *, env=None, cwd=ROOT, input=None):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        input=input,
    )


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _commands(settings: dict, event: str) -> list[str]:
    return [
        hook.get("command", "")
        for group in settings.get("hooks", {}).get(event, [])
        for hook in group.get("hooks", [])
        if isinstance(hook, dict)
    ]


def _install(temp_root: Path):
    home = temp_root / "home"
    prefix = temp_root / "prefix"
    home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    proc = _run(["bash", ROOT / "scripts/install.sh", "--prefix", prefix], env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return home, prefix, env


def _initial_settings(temp_root: Path) -> dict:
    return {
        "theme": "dark",
        "custom": {"nested": [1, 2, 3]},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [
                        {
                            "type": "command",
                            "command": str(temp_root / "my-ume-harness-helper" / "read.py"),
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": "/opt/custom/stop.py"}],
                }
            ],
        },
    }


def test_release_identity_is_explicit_and_detects_tampered_bytes():
    manifest = _read_json(ROOT / "package_manifest.json")
    identity = manifest["release_identity"]
    required = {
        "runtime/translation_konjac.py",
        "runtime/hook_setup_service.py",
        "adapters/claude-code/pretooluse_hook.py",
        "adapters/claude-code/permission_request_hook.py",
        "adapters/claude-code/posttooluse_failure_hook.py",
        "runtime/common_language_pack.py",
        "common-language/packs/ja-JP/p0_concepts.json",
        "common-language/schema/concept_pack.schema.json",
    }
    assert required <= set(identity["closure"])

    health = _load_module(ROOT / "scripts/health_check.py", "health_check_under_test")
    actual = health.calculate_release_identity(str(ROOT), identity["closure"])
    assert actual == health.EXPECTED_ROOT_DIGEST

    with tempfile.TemporaryDirectory() as td:
        home, prefix, env = _install(Path(td))
        installed = prefix / "lib/ume-harness" / VERSION
        clean = _run(
            [sys.executable, installed / "scripts/health_check.py", "--installed-dir", installed, "--prefix", prefix, "--json"],
            env=env,
        )
        assert clean.returncode == 0, clean.stdout + clean.stderr

        permission_hook = installed / "adapters/claude-code/permission_request_hook.py"
        original_mode = permission_hook.stat().st_mode
        permission_hook.chmod(original_mode & ~0o111)
        non_executable = _run(
            [sys.executable, installed / "scripts/health_check.py", "--installed-dir", installed, "--prefix", prefix, "--json"],
            env=env,
        )
        assert non_executable.returncode != 0
        executable_check = next(
            c for c in json.loads(non_executable.stdout)["checks"]
            if c["name"] == "Claude Hook Executability"
        )
        assert executable_check["passed"] is False
        permission_hook.chmod(original_mode)

        with (installed / "runtime/translation_konjac.py").open("ab") as f:
            f.write(b"\n# tamper regression probe\n")
        tampered = _run(
            [sys.executable, installed / "scripts/health_check.py", "--installed-dir", installed, "--prefix", prefix, "--json"],
            env=env,
        )
        assert tampered.returncode != 0
        result = json.loads(tampered.stdout)
        identity_check = next(c for c in result["checks"] if c["name"] == "Release Byte Identity")
        assert identity_check["passed"] is False
        assert "expected=" in identity_check["detail"]
        assert "actual=" in identity_check["detail"]


def test_release_identity_rejects_symlinked_closure_directories():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        external_runtime = temp_root / "external-runtime"
        (installed / "runtime").rename(external_runtime)
        (installed / "runtime").symlink_to(external_runtime, target_is_directory=True)

        checked = _run(
            [
                sys.executable,
                installed / "scripts/health_check.py",
                "--installed-dir",
                installed,
                "--identity-only",
            ],
            env=env,
        )

        assert checked.returncode != 0
        assert "symlink" in (checked.stdout + checked.stderr).lower()


def test_fresh_settings_setup_then_disconnect_succeeds_without_unrelated_state():
    sys.path.insert(0, str(ROOT / "runtime"))
    import hook_setup_service as hss

    with tempfile.TemporaryDirectory() as td:
        settings_path = Path(td) / ".claude/settings.json"
        assert not settings_path.exists()
        connected, connect_message = hss.install_hooks_to_settings(str(ROOT), str(settings_path))
        assert connected, connect_message
        disconnected, disconnect_message = hss.disconnect_hooks_from_settings(str(ROOT), str(settings_path))
        assert disconnected, disconnect_message
        data = _read_json(settings_path)
        assert hss.contains_owned_hooks(data, str(ROOT)) is False


def test_disconnect_fails_closed_when_settings_cannot_be_read():
    sys.path.insert(0, str(ROOT / "runtime"))
    import hook_setup_service as hss

    with tempfile.TemporaryDirectory() as td:
        protected = Path(td) / "protected"
        settings_path = protected / "settings.json"
        _write_json(settings_path, {"hooks": {}})
        protected.chmod(0)
        try:
            disconnected, message = hss.disconnect_hooks_from_settings(str(ROOT), str(settings_path))
            assert disconnected is False
            assert "読み込みに失敗" in message
        finally:
            protected.chmod(0o700)

        target = Path(td) / "target.json"
        link = Path(td) / "settings-link.json"
        original_target = {"theme": "dark", "hooks": {}}
        _write_json(target, original_target)
        link.symlink_to(target)
        connected, connect_message = hss.install_hooks_to_settings(str(ROOT), str(link))
        assert connected is False
        assert "symlink" in connect_message
        assert link.is_symlink()
        assert _read_json(target) == original_target


@pytest.mark.parametrize(
    "command_template",
    (
        'printf "%s\\n" "user\'s hook"',
        'echo bash -c "user\'s hook"',
        "python3 {pkg_root}-backup/user-hook.py",
        "python3 /backup{pkg_root}/user-hook.py",
        "python3 /backup:{pkg_root}/user-hook.py",
        "PATH=/usr/bin: python3 /backup:{pkg_root}/user-hook.py",
        "PATH=/usr/bin: python3 /backup:{pkg_root}/adapters/claude-code/user-hook.py",
        "echo PATH=\"/tmp/a b:{pkg_root}/user-hook.py\"",
        "env -- echo 'PATH=/tmp/a b:{pkg_root}/user-hook.py'",
        "echo $(true)PATH=\"/tmp/a b:{pkg_root}/user-hook.py\"",
        "PATH=/usr/bin /opt/custom/my-pretooluse_hook.py",
        "PATH=/usr/bin printf '%s\\n' pretooluse_hook.py",
        "PATH=/opt/custom:/usr/bin pretooluse_hook.py",
        "FOO=/opt/pkg/adapters/claude-code printf '%s\\n' pretooluse_hook.py",
        "LOG_DIR=/opt/pkg/adapters/claude-code echo pretooluse_hook.py",
        "env FOO=/opt/pkg/adapters/claude-code printf '%s' pretooluse_hook.py",
        "bash -c \"echo ok # user's hook\"",
    ),
)
def test_dangling_hook_check_accepts_unrelated_quoted_literal_with_apostrophe(command_template):
    hss = _load_module(
        ROOT / "runtime/hook_setup_service.py",
        "hook_setup_unrelated_quoted_literal",
    )
    pkg_root = Path("/opt/pkg")
    data = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command_template.format(pkg_root=pkg_root),
                        }
                    ],
                }
            ]
        }
    }

    assert hss.contains_noncanonical_hook_reference(data, str(pkg_root)) is False


@pytest.mark.parametrize(
    "command_template",
    (
        "env -u FOO bash -c 'python3 {hook}'",
        "bash --rcfile /dev/null -c 'python3 {hook}'",
        "true\nbash -c 'python3 {hook}'",
        "sudo bash -c 'python3 {hook}'",
        "$SHELL -c 'python3 {hook}'",
        "bash -c 'python3 {home_hook}'",
        "bash -c \"python3 {spliced_hook}\"",
        "cd {pkg_root} && python3 adapters/claude-code/pretooluse_hook.py",
        "python3 \"${{HOOK:-{hook}}}\"",
        "PATH=/usr/bin:{adapter_dir}:$PATH pretooluse_hook.py",
        "PATH+=:{adapter_dir}; pretooluse_hook.py",
        "PATH=\"$(printf /usr/bin):{adapter_dir}\"; pretooluse_hook.py",
        "PATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "bash -c 'export PATH=/usr/bin:{adapter_dir}:$PATH; pretooluse_hook.py'",
        "PATH=$(printf /usr/bin):{adapter_dir}:$PATH pretooluse_hook.py",
        "FOO=1 PATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "bash -lc 'PATH=\"/tmp/a b:{adapter_dir}:$PATH\"; pretooluse_hook.py'",
        "sudo -u root bash -c 'PATH=\"/tmp/a b:{adapter_dir}:$PATH\"; pretooluse_hook.py'",
        "FOO=$(true); PATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "echo ok\nPATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "env -- PATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "echo $(PATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py)",
        ">/dev/null PATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "FOO=1 env PATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "exec bash -c 'PATH=\"/tmp/a b:{adapter_dir}:$PATH\"; pretooluse_hook.py'",
        "bash -O extglob -c 'PATH=\"/tmp/a b:{adapter_dir}:$PATH\"; pretooluse_hook.py'",
        "if true; then PATH=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py; fi",
        "cat <<'EOF'\nPATH=\"/tmp/a b:{adapter_dir}:$PATH\"\nEOF",
        "'PATH=/tmp/a b:{adapter_dir}:$PATH' true",
        "1PATH=\"/tmp/a b:{adapter_dir}:$PATH\" true",
        "bash -c 'true' arg0 -c 'PATH=\"/tmp/a b:{adapter_dir}:$PATH\"; pretooluse_hook.py'",
        "bash /dev/null -c 'PATH=\"/tmp/a b:{adapter_dir}:$PATH\"; pretooluse_hook.py'",
        "PATH=\"/tmp;x:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "PATH=\"$(printf :){adapter_dir}:$PATH\" pretooluse_hook.py",
        "PATH=\"{pkg_root}/adapters/../adapters/claude-code:$PATH\" pretooluse_hook.py",
        "PATH=\"/tmp/a b:{empty_var_adapter_dir}:$PATH\" pretooluse_hook.py",
        "PATH=$( (printf /usr/bin); true ):{adapter_dir}:$PATH pretooluse_hook.py",
        "env -u JOIN bash -c 'PATH=\"/tmp/a b:{pkg_parent}/${{JOIN:-pkg}}/adapters/claude-code:$PATH\" pretooluse_hook.py'",
        "env P\"AT\"H=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "env \"PATH=/tmp/a\\\" b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "PATH=\"/tmp/a b:{empty_var_adapter_dir}:$PATH\" pretooluse_${{UME_HARNESS_EMPTY_PATH_SEGMENT}}hook.py",
        "env P$'AT'H=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "env P$(printf AT)H=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "env P`printf AT`H=\"/tmp/a b:{adapter_dir}:$PATH\" pretooluse_hook.py",
        "PATH=\"/tmp/a b:/{adapter_dir}:/usr/bin:/bin\" pretooluse_hook.py",
        "PATH=\"/tmp/a b:{username_adapter_dir}:/usr/bin:/bin\" pretooluse_hook.py",
        "PATH=\"/tmp/a b:{continued_adapter_dir}:/usr/bin:/bin\" pretooluse_hook.py",
        "PATH=\"/tmp/a b:\"$'{adapter_dir}'\":/usr/bin:/bin\" pretooluse_hook.py",
        r"""PATH="/tmp/a b:"$'\x2f{adapter_no_leading_slash}'":/usr/bin:/bin" pretooluse_hook.py""",
        "env PATH=\"/tmp/a b:{brace_adapter_prefix}\"{{c..c}}\"ode:/usr/bin:/bin\" pretooluse_hook.py",
        "env PATH={padded_brace_adapter_dir} pretooluse_hook.py",
        "env PATH={plus_brace_adapter_dir} pretooluse_hook.py",
        "HOOK={hook} bash -c 'python3 \"$HOOK\"'",
        r"""HOOK=$'\x2f{hook_no_leading_slash}' bash -c 'python3 "$HOOK"'""",
        "env HOOK={hook} bash -c 'python3 \"$HOOK\"'",
        "env H$'OO'K={hook} bash -c 'python3 \"$HOOK\"'",
        "env H$(printf OO)K={hook} bash -c 'python3 \"$HOOK\"'",
        "env H`printf OO`K={hook} bash -c 'python3 \"$HOOK\"'",
        "env H${{UME_HARNESS_EMPTY_PATH_SEGMENT}}OOK={hook} bash -c 'python3 \"$HOOK\"'",
        "env $(printf HOOK)={hook} bash -c 'python3 \"$HOOK\"'",
        "env NAME=HOOK HOOK={hook} bash -c 'python3 \"${{!NAME}}\"'",
        "HOOK={hook} bash -c 'python3 \"${{HOOK%}}\"'",
        "HOOK={hook} bash -c 'python3 \"${{HOOK#}}\"'",
        "HOOK={hook} bash -c 'python3 \"${{HOOK/nomatch/other}}\"'",
        "python3 \"${{@:-{hook}}}\"",
        "python3 \"${{*:-{hook}}}\"",
    ),
)
def test_dangling_hook_check_rejects_shell_dispatch_forms(command_template, monkeypatch):
    hss = _load_module(
        ROOT / "runtime/hook_setup_service.py",
        "hook_setup_shell_dispatch_forms",
    )
    pkg_root = Path.home() / ".local/lib/ume-harness/v0.1.0"
    hook = hss.get_adapter_hook_paths(str(pkg_root))["PreToolUse"]
    home_hook = "~" + hook[len(str(Path.home())):]
    spliced_hook = hook.replace("ume-harness", "ume-'harness'", 1)
    empty_variable = "UME_HARNESS_EMPTY_PATH_SEGMENT"
    monkeypatch.delenv(empty_variable, raising=False)
    empty_var_adapter_dir = str(Path(hook).parent).replace(
        "claude-code",
        f"${{{empty_variable}}}claude-code",
    )
    username_adapter_dir = str(Path(hook).parent).replace(
        str(Path.home()),
        f"~{Path.home().name}",
        1,
    )
    continued_adapter_dir = str(Path(hook).parent).replace(
        "claude-code",
        "claude-\\\ncode",
    )
    adapter_no_leading_slash = str(Path(hook).parent).lstrip("/")
    brace_adapter_prefix = str(Path(hook).parent).replace("claude-code", "claude-")
    padded_brace_adapter_dir = str(Path(hook).parent).replace(
        "v0.1.0",
        "v{0..00}.1.0",
    )
    plus_brace_adapter_dir = str(Path(hook).parent).replace(
        "v0.1.0",
        "v{+0..+0}.1.0",
    )
    hook_no_leading_slash = hook.lstrip("/")
    data = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command_template.format(
                                hook=hook,
                                home_hook=home_hook,
                                spliced_hook=spliced_hook,
                                pkg_root=pkg_root,
                                pkg_parent=pkg_root.parent,
                                adapter_dir=Path(hook).parent,
                                empty_var_adapter_dir=empty_var_adapter_dir,
                                username_adapter_dir=username_adapter_dir,
                                continued_adapter_dir=continued_adapter_dir,
                                adapter_no_leading_slash=adapter_no_leading_slash,
                                brace_adapter_prefix=brace_adapter_prefix,
                                padded_brace_adapter_dir=padded_brace_adapter_dir,
                                plus_brace_adapter_dir=plus_brace_adapter_dir,
                                hook_no_leading_slash=hook_no_leading_slash,
                            ),
                        }
                    ],
                }
            ]
        }
    }

    assert hss.contains_noncanonical_hook_reference(data, str(pkg_root)) is True


def test_dangling_hook_check_rejects_symlinked_adapter_path(tmp_path):
    hss = _load_module(
        ROOT / "runtime/hook_setup_service.py",
        "hook_setup_symlinked_adapter_path",
    )
    pkg_root = tmp_path / "pkg"
    adapter_dir = pkg_root / "adapters" / "claude-code"
    adapter_dir.mkdir(parents=True)
    adapter_link = tmp_path / "adapter-link"
    adapter_link.symlink_to(adapter_dir, target_is_directory=True)
    data = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                f'PATH="/tmp/a b:{adapter_link}:/usr/bin:/bin" '
                                "pretooluse_hook.py"
                            ),
                        }
                    ],
                }
            ]
        }
    }

    assert hss.contains_noncanonical_hook_reference(data, str(pkg_root)) is True


def test_dangling_hook_check_fails_closed_for_deeply_nested_shell_text():
    hss = _load_module(
        ROOT / "runtime/hook_setup_service.py",
        "hook_setup_nested_depth_limit",
    )
    pkg_root = Path.home() / ".local/lib/ume-harness/v0.1.0"
    adapter_dir = Path(hss.get_adapter_hook_paths(str(pkg_root))["PreToolUse"]).parent
    command = f'PATH="/tmp/a b:{adapter_dir}:$PATH" pretooluse_hook.py'
    for _ in range(5):
        command = f"bash -c {shlex.quote(command)}"
    data = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": command}],
                }
            ]
        }
    }

    assert hss.contains_noncanonical_hook_reference(data, str(pkg_root)) is True


def test_setup_reconnect_preserves_customized_owned_hook_fields_and_file_bytes():
    sys.path.insert(0, str(ROOT / "runtime"))
    import hook_setup_service as hss

    with tempfile.TemporaryDirectory() as td:
        settings_path = Path(td) / ".claude/settings.json"
        connected, message = hss.install_hooks_to_settings(str(ROOT), str(settings_path))
        assert connected, message

        data = _read_json(settings_path)
        owned = hss.get_adapter_hook_paths(str(ROOT))["PreToolUse"]
        group = next(
            group for group in data["hooks"]["PreToolUse"]
            if any(item.get("command") == owned for item in group["hooks"])
        )
        group["matcher"] = "Bash"
        owned_item = next(item for item in group["hooks"] if item.get("command") == owned)
        owned_item["timeout"] = 999
        owned_item["statusMessage"] = "custom"
        _write_json(settings_path, data)
        before = settings_path.read_bytes()

        reconnected, reconnect_message = hss.install_hooks_to_settings(str(ROOT), str(settings_path))
        assert reconnected, reconnect_message
        assert settings_path.read_bytes() == before
        after = _read_json(settings_path)
        preserved = next(
            group for group in after["hooks"]["PreToolUse"]
            if any(item.get("command") == owned for item in group["hooks"])
        )
        assert preserved["matcher"] == "Bash"
        item = next(item for item in preserved["hooks"] if item.get("command") == owned)
        assert item["timeout"] == 999
        assert item["statusMessage"] == "custom"


def _write_user_owned_cli(temp_root: Path, prefix: Path, *, symlink: bool):
    wrapper = prefix / "bin/ume-harness"
    wrapper.parent.mkdir(parents=True)
    original = b"#!/usr/bin/env bash\n# user-owned ume-harness notes\nexit 0\n"
    target = wrapper
    if symlink:
        target = temp_root / "outside-user-launcher"
        target.write_bytes(original)
        wrapper.symlink_to(target)
    else:
        wrapper.write_bytes(original)
    return wrapper, target, original


def test_rendered_cli_wrapper_does_not_expand_shell_metacharacters_in_prefix():
    hss = _load_module(ROOT / "runtime/hook_setup_service.py", "hook_setup_wrapper_quoting")
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        marker = temp_root / "unexpected-side-effect"
        pkg_root = temp_root / "prefix-$(touch unexpected-side-effect)"
        cli = pkg_root / "bin/ume-harness"
        wrapper = temp_root / "ume-harness-wrapper"
        cli.parent.mkdir(parents=True)
        cli.write_text("print('WRAPPER_OK')\n", encoding="utf-8")
        wrapper.write_text(hss.render_cli_wrapper(str(pkg_root)), encoding="utf-8")

        invoked = _run(["bash", wrapper], cwd=temp_root)

        assert invoked.returncode == 0, invoked.stdout + invoked.stderr
        assert invoked.stdout.strip() == "WRAPPER_OK"
        assert not marker.exists()


@pytest.mark.parametrize("symlink", (False, True), ids=("regular", "symlink"))
def test_install_refuses_user_owned_cli_without_touching_its_bytes(symlink):
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home = temp_root / "home"
        prefix = temp_root / "prefix"
        home.mkdir()
        wrapper, target, original = _write_user_owned_cli(temp_root, prefix, symlink=symlink)
        env = os.environ.copy()
        env["HOME"] = str(home)

        args = ["bash", ROOT / "scripts/install.sh", "--prefix", prefix]
        if symlink:
            args.append("--force")
        install = _run(args, env=env)

        assert install.returncode != 0
        assert wrapper.is_symlink() if symlink else wrapper.is_file()
        assert target.read_bytes() == original
        assert not (prefix / "lib/ume-harness" / VERSION).exists()


def test_install_force_refuses_user_owned_regular_cli_without_touching_its_bytes():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home = temp_root / "home"
        prefix = temp_root / "prefix"
        home.mkdir()
        wrapper, target, original = _write_user_owned_cli(temp_root, prefix, symlink=False)
        env = os.environ.copy()
        env["HOME"] = str(home)

        install = _run(
            ["bash", ROOT / "scripts/install.sh", "--prefix", prefix, "--force"],
            env=env,
        )

        assert install.returncode != 0
        assert "Unrelated file" in install.stderr
        assert wrapper.is_file()
        assert target.read_bytes() == original
        assert not (prefix / "lib/ume-harness" / VERSION).exists()


def test_install_preserves_preexisting_predictable_staging_bytes():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home = temp_root / "home"
        prefix = temp_root / "prefix"
        pid_file = temp_root / "installer-shell-pid"
        home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        marker_bytes = b"user-owned staging bytes\n"
        shell = "\n".join(
            (
                "set -eu",
                f"prefix={shlex.quote(str(prefix))}",
                f"pid_file={shlex.quote(str(pid_file))}",
                'staging="$prefix/lib/ume-harness/.staging_$$"',
                'mkdir -p "$staging"',
                f"printf %s {shlex.quote(marker_bytes.decode('utf-8'))} > \"$staging/marker\"",
                'printf %s "$$" > "$pid_file"',
                f"exec bash {shlex.quote(str(ROOT / 'scripts/install.sh'))} --prefix \"$prefix\"",
            )
        )

        install = _run(["bash", "-c", shell], env=env)

        assert install.returncode == 0, install.stdout + install.stderr
        shell_pid = pid_file.read_text(encoding="utf-8")
        marker = prefix / "lib/ume-harness" / f".staging_{shell_pid}" / "marker"
        assert marker.read_bytes() == marker_bytes


def test_install_force_refuses_hardlinked_owned_wrapper_without_touching_shared_inode():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        wrapper = prefix / "bin/ume-harness"
        outside = temp_root / "outside-owned-looking-wrapper"
        original = wrapper.read_bytes()
        payload_marker = installed / "package_manifest.json"
        payload_before = payload_marker.read_bytes()

        outside.write_bytes(original)
        wrapper.unlink()
        os.link(outside, wrapper)
        assert os.stat(wrapper).st_nlink == 2

        reinstall = _run(
            ["bash", ROOT / "scripts/install.sh", "--prefix", prefix, "--force"],
            env=env,
        )

        assert reinstall.returncode != 0
        assert "Unrelated file" in reinstall.stderr
        assert outside.read_bytes() == original
        assert wrapper.read_bytes() == original
        assert os.stat(wrapper).st_nlink == 2
        assert payload_marker.read_bytes() == payload_before


def test_install_force_refuses_hardlinked_payload_without_touching_shared_inode():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        payload_path = installed / "runtime/tool_policy.py"
        outside = temp_root / "outside-owned-looking-payload"
        original = payload_path.read_bytes()

        outside.write_bytes(original)
        payload_path.unlink()
        os.link(outside, payload_path)
        assert os.stat(payload_path).st_nlink == 2

        reinstall = _run(
            ["bash", ROOT / "scripts/install.sh", "--prefix", prefix, "--force"],
            env=env,
        )

        assert reinstall.returncode != 0
        assert "Unproven version directory" in reinstall.stderr
        assert outside.read_bytes() == original
        assert payload_path.read_bytes() == original
        assert os.stat(payload_path).st_nlink == 2


def test_install_force_refuses_unproven_version_directory_without_touching_it():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home = temp_root / "home"
        prefix = temp_root / "prefix"
        home.mkdir()
        version_dir = prefix / "lib/ume-harness" / VERSION
        version_dir.mkdir(parents=True)
        marker = version_dir / "user-owned.txt"
        original = b"user-owned payload\n"
        marker.write_bytes(original)
        env = os.environ.copy()
        env["HOME"] = str(home)

        install = _run(
            ["bash", ROOT / "scripts/install.sh", "--prefix", prefix, "--force"],
            env=env,
        )

        assert install.returncode != 0
        assert "Unproven" in install.stderr
        assert marker.read_bytes() == original
        assert not (prefix / "bin/ume-harness").exists()


def test_install_force_replaces_only_a_verified_owned_installation():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        cache_root = temp_root / "python-cache"
        env["PYTHONPYCACHEPREFIX"] = str(cache_root)
        cli_use = _run([prefix / "bin/ume-harness", "--help"], env=env)
        assert cli_use.returncode == 0, cli_use.stdout + cli_use.stderr
        direct_cli_use = _run([installed / "bin/ume-harness", "--help"], env=env)
        assert direct_cli_use.returncode == 0, direct_cli_use.stdout + direct_cli_use.stderr
        direct_runner_use = _run(
            [installed / "adapters/claude-code/lease_gate_runner.py", "--help"],
            env=env,
        )
        assert direct_runner_use.returncode == 0, direct_runner_use.stdout + direct_runner_use.stderr
        hook_payloads = {
            "pretooluse_hook.py": {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": str(temp_root / "normal.txt")},
                "cwd": str(temp_root),
            },
            "permission_request_hook.py": {
                "hook_event_name": "PermissionRequest",
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
            },
            "posttooluse_failure_hook.py": {
                "hook_event_name": "PostToolUseFailure",
                "error": "synthetic failure",
                "is_interrupt": False,
            },
        }
        for hook_name, payload in hook_payloads.items():
            hook_use = _run(
                [installed / "adapters/claude-code" / hook_name],
                env=env,
                input=json.dumps(payload),
            )
            assert hook_use.returncode == 0, hook_use.stdout + hook_use.stderr
        assert list(installed.rglob("*.pyc")) == []
        installed_runtime_cache = [
            path
            for path in cache_root.rglob("*.pyc")
            if f"ume-harness/{VERSION}/runtime/" in path.as_posix()
        ]
        assert installed_runtime_cache == []

        reinstall = _run(
            ["bash", ROOT / "scripts/install.sh", "--prefix", prefix, "--force"],
            env=env,
        )

        assert reinstall.returncode == 0, reinstall.stdout + reinstall.stderr
        health = _run(
            [sys.executable, installed / "scripts/health_check.py", "--installed-dir", installed, "--prefix", prefix],
            env=env,
        )
        assert health.returncode == 0, health.stdout + health.stderr


def test_install_force_rejects_unproven_legacy_bytecode_cache():
    hss = _load_module(ROOT / "runtime/hook_setup_service.py", "hook_setup_legacy_cache")
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        wrapper = prefix / "bin/ume-harness"
        wrapper.write_text(
            hss.render_cli_wrapper(str(installed), bytecode_safe=False),
            encoding="utf-8",
        )
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        env.pop("PYTHONPYCACHEPREFIX", None)

        imported = _run(
            [
                sys.executable,
                "-c",
                "import py_compile, sys; sys.pycache_prefix = None; py_compile.compile(sys.argv[1], doraise=True)",
                installed / "runtime/tool_policy.py",
            ],
            env=env,
            cwd=temp_root,
        )
        assert imported.returncode == 0, imported.stdout + imported.stderr
        generated = list((installed / "runtime/__pycache__").glob("tool_policy.*.pyc"))
        assert generated
        generated_bytes = generated[0].read_bytes()

        reinstall = _run(
            ["bash", ROOT / "scripts/install.sh", "--prefix", prefix, "--force"],
            env=env,
        )

        assert reinstall.returncode != 0
        assert "Unproven version directory" in reinstall.stderr
        assert generated[0].read_bytes() == generated_bytes
        assert (installed / "runtime/__pycache__").is_dir()


def test_owned_install_verifier_accepts_known_prior_identity_and_legacy_wrapper(monkeypatch):
    health = _load_module(ROOT / "scripts/health_check.py", "health_check_prior_identity")
    hss = _load_module(ROOT / "runtime/hook_setup_service.py", "hook_setup_prior_wrapper")
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, _env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        wrapper = prefix / "bin/ume-harness"

        actual_root = health.calculate_release_identity(
            str(installed),
            _read_json(installed / "package_manifest.json")["release_identity"]["closure"],
        )
        installed_health_sha = health._sha256_regular_file(
            str(installed / "scripts/health_check.py")
        )
        monkeypatch.setattr(
            health,
            "_load_owned_release_anchors",
            lambda: {actual_root: installed_health_sha},
        )

        owned, detail = health.verify_owned_install(str(installed))
        assert owned, detail

        legacy_wrapper = hss.render_cli_wrapper(str(installed), bytecode_safe=False)
        wrapper.write_text(legacy_wrapper, encoding="utf-8")
        assert hss.cli_wrapper_is_owned(str(wrapper), str(installed))


def test_external_owned_install_verifier_uses_independent_health_anchor():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, _env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION

        verifier_scripts = temp_root / "verifier" / "scripts"
        verifier_scripts.mkdir(parents=True)
        external_health = verifier_scripts / "health_check.py"
        external_gate = verifier_scripts / "release_promote.py"
        external_health.write_bytes(
            (ROOT / "scripts/health_check.py").read_bytes()
            + b"\n# independently modified verifier probe\n"
        )
        external_gate.write_bytes((ROOT / "scripts/release_promote.py").read_bytes())
        installed_health = installed / "scripts/health_check.py"
        installed_health.write_bytes(external_health.read_bytes())

        verifier = _load_module(external_health, "modified_external_health_check")
        owned, detail = verifier.verify_owned_install(str(installed))

        assert not owned
        assert "health-check trust anchor mismatch" in detail


def test_installed_owned_install_verifier_refuses_self_attestation():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        installed_health = installed / "scripts/health_check.py"
        installed_health.write_bytes(installed_health.read_bytes() + b"\n# tampered self-attestation probe\n")

        self_check = _run(
            [
                sys.executable,
                installed_health,
                "--installed-dir",
                installed,
                "--owned-install-only",
                "--json",
            ],
            env=env,
        )

        assert self_check.returncode != 0
        assert "external verifier" in (self_check.stdout + self_check.stderr)


def test_owned_install_verifier_rejects_fifo_without_blocking():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        payload_path = installed / "runtime/decision_state.py"
        payload_path.unlink()
        os.mkfifo(payload_path)

        try:
            checked = subprocess.run(
                [
                    sys.executable,
                    ROOT / "scripts/health_check.py",
                    "--installed-dir",
                    installed,
                    "--owned-install-only",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired as exc:
            pytest.fail(f"owned-install verification blocked on a FIFO: {exc}")

        assert checked.returncode != 0
        assert "unsafe=" in (checked.stdout + checked.stderr)


def test_installed_hook_entrypoints_use_portable_env_shebangs():
    hook_names = (
        "pretooluse_hook.py",
        "permission_request_hook.py",
        "posttooluse_failure_hook.py",
    )
    for hook_name in hook_names:
        hook_path = ROOT / "adapters/claude-code" / hook_name
        lines = hook_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "#!/usr/bin/env python3"
        assert "sys.dont_write_bytecode = True" in lines
    runner_lines = (ROOT / "adapters/claude-code/lease_gate_runner.py").read_text(
        encoding="utf-8"
    ).splitlines()
    assert "sys.dont_write_bytecode = True" in runner_lines


def test_install_force_refuses_verified_payload_with_extra_user_bytes():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        marker = installed / "user-owned-extra.txt"
        original = b"do not delete\n"
        marker.write_bytes(original)

        reinstall = _run(
            ["bash", ROOT / "scripts/install.sh", "--prefix", prefix, "--force"],
            env=env,
        )

        assert reinstall.returncode != 0
        assert "Unproven" in reinstall.stderr
        assert marker.read_bytes() == original


def test_install_force_refuses_payload_with_tampered_excluded_health_anchor():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        _home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        installed_health = installed / "scripts/health_check.py"
        original = b"#!/usr/bin/env python3\n# user-modified trust anchor\n"
        installed_health.write_bytes(original)

        reinstall = _run(
            ["bash", ROOT / "scripts/install.sh", "--prefix", prefix, "--force"],
            env=env,
        )

        assert reinstall.returncode != 0
        assert "Unproven" in reinstall.stderr
        assert installed_health.read_bytes() == original


@pytest.mark.parametrize("symlink", (False, True), ids=("regular", "symlink"))
def test_uninstall_preserves_user_owned_cli_and_target(symlink):
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home = temp_root / "home"
        prefix = temp_root / "prefix"
        settings_path = home / ".claude/settings.json"
        home.mkdir()
        wrapper, target, original = _write_user_owned_cli(temp_root, prefix, symlink=symlink)
        env = os.environ.copy()
        env["HOME"] = str(home)

        uninstall = _run(
            ["bash", ROOT / "scripts/uninstall.sh", "--prefix", prefix,
             "--settings-path", settings_path, "--yes"],
            env=env,
        )

        assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
        assert wrapper.is_symlink() if symlink else wrapper.is_file()
        assert target.read_bytes() == original


def test_source_uninstaller_does_not_trust_a_legacy_target_helper():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        wrapper = prefix / "bin/ume-harness"
        settings_path = home / ".claude/settings.json"
        initial = _initial_settings(temp_root)
        owned_command = str(installed / "adapters/claude-code/pretooluse_hook.py")
        configured = _initial_settings(temp_root)
        configured["hooks"]["PreToolUse"].append({
            "matcher": "*",
            "hooks": [{"type": "command", "command": owned_command}],
        })
        _write_json(settings_path, configured)

        legacy_helper = installed / "runtime/hook_setup_service.py"
        legacy_helper.write_text("#!/usr/bin/env python3\nraise SystemExit(0)\n", encoding="utf-8")
        user_wrapper = b"#!/usr/bin/env bash\necho user-owned\n"
        wrapper.write_bytes(user_wrapper)

        uninstall = _run(
            ["bash", ROOT / "scripts/uninstall.sh", "--prefix", prefix,
             "--settings-path", settings_path, "--yes"],
            env=env,
        )

        assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
        assert not installed.exists()
        assert wrapper.read_bytes() == user_wrapper
        assert _read_json(settings_path) == initial


def test_installed_uninstaller_holds_when_its_helper_protocol_is_unproven():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        wrapper = prefix / "bin/ume-harness"
        settings_path = home / ".claude/settings.json"
        initial = _initial_settings(temp_root)
        _write_json(settings_path, initial)
        legacy_helper = installed / "runtime/hook_setup_service.py"
        legacy_helper.write_text("#!/usr/bin/env python3\nraise SystemExit(0)\n", encoding="utf-8")

        uninstall = _run(
            ["bash", installed / "scripts/uninstall.sh", "--prefix", prefix,
             "--settings-path", settings_path, "--yes"],
            env=env,
        )

        assert uninstall.returncode != 0
        assert installed.is_dir()
        assert wrapper.is_file()
        assert _read_json(settings_path) == initial


def test_final_isolated_lifecycle_closes_owned_state_and_preserves_user_state():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        cli = prefix / "bin/ume-harness"
        settings_path = home / ".claude/settings.json"
        initial = _initial_settings(temp_root)
        _write_json(settings_path, initial)
        user_state = home / ".ume-harness/state/preserved.txt"
        user_state.parent.mkdir(parents=True)
        user_state.write_text("preserve-me\n", encoding="utf-8")

        setup = _run([cli, "setup", "--yes", "--settings-path", settings_path], env=env)
        assert setup.returncode == 0, setup.stdout + setup.stderr
        configured = _read_json(settings_path)
        owned = {
            event: str(installed / "adapters/claude-code" / filename)
            for event, filename in {
                "PreToolUse": "pretooluse_hook.py",
                "PermissionRequest": "permission_request_hook.py",
                "PostToolUseFailure": "posttooluse_failure_hook.py",
            }.items()
        }
        for event, command in owned.items():
            assert _commands(configured, event).count(command) == 1

        llm_output = temp_root / "offline.json"
        _write_json(
            llm_output,
            {
                "work_type": "RESEARCH",
                "inferred_intent": "x",
                "inferred_deliverable": "x",
                "candidate_actions": ["資料を確認する"],
                "clarification_assessments": [],
            },
        )
        use = _run([cli, "--llm-output-file", llm_output], env=env)
        assert use.returncode == 0, use.stdout + use.stderr

        verify = _run(
            [sys.executable, installed / "scripts/health_check.py", "--installed-dir", installed, "--prefix", prefix],
            env=env,
        )
        assert verify.returncode == 0, verify.stdout + verify.stderr

        disconnect = _run([cli, "setup", "--disconnect", "--settings-path", settings_path], env=env)
        assert disconnect.returncode == 0, disconnect.stdout + disconnect.stderr
        assert _read_json(settings_path) == initial

        uninstall = _run(
            ["bash", installed / "scripts/uninstall.sh", "--prefix", prefix, "--settings-path", settings_path, "--yes"],
            env=env,
        )
        assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr

        assert not installed.exists()
        assert not cli.exists()
        final_settings = _read_json(settings_path)
        for event, command in owned.items():
            assert command not in _commands(final_settings, event)
        assert final_settings == initial
        assert user_state.read_text(encoding="utf-8") == "preserve-me\n"


def test_uninstall_disconnects_active_hooks_and_aborts_if_settings_are_unreadable():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        home, prefix, env = _install(temp_root)
        installed = prefix / "lib/ume-harness" / VERSION
        cli = prefix / "bin/ume-harness"
        settings_path = home / ".claude/settings.json"
        initial = _initial_settings(temp_root)
        _write_json(settings_path, initial)

        setup = _run([cli, "setup", "--yes", "--settings-path", settings_path], env=env)
        assert setup.returncode == 0, setup.stdout + setup.stderr
        uninstall = _run(
            ["bash", installed / "scripts/uninstall.sh", "--prefix", prefix, "--settings-path", settings_path, "--yes"],
            env=env,
        )
        assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
        assert _read_json(settings_path) == initial
        assert not installed.exists()
        assert not cli.exists()

        # A user-owned wrapper around the exact payload path is never removed.
        # It instead blocks deletion so uninstall cannot create a dangling hook.
        wrapped_install = _run(["bash", ROOT / "scripts/install.sh", "--prefix", prefix], env=env)
        assert wrapped_install.returncode == 0, wrapped_install.stdout + wrapped_install.stderr
        wrapped_command = f"python3 {installed / 'adapters/claude-code/pretooluse_hook.py'} --custom"
        wrapped_settings = _initial_settings(temp_root)
        wrapped_settings["hooks"]["PreToolUse"].append({
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": wrapped_command}],
        })
        _write_json(settings_path, wrapped_settings)
        wrapped_refused = _run(
            ["bash", installed / "scripts/uninstall.sh", "--prefix", prefix, "--settings-path", settings_path, "--yes"],
            env=env,
        )
        assert wrapped_refused.returncode != 0
        assert installed.is_dir()
        assert cli.is_file()
        assert _read_json(settings_path) == wrapped_settings
        wrapped_settings["hooks"]["PreToolUse"].pop()
        _write_json(settings_path, wrapped_settings)

        # A canonical path nested inside a quoted shell command remains
        # user-owned, but it must still block deletion to avoid a dangling hook.
        nested_command = f"bash -c 'python3 {installed / 'adapters/claude-code/pretooluse_hook.py'}'"
        wrapped_settings["hooks"]["PreToolUse"].append({
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": nested_command}],
        })
        _write_json(settings_path, wrapped_settings)
        nested_refused = _run(
            ["bash", installed / "scripts/uninstall.sh", "--prefix", prefix,
             "--settings-path", settings_path, "--yes"],
            env=env,
        )
        assert nested_refused.returncode != 0
        assert installed.is_dir()
        assert cli.is_file()
        assert _read_json(settings_path) == wrapped_settings
        wrapped_settings["hooks"]["PreToolUse"].pop()
        _write_json(settings_path, wrapped_settings)

        # An exact canonical command moved to an unrelated event is not owned
        # there and is not removed, but it must still block payload deletion.
        moved_command = str(installed / "adapters/claude-code/pretooluse_hook.py")
        moved_group = {
            "matcher": "*",
            "hooks": [{"type": "command", "command": moved_command}],
        }
        wrapped_settings["hooks"]["Stop"].append(moved_group)
        _write_json(settings_path, wrapped_settings)
        moved_refused = _run(
            ["bash", installed / "scripts/uninstall.sh", "--prefix", prefix, "--settings-path", settings_path, "--yes"],
            env=env,
        )
        assert moved_refused.returncode != 0
        assert installed.is_dir()
        assert cli.is_file()
        assert _read_json(settings_path) == wrapped_settings
        wrapped_settings["hooks"]["Stop"].pop()
        _write_json(settings_path, wrapped_settings)

        wrapped_cleanup = _run(
            ["bash", installed / "scripts/uninstall.sh", "--prefix", prefix, "--settings-path", settings_path, "--yes"],
            env=env,
        )
        assert wrapped_cleanup.returncode == 0, wrapped_cleanup.stdout + wrapped_cleanup.stderr
        assert _read_json(settings_path) == initial

        # If payload bytes disappear out-of-band, the source uninstaller still
        # removes exact dangling commands instead of returning "nothing to do".
        install_dangling = _run(["bash", ROOT / "scripts/install.sh", "--prefix", prefix], env=env)
        assert install_dangling.returncode == 0, install_dangling.stdout + install_dangling.stderr
        setup_dangling = _run([cli, "setup", "--yes", "--settings-path", settings_path], env=env)
        assert setup_dangling.returncode == 0, setup_dangling.stdout + setup_dangling.stderr
        shutil.rmtree(installed)
        cli.unlink()
        cleanup_dangling = _run(
            ["bash", ROOT / "scripts/uninstall.sh", "--prefix", prefix, "--settings-path", settings_path, "--yes"],
            env=env,
        )
        assert cleanup_dangling.returncode == 0, cleanup_dangling.stdout + cleanup_dangling.stderr
        assert _read_json(settings_path) == initial

        # Reinstall, connect, then make settings unreadable. Uninstall must fail
        # before deleting bytes because it cannot prove that no owned hooks remain.
        install_again = _run(["bash", ROOT / "scripts/install.sh", "--prefix", prefix], env=env)
        assert install_again.returncode == 0, install_again.stdout + install_again.stderr
        setup_again = _run([cli, "setup", "--yes", "--settings-path", settings_path], env=env)
        assert setup_again.returncode == 0, setup_again.stdout + setup_again.stderr
        settings_path.write_text("{not-json", encoding="utf-8")
        refused = _run(
            ["bash", installed / "scripts/uninstall.sh", "--prefix", prefix, "--settings-path", settings_path, "--yes"],
            env=env,
        )
        assert refused.returncode != 0
        assert installed.is_dir()
        assert cli.is_file()


def test_release_promotion_is_clean_explicit_deterministic_and_one_way():
    script_path = ROOT / "scripts/release_promote.py"
    assert script_path.is_file()
    release = _load_module(script_path, "release_promote_under_test")
    manifest = _read_json(ROOT / "package_manifest.json")
    contract = manifest["release"]
    assert contract["canonical_repository"] == CANONICAL_REPOSITORY
    assert contract["public_mirror_repository"] == PUBLIC_MIRROR_REPOSITORY
    assert contract["promotion_direction"] == "canonical_to_public_only"
    assert contract["public_source_edits_supported"] is False
    assert (
        release.OWNED_INSTALL_HEALTH_ANCHORS[release.EXPECTED_INSTALL_ROOT_DIGEST]
        == release.EXPECTED_HEALTH_CHECK_SHA256
    )

    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        source = temp_root / "canonical"
        source.mkdir()
        generated = contract["generated_identity_file"]
        for rel in contract["payload"]:
            if rel == generated:
                continue
            src = ROOT / rel
            dst = source / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        health_probe = source / "scripts/health_check.py"
        health_probe_original = health_probe.read_bytes()
        health_probe.write_bytes(health_probe_original + b"\n# modified verifier probe\n")
        with pytest.raises(release.ReleaseError, match="health-check trust anchor"):
            release.assert_frozen_install_identity(source)
        health_probe.write_bytes(health_probe_original)

        assert _run(["git", "init", "-b", "main"], cwd=source).returncode == 0
        assert _run(["git", "config", "user.email", "release-test@example.invalid"], cwd=source).returncode == 0
        assert _run(["git", "config", "user.name", "Release Test"], cwd=source).returncode == 0
        assert _run(["git", "add", "."], cwd=source).returncode == 0
        assert _run(["git", "commit", "-m", "test canonical release"], cwd=source).returncode == 0
        assert _run(["git", "remote", "add", "origin", CANONICAL_REPOSITORY], cwd=source).returncode == 0

        # An ignored ambient file exists but is not part of the explicit closure.
        info_exclude = source / ".git/info/exclude"
        info_exclude.write_text("ambient-scratch.txt\n", encoding="utf-8")
        (source / "ambient-scratch.txt").write_text("not a release byte\n", encoding="utf-8")

        stage_one = temp_root / "stage-one"
        stage_two = temp_root / "stage-two"
        public = temp_root / "public"
        with pytest.raises(release.ReleaseError):
            release.assert_staging_is_disjoint(source, public / ".git/release-stage", public)
        release.stage_release(source, stage_one)
        release.stage_release(source, stage_two)
        release.verify_staged_release(stage_one)
        release.verify_staged_release(stage_two)
        assert not (stage_one / "ambient-scratch.txt").exists()
        assert (stage_one / generated).is_file()
        assert release.compare_trees(stage_one, stage_two) == []
        assert _read_json(stage_one / generated) == _read_json(stage_two / generated)

        shutil.copytree(stage_one, public)
        assert _run(["git", "init", "-b", "main"], cwd=public).returncode == 0
        assert _run(["git", "config", "user.email", "release-test@example.invalid"], cwd=public).returncode == 0
        assert _run(["git", "config", "user.name", "Release Test"], cwd=public).returncode == 0
        assert _run(["git", "add", "."], cwd=public).returncode == 0
        assert _run(["git", "commit", "-m", "test public mirror"], cwd=public).returncode == 0
        assert _run(["git", "remote", "add", "origin", PUBLIC_MIRROR_REPOSITORY], cwd=public).returncode == 0
        assert release.compare_public_mirror(stage_one, public) == []
        (public / "ignored-ambient.pyc").write_bytes(b"not a release byte")
        assert release.compare_public_mirror(stage_one, public) == []
        (public / "tracked-dangling-link").symlink_to("missing-target")
        assert _run(["git", "add", "tracked-dangling-link"], cwd=public).returncode == 0
        assert _run(["git", "commit", "-m", "tracked dangling link probe"], cwd=public).returncode == 0
        assert "unexpected:tracked-dangling-link" in release.compare_public_mirror(stage_one, public)
        public_readme = public / "README.md"
        outside_readme = temp_root / "outside-readme.md"
        outside_readme.write_bytes(public_readme.read_bytes())
        public_readme.unlink()
        public_readme.symlink_to(outside_readme)
        assert _run(["git", "add", "README.md"], cwd=public).returncode == 0
        assert _run(["git", "commit", "-m", "tracked symlink probe"], cwd=public).returncode == 0
        assert "changed:README.md" in release.compare_public_mirror(stage_one, public)

        # The public mirror can never be selected as the source.
        assert _run(["git", "remote", "set-url", "origin", PUBLIC_MIRROR_REPOSITORY], cwd=source).returncode == 0
        with pytest.raises(release.ReleaseError):
            release.assert_canonical_checkout(source)

        # Dirty canonical checkouts are rejected before staging.
        assert _run(["git", "remote", "set-url", "origin", CANONICAL_REPOSITORY], cwd=source).returncode == 0
        tracked_probe = source / "runtime/translation_konjac.py"
        tracked_probe_original = tracked_probe.read_bytes()
        tracked_probe.write_bytes(tracked_probe_original + b"\n# assume-unchanged probe\n")
        assert _run(["git", "update-index", "--assume-unchanged", "runtime/translation_konjac.py"], cwd=source).returncode == 0
        assert _run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=source).stdout.strip() == ""
        with pytest.raises(release.ReleaseError, match="committed HEAD"):
            release.assert_payload_matches_head(source, ["runtime/translation_konjac.py"])
        assert _run(["git", "update-index", "--no-assume-unchanged", "runtime/translation_konjac.py"], cwd=source).returncode == 0
        tracked_probe.write_bytes(tracked_probe_original)

        (source / "README.md").write_text("dirty\n", encoding="utf-8")
        with pytest.raises(release.ReleaseError):
            release.assert_canonical_checkout(source)

        # Even a clean, committed payload cannot be staged until its frozen
        # installed identity has been deliberately updated.
        readme_bytes = (ROOT / "README.md").read_bytes()
        (source / "README.md").write_bytes(readme_bytes)
        tracked_probe.write_bytes(tracked_probe_original + b"\n# stale frozen identity probe\n")
        assert _run(["git", "add", "runtime/translation_konjac.py"], cwd=source).returncode == 0
        assert _run(["git", "commit", "-m", "stale frozen identity probe"], cwd=source).returncode == 0
        with pytest.raises(release.ReleaseError, match="frozen install identity"):
            release.stage_release(source, temp_root / "stale-identity-stage")
