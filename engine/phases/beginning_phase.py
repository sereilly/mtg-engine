from __future__ import annotations

"""Beginning phase (CR 501).

The beginning phase contains, in order, the untap step, the upkeep step and the
draw step — each implemented in its own module (``untap_step``, ``upkeep_step``,
``draw_step``). This module holds the phase-level concerns that aren't tied to a
single step: the begin-of-turn "skip your turn to untap" decision (Time Vault)
and closing a deferred upkeep/draw priority window.
"""


class BeginningPhaseMixin:
    def get_begin_turn_untap_options(self, player_index: int) -> list[str]:
        """Names of tapped permanents the player may untap by skipping this turn.

        Covers Time Vault: "If you would begin your turn while this artifact is
        tapped, you may skip that turn instead. If you do, untap this artifact."
        The UI surfaces this as a beginning-of-turn prompt.
        """
        player = self.players[player_index]
        options: list[str] = []
        for permanent in player.battlefield:
            text = permanent.card.oracle_text.lower()
            if (
                permanent.tapped
                and "skip that turn instead" in text
                and "untap this artifact" in text
            ):
                options.append(permanent.card.name)
        return options

    def skip_turn_to_untap(self, player_index: int, permanent_name: str) -> bool:
        """Skip the player's turn to untap a tapped Time Vault-style permanent.

        Returns True if the skip/untap was performed. The player must control a
        tapped permanent of that name whose text grants the skip-to-untap option.
        """
        if permanent_name not in self.get_begin_turn_untap_options(player_index):
            return False
        player = self.players[player_index]
        permanent = next(
            (p for p in player.battlefield if p.card.name == permanent_name and p.tapped),
            None,
        )
        if permanent is None:
            return False
        permanent.tapped = False
        self.skip_next_turn(player_index)
        self.log.append(
            f"{player.name} skipped their turn to untap {permanent_name}"
        )
        return True

    def close_beginning_step(self) -> None:
        """Close a deferred upkeep/draw step (counterpart to close_end_step)."""
        phase = self.current_turn_phase
        step = self.current_step
        if phase != "beginning" or step not in ("upkeep", "draw"):
            return
        if self._receives_priority(step):
            self.clear_priority_window()
        self._on_step_or_phase_end(phase, step)
