#!/usr/bin/env python3
"""
stop_adapter.py — Portable Stop Adapter (ume-harness Core)

個人実装（unified_stop_router.py）から、7段の個人hook直列実行（budget alert / docs
reminder / browser leak check / 音声persona等）を全て除去し、
contracts/autonomous_stop.md の5条件チェックのみを行う最小adapterへ一般化したもの。

Work Type非依存（コードタスクの「テスト全通」に限定しない）。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class AcceptanceStatus(str, Enum):
    STOP_COMPLETE = "STOP_COMPLETE"          # 5条件すべて満たし、自律停止してよい
    CONTINUE_BLOCKED = "CONTINUE_BLOCKED"    # 未達点がある。継続 or 人間へ報告


@dataclass
class AcceptanceCheck:
    required_acceptance_criteria_satisfied: bool
    required_verification_completed: bool
    deliverables_present: bool
    persistence_confirmed_or_na: bool  # N/Aな性質のタスクなら True 扱いにして呼び出し側で理由を残す
    unresolved_blockers: list[str] = field(default_factory=list)

    def evaluate(self) -> AcceptanceStatus:
        all_ok = (
            self.required_acceptance_criteria_satisfied
            and self.required_verification_completed
            and self.deliverables_present
            and self.persistence_confirmed_or_na
            and not self.unresolved_blockers
        )
        return AcceptanceStatus.STOP_COMPLETE if all_ok else AcceptanceStatus.CONTINUE_BLOCKED

    def unmet_points(self) -> list[str]:
        unmet = []
        if not self.required_acceptance_criteria_satisfied:
            unmet.append("required_acceptance_criteria not satisfied")
        if not self.required_verification_completed:
            unmet.append("required_verification not completed")
        if not self.deliverables_present:
            unmet.append("deliverables not present")
        if not self.persistence_confirmed_or_na:
            unmet.append("persistence not confirmed (and not marked N/A)")
        for b in self.unresolved_blockers:
            unmet.append(f"unresolved blocker: {b}")
        return unmet


def render_result(
    check: AcceptanceCheck,
    completed_items: list[str],
    untouched_items: list[str],
    verification_summary: str,
) -> str:
    """result_presenter.md 相当の自然語サマリーの元になる構造化出力。
    UX層（japanese-human-layer/prompts/result_presenter.md）がこれを自然語へ翻訳する。
    Core自体は自然語生成をしない。"""
    status = check.evaluate()
    lines = [f"status: {status.value}"]
    lines.append("completed:")
    lines.extend(f"  - {item}" for item in completed_items)
    lines.append("untouched (unchanged):")
    lines.extend(f"  - {item}" for item in untouched_items)
    lines.append(f"verification_summary: {verification_summary}")
    if status == AcceptanceStatus.CONTINUE_BLOCKED:
        lines.append("unmet_points:")
        lines.extend(f"  - {p}" for p in check.unmet_points())
    return "\n".join(lines)
