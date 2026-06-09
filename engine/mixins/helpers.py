from __future__ import annotations

from ..models import CardDefinition, Permanent, PlayerState
from ._constants import _MANA_SYMBOLS, _NO_PRIORITY_STEPS

class GameHelpersMixin:
    def _find_controlled_permanent(
        self,
        controller: PlayerState,
        permanent_name: str,
        permanent_index: int | None = None,
    ) -> tuple[int, Permanent] | None:
        if permanent_index is not None:
            if permanent_index < 0 or permanent_index >= len(controller.battlefield):
                return None
            permanent = controller.battlefield[permanent_index]
            if permanent.card.name != permanent_name:
                return None
            return permanent_index, permanent

        for idx, permanent in enumerate(controller.battlefield):
            if permanent.card.name == permanent_name:
                return idx, permanent
        return None

    def _is_summoning_sick(self, permanent: Permanent) -> bool:
        if permanent.card.primary_type != "creature":
            return False
        if self._has_keyword(permanent, "Haste"):
            return False
        return permanent.metadata.get("summoning_sickness_turn") == self.turn

    def _public_phase_name(self, phase: str, step: str) -> str:
        if phase in {"precombat_main", "postcombat_main"}:
            return "main"
        if phase == "combat":
            return "combat"
        if phase == "ending" and step in {"end", "cleanup"}:
            return step
        if phase == "beginning" and step in {"untap", "upkeep", "draw"}:
            return step
        return step

    def _receives_priority(self, step: str) -> bool:
        return step not in _NO_PRIORITY_STEPS

    def _make_expiry_tag(self, edge: str, phase: str, step: str) -> str:
        return f"{edge}:{phase}:{step}"

    def _expire_tagged_effects(self, tag: str) -> None:
        for player in self.players:
            for permanent in player.battlefield:
                expires = permanent.metadata.get("expires_at")
                if expires != tag:
                    continue
                key = permanent.metadata.get("expires_key")
                if isinstance(key, str):
                    permanent.metadata.pop(key, None)
                permanent.metadata.pop("expires_at", None)
                permanent.metadata.pop("expires_key", None)

    def _on_step_or_phase_begin(self, phase: str, step: str) -> None:
        # 500.4
        self._expire_tagged_effects(self._make_expiry_tag("begin_step", phase, step))
        self._expire_tagged_effects(self._make_expiry_tag("begin_phase", phase, step))

    def _on_step_or_phase_end(self, phase: str, step: str) -> None:
        # 500.5 and 500.5a
        self._expire_tagged_effects(self._make_expiry_tag("end_step", phase, step))
        self._expire_tagged_effects(self._make_expiry_tag("end_phase", phase, step))
        if phase == "combat" and step == "end_of_combat":
            self._expire_tagged_effects("end_of_combat")
        self.clear_mana_pools()

    def _normalize_mana_color(self, mana_color: str | None) -> str | None:
        if mana_color is None:
            return None
        color = mana_color.strip().upper()
        if color not in {"W", "U", "B", "R", "G"}:
            raise ValueError(f"Invalid mana color: {mana_color}")
        return color

    def clear_mana_pools(self) -> None:
        for player in self.players:
            for symbol in _MANA_SYMBOLS:
                player.mana_pool[symbol] = 0

    def _permanent_to_graveyard(self, player: PlayerState, permanent: Permanent) -> None:
        """Move a permanent to the graveyard. Tokens (704.5d) cease to exist instead."""
        if not permanent.metadata.get("is_token", False):
            player.graveyard.append(permanent.card)

    def _put_permanent_onto_battlefield(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
    ) -> None:
        self.players[controller_index].battlefield.append(permanent)
        self._initialize_permanent_state(permanent, controller_index, target_player_index)
        # 611.3a/611.3c: static abilities apply as permanents enter. Recalculate
        # lord buffs so the new permanent immediately receives applicable bonuses,
        # and so any new lord immediately buffs existing matching permanents.
        self._recalculate_lord_buffs()
