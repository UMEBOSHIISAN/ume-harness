"""Regressions from the live CC search failures; targets are synthetic."""
from test_local_work_policy import env, runner
import pytest


def evaluate(env, command):
    project, state, install, _ = env
    return runner.evaluate_invocation_result(
        {"tool_name": "Bash", "cwd": str(project), "permission_mode": "bypassPermissions",
         "tool_input": {"command": command}}, state_dir=str(state), install_dir=str(install))


@pytest.mark.parametrize("command", [
    "grep -n 'BATCH_ROWS' scripts/build_input.py",
    'grep -n "第1[4-9]\\|range(" RUNBOOK.md SCHEDULE.md 2>/dev/null | tail -60',
    "cd . && grep -n 'BATCH_ROWS' RUNBOOK.md | head -50",
    "/usr/bin/grep -n 'BATCH_ROWS' scripts/build_input.py",
])
def test_live_search_delegates_to_host_even_in_bypass_mode(env, command):
    assert evaluate(env, command).decision == "defer"


@pytest.mark.parametrize("command", [
    "grep -n x .env", "grep -f .env report.md", "grep -R x .",
    "grep x report.md > out", "grep x report.md | python3 run.py",
    "grep x report.md | curl https://example.com", "grep x $(cat .env)",
    "grep x *.json", "grep --include='*' -r x .", "grep x /proc/self/environ",
])
def test_search_is_not_a_general_bypass(env, command):
    assert evaluate(env, command).decision == "deny"


def test_search_checks_aliases_and_managed_domains(env):
    project = env[0]
    (project / '.env').write_text('synthetic')
    (project / 'report.md').symlink_to(project / '.env')
    assert evaluate(env, "grep x report.md").decision == "deny"
    (project / 'managed/.ume-harness').mkdir(parents=True)
    (project / 'managed/.ume-harness/domain.json').write_text('{}')
    assert evaluate(env, "cd managed && grep x report.md | head -10").decision == "deny"


@pytest.mark.parametrize("command", [
    "grep x report.md '|' head", r"grep x report.md \| head",
    "grep x report.md 2 >/dev/null", "grep x report.md '2'>/dev/null",
])
def test_quoted_operators_and_spaced_descriptor_keep_real_operands(env, command):
    project = env[0]
    (project / '.env').write_text('synthetic')
    (project / 'head').symlink_to(project / '.env')
    (project / '2').symlink_to(project / '.env')
    assert evaluate(env, command).decision == "deny"


def test_memo_name_and_sensitive_storage(env):
    assert env[3]("Read", "insight_project_secrets_read_block.md").decision == "defer"
    assert env[3]("Read", ".secrets/notes.md").decision == "deny"
    assert env[3]("Read", "secrets/notes.md").decision == "deny"
    assert env[3]("Read", "account_secrets.json").decision == "deny"


def test_cd_parent_after_alias_cannot_claim_physical_read_scope(env):
    project = env[0]
    (project / 'child').mkdir()
    outside = project.parent / 'outside'
    outside.mkdir()
    (outside / 'link').symlink_to(project / 'child')
    assert evaluate(env, "cd ../outside/link/.. && grep x report.md").decision == "deny"
