"""Synthetic-only regressions for bounded, non-authoritative presentation."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
import translation_konjac as konjac

VALUE = "synthetic-value-U5-ONLY"
INLINE = f"API_KEY={VALUE}"
BEARER = f"Authorization: Bearer {VALUE}"
HOOKS = ("permission_request_hook.py", "posttooluse_failure_hook.py")
FORBIDDEN_FIELDS = {
    "decision", "permissionDecision", "permissionDecisionReason",
    "updatedInput", "updatedPermissions", "continue",
}

# Run the actual hook, with optional faults only at the presentation boundary.
# Audit attempted writes in memory: a hook cannot hide a write attempt by
# catching the guard's exception. No helper script or log is written to disk.
HOOK_PROCESS = r'''
import importlib.util
import os
import sys

writes = []
def forbid_writes(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    else:
        writing = event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename",
                            "os.link", "os.symlink", "os.chmod", "os.truncate"}
    if writing:
        writes.append(event)
        raise RuntimeError("unexpected presentation filesystem mutation")

sys.addaudithook(forbid_writes)
spec = importlib.util.spec_from_file_location("presentation_hook_under_test", sys.argv[1])
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

def broken(*args, **kwargs):
    raise RuntimeError(sys.argv[3])

if sys.argv[2] == "translation":
    hook.konjac.translate_tool_event = broken
elif sys.argv[2] == "banner":
    hook.konjac.format_user_banner = broken
elif sys.argv[2] == "failure-template":
    class BrokenTemplate:
        get = broken
    hook.pack.JA_CONCEPT_PACK = BrokenTemplate()

result = hook.main()
assert not writes, "presentation attempted filesystem mutation"
sys.exit(result)
'''


def assert_no_permission_fields(value):
    if isinstance(value, dict):
        assert FORBIDDEN_FIELDS.isdisjoint(value), value.keys()
        for child in value.values():
            assert_no_permission_fields(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_permission_fields(child)


def assert_safe(text):
    assert VALUE not in text
    assert len(text) <= 1000
    assert len(text.splitlines()) <= 8


@pytest.mark.parametrize("command", [
    f"{INLINE} python3 script.py",
    f"curl -H '{BEARER}' https://example.invalid",
    f"python3 -c 'print(\"{INLINE}\")'",
    f"git commit -m '{BEARER}'",
    f"git add '{INLINE}'",
    f"rm '{INLINE}'",
    f"git push origin '{INLINE}'",
    f"git status && mystery '{BEARER}'",
    "git status; " * 500 + f"mystery '{INLINE}'",
])
def test_command_display_omits_arguments_and_is_bounded(command, tmp_path):
    result = konjac.translate_bash_command(command, str(tmp_path))
    assert_safe(konjac.format_user_banner(result, permission_context=True))
    assert VALUE not in result.headline + result.explanation + result.locality_badge
    assert result.raw_event == command.strip()


@pytest.mark.parametrize("opener", ["python3 <<'PY'", "python3 <<-PY", 'python3 <<"PY"'])
def test_heredoc_body_is_one_opaque_program(opener, tmp_path):
    command = opener + "\n" + f"print('{INLINE}')\n" * 500 + "PY"
    result = konjac.translate_bash_command(command, str(tmp_path))
    assert result.concept_id == "unknown.command"
    assert result.effect_level == konjac.EffectLevel.UNKNOWN
    assert not result.is_known
    assert "プログラム" in result.headline + result.explanation
    assert "print(" not in result.explanation
    assert_safe(konjac.format_user_banner(result, permission_context=True))


@pytest.mark.parametrize("tool,inputs", [
    ("Read", {"file_path": INLINE}),
    ("Write", {"file_path": INLINE, "content": BEARER}),
    ("Edit", {"file_path": INLINE, "new_string": BEARER}),
    ("Grep", {"pattern": BEARER}),
    ("Glob", {"pattern": INLINE}),
    (INLINE, {"command": BEARER}),
])
def test_tool_display_does_not_echo_input(tool, inputs, tmp_path):
    result = konjac.translate_tool_event(tool, inputs, str(tmp_path))
    assert_safe(konjac.format_user_banner(result, permission_context=True))


def run_hook(name, payload, tmp_path, *, raw=False, fault=""):
    # Hook fixtures never execute supplied commands or use real host settings.
    proc = subprocess.run(
        [sys.executable, "-B", "-c", HOOK_PROCESS,
         str(ROOT / "adapters" / "claude-code" / name), fault, VALUE],
        input=payload if raw else json.dumps(payload), text=True, capture_output=True,
        cwd=tmp_path, env={**os.environ, "HOME": str(tmp_path)}, check=False,
        timeout=3,
    )
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert VALUE not in proc.stdout
    output = json.loads(proc.stdout) if proc.stdout else None
    assert_no_permission_fields(output)
    if output is not None:
        assert_safe(output["systemMessage"])
        if "hookSpecificOutput" in output:
            assert output["hookSpecificOutput"] == {
                "hookEventName": "PostToolUseFailure",
                "additionalContext": output["systemMessage"],
            }
    assert not list(tmp_path.iterdir()), "hook created files in its isolated home/cwd"
    return output


@pytest.mark.parametrize("command", [
    f"{INLINE} python3 script.py",
    f"curl -H '{BEARER}' https://example.invalid",
    "python3 <<'PY'\n" + f"print('{INLINE}')\n" * 500 + "PY",
])
def test_permission_hook_all_output_safe_and_native_confirmation_referenced(command, tmp_path):
    output = run_hook("permission_request_hook.py", {
        "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path),
    }, tmp_path)
    assert_safe(output["systemMessage"])
    assert "Claude Code" in output["systemMessage"]
    assert "確認" in output["systemMessage"]
    assert "hookSpecificOutput" not in output
    assert "許可しました" not in output["systemMessage"]
    assert "禁止" not in output["systemMessage"]


@pytest.mark.parametrize("field", ["error", "stderr"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_failure_hook_omits_raw_details_and_preserves_uncertainty(field, interrupt, tmp_path):
    error = f"Exit code 127\n{INLINE}\n{BEARER}\n" * 500
    payload = {"is_interrupt": interrupt}
    if field == "error":
        payload["error"] = error
    else:
        payload["tool_response"] = {"stderr": error}
    output = run_hook("posttooluse_failure_hook.py", payload, tmp_path)
    assert_safe(output["systemMessage"])
    assert "Claude Code" in output["systemMessage"]
    assert "変更" in output["systemMessage"]
    assert "中断" in output["systemMessage"] if interrupt else "終了コード: 127" in output["systemMessage"]
    assert output["hookSpecificOutput"] == {
        "hookEventName": "PostToolUseFailure", "additionalContext": output["systemMessage"],
    }


def test_failure_hook_does_not_echo_unbounded_numeric_error(tmp_path):
    output = run_hook("posttooluse_failure_hook.py", {"error": "Exit code " + "9" * 2000}, tmp_path)
    assert_safe(output["systemMessage"])


@pytest.mark.parametrize("name", HOOKS)
@pytest.mark.parametrize("raw", ["", " \n", "{", '{"error":', VALUE],
                         ids=["empty", "whitespace", "invalid-json", "truncated-json", "marker"])
def test_malformed_json_is_silent_without_permission_output(name, raw, tmp_path):
    assert run_hook(name, raw, tmp_path, raw=True) is None


@pytest.mark.parametrize("name", HOOKS)
@pytest.mark.parametrize("payload", [
    None, [], [VALUE], 42, True, VALUE, {},
    {"tool_name": "Bash"}, {"tool_input": {"command": INLINE}},
    {"tool_name": "Bash", "tool_input": None},
    {"tool_name": "Bash", "tool_input": {"command": [VALUE]}},
    {"error": [VALUE]}, {"tool_response": None},
], ids=["null", "list", "marker-list", "number", "boolean", "string", "empty-object",
        "missing-input", "missing-tool", "null-input", "nonstring-command",
        "nonstring-error", "null-response"])
def test_abnormal_shapes_do_not_leak_or_emit_permission_fields(name, payload, tmp_path):
    # Either silence or a bounded explanation is acceptable; never a verdict.
    run_hook(name, payload, tmp_path)


@pytest.mark.parametrize("name", HOOKS)
def test_incoming_permission_fields_are_not_forwarded(name, tmp_path):
    payload = {
        "tool_name": "Bash", "tool_input": {"command": INLINE}, "error": BEARER,
        "decision": "deny", "permissionDecision": "allow", "continue": False,
        "updatedInput": {"command": INLINE}, "updatedPermissions": [{"value": VALUE}],
        "hookSpecificOutput": {"decision": {"behavior": "allow", "updatedInput": {}}},
    }
    assert run_hook(name, payload, tmp_path) is not None


@pytest.mark.parametrize("tool,inputs", [
    ("Read", {"file_path": "ordinary.txt"}),
    ("Write", {"file_path": "ordinary.txt", "content": INLINE}),
    ("Bash", {"command": "python3 -m pytest"}),
    ("Bash", {"command": "git push origin ordinary-branch"}),
    ("Bash", {"command": "rm ordinary.txt"}),
    ("UnregisteredTool", {"value": VALUE}),
], ids=["read", "write", "test", "external", "destructive", "unknown"])
def test_permission_explanations_never_supply_a_verdict(tool, inputs, tmp_path):
    output = run_hook(HOOKS[0], {"tool_name": tool, "tool_input": inputs,
                               "cwd": str(tmp_path)}, tmp_path)
    assert output is not None
    assert "hookSpecificOutput" not in output
    assert "Claude Code" in output["systemMessage"]


@pytest.mark.parametrize("name,fault,interrupt", [
    (HOOKS[0], "translation", False), (HOOKS[0], "banner", False),
    (HOOKS[1], "failure-template", False), (HOOKS[1], "failure-template", True),
])
def test_rendering_exception_is_private_and_noninterfering(name, fault, interrupt, tmp_path):
    output = run_hook(name, {
        "tool_name": "Bash", "tool_input": {"command": INLINE},
        "error": BEARER, "is_interrupt": interrupt,
    }, tmp_path, fault=fault)
    assert output is not None
    assert "解説" in output["systemMessage"] and "失敗" in output["systemMessage"]
    assert "Claude Code" in output["systemMessage"]


@pytest.mark.parametrize("name,kind", [
    (HOOKS[0], "heredoc"), (HOOKS[0], "compound"),
    (HOOKS[1], "error"), (HOOKS[1], "interrupt"),
])
def test_long_input_finishes_within_subprocess_deadline(name, kind, tmp_path):
    # Fixed synthetic sizes, not an unbounded stress test. The helper kills and
    # fails the subprocess after three seconds on every path, including faults.
    payload = {"tool_name": "Bash", "tool_input": {}}
    if kind == "heredoc":
        payload["tool_input"]["command"] = "python3 <<'PY'\n" + f"print('{INLINE}')\n" * 10000 + "PY"
    elif kind == "compound":
        payload["tool_input"]["command"] = f"mystery '{BEARER}'; " * 2000
    else:
        payload["error"] = f"Exit code 127\n{INLINE}\n{BEARER}\n" * 10000
        payload["is_interrupt"] = kind == "interrupt"
    assert run_hook(name, payload, tmp_path) is not None
