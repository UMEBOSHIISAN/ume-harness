#!/usr/bin/env python3
"""Tests for the opt-in, offline-capable Harness handoff JSON seam."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from importlib.machinery import SourceFileLoader

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLI_PATH = os.path.join(_ROOT, "bin", "ume-harness")
_loader = SourceFileLoader("ume_harness_preview_cli", _CLI_PATH)
_spec = importlib.util.spec_from_loader("ume_harness_preview_cli", _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)


def _interpretation(*, action: str = "資料を確認する") -> dict:
    return {
        "work_type": "RESEARCH",
        "inferred_intent": "内容を確認する",
        "inferred_deliverable": "確認結果",
        "candidate_actions": [action],
        "clarification_assessments": [],
    }


def _write_json(path, value: str | bytes) -> None:
    mode = "wb" if isinstance(value, bytes) else "w"
    kwargs = {} if isinstance(value, bytes) else {"encoding": "utf-8"}
    with open(path, mode, **kwargs) as stream:
        stream.write(value)


def _run_handoff(tmp_path, interpretation: str | bytes, *extra: str):
    source = tmp_path / "interpretation.json"
    _write_json(source, interpretation)
    request = "この資料を確認する"
    return subprocess.run(
        [
            sys.executable,
            _CLI_PATH,
            "--handoff-json",
            "--request",
            request,
            "--llm-output-file",
            str(source),
            *extra,
        ],
        capture_output=True,
    )


def test_handoff_json_is_json_only_and_hashes_raw_and_canonical_inputs(tmp_path):
    interpretation = _interpretation(action="資料を確認する")
    # Deliberately use a noncanonical key order and non-ASCII text.
    source = json.dumps(
        {
            "clarification_assessments": [],
            "candidate_actions": interpretation["candidate_actions"],
            "inferred_deliverable": interpretation["inferred_deliverable"],
            "inferred_intent": interpretation["inferred_intent"],
            "work_type": interpretation["work_type"],
        },
        ensure_ascii=False,
        indent=2,
    )
    proc = _run_handoff(tmp_path, source)
    assert proc.returncode == 0, proc.stderr.decode()
    assert proc.stderr == b""
    document = json.loads(proc.stdout.decode("utf-8"))
    assert set(document) == {
        "schema_version",
        "source",
        "request_sha256",
        "interpretation_sha256",
        "work_type",
        "classification_status",
        "candidate_actions",
        "required_human_approvals",
        "surfaced_unknowns",
        "clarification_blocked",
        "authority",
        "execution",
    }
    request = "この資料を確認する".encode("utf-8")
    canonical = json.dumps(
        interpretation,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert document == {
        "schema_version": "ume.preview-handoff.v0",
        "source": "offline_interpretation",
        "request_sha256": hashlib.sha256(request).hexdigest(),
        "interpretation_sha256": hashlib.sha256(canonical).hexdigest(),
        "work_type": "RESEARCH",
        "classification_status": "RESOLVED",
        "candidate_actions": ["資料を確認する"],
        "required_human_approvals": [],
        "surfaced_unknowns": [],
        "clarification_blocked": False,
        "authority": False,
        "execution": False,
    }


@pytest.mark.parametrize("encoding,action", [
    ("latin-1", "read café"),
    ("ascii", "資料を確認する"),
    ("utf-16", "資料を確認する"),
])
def test_handoff_stdout_is_utf8_independent_of_locale(tmp_path, monkeypatch, encoding, action):
    monkeypatch.setenv("PYTHONIOENCODING", encoding)
    interpretation = _interpretation(action=action)
    proc = _run_handoff(tmp_path, json.dumps(interpretation, ensure_ascii=False))
    assert proc.returncode == 0, repr(proc.stderr)
    assert proc.stderr == b""
    document = json.loads(proc.stdout.decode("utf-8"))
    assert document["candidate_actions"] == [action]
    canonical = json.dumps(interpretation, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert document["interpretation_sha256"] == hashlib.sha256(canonical).hexdigest()


def test_handoff_json_reuses_normalized_approval_and_ask_states(tmp_path):
    impact = {dimension: "false" for dimension in cli.hla.DIMENSIONS}
    impact["mutation_target"] = "true"
    interpretation = _interpretation(action="ファイルを削除する")
    interpretation["work_type"] = "EDIT_CREATE"
    interpretation["clarification_assessments"] = [
        {
            "question": "対象は何ですか？",
            "missing_information": "対象",
            "impact": impact,
            "basis": {},
        }
    ]
    proc = _run_handoff(tmp_path, json.dumps(interpretation, ensure_ascii=False))
    assert proc.returncode == 1, proc.stderr.decode()
    document = json.loads(proc.stdout.decode("utf-8"))
    assert document["required_human_approvals"] == ["ファイルを削除する"]
    assert document["surfaced_unknowns"] == ["対象は何ですか？"]
    assert document["candidate_actions"] == ["ファイルを削除する"]
    assert document["authority"] is False
    assert document["execution"] is False


def test_handoff_json_conflicts_with_mixed_json(tmp_path):
    source = json.dumps(_interpretation(), ensure_ascii=False)
    proc = _run_handoff(tmp_path, source, "--json")
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"not allowed with argument" in proc.stderr


def test_handoff_json_rejects_malformed_input_without_accepted_json(tmp_path):
    for source in (b"{", b"null", b"[]", b'{"work_type":"RESEARCH"}'):
        proc = _run_handoff(tmp_path, source)
        assert proc.returncode == 3
        assert proc.stdout == b""
        assert b"Traceback" not in proc.stderr


def test_handoff_json_rejects_duplicate_nonfinite_and_invalid_utf8(tmp_path):
    cases = (
        b'{"work_type":"RESEARCH","work_type":"EDIT_CREATE",'
        b'"inferred_intent":"x","inferred_deliverable":"x",'
        b'"candidate_actions":[],"clarification_assessments":[]}',
        b'{"work_type":"RESEARCH","inferred_intent":"x",'
        b'"inferred_deliverable":"x","candidate_actions":[],'
        b'"clarification_assessments":[],"extra":NaN}',
        b'\xff',
    )
    for source in cases:
        proc = _run_handoff(tmp_path, source)
        assert proc.returncode == 3
        assert proc.stdout == b""


def test_handoff_json_rejects_byte_limit_before_parsing(tmp_path):
    proc = _run_handoff(tmp_path, b" " * (cli._HANDOFF_MAX_BYTES + 1))
    assert proc.returncode == 3
    assert proc.stdout == b""


@pytest.mark.parametrize("kind", ["symlink", "parent_symlink", "fifo", "directory"])
def test_handoff_json_refuses_nonregular_or_linked_input_without_blocking(tmp_path, kind):
    original = tmp_path / "original.json"
    original.write_text(json.dumps(_interpretation()), encoding="utf-8")
    before = original.read_bytes()
    source = tmp_path / "input.json"
    if kind == "symlink":
        source.symlink_to(original)
    elif kind == "parent_symlink":
        source.symlink_to(tmp_path, target_is_directory=True)
        source = source / "original.json"
    elif kind == "fifo":
        os.mkfifo(source)
    else:
        source.mkdir()
    proc = subprocess.run(
        [sys.executable, _CLI_PATH, "--handoff-json", "--request", "確認する",
         "--llm-output-file", str(source)],
        capture_output=True, timeout=3,
    )
    assert proc.returncode == 3
    assert proc.stdout == b""
    assert b"Traceback" not in proc.stderr
    assert original.read_bytes() == before


@pytest.mark.parametrize("flag", ["O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"])
def test_handoff_json_refuses_platform_without_required_open_semantics(
    tmp_path, monkeypatch, capsys, flag
):
    source = tmp_path / "original.json"
    source.write_text(json.dumps(_interpretation()), encoding="utf-8")
    monkeypatch.setattr(cli.os, flag, 0)
    code = cli.main(["--handoff-json", "--request", "確認する",
                     "--llm-output-file", str(source)])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "source",
    [
        lambda: json.dumps(_interpretation(action="x" * 16385), ensure_ascii=False),
        lambda: json.dumps([[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]], ensure_ascii=False),
        lambda: json.dumps({str(index): index for index in range(4097)}),
    ],
)
def test_handoff_json_rejects_structural_bounds(tmp_path, source):
    proc = _run_handoff(tmp_path, source())
    assert proc.returncode == 3
    assert proc.stdout == b""


def test_handoff_json_requires_nonempty_request(tmp_path):
    source = json.dumps(_interpretation(), ensure_ascii=False)
    path = tmp_path / "interpretation.json"
    _write_json(path, source)
    proc = subprocess.run(
        [
            sys.executable,
            _CLI_PATH,
            "--handoff-json",
            "--request",
            "   ",
            "--llm-output-file",
            str(path),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3
    assert proc.stdout == b""


def test_handoff_json_stops_before_model_without_offline_source(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "call_claude_for_interpretation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model must not run")),
    )
    code = cli.main(["--handoff-json", "--request", "依頼", "--context", "補足"])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert "--llm-output-file" in captured.err


def test_handoff_json_passes_context_to_normalizer(tmp_path, monkeypatch, capsys):
    source = tmp_path / "interpretation.json"
    _write_json(source, json.dumps(_interpretation(), ensure_ascii=False))
    original_normalize = cli.hla.normalize
    contexts = []

    def normalize_with_record(*args, **kwargs):
        contexts.append(kwargs.get("workspace_context"))
        return original_normalize(*args, **kwargs)

    monkeypatch.setattr(cli.hla, "normalize", normalize_with_record)
    code = cli.main(
        [
            "--handoff-json",
            "--request",
            "依頼",
            "--context",
            "補足",
            "--llm-output-file",
            str(source),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert contexts == ["補足"]
    assert json.loads(captured.out)["source"] == "offline_interpretation"
    assert captured.err == ""


def test_strict_parser_turns_recursion_error_into_bounded_input_error(monkeypatch):
    def recursive_loader(*_args, **_kwargs):
        raise RecursionError("synthetic recursion")

    monkeypatch.setattr(cli.json, "loads", recursive_loader)
    with pytest.raises(cli.HandoffInputError):
        cli._parse_strict_handoff_bytes(b"{}")


class _ShortWriter:
    def __init__(self):
        self.flush_count = 0

    def write(self, text):
        return len(text) - 1

    def flush(self):
        self.flush_count += 1


class _FlushFailureWriter:
    def __init__(self):
        self.write_count = 0

    def write(self, text):
        self.write_count += 1
        return len(text)

    def flush(self):
        raise OSError("synthetic flush")


@pytest.mark.parametrize("binary", [False, True])
def test_handoff_writer_rejects_short_writes_before_flush(binary):
    stream = _ShortWriter()
    with pytest.raises(cli.HandoffOutputError):
        cli.write_handoff_json({"ok": "資料"}, SimpleNamespace(buffer=stream) if binary else stream)
    assert stream.flush_count == 0


@pytest.mark.parametrize("binary", [False, True])
def test_handoff_writer_rejects_flush_failure_after_complete_write(binary):
    stream = _FlushFailureWriter()
    with pytest.raises(cli.HandoffOutputError):
        cli.write_handoff_json({"ok": "資料"}, SimpleNamespace(buffer=stream) if binary else stream)
    assert stream.write_count == 1
