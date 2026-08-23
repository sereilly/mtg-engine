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
    optional_trigger_choices: list[dict] = field(default_factory=list)
    optional_trigger_resolved: dict[str, bool] = field(default_factory=dict)
    upkeep_mana_prevention_choices: list[dict] = field(default_factory=list)
    upkeep_mana_prevention_resolved: dict[str, int] = field(default_factory=dict)
    upkeep_decisions_deferred: bool = False
    island_sanctuary_pending: bool = False
    paused_beginning_phase: tuple[str, int] | None = None


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
                optional_trigger_choices=list(session.optional_trigger_choices),
                optional_trigger_resolved=dict(session.optional_trigger_resolved),
                upkeep_mana_prevention_choices=list(session.upkeep_mana_prevention_choices),
                upkeep_mana_prevention_resolved=dict(session.upkeep_mana_prevention_resolved),
                upkeep_decisions_deferred=session.upkeep_decisions_deferred,
                island_sanctuary_pending=session.island_sanctuary_pending,
                paused_beginning_phase=session.paused_beginning_phase,
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
