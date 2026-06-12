from __future__ import annotations

import re

from ..models import PlayerState
from ..oracle import OracleInstruction, compile_card_oracle
from ._constants import _UPKEEP_PAY_KINDS

class UpkeepMixin:
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
                })
                break
        return choices

    def resolve_upkeep(self, player_index: int, human_choices: dict[str, bool] | None = None) -> None:
        phase = "beginning"
        step = "upkeep"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
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
                            permanent.tapped = True
                            opponent = next((p for p in self.players if p is not controller), None)
                            if opponent is not None:
                                for idx, land in enumerate(opponent.battlefield):
                                    if land.card.primary_type == "land":
                                        removed = opponent.battlefield.pop(idx)
                                        opponent.graveyard.append(removed.card)
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

        if self._receives_priority(step):
            self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)
