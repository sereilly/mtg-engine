from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GameSnapshot:
    game: Any
    current_turn: int
    status: str
    cleanup_required_discards: int
    cleanup_selected_indices: list[int]
    untap_required_lands: int
    untap_candidate_indices: list[int]
    untap_selected_indices: list[int]
    upkeep_pay_choices: list[dict]
    upkeep_resolved_choices: dict[str, bool]


class GameHistory:
    def __init__(self) -> None:
        self._snapshots: list[GameSnapshot] = []

    def save(self, session: Any) -> None:
        self._snapshots.append(
            GameSnapshot(
                game=copy.deepcopy(session.game),
                current_turn=session.current_turn,
                status=session.status,
                cleanup_required_discards=session.cleanup_required_discards,
                cleanup_selected_indices=list(session.cleanup_selected_indices),
                untap_required_lands=session.untap_required_lands,
                untap_candidate_indices=list(session.untap_candidate_indices),
                untap_selected_indices=list(session.untap_selected_indices),
                upkeep_pay_choices=list(session.upkeep_pay_choices),
                upkeep_resolved_choices=dict(session.upkeep_resolved_choices),
            )
        )

    def can_undo(self) -> bool:
        return bool(self._snapshots)

    def undo(self) -> GameSnapshot | None:
        if not self._snapshots:
            return None
        return self._snapshots.pop()

    def __len__(self) -> int:
        return len(self._snapshots)
