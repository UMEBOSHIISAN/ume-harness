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
import importlib
import json
import os
import re
import shlex
import stat
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

# Add runtime directory to sys.path
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME_DIR = os.path.join(_PKG_ROOT, "runtime")
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

class _LazyRuntimeModule:
    """Resolve a protected runtime module only when a caller needs it."""

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._module: Any | None = None

    def load(self) -> Any:
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str) -> Any:
        return getattr(self.load(), name)


# These modules are part of the protected runtime closure.  Keep them out of
# module import time so an activation-bound invocation can verify the installed
# bytes before executing any authority code.
leg: Any = _LazyRuntimeModule("local_execution_gate")
lels: Any = _LazyRuntimeModule("local_execution_lease_state")
tp: Any = _LazyRuntimeModule("tool_policy")


def _exec_snapshot_module(
    module_name: str,
    relative_path: str,
    source: bytes,
    install_dir: str,
) -> Any:
    """Execute an in-memory snapshot, never reopening an attested path."""
    module = types.ModuleType(module_name)
    module.__file__ = os.path.join(install_dir, relative_path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        code = compile(source, module.__file__, "exec")
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _load_runtime_modules(
    snapshot: dict[str, bytes] | None = None,
    install_dir: str | None = None,
) -> None:
    """Import authority modules, using attested bytes when activation is active."""
    global leg, lels, tp
    if snapshot is not None:
        module_specs = (
            ("local_execution_lease", "runtime/local_execution_lease.py"),
            ("local_execution_lease_state", "runtime/local_execution_lease_state.py"),
            ("local_execution_gate", "runtime/local_execution_gate.py"),
            ("tool_policy", "runtime/tool_policy.py"),
        )
        modules: dict[str, Any] = {}
        for module_name, relative_path in module_specs:
            source = snapshot.get(relative_path)
            if source is None:
                raise ImportError(f"attested runtime snapshot is missing {relative_path}")
            modules[module_name] = _exec_snapshot_module(
                module_name,
                relative_path,
                source,
                install_dir or _PKG_ROOT,
            )
        leg = modules["local_execution_gate"]
        lels = modules["local_execution_lease_state"]
        tp = modules["tool_policy"]
        return

    if not isinstance(leg, _LazyRuntimeModule):
        return
    _leg = leg.load()
    _lels = lels.load()
    _tp = tp.load()

    leg = _leg
    lels = _lels
    tp = _tp


def _load_attested_activation_module(
    snapshot: dict[str, bytes],
    install_dir: str,
) -> Any:
    """Load activation parsing logic from the already-attested byte snapshot."""
    source = snapshot.get("runtime/activation_updater.py")
    if source is None:
        raise ImportError("attested activation snapshot is missing activation_updater.py")
    return _exec_snapshot_module(
        "_ume_harness_attested_activation_updater",
        "runtime/activation_updater.py",
        source,
        install_dir,
    )

_DESTRUCTIVE_CMD_RE = re.compile(r"\b(rm\s+-[rf]+\w*|git\s+reset\s+--hard|drop\s+table|mkfs)\b", re.IGNORECASE)
_EXTERNAL_CMD_RE = re.compile(r"\b(ssh\s|git\s+push|curl\s+[^|]*-[Xd]|curl\s+[^|]*--data)\b", re.IGNORECASE)

_DISALLOWED_SHELL_CHARS = set(";&|`$><\n\r*?[]{}~")
_SAFE_COMMANDS = {"ls", "pwd", "cat", "head", "tail", "wc"}
_SAFE_PATH_FREE_GIT_SUBCOMMANDS = frozenset({"branch", "log"})
_GIT_STATUS_PATH_OPTIONS = frozenset(
    {"-C", "--git-dir", "--work-tree", "--pathspec-from-file", "--pathspec-file-nul"}
)
_HOST_INTERACTION_TOOLS = frozenset({"AskUserQuestion", "EnterPlanMode", "ExitPlanMode"})
_HOST_CAPABILITY_DISCOVERY_TOOLS = frozenset({"ToolSearch"})

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
        ".secrets",
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
        "rclone.conf",
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
_STARTUP_FILENAMES = frozenset(
    {
        ".bash_login",
        ".bash_logout",
        ".bash_profile",
        ".bashrc",
        ".profile",
        ".zlogin",
        ".zlogout",
        ".zprofile",
        ".zshenv",
        ".zshrc",
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
    RESTRICTED = "RESTRICTED"


@dataclass(frozen=True)
class InvocationResult:
    decision: str
    reason: str
    code: str


def _result(decision: str, code: str, reason: str) -> InvocationResult:
    return InvocationResult(decision, f"[ume-harness] {reason} ({code})\n", code)


def _protected_roots(state_dir: str, install_dir: str) -> tuple[str, ...]:
    roots = [os.path.realpath(state_dir), os.path.realpath(install_dir)]
    profile = os.path.join(state_dir, "local_work_policy.json")
    try:
        os.lstat(profile)
    except FileNotFoundError:
        return tuple(roots)
    data = json.loads(_read_snapshot_member(state_dir, "local_work_policy.json"))
    if not isinstance(data, dict) or data.get("schema_version") != "local_work_policy.v1":
        raise ValueError("invalid local work policy schema")
    configured = data.get("protected_roots")
    if not isinstance(configured, list):
        raise ValueError("protected_roots must be a list")
    for root in configured:
        if (not isinstance(root, str) or not root or "\x00" in root
                or not os.path.isabs(root) or os.path.normpath(root) != root
                or os.path.realpath(root) != root
                or (os.path.exists(root) and not os.path.isdir(root))):
            raise ValueError("protected roots must be absolute normalized directories")
        roots.append(root)
    return tuple(roots)


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

_ACTIVATION_MODES = frozenset({"disabled", "canary", "active"})
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")


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


def _read_snapshot_member(root: str, relative_path: str) -> bytes:
    """Read one closure member through a no-follow regular-file descriptor."""
    current = os.path.abspath(root)
    parts = Path(relative_path).parts
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        metadata = os.lstat(current)
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"closure path contains a symlink component: {relative_path}")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"closure parent is not a directory: {relative_path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(current, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"closure member is not a regular file: {relative_path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _read_closure_snapshot(
    install_dir: str,
) -> tuple[dict[str, bytes] | None, str | None, str | None]:
    snapshot: dict[str, bytes] = {}
    mapping: dict[str, str] = {}
    for relative_path in CLOSURE_FILES:
        try:
            source = _read_snapshot_member(install_dir, relative_path)
        except (OSError, ValueError) as exc:
            return None, None, f"CLOSURE_READ_ERROR:{relative_path}:{exc}"
        snapshot[relative_path] = source
        mapping[relative_path] = hashlib.sha256(source).hexdigest()
    canonical = json.dumps(
        mapping,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return snapshot, hashlib.sha256(canonical).hexdigest(), None


def compute_closure_root_digest(install_dir: str) -> tuple[str | None, str | None]:
    _snapshot, root, error = _read_closure_snapshot(install_dir)
    return root, error


def _read_activation_header(path: str) -> dict[str, Any] | None:
    """Read inert activation metadata before importing protected runtime code."""
    try:
        with open(path, "r", encoding="utf-8") as activation_file:
            data = json.load(activation_file)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("mode") not in _ACTIVATION_MODES:
        return None
    runtime_root_digest = data.get("runtime_root_digest")
    if not isinstance(runtime_root_digest, str) or _SHA256_HEX_RE.fullmatch(runtime_root_digest) is None:
        return None
    return data


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


def _has_shell_composition(command: str) -> bool:
    """Deny shell syntax outside literal quotes; this never proves execution safe."""
    quote = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            elif quote == '"' and char in "$`":
                return True
        elif char in "\"'":
            quote = char
        elif char in ";&|`$><\n\r":
            return True
    return False


def classify_side_effect(tool_name: str, tool_input: dict) -> tp.SideEffect:
    if tool_name in ("Glob", "Grep", "Read"):
        return tp.SideEffect.READ_ONLY
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return tp.SideEffect.BOUNDED_WRITE
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if not isinstance(cmd, str):
            return tp.SideEffect.UNKNOWN
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = []
        if tokens:
            executable = os.path.basename(tokens[0])
            if executable in {"rm", "mkfs"}:
                return tp.SideEffect.DESTRUCTIVE
            if executable == "find" and set(tokens[1:]) & {"-exec", "-execdir", "-ok", "-okdir", "-delete"}:
                return tp.SideEffect.DESTRUCTIVE
            if executable in {"curl", "wget", "ssh", "scp", "sftp"}:
                return tp.SideEffect.EXTERNAL_MUTATION
            if executable == "git":
                index = 1
                while index < len(tokens) and tokens[index].startswith("-"):
                    option = tokens[index]
                    index += 2 if option in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"} else 1
                if index < len(tokens) and tokens[index] == "push":
                    return tp.SideEffect.EXTERNAL_MUTATION
                if index < len(tokens) and tokens[index] == "reset" and "--hard" in tokens[index + 1:]:
                    return tp.SideEffect.DESTRUCTIVE
        if _DESTRUCTIVE_CMD_RE.search(cmd):
            return tp.SideEffect.DESTRUCTIVE
        if _EXTERNAL_CMD_RE.search(cmd):
            return tp.SideEffect.EXTERNAL_MUTATION
        if is_safe_readonly_command(cmd):
            return tp.SideEffect.READ_ONLY
        return tp.SideEffect.UNKNOWN
    if tool_name in ("WebFetch", "WebSearch", "SendMessage"):
        return tp.SideEffect.EXTERNAL_MUTATION
    return tp.SideEffect.UNKNOWN


def _classify_policy_path(path: str) -> tp.Tier:
    normalized = os.path.normpath(path)
    parts = tuple(part.lower() for part in normalized.split(os.sep) if part)
    filename = parts[-1] if parts else ""
    suffix = os.path.splitext(filename)[1]
    process_environment = any(
        parts[index] == "proc"
        and (
            parts[index + 2] == "environ"
            or (
                index + 4 < len(parts)
                and parts[index + 2] == "task"
                and parts[index + 4] == "environ"
            )
        )
        for index in range(len(parts) - 2)
    )

    if (
        process_environment
        or any(part in _SECRET_COMPONENTS for part in parts)
        or any(
            (_SENSITIVE_FILENAME_RE.search(part) is not None
             and not (part == filename and suffix in {".md", ".rst"}))
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
        or filename in _STARTUP_FILENAMES
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
    real_path = _absolute_target(expanded, base_dir or os.getcwd())
    tiers = {_classify_policy_path(lexical_path), _classify_policy_path(real_path)}
    effective_execution_root = execution_root
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
    paths = [os.path.abspath(os.path.join(base_dir, os.path.expanduser(base_path))), effective_base]
    if not os.path.isdir(effective_base):
        return InvocationPathResolution(tuple(paths))
    if glob_filter is not None and (
        os.path.isabs(glob_filter)
        or glob_filter.startswith("!")
        or "**" in glob_filter
        or any(char in glob_filter for char in "{}\\[]")
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


def _matches_long_option_prefix(token: str, option: str) -> bool:
    option_name = token.split("=", 1)[0]
    return option_name.startswith("--") and len(option_name) > 2 and option.startswith(option_name)


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
                or any(
                    _matches_long_option_prefix(token, option)
                    for option in (
                        "--dereference",
                        "--dereference-command-line",
                        "--dereference-command-line-symlink-to-dir",
                        "--recursive",
                    )
                )
                or (not token.startswith("--") and any(flag in token[1:] for flag in ("L", "R")))
            ):
                return InvocationPathResolution(tuple(operands or (base_dir,)), complete=False)
            if command in {"head", "tail"} and (
                token in _HEAD_TAIL_OPTIONS_WITH_VALUE
                or any(
                    _matches_long_option_prefix(token, option)
                    for option in _HEAD_TAIL_OPTIONS_WITH_VALUE
                    if option.startswith("--")
                )
            ):
                if "=" in token:
                    return InvocationPathResolution(tuple(operands or (base_dir,)), complete=False)
                if index + 1 >= len(tokens):
                    return InvocationPathResolution(tuple(operands or (base_dir,)), complete=False)
                index += 2
                continue
            wc_files0_from = "--files0-from"
            if command == "wc" and (
                _matches_long_option_prefix(token, wc_files0_from)
            ):
                if "=" not in token:
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


def _literal_search_paths(command: str, base_dir: str) -> InvocationPathResolution | None:
    """Model only grep on named files, optionally cd && and head/tail pipes.

    No recursive search, pattern files, expansion, arbitrary filters or output
    files. Reuse the regular path/Lease policy on every actual read operand.
    This is recognition of a bounded read, not approval of unknown shell code.
    """
    if not isinstance(command, str) or any(c in command for c in "$`\n\r"):
        return None
    quote = None
    escaped = False
    surface = list(command)
    for position, char in enumerate(command):
        if escaped:
            surface[position] = "x"
            escaped = False
            continue
        if char == "\\" and quote != "'":
            if quote is None:
                return None
            surface[position] = "x"
            escaped = True
        elif quote:
            surface[position] = "x"
            if char == quote:
                quote = None
        elif char in "\"'":
            surface[position] = "x"
            quote = char
        elif char in "*?[]{}~()":
            return None
    if quote or escaped:
        return None
    surface = "".join(surface)
    # Keep quote and adjacency evidence until shell operators are separated.
    # A spaced/quoted 2 is a grep operand, not descriptor 2.
    for match in reversed(list(re.finditer(r"(?<!\S)2>/dev/null(?=\s*(?:\||$))", surface))):
        padding = " " * (match.end() - match.start())
        command = command[:match.start()] + padding + command[match.end():]
        surface = surface[:match.start()] + padding + surface[match.end():]
    if any(char in surface.replace("&&", "") for char in ";&<>"):
        return None
    separators = list(re.finditer(r"&&|\|", surface))
    segments = []
    start = 0
    try:
        for separator in separators:
            segments.append(shlex.split(command[start:separator.start()]))
            start = separator.end()
        segments.append(shlex.split(command[start:]))
    except ValueError:
        return None
    paths = [base_dir]
    if segments and segments[0] and segments[0][0] == "cd":
        if (len(segments[0]) != 2 or segments[0][1].startswith("-")
                or ".." in Path(segments[0][1]).parts
                or not (os.path.isabs(segments[0][1]) or segments[0][1] == "."
                        or segments[0][1].startswith("./"))
                or not separators or separators[0].group() != "&&"):
            return None
        # A bare relative cd may use inherited CDPATH. Do not claim its cwd.
        paths.append(os.path.abspath(os.path.join(base_dir, segments[0][1])))
        base_dir = _absolute_target(segments[0][1], base_dir)
        paths.append(base_dir)
        segments = segments[1:]
        separators = separators[1:]
    if any(separator.group() != "|" for separator in separators):
        return None
    for index, segment in enumerate(segments):
        if not segment or any(t in {";", "&", "&&", "||", "<", ">", ">>", "<<", "<>"} for t in segment):
            return None
        executable = segment[0]
        name = os.path.basename(executable)
        if executable not in {name, "/usr/bin/" + name, "/bin/" + name}:
            return None
        if index == 0:
            if name != "grep":
                return None
            cursor = 1
            while cursor < len(segment) and segment[cursor].startswith("-"):
                option = segment[cursor]
                cursor += 1
                if option == "--":
                    break
                if re.fullmatch(r"-[nEFivclLqwxohH]+", option) is None:
                    return None
            # One literal pattern followed by at least one named input file.
            operands = segment[cursor + 1:]
            if cursor >= len(segment) or not operands:
                return None
            for operand in operands:
                if operand.startswith("-"):
                    return None
                target = _absolute_target(operand, base_dir)
                if os.path.isdir(target):
                    return None
                # Keep the named alias as well as the physical destination:
                # resolving .env -> ordinary.txt must not erase protection.
                paths.extend((os.path.abspath(os.path.join(base_dir, operand)), target))
        elif name not in {"head", "tail"} or not (
            len(segment) == 1
            or (len(segment) == 2 and re.fullmatch(r"-[0-9]+", segment[1]))
            or (len(segment) == 3 and segment[1] == "-n" and segment[2].isdigit())
        ):
            return None
    return InvocationPathResolution(tuple(paths))


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
    search = _literal_search_paths(command, base_dir)
    if search is not None:
        return search
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
    if tool_name == "Bash" and _literal_search_paths(tool_input.get("command", ""), base_dir) is not None:
        side_effect = tp.SideEffect.READ_ONLY
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
        try:
            os.lstat(state_store.state_path)
        except FileNotFoundError:
            # Ordinary work must not need a writable state directory or lock.
            return ActiveLeaseLookup(ActiveLeaseStatus.NO_ACTIVE)
        with state_store._locked_document() as doc:
            now = state_store._now()
            state_store._expire_due(doc, now)
            active_worktrees = tuple(
                os.path.realpath(raw["worktree_realpath"])
                for raw in doc.get("leases", [])
                if raw.get("lifecycle") == lels.LeaseLifecycle.ACTIVE.value
            )
            lookup_paths = tuple(_absolute_target(path, base_dir or os.getcwd())
                                 for path in target_paths) + (os.path.realpath(invocation_cwd or base_dir or os.getcwd()),)
            for raw in doc.get("leases", []):
                root = os.path.realpath(raw["worktree_realpath"])
                if (root not in active_worktrees
                        and any(_is_path_inside(path, root) for path in lookup_paths)):
                    return ActiveLeaseLookup(ActiveLeaseStatus.RESTRICTED,
                                             worktree_realpath=root)
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
        real_cwd = _absolute_target(invocation_cwd, lookup_base)
        cwd_matches = tuple(
            worktree
            for worktree in active_worktrees
            if _is_path_inside(real_cwd, worktree)
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
                if all(_is_path_inside(path, worktree) for path in normalized_targets)
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
            if all(_is_path_inside(path, worktree) for path in normalized_targets)
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
        if os.path.lexists(desc):
            try:
                with open(desc, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if not isinstance(d, dict) or d.get("management_mode", "lease") != "lease":
                    raise ValueError("invalid managed domain descriptor")
                return leg.ManagedExecutionDomain(
                    repository=d.get("repository", os.path.basename(curr)),
                    worktree_realpath=os.path.realpath(d.get("worktree_realpath", curr)),
                    management_mode=d.get("management_mode", "lease"),
                    policy_id=d.get("policy_id", "ume-harness-site-policy-v0"),
                    policy_sha256=d.get("policy_sha256", ""),
                )
            except Exception as exc:
                raise ValueError("managed domain descriptor cannot be trusted") from exc
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return None


def _absolute_target(path: str, base_dir: str) -> str:
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(base_dir, expanded)
    # Missing new files are ordinary; existing broken/looping aliases are not.
    # Inspect components before normalization so '..' cannot erase an alias.
    current = os.path.sep
    for component in Path(expanded).parts[1:]:
        current = os.path.join(current, component)
        if os.path.islink(current):
            os.stat(current)
    return os.path.realpath(expanded)


def _is_path_inside(path: str, root: str) -> bool:
    """Component containment; '..notes' is an ordinary child name."""
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


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
        try:
            targets.append(_absolute_target(value, base_dir))
        except OSError:
            return None, "target contains an unresolved symlink"
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
            if not _is_path_inside(real_target, active_worktree):
                return f"read target path escapes active lease worktree boundary ({active_worktree})"
    return None


def evaluate_invocation_result(
    data: dict,
    gate: leg.LocalExecutionGate | None = None,
    install_dir: str | None = None,
    state_dir: str | None = None,
) -> InvocationResult:
    if not isinstance(data, dict):
        return InvocationResult("error", "[ume-harness Lease Gate] hook input must be an object (INVALID_HOOK_INPUT)\n", "INVALID_HOOK_INPUT")
    if "tool_name" not in data:
        return InvocationResult("error", "[ume-harness Lease Gate] tool_name is required (INVALID_HOOK_INPUT)\n", "INVALID_HOOK_INPUT")
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_name, str) or not tool_name.strip() or not isinstance(tool_input, dict):
        return InvocationResult("error", "[ume-harness Lease Gate] malformed tool invocation (INVALID_HOOK_INPUT)\n", "INVALID_HOOK_INPUT")
    if tool_name == "Bash" and (not isinstance(tool_input.get("command"), str) or not tool_input["command"].strip()):
        return _result("error", "INVALID_COMMAND", "command must be a non-empty string")
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
        return InvocationResult("error", "[ume-harness Lease Gate] path-like input contains NUL (INVALID_TARGET_PATH)\n", "INVALID_TARGET_PATH")
    invocation_cwd = data.get("cwd") if isinstance(data.get("cwd"), str) and data.get("cwd") else None
    base_dir = os.path.realpath(invocation_cwd or os.getcwd())
    file_path: str | None = None
    if tool_name == "Read":
        file_path, target_error = _canonical_file_target(tool_name, tool_input, base_dir)
        if target_error is not None:
            return InvocationResult("error", f"[ume-harness Lease Gate] {target_error} (INVALID_TARGET_PATH)\n", "INVALID_TARGET_PATH")
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        file_path, target_error = _canonical_file_target(tool_name, tool_input, base_dir)
        if target_error is not None:
            return InvocationResult("error", f"[ume-harness Lease Gate] {target_error} (INVALID_TARGET_PATH)\n", "INVALID_TARGET_PATH")
    if tool_name in ("Glob", "Grep") and "path" in tool_input:
        search_path = tool_input.get("path")
        if not isinstance(search_path, str) or not search_path.strip():
            return InvocationResult("error", "[ume-harness Lease Gate] search path must be a non-empty string (INVALID_TARGET_PATH)\n", "INVALID_TARGET_PATH")
    if tool_name == "Glob":
        pattern = tool_input.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return InvocationResult("error", "[ume-harness Lease Gate] Glob pattern must be a non-empty string (INVALID_TARGET_PATH)\n", "INVALID_TARGET_PATH")
    if tool_name == "Grep":
        pattern = tool_input.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return InvocationResult("error", "[ume-harness Lease Gate] Grep pattern must be a non-empty string (INVALID_TARGET_PATH)\n", "INVALID_TARGET_PATH")
        if "glob" in tool_input:
            glob_filter = tool_input.get("glob")
            if not isinstance(glob_filter, str) or not glob_filter:
                return InvocationResult("error", "[ume-harness Lease Gate] Grep glob must be a non-empty string (INVALID_TARGET_PATH)\n", "INVALID_TARGET_PATH")

    state_dir = state_dir or os.environ.get("UME_HARNESS_STATE_DIR") or os.path.expanduser("~/.ume-harness/state")
    install_dir = install_dir or os.environ.get("UME_HARNESS_INSTALL_DIR") or _PKG_ROOT

    # 1. Verification of activation & closure integrity if activation state exists
    activation_file = os.path.join(state_dir, "activation.json")
    attested_snapshot: dict[str, bytes] | None = None
    if os.path.lexists(activation_file):
        try:
            # Parse only inert JSON metadata first. Do not import the protected
            # activation helper until the installed closure has been verified.
            activation_header = _read_activation_header(activation_file)
            if activation_header is None:
                return InvocationResult("error", "[ume-harness Lease Gate] activation state is missing or invalid (ACTIVATION_ERROR)\n", "ACTIVATION_ERROR")
            expected_root = activation_header["runtime_root_digest"]
            if not os.path.isdir(install_dir):
                return InvocationResult("error", "[ume-harness Lease Gate] installed runtime is missing (ACTIVATION_TAMPER)\n", "ACTIVATION_TAMPER")
            attested_snapshot, actual_root, err = _read_closure_snapshot(install_dir)
            if err or actual_root != expected_root or attested_snapshot is None:
                return InvocationResult("error", f"[ume-harness Lease Gate] runtime tamper or digest mismatch detected (ACTIVATION_TAMPER)\n", "ACTIVATION_TAMPER")

            # The byte identity is now proven, so load the canonical schema
            # parser from that same attested install tree.  Do not resolve it
            # from the executing runner's sys.path.
            activation = _load_attested_activation_module(attested_snapshot, install_dir)

            act = activation.read_activation_state(activation_file)
            if act is None:
                return InvocationResult("error", "[ume-harness Lease Gate] activation state is missing or invalid (ACTIVATION_ERROR)\n", "ACTIVATION_ERROR")
            if act["runtime_root_digest"] != expected_root:
                return InvocationResult("error", "[ume-harness Lease Gate] activation state changed during verification (ACTIVATION_TAMPER)\n", "ACTIVATION_TAMPER")
            if act["mode"] == "disabled":
                return InvocationResult("deny", "[ume-harness Lease Gate] lease gate is disabled by administrator (DISABLED_BY_ADMIN)\n", "DISABLED_BY_ADMIN")
        except Exception as e:
            return InvocationResult("error", f"[ume-harness Lease Gate] activation error: {e} (ACTIVATION_ERROR)\n", "ACTIVATION_ERROR")

    try:
        # No protected runtime module may execute before the activation-bound
        # closure check above.  Unactivated legacy operation keeps its prior
        # behavior and loads the same modules here before evaluation.
        _load_runtime_modules(attested_snapshot, install_dir)
    except Exception as exc:
        return InvocationResult("error", f"[ume-harness Lease Gate] protected runtime unavailable: {exc} (RUNTIME_IMPORT_ERROR)\n", "RUNTIME_IMPORT_ERROR")

    try:
        protected_roots = _protected_roots(state_dir, install_dir)
    except Exception as exc:
        return _result("error", "LOCAL_WORK_POLICY_ERROR", str(exc))

    # Claude owns these exact host-control tools.  Closure attestation and
    # activation checks above still run; only the generic local side-effect
    # policy is skipped, without synthesizing a host decision or user answer.
    if tool_name in _HOST_INTERACTION_TOOLS:
        return _result("defer", "HOST_DEFER", "host permissions apply")

    # ToolSearch is Claude's host-owned deferred-tool schema loader.  Loading a
    # capability does not authorize the later invocation of that tool; the
    # resulting tool call returns through this same wildcard PreToolUse hook.
    if tool_name in _HOST_CAPABILITY_DISCOVERY_TOOLS:
        return _result("defer", "HOST_DEFER", "host permissions apply")

    if gate is None:
        try:
            gate = leg.create_default_gate(
                state_path=os.path.join(state_dir, lels.STATE_FILENAME),
                domain_resolver=default_domain_resolver,
                # invocation_policy() below is the adapter's canonical host
                # policy decision.  The explicit bridge keeps Core's default
                # fail-closed while preserving that already-evaluated boundary.
                policy_evaluator=lambda _policy, _path, _action: True,
            )
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
        return InvocationResult("error", "[ume-harness Lease Gate] lease state store cannot be trusted (STATE_STORE_ERROR)\n", "STATE_STORE_ERROR")
    if lease_lookup.status == ActiveLeaseStatus.RESTRICTED:
        return _result("deny", "NO_ACTIVE_LEASE", "prior restricted Lease is no longer active")
    active_worktree = lease_lookup.worktree_realpath if lease_lookup.status == ActiveLeaseStatus.ACTIVE else None
    side_effect, tiers, policy_decision = invocation_policy(
        tool_name,
        tool_input,
        base_dir,
        execution_root=active_worktree,
    )

    policy_paths = provisional_resolution.paths
    if tool_name == "Bash" and side_effect == tp.SideEffect.UNKNOWN:
        command = tool_input.get("command", "")
        if "$(" in command or "`" in command:
            return _result("deny", "UNRESOLVED_SHELL_COMPOSITION", "command substitution requires explicit authority")
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
            lexer.whitespace_split = True
            lexer.whitespace = " \t\r"
            lexer.commenters = ""
            tokens = list(lexer)
        except ValueError:
            return _result("error", "INVALID_COMMAND", "command quoting is malformed")
        # Conservative explicit-consequence screen across compound segments.
        # This is not a shell interpreter or proof of safety: unresolved work
        # still reaches native ask only after domain/Lease/path checks below.
        segments = [[]]
        for token in tokens:
            if token and all(char in ";&|\n" for char in token):
                segments.append([])
            else:
                segments[-1].append(token)
        cwd_candidates = {base_dir}
        compound_paths = []
        compound_lease_paths = []
        for segment in segments:
            original_segment = tuple(segment)
            while segment and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[0]):
                segment = segment[1:]
            if segment and (segment[0] in {"<", ">", ">>", "<<", "<>"}
                            or (segment[0].isdigit() and len(segment) > 1 and segment[1] in {"<", ">", ">>", "<<", "<>"})):
                return _result("deny", "UNRESOLVED_SHELL_COMPOSITION", "leading redirection obscures the command")
            if segment and classify_side_effect("Bash", {"command": shlex.join(segment)}) in (
                tp.SideEffect.DESTRUCTIVE, tp.SideEffect.EXTERNAL_MUTATION, tp.SideEffect.AUTHORITY_TOUCH
            ):
                return _result("deny", "CONSEQUENTIAL_AUTHORITY_REQUIRED", "explicit consequential command requires separate authority")
            if segment and segment[0] == "cd":
                if len(segment) != 2 or segment[1].startswith("-") or any(c in segment[1] for c in "$*?[]{}"):
                    return _result("deny", "UNRESOLVED_SHELL_CWD", "directory change cannot be resolved")
                if not (os.path.isabs(segment[1]) or segment[1] == "." or segment[1].startswith("./")):
                    return _result("deny", "UNRESOLVED_SHELL_CWD", "directory change may depend on inherited CDPATH")
                # Consider both successful and failed/conditional cd; never
                # assume a branch executed. Bound expansion rather than guess.
                changed = {_absolute_target(segment[1], cwd) for cwd in cwd_candidates}
                cwd_candidates |= changed
                if len(cwd_candidates) > 16:
                    return _result("deny", "UNRESOLVED_SHELL_CWD", "too many directory-change outcomes")
                compound_paths.extend(changed)
            for cwd in cwd_candidates:
                for token in original_segment:
                    if "=" in token and token.split("=", 1)[1]:
                        embedded = _absolute_target(token.split("=", 1)[1], cwd)
                        compound_lease_paths.append(embedded)
                        if not token.startswith("SERVICE_ACCOUNT_JSON="):
                            compound_paths.append(embedded)
                compound_paths.extend(_absolute_target(token, cwd) for token in segment
                                      if token and not token.startswith("-") and token not in {"<", ">", ">>", "<<", "<>"})
        # This is only a deny screen, never evidence that arbitrary code is safe.
        # A credential-file binding is not a request to display its contents.
        # This narrow script form still requires native confirmation below; it
        # does not attest the script's behavior or grant external authority.
        credential_script = (
            len(tokens) >= 3
            and len(segments) == 1
            and tokens[0].startswith("SERVICE_ACCOUNT_JSON=/")
            and re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", os.path.basename(tokens[1])) is not None
            and not tokens[2].startswith("-") and tokens[2].endswith(".py")
            and not any(char in tokens[0] for char in "*?[]{}~")
        )
        if credential_script and data.get("permission_mode") == "bypassPermissions":
            return _result("deny", "CONFIRMATION_UNAVAILABLE", "credential-backed execution requires native confirmation, not bypass mode")
        screened_tokens = tokens[1:] if credential_script else tokens
        policy_paths += tuple(token for token in screened_tokens if token and not token.startswith("-"))
        policy_paths += tuple(compound_paths)
        embedded_paths = tuple(token.split("=", 1)[1] for token in tokens
                               if "=" in token and token.split("=", 1)[1])
        policy_paths += tuple(token.split("=", 1)[1] for token in screened_tokens
                              if "=" in token and token.split("=", 1)[1])
        # Unknown shell operands are discovered after provisional resolution.
        # They must participate in the same Lease check before native ask.
        if gate is not None:
            lease_lookup = get_active_lease_context(
                gate._state_store, target_paths=policy_paths + embedded_paths + tuple(compound_lease_paths), base_dir=base_dir,
                invocation_cwd=invocation_cwd)
            if lease_lookup.status == ActiveLeaseStatus.STATE_ERROR:
                return _result("error", "STATE_STORE_ERROR", "lease state store cannot be trusted")
            if lease_lookup.status == ActiveLeaseStatus.RESTRICTED:
                return _result("deny", "NO_ACTIVE_LEASE", "prior restricted Lease is no longer active")
            active_worktree = lease_lookup.worktree_realpath if lease_lookup.status == ActiveLeaseStatus.ACTIVE else None
            side_effect, tiers, policy_decision = invocation_policy(
                tool_name, tool_input, base_dir, execution_root=active_worktree)
    for path in policy_paths:
        lexical = os.path.abspath(os.path.join(base_dir, os.path.expanduser(path)))
        if any(_is_path_inside(candidate, root)
               for root in protected_roots
               for candidate in (lexical, _absolute_target(path, base_dir))):
            if side_effect != tp.SideEffect.READ_ONLY:
                return _result("deny", "PROTECTED_ZONE_VIOLATION", "target is protected local control plane")
        if tool_name == "Bash" and side_effect == tp.SideEffect.UNKNOWN and resolve_path_tier(path, base_dir) in (
            tp.Tier.TIER_SECRETS, tp.Tier.TIER_GOVERNANCE, tp.Tier.TIER_CONSTITUTION
        ):
            return _result("deny", "PROTECTED_TARGET", "command references a protected target")

    try:
        domains = tuple(default_domain_resolver(_absolute_target(path, base_dir))
                        for path in policy_paths + (base_dir,))
    except Exception as exc:
        return _result("error", "DOMAIN_RESOLVER_ERROR", str(exc))
    if active_worktree is None and any(domain is not None for domain in domains):
        return _result("deny", "NO_ACTIVE_LEASE", "managed domain requires an active Lease")

    # Path containment cannot establish provenance for multiply-linked files.
    # This managed-mode check is not an OS sandbox or a race-free inode guard.
    if active_worktree is not None:
        for path in policy_paths:
            try:
                info = os.stat(_absolute_target(path, base_dir))
            except FileNotFoundError:
                continue
            except OSError:
                return _result("error", "TARGET_STAT_ERROR", "cannot verify managed target metadata")
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                return _result("deny", "UNVERIFIABLE_FILE_ALIAS", "managed target has multiple hard links")

    # 2. Read scope escape check under active lease
    if active_worktree is not None and tool_name in ("Read", "Glob", "Grep", "Bash"):
        escape_reason = check_read_scope_escape(
            tool_name,
            tool_input,
            active_worktree,
            base_dir,
        )
        if escape_reason is not None:
            return InvocationResult("deny", f"[ume-harness Lease Gate] {escape_reason} (SCOPE_ESCAPE)\n", "SCOPE_ESCAPE")

    # Explicit Lease and managed-domain constraints precede ordinary host defer.
    if tool_name in ("Edit", "Write", "NotebookEdit") and gate is not None:
        action = leg.GateAction.WRITE if tool_name == "Write" else leg.GateAction.EDIT
        gate_res = gate.evaluate_request(file_path, action)
        if gate_res.decision == leg.GateDecision.DENY:
            code = gate_res.violation_code or "LEASE_DENIED"
            decision = "error" if code in {"STATE_STORE_ERROR", "DOMAIN_RESOLVER_ERROR", "POLICY_EVALUATION_ERROR"} else "deny"
            return _result(decision, code, gate_res.reason)
        if gate_res.decision == leg.GateDecision.NOT_APPLICABLE and active_worktree is not None:
            return _result("deny", "SCOPE_ESCAPE", "active Lease requires a matching managed domain")

    if policy_decision == tp.Decision.DENY:
        return _result("deny", "POLICY_DENIED", f"{tool_name}: {side_effect.value} / {tiers[0].value}")
    if side_effect in (tp.SideEffect.DESTRUCTIVE, tp.SideEffect.EXTERNAL_MUTATION, tp.SideEffect.AUTHORITY_TOUCH):
        return _result("deny", "CONSEQUENTIAL_AUTHORITY_REQUIRED", "external or consequential authority is not provided by local confirmation")
    if side_effect != tp.SideEffect.READ_ONLY and any(
        tier in (tp.Tier.TIER_GOVERNANCE, tp.Tier.TIER_CONSTITUTION, tp.Tier.TIER_SECRETS)
        for tier in tiers
    ):
        return _result("deny", "PROTECTED_TARGET", "protected target requires its explicit authority")
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return _result("defer", "HOST_DEFER", "ordinary local edit uses host permissions")
    if policy_decision == tp.Decision.ALLOW:
        return _result("defer", "HOST_DEFER", "host permissions apply")
    if tool_name == "Bash" and active_worktree is None:
        if data.get("permission_mode") == "bypassPermissions":
            return _result("deny", "CONFIRMATION_UNAVAILABLE", "unresolved execution requires native confirmation, not bypass mode")
        return _result("ask", "LOCAL_EXECUTION_CONFIRMATION", "opaque local command requires host confirmation")
    return _result("deny", "UNRESOLVED_OPERATION", "operation cannot be proven within its execution constraints")


def evaluate_invocation(
    data: dict,
    gate: leg.LocalExecutionGate | None = None,
    install_dir: str | None = None,
    state_dir: str | None = None,
) -> tuple[int, str | None]:
    """Compatibility only: typed decisions are the single evaluation result."""
    result = evaluate_invocation_result(data, gate, install_dir, state_dir)
    return (0, None) if result.decision == "defer" else (2, result.reason)


def evaluate_host_path(
    target_path: str,
    action: str = "edit",
    install_dir: str | None = None,
    state_dir: str | None = None,
    worktrees_root: str | None = None,
) -> int:
    """Report the typed policy verdict without claiming host authorization."""
    tool_name = "Write" if action == "write" else "Edit"
    result = evaluate_invocation_result(
        {"tool_name": tool_name, "tool_input": {"file_path": target_path}},
        install_dir=install_dir,
        state_dir=state_dir,
    )
    return _emit(result.decision.upper(), result.reason.strip(), result.code)


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
