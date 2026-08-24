#!/usr/bin/env python3
"""runtime/translation_konjac.py — Hardened Auto Translation Konjac Engine (P0 Final).

Deterministic, context-aware, push-based translator for Claude Code technical events.
Maps raw tool and bash invocations to stable concept_ids and renders bounded Japanese
text from common_language_pack.
Presentation-only boundary:
- this module renders explanatory metadata and banners; it does not grant or deny permission;
- ``effect_level`` is display metadata and is not an Authority event, approval, or consume input;
- local gate / Authority decisions must be evaluated independently by the host adapter.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import common_language_pack as pack


class Locality(str, Enum):
    LOCAL_PC = "LOCAL_PC"
    LOCAL_GIT = "LOCAL_GIT"
    REMOTE_GIT = "REMOTE_GIT"
    EXTERNAL_NETWORK = "EXTERNAL_NETWORK"
    UNKNOWN = "UNKNOWN"


class EffectLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOCAL_WRITE = "LOCAL_WRITE"
    TEST_EXECUTION = "TEST_EXECUTION"
    EXTERNAL_TRANSMIT = "EXTERNAL_TRANSMIT"
    DESTRUCTIVE = "DESTRUCTIVE"
    UNKNOWN = "UNKNOWN"


_EFFECT_SEVERITY: Dict[EffectLevel, int] = {
    EffectLevel.READ_ONLY: 1,
    EffectLevel.TEST_EXECUTION: 2,
    EffectLevel.LOCAL_WRITE: 3,
    EffectLevel.EXTERNAL_TRANSMIT: 4,
    EffectLevel.DESTRUCTIVE: 5,
    EffectLevel.UNKNOWN: 6,
}


@dataclass(frozen=True)
class ConceptMatch:
    concept_id: str
    effect_level: EffectLevel
    raw_event: str
    is_known: bool
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TranslationResult:
    concept_id: str
    headline: str
    locality_badge: str
    explanation: str
    effect_level: EffectLevel
    raw_event: str
    is_known: bool
    params: Dict[str, Any] = field(default_factory=dict)


def sanitize_remote_url(raw_url: str) -> Tuple[str, str]:
    """Sanitize credentials from Git remote URL and return (service_name, display_host)."""
    trimmed = raw_url.strip()
    if not trimmed:
        return "PCの外にあるGit保管先 (未設定)", "未設定"

    # 1. Standard URL scheme: https://..., ssh://..., git://...
    if "://" in trimmed:
        try:
            parsed = urllib.parse.urlparse(trimmed)
            host = (parsed.hostname or "").lower()
            if host == "github.com":
                return "GitHub", host
            elif host == "gitlab.com":
                return "GitLab", host
            elif host == "bitbucket.org":
                return "Bitbucket", host
            elif host:
                return f"Git保管先 ({host})", host
        except Exception:
            pass

    # 2. SCP-style: [user@]host:path/to/repo.git
    scp_match = re.match(r"^(?:[\w-]+@)?([\w.-]+):(?:.+)$", trimmed)
    if scp_match:
        host = scp_match.group(1).lower()
        if host == "github.com":
            return "GitHub", host
        elif host == "gitlab.com":
            return "GitLab", host
        elif host == "bitbucket.org":
            return "Bitbucket", host
        return f"Git保管先 ({host})", host

    return "PCの外にあるGit保管先 (未確定)", "未確定"


def resolve_remote_service(cwd: str, remote_name: Optional[str] = None) -> Tuple[str, str]:
    """Resolve remote service name from actual local git config with exact hostname matching."""
    try:
        if not remote_name:
            # Try to resolve upstream remote from current tracking branch
            res_upstream = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if res_upstream.returncode == 0 and "/" in res_upstream.stdout.strip():
                remote_name = res_upstream.stdout.strip().split("/")[0]
            else:
                return "設定されたGit送信先 (未確定)", "未確定"

        res = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", remote_name],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if res.returncode == 0:
            return sanitize_remote_url(res.stdout.strip())
    except Exception:
        pass
    return "PCの外にあるGit保管先 (未確定)", "未確定"


def _parse_single_command_tokens(tokens: List[str], raw_segment: str, cwd: str) -> ConceptMatch:
    """Parse a single command (no logical operators or pipes) into a ConceptMatch."""
    if not tokens:
        return ConceptMatch("unknown.command", EffectLevel.UNKNOWN, raw_segment, False, {"cmd_preview": "", "cmd_full": ""})

    cmd_name = os.path.basename(tokens[0])

    # 1. Git commands
    if cmd_name == "git" and len(tokens) >= 2:
        sub = tokens[1]
        
        # git status
        if sub == "status":
            allowed_status_flags = {"-s", "--short", "-b", "--branch", "-u", "--untracked-files", "--ignored", "-v", "--verbose"}
            unknown_status_flags = [t for t in tokens[2:] if t.startswith("-") and not any(t.startswith(a) for a in allowed_status_flags)]
            if unknown_status_flags:
                return ConceptMatch("unknown.command", EffectLevel.UNKNOWN, raw_segment, False, {
                    "cmd_preview": raw_segment[:40], "cmd_full": raw_segment
                })
            return ConceptMatch("git.status", EffectLevel.READ_ONLY, raw_segment, True)

        # git diff
        if sub == "diff":
            if any(t in ("--cached", "--staged") for t in tokens[2:]):
                return ConceptMatch("git.diff.staged", EffectLevel.READ_ONLY, raw_segment, True)
            return ConceptMatch("git.diff.working", EffectLevel.READ_ONLY, raw_segment, True)

        # git add
        if sub == "add":
            add_args = [t for t in tokens[2:] if not t.startswith("-")]
            add_flags = [t for t in tokens[2:] if t.startswith("-")]
            allowed_add_flags = {"-A", "--all", "-u", "--update", "-v", "--verbose", "-f", "--force"}
            if any(f not in allowed_add_flags for f in add_flags):
                return ConceptMatch("unknown.command", EffectLevel.UNKNOWN, raw_segment, False, {
                    "cmd_preview": raw_segment[:40], "cmd_full": raw_segment
                })
            if any(f in ("-A", "--all") for f in add_flags):
                if add_args:
                    target = add_args[0]
                    return ConceptMatch("git.add.path", EffectLevel.LOCAL_WRITE, raw_segment, True, {"path": target})
                return ConceptMatch("git.add.all", EffectLevel.LOCAL_WRITE, raw_segment, True)
            if "." in tokens[2:]:
                return ConceptMatch("git.add.dot", EffectLevel.LOCAL_WRITE, raw_segment, True)
            target = add_args[0] if add_args else "ファイル"
            return ConceptMatch("git.add.path", EffectLevel.LOCAL_WRITE, raw_segment, True, {"path": target})

        # git commit
        if sub == "commit":
            commit_flags = [t for t in tokens[2:] if t.startswith("-")]
            allowed_commit_flags = {"-m", "--message", "--amend", "-a", "--all", "-v", "--verbose", "-q", "--quiet"}
            if any(not any(f.startswith(a) for a in allowed_commit_flags) for f in commit_flags):
                return ConceptMatch("unknown.command", EffectLevel.UNKNOWN, raw_segment, False, {
                    "cmd_preview": raw_segment[:40], "cmd_full": raw_segment
                })

            is_amend = "--amend" in tokens[2:]
            msg = ""
            for i, t in enumerate(tokens[2:]):
                if t in ("-m", "--message") and i + 1 < len(tokens[2:]):
                    msg = tokens[2:][i + 1]
                    break
            msg_note = f"（メッセージ: {msg}）" if msg else ""
            concept_id = "git.commit.amend" if is_amend else "git.commit.normal"
            return ConceptMatch(concept_id, EffectLevel.LOCAL_WRITE, raw_segment, True, {"msg_note": msg_note})

        # git push
        if sub == "push":
            push_args = tokens[2:]
            flags = [t for t in push_args if t.startswith("-")]
            positionals = [t for t in push_args if not t.startswith("-")]

            allowed_push_prefixes = (
                "-u", "--set-upstream", "-f", "--force", "-d", "--delete",
                "--mirror", "--all", "--tags", "--force-with-lease",
                "-v", "--verbose", "-q", "--quiet"
            )
            # If any unhandled/unknown flag is present (e.g. --prune, --atomic, --porcelain, etc.) -> unknown
            if any(not any(f.startswith(a) for a in allowed_push_prefixes) for f in flags):
                return ConceptMatch("unknown.command", EffectLevel.UNKNOWN, raw_segment, False, {
                    "cmd_preview": raw_segment[:40], "cmd_full": raw_segment
                })

            is_force = any(f in ("-f", "--force") or f.startswith("--force-with-lease") for f in flags)
            is_delete = any(f in ("-d", "--delete") for f in flags)
            is_mirror = "--mirror" in flags
            is_all = "--all" in flags
            is_tags = "--tags" in flags

            remote = positionals[0] if len(positionals) >= 1 else None
            refspec = positionals[1] if len(positionals) >= 2 else (None if len(positionals) == 0 else "現在の作業ブランチ")

            service_name, _ = resolve_remote_service(cwd, remote)

            if not refspec:
                # Try to resolve upstream branch
                try:
                    res_ubranch = subprocess.run(
                        ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                        capture_output=True,
                        text=True,
                        timeout=1,
                    )
                    if res_ubranch.returncode == 0 and "/" in res_ubranch.stdout.strip():
                        branch_name = res_ubranch.stdout.strip().split("/", 1)[1]
                    else:
                        branch_name = "UNKNOWN (未設定)"
                except Exception:
                    branch_name = "UNKNOWN (未設定)"
            else:
                # Check for refspec deletion e.g. :branch
                if refspec.startswith(":") and len(refspec) > 1:
                    is_delete = True
                    branch_name = refspec[1:]
                elif ":" in refspec:
                    branch_name = refspec.split(":")[-1]
                else:
                    branch_name = refspec

                if branch_name.startswith("refs/heads/"):
                    branch_name = branch_name.replace("refs/heads/", "")

            if is_delete:
                return ConceptMatch("git.push.delete", EffectLevel.DESTRUCTIVE, raw_segment, True, {
                    "service": service_name, "branch": branch_name
                })
            if is_force or is_mirror:
                return ConceptMatch("git.push.force", EffectLevel.DESTRUCTIVE, raw_segment, True, {
                    "service": service_name, "branch": branch_name
                })
            if is_all:
                return ConceptMatch("git.push.all", EffectLevel.EXTERNAL_TRANSMIT, raw_segment, True, {
                    "service": service_name
                })
            if is_tags:
                return ConceptMatch("git.push.tags", EffectLevel.EXTERNAL_TRANSMIT, raw_segment, True, {
                    "service": service_name
                })
            if branch_name in ("main", "master"):
                return ConceptMatch("git.push.main", EffectLevel.EXTERNAL_TRANSMIT, raw_segment, True, {
                    "service": service_name, "branch": branch_name
                })
            return ConceptMatch("git.push.normal", EffectLevel.EXTERNAL_TRANSMIT, raw_segment, True, {
                "service": service_name, "branch": branch_name
            })

    # 2. Test commands (pytest, python -m unittest, npm test)
    if cmd_name == "pytest" or (cmd_name in ("python", "python3") and len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] in ("pytest", "unittest")):
        return ConceptMatch("test.pytest", EffectLevel.TEST_EXECUTION, raw_segment, True)

    if cmd_name == "npm":
        if len(tokens) >= 2:
            npm_sub = tokens[1]
            if npm_sub in ("test", "t") or (npm_sub in ("run", "run-script") and len(tokens) >= 3 and tokens[2] == "test"):
                return ConceptMatch("test.npm", EffectLevel.TEST_EXECUTION, raw_segment, True)
            if npm_sub in ("install", "i", "add"):
                return ConceptMatch("package.npm.install", EffectLevel.LOCAL_WRITE, raw_segment, True)

    # 3. Destructive file operations (rm, rmdir)
    if cmd_name == "rm":
        rm_args = [t for t in tokens[1:] if not t.startswith("-")]
        target = rm_args[0] if rm_args else "指定ファイル/フォルダ"
        return ConceptMatch("fs.delete", EffectLevel.DESTRUCTIVE, raw_segment, True, {"target": target})

    # Fallback to unknown command
    cmd_preview = raw_segment[:40] + ("..." if len(raw_segment) > 40 else "")
    return ConceptMatch("unknown.command", EffectLevel.UNKNOWN, raw_segment, False, {"cmd_preview": cmd_preview, "cmd_full": raw_segment})


def _split_into_command_segments(cmd: str) -> List[str]:
    """Split compound command string into individual segment strings."""
    segments = re.split(r"(?:&&|\|\||;|\n)+", cmd)
    return [s.strip() for s in segments if s.strip()]


def translate_bash_command(cmd: str, cwd: str) -> TranslationResult:
    """Parse and translate compound or single Bash command."""
    trimmed = cmd.strip()
    if not trimmed:
        return render_concept(ConceptMatch("unknown.command", EffectLevel.UNKNOWN, "", False, {"cmd_preview": "", "cmd_full": ""}))

    # Check for command substitutions $(...) or `...`
    has_subshell = bool(re.search(r"\$\(.*\)|\`.*\`", trimmed))

    # Split into independent statements
    segments = _split_into_command_segments(trimmed)

    # Single segment processing
    if len(segments) == 1 and not has_subshell and "|" not in trimmed and ">" not in trimmed:
        try:
            tokens = shlex.split(segments[0])
            match = _parse_single_command_tokens(tokens, segments[0], cwd)
            return render_concept(match)
        except Exception:
            pass

    # Compound or pipeline or redirection analysis
    evaluated_matches: List[ConceptMatch] = []
    has_redirection = bool(re.search(r"(?:^|[^<])>(?:[^>]|$)|>>", trimmed))

    for seg in segments:
        pipe_parts = seg.split("|")
        for part in pipe_parts:
            part_trimmed = part.strip()
            if not part_trimmed:
                continue
            try:
                tokens = shlex.split(part_trimmed)
                m = _parse_single_command_tokens(tokens, part_trimmed, cwd)
                evaluated_matches.append(m)
            except Exception:
                evaluated_matches.append(ConceptMatch("unknown.command", EffectLevel.UNKNOWN, part_trimmed, False, {
                    "cmd_preview": part_trimmed[:30], "cmd_full": part_trimmed
                }))

    if not evaluated_matches:
        return render_concept(ConceptMatch("unknown.command", EffectLevel.UNKNOWN, trimmed, False, {"cmd_preview": trimmed[:40], "cmd_full": trimmed}))

    max_effect = max((m.effect_level for m in evaluated_matches), key=lambda e: _EFFECT_SEVERITY[e])
    if has_redirection and _EFFECT_SEVERITY[max_effect] < _EFFECT_SEVERITY[EffectLevel.LOCAL_WRITE]:
        max_effect = EffectLevel.LOCAL_WRITE

    if has_subshell and _EFFECT_SEVERITY[max_effect] < _EFFECT_SEVERITY[EffectLevel.UNKNOWN]:
        max_effect = EffectLevel.UNKNOWN

    if len(evaluated_matches) == 1 and not has_redirection and not has_subshell:
        return render_concept(evaluated_matches[0])

    seg_summaries = []
    for m in evaluated_matches:
        title = pack.JA_CONCEPT_PACK.get(m.concept_id, {}).get("headline", m.raw_event)
        try:
            title = title.format(**m.params)
        except Exception:
            pass
        seg_summaries.append(f"・{title}")
    
    if has_redirection:
        seg_summaries.append("・ファイルへの書き込み（リダイレクト >）")

    summary_text = "\n".join(seg_summaries)
    compound_match = ConceptMatch(
        "shell.compound",
        max_effect,
        trimmed,
        is_known=all(m.is_known for m in evaluated_matches),
        params={"max_impact": max_effect.value, "segments_summary": summary_text}
    )
    return render_concept(compound_match)


def translate_tool_event(tool_name: str, tool_input: Dict[str, Any], cwd: str) -> TranslationResult:
    """Translate raw Claude Code tool invocation."""
    try:
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            return translate_bash_command(cmd, cwd)

        if tool_name in ("Read", "ViewFile"):
            path = tool_input.get("file_path", "") or tool_input.get("path", "")
            rel_path = os.path.relpath(path, cwd) if path and os.path.isabs(path) else path
            match = ConceptMatch("fs.read", EffectLevel.READ_ONLY, f"{tool_name}({rel_path})", True, {"path": rel_path})
            return render_concept(match)

        if tool_name in ("Grep", "Glob"):
            query = tool_input.get("pattern", "") or tool_input.get("query", "")
            match = ConceptMatch("fs.grep", EffectLevel.READ_ONLY, f"{tool_name}({query})", True, {"query": query})
            return render_concept(match)

        if tool_name == "Edit":
            path = tool_input.get("file_path", "") or tool_input.get("path", "")
            rel_path = os.path.relpath(path, cwd) if path and os.path.isabs(path) else path
            match = ConceptMatch("fs.edit", EffectLevel.LOCAL_WRITE, f"Edit({rel_path})", True, {"path": rel_path})
            return render_concept(match)

        if tool_name == "Write":
            path = tool_input.get("file_path", "") or tool_input.get("path", "")
            full_path = os.path.join(cwd, path) if path and not os.path.isabs(path) else path
            rel_path = os.path.relpath(path, cwd) if path and os.path.isabs(path) else path
            
            if os.path.exists(full_path):
                match = ConceptMatch("fs.write_overwrite", EffectLevel.LOCAL_WRITE, f"Write({rel_path})", True, {"path": rel_path})
            else:
                match = ConceptMatch("fs.write_new", EffectLevel.LOCAL_WRITE, f"Write({rel_path})", True, {"path": rel_path})
            return render_concept(match)

        match = ConceptMatch("unknown.tool", EffectLevel.UNKNOWN, f"{tool_name}({tool_input})", False, {"tool_name": tool_name})
        return render_concept(match)

    except Exception:
        return render_concept(ConceptMatch("fallback.failure", EffectLevel.UNKNOWN, f"{tool_name}", False))


def render_concept(match: ConceptMatch) -> TranslationResult:
    """Render a ConceptMatch into a TranslationResult using the Language Pack."""
    tmpl = pack.JA_CONCEPT_PACK.get(match.concept_id, pack.JA_CONCEPT_PACK.get("unknown.command", {}))
    
    headline = tmpl.get("headline", "")
    badge = tmpl.get("badge", "")
    explanation = tmpl.get("explanation", "")

    try:
        headline = headline.format(**match.params)
        badge = badge.format(**match.params)
        explanation = explanation.format(**match.params)
    except Exception:
        pass

    return TranslationResult(
        concept_id=match.concept_id,
        headline=headline,
        locality_badge=badge,
        explanation=explanation,
        effect_level=match.effect_level,
        raw_event=match.raw_event,
        is_known=match.is_known,
        params=match.params,
    )


def format_user_banner(res: TranslationResult, permission_context: bool = False) -> str:
    """Format the translation into a non-intrusive, natural Japanese explanation block."""
    if permission_context or res.effect_level in (EffectLevel.EXTERNAL_TRANSMIT, EffectLevel.DESTRUCTIVE, EffectLevel.UNKNOWN):
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🇯🇵 {res.headline}",
            f"   {res.locality_badge}",
            f"   詳細: {res.explanation}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        return "\n".join(lines) + "\n"
    
    return f"  ↳ 🇯🇵 {res.headline} ({res.locality_badge})\n"
