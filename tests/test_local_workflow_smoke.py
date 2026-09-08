"""Synthetic workbook workflow through real hook subprocesses, not a live host UI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_workbook_script_workflow(tmp_path):
    project = tmp_path / "ordinary-project"
    project.mkdir()
    state = tmp_path / "state"
    env = os.environ.copy()
    env["UME_HARNESS_STATE_DIR"] = str(state)
    env["UME_HARNESS_INSTALL_DIR"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def evaluate(tool, data):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "adapters/claude-code/pretooluse_hook.py")],
            input=json.dumps({"tool_name": tool, "tool_input": data,
                              "cwd": str(project), "permission_mode": "default"}),
            text=True, capture_output=True, env=env, cwd=project, timeout=10,
        )

    workbook = project / "fixture.xlsx"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml",
                         '<worksheet><sheetData><row r="358"><c t="inlineStr">'
                         '<is><t>synthetic-title</t></is></c></row></sheetData></worksheet>')
    script = project / "scripts" / "peek.py"
    source = (
        "import zipfile\n"
        "from xml.etree import ElementTree\n"
        "with zipfile.ZipFile('fixture.xlsx') as archive:\n"
        "    root = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))\n"
        "print(root.find('.//t').text)\n"
    )
    write = evaluate("Write", {"file_path": str(script), "content": source})
    assert write.returncode == 0, write.stderr
    assert not write.stdout.strip()  # no extra Harness verdict/false dialog claim
    script.parent.mkdir()
    script.write_text(source, encoding="utf-8")
    run = evaluate("Bash", {"command": "python3 scripts/peek.py"})
    assert run.returncode == 0, run.stderr
    verdict = json.loads(run.stdout)["hookSpecificOutput"]
    assert verdict["permissionDecision"] == "ask"
    # Explicit test-fixture execution only. This does NOT simulate/claim a real
    # host approval UI or automatically execute the command in the adapter.
    executed = subprocess.run([sys.executable, "-B", str(script)], cwd=project,
                              text=True, capture_output=True, timeout=10)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "synthetic-title"
    secret = evaluate("Write", {"file_path": str(project / ".env"), "content": "fixture"})
    assert secret.returncode == 0
    assert json.loads(secret.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not (project / ".env").exists()
