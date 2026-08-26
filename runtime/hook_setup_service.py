#!/usr/bin/env python3
"""Ownership service for Claude Code hooks and the installed CLI wrapper.

It owns exactly three hook command paths and one exact generated wrapper under
the supplied package root. It never claims artifacts by substring or filename.
"""

from __future__ import annotations

import argparse
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
        "  1. PreToolUse: ツール実行直前の日本語意味訳自動表示",
        f"     -> {hook_paths.get('PreToolUse')}",
        "  2. PermissionRequest: 手動許可プロンプト直前の詳細解説",
        f"     -> {hook_paths.get('PermissionRequest')}",
        "  3. PostToolUseFailure: エラー発生時の事実ベースの案内",
        f"     -> {hook_paths.get('PostToolUseFailure')}",
        "",
        "【安全の保証】",
        "  ✓ 変更前に既存設定のバックアップを自動作成します",
        "  ✓ `ume-harness setup --disconnect` は上記3本だけを安全に取り外します",
        "  ✓ その他の設定・イベント・matcher・hookには触れません",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def _read_settings(settings_path: str) -> Tuple[Dict[str, Any], bool]:
    try:
        path_mode = os.lstat(settings_path).st_mode
    except FileNotFoundError:
        return {}, False
    if stat.S_ISLNK(path_mode):
        raise ValueError("settings.json symlinks are unsupported because ownership cannot be preserved safely")
    if not stat.S_ISREG(path_mode):
        raise ValueError("settings.json must be a regular file")
    with open(settings_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return {}, True
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("settings.json のルートは JSON object である必要があります。")
    return data, True


def _atomic_write_settings(settings_path: str, data: Dict[str, Any]) -> None:
    settings_dir = os.path.dirname(settings_path)
    os.makedirs(settings_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=settings_dir, prefix="settings_merge_", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temp_path, settings_path)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def _remove_owned_commands(data: Dict[str, Any], hook_paths: Dict[str, str]) -> bool:
    """Remove exact canonical commands only from the three owned events."""
    hooks = data.get("hooks")
    if hooks is None:
        return False
    if not isinstance(hooks, dict):
        raise ValueError("settings.json の hooks は JSON object である必要があります。")

    changed = False
    for event_name, owned_command in hook_paths.items():
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
                    and hook_item.get("command") == owned_command
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
                    and group_hooks[0] == {"type": "command", "command": owned_command}
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

    for event_name, owned_command in get_adapter_hook_paths(pkg_root).items():
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
                    and hook_item.get("command") == owned_command
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


def install_hooks_to_settings(
    pkg_root: str,
    settings_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Idempotently and atomically merge the three canonical hooks."""
    if not settings_path:
        settings_path = get_default_settings_path()
    settings_path = os.path.abspath(settings_path)

    hook_paths = get_adapter_hook_paths(pkg_root)
    for hpath in hook_paths.values():
        if not os.path.exists(hpath):
            return False, f"フックファイルが見つかりません: {hpath}"

    try:
        current_data, existed = _read_settings(settings_path)
    except Exception as e:
        return False, f"既存の settings.json の読み込みに失敗しました: {e}"

    hooks = current_data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return False, "既存の settings.json の hooks は JSON object ではありません。"
    changed = False
    try:
        for event_name, hpath in hook_paths.items():
            event_hooks = hooks.setdefault(event_name, [])
            if _event_contains_owned_command(event_name, event_hooks, hpath):
                continue
            event_hooks.append({
                "matcher": "*",
                "hooks": [{"type": "command", "command": hpath}],
            })
            changed = True
    except Exception as e:
        return False, f"既存の settings.json の hook 構造を安全に処理できません: {e}"

    if not changed:
        return True, "接続済み（設定変更なし）"

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
        _atomic_write_settings(settings_path, current_data)
    except Exception as e:
        return False, f"settings.json の安全な書き込みに失敗しました: {e}"
    return True, f"接続完了\nバックアップ: {backup_path}"


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
        current_data, existed = _read_settings(settings_path)
    except Exception as e:
        return False, f"既存の settings.json の読み込みに失敗しました: {e}"
    if not existed:
        return True, "対象設定が存在しないため、切断対象はありません。"

    try:
        changed = _remove_owned_commands(current_data, get_adapter_hook_paths(pkg_root))
        if changed:
            _atomic_write_settings(settings_path, current_data)
        verified_data, _ = _read_settings(settings_path)
        if contains_owned_hooks(verified_data, pkg_root):
            return False, "所有フックが残っているため切断を完了できませんでした。"
        if require_no_payload_references and contains_noncanonical_hook_reference(verified_data, pkg_root):
            return False, (
                "canonical hook pathを参照する非canonical commandが残っています。"
                "ユーザー所有設定は削除せず、payload削除を停止します。"
            )
    except Exception as e:
        return False, f"所有フックを安全に切断できません: {e}"

    if changed:
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
