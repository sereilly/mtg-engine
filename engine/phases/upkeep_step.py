from __future__ import annotations

"""Upkeep step (CR 503).

"At the beginning of upkeep" triggered abilities are put on the stack here, plus
the pay-or-consequence upkeep triggers that may require an interactive choice,
enchant-land upkeep effects, and graveyard-recursion upkeep triggers.
"""

import re

from ..models import Permanent
from ..oracle import compile_card_oracle
from ..mixins._constants import _UPKEEP_PAY_KINDS


class UpkeepStepMixin:
    def get_upkeep_pay_triggers(self, player_index: int) -> list[dict]:
        """Return pay-or-consequence upkeep triggers that the player must decide on.

        Only returns triggers where the permanent's controller is ``player_index``
        and the condition is ``upkeep_self`` (i.e. fires on *their* upkeep).
        """
        controller = self.players[player_index]
        choices: list[dict] = []
        for permanent in controller.battlefield:
            program = compile_card_oracle(permanent.card)
            for trig in program.triggered_abilities:
                if trig.instruction is None:
                    continue
                if trig.condition.kind != "upkeep_self":
                    continue
                if trig.instruction.kind not in _UPKEEP_PAY_KINDS:
                    continue
                mana: dict[str, int] = trig.instruction.payload.get("mana", {})
                choices.append({
                    "card_name": permanent.card.name,
                    "mana": mana,
                    "kind": trig.instruction.kind,
                    # "unless you pay" alternative consequence, used to label the
                    # decline button (e.g. Force of Nature deals 8 damage; it is
                    # not a sacrifice).
                    "damage": int(trig.instruction.payload.get("damage", 0)),
                })
                break
        return choices

    def get_upkeep_mana_prevention_triggers(self, player_index: int) -> list[dict]:
        """Return upkeep triggers where this player may pay any amount of mana to
        prevent that much damage (Power Leak). The UI prompts for an amount; the
        chosen value is passed back via ``resolve_upkeep(mana_prevention=...)``.
        """
        victim = self.players[player_index]
        triggers: list[dict] = []
        for controller in self.players:
            for permanent in controller.battlefield:
                if "prevent x of that damage" not in permanent.card.oracle_text.lower():
                    continue
                attached = permanent.metadata.get("attached_to")
                if attached is None or attached not in victim.battlefield:
                    continue
                for trig in compile_card_oracle(permanent.card).triggered_abilities:
                    if (
                        trig.condition.kind == "upkeep_enchanted_controller"
                        and trig.instruction is not None
                        and trig.instruction.kind == "deal_damage"
                    ):
                        triggers.append({
                            "card_name": permanent.card.name,
                            "kind": "upkeep_pay_to_prevent_damage",
                            "damage": int(trig.instruction.payload.get("amount", 1)),
                        })
                        break
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
            return any(land in player.battlefield for player in self.players)

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
                freed.metadata.pop("land_type_override", None)
                self.log.append(f"Mire counter removed from {freed.card.name}")
            if lands:
                obligation["lands"] = lands
                surviving.append(obligation)
        self.mire_cleanup_obligations = surviving

    def _graveyard_return_candidates(self, player_index: int) -> list:
        """Graveyard cards whose 'return during your upkeep' trigger condition is
        currently met for ``player_index`` (e.g. Nether Shadow with enough creature
        cards above it). Shared by the prompt query and the upkeep resolver so both
        agree on which cards are eligible.
        """
        owner = self.players[player_index]
        candidates = []
        for grave_index, card in enumerate(owner.graveyard):
            program = compile_card_oracle(card)
            instr = next(
                (
                    trig.instruction
                    for trig in program.triggered_abilities
                    if trig.instruction is not None
                    and trig.instruction.kind == "upkeep_return_self_from_graveyard"
                    and trig.condition.kind == "upkeep_self"
                ),
                None,
            )
            if instr is None:
                continue
            creatures_above = sum(
                1
                for above in owner.graveyard[grave_index + 1:]
                if above.primary_type == "creature"
            )
            if creatures_above >= int(instr.payload.get("min_creatures_above", 3)):
                candidates.append(card)
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
        for card in self._graveyard_return_candidates(player_index):
            if card.name in seen:
                continue
            seen.add(card.name)
            triggers.append({
                "card_name": card.name,
                "kind": "upkeep_return_self_from_graveyard",
                "prompt": f"Return {card.name} to the battlefield from your graveyard?",
            })
        return triggers

    def resolve_upkeep(self, player_index: int, human_choices: dict[str, bool] | None = None, optional_choices: dict[str, bool] | None = None, defer_priority: bool = False, mana_prevention: dict[str, int] | None = None) -> None:
        phase = "beginning"
        step = "upkeep"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        self._process_mire_cleanups(player_index)
        for controller in self.players:
            for permanent in controller.battlefield:
                program = compile_card_oracle(permanent.card)
                for trig in program.triggered_abilities:
                    if trig.instruction is None:
                        continue
                    kind = trig.instruction.kind
                    cond = trig.condition.kind

                    # "at the beginning of YOUR upkeep" only fires during the controller's own upkeep.
                    if cond == "upkeep_self" and controller is not self.players[player_index]:
                        break

                    if cond == "upkeep_self" and kind == "upkeep_pay_or_sacrifice_enchantment":
                        mana: dict[str, int] = trig.instruction.payload.get("mana", {})
                        if human_choices is not None and permanent.card.name in human_choices:
                            paid = human_choices[permanent.card.name]
                        else:
                            paid = all(
                                controller.mana_pool.get(sym, 0) >= count
                                for sym, count in mana.items()
                                if sym != "generic"
                            )
                        if paid:
                            for sym, count in mana.items():
                                if sym != "generic":
                                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
                            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                        else:
                            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
                            controller.graveyard.append(permanent.card)
                            self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")
                        break

                    if cond == "upkeep_each" and kind == "deal_damage":
                        raw_amount = trig.instruction.payload.get("amount", 1)
                        if raw_amount == "x":
                            amount = self.untapped_lands_at_turn_start.get(player_index, 0)
                        else:
                            amount = int(raw_amount)
                        victim = self.players[player_index]
                        damage = self._deal_damage_to_player(victim, amount)
                        self.log.append(f"{permanent.card.name} dealt {damage} upkeep damage to {victim.name}")
                        break

                    if cond == "upkeep_each" and kind == "deal_damage_equal_to_swamps":
                        victim = self.players[player_index]
                        swamp_count = sum(
                            1 for perm in victim.battlefield
                            if "swamp" in perm.card.type_line.lower()
                            or perm.metadata.get("land_type_override") == "swamp"
                        )
                        damage = self._deal_damage_to_player(victim, swamp_count)
                        self.log.append(f"{permanent.card.name} dealt {damage} damage to {victim.name} ({swamp_count} swamps)")
                        break

                    if cond == "upkeep_enchanted_controller" and kind == "deal_damage":
                        # This covers Auras that read "At the beginning of the upkeep of
                        # enchanted enchantment's controller, this Aura deals N damage to that player."
                        attached = permanent.metadata.get("attached_to")
                        if attached is None:
                            break
                        attached_controller_idx = next(
                            (i for i, p in enumerate(self.players) if attached in p.battlefield),
                            None,
                        )
                        if attached_controller_idx != player_index:
                            break
                        amount = int(trig.instruction.payload.get("amount", 1))
                        victim = self.players[player_index]
                        # Power Leak: "that player may pay any amount of mana. ...
                        # Prevent X of that damage, where X is the amount of mana
                        # that player paid this way." The controller may pay up to
                        # `amount` mana to prevent that much damage.
                        if "prevent x of that damage" in permanent.card.oracle_text.lower():
                            requested = 0
                            if mana_prevention is not None and permanent.card.name in mana_prevention:
                                requested = max(0, int(mana_prevention[permanent.card.name]))
                            available = sum(victim.mana_pool.get(s, 0) for s in victim.mana_pool)
                            paid = min(requested, amount, available)
                            remaining = paid
                            for sym in list(victim.mana_pool):
                                while remaining > 0 and victim.mana_pool.get(sym, 0) > 0:
                                    victim.mana_pool[sym] -= 1
                                    remaining -= 1
                            amount = max(0, amount - paid)
                            if paid:
                                self.log.append(f"{victim.name} paid {paid} mana to prevent {paid} damage from {permanent.card.name}")
                        damage = self._deal_damage_to_player(victim, amount)
                        self.log.append(f"{permanent.card.name} dealt {damage} upkeep damage to {victim.name}")
                        break

                    if cond == "upkeep_chosen" and kind == "upkeep_chosen_player_hand_overflow_damage":
                        chosen = permanent.metadata.get("chosen_player_index")
                        if chosen != player_index:
                            break
                        victim = self.players[player_index]
                        damage = max(0, len(victim.hand) - 4)
                        if damage > 0:
                            damage = self._deal_damage_to_player(victim, damage)
                        self.log.append(f"{permanent.card.name} dealt {damage} upkeep damage")
                        break

                    if cond == "upkeep_self" and kind == "upkeep_pay_or_deal_damage_to_controller":
                        mana = trig.instruction.payload.get("mana", {})
                        damage_amt = int(trig.instruction.payload.get("damage", 0))
                        if human_choices is not None and permanent.card.name in human_choices:
                            paid = human_choices[permanent.card.name]
                        else:
                            paid = all(
                                controller.mana_pool.get(sym, 0) >= count
                                for sym, count in mana.items()
                                if sym != "generic"
                            )
                        if paid:
                            for sym, count in mana.items():
                                if sym != "generic":
                                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
                            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                        else:
                            damage_amt = self._deal_damage_to_player(controller, damage_amt)
                            self.log.append(f"{permanent.card.name} dealt {damage_amt} upkeep damage to {controller.name}")
                        break

                    if cond == "upkeep_self" and kind == "upkeep_pay_or_tap_and_sacrifice_opponent_land":
                        mana = trig.instruction.payload.get("mana", {})
                        if human_choices is not None and permanent.card.name in human_choices:
                            paid = human_choices[permanent.card.name]
                        else:
                            paid = all(
                                controller.mana_pool.get(sym, 0) >= count
                                for sym, count in mana.items()
                                if sym != "generic"
                            )
                        if paid:
                            for sym, count in mana.items():
                                if sym != "generic":
                                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
                            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                        else:
                            # "tap this creature and sacrifice a land of an opponent's
                            # choice" — the CONTROLLER sacrifices one of their own lands
                            # (the opponent merely chooses which; simplified to the first).
                            permanent.tapped = True
                            for idx, land in enumerate(controller.battlefield):
                                if land.card.primary_type == "land":
                                    removed = controller.battlefield.pop(idx)
                                    controller.graveyard.append(removed.card)
                                    self.log.append(f"{permanent.card.name} forced sacrifice of {removed.card.name}")
                                    break
                        break

                    if cond == "upkeep_self" and kind == "upkeep_sacrifice_other_creature_or_deal_damage":
                        other_idx = next(
                            (
                                i
                                for i, perm in enumerate(controller.battlefield)
                                if perm is not permanent and perm.card.primary_type == "creature"
                            ),
                            None,
                        )
                        if other_idx is not None:
                            sacrificed = controller.battlefield.pop(other_idx)
                            controller.graveyard.append(sacrificed.card)
                            self.log.append(f"{controller.name} sacrificed {sacrificed.card.name} for {permanent.card.name}")
                        else:
                            alt_damage = int(trig.instruction.payload.get("damage", 0))
                            alt_damage = self._deal_damage_to_player(controller, alt_damage)
                            self.log.append(f"{permanent.card.name} dealt {alt_damage} upkeep damage to {controller.name}")
                        break

                    if cond == "upkeep_self" and kind == "upkeep_pay_or_sacrifice_self":
                        mana = trig.instruction.payload.get("mana", {})
                        if human_choices is not None and permanent.card.name in human_choices:
                            paid = human_choices[permanent.card.name]
                        else:
                            paid = all(
                                controller.mana_pool.get(sym, 0) >= count
                                for sym, count in mana.items()
                                if sym != "generic"
                            )
                        if paid:
                            for sym, count in mana.items():
                                if sym != "generic":
                                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
                            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                        else:
                            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
                            controller.graveyard.append(permanent.card)
                            self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")
                        break

                    if cond == "upkeep_self" and kind == "target_gains_life":
                        counters = int(permanent.metadata.get("vitality_counters", 0))
                        if counters > 0:
                            permanent.metadata["vitality_counters"] = counters - 1
                            self.log.append(f"{permanent.card.name}: {controller.name} removed a vitality counter")
                            self._gain_life(controller, 1, permanent.card.name)
                        break

                    if cond == "no_islands" and kind == "sacrifice_self":
                        has_island = any(
                            perm.card.primary_type == "land"
                            and (
                                "island" in perm.card.type_line.lower()
                                or perm.metadata.get("land_type_override") == "island"
                            )
                            for perm in controller.battlefield
                        )
                        if not has_island:
                            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
                            controller.graveyard.append(permanent.card)
                            self.log.append(f"{controller.name} sacrificed {permanent.card.name} for lacking an Island")
                        break

        # Handle enchant-land auras with upkeep damage (e.g. Cursed Land)
        for controller in self.players:
            for permanent in controller.battlefield:
                if permanent.card.primary_type != "enchantment":
                    continue
                prog = compile_card_oracle(permanent.card)
                text = prog.normalized_text
                if not text.startswith("enchant land"):
                    continue
                attached_land = permanent.metadata.get("attached_to")
                if attached_land is None:
                    continue
                # Find which player controls the enchanted land
                land_controller_idx = next(
                    (i for i, p in enumerate(self.players) if attached_land in p.battlefield),
                    None,
                )
                if land_controller_idx != player_index:
                    continue
                instr = next((i for i in prog.instructions if i.kind == "deal_damage"), None)
                if instr is None:
                    continue
                amount = int(instr.payload.get("amount", 1))
                victim = self.players[player_index]
                damage = self._deal_damage_to_player(victim, amount)
                self.log.append(f"{permanent.card.name} dealt {damage} upkeep damage to {victim.name}")

        # Handle enchant-land auras with optional upkeep life gain (e.g. Farmstead)
        for controller in self.players:
            for permanent in controller.battlefield:
                if permanent.card.primary_type != "enchantment":
                    continue
                prog = compile_card_oracle(permanent.card)
                text = prog.normalized_text
                if not text.startswith("enchant land"):
                    continue
                attached_land = permanent.metadata.get("attached_to")
                if attached_land is None:
                    continue
                land_controller_idx = next(
                    (i for i, p in enumerate(self.players) if attached_land in p.battlefield),
                    None,
                )
                if land_controller_idx != player_index:
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
                    # Auto-pay if controller has enough
                    can_pay = all(gainer.mana_pool.get(sym, 0) >= cnt for sym, cnt in cost.items())
                    if can_pay:
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
        for card in self._graveyard_return_candidates(player_index):
            if optional_choices is None:
                accepted = True
            else:
                accepted = optional_choices.get(card.name, False)
            if not accepted:
                continue
            owner.graveyard = [c for c in owner.graveyard if c is not card]
            self._put_permanent_onto_battlefield(player_index, Permanent(card=card), None)
            self.log.append(
                f"{owner.name} returned {card.name} to the battlefield from the graveyard"
            )

        self._close_or_defer_step(phase, step, defer_priority)
