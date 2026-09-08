"""Isolated host protocol tests; policy evaluation belongs to the runner."""

import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters" / "claude-code"))
import pretooluse_hook as hook


PAYLOAD = {"tool_name": "Write", "tool_input": {"file_path": "/project/code.py"}}


def invoke(monkeypatch, result, payload=PAYLOAD):
    evaluator = Mock(return_value=result)
    legacy = Mock(side_effect=AssertionError("duplicate legacy evaluation"))
    monkeypatch.setattr(hook.runner, "evaluate_invocation_result", evaluator, raising=False)
    monkeypatch.setattr(hook.runner, "evaluate_invocation", legacy)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    status = hook.main()
    evaluator.assert_called_once_with(payload)
    legacy.assert_not_called()
    return status


@pytest.mark.parametrize("decision", ["ask", "deny"])
def test_native_permission_json(monkeypatch, capsys, decision):
    # The reason deliberately contradicts the verdict: no prose parsing is allowed.
    reason = "defer / error / 日本語の理由"
    result = SimpleNamespace(decision=decision, reason=reason, code="POLICY")
    assert invoke(monkeypatch, result) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }


@pytest.mark.parametrize("permission_mode", ["auto", "ask"])
def test_defer_is_silent_and_never_force_allows(monkeypatch, capsys, permission_mode):
    translator = Mock(side_effect=AssertionError("false permission card"))
    monkeypatch.setattr(hook.konjac, "translate_tool_event", translator)
    result = SimpleNamespace(decision="defer", reason="", code="LOCAL")
    assert invoke(monkeypatch, result, {**PAYLOAD, "permission_mode": permission_mode}) == 0
    output = capsys.readouterr()
    assert (output.out, output.err) == ("", "")
    translator.assert_not_called()


def test_error_blocks_without_permission_json(monkeypatch, capsys):
    result = SimpleNamespace(decision="error", reason="corrupt state", code="STATE_ERROR")
    assert invoke(monkeypatch, result) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "corrupt state" in output.err
    assert "STATE_ERROR" in output.err


@pytest.mark.parametrize("decision", ["ask", "deny"])
def test_presentation_failure_preserves_decision(monkeypatch, capsys, decision):
    monkeypatch.setattr(hook.konjac, "translate_tool_event", Mock(side_effect=ValueError("broken")))
    result = SimpleNamespace(decision=decision, reason="policy reason", code="POLICY")
    assert invoke(monkeypatch, result) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == decision


@pytest.mark.parametrize("result", [None, SimpleNamespace(decision="allow", reason="", code=""),
                                    SimpleNamespace(decision="ask", reason=None, code="")])
def test_invalid_result_fails_closed(monkeypatch, capsys, result):
    assert invoke(monkeypatch, result) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "evaluation failed" in output.err


def test_evaluator_exception_is_not_retried(monkeypatch, capsys):
    evaluator = Mock(side_effect=RuntimeError("state unavailable"))
    monkeypatch.setattr(hook.runner, "evaluate_invocation_result", evaluator, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(PAYLOAD)))
    assert hook.main() == 2
    evaluator.assert_called_once_with(PAYLOAD)
    output = capsys.readouterr()
    assert output.out == ""
    assert "state unavailable" in output.err


def test_compatibility_delegate_preserves_arguments(monkeypatch):
    legacy = Mock(return_value=(2, "legacy reason"))
    monkeypatch.setattr(hook.runner, "evaluate_invocation", legacy)
    gate = object()
    assert hook.evaluate_invocation(PAYLOAD, gate, "/install", "/state") == (2, "legacy reason")
    legacy.assert_called_once_with(PAYLOAD, gate=gate, install_dir="/install", state_dir="/state")
