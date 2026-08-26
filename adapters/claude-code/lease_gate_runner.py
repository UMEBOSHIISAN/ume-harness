#!/usr/bin/env python3
"""Canonical Claude Code Lease Gate Runner & Authenticated Verifier.

Single Source of Truth for Claude Code enforcement:
1. Validates authenticated protected-runtime closure against activation root digest.
2. Evaluates atomic activation state (disabled / canary / active).
3. Enforces read and write scope escape rules under active LocalExecutionLease.
4. Enforces control-plane protection (<worktree>/.ume-harness/**).
5. Enforces deterministic side effect classification (Bash shell composition & injection protection).
"""

from __future__ import annotations

import argparse
import enum
import fnmatch
import functools
import hashlib
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

# Add runtime directory to sys.path
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

import local_execution_gate as leg  # noqa: E402
import local_execution_lease_state as lels  # noqa: E402
import tool_policy as tp  # noqa: E402

_DESTRUCTIVE_CMD_RE = re.compile(r"\b(rm\s+-[rf]+\w*|git\s+reset\s+--hard|drop\s+table|mkfs)\b", re.IGNORECASE)
_EXTERNAL_CMD_RE = re.compile(r"\b(ssh\s|git\s+push|curl\s+[^|]*-[Xd]|curl\s+[^|]*--data)\b", re.IGNORECASE)

_DISALLOWED_SHELL_CHARS = set(";&|`$><\n\r*?[]{}~")
_SAFE_COMMANDS = {"ls", "pwd", "cat", "head", "tail", "wc"}
_SAFE_PATH_FREE_GIT_SUBCOMMANDS = frozenset({"branch", "log"})
_GIT_STATUS_PATH_OPTIONS = frozenset(
    {"-C", "--git-dir", "--work-tree", "--pathspec-from-file", "--pathspec-file-nul"}
)

_SECRET_COMPONENTS = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".docker",
        ".kube",
        "keychains",
        "credential",
        "credentials",
        "key",
        "keys",
        "secret",
        "secrets",
    }
)
_SECRET_FILENAMES = frozenset(
    {
        ".env",
        ".claude.json",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pgpass",
        ".pypirc",
        "accesstokens.json",
        "auth.json",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "gshadow",
        "master.passwd",
        "secrets.json",
        "shadow",
        "token.json",
        "tokens.json",
    }
)
_SECRET_PATH_SUFFIXES = frozenset(
    {
        (".config", "gh", "hosts.yaml"),
        (".config", "gh", "hosts.yml"),
    }
)
_SENSITIVE_FILENAME_RE = re.compile(
    r"(?:^|[._-])(?:secret|secrets|credential|credentials)(?:[._-]|$)"
)
_KEY_FILENAME_RE = re.compile(
    r"(?:^|[._-])(?:(?:api|private|access|secret|auth|client)[._-]?keys?|keys?)(?:[._-]|$)"
)
_TOKEN_FILENAME_RE = re.compile(
    r"(?:^|[._-])(?:(?:access|auth|client|refresh)[._-]?)?tokens?(?:[._-]|$)"
)
_CONSTITUTION_FILENAMES = frozenset(
    {"agents.md", "claude.md", "ai_harness_constitution.md", "ume_ai_constitution.md"}
)
_CONSTITUTION_ALIAS_RE = re.compile(r"^(?:agents|claude)\.(?:local|override)\.md$")
_GOVERNANCE_COMPONENTS = frozenset(
    {
        ".circleci",
        ".claude",
        ".git",
        ".git-hooks",
        ".ume-harness",
        "cron",
        "crontab",
        "deploy",
        "deployment",
        "deployments",
        "launchagents",
        "launchd",
        "launchdaemons",
        "pam.d",
        "sudoers.d",
        "systemd",
    }
)
_GOVERNANCE_FILENAMES = frozenset(
    {
        ".gitlab-ci.yml",
        "authority_contract.md",
        "autonomous_stop.md",
        ".gitconfig",
        "azure-pipelines.yaml",
        "azure-pipelines.yml",
        "config.toml",
        "domain_descriptor.json",
        "jenkinsfile",
        "manifest.md",
        "package_manifest.json",
        "release_identity.json",
        "settings.json",
        "sudoers",
        "task_intake.md",
        "tool_policy.md",
        "vercel.json",
    }
)
_GOVERNANCE_PATH_SUFFIXES = frozenset(
    {
        ("etc", "profile"),
        ("private", "etc", "profile"),
    }
)
_GOVERNANCE_CONTRACT_RE = re.compile(r"(?:^|_)contract(?:_[a-z0-9_-]+)?\.md$")
_EXECUTION_GATE_ROOT_COMPONENTS = frozenset(
    {"automation", "ci", "contracts", "hooks", "scripts"}
)
_RUNTIME_COMPONENTS = frozenset({"bin", "sbin"})
_RUNTIME_FILENAMES = frozenset(
    {"cargo.toml", "dockerfile", "go.mod", "makefile", "package.json", "pyproject.toml", "ume-harness"}
)
_RUNTIME_SUFFIXES = frozenset(
    {".bash", ".c", ".cfg", ".conf", ".cpp", ".go", ".h", ".hpp", ".ini", ".ipynb", ".java", ".js", ".jsx", ".mjs", ".php", ".py", ".rb", ".rs", ".sh", ".swift", ".toml", ".ts", ".tsx", ".yaml", ".yml", ".zsh"}
)
_MAX_GLOB_POLICY_MATCHES = 4096
_MAX_POLICY_VISITED_ENTRIES = 4096
_MAX_GLOB_PATTERN_COMPONENTS = 128
_HEAD_TAIL_OPTIONS_WITH_VALUE = frozenset(
    {"-b", "-c", "-n", "--bytes", "--lines", "--pid", "--sleep-interval"}
)


class ActiveLeaseStatus(str, enum.Enum):
    NO_ACTIVE = "NO_ACTIVE"
    ACTIVE = "ACTIVE"
    STATE_ERROR = "STATE_ERROR"


@dataclass(frozen=True)
class ActiveLeaseLookup:
    status: ActiveLeaseStatus
    worktree_realpath: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class InvocationPathResolution:
    paths: tuple[str, ...]
    complete: bool = True

CLOSURE_FILES = [
    "domain_descriptor.json",
    "contracts/authority_contract.md",
    "contracts/tool_policy.md",
    "contracts/autonomous_stop.md",
    "contracts/task_intake.md",
    "runtime/local_execution_gate.py",
    "runtime/local_execution_lease.py",
    "runtime/local_execution_lease_state.py",
    "runtime/tool_policy.py",
    "runtime/decision_state.py",
    "runtime/human_layer_adapter.py",
    "runtime/stop_adapter.py",
    "runtime/activation_updater.py",
    "adapters/claude-code/lease_gate_runner.py",
    "adapters/claude-code/pretooluse_hook.py",
]


def _emit(decision: str, reason: str, violation_code: str | None = None, lease_id: str | None = None) -> int:
    result = {
        "decision": decision,
        "reason": reason,
        "violation_code": violation_code,
        "lease_id": lease_id,
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def compute_closure_root_digest(install_dir: str) -> tuple[str | None, str | None]:
    mapping: dict[str, str] = {}
    for rel_f in CLOSURE_FILES:
        p = os.path.join(install_dir, rel_f)
        if not os.path.exists(p):
            return None, f"MISSING_CLOSURE_FILE:{rel_f}"
        with open(p, "rb") as f:
            mapping[rel_f] = hashlib.sha256(f.read()).hexdigest()

    can_bytes = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(can_bytes).hexdigest(), None


def is_safe_readonly_command(cmd_str: str) -> bool:
    s = cmd_str.strip()
    if not s:
        return False
    if any(c in _DISALLOWED_SHELL_CHARS for c in s):
        return False
    try:
        tokens = shlex.split(s)
    except Exception:
        return False
    if not tokens:
        return False
    base_cmd = tokens[0]
    if base_cmd in _SAFE_COMMANDS:
        return True
    if base_cmd == "git" and len(tokens) >= 2:
        subcmd = tokens[1]
        args = tokens[2:]
        if subcmd == "status":
            option_names = {token.split("=", 1)[0] for token in tokens[2:] if token.startswith("-")}
            if (
                not any(t.startswith(("--output", "-o")) for t in tokens[2:])
                and option_names.isdisjoint(_GIT_STATUS_PATH_OPTIONS)
            ):
                return True
        if subcmd in _SAFE_PATH_FREE_GIT_SUBCOMMANDS and not args:
            return True
    return False


def classify_side_effect(tool_name: str, tool_input: dict) -> tp.SideEffect:
    if tool_name in ("Glob", "Grep", "WebSearch", "Read"):
        return tp.SideEffect.READ_ONLY
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return tp.SideEffect.BOUNDED_WRITE
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if not isinstance(cmd, str):
            return tp.SideEffect.UNKNOWN
        if _DESTRUCTIVE_CMD_RE.search(cmd):
            return tp.SideEffect.DESTRUCTIVE
        if _EXTERNAL_CMD_RE.search(cmd):
            return tp.SideEffect.EXTERNAL_MUTATION
        if is_safe_readonly_command(cmd):
            return tp.SideEffect.READ_ONLY
        return tp.SideEffect.UNKNOWN
    if tool_name in ("WebFetch", "SendMessage"):
        return tp.SideEffect.EXTERNAL_MUTATION
    return tp.SideEffect.UNKNOWN


def _classify_policy_path(path: str) -> tp.Tier:
    normalized = os.path.normpath(path)
    parts = tuple(part.lower() for part in normalized.split(os.sep) if part)
    filename = parts[-1] if parts else ""
    suffix = os.path.splitext(filename)[1]
    process_environment = any(
        parts[index] == "proc" and parts[index + 2] == "environ"
        for index in range(len(parts) - 2)
    )

    if (
        process_environment
        or any(part in _SECRET_COMPONENTS for part in parts)
        or any(
            _SENSITIVE_FILENAME_RE.search(part) is not None
            or _KEY_FILENAME_RE.search(part) is not None
            or (
                _TOKEN_FILENAME_RE.search(part) is not None
                and os.path.splitext(part)[1] not in {".md", ".rst"}
            )
            for part in parts
        )
        or filename in _SECRET_FILENAMES
        or any(parts[-len(suffix) :] == suffix for suffix in _SECRET_PATH_SUFFIXES)
        or filename.startswith(".env")
        or filename.startswith(".claude.json.")
        or suffix == ".env"
        or suffix in {".key", ".p12", ".pem", ".pfx"}
    ):
        return tp.Tier.TIER_SECRETS
    if (
        filename in _CONSTITUTION_FILENAMES
        or _CONSTITUTION_ALIAS_RE.fullmatch(filename) is not None
        or "constitution" in filename
    ):
        return tp.Tier.TIER_CONSTITUTION
    if (
        any(part in _GOVERNANCE_COMPONENTS for part in parts)
        or any(part.startswith("cron.") for part in parts)
        or any(parts[index : index + 2] == ("etc", "ssh") for index in range(len(parts) - 1))
        or filename in _GOVERNANCE_FILENAMES
        or any(parts[-len(path_suffix) :] == path_suffix for path_suffix in _GOVERNANCE_PATH_SUFFIXES)
        or _GOVERNANCE_CONTRACT_RE.search(filename) is not None
        or suffix == ".service"
        or any(parts[index : index + 2] == (".github", "workflows") for index in range(len(parts) - 1))
    ):
        return tp.Tier.TIER_GOVERNANCE
    if (
        any(part in _RUNTIME_COMPONENTS for part in parts)
        or filename in _RUNTIME_FILENAMES
        or filename.startswith("settings.json.")
        or suffix in _RUNTIME_SUFFIXES
    ):
        return tp.Tier.TIER_RUNTIME_CODE
    return tp.Tier.TIER_NORMAL


def _is_root_execution_gate_path(path: str, execution_root: str | None) -> bool:
    if execution_root is None:
        return False
    root = os.path.realpath(os.path.abspath(os.path.expanduser(execution_root)))
    candidate = os.path.abspath(path)
    try:
        relative = os.path.relpath(candidate, root)
    except ValueError:
        return False
    if relative == ".." or relative.startswith(f"..{os.sep}"):
        return False
    parts = tuple(part.lower() for part in Path(relative).parts if part not in ("", "."))
    return bool(parts) and parts[0] in _EXECUTION_GATE_ROOT_COMPONENTS


def resolve_path_tier(
    path: str,
    base_dir: str | None = None,
    execution_root: str | None = None,
) -> tp.Tier:
    """Resolve one host path to the strictest canonical portable Authority Tier."""
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(base_dir or os.getcwd(), expanded)
    lexical_path = os.path.abspath(expanded)
    real_path = os.path.realpath(lexical_path)
    tiers = {_classify_policy_path(lexical_path), _classify_policy_path(real_path)}
    effective_execution_root = execution_root if execution_root is not None else base_dir
    if _is_root_execution_gate_path(lexical_path, effective_execution_root) or _is_root_execution_gate_path(
        real_path, effective_execution_root
    ):
        tiers.add(tp.Tier.TIER_GOVERNANCE)
    for tier in (
        tp.Tier.TIER_SECRETS,
        tp.Tier.TIER_CONSTITUTION,
        tp.Tier.TIER_GOVERNANCE,
        tp.Tier.TIER_RUNTIME_CODE,
    ):
        if tier in tiers:
            return tier
    return tp.Tier.TIER_NORMAL


def _path_pattern_matches(path_parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    """Match path components without allowing ``*`` to cross directory boundaries."""
    @functools.lru_cache(maxsize=None)
    def matches(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        pattern = pattern_parts[pattern_index]
        if pattern == "**":
            return matches(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and matches(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], pattern)
            and matches(path_index + 1, pattern_index + 1)
        )

    return matches(0, 0)


def _path_pattern_can_match_below(path_parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    """Return whether a directory prefix can lead to a full pattern match."""
    @functools.lru_cache(maxsize=None)
    def matches(path_index: int, pattern_index: int) -> bool:
        if path_index == len(path_parts):
            return pattern_index < len(pattern_parts)
        if pattern_index == len(pattern_parts):
            return False
        pattern = pattern_parts[pattern_index]
        if pattern == "**":
            return matches(path_index, pattern_index + 1) or matches(path_index + 1, pattern_index)
        return (
            fnmatch.fnmatchcase(path_parts[path_index], pattern)
            and matches(path_index + 1, pattern_index + 1)
        )

    return matches(0, 0)


def _glob_syntax_is_modeled(pattern: str) -> bool:
    """Return whether the resolver models Claude's minimatch pattern exactly enough."""
    if any(char in pattern for char in "{}\\") or pattern.startswith("!"):
        return False
    return re.search(r"[?*+@!]\(", pattern) is None


def _glob_policy_paths(base_path: str, pattern: str, base_dir: str) -> InvocationPathResolution:
    effective_base = _absolute_target(base_path, base_dir)
    expanded_pattern = os.path.expanduser(pattern)
    lexical_pattern = expanded_pattern if os.path.isabs(expanded_pattern) else os.path.join(effective_base, expanded_pattern)
    lexical_pattern = os.path.abspath(lexical_pattern)
    paths = [effective_base, lexical_pattern]
    # Claude Code uses minimatch. Until its brace/extglob/negation syntax is
    # modeled exactly, never under-approximate the paths that the host can read.
    if not _glob_syntax_is_modeled(expanded_pattern):
        return InvocationPathResolution(tuple(paths), complete=False)
    try:
        if not os.path.isdir(effective_base):
            return InvocationPathResolution(tuple(paths))
        try:
            relative_pattern = os.path.relpath(lexical_pattern, effective_base)
        except ValueError:
            return InvocationPathResolution(tuple(paths), complete=False)
        if relative_pattern == ".." or relative_pattern.startswith(f"..{os.sep}"):
            return InvocationPathResolution(tuple(paths), complete=False)
        pattern_parts = tuple(part for part in Path(relative_pattern).parts if part not in ("", "."))
        if not pattern_parts:
            return InvocationPathResolution(tuple(paths))
        if len(pattern_parts) > _MAX_GLOB_PATTERN_COMPONENTS:
            return InvocationPathResolution(tuple(paths), complete=False)

        recursive = "**" in pattern_parts
        max_depth = None if recursive else len(pattern_parts)
        visited = 0
        matches = 0
        complete = True

        def mark_incomplete(_error: OSError) -> None:
            nonlocal complete
            complete = False

        for current_root, dirnames, filenames in os.walk(
            effective_base,
            topdown=True,
            onerror=mark_incomplete,
            followlinks=False,
        ):
            dirnames.sort()
            filenames.sort()
            current_relative = os.path.relpath(current_root, effective_base)
            current_parts = () if current_relative == "." else Path(current_relative).parts
            traversable_dirs: list[str] = []
            for name in dirnames:
                visited += 1
                if visited > _MAX_POLICY_VISITED_ENTRIES:
                    return InvocationPathResolution(tuple(paths), complete=False)
                candidate = os.path.join(current_root, name)
                relative_parts = current_parts + (name,)
                if _path_pattern_matches(relative_parts, pattern_parts):
                    paths.append(candidate)
                    matches += 1
                    if matches > _MAX_GLOB_POLICY_MATCHES:
                        return InvocationPathResolution(tuple(paths), complete=False)
                may_descend = max_depth is None or len(relative_parts) < max_depth
                if os.path.islink(candidate):
                    if may_descend and _path_pattern_can_match_below(relative_parts, pattern_parts):
                        complete = False
                elif may_descend:
                    traversable_dirs.append(name)
            dirnames[:] = traversable_dirs

            for name in filenames:
                visited += 1
                if visited > _MAX_POLICY_VISITED_ENTRIES:
                    return InvocationPathResolution(tuple(paths), complete=False)
                candidate = os.path.join(current_root, name)
                relative_parts = current_parts + (name,)
                if not _path_pattern_matches(relative_parts, pattern_parts):
                    continue
                paths.append(candidate)
                matches += 1
                if matches > _MAX_GLOB_POLICY_MATCHES:
                    return InvocationPathResolution(tuple(paths), complete=False)
    except Exception:
        return InvocationPathResolution(tuple(paths), complete=False)
    return InvocationPathResolution(tuple(paths), complete=complete)


def _grep_glob_matches(relative_path: str, pattern: str) -> bool:
    """Match the bounded ripgrep-style subset accepted by ``_grep_policy_paths``.

    A slash-less ripgrep glob applies to basenames at every depth.  Unlike shell
    globs, leading dots are matchable; however, a hidden directory is traversed
    only when that same basename glob can select the directory.  Slash-bearing
    patterns are matched component by component so ``*`` never crosses ``/``.
    Recursive ``**`` patterns are rejected by the caller rather than guessed.
    """
    path_parts = tuple(part for part in Path(relative_path).parts if part not in ("", "."))
    if not path_parts:
        return False
    if "/" not in pattern:
        if any(
            part.startswith(".") and not fnmatch.fnmatchcase(part, pattern)
            for part in path_parts[:-1]
        ):
            return False
        return fnmatch.fnmatchcase(path_parts[-1], pattern)

    pattern_parts = tuple(part for part in pattern.split("/") if part not in ("", "."))
    if len(path_parts) != len(pattern_parts):
        return False
    return all(
        fnmatch.fnmatchcase(path_part, pattern_part)
        for path_part, pattern_part in zip(path_parts, pattern_parts)
    )


def _grep_policy_paths(
    base_path: str,
    base_dir: str,
    glob_filter: str | None = None,
) -> InvocationPathResolution:
    """Resolve the visible recursive tree that Claude's default Grep may read."""
    effective_base = _absolute_target(base_path, base_dir)
    paths = [effective_base]
    if not os.path.isdir(effective_base):
        return InvocationPathResolution(tuple(paths))
    if glob_filter is not None and (
        os.path.isabs(glob_filter)
        or glob_filter.startswith("!")
        or "**" in glob_filter
        or any(char in glob_filter for char in "{}\\")
    ):
        return InvocationPathResolution(tuple(paths), complete=False)

    complete = True
    visited = 0
    # Supplying --glob changes ripgrep's hidden-path selection.  Walk hidden
    # entries too and let the bounded matcher decide which files are reachable.
    include_hidden = glob_filter is not None

    def mark_incomplete(_error: OSError) -> None:
        nonlocal complete
        complete = False

    try:
        for current_root, dirnames, filenames in os.walk(
            effective_base,
            topdown=True,
            onerror=mark_incomplete,
            followlinks=False,
        ):
            visible_dirs: list[str] = []
            dirnames.sort()
            filenames.sort()
            for name in dirnames:
                visited += 1
                if visited > _MAX_POLICY_VISITED_ENTRIES:
                    return InvocationPathResolution(tuple(paths), complete=False)
                if name.startswith(".") and not include_hidden:
                    continue
                child = os.path.join(current_root, name)
                if glob_filter is None:
                    paths.append(child)
                    if len(paths) > _MAX_GLOB_POLICY_MATCHES:
                        return InvocationPathResolution(tuple(paths), complete=False)
                if not os.path.islink(child):
                    visible_dirs.append(name)
            dirnames[:] = visible_dirs

            for name in filenames:
                visited += 1
                if visited > _MAX_POLICY_VISITED_ENTRIES:
                    return InvocationPathResolution(tuple(paths), complete=False)
                if name.startswith(".") and not include_hidden:
                    continue
                candidate = os.path.join(current_root, name)
                if glob_filter is not None:
                    relative = os.path.relpath(candidate, effective_base)
                    try:
                        if not _grep_glob_matches(relative, glob_filter):
                            continue
                    except Exception:
                        return InvocationPathResolution(tuple(paths), complete=False)
                paths.append(candidate)
                if len(paths) > _MAX_GLOB_POLICY_MATCHES:
                    return InvocationPathResolution(tuple(paths), complete=False)
    except Exception:
        return InvocationPathResolution(tuple(paths), complete=False)
    return InvocationPathResolution(tuple(paths), complete=complete)


def _git_pathspec_is_ambiguous(pathspec: str) -> bool:
    return pathspec.startswith(":") or ":" in pathspec


def _bash_read_paths(tokens: list[str], base_dir: str) -> InvocationPathResolution:
    command = tokens[0]
    if command == "pwd":
        return InvocationPathResolution((base_dir,), complete=all(token.startswith("-") for token in tokens[1:]))

    index = 2 if command == "git" else 1
    options_ended = False
    operands: list[str] = []
    complete = True
    while index < len(tokens):
        token = tokens[index]
        if token == "--" and not options_ended:
            options_ended = True
            index += 1
            continue
        if not options_ended and token.startswith("-") and token != "-":
            if command == "ls" and (
                token in {
                    "--dereference",
                    "--dereference-command-line",
                    "--dereference-command-line-symlink-to-dir",
                    "--recursive",
                }
                or (not token.startswith("--") and any(flag in token[1:] for flag in ("L", "R")))
            ):
                return InvocationPathResolution(tuple(operands or (base_dir,)), complete=False)
            if command in {"head", "tail"} and token in _HEAD_TAIL_OPTIONS_WITH_VALUE:
                if index + 1 >= len(tokens):
                    return InvocationPathResolution(tuple(operands or (base_dir,)), complete=False)
                index += 2
                continue
            if command == "wc" and (token == "--files0-from" or token.startswith("--files0-from=")):
                if token == "--files0-from":
                    if index + 1 >= len(tokens):
                        return InvocationPathResolution(tuple(operands or (base_dir,)), complete=False)
                    operands.append(tokens[index + 1])
                else:
                    operands.append(token.split("=", 1)[1])
                return InvocationPathResolution(tuple(operands), complete=False)
            index += 1
            continue
        if command == "git" and _git_pathspec_is_ambiguous(token):
            operands.append(token)
            complete = False
        else:
            operands.append(token)
        index += 1
    return InvocationPathResolution(tuple(operands or (base_dir,)), complete=complete)


def _invocation_paths(tool_name: str, tool_input: dict, base_dir: str) -> InvocationPathResolution:
    if tool_name in ("Read", "Edit", "Write"):
        target = tool_input.get("file_path") or tool_input.get("filePath")
        return InvocationPathResolution((target,)) if isinstance(target, str) and target else InvocationPathResolution(())
    if tool_name in ("Glob", "Grep"):
        target = tool_input.get("path")
        effective_target = target if isinstance(target, str) and target else base_dir
        if tool_name == "Glob":
            pattern = tool_input.get("pattern")
            if isinstance(pattern, str) and pattern:
                return _glob_policy_paths(effective_target, pattern, base_dir)
        if tool_name == "Grep":
            glob_filter = tool_input.get("glob")
            if isinstance(glob_filter, str) and glob_filter:
                return _grep_policy_paths(effective_target, base_dir, glob_filter)
            return _grep_policy_paths(effective_target, base_dir)
        return InvocationPathResolution((effective_target,))
    if tool_name == "NotebookEdit":
        target = (
            tool_input.get("notebook_path")
            or tool_input.get("file_path")
            or tool_input.get("filePath")
        )
        return InvocationPathResolution((target,)) if isinstance(target, str) and target else InvocationPathResolution(())
    if tool_name != "Bash":
        return InvocationPathResolution(())

    command = tool_input.get("command", "")
    if not isinstance(command, str) or not is_safe_readonly_command(command):
        return InvocationPathResolution(())
    try:
        tokens = shlex.split(command.strip())
    except Exception:
        return InvocationPathResolution(())
    if not tokens:
        return InvocationPathResolution(())
    return _bash_read_paths(tokens, base_dir)


def invocation_policy(
    tool_name: str,
    tool_input: dict,
    base_dir: str,
    execution_root: str | None = None,
) -> tuple[tp.SideEffect, tuple[tp.Tier, ...], tp.Decision]:
    side_effect = classify_side_effect(tool_name, tool_input)
    resolution = _invocation_paths(tool_name, tool_input, base_dir)
    tiers = tuple(
        resolve_path_tier(path, base_dir, execution_root) for path in resolution.paths
    ) or (tp.Tier.TIER_NORMAL,)
    decisions = tuple(tp.decide(tier, side_effect) for tier in tiers)
    if tp.Decision.DENY in decisions:
        decision = tp.Decision.DENY
    elif tp.Decision.APPROVAL_REQUIRED in decisions:
        decision = tp.Decision.APPROVAL_REQUIRED
    elif not resolution.complete:
        decision = tp.Decision.APPROVAL_REQUIRED
    else:
        decision = tp.Decision.ALLOW
    return side_effect, tiers, decision


def get_active_lease_context(
    state_store: lels.LeaseStateStore | None,
    *,
    target_paths: tuple[str, ...] = (),
    base_dir: str | None = None,
    invocation_cwd: str | None = None,
) -> ActiveLeaseLookup:
    """Select the active Lease bound to this invocation, or fail closed if ambiguous."""
    if state_store is None:
        return ActiveLeaseLookup(ActiveLeaseStatus.NO_ACTIVE)
    try:
        with state_store._locked_document() as doc:
            now = state_store._now()
            state_store._expire_due(doc, now)
            active_worktrees = tuple(
                os.path.realpath(raw["worktree_realpath"])
                for raw in doc.get("leases", [])
                if raw.get("lifecycle") == lels.LeaseLifecycle.ACTIVE.value
            )
    except Exception as exc:
        return ActiveLeaseLookup(ActiveLeaseStatus.STATE_ERROR, error=str(exc))
    if not active_worktrees:
        return ActiveLeaseLookup(ActiveLeaseStatus.NO_ACTIVE)
    if len(active_worktrees) == 1:
        return ActiveLeaseLookup(
            ActiveLeaseStatus.ACTIVE,
            worktree_realpath=active_worktrees[0],
        )

    lookup_base = base_dir or invocation_cwd or os.getcwd()
    normalized_targets = tuple(
        _absolute_target(path, lookup_base)
        for path in target_paths
        if isinstance(path, str) and path
    )
    if invocation_cwd:
        real_cwd = os.path.realpath(os.path.abspath(os.path.expanduser(invocation_cwd)))
        cwd_matches = tuple(
            worktree
            for worktree in active_worktrees
            if leg._is_path_inside(real_cwd, worktree)
        )
        if len(cwd_matches) != 1:
            return ActiveLeaseLookup(
                ActiveLeaseStatus.STATE_ERROR,
                error="invocation cwd does not map uniquely to an active Lease worktree",
            )
        cwd_match = cwd_matches[0]
        if normalized_targets:
            target_matches = tuple(
                worktree
                for worktree in active_worktrees
                if all(leg._is_path_inside(path, worktree) for path in normalized_targets)
            )
            if len(target_matches) > 1 or (
                len(target_matches) == 1 and target_matches[0] != cwd_match
            ):
                return ActiveLeaseLookup(
                    ActiveLeaseStatus.STATE_ERROR,
                    error="invocation cwd and target paths map to different active Lease worktrees",
                )
        return ActiveLeaseLookup(
            ActiveLeaseStatus.ACTIVE,
            worktree_realpath=cwd_match,
        )

    if normalized_targets:
        target_matches = tuple(
            worktree
            for worktree in active_worktrees
            if all(leg._is_path_inside(path, worktree) for path in normalized_targets)
        )
        if len(target_matches) == 1:
            return ActiveLeaseLookup(
                ActiveLeaseStatus.ACTIVE,
                worktree_realpath=target_matches[0],
            )

    return ActiveLeaseLookup(
        ActiveLeaseStatus.STATE_ERROR,
        error="multiple active Lease worktrees do not map uniquely to this invocation",
    )


def default_domain_resolver(real_path: str) -> leg.ManagedExecutionDomain | None:
    """Discovers .ume-harness/domain.json upwards from real_path."""
    curr = real_path if os.path.isdir(real_path) else os.path.dirname(real_path)
    while curr and curr != "/":
        desc = os.path.join(curr, ".ume-harness", "domain.json")
        if os.path.exists(desc):
            try:
                with open(desc, "r", encoding="utf-8") as f:
                    d = json.load(f)
                return leg.ManagedExecutionDomain(
                    repository=d.get("repository", os.path.basename(curr)),
                    worktree_realpath=os.path.realpath(d.get("worktree_realpath", curr)),
                    management_mode=d.get("management_mode", "lease"),
                    policy_id=d.get("policy_id", "ume-harness-site-policy-v0"),
                    policy_sha256=d.get("policy_sha256", ""),
                )
            except Exception:
                return None
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return None


def _absolute_target(path: str, base_dir: str) -> str:
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(base_dir, expanded)
    return os.path.realpath(os.path.abspath(expanded))


def _canonical_file_target(
    tool_name: str,
    tool_input: dict,
    base_dir: str,
) -> tuple[str | None, str | None]:
    """Resolve file-target aliases and reject ambiguous host payloads."""
    keys = (
        ("notebook_path", "file_path", "filePath")
        if tool_name == "NotebookEdit"
        else ("file_path", "filePath")
    )
    targets: list[str] = []
    for key in keys:
        if key not in tool_input:
            continue
        value = tool_input.get(key)
        if not isinstance(value, str) or not value.strip():
            return None, f"{key} must be a non-empty string"
        targets.append(_absolute_target(value, base_dir))
    if not targets:
        return None, "target path must be a non-empty string"
    if len(set(targets)) != 1:
        return None, "conflicting target path aliases"
    return targets[0], None


def check_read_scope_escape(
    tool_name: str,
    tool_input: dict,
    active_worktree: str,
    base_dir: str,
) -> str | None:
    """Checks if a read tool or bash read command targets files outside the active lease worktree."""
    if tool_name in ("Read", "Glob", "Grep", "Bash"):
        resolution = _invocation_paths(tool_name, tool_input, base_dir)
        if not resolution.complete:
            return "read target expansion could not be proven inside the active lease worktree"
        for target in resolution.paths:
            real_target = _absolute_target(target, base_dir)
            if not leg._is_path_inside(real_target, active_worktree):
                return f"read target path escapes active lease worktree boundary ({active_worktree})"
    return None


def evaluate_invocation(
    data: dict,
    gate: leg.LocalExecutionGate | None = None,
    install_dir: str | None = None,
    state_dir: str | None = None,
) -> tuple[int, str | None]:
    if not isinstance(data, dict):
        return 2, "[ume-harness Lease Gate] hook input must be an object (INVALID_HOOK_INPUT)\n"
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 2, "[ume-harness Lease Gate] malformed tool invocation (INVALID_HOOK_INPUT)\n"
    path_like_values = (
        data.get("cwd"),
        tool_input.get("file_path"),
        tool_input.get("filePath"),
        tool_input.get("notebook_path"),
        tool_input.get("path"),
        tool_input.get("pattern"),
        tool_input.get("glob"),
        tool_input.get("command"),
    )
    if any(isinstance(value, str) and "\x00" in value for value in path_like_values):
        return 2, "[ume-harness Lease Gate] path-like input contains NUL (INVALID_TARGET_PATH)\n"
    invocation_cwd = data.get("cwd") if isinstance(data.get("cwd"), str) and data.get("cwd") else None
    base_dir = os.path.realpath(invocation_cwd or os.getcwd())
    file_path: str | None = None
    if tool_name == "Read":
        file_path, target_error = _canonical_file_target(tool_name, tool_input, base_dir)
        if target_error is not None:
            return 2, f"[ume-harness Lease Gate] {target_error} (INVALID_TARGET_PATH)\n"
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        file_path, target_error = _canonical_file_target(tool_name, tool_input, base_dir)
        if target_error is not None:
            return 2, f"[ume-harness Lease Gate] {target_error} (INVALID_TARGET_PATH)\n"
    if tool_name in ("Glob", "Grep") and "path" in tool_input:
        search_path = tool_input.get("path")
        if not isinstance(search_path, str) or not search_path.strip():
            return 2, "[ume-harness Lease Gate] search path must be a non-empty string (INVALID_TARGET_PATH)\n"
    if tool_name == "Glob":
        pattern = tool_input.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return 2, "[ume-harness Lease Gate] Glob pattern must be a non-empty string (INVALID_TARGET_PATH)\n"
    if tool_name == "Grep":
        pattern = tool_input.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return 2, "[ume-harness Lease Gate] Grep pattern must be a non-empty string (INVALID_TARGET_PATH)\n"
        if "glob" in tool_input:
            glob_filter = tool_input.get("glob")
            if not isinstance(glob_filter, str) or not glob_filter:
                return 2, "[ume-harness Lease Gate] Grep glob must be a non-empty string (INVALID_TARGET_PATH)\n"

    state_dir = state_dir or os.environ.get("UME_HARNESS_STATE_DIR") or os.path.expanduser("~/.ume-harness/state")
    install_dir = install_dir or os.environ.get("UME_HARNESS_INSTALL_DIR") or _PKG_ROOT

    # 1. Verification of activation & closure integrity if activation state exists
    activation_file = os.path.join(state_dir, "activation.json")
    if os.path.exists(activation_file):
        try:
            with open(activation_file, "r", encoding="utf-8") as af:
                act = json.load(af)
            act_mode = act.get("mode", "disabled")
            if act_mode == "disabled":
                return 2, "[ume-harness Lease Gate] lease gate is disabled by administrator (DISABLED_BY_ADMIN)\n"
            if act_mode not in ("canary", "active"):
                return 2, f"[ume-harness Lease Gate] unsupported activation mode: {act_mode} (UNSUPPORTED_ACTIVATION_MODE)\n"
            expected_root = act.get("runtime_root_digest")
            if expected_root and os.path.exists(install_dir):
                actual_root, err = compute_closure_root_digest(install_dir)
                if err or actual_root != expected_root:
                    return 2, f"[ume-harness Lease Gate] runtime tamper or digest mismatch detected (ACTIVATION_TAMPER)\n"
        except Exception as e:
            return 2, f"[ume-harness Lease Gate] activation error: {e} (ACTIVATION_ERROR)\n"

    if gate is None:
        try:
            gate = leg.create_default_gate(domain_resolver=default_domain_resolver)
        except Exception:
            gate = None

    provisional_base = base_dir
    provisional_resolution = _invocation_paths(tool_name, tool_input, provisional_base)
    lease_lookup = (
        get_active_lease_context(
            gate._state_store,
            target_paths=provisional_resolution.paths,
            base_dir=provisional_base,
            invocation_cwd=invocation_cwd,
        )
        if gate is not None
        else ActiveLeaseLookup(ActiveLeaseStatus.STATE_ERROR, error="lease gate unavailable")
    )
    if lease_lookup.status == ActiveLeaseStatus.STATE_ERROR and tool_name in (
        "Read",
        "Glob",
        "Grep",
        "Bash",
        "Edit",
        "Write",
        "NotebookEdit",
    ):
        return 2, "[ume-harness Lease Gate] lease state store cannot be trusted (STATE_STORE_ERROR)\n"
    active_worktree = lease_lookup.worktree_realpath if lease_lookup.status == ActiveLeaseStatus.ACTIVE else None
    side_effect, tiers, policy_decision = invocation_policy(
        tool_name,
        tool_input,
        base_dir,
        execution_root=active_worktree,
    )

    # 2. Read scope escape check under active lease
    if active_worktree is not None and tool_name in ("Read", "Glob", "Grep", "Bash"):
        escape_reason = check_read_scope_escape(
            tool_name,
            tool_input,
            active_worktree,
            base_dir,
        )
        if escape_reason is not None:
            return 2, f"[ume-harness Lease Gate] {escape_reason} (SCOPE_ESCAPE)\n"

    # 3. Gate evaluation for Edit/Write/NotebookEdit
    if tool_name in ("Edit", "Write", "NotebookEdit") and gate is not None:
        action = leg.GateAction.WRITE if tool_name == "Write" else leg.GateAction.EDIT
        gate_res = gate.evaluate_request(file_path, action)
        if gate_res.decision == leg.GateDecision.ALLOW:
            if policy_decision == tp.Decision.DENY:
                return 2, (
                    f"[ume-harness] このツール呼び出し（{tool_name}）は "
                    f"{side_effect.value} / {tiers[0].value} として許可されていません。\n"
                )
            if policy_decision == tp.Decision.ALLOW:
                return 0, None
            if all(tier == tp.Tier.TIER_RUNTIME_CODE for tier in tiers):
                return 0, None
        if gate_res.decision == leg.GateDecision.DENY:
            return 2, f"[ume-harness Lease Gate] {gate_res.reason} ({gate_res.violation_code})\n"
        if gate_res.decision == leg.GateDecision.NOT_APPLICABLE:
            if active_worktree is not None:
                return 2, f"[ume-harness Lease Gate] target path escapes active lease worktree boundary ({active_worktree}) (SCOPE_ESCAPE)\n"

    if policy_decision == tp.Decision.DENY:
        return 2, (
            f"[ume-harness] このツール呼び出し（{tool_name}）は "
            f"{side_effect.value} / {tiers[0].value} として許可されていません。\n"
        )

    if policy_decision == tp.Decision.ALLOW:
        return 0, None

    return 2, (
        f"[ume-harness] このツール呼び出し（{tool_name}）は "
        f"{side_effect.value} / {tiers[0].value} に分類され、承認が必要です。\n"
    )


def evaluate_host_path(
    target_path: str,
    action: str = "edit",
    install_dir: str | None = None,
    state_dir: str | None = None,
    worktrees_root: str | None = None,
) -> int:
    """CLI evaluation wrapper for single host path (backwards compatibility)."""
    tool_name = "Write" if action == "write" else "Edit"
    code, err = evaluate_invocation(
        {"tool_name": tool_name, "tool_input": {"file_path": target_path}},
        install_dir=install_dir,
        state_dir=state_dir,
    )
    if code == 0:
        return _emit("ALLOW", "execution allowed under active lease")
    return _emit("DENY", err.strip() if err else "execution denied", "DENIED")


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Code Lease Gate Runner")
    parser.add_argument("--evaluate-path", help="Target file path to evaluate")
    parser.add_argument("--action", default="edit", help="Action string (edit or write)")
    parser.add_argument("--install-dir", help="Override installed runtime directory")
    parser.add_argument("--state-dir", help="Override state directory")
    parser.add_argument("--worktrees-root", help="Override worktrees root directory")
    args = parser.parse_args()

    if args.evaluate_path:
        return evaluate_host_path(
            target_path=args.evaluate_path,
            action=args.action,
            install_dir=args.install_dir,
            state_dir=args.state_dir,
            worktrees_root=args.worktrees_root,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
