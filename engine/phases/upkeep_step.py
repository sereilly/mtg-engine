from __future__ import annotations

"""Upkeep step (CR 503).

"At the beginning of upkeep" triggered abilities are put on the stack here, plus
the pay-or-consequence upkeep triggers that may require an interactive choice,
enchant-land upkeep effects, and graveyard-recursion upkeep triggers.

The pay-or-consequence effects themselves live in upkeep_effects.py, registered
by (trigger condition, instruction kind); this module scans the battlefield and
dispatches. A new upkeep card is an entry there, never a branch here.
"""

import re

from ..auras import aura_enchants
from ..copies import RECOPY_EACH_UPKEEP, grants_ability
from ..land_types import MIRE_COUNTER, end_land_type_change
from ..layer_bridge import GAINED_TYPES
from ..models import Permanent
from ..oracle import OracleInstruction, compile_card_oracle
from ..trigger_utils import iter_triggered_abilities, matching_triggers
from ..mixins._constants import _UPKEEP_PAY_KINDS
from ..effect_labels import triggered_label
from ..handlers import EFFECT_HANDLERS
from .upkeep_effects import UPKEEP_EFFECTS, UpkeepContext, UpkeepEffectsMixin

#: Upkeep conditions whose seat this loop can name without asking anything else:
#: "at the beginning of **your** upkeep" is the source's controller, and "at the
#: beginning of **each player's** upkeep" is the player whose upkeep it is. The
#: other two (`upkeep_enchanted_controller`, `upkeep_chosen`) read a seat off
#: something else, so they stay with the registry that already knows how.
_ORDINARY_UPKEEP_SEATS = frozenset({"upkeep_self", "upkeep_each"})


class UpkeepStepMixin(UpkeepEffectsMixin):
    def can_pay_upkeep_mana(self, player, mana: dict[str, int]) -> bool:
        """Whether *player* can cover an upkeep cost: colored pips from floating
        mana, the generic part from what's left plus untapped mana-producing
        lands (the player gets the chance to tap during upkeep)."""
        colored = {sym: n for sym, n in mana.items() if sym != "generic" and n > 0}
        if any(player.mana_pool.get(sym, 0) < n for sym, n in colored.items()):
            return False
        generic = int(mana.get("generic", 0) or 0)
        if generic <= 0:
            return True
        floating_left = sum(player.mana_pool.values()) - sum(colored.values())
        untapped_land_mana = sum(
            1
            for perm in self.controlled_by(player)
            if perm.card.primary_type == "land" and not perm.tapped and perm.effective_produced_mana
        )
        return floating_left + untapped_land_mana >= generic

    def _spend_upkeep_mana(self, player, mana: dict[str, int]) -> None:
        """Spend an upkeep cost validated by ``can_pay_upkeep_mana``: colored
        pips from the pool, then the generic part from floating mana and by
        tapping untapped mana-producing lands."""
        for sym, count in mana.items():
            if sym != "generic" and count > 0:
                player.mana_pool[sym] = player.mana_pool.get(sym, 0) - count
        remaining = int(mana.get("generic", 0) or 0)
        for sym in list(player.mana_pool):
            while remaining > 0 and player.mana_pool.get(sym, 0) > 0:
                player.mana_pool[sym] -= 1
                remaining -= 1
        if remaining > 0:
            for perm in self.controlled_by(player):
                if remaining <= 0:
                    break
                if perm.card.primary_type == "land" and not perm.tapped and perm.effective_produced_mana:
                    self.become_tapped(perm)
                    remaining -= 1

    def get_upkeep_pay_triggers(self, player_index: int) -> list[dict]:
        """Return pay-or-consequence upkeep triggers that the player must decide on.

        Only returns triggers where the permanent's controller is ``player_index``
        and the condition is ``upkeep_self`` (i.e. fires on *their* upkeep).
        """
        controller = self.players[player_index]
        choices: list[dict] = []
        for _idx, permanent, trig in iter_triggered_abilities(
            self,
            condition_kinds={"upkeep_self"},
            instruction_kinds=_UPKEEP_PAY_KINDS,
            players=[controller],
        ):
            mana = trig.instruction.payload.get("mana", {})
            # Cyclone: the cost escalates with its wind counters — the counter
            # for THIS upkeep is added when the trigger resolves, so the prompt
            # quotes counters + 1 green.
            if trig.instruction.kind == "upkeep_wind_counter_pay_or_sacrifice":
                mana = {"G": int(permanent.metadata.get("wind_counters", 0)) + 1}
            choices.append({
                "card_name": permanent.card.name,
                "mana": mana,
                "kind": trig.instruction.kind,
                # "unless you pay" alternative consequence, used to label the
                # decline button (e.g. Force of Nature deals 8 damage; it is
                # not a sacrifice).
                "damage": int(trig.instruction.payload.get("damage", 0)),
            })

        # Paralyze-style auras: "At the beginning of the upkeep of enchanted
        # creature's controller, that player may pay {N}. If they do, untap the
        # creature." The aura may be controlled by either player, so scan every
        # battlefield for one whose enchanted creature this player controls.
        for permanent in self.all_permanents():
            attached = permanent.metadata.get("attached_to")
            if attached is None or not self.controls(controller, attached):
                continue
            trig = next(matching_triggers(
                permanent.effective_card,
                condition_kinds={"upkeep_enchanted_controller"},
                instruction_kinds={"upkeep_pay_to_untap_enchanted"},
            ), None)
            if trig is not None:
                choices.append({
                    "card_name": permanent.card.name,
                    "mana": trig.instruction.payload.get("mana", {}),
                    "kind": trig.instruction.kind,
                    "damage": 0,
                })

        # Farmstead-style enchant-land grants: "Enchanted land has 'At the beginning
        # of your upkeep, you may pay {N}. If you do, you gain X life.'" The enchanted
        # land's controller (player_index) may pay for the life.
        for permanent in self.all_permanents():
            if permanent.card.primary_type != "enchantment":
                continue
            attached = permanent.metadata.get("attached_to")
            if attached is None or not self.controls(controller, attached):
                continue
            text = compile_card_oracle(permanent.effective_card).normalized_text
            if (
                not aura_enchants(permanent.effective_card.oracle_text, "land")
                or "you may pay" not in text or "you gain" not in text
            ):
                continue
            pay_match = re.search(r"you may pay ((?:\{[wubrgc]\})+)", text)
            mana: dict[str, int] = {}
            if pay_match:
                for sym in re.findall(r"\{([wubrg])\}", pay_match.group(1)):
                    mana[sym.upper()] = mana.get(sym.upper(), 0) + 1
            choices.append({
                "card_name": permanent.card.name,
                "mana": mana,
                "kind": "upkeep_pay_to_gain_life",
                "damage": 0,
            })
        return choices

    def get_upkeep_mana_prevention_triggers(self, player_index: int) -> list[dict]:
        """Return upkeep triggers where this player may pay any amount of mana to
        prevent that much damage (Power Leak). The UI prompts for an amount; the
        chosen value is passed back via ``resolve_upkeep(mana_prevention=...)``.
        """
        victim = self.players[player_index]
        triggers: list[dict] = []
        for permanent in self.all_permanents():
            if "prevent x of that damage" not in permanent.effective_card.oracle_text.lower():
                continue
            attached = permanent.metadata.get("attached_to")
            if attached is None or not self.controls(victim, attached):
                continue
            trig = next(matching_triggers(
                permanent.effective_card,
                condition_kinds={"upkeep_enchanted_controller"},
                instruction_kinds={"deal_damage"},
            ), None)
            if trig is not None:
                triggers.append({
                    "card_name": permanent.card.name,
                    "kind": "upkeep_pay_to_prevent_damage",
                    "damage": int(trig.instruction.payload.get("amount", 1)),
                })
        return triggers

    def _process_mire_cleanups(self, player_index: int) -> None:
        """Drain Cyclopean Tomb's rest-of-game mire-removal obligations.

        For each obligation belonging to this player, remove all mire counters
        from one still-mired land at the beginning of their upkeep (the trigger
        acts on a single land per upkeep). A land whose counter has already gone —
        because the land left the battlefield or was freed by a prior upkeep — is
        no longer eligible. An obligation with no eligible lands left is dropped
        (it would do nothing on future upkeeps).
        """
        if not self.mire_cleanup_obligations:
            return

        def _on_battlefield(land) -> bool:
            return self.is_on_battlefield(land)

        surviving: list = []
        for obligation in self.mire_cleanup_obligations:
            if obligation.get("controller_index") != player_index:
                surviving.append(obligation)
                continue
            lands = [
                land
                for land in obligation.get("lands", [])
                if land.metadata.get("mire_counter") and _on_battlefield(land)
            ]
            if lands:
                freed = lands.pop(0)
                freed.metadata.pop("mire_counter", None)
                # The counter is what the type change hung on, so removing it
                # drops that one contribution — not every land-type effect on
                # the land, which is what clearing the stored type did.
                end_land_type_change(freed, source=MIRE_COUNTER)
                self.log.append(f"Mire counter removed from {freed.card.name}")
            if lands:
                obligation["lands"] = lands
                surviving.append(obligation)
        self.mire_cleanup_obligations = surviving

    def _graveyard_return_candidates(self, player_index: int) -> list:
        """``(graveyard index, card)`` for each card whose "return during your
        upkeep" condition is currently met for ``player_index`` (Nether Shadow
        with enough creature cards above it). Shared by the prompt query and the
        upkeep resolver so both agree on which cards are eligible.

        **The index is part of the answer, not scaffolding.** A graveyard holds
        ``CardDefinition`` objects and ``load_cards`` dedupes by ``oracle_id``, so
        two copies of one card in one graveyard are the *same object* — which
        means a caller handed only the card cannot say which copy was eligible.
        This used to return the card alone and the resolver removed it with
        ``[c for c in graveyard if c is not card]``, which removes **every** copy:
        with one Nether Shadow deep enough to return and a second one on top, five
        cards went in and four came out. That is the look-alike bug class
        ``tests/engine/test_control_reads.py`` bans on the battlefield, and it is
        worse here, because on the battlefield the copies are distinct objects.
        """
        owner = self.players[player_index]
        candidates = []
        for grave_index, card in enumerate(owner.graveyard):
            trig = next(matching_triggers(
                card,
                condition_kinds={"upkeep_self"},
                instruction_kinds={"upkeep_return_self_from_graveyard"},
            ), None)
            if trig is None:
                continue
            instr = trig.instruction
            creatures_above = sum(
                1
                for above in owner.graveyard[grave_index + 1:]
                if above.primary_type == "creature"
            )
            if creatures_above >= int(instr.payload.get("min_creatures_above", 3)):
                candidates.append((grave_index, card))
        return candidates

    def get_optional_upkeep_triggers(self, player_index: int) -> list[dict]:
        """Optional ("you may") upkeep triggers awaiting a yes/no decision on this
        player's own upkeep.

        Generic across trigger sources; currently covers graveyard-recursion
        abilities (Nether Shadow). Each entry carries a human-readable ``prompt``
        and the ``card_name`` used to key the player's decision.
        """
        triggers: list[dict] = []
        seen: set[str] = set()
        for _grave_index, card in self._graveyard_return_candidates(player_index):
            if card.name in seen:
                continue
            seen.add(card.name)
            triggers.append({
                "card_name": card.name,
                "kind": "upkeep_return_self_from_graveyard",
                "prompt": f"Return {card.name} to the battlefield from your graveyard?",
            })
        # Living Artifact used to be surfaced here, matched on a substring of
        # its own text and answered through `optional_choices`. Its trigger now
        # takes the ordinary route (CR 603.3) and asks through the general
        # `optional_pay` prompt, which the web layer renders from the registry —
        # so listing it here as well would offer the same decision twice, only
        # one of which anything acts on.
        # Vesuvan Doppelganger's granted ability: "At the beginning of your
        # upkeep, you may have this creature become a copy of target creature."
        # Carries a creature-target choice alongside the yes/no.
        for perm_index, perm in enumerate(self.players[player_index].battlefield):
            if not grants_ability(perm, RECOPY_EACH_UPKEEP):
                continue
            if perm.card.name in seen:
                continue
            valid_targets = [
                {"kind": "permanent", "seat": s, "index": i, "name": p.card.name}
                for s, player in enumerate(self.players)
                for i, p in enumerate(player.battlefield)
                if p is not perm and self._is_creature(p)
            ]
            if not valid_targets:
                continue
            seen.add(perm.card.name)
            triggers.append({
                "card_name": perm.card.name,
                "kind": "upkeep_recopy",
                "prompt": f"Have {perm.card.name} become a copy of a different creature?",
                "needs_target": "creature",
                "valid_targets": valid_targets,
                "permanent_index": perm_index,
            })
        return triggers

    def _forestwalk_grant_candidates(self, controller) -> list[Permanent]:
        """Legal targets for Erhnam Djinn's upkeep grant: "target non-Wall
        creature an opponent controls"."""
        controller_seat = self.seat_index(controller)
        return [
            perm
            for seat, perm in self.permanents_with_controller()
            if seat != controller_seat
            and perm.is_creature
            and "wall" not in perm.effective_card.type_line.lower()
        ]

    def _base_pt_copy_candidates(self, source: Permanent) -> list[Permanent]:
        """Legal targets for a "change …'s base power and toughness to the
        power and toughness of target creature other than ~" upkeep trigger
        (Halfdane): every creature on any battlefield except the source itself
        — the exclusion is by identity, because a look-alike is a different
        permanent (CR 400.7)."""
        return [
            perm
            for _seat, perm in self.permanents_with_controller()
            if perm.is_creature and perm is not source
        ]

    def _upkeep_land_sacrifice_candidates(self, controller) -> list[Permanent]:
        """Legal choices for Serendib Djinn's upkeep "sacrifice a land": every
        land its controller controls (you choose which of your own permanents a
        sacrifice takes, CR 701.21a)."""
        return [perm for perm in self.controlled_by(controller) if perm.card.primary_type == "land"]

    def _resolve_upkeep_trigger_target(
        self, card_name: str, trigger_targets: dict | None, candidates: list[Permanent]
    ) -> Permanent | None:
        """The target a human picked for a mandatory targeted upkeep trigger, or —
        for AI/headless play, or a stale pick whose permanent has since left the
        battlefield — the first legal candidate. Returns None with no candidates
        (CR 603.3d: a trigger with no legal target is removed from the stack)."""
        chosen = (trigger_targets or {}).get(card_name)
        if chosen is not None:
            seat, index = chosen
            if 0 <= seat < len(self.players) and 0 <= index < len(self.players[seat].battlefield):
                candidate = self.players[seat].battlefield[index]
                if any(candidate is perm for perm in candidates):
                    return candidate
        return candidates[0] if candidates else None

    def get_upkeep_target_triggers(self, player_index: int) -> list[dict]:
        """Mandatory upkeep triggers that need the controller to choose a target.

        Same payload shape as ``get_optional_upkeep_triggers`` (``card_name``,
        ``prompt``, ``valid_targets``) plus ``mandatory: True``, so the web layer
        and UI reuse one channel — the difference is only that the player picks a
        target rather than answering yes/no, and can't decline.
        """
        # instruction kind -> (choice kind, target-noun the UI highlights,
        # prompt builder, candidate lookup). A lookup takes the trigger's
        # controller and its source permanent — most read one or the other,
        # and handing both over is what let the base-P/T copy exclude its own
        # source without the table growing a second shape.
        targeted_kinds = {
            "grant_forestwalk_until_next_upkeep": (
                "upkeep_grant_forestwalk",
                "creature",
                lambda name: (
                    f"{name}: choose a non-Wall creature an opponent controls "
                    "to gain forestwalk until your next upkeep."
                ),
                lambda controller, source: self._forestwalk_grant_candidates(controller),
            ),
            "upkeep_sacrifice_land_conditional_damage": (
                "upkeep_sacrifice_land",
                "land",
                lambda name: f"{name}: choose a land to sacrifice.",
                lambda controller, source: self._upkeep_land_sacrifice_candidates(controller),
            ),
            "set_source_base_pt_from_target_until_next_upkeep": (
                "upkeep_copy_base_pt",
                "creature",
                lambda name: (
                    f"{name}: choose a creature whose power and toughness "
                    f"{name} copies until the end of your next upkeep."
                ),
                lambda controller, source: self._base_pt_copy_candidates(source),
            ),
        }
        triggers: list[dict] = []
        seen: set[str] = set()
        controller = self.players[player_index]
        for perm in self.controlled_by(player_index):
            program = compile_card_oracle(perm.effective_card)
            for trig in program.triggered_abilities:
                if trig.instruction is None or trig.condition.kind != "upkeep_self":
                    continue
                entry = targeted_kinds.get(trig.instruction.kind)
                if entry is None:
                    continue
                if perm.card.name in seen:
                    continue
                choice_kind, target_noun, build_prompt, find_candidates = entry
                candidates = find_candidates(controller, perm)
                if not candidates:
                    continue
                seen.add(perm.card.name)
                triggers.append({
                    "card_name": perm.card.name,
                    "kind": choice_kind,
                    "mandatory": True,
                    "prompt": build_prompt(perm.card.name),
                    "needs_target": target_noun,
                    "valid_targets": [
                        {"kind": "permanent", "seat": s, "index": i, "name": p.card.name}
                        for s, player in enumerate(self.players)
                        for i, p in enumerate(player.battlefield)
                        if any(p is c for c in candidates)
                    ],
                })
        return triggers

    def _force_sacrifice_first_land(self, controller, source, chosen: Permanent | None = None) -> Permanent | None:
        """Sacrifice a land on *controller*'s battlefield to *source*'s upkeep
        effect, logging it. Returns the sacrificed land so callers can branch on
        its type (Serendib Djinn's "if it was an Island" damage), or None if the
        player controls no land.

        ``chosen`` is the land its controller picked (CR 701.21a: you choose
        which of your own permanents a sacrifice takes). Without one — AI /
        headless play, or an effect where another player does the choosing — the
        first land is taken, the deterministic forced-sacrifice fallback."""
        for idx, land in enumerate(controller.battlefield):
            if land.card.primary_type != "land":
                continue
            if chosen is not None and land is not chosen:
                continue
            removed = self.sacrifice_permanent(land)
            if removed is None:
                continue
            self.log.append(f"{source.card.name} forced sacrifice of {removed.card.name}")
            return removed
        # A stale pick (the land left the battlefield since the prompt) still
        # has to sacrifice something — fall back to the first land.
        return self._force_sacrifice_first_land(controller, source) if chosen is not None else None

    def _destroy_least_power_creature(self, owner, victim, card_name: str, chosen: bool = False) -> None:
        """Drop of Honey's kill (CR 701.7, "it can't be regenerated")."""
        self.remove_from_battlefield(victim)
        self._permanent_to_graveyard(owner, victim)
        how = "least power, controller's choice" if chosen else "least power"
        self.log.append(
            f"{card_name} destroyed {victim.card.name} ({how}; it can't be regenerated)"
        )

    def _live_least_power_candidates(self, choice) -> list:
        """The tied creatures still on a battlefield — a candidate can die to
        something else while the prompt waits."""
        return [
            perm
            for perm in (choice.data.get("_candidate_perms") or [])
            if self.is_on_battlefield(perm)
        ]

    def confirm_least_power_choice(
        self, player_index: int, target_seat: int, target_permanent_index: int
    ) -> bool:
        """Resolve a pending Drop of Honey tie-break: destroy the creature the
        controller chose among those tied for least power."""
        return self.resolve_pending_choice(
            "least_power_choice", player_index,
            target_seat=target_seat, target_permanent_index=target_permanent_index,
        )

    def _resolve_least_power_choice(
        self, choice, target_seat: int, target_permanent_index: int
    ) -> bool:
        """If every stored candidate has meanwhile left the battlefield, the
        prompt clears with nothing to destroy."""
        live = self._live_least_power_candidates(choice)
        if not live:
            self.discard_pending_choice(choice)
            self.log.append(f"{choice.data['card_name']}: no tied creature remains to destroy")
            return True
        if not (0 <= target_seat < len(self.players)):
            return False
        owner = self.players[target_seat]
        if not (0 <= target_permanent_index < len(owner.battlefield)):
            return False
        victim = owner.battlefield[target_permanent_index]
        if not any(victim is perm for perm in live):
            return False
        self.discard_pending_choice(choice)
        self._destroy_least_power_creature(owner, victim, choice.data["card_name"], chosen=True)
        self.check_state_based_actions()
        return True

    def _default_least_power_choice(self, choice) -> None:
        """Break the tie by battlefield scan order — the first tied creature."""
        self.discard_pending_choice(choice)
        live = self._live_least_power_candidates(choice)
        if not live:
            return
        victim = live[0]
        owner = self.players[self.controller_index_of(victim)]
        self._destroy_least_power_creature(owner, victim, choice.data["card_name"])

    def resolve_upkeep(self, player_index: int, human_choices: dict[str, bool] | None = None, optional_choices: dict[str, bool] | None = None, defer_priority: bool = False, mana_prevention: dict[str, int] | None = None, sacrifice_choices: dict[str, int] | None = None, trigger_targets: dict[str, tuple[int, int]] | None = None) -> None:
        phase = "beginning"
        step = "upkeep"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        self._process_mire_cleanups(player_index)
        # Erhnam Djinn: a granted forestwalk (or similar) lasting "until your
        # next upkeep" expires now, at the start of that same upkeep, before
        # this turn's own upkeep triggers (which might grant a fresh one) run.
        for perm in self.all_permanents():
            if perm.metadata.get("forestwalk_until_next_upkeep_of") == player_index:
                perm.metadata.pop("has_forestwalk", None)
                perm.metadata.pop("forestwalk_until_next_upkeep_of", None)
            # "Until **your** next upkeep, target noncreature artifact becomes
            # an artifact creature…" (Xenic Poltergeist) — the same moment and
            # the same reasoning as the forestwalk above: it expires at the
            # start of that upkeep, before this turn's own triggers get a
            # chance to grant a fresh one. Whose upkeep is the seat recorded
            # when the ability resolved, because CR 109.5 makes it the
            # controller of the ability rather than of the affected permanent.
            gained = perm.metadata.get(GAINED_TYPES)
            if gained:
                kept = [
                    g for g in gained
                    if not (
                        g.get("duration") == "until_your_next_upkeep"
                        and g.get("seat") == player_index
                    )
                ]
                if kept:
                    perm.metadata[GAINED_TYPES] = kept
                else:
                    perm.metadata.pop(GAINED_TYPES, None)
        # Non-interactive "at the beginning of upkeep" triggers (fixed upkeep damage)
        # are collected here and put on the stack (CR 603.3); they resolve through the
        # upkeep priority window. The pay-or-consequence triggers below stay inline
        # because their interactive prompt protocol (human_choices / mana_prevention /
        # sacrifice_choices) is driven directly by the web layer.
        upkeep_events: list[dict] = []

        def _enqueue_upkeep_damage(perm, controller_idx, victim_idx, amount, source_line=None):
            upkeep_events.append({
                "controller_index": controller_idx,
                "source_permanent": perm,
                "instruction": OracleInstruction("deal_damage_to_player", None, {}),
                "effect_kind": "triggered_damage",
                "ability_text": source_line,
                "trigger_context": {"victim_player_index": victim_idx, "amount": int(amount)},
            })

        for controller_seat, permanent in self.permanents_with_controller():
            controller = self.players[controller_seat]
            program = compile_card_oracle(permanent.effective_card)
            for trig in program.triggered_abilities:
                if trig.instruction is None:
                    continue
                kind = trig.instruction.kind
                cond = trig.condition.kind

                # "at the beginning of YOUR upkeep" only fires during the controller's own upkeep.
                if cond == "upkeep_self" and controller_seat != player_index:
                    break

                handler = UPKEEP_EFFECTS.get((cond, kind))
                if handler is None and cond in _ORDINARY_UPKEEP_SEATS:
                    # An upkeep trigger with nothing interactive about it —
                    # "At the beginning of your upkeep, you may search your
                    # library …" (Sanctum of All). CR 603.3: it goes on the
                    # stack and resolves through EFFECT_HANDLERS like any other
                    # trigger, which is what makes it the *ordinary* case and
                    # the registry above the exception.
                    #
                    # The registry is asked first because those handlers are
                    # pay-or-consequence shapes whose prompt protocol the web
                    # layer drives inline; a pair it answers never reaches here.
                    # Only the two conditions whose seat is unambiguous are
                    # admitted: "your upkeep" is the source's controller and
                    # "each player's upkeep" is whoever's it is, where
                    # `upkeep_enchanted_controller` and `upkeep_chosen` name a
                    # seat this loop does not have in hand.
                    if kind in EFFECT_HANDLERS:
                        upkeep_events.append({
                            "controller_index": controller_seat,
                            "source_permanent": permanent,
                            "instruction": trig.instruction,
                            "effect_kind": triggered_label(kind, cond),
                            "ability_text": trig.source_line or None,
                        })
                        # `continue`, not `break`. CR 603.3 puts **every**
                        # ability that triggered on the stack, and this loop
                        # stopped at the first one — invisible until Tetravus,
                        # the only card in the pool printing two upkeep
                        # triggers, whose second one never fired.
                        continue
                if handler is not None:
                    handler(self, UpkeepContext(
                        game=self,
                        player_index=player_index,
                        controller=controller,
                        permanent=permanent,
                        trig=trig,
                        cond=cond,
                        kind=kind,
                        human_choices=human_choices,
                        optional_choices=optional_choices,
                        mana_prevention=mana_prevention,
                        sacrifice_choices=sacrifice_choices,
                        trigger_targets=trigger_targets,
                        enqueue_damage=_enqueue_upkeep_damage,
                    ))
                    continue

        # Unstable Mutation: enchant-creature auras that decay the enchanted
        # creature at the beginning of its controller's upkeep. The counters
        # are real -1/-1 counters, not an aura grant — they stay if the Aura
        # leaves, and 704.5f/704.5q apply.
        #
        # That last clause was a promise this loop broke: it wrote the two P/T
        # bonuses and no counter record at all, so the 704.5q sweep — which
        # cancels +1/+1 against -1/-1 by reading `minus_counters` — had nothing
        # to find, and a creature carrying both kinds kept both. The placement
        # goes through the counter seam now, which writes the record and the
        # P/T channel together.
        mutation_decay_applied = False
        for permanent in self.all_permanents():
            if permanent.card.primary_type != "enchantment":
                continue
            trig = next(matching_triggers(
                permanent.effective_card,
                condition_kinds={"upkeep_enchanted_controller"},
                instruction_kinds={"add_minus1_counter_to_enchanted"},
            ), None)
            if trig is None:
                continue
            attached = permanent.metadata.get("attached_to")
            if attached is None:
                continue
            if self.controller_index_of(attached) != player_index:
                continue
            self.place_pt_counters(attached, "-1/-1")
            mutation_decay_applied = True
            self.log.append(
                f"{permanent.card.name}: {attached.card.name} gets a -1/-1 counter"
            )
        if mutation_decay_applied:
            # 704.5f: a creature decayed to 0 toughness dies now.
            self.check_state_based_actions()

        # Handle enchant-land auras with optional upkeep life gain (e.g. Farmstead)
        for permanent in self.all_permanents():
            if permanent.card.primary_type != "enchantment":
                continue
            prog = compile_card_oracle(permanent.effective_card)
            text = prog.normalized_text
            if not aura_enchants(permanent.effective_card.oracle_text, "land"):
                continue
            attached_land = permanent.metadata.get("attached_to")
            if attached_land is None:
                continue
            if self.controller_index_of(attached_land) != player_index:
                continue
            instr = next((i for i in prog.instructions if i.kind == "target_gains_life"), None)
            if instr is None:
                continue
            # Parse the optional mana payment from text (e.g. "you may pay {w}{w}")
            pay_match = re.search(r"you may pay ((?:\{[wubrgcWUBRGC]\})+)", text)
            gainer = self.players[player_index]
            paid = False
            if pay_match:
                cost_str = pay_match.group(1).upper()
                cost: dict[str, int] = {}
                for sym in re.findall(r"\{([WUBRG])\}", cost_str):
                    cost[sym] = cost.get(sym, 0) + 1
                can_pay = all(gainer.mana_pool.get(sym, 0) >= cnt for sym, cnt in cost.items())
                # Honor a human's decision (from the upkeep-pay prompt) when given;
                # otherwise auto-pay when able (beneficial default for AI/headless).
                if human_choices is not None and permanent.card.name in human_choices:
                    wants_pay = bool(human_choices[permanent.card.name])
                else:
                    wants_pay = can_pay
                if wants_pay and can_pay:
                    for sym, cnt in cost.items():
                        gainer.mana_pool[sym] -= cnt
                    paid = True
            else:
                paid = True  # No payment required
            if paid:
                amount = int(instr.payload.get("amount", 1))
                self._gain_life(gainer, amount, permanent.card.name)

        # Graveyard-recursion upkeep triggers (e.g. Nether Shadow). These abilities
        # function from the owner's graveyard, so they aren't covered by the
        # battlefield loop above. A card may return itself to the battlefield if at
        # least N creature cards lie above it (i.e. were put into the graveyard more
        # recently — appended later in the list). These are optional ("you may"):
        # ``optional_choices`` maps the card name to the player's decision. When it
        # is None (AI turns, scripted/test runs) the beneficial default is taken;
        # when provided, the card returns only on an explicit yes.
        owner = self.players[player_index]
        accepted_returns = [
            (grave_index, card)
            for grave_index, card in self._graveyard_return_candidates(player_index)
            if optional_choices is None or optional_choices.get(card.name, False)
        ]
        # Remove highest index first, so popping one does not renumber the slots
        # of the ones still to come — the same ordering rule the several-card
        # graveyard return follows. Removing by identity instead would take every
        # copy of the card (see `_graveyard_return_candidates`).
        for grave_index, _card in sorted(accepted_returns, reverse=True):
            if 0 <= grave_index < len(owner.graveyard):
                owner.graveyard.pop(grave_index)
        # Then onto the battlefield in printed graveyard order, so the log reads
        # bottom-up as it always has.
        for _grave_index, card in accepted_returns:
            self._put_permanent_onto_battlefield(player_index, Permanent(card=card), None)
            self.log.append(
                f"{owner.name} returned {card.name} to the battlefield from the graveyard"
            )

        # Vesuvan Doppelganger's upkeep re-copy: apply an accepted choice to the
        # player-chosen creature. Declined (or target-less) prompts do nothing;
        # AI/headless runs (optional_choices is None) keep the current copy.
        for perm in list(owner.battlefield):
            if not grants_ability(perm, RECOPY_EACH_UPKEEP):
                continue
            if optional_choices is None or not optional_choices.get(perm.card.name, False):
                continue
            chosen = (trigger_targets or {}).get(perm.card.name)
            source = None
            if chosen is not None:
                seat, index = chosen
                if 0 <= seat < len(self.players) and 0 <= index < len(self.players[seat].battlefield):
                    candidate = self.players[seat].battlefield[index]
                    if candidate is not perm and self._is_creature(candidate):
                        source = candidate
            if source is None:
                self.log.append(f"{perm.card.name}: no valid creature chosen to copy")
                continue
            self._apply_copy(perm, source)
            self.log.append(f"{perm.card.name} becomes a copy of {source.card.name}")
            self._refresh_dynamic_creatures()

        # Put the collected non-interactive upkeep triggers on the stack in APNAP
        # order; they resolve through the upkeep priority window opened below.
        self._enqueue_triggered_batch(upkeep_events)

        # CR 704.3: state-based actions are checked before a player receives
        # priority. Several upkeep effects deal damage inline (Cyclone's wind
        # counters, the pay-or-suffer family), and this is what destroys what
        # they killed — the handlers no longer sweep for themselves.
        self.check_state_based_actions()

        self._close_or_defer_step(phase, step, defer_priority)
