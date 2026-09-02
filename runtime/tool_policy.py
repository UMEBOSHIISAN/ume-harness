#!/usr/bin/env python3
"""
tool_policy.py — Portable Tool Policy (ume-harness Core)

5つの副作用クラスと5層のAuthority Tierを組み合わせて、操作の可否
（ALLOW / APPROVAL_REQUIRED / DENY）を決定する。個人実装（unified_tool_classifier.py /
write-gate.sh / validate-command.sh）から、ビジネス固有ロジック（WooCommerce/X API/
production host/pm2/crontab等）を除去し、汎用の分類・tier決定ロジックのみを抽出したもの。

契約書: ../contracts/tool_policy.md / ../contracts/authority_contract.md
"""

from __future__ import annotations
from contextlib import contextmanager
import fcntl
import json
import os
import stat
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TokenCommitDurabilityError(OSError):
    """The token replacement committed but directory durability was unproven."""


class SideEffect(str, Enum):
    READ_ONLY = "READ_ONLY"
    BOUNDED_WRITE = "BOUNDED_WRITE"
    EXTERNAL_MUTATION = "EXTERNAL_MUTATION"
    DESTRUCTIVE = "DESTRUCTIVE"
    AUTHORITY_TOUCH = "AUTHORITY_TOUCH"
    UNKNOWN = "UNKNOWN"


class Tier(str, Enum):
    TIER_CONSTITUTION = "TIER_CONSTITUTION"
    TIER_SECRETS = "TIER_SECRETS"
    TIER_GOVERNANCE = "TIER_GOVERNANCE"
    TIER_RUNTIME_CODE = "TIER_RUNTIME_CODE"
    TIER_NORMAL = "TIER_NORMAL"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENY = "DENY"


# Tier x SideEffect 決定表（contracts/tool_policy.md の表を実装化したもの）
_DECISION_TABLE: dict[Tier, dict[SideEffect, Decision]] = {
    Tier.TIER_NORMAL: {
        SideEffect.READ_ONLY: Decision.ALLOW,
        SideEffect.BOUNDED_WRITE: Decision.ALLOW,
        SideEffect.EXTERNAL_MUTATION: Decision.APPROVAL_REQUIRED,
        SideEffect.DESTRUCTIVE: Decision.APPROVAL_REQUIRED,
        SideEffect.AUTHORITY_TOUCH: Decision.APPROVAL_REQUIRED,
        SideEffect.UNKNOWN: Decision.APPROVAL_REQUIRED,
    },
    Tier.TIER_RUNTIME_CODE: {
        # 2026-08-18 human裁定: delegate必須はCoreに固定しない。既定は明示承認のみ。
        SideEffect.READ_ONLY: Decision.ALLOW,
        SideEffect.BOUNDED_WRITE: Decision.APPROVAL_REQUIRED,
        SideEffect.EXTERNAL_MUTATION: Decision.APPROVAL_REQUIRED,
        SideEffect.DESTRUCTIVE: Decision.APPROVAL_REQUIRED,
        SideEffect.AUTHORITY_TOUCH: Decision.APPROVAL_REQUIRED,
        SideEffect.UNKNOWN: Decision.APPROVAL_REQUIRED,
    },
    Tier.TIER_GOVERNANCE: {
        SideEffect.READ_ONLY: Decision.ALLOW,
        SideEffect.BOUNDED_WRITE: Decision.APPROVAL_REQUIRED,
        SideEffect.EXTERNAL_MUTATION: Decision.APPROVAL_REQUIRED,
        SideEffect.DESTRUCTIVE: Decision.APPROVAL_REQUIRED,
        SideEffect.AUTHORITY_TOUCH: Decision.APPROVAL_REQUIRED,
        SideEffect.UNKNOWN: Decision.APPROVAL_REQUIRED,
    },
    Tier.TIER_SECRETS: {
        # 読み取りすら拒否。副作用クラスに関わらず一律DENY。
        SideEffect.READ_ONLY: Decision.DENY,
        SideEffect.BOUNDED_WRITE: Decision.DENY,
        SideEffect.EXTERNAL_MUTATION: Decision.DENY,
        SideEffect.DESTRUCTIVE: Decision.DENY,
        SideEffect.AUTHORITY_TOUCH: Decision.DENY,
        SideEffect.UNKNOWN: Decision.DENY,
    },
    Tier.TIER_CONSTITUTION: {
        SideEffect.READ_ONLY: Decision.ALLOW,
        SideEffect.BOUNDED_WRITE: Decision.DENY,
        SideEffect.EXTERNAL_MUTATION: Decision.DENY,
        SideEffect.DESTRUCTIVE: Decision.DENY,
        SideEffect.AUTHORITY_TOUCH: Decision.DENY,
        SideEffect.UNKNOWN: Decision.DENY,
    },
}


def decide(tier: Tier, side_effect: SideEffect) -> Decision:
    """Tier x SideEffect の組み合わせから ALLOW/APPROVAL_REQUIRED/DENY を返す。
    未知の組み合わせは fail-closed で APPROVAL_REQUIRED を返す（無言でDENYにも
    ALLOWにも倒さない）。"""
    row = _DECISION_TABLE.get(tier)
    if row is None:
        return Decision.APPROVAL_REQUIRED
    return row.get(side_effect, Decision.APPROVAL_REQUIRED)


@dataclass
class ApprovalToken:
    action: str
    scope_target: str
    expires_epoch: int
    uses_remaining: int


class TokenStore:
    """Canonical Authority Token の保管・アトミック消費。
    JSON store: {"tokens": [ {action, scope_target, expires_epoch, uses_remaining}, ... ]}
    一致するトークンが複数あっても、最も早く期限切れになる1件だけを消費する
    （元実装で一度「全件を一括減算する」バグが起きた教訓をCore仕様として明記）。
    """

    def __init__(self, store_path: str):
        self.store_path = os.path.abspath(os.fspath(store_path))
        self.lock_path = f"{self.store_path}.lock"

    @staticmethod
    def _reject_alias(path: str, label: str) -> None:
        """Do not consume through symlink/hard-link aliases with separate locks."""
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError(f"{label} must be a regular, non-symlink file")
        if metadata.st_nlink != 1:
            raise OSError(f"{label} must not have hard-link aliases")

    def _load(self) -> dict:
        if not os.path.exists(self.store_path):
            return {"tokens": []}
        with open(self.store_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_atomic(self, data: dict) -> None:
        dir_name = os.path.dirname(self.store_path) or "."
        os.makedirs(dir_name, exist_ok=True)
        self._reject_alias(self.store_path, "token store")
        temp_name = None
        committed = False
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=dir_name, delete=False, encoding="utf-8"
            ) as tf:
                # Capture the path immediately after creation so cleanup also
                # covers write/flush/fsync failures before the first write.
                temp_name = tf.name
                json.dump(data, tf, ensure_ascii=False, indent=2)
                tf.write("\n")
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(temp_name, self.store_path)
            committed = True
            dir_fd = os.open(dir_name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            if committed:
                raise TokenCommitDurabilityError(
                    "token replacement committed but directory durability could not be confirmed"
                ) from exc
            raise
        finally:
            if temp_name is not None and os.path.exists(temp_name):
                os.unlink(temp_name)

    @contextmanager
    def _locked_store(self):
        """Serialize token read/validate/decrement/write transactions."""
        dir_name = os.path.dirname(self.store_path) or "."
        os.makedirs(dir_name, exist_ok=True)
        self._reject_alias(self.store_path, "token store")
        self._reject_alias(self.lock_path, "token lock")
        lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    @staticmethod
    def _valid_document(data: object) -> bool:
        if not isinstance(data, dict) or not isinstance(data.get("tokens"), list):
            return False
        for token in data["tokens"]:
            if not isinstance(token, dict):
                return False
            action = token.get("action")
            scope_target = token.get("scope_target")
            expires_epoch = token.get("expires_epoch")
            uses_remaining = token.get("uses_remaining")
            if not isinstance(action, str) or not action:
                return False
            if not isinstance(scope_target, str) or not scope_target:
                return False
            if isinstance(expires_epoch, bool) or not isinstance(expires_epoch, int):
                return False
            if isinstance(uses_remaining, bool) or not isinstance(uses_remaining, int):
                return False
            if uses_remaining < 0:
                return False
        return True

    def consume(self, action: str, scope_target: Optional[str] = None) -> bool:
        """action（+ scope_target が指定されていればそれも一致）に該当する
        有効なトークンのうち最も早く期限切れになる1件を消費する。消費できたら True。"""
        if not isinstance(action, str) or not action:
            return False
        if scope_target is not None and (
            not isinstance(scope_target, str) or not scope_target
        ):
            return False

        try:
            with self._locked_store():
                data = self._load()
                if not self._valid_document(data):
                    return False

                now = int(time.time())
                candidates = []
                for i, t in enumerate(data["tokens"]):
                    if t["action"] != action:
                        continue
                    if scope_target is not None and t["scope_target"] != scope_target:
                        continue
                    if t["expires_epoch"] <= now or t["uses_remaining"] <= 0:
                        continue
                    candidates.append((i, t))

                if not candidates:
                    return False

                idx, _ = min(candidates, key=lambda pair: pair[1]["expires_epoch"])
                data["tokens"][idx]["uses_remaining"] -= 1
                self._save_atomic(data)
                return True
        except TokenCommitDurabilityError:
            # The logical consume already committed before the durability
            # check failed. Report success so callers do not retry and spend
            # a second approval; later verification can surface the durability
            # issue separately.
            return True
        except (OSError, TypeError, ValueError):
            # Corrupt/unavailable authority state must never authorize a request.
            return False


def classify_command_side_effect(
    command_verbs: list[str],
    destructive_verbs: frozenset[str] = frozenset(
        {"rm", "delete", "drop", "truncate", "reset_hard"}
    ),
    external_verbs: frozenset[str] = frozenset(
        {"send", "publish", "post", "push", "purchase", "pay"}
    ),
    authority_verbs: frozenset[str] = frozenset(
        {"grant", "revoke", "approve", "edit_policy", "edit_settings"}
    ),
) -> SideEffect:
    """操作を表す動詞の集合（アダプタ側で正規化済みのもの）から副作用クラスを決める。
    どの集合にも一致しなければ UNKNOWN を返し、呼び出し側の decide() で
    fail-closed（APPROVAL_REQUIRED）に倒す。個人実装の「文字列部分一致で誤爆する」
    パターンを避けるため、正規化済みの動詞集合を受け取る設計にしている
    （生コマンド文字列への正規表現マッチはCoreの責務にしない）。"""
    verbs = set(command_verbs)
    if verbs & destructive_verbs:
        return SideEffect.DESTRUCTIVE
    if verbs & authority_verbs:
        return SideEffect.AUTHORITY_TOUCH
    if verbs & external_verbs:
        return SideEffect.EXTERNAL_MUTATION
    if not verbs:
        return SideEffect.UNKNOWN
    if verbs <= {"read", "list", "search", "view"}:
        return SideEffect.READ_ONLY
    if verbs <= {"write", "edit", "create"}:
        return SideEffect.BOUNDED_WRITE
    return SideEffect.UNKNOWN
