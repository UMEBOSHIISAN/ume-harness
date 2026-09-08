#!/usr/bin/env python3
"""Ownership service for Claude Code hooks and the installed CLI wrapper.

It owns exactly three hook command paths and one exact generated wrapper under
the supplied package root. It never claims artifacts by substring or filename.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
from functools import wraps
import json
import os
import re
import shlex
import shutil
import stat
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple


OWNERSHIP_PROTOCOL_VERSION = "ume-harness-ownership.v1"
PRESENTATION_TIMEOUT_SECONDS = 3


def get_default_settings_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "settings.json")


def get_adapter_hook_paths(pkg_root: str) -> Dict[str, str]:
    adapter_dir = os.path.join(os.path.abspath(pkg_root), "adapters", "claude-code")
    return {
        "PreToolUse": os.path.join(adapter_dir, "pretooluse_hook.py"),
        "PermissionRequest": os.path.join(adapter_dir, "permission_request_hook.py"),
        "PostToolUseFailure": os.path.join(adapter_dir, "posttooluse_failure_hook.py"),
    }


def get_adapter_hook_commands(pkg_root: str) -> Dict[str, str]:
    """Return shell-safe command strings for the three owned hook paths."""
    return {
        event_name: shlex.quote(path)
        for event_name, path in get_adapter_hook_paths(pkg_root).items()
    }


def _owned_hook_command_variants(pkg_root: str) -> Dict[str, frozenset[str]]:
    """Return current commands plus exact legacy unquoted commands."""
    paths = get_adapter_hook_paths(pkg_root)
    commands = get_adapter_hook_commands(pkg_root)
    return {
        event_name: frozenset({paths[event_name], commands[event_name]})
        for event_name in paths
    }


def render_cli_wrapper(pkg_root: str, *, bytecode_safe: bool = True) -> str:
    cli_path = os.path.join(os.path.abspath(pkg_root), "bin", "ume-harness")
    quoted_cli_path = shlex.quote(cli_path)
    python_args = "python3 -B" if bytecode_safe else "python3"
    return (
        "#!/usr/bin/env bash\n"
        "# ume-harness launcher wrapper\n"
        f'exec {python_args} {quoted_cli_path} "$@"\n'
    )


def cli_wrapper_is_owned(wrapper_path: str, pkg_root: str) -> bool:
    try:
        metadata = os.lstat(wrapper_path)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            return False
        with open(wrapper_path, "rb") as f:
            actual = f.read()
    except OSError:
        return False
    owned_variants = (
        render_cli_wrapper(pkg_root).encode("utf-8"),
        render_cli_wrapper(pkg_root, bytecode_safe=False).encode("utf-8"),
    )
    return actual in owned_variants


def inspect_hook_registrations(data: Dict[str, Any], pkg_root: str, *, settings_path: str) -> Dict[str, Any]:
    """Inventory one settings object; recognition never grants removal ownership.

    Only direct absolute paths, optionally preceded by python/python3, are
    interpreted. Shell wrappers and expansions remain ambiguous.
    """
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError("settings hooks must be an object")
    owned = _owned_hook_command_variants(pkg_root)
    paths = get_adapter_hook_paths(pkg_root)
    settings_dir = os.path.dirname(os.path.abspath(settings_path))
    legacy_path = (
        os.path.join(settings_dir, "hooks", "unified_tool_classifier.py")
        if os.path.basename(settings_dir) == ".claude" else None
    )
    records = []
    for event, groups in data.get("hooks", {}).items():
        if not isinstance(groups, list):
            raise ValueError("hook event must be an array")
        for gi, group in enumerate(groups):
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("hook group must contain a hooks array")
            for hi, hook in enumerate(group.get("hooks", [])):
                command = hook.get("command") if isinstance(hook, dict) else None
                classification = "ambiguous"
                is_owned = False
                target = None
                if isinstance(hook, dict) and hook.get("type") != "command":
                    classification = "non_command"
                elif isinstance(command, str):
                    is_owned = command in owned.get(event, ())
                    if is_owned:
                        classification = "current"
                        target = paths[event]
                    else:
                        try:
                            tokens = _command_tokens(command)
                        except ValueError:
                            tokens = []
                        if len(tokens) == 2 and tokens[0] in ("python", "python3"):
                            tokens = tokens[1:]
                        if len(tokens) == 1 and os.path.isabs(tokens[0]) and not any(
                            char in tokens[0] for char in "$`*?[]{}\n"
                        ):
                            target = tokens[0]
                            if target != os.path.normpath(target):
                                classification = "ambiguous"
                            elif event == "PreToolUse" and target == legacy_path:
                                classification = "legacy_classifier"
                            elif target == paths.get(event):
                                classification = "current_unowned"
                            elif event in paths and re.search(
                                r"/ume-harness/v[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?/adapters/claude-code/"
                                + re.escape(os.path.basename(paths[event])) + r"$", target
                            ):
                                classification = "other_version_reference"
                            else:
                                classification = "unrelated"
                records.append({"event": event, "matcher": group.get("matcher"),
                                "group_index": gi, "hook_index": hi, "command": command,
                                "classification": classification, "owned": is_owned,
                                "target": target,
                                "timeout": hook.get("timeout") if isinstance(hook, dict) else None})
    pre = [r for r in records if r["event"] == "PreToolUse"]
    current = [r for r in pre if r["classification"] in ("current", "current_unowned")]
    findings = []
    if len(current) > 1:
        findings.append("duplicate_current_pretooluse")
    if current and any(r["classification"] == "legacy_classifier" for r in pre):
        findings.append("legacy_current_coexistence")
    if current and any(r["classification"] == "other_version_reference" for r in pre):
        findings.append("multiple_version_pretooluse")
    for event in ("PermissionRequest", "PostToolUseFailure"):
        if sum(r["event"] == event and r["classification"] in ("current", "current_unowned") for r in records) > 1:
            findings.append("duplicate_current_" + event.lower())
    conflicting = any(r["classification"] in (
        "legacy_classifier", "other_version_reference", "current_unowned"
    ) for r in records)
    connected = {r["event"] for r in records if r["owned"]}
    complete = {r["event"] for r in records if r["owned"] and r["matcher"] in (None, "", "*")}
    if findings or conflicting:
        connected_mode = "conflict"
    elif not connected:
        connected_mode = "disconnected"
    elif connected == complete == set(paths):
        connected_mode = "managed"
    elif connected == complete == {"PermissionRequest", "PostToolUseFailure"}:
        connected_mode = "presentation"
    else:
        connected_mode = "partial"
    return {"settings_path": settings_path, "scope": "file inventory only",
            "connected_mode": connected_mode,
            "live_effective_settings": "unknown", "restart_status": "unknown; verify in a fresh host",
            "session_hook_recognition": "unknown", "actual_hook_event": "unknown",
            "matcher_overlap": "not evaluated", "profile_diagnostics": "separate health check --state-dir required",
            "registrations": records, "findings": findings}


def inspect_settings_file(settings_path: str, pkg_root: str) -> Dict[str, Any]:
    data, exists = _read_settings(settings_path)
    result = inspect_hook_registrations(data, pkg_root, settings_path=settings_path)
    result["file_exists"] = exists
    if not exists:
        result["connected_mode"] = "absent"
    return result


def generate_preview(settings_path: str, hook_paths: Dict[str, str]) -> str:
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🇯🇵 Claude Code 日本語通訳（翻訳こんにゃく）の接続設定",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "【変更対象ファイル】",
        f"  {settings_path}",
        "",
        "【追加される日本語通訳フック】",
        "  PermissionRequest: 手動許可プロンプト直前の詳細解説",
        f"     -> {hook_paths.get('PermissionRequest')}",
        "  PostToolUseFailure: エラー発生時の事実ベースの案内",
        f"     -> {hook_paths.get('PostToolUseFailure')}",
        "",
        "【安全の保証】",
        "  ✓ 変更前に既存設定のバックアップを自動作成します",
        "  ✓ `ume-harness setup --disconnect` は所有する全3種類のフックを取り外します",
        "  ✓ その他の設定・イベント・matcher・hookには触れません",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if "PreToolUse" in hook_paths:
        lines.insert(12, f"  PreToolUse: managed実行制限（明示選択または既存接続を保持） -> {hook_paths['PreToolUse']}")
        lines.insert(13, "  managedは保守的な評価です。未知tool・shell処理等で追加確認や拒否があり、任意scriptの安全性は保証しません。")
    else:
        lines.insert(12, "  presentation: 表示用2本。実行制限の追加は setup --managed で明示選択します。")
    return "\n".join(lines)


def _connection_summary(data: Dict[str, Any], pkg_root: str, settings_path: str) -> str:
    """Describe registered state, never claim a live session's enforcement."""
    report = inspect_hook_registrations(data, pkg_root, settings_path=settings_path)
    mode = report["connected_mode"]
    lines = [f"登録結果: {mode}（この設定ファイルのみ）"]
    if mode == "presentation":
        lines.append("説明のみ: UMEの追加実行制限・Lease・path制限を強制しません。")
    elif mode == "managed":
        lines.append("厳格接続です。説明だけには移行していません。移行は --disconnect 後に通常setupしてください。")
    else:
        lines.append("接続範囲は未確認です。登録診断を確認し、所有不明のhookは管理者に確認してください。")
    lines.append("Claude Codeの権限設定は変更しません。nativeの許可は今回の依頼範囲の承認ではありません。")
    lines.append("依頼範囲外の実装・重大操作の防止を、本接続だけで保証しません。")
    lines.append("CCセッションでの設定認識・実イベントの発火は未確認です。")
    if any(r["owned"] and r["event"] in ("PermissionRequest", "PostToolUseFailure")
           and r["timeout"] != PRESENTATION_TIMEOUT_SECONDS for r in report["registrations"]):
        lines.append("既存timeout設定を維持しました。説明hookの短い時間上限は未確認です。変更は対象を確認して再接続してください。")
    if any(r["classification"] == "ambiguous" for r in report["registrations"]):
        lines.append("所有不明のラッパー等は変更していません。その動作は未確認です。")
    return "\n".join(lines)


def _settings_revision(settings_path: str):
    """Capture exact bytes and metadata; missing is a distinct revision."""
    try:
        fd = os.open(settings_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError("settings.json symlinks are unsupported") from exc
        raise
    with os.fdopen(fd, "rb") as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("settings.json must be a regular file")
        content = f.read()
        after = os.fstat(f.fileno())
    fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid,
                        s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if fields(before) != fields(after) or fields(after) != fields(os.lstat(settings_path)):
        raise SettingsConflictError("settings changed during read")
    return content, fields(after)


def _read_settings_snapshot(settings_path: str):
    revision = _settings_revision(settings_path)
    if revision is None:
        return {}, False, revision
    content = revision[0].decode("utf-8").strip()
    if not content:
        return {}, True, revision
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("settings.json のルートは JSON object である必要があります。")
    return data, True, revision


def _read_settings(settings_path: str) -> Tuple[Dict[str, Any], bool]:
    data, existed, _ = _read_settings_snapshot(settings_path)
    return data, existed


class SettingsConflictError(OSError):
    """An external update was detected before replacement."""


class SettingsPostCommitConflictError(OSError):
    """Replacement happened, but its expected result could not be verified."""


def _settings_writer(operation):
    """One persistent sidecar inode for UME writers, never renamed or unlinked.

    Non-cooperating applications remain outside this advisory lock. No retries.
    Canonicalize the parent, not the final component (settings symlinks fail).
    """
    @wraps(operation)
    def locked(pkg_root, settings_path=None, *args, **kwargs):
        path = os.path.abspath(settings_path or get_default_settings_path())
        path = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
        fd = None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            lock_path = path + ".ume-harness.lock"
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsupported settings lock")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            current = os.lstat(lock_path)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError("settings lock changed")
        except (OSError, ValueError):
            if fd is not None:
                os.close(fd)
            return False, "設定更新の競合またはロック取得失敗：未反映です。別の設定更新がないことを確認してください。"
        try:
            return operation(pkg_root, path, *args, **kwargs)
        finally:
            os.close(fd)
    return locked


class SettingsCommitDurabilityError(OSError):
    """The settings replacement committed but directory durability was unproven."""


_UNSPECIFIED_REVISION = object()


def _atomic_write_settings(settings_path: str, data: Dict[str, Any], *,
                           expected_revision=_UNSPECIFIED_REVISION) -> None:
    settings_dir = os.path.dirname(settings_path)
    os.makedirs(settings_dir, exist_ok=True)

    # Preserve the security metadata of an existing settings file.  Replacing
    # the pathname with a fresh mkstemp file would otherwise silently reset
    # custom mode/ownership (and make a settings update a privilege boundary).
    existing = None
    try:
        existing = os.lstat(settings_path)
    except FileNotFoundError:
        pass
    if existing is not None:
        if stat.S_ISLNK(existing.st_mode):
            raise ValueError("settings.json symlinks are unsupported because ownership cannot be preserved safely")
        if not stat.S_ISREG(existing.st_mode):
            raise ValueError("settings.json must be a regular file")

    fd, temp_path = tempfile.mkstemp(dir=settings_dir, prefix="settings_merge_", text=True)
    committed = False
    try:
        target_mode = stat.S_IMODE(existing.st_mode) if existing is not None else 0o600
        os.fchmod(fd, target_mode)
        if existing is not None and hasattr(os, "fchown"):
            os.fchown(fd, existing.st_uid, existing.st_gid)

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        if expected_revision is not _UNSPECIFIED_REVISION:
            if _settings_revision(settings_path) != expected_revision:
                raise SettingsConflictError("settings changed before replacement")
        # This comparison and replace are NOT a CAS against non-cooperating writers.
        os.replace(temp_path, settings_path)
        committed = True

        try:
            actual = _settings_revision(settings_path)
            expected_bytes = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            if actual is None or actual[0] != expected_bytes:
                raise ValueError("settings changed after replacement")
        except Exception as exc:
            raise SettingsPostCommitConflictError("settings replacement outcome unconfirmed") from exc

        # Make the rename durable as well as the file contents.  This is a
        # no-op only on platforms that cannot open directories for fsync; the
        # supported POSIX hosts provide it.
        dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        dir_fd = os.open(settings_dir, dir_flags)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception as exc:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        if fd >= 0:
            os.close(fd)
        if isinstance(exc, SettingsPostCommitConflictError):
            raise
        if committed:
            raise SettingsCommitDurabilityError(
                "settings replacement committed but directory durability could not be confirmed"
            ) from exc
        raise


def _remove_owned_commands(
    data: Dict[str, Any],
    owned_commands_by_event: Dict[str, frozenset[str]],
) -> bool:
    """Remove exact canonical commands only from the three owned events."""
    hooks = data.get("hooks")
    if hooks is None:
        return False
    if not isinstance(hooks, dict):
        raise ValueError("settings.json の hooks は JSON object である必要があります。")

    changed = False
    for event_name, owned_commands in owned_commands_by_event.items():
        if event_name not in hooks:
            continue
        event_groups = hooks[event_name]
        if not isinstance(event_groups, list):
            raise ValueError(f"settings.json の hooks.{event_name} は配列である必要があります。")

        new_groups: List[Any] = []
        for group in event_groups:
            if not isinstance(group, dict):
                raise ValueError(f"settings.json の hooks.{event_name} に不正な要素があります。")
            group_hooks = group.get("hooks", [])
            if not isinstance(group_hooks, list):
                raise ValueError(f"settings.json の hooks.{event_name}[].hooks は配列である必要があります。")

            kept_hooks: List[Any] = []
            for hook_item in group_hooks:
                is_owned = (
                    isinstance(hook_item, dict)
                    and hook_item.get("type") == "command"
                    and hook_item.get("command") in owned_commands
                )
                if is_owned:
                    changed = True
                else:
                    kept_hooks.append(hook_item)

            if kept_hooks:
                if len(kept_hooks) != len(group_hooks):
                    new_group = dict(group)
                    new_group["hooks"] = kept_hooks
                    new_groups.append(new_group)
                else:
                    new_groups.append(group)
            elif group_hooks:
                changed = True
                generated_group = (
                    set(group) == {"matcher", "hooks"}
                    and group.get("matcher") == "*"
                    and len(group_hooks) == 1
                    and isinstance(group_hooks[0], dict)
                    and (set(group_hooks[0]) == {"type", "command"}
                         or (event_name in ("PermissionRequest", "PostToolUseFailure")
                             and set(group_hooks[0]) == {"type", "command", "timeout"}
                             and group_hooks[0]["timeout"] == PRESENTATION_TIMEOUT_SECONDS))
                    and group_hooks[0].get("type") == "command"
                    and group_hooks[0].get("command") in owned_commands
                )
                if not generated_group:
                    preserved_group = dict(group)
                    preserved_group["hooks"] = []
                    new_groups.append(preserved_group)
            else:
                new_groups.append(group)

        if new_groups:
            hooks[event_name] = new_groups
        else:
            del hooks[event_name]
    return changed


def contains_owned_hooks(data: Dict[str, Any], pkg_root: str) -> bool:
    """Return whether any exact canonical setup command remains active."""
    hooks = data.get("hooks")
    if hooks is None:
        return False
    if not isinstance(hooks, dict):
        raise ValueError("settings.json の hooks は JSON object である必要があります。")

    for event_name, owned_commands in _owned_hook_command_variants(pkg_root).items():
        event_groups = hooks.get(event_name, [])
        if not isinstance(event_groups, list):
            raise ValueError(f"settings.json の hooks.{event_name} は配列である必要があります。")
        for group in event_groups:
            if not isinstance(group, dict):
                raise ValueError(f"settings.json の hooks.{event_name} に不正な要素があります。")
            group_hooks = group.get("hooks", [])
            if not isinstance(group_hooks, list):
                raise ValueError(f"settings.json の hooks.{event_name}[].hooks は配列である必要があります。")
            for hook_item in group_hooks:
                if (
                    isinstance(hook_item, dict)
                    and hook_item.get("type") == "command"
                    and hook_item.get("command") in owned_commands
                ):
                    return True
    return False


def _command_tokens(command: str) -> List[str]:
    """Split a shell command without executing it, keeping control operators separate."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


_ANSI_C_QUOTE_PATTERN = re.compile(r"\$'((?:\\.|[^'])*)'")


def _decode_ansi_c_payload(payload: str) -> str:
    """Decode the bounded ANSI-C escapes that can construct a filesystem path."""
    simple = {
        "a": "\a",
        "b": "\b",
        "e": "\x1b",
        "E": "\x1b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        "'": "'",
        '"': '"',
    }
    decoded = []
    index = 0
    while index < len(payload):
        if payload[index] != "\\":
            decoded.append(payload[index])
            index += 1
            continue
        index += 1
        if index >= len(payload):
            decoded.append("\\")
            break
        escape = payload[index]
        if escape == "\n":
            index += 1
            continue
        if escape in simple:
            decoded.append(simple[escape])
            index += 1
            continue
        if escape in {"x", "u", "U"}:
            widths = {"x": 2, "u": 4, "U": 8}
            width = widths[escape]
            digits = payload[index + 1:index + 1 + width]
            if escape == "x":
                match = re.match(r"[0-9A-Fa-f]{1,2}", digits)
                digits = match.group(0) if match else ""
            elif len(digits) != width or not all(
                char in "0123456789abcdefABCDEF" for char in digits
            ):
                digits = ""
            if digits:
                decoded.append(chr(int(digits, 16)))
                index += 1 + len(digits)
                continue
        if escape in "01234567":
            match = re.match(r"[0-7]{1,3}", payload[index:])
            digits = match.group(0)
            decoded.append(chr(int(digits, 8)))
            index += len(digits)
            continue
        if escape == "c" and index + 1 < len(payload):
            decoded.append(chr(ord(payload[index + 1].upper()) & 0x1F))
            index += 2
            continue
        decoded.extend(("\\", escape))
        index += 1
    return "".join(decoded)


def _shell_reference_form(value: str) -> str:
    """Normalize non-semantic shell quoting for conservative path detection."""
    normalized = value.replace("\\\n", "")
    normalized = _ANSI_C_QUOTE_PATTERN.sub(
        lambda match: _decode_ansi_c_payload(match.group(1)),
        normalized,
    )
    normalized = normalized.replace('$"', '"')
    expanded = os.path.expandvars(normalized)
    return expanded.replace("\\", "").replace("'", "").replace('"', "")


def _is_shell_parameter_value_boundary(command: str, index: int) -> bool:
    """Return whether index follows a parameter-expansion value operator."""
    prefix = command[:index]
    opening = prefix.rfind("${")
    if opening < 0 or prefix.rfind("}") > opening:
        return False
    expression = prefix[opening + 2:]
    for operator in (":-", ":=", ":+", ":?", "-", "=", "+", "?"):
        if not expression.endswith(operator):
            continue
        parameter = expression[:-len(operator)]
        return bool(parameter) and (
            all(char.isalnum() or char == "_" for char in parameter)
            or parameter in {"@", "*", "#", "?", "-", "$", "!"}
        )
    return False


def _is_path_list_assignment_boundary(command: str, index: int) -> bool:
    """Return whether index follows ':' inside a *PATH shell assignment."""
    if index == 0 or command[index - 1] != ":":
        return False
    prefix = command[:index]
    for equals in range(len(prefix) - 1, -1, -1):
        if prefix[equals] != "=":
            continue
        name_end = equals
        if name_end > 0 and prefix[name_end - 1] == "+":
            name_end -= 1
        name_start = name_end
        while name_start > 0 and (
            prefix[name_start - 1].isalnum() or prefix[name_start - 1] == "_"
        ):
            name_start -= 1
        name = prefix[name_start:name_end]
        if not name or (name != "PATH" and not name.endswith("PATH")):
            continue
        if name_start > 0 and (
            not prefix[name_start - 1].isspace()
            and prefix[name_start - 1] not in ";|&("
        ):
            continue
        value = prefix[equals + 1:]
        depth = 0
        has_top_level_whitespace = False
        for position, char in enumerate(value):
            if char == "(" and (depth > 0 or (position > 0 and value[position - 1] == "$")):
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            elif char.isspace() and depth == 0:
                has_top_level_whitespace = True
                break
        if (
            value.endswith(":")
            and not has_top_level_whitespace
            and not any(separator in value for separator in ";|&\n")
        ):
            return True
    return False


def _is_path_assignment_value_boundary(command: str, index: int) -> bool:
    """Return whether index begins the value of a literal ``*PATH=`` word."""
    if index == 0 or command[index - 1] != "=":
        return False
    name_end = index - 1
    if name_end > 0 and command[name_end - 1] == "+":
        name_end -= 1
    name_start = name_end
    while name_start > 0 and (
        command[name_start - 1].isalnum() or command[name_start - 1] == "_"
    ):
        name_start -= 1
    name = command[name_start:name_end]
    return bool(name) and (name == "PATH" or name.endswith("PATH")) and (
        name_start == 0
        or command[name_start - 1].isspace()
        or command[name_start - 1] in ";|&("
    )


_PATH_ASSIGNMENT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_]*PATH)\+?="
)

_BRACE_RANGE_PATTERN = re.compile(
    r"\{([-+]?\d+|[A-Za-z])\.\.([-+]?\d+|[A-Za-z])(?:\.\.([-+]?\d+))?\}"
)


def _brace_range_alternatives(match) -> List[str]:
    """Expand a finite Bash-style integer or ASCII-letter brace range."""
    start_text, stop_text, step_text = match.groups()
    numeric = start_text.lstrip("-+").isdigit() and stop_text.lstrip("-+").isdigit()
    alphabetic = (
        len(start_text) == 1
        and len(stop_text) == 1
        and start_text.isalpha()
        and stop_text.isalpha()
    )
    if not numeric and not alphabetic:
        return []
    start = int(start_text) if numeric else ord(start_text)
    stop = int(stop_text) if numeric else ord(stop_text)
    step = abs(int(step_text)) if step_text is not None else 1
    if step == 0:
        step = 1
    if start > stop:
        step = -step
    values = range(start, stop + (1 if step > 0 else -1), step)
    alternatives = []
    for value in values:
        if numeric:
            if start == stop:
                rendered = str(start) if start_text.startswith("+") else start_text
            else:
                rendered = str(value)
                start_digits = start_text.lstrip("-+")
                stop_digits = stop_text.lstrip("-+")
                if (
                    (len(start_digits) > 1 and start_digits.startswith("0"))
                    or (len(stop_digits) > 1 and stop_digits.startswith("0"))
                ):
                    rendered = rendered.zfill(max(len(start_text), len(stop_text)))
        else:
            rendered = chr(value)
        alternatives.append(rendered)
        if len(alternatives) > 256:
            raise ValueError("shell expansion form count exceeds uninstall safety limit")
    return alternatives


def _empty_expansion_forms(value: str) -> set[str]:
    """Return literal and stable empty-expansion forms without evaluation."""
    raw_forms = {value}
    pending = [value]
    while pending:
        current = pending.pop()
        candidates = []
        collapsed = re.sub(r"\$\{[^{}]*\}", "", current)
        collapsed = re.sub(r"\$\([^()]*\)", "", collapsed)
        collapsed = re.sub(r"`[^`]*`", "", collapsed)
        collapsed = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*", "", collapsed)
        if collapsed != current:
            candidates.append(collapsed)
        brace = re.search(r"\{([^{}]*,[^{}]*)\}", current)
        if brace:
            for alternative in brace.group(1).split(","):
                candidates.append(
                    current[:brace.start()] + alternative + current[brace.end():]
                )
        brace_range = _BRACE_RANGE_PATTERN.search(current)
        if brace_range:
            for alternative in _brace_range_alternatives(brace_range):
                candidates.append(
                    current[:brace_range.start()]
                    + alternative
                    + current[brace_range.end():]
                )
        for candidate in candidates:
            if candidate in raw_forms:
                continue
            if len(raw_forms) >= 256:
                raise ValueError("shell expansion form count exceeds uninstall safety limit")
            raw_forms.add(candidate)
            pending.append(candidate)
    return {_shell_reference_form(form) for form in raw_forms}


def _normalized_path_component(value: str) -> str:
    normalized = os.path.realpath(os.path.expanduser(value.strip()))
    if normalized.startswith(os.sep * 2):
        normalized = os.sep + normalized.lstrip(os.sep)
    return normalized


def _path_token_references(token: str, references) -> bool:
    """Check one shell token containing a literal ``*PATH=`` assignment."""
    normalized = _shell_reference_form(token)
    for match in _PATH_ASSIGNMENT_PATTERN.finditer(normalized):
        value = normalized[match.end():]
        for entry in value.split(":"):
            normalized_entry = _normalized_path_component(entry)
            for reference in references:
                normalized_reference = _normalized_path_component(reference)
                if (
                    normalized_entry == normalized_reference
                    or normalized_entry.startswith(normalized_reference + os.sep)
                ):
                    return True
    return False


def _contains_bare_hook_basename(command: str, hook_basenames) -> bool:
    for basename in hook_basenames:
        if re.search(
            rf"(?<![A-Za-z0-9_./-]){re.escape(basename)}(?![A-Za-z0-9_.-])",
            command,
        ):
            return True
    return False


def _assignment_value_references(token: str, references) -> bool:
    """Return whether an assignment value names a reference or its descendant."""
    for normalized in _empty_expansion_forms(token):
        if "=" not in normalized:
            continue
        value = normalized.split("=", 1)[1]
        for reference in references:
            normalized_reference = _normalized_path_component(reference)
            for entry in value.split(":"):
                normalized_entry = _normalized_path_component(entry)
                if (
                    normalized_entry == normalized_reference
                    or normalized_entry.startswith(normalized_reference + os.sep)
                ):
                    return True
    return False


def _assignment_token_references_adapter(token: str, references) -> bool:
    """Detect an adapter path in an assignment token with an opaque name."""
    if "=" not in token:
        return False
    raw_name = token.split("=", 1)[0]
    name_is_path = any(
        re.fullmatch(r"[A-Za-z0-9_]*PATH", normalized_name)
        for normalized_name in _empty_expansion_forms(raw_name)
    )
    name_is_dynamic = bool(re.search(r"\$(?:\{|\(|'|\"|[A-Za-z_])|`", raw_name))
    if not name_is_path and not name_is_dynamic:
        return False
    return _assignment_value_references(token, references)


def _contains_referenced_assignment_path(command: str, tokens, references) -> bool:
    """Detect a payload-valued variable that is referenced by a later shell layer."""
    for reference in references:
        start = 0
        while True:
            index = command.find(reference, start)
            if index < 0:
                break
            equals = command.rfind("=", 0, index)
            suffix = command[index + len(reference):]
            if equals >= 0 and not any(
                separator in command[equals + 1:index]
                for separator in ";|&\n"
            ) and re.search(r"\$|`", suffix):
                return True
            start = index + 1

    for token in tokens:
        if "=" not in token:
            continue
        raw_name = token.split("=", 1)[0]
        normalized_name = _shell_reference_form(raw_name)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized_name):
            continue
        if not _assignment_value_references(token, references):
            continue
        usage = re.compile(
            rf"\$(?:{re.escape(normalized_name)}(?![A-Za-z0-9_])|"
            rf"\{{{re.escape(normalized_name)}(?:\}}|[^A-Za-z0-9_]))"
        )
        if usage.search(command):
            return True

    used_names = {
        direct or braced
        for direct, braced in re.findall(
            r"\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*))",
            command,
        )
    }
    has_dynamic_assignment_name = bool(
        re.search(
            r"(?:\$'(?:\\.|[^'])*'|\$\([^)]*\)|`[^`]*`|\$\{[^}]*\})[^=]*=",
            command,
        )
    )
    if not used_names:
        return False
    for form in _empty_expansion_forms(command):
        for match in re.finditer(
            r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)=([^\s;|&]+)",
            form,
        ):
            assigned_name, assigned_value = match.groups()
            if not _assignment_value_references(
                f"{assigned_name}={assigned_value}",
                references,
            ):
                continue
            for used_name in used_names:
                if assigned_name == used_name:
                    return True
                if not has_dynamic_assignment_name:
                    continue
                remaining = iter(used_name)
                if all(char in remaining for char in assigned_name):
                    return True
    return False


def _contains_path_list_assignment_reference(
    command: str,
    references,
    hook_basenames,
    tokens,
) -> bool:
    """Fail closed for PATH-based dispatch of a shipped hook basename.

    This uninstall guard does not interpret shell grammar. Quote removal is
    sufficient to identify a ``*PATH=`` assignment and a shipped hook basename;
    that combination is unsafe even when the PATH value is dynamically or
    ambiguously constructed. Literal assignments without a hook basename are
    checked token-by-token so unrelated later arguments remain permitted.
    """
    command_forms = _empty_expansion_forms(command)
    has_bare_hook = any(
        _contains_bare_hook_basename(form, hook_basenames)
        for form in command_forms
    )
    if has_bare_hook and any(
        _assignment_token_references_adapter(token, references)
        for token in (*tokens, *command_forms)
    ):
        return True

    has_dynamic_shell_value = bool(
        re.search(r"\$(?:\{|\(|[A-Za-z_])|`", command)
    )
    if has_dynamic_shell_value:
        for normalized_command in command_forms:
            if _PATH_ASSIGNMENT_PATTERN.search(
                normalized_command
            ) and _contains_bare_hook_basename(normalized_command, hook_basenames):
                return True
    return any(_path_token_references(token, references) for token in tokens)


def _contains_shell_path_reference(command: str, references) -> bool:
    """Match a normalized path only at shell/path component boundaries."""
    normalized_command = _shell_reference_form(command)
    for reference in references:
        start = 0
        while True:
            index = normalized_command.find(reference, start)
            if index < 0:
                break
            end = index + len(reference)
            before_ok = (
                index == 0
                or normalized_command[index - 1].isspace()
                or normalized_command[index - 1] in {";", "|", "&", "("}
                or _is_path_assignment_value_boundary(normalized_command, index)
                or _is_shell_parameter_value_boundary(normalized_command, index)
                or _is_path_list_assignment_boundary(normalized_command, index)
            )
            after_ok = (
                end == len(normalized_command)
                or normalized_command[end] == os.sep
                or normalized_command[end].isspace()
                or normalized_command[end] in ":;|&)"
            )
            if before_ok and after_ok:
                return True
            start = index + 1
    return False


def contains_noncanonical_hook_reference(data: Dict[str, Any], pkg_root: str) -> bool:
    """Detect, but never claim, commands that invoke a canonical hook path indirectly.

    Uninstall uses this as a fail-closed dangling-reference check. Exact canonical
    commands are handled by ownership-scoped disconnect; wrapped commands remain
    user-owned and therefore block payload deletion instead of being removed.
    Ambiguous ``*PATH=`` references to the adapter directory also block deletion.
    """
    hooks = data.get("hooks")
    if hooks is None:
        return False
    if not isinstance(hooks, dict):
        raise ValueError("settings.json の hooks は JSON object である必要があります。")

    canonical_paths = set(get_adapter_hook_paths(pkg_root).values())
    absolute_pkg_root = os.path.abspath(pkg_root)
    pkg_root_references = {absolute_pkg_root}
    home = os.path.expanduser("~")
    if absolute_pkg_root.startswith(home + os.sep):
        home_relative_root = absolute_pkg_root[len(home):]
        pkg_root_references.add("~" + home_relative_root)
        pkg_root_references.add(
            "~" + os.path.basename(home.rstrip(os.sep)) + home_relative_root
        )
    normalized_pkg_roots = {
        _shell_reference_form(reference.rstrip(os.sep))
        for reference in pkg_root_references
    }
    adapter_references = {os.path.dirname(path) for path in canonical_paths}
    for reference in tuple(adapter_references):
        if reference.startswith(home + os.sep):
            home_relative_adapter = reference[len(home):]
            adapter_references.add("~" + home_relative_adapter)
            adapter_references.add(
                "~" + os.path.basename(home.rstrip(os.sep)) + home_relative_adapter
            )
    normalized_adapter_references = {
        _shell_reference_form(reference.rstrip(os.sep))
        for reference in adapter_references
    }
    hook_basenames = {os.path.basename(path) for path in canonical_paths}
    for event_name, event_groups in hooks.items():
        if not isinstance(event_groups, list):
            raise ValueError(f"settings.json の hooks.{event_name} は配列である必要があります。")
        for group in event_groups:
            if not isinstance(group, dict):
                raise ValueError(f"settings.json の hooks.{event_name} に不正な要素があります。")
            group_hooks = group.get("hooks", [])
            if not isinstance(group_hooks, list):
                raise ValueError(f"settings.json の hooks.{event_name}[].hooks は配列である必要があります。")
            for hook_item in group_hooks:
                if not isinstance(hook_item, dict) or hook_item.get("type") != "command":
                    continue
                command = hook_item.get("command")
                if not isinstance(command, str):
                    continue
                try:
                    tokens = _command_tokens(command)
                except ValueError:
                    raise ValueError(
                        f"settings.json の hooks.{event_name} に解析不能な command があります。"
                    )
                if (
                    _contains_shell_path_reference(command, normalized_pkg_roots)
                    or _contains_referenced_assignment_path(
                        command,
                        tokens,
                        normalized_pkg_roots,
                    )
                    or _contains_path_list_assignment_reference(
                        command,
                        normalized_adapter_references,
                        hook_basenames,
                        tokens,
                    )
                ):
                    return True
                expanded_tokens = {
                    os.path.abspath(os.path.expandvars(os.path.expanduser(token)))
                    for token in tokens
                }
                if canonical_paths.intersection(tokens) or canonical_paths.intersection(expanded_tokens):
                    return True
    return False


def _event_contains_owned_command(event_name: str, event_groups: Any, owned_command: str) -> bool:
    if not isinstance(event_groups, list):
        raise ValueError(f"settings.json の hooks.{event_name} は配列である必要があります。")
    for group in event_groups:
        if not isinstance(group, dict):
            raise ValueError(f"settings.json の hooks.{event_name} に不正な要素があります。")
        group_hooks = group.get("hooks", [])
        if not isinstance(group_hooks, list):
            raise ValueError(f"settings.json の hooks.{event_name}[].hooks は配列である必要があります。")
        for hook_item in group_hooks:
            if (
                isinstance(hook_item, dict)
                and hook_item.get("type") == "command"
                and hook_item.get("command") == owned_command
            ):
                return True
    return False


@_settings_writer
def install_hooks_to_settings(
    pkg_root: str,
    settings_path: Optional[str] = None,
    *,
    managed: bool = False,
) -> Tuple[bool, str]:
    """Merge presentation hooks; add execution enforcement only by explicit opt-in.

    Existing owned PreToolUse registrations remain untouched by default setup.
    The settings themselves are the only record of the connection profile.
    """
    if not settings_path:
        settings_path = get_default_settings_path()
    settings_path = os.path.abspath(settings_path)

    hook_paths = get_adapter_hook_paths(pkg_root)
    for hpath in hook_paths.values():
        if not os.path.exists(hpath):
            return False, f"フックファイルが見つかりません: {hpath}"

    try:
        current_data, existed, revision = _read_settings_snapshot(settings_path)
        inventory = inspect_hook_registrations(current_data, pkg_root, settings_path=settings_path)
        if inventory["connected_mode"] == "conflict":
            return False, "登録状態 conflict: 設定は変更していません。登録診断で重複・旧版を確認し、所有元のCLIで明示的に切断してください。"
    except Exception as e:
        return False, f"既存の settings.json の読み込みに失敗しました: {e}"

    hook_commands = get_adapter_hook_commands(pkg_root)
    if not managed:
        hook_commands.pop("PreToolUse")
    changed = False
    try:
        # Quote exact legacy commands in place: matcher, timeout, metadata and
        # adjacent third-party entries remain owned by the existing settings.
        for record in inventory["registrations"]:
            event = record["event"]
            if (record["owned"] and event in hook_commands
                    and record["command"] == hook_paths[event]
                    and record["command"] != hook_commands[event]):
                entry = current_data["hooks"][event][record["group_index"]]["hooks"][record["hook_index"]]
                entry["command"] = hook_commands[event]
                changed = True
    except Exception as e:
        return False, f"既存の settings.json の hook 構造を安全に処理できません: {e}"

    hooks = current_data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return False, "既存の settings.json の hooks は JSON object ではありません。"
    try:
        for event_name, command in hook_commands.items():
            event_hooks = hooks.setdefault(event_name, [])
            if _event_contains_owned_command(event_name, event_hooks, command):
                continue
            entry = {"type": "command", "command": command}
            if event_name in ("PermissionRequest", "PostToolUseFailure"):
                entry["timeout"] = PRESENTATION_TIMEOUT_SECONDS
            event_hooks.append({
                "matcher": "*",
                "hooks": [entry],
            })
            changed = True
    except Exception as e:
        return False, f"既存の settings.json の hook 構造を安全に処理できません: {e}"

    summary = _connection_summary(current_data, pkg_root, settings_path)
    if not changed:
        return True, "接続済み（設定変更なし）\n" + summary

    settings_dir = os.path.dirname(settings_path)
    os.makedirs(settings_dir, exist_ok=True)
    if existed:
        backup_path = f"{settings_path}.bak.{time.time_ns()}"
        try:
            shutil.copy2(settings_path, backup_path)
        except Exception as e:
            return False, f"バックアップの作成に失敗しました: {e}"
    else:
        backup_path = "新規作成（既存ファイルなし）"

    try:
        _atomic_write_settings(settings_path, current_data, expected_revision=revision)
    except SettingsConflictError:
        return False, "設定更新の競合を検出：未反映です。現在の設定を保持し、自動再試行・復元はしていません。"
    except SettingsPostCommitConflictError:
        return False, "設定の反映後に確認不一致が発生しました。現在の設定は復元せず、接続状態は未確認です。"
    except SettingsCommitDurabilityError:
        return True, f"接続完了（設定は反映済みですが、永続性の確認は保留です）\nバックアップ: {backup_path}\n{summary}"
    except Exception as e:
        return False, f"settings.json の安全な書き込みに失敗しました: {e}"
    return True, f"接続完了\nバックアップ: {backup_path}\n{summary}"


@_settings_writer
def disconnect_hooks_from_settings(
    pkg_root: str,
    settings_path: Optional[str] = None,
    require_no_payload_references: bool = False,
) -> Tuple[bool, str]:
    """Disconnect only exact canonical commands owned by this package."""
    if not settings_path:
        settings_path = get_default_settings_path()
    settings_path = os.path.abspath(settings_path)

    try:
        current_data, existed, revision = _read_settings_snapshot(settings_path)
    except Exception as e:
        return False, f"既存の settings.json の読み込みに失敗しました: {e}"
    if not existed:
        return True, "対象設定が存在しないため、切断対象はありません。"

    durability_unconfirmed = False
    replacement_applied = False
    try:
        changed = _remove_owned_commands(current_data, _owned_hook_command_variants(pkg_root))
        if changed:
            try:
                _atomic_write_settings(settings_path, current_data, expected_revision=revision)
                replacement_applied = True
            except SettingsCommitDurabilityError:
                durability_unconfirmed = True
                replacement_applied = True
        verified_data, _ = _read_settings(settings_path)
        if contains_owned_hooks(verified_data, pkg_root):
            return False, "所有フックが残っているため切断を完了できませんでした。"
        if require_no_payload_references and contains_noncanonical_hook_reference(verified_data, pkg_root):
            return False, (
                "canonical hook pathを参照する非canonical commandが残っています。"
                "ユーザー所有設定は削除せず、payload削除を停止します。"
            )
        if durability_unconfirmed and require_no_payload_references:
            return False, (
                "settings.json の変更は反映済みですが永続性を確認できないため、"
                "アンインストールを停止しました。"
            )
    except SettingsConflictError:
        return False, "設定更新の競合を検出：未反映です。現在の設定を保持し、自動再試行・復元はしていません。"
    except SettingsPostCommitConflictError:
        return False, "設定の反映後に確認不一致が発生しました。現在の設定は復元せず、切断状態は未確認です。"
    except Exception as e:
        if replacement_applied:
            return False, "設定の反映後に再検証できませんでした。現在の設定は復元せず、切断状態は未確認です。"
        return False, f"所有フックを安全に切断できません: {e}"

    if changed:
        if durability_unconfirmed:
            return True, "ume-harness が所有する3本のフックを切断しました（永続性の確認は保留です）。"
        return True, "ume-harness が所有する3本のフックを切断しました。"
    return True, "ume-harness が所有するフックは接続されていません。"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Manage exact ume-harness hook and CLI-wrapper ownership")
    parser.add_argument(
        "operation",
        choices=(
            "disconnect",
            "disconnect-for-uninstall",
            "emit-cli-wrapper",
            "verify-cli-wrapper",
            "protocol-version",
        ),
    )
    parser.add_argument("--pkg-root", required=True)
    parser.add_argument("--settings-path")
    parser.add_argument("--wrapper-path")
    args = parser.parse_args(argv)

    if args.operation == "protocol-version":
        print(OWNERSHIP_PROTOCOL_VERSION)
        return 0
    if args.operation == "emit-cli-wrapper":
        sys.stdout.write(render_cli_wrapper(args.pkg_root))
        return 0
    if args.operation == "verify-cli-wrapper":
        if not args.wrapper_path:
            parser.error("--wrapper-path is required for verify-cli-wrapper")
        return 0 if cli_wrapper_is_owned(args.wrapper_path, args.pkg_root) else 1
    if not args.settings_path:
        parser.error("--settings-path is required for disconnect operations")

    ok, message = disconnect_hooks_from_settings(
        args.pkg_root,
        args.settings_path,
        require_no_payload_references=args.operation == "disconnect-for-uninstall",
    )
    stream = sys.stdout if ok else sys.stderr
    print(message, file=stream)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
