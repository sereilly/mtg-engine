from __future__ import annotations

import re

from ..card_hooks import ON_LEAVE_BATTLEFIELD
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle
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

    @staticmethod
    def _stack_item_colors(item) -> tuple[str, ...]:
        """Effective color symbols of a spell on the stack, honoring a color
        change applied by a Lace card (StackItem.new_color)."""
        if getattr(item, "new_color", None):
            return (item.new_color,)
        return tuple(item.card.colors or ())

    def _is_creature(self, permanent: Permanent) -> bool:
        """A permanent is a creature if its printed type says so or an effect has
        turned it into one (e.g. Kormus Bell / Living Lands animated lands)."""
        return permanent.card.primary_type == "creature" or bool(
            permanent.metadata.get("land_animated")
        )

    def _is_summoning_sick(self, permanent: Permanent) -> bool:
        if not self._is_creature(permanent):
            return False
        if self._has_keyword(permanent, "Haste"):
            return False
        return permanent.metadata.get("summoning_sickness_turn") == self.turn

    def _advance_summoning_sickness(self, active_player_index: int) -> None:
        """Carry summoning sickness across other players' turns (CR 302.6).

        ``self.turn`` advances on *every* player's turn, but a creature only sheds
        summoning sickness once *its controller's* most recent turn begins. A sick
        creature is marked with ``summoning_sickness_turn == self.turn``; left
        untouched, the marker would no longer match once an opponent's turn bumps
        the counter, clearing sickness a full turn early.

        Called at the start of each turn (untap step), this re-stamps the marker on
        every *non-active* player's still-sick creatures so it keeps tracking the
        current turn. The active player's own creatures are deliberately left stale
        so their marker falls behind ``self.turn`` — that is how they shed sickness
        as their turn begins.
        """
        for index, player in enumerate(self.players):
            if index == active_player_index:
                continue
            for permanent in player.battlefield:
                if (
                    self._is_creature(permanent)
                    and permanent.metadata.get("summoning_sickness_turn") == self.turn - 1
                ):
                    permanent.metadata["summoning_sickness_turn"] = self.turn

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

    def _recompute_continuous_effects(self) -> None:
        """Recalculate all static/continuous P/T effects (611.3). Call after any
        permanent leaves the battlefield so lord buffs (Crusade, Gauntlet of Might,
        Lord of Atlantis, Castle) and dynamic P/T (Nightmare) reflect the new board."""
        self._recalculate_lord_buffs()
        self._refresh_dynamic_creatures()

    def _remove_aura_effects(self, aura: Permanent) -> None:
        """Undo the continuous effects an Aura granted to the permanent it was
        attached to (CR 611.3 — the effect ends when the Aura leaves). The grants
        were recorded on the Aura by _apply_aura_effect."""
        attached = aura.metadata.get("attached_to")
        if attached is None:
            return
        power_delta = int(aura.metadata.get("aura_granted_power", 0) or 0)
        toughness_delta = int(aura.metadata.get("aura_granted_toughness", 0) or 0)
        if power_delta:
            attached.power_bonus -= power_delta
        if toughness_delta:
            attached.toughness_bonus -= toughness_delta
        for key in aura.metadata.get("aura_granted_meta", []) or []:
            attached.metadata.pop(key, None)
        # Animate Artifact (and similar) replaced the permanent's card with an
        # animated artifact-creature version. Restore the original card so it stops
        # being a creature and the UI drops its power/toughness labels (CR 611.3).
        pre_animate_card = attached.metadata.pop("pre_animate_card", None)
        if pre_animate_card is not None:
            attached.card = pre_animate_card
        if attached.metadata.get("attached_aura") is aura:
            attached.metadata.pop("attached_aura", None)

    def _permanent_to_graveyard(self, player: PlayerState, permanent: Permanent) -> None:
        """Move a permanent to the graveyard. Tokens (704.5d) cease to exist instead."""
        if "Aura" in permanent.card.type_line:
            self._remove_aura_effects(permanent)
        # Disintegrate-style replacement: "if it would die this turn, exile it
        # instead." The creature never reaches the graveyard, so no dies-triggers
        # fire (CR 614 — the replacement applies as it would leave the battlefield).
        if permanent.metadata.get("exile_if_dies_this_turn"):
            if not permanent.metadata.get("is_token", False):
                player.exile.append(permanent.card)
            self.log.append(f"{permanent.card.name} was exiled instead of dying")
            return
        if not permanent.metadata.get("is_token", False):
            player.graveyard.append(permanent.card)
        if permanent.card.primary_type == "creature":
            self.creatures_died_this_turn = getattr(self, "creatures_died_this_turn", 0) + 1
            program = compile_card_oracle(permanent.card)
            for trig in program.triggered_abilities:
                if (
                    trig.condition.kind == "dies"
                    and trig.instruction is not None
                    and trig.instruction.kind == "owner_loses_half_life"
                ):
                    loss = max(0, (player.life + 1) // 2)
                    player.life -= loss
                    self.log.append(
                        f"{permanent.card.name} died: {player.name} loses {loss} life (half, rounded up)"
                    )
                    break
        text = permanent.card.oracle_text.lower()
        if (
            "when this enchantment is put into a graveyard from the battlefield, you lose the game"
            in text
            and not player.lost
        ):
            player.lost = True
            self.log.append(
                f"{player.name} lost the game ({permanent.card.name} was put into a graveyard from the battlefield)"
            )

        if permanent.card.primary_type == "creature":
            self._fire_creature_dies_triggers(permanent)

        leave_hook = ON_LEAVE_BATTLEFIELD.get(permanent.card.name)
        if leave_hook is not None:
            leave_hook(self, player, permanent)

    def _fire_creature_dies_triggers(self, dead_permanent: Permanent) -> None:
        """Fire "whenever a creature dies" triggers (e.g. Soul Net).

        Observers may be controlled by any player. For "you may pay {N}" optional
        triggers the controller pays automatically when able (deterministic), then
        applies the rider effect (Rule 603.2, 603.3).
        """
        for controller in self.players:
            for observer in list(controller.battlefield):
                if observer is dead_permanent:
                    continue
                program = compile_card_oracle(observer.card)
                for trig in program.triggered_abilities:
                    # Sengir Vampire: "Whenever a creature dealt damage by this
                    # creature this turn dies, put a +1/+1 counter on this creature."
                    if (
                        trig.condition.kind == "creature_dealt_damage_by_self_dies"
                        and trig.instruction is not None
                        and trig.instruction.kind == "add_counter_to_self"
                    ):
                        damagers = dead_permanent.metadata.get("damaged_by_sources_this_turn", [])
                        if observer in damagers:
                            observer.power_bonus += int(trig.instruction.payload.get("power", 1))
                            observer.toughness_bonus += int(trig.instruction.payload.get("toughness", 1))
                            self.log.append(
                                f"{observer.card.name} gets a +1/+1 counter ({dead_permanent.card.name} it damaged died)"
                            )
                        continue
                    if trig.condition.kind != "creature_dies" or trig.instruction is None:
                        continue
                    instr = trig.instruction
                    obs_text = observer.card.oracle_text.lower()
                    pay_match = re.search(r"you may pay \{(\d+)\}", obs_text)
                    if pay_match:
                        needed = int(pay_match.group(1))
                        available = sum(controller.mana_pool.get(s, 0) for s in controller.mana_pool)
                        if available < needed:
                            continue  # chose not to / unable to pay
                        remaining = needed
                        for sym in list(controller.mana_pool):
                            while remaining > 0 and controller.mana_pool.get(sym, 0) > 0:
                                controller.mana_pool[sym] -= 1
                                remaining -= 1
                    if instr.kind == "target_gains_life":
                        amount = int(instr.payload.get("amount", 1))
                        self._gain_life(controller, amount, observer.card.name)
                        self.log.append(
                            f"{observer.card.name} trigger: {controller.name} gained {amount} life ({dead_permanent.card.name} died)"
                        )
                    break

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
        self._recompute_continuous_effects()
