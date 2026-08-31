from __future__ import annotations

"""End of combat step (CR 511).

Fires "at end of combat" triggered abilities (Clockwork Beast counter removal,
Cockatrice/Thicket Basilisk delayed destruction) while "attacked or blocked this
combat" is still known, then clears until-end-of-combat effects and combat state.
"""

from ..attack_tapping import clear_attack_tap_exemptions
from ..delayed_triggers import (expire_combat_delayed_triggers,
                                fire_delayed_triggers)
from ..keywords import clear_granted_ability_lines, clear_granted_keywords
from ..models import Permanent
from ..pt import remove_temporary_pt
from ..oracle import compile_card_oracle
from ..damage_redirects import clear_redirects
from ..prevention import clear_directional_shields
from ..shields import END_OF_COMBAT, clear_shields
from ..trigger_utils import iter_triggered_abilities, make_trigger_event


class EndOfCombatStepMixin:
    def end_combat(self, step_already_started: bool = False) -> None:
        phase = "combat"
        step = "end_of_combat"
        if not step_already_started:
            self._set_phase_and_step(phase, step)
            self._on_step_or_phase_begin(phase, step)
        # End-of-combat triggered abilities fire before combat state is cleared,
        # while "attacked or blocked this combat" is still known.
        self._fire_end_of_combat_triggers()
        # "At this turn's next end of combat, …" (Glyph of Doom) — a delayed
        # ability (CR 603.7), which belongs to no permanent and so is invisible
        # to the battlefield scan above.
        fire_delayed_triggers(self, "next_end_of_combat")
        for permanent in self.all_permanents():
            # "…gets +10/+0 until end of combat." (Glyph of Destruction.) The
            # layer-7c twin of the cleanup step's end-of-turn sweep, reading the
            # same channel table so a duration is implemented by having a sweep
            # rather than by having a word.
            remove_temporary_pt(permanent, "end_of_combat")
            # Layer 6's twin of the same sweep: "…gain "Johan can't attack"
            # **until end of combat**" (Johan). Beside the P/T channel rather
            # than in a step of its own, because both are the same duration
            # ending and a second sweep site is a second place to forget one.
            clear_granted_ability_lines(permanent, "end_of_combat")
            clear_granted_keywords(permanent, "end_of_combat")
            if permanent.metadata.get("animate_until_end_of_combat"):
                permanent.metadata.pop("animate_until_end_of_combat", None)
                permanent.metadata.pop("absolute_power", None)
                permanent.metadata.pop("absolute_toughness", None)
            # "…prevent all combat damage that would be dealt to and dealt by
            # that creature **this combat**." (Winter's Chill.) The directional
            # marker's window is data on the record, so this sweep asks for the
            # window rather than knowing which card printed it — the same shape
            # `clear_shields` below has for the collection form.
            clear_directional_shields(permanent, END_OF_COMBAT)
            permanent.metadata.pop("blocked_this_combat", None)
        # "…this combat" (Johan). The exemptions are scoped to the combat
        # phase, so they end where every other until-end-of-combat effect above
        # does rather than waiting for cleanup.
        clear_attack_tap_exemptions(self)
        # "Whenever a creature attacks and isn't blocked **this combat**, …"
        # (Melee). CR 603.7b's stated duration, ending in the same sweep as
        # every other until-end-of-combat effect above rather than waiting for
        # cleanup — a turn may hold a second combat phase, and an entry left
        # waiting would fire on a declaration the card never saw.
        expire_combat_delayed_triggers(self)
        self.combat_damage_prevented_until_eot = False
        self.combat_damage_prevented_for = []
        for player in self.players:
            # CR 615.3: a shield whose duration is this combat expires here.
            # Which shields those are is data on the shield, so this sweep does
            # not have to know that Forcefield's is the only one.
            clear_shields(player, END_OF_COMBAT)
            clear_redirects(player, END_OF_COMBAT)
            for permanent in self.controlled_by(player):
                clear_shields(permanent, END_OF_COMBAT)
                clear_redirects(permanent, END_OF_COMBAT)
        self._reset_combat_state(clear_damage_marked=False)
        if self._receives_priority(step):
            self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)

    def _fire_end_of_combat_triggers(self) -> None:
        """Fire "at end of combat" triggered abilities (CR 511.1, 603.2).

        Two dispatches. Compiled ``end_of_combat`` triggers (The Wretched) go
        onto the stack through the standard batch, with what the trigger's
        effect needs captured now — the blockers of the firing attacker, by
        id — because ``end_combat`` clears the combat record before the
        priority window that resolves them. Clockwork Beast's line compiles
        as a static line instead (its intervening-if has no production), so
        it keeps the direct text probe below.
        """
        events = []
        for controller_index, permanent, trig in iter_triggered_abilities(
            self, condition_kinds={"end_of_combat"}
        ):
            # "…creatures blocking or blocked by this creature" (Kjeldoran
            # Frostbeast's destruction, Dread Wight's counters). CR 509's
            # relation, captured **for every end-of-combat trigger whether or
            # not it asks** — the same discipline the dies transition takes with
            # ``dead_power``, and for a sharper reason here: this batch goes on
            # the stack now and resolves in the priority window at the *end* of
            # ``end_combat``, by which time ``_reset_combat_state`` has emptied
            # the maps the relation reads. It used to be captured for one named
            # instruction kind, which cannot see a kind nested inside a
            # ``sequence`` — Dread Wight's counters, tap, untap restriction and
            # grant are four steps under one — and a fire site that enumerates
            # kinds is complete only up to the last card that touched it.
            #
            # Permanent objects, which is CR 603.10's last-known information and
            # what the handlers already expect.
            trigger_context = {
                "combat_opponents": self.creatures_in_combat_with(permanent),
            }
            if trig.instruction is not None and trig.instruction.kind == "steal_blockers_of_source":
                # "all creatures blocking this creature" — CR 611.2c fixes the
                # set when the effect begins, and this is the last moment the
                # combat record can answer it.
                blocker_ids = []
                attacker_idx = self.battlefield_index_of(permanent)
                if (
                    attacker_idx is not None
                    and controller_index == self.active_player_index
                    and attacker_idx in self.combat_attackers
                ):
                    defending_idx = self.combat_attackers.get(attacker_idx)
                    for blocker_idx in self._combat_blockers_for_attacker(attacker_idx):
                        blocker = self.permanent_at(defending_idx, blocker_idx)
                        if blocker is not None:
                            blocker_ids.append(blocker.permanent_id)
                trigger_context["blocker_ids"] = tuple(blocker_ids)
            events.append(
                make_trigger_event(
                    controller_index, permanent, trig,
                    trigger_context=trigger_context,
                )
            )
        self._enqueue_triggered_batch(events)

        clockwork_line = (
            "at end of combat, if this creature attacked or blocked this combat, "
            "remove a +1/+0 counter from it"
        )
        for permanent in self.all_permanents():
            program = compile_card_oracle(permanent.effective_card)
            if not any(clockwork_line == line for line in program.static_lines):
                continue
            attacked_or_blocked = permanent.metadata.get(
                "attacked_this_turn"
            ) or permanent.metadata.get("blocked_this_combat")
            if not attacked_or_blocked:
                continue
            counters = int(permanent.metadata.get("plus_1_0_counters", 0))
            if counters <= 0:
                continue
            permanent.metadata["plus_1_0_counters"] = counters - 1
            permanent.power_bonus -= 1
            self.log.append(
                f"{permanent.card.name} removes a +1/+0 counter at end of combat "
                f"({counters - 1} remaining)"
            )

        self._resolve_end_of_combat_destruction()

    def _resolve_end_of_combat_destruction(self) -> None:
        """Destroy creatures marked by a "destroy at end of combat" trigger.

        Used by Cockatrice / Thicket Basilisk, whose joined block condition is
        fired by the two dispatchers in declare_blockers_step.py. Honors
        regeneration shields like any other destruction.
        """
        def _on_regenerate(permanent: Permanent) -> None:
            permanent.damage_marked = 0
            self.log.append(f"{permanent.card.name} regenerated")

        any_died = False
        for player in self.players:
            def _on_destroy(permanent: Permanent, player=player) -> None:
                self._trigger_aura_death_effects(permanent, player)
                # "…**if that creature was destroyed this way**" (Infinite
                # Authority) is asked at the next end step, by which time the
                # creature is a card in a graveyard. Recorded here, where the
                # destruction actually happens, rather than inferred later from
                # absence — a creature that regenerated or left in between is
                # not one this sweep destroyed.
                self.destroyed_at_end_of_combat_this_turn.append(
                    permanent.permanent_id
                )
                self.log.append(f"{permanent.card.name} was destroyed at end of combat")

            destroyed = self._destroy_swept_permanents(
                player,
                lambda p: p.metadata.pop("destroy_at_end_of_combat", False),
                respect_indestructible=False,
                on_regenerate=_on_regenerate,
                on_destroy=_on_destroy,
            )
            any_died = any_died or bool(destroyed)
        if any_died:
            self._recalculate_lord_buffs()
