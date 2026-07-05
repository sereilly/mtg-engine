from __future__ import annotations

"""Upkeep step (CR 503).

"At the beginning of upkeep" triggered abilities are put on the stack here, plus
the pay-or-consequence upkeep triggers that may require an interactive choice,
enchant-land upkeep effects, and graveyard-recursion upkeep triggers.
"""

import re

from ..handlers._common import permanent_effective_colors
from ..models import Permanent
from ..oracle import OracleInstruction, compile_card_oracle
from ..trigger_utils import iter_triggered_abilities, matching_triggers
from ..mixins._constants import _UPKEEP_PAY_KINDS


class UpkeepStepMixin:
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
            for perm in player.battlefield
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
            for perm in player.battlefield:
                if remaining <= 0:
                    break
                if perm.card.primary_type == "land" and not perm.tapped and perm.effective_produced_mana:
                    perm.tapped = True
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
            choices.append({
                "card_name": permanent.card.name,
                "mana": trig.instruction.payload.get("mana", {}),
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
        for owner in self.players:
            for permanent in owner.battlefield:
                attached = permanent.metadata.get("attached_to")
                if attached is None or attached not in controller.battlefield:
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
        for owner in self.players:
            for permanent in owner.battlefield:
                if permanent.card.primary_type != "enchantment":
                    continue
                attached = permanent.metadata.get("attached_to")
                if attached is None or attached not in controller.battlefield:
                    continue
                text = compile_card_oracle(permanent.effective_card).normalized_text
                if not text.startswith("enchant land") or "you may pay" not in text or "you gain" not in text:
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
        for controller in self.players:
            for permanent in controller.battlefield:
                if "prevent x of that damage" not in permanent.card.oracle_text.lower():
                    continue
                attached = permanent.metadata.get("attached_to")
                if attached is None or attached not in victim.battlefield:
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
        # Living Artifact: "At the beginning of your upkeep, you may remove a
        # vitality counter from this Aura. If you do, you gain 1 life."
        for perm in self.players[player_index].battlefield:
            if "you may remove a vitality counter" not in perm.card.oracle_text.lower():
                continue
            if int(perm.metadata.get("vitality_counters", 0)) <= 0:
                continue
            if perm.card.name in seen:
                continue
            seen.add(perm.card.name)
            triggers.append({
                "card_name": perm.card.name,
                "kind": "upkeep_remove_vitality_counter",
                "prompt": f"Remove a vitality counter from {perm.card.name} to gain 1 life?",
            })
        # Vesuvan Doppelganger's granted ability: "At the beginning of your
        # upkeep, you may have this creature become a copy of target creature."
        # Carries a creature-target choice alongside the yes/no.
        for perm_index, perm in enumerate(self.players[player_index].battlefield):
            if not perm.metadata.get("may_recopy_each_upkeep"):
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

    def resolve_upkeep(self, player_index: int, human_choices: dict[str, bool] | None = None, optional_choices: dict[str, bool] | None = None, defer_priority: bool = False, mana_prevention: dict[str, int] | None = None, sacrifice_choices: dict[str, int] | None = None, recopy_targets: dict[str, tuple[int, int]] | None = None) -> None:
        phase = "beginning"
        step = "upkeep"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        self._process_mire_cleanups(player_index)
        # Erhnam Djinn: a granted forestwalk (or similar) lasting "until your
        # next upkeep" expires now, at the start of that same upkeep, before
        # this turn's own upkeep triggers (which might grant a fresh one) run.
        for owner in self.players:
            for perm in owner.battlefield:
                if perm.metadata.get("forestwalk_until_next_upkeep_of") == player_index:
                    perm.metadata.pop("has_forestwalk", None)
                    perm.metadata.pop("forestwalk_until_next_upkeep_of", None)
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

        for controller in self.players:
            for permanent in controller.battlefield:
                program = compile_card_oracle(permanent.effective_card)
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
                        _enqueue_upkeep_damage(
                            permanent, self.players.index(controller), player_index, amount, trig.source_line
                        )
                        break

                    if cond == "upkeep_each" and kind == "upkeep_pay_per_creature_untap_color":
                        # Magnetic Mountain: "that player" is whoever's upkeep
                        # is currently resolving (player_index), not this
                        # enchantment's controller. No interactive per-creature
                        # selection channel exists, so as many affordable
                        # tapped creatures of the color are untapped as
                        # possible (greedy, battlefield order) — not an
                        # all-or-nothing simplification.
                        color = str(trig.instruction.payload.get("color", ""))
                        cost_per = int(trig.instruction.payload.get("cost_per", 0))
                        victim = self.players[player_index]
                        untapped_names = []
                        for perm in victim.battlefield:
                            if not (perm.is_creature and perm.tapped):
                                continue
                            if color not in permanent_effective_colors(perm):
                                continue
                            if not self.can_pay_upkeep_mana(victim, {"generic": cost_per}):
                                continue
                            self._spend_upkeep_mana(victim, {"generic": cost_per})
                            perm.tapped = False
                            untapped_names.append(perm.card.name)
                        if untapped_names:
                            self.log.append(
                                f"{victim.name} paid to untap {', '.join(untapped_names)} ({permanent.card.name})"
                            )
                        break

                    if cond == "upkeep_each" and kind == "deal_damage_equal_to_swamps":
                        victim = self.players[player_index]
                        swamp_count = sum(
                            1 for perm in victim.battlefield
                            if "swamp" in perm.card.type_line.lower()
                            or perm.metadata.get("land_type_override") == "swamp"
                        )
                        _enqueue_upkeep_damage(
                            permanent, self.players.index(controller), player_index, swamp_count, trig.source_line
                        )
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
                        damage = self._deal_damage_to_player(victim, amount, source=permanent)
                        self.log.append(f"{permanent.card.name} dealt {damage} upkeep damage to {victim.name}")
                        break

                    if cond == "upkeep_chosen" and kind == "upkeep_chosen_player_hand_overflow_damage":
                        chosen = permanent.metadata.get("chosen_player_index")
                        if chosen != player_index:
                            break
                        victim = self.players[player_index]
                        damage = max(0, len(victim.hand) - 4)
                        if damage > 0:
                            _enqueue_upkeep_damage(
                                permanent, self.players.index(controller), player_index, damage, trig.source_line
                            )
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
                            damage_amt = self._deal_damage_to_player(controller, damage_amt, source=permanent)
                            self.log.append(f"{permanent.card.name} dealt {damage_amt} upkeep damage to {controller.name}")
                        break

                    if cond == "upkeep_self" and kind == "upkeep_pay_to_untap_self":
                        # Mana Vault / Basalt Monolith: "you may pay {N}. If you do,
                        # untap this artifact." No consequence on decline; the
                        # beneficial default (AI/headless) untaps when affordable.
                        # A human accept is honored only when the cost is actually
                        # payable — choosing "pay" with no mana must not untap for free.
                        mana = trig.instruction.payload.get("mana", {})
                        if human_choices is not None and permanent.card.name in human_choices:
                            paid = human_choices[permanent.card.name]
                        else:
                            paid = True
                        paid = paid and self.can_pay_upkeep_mana(controller, mana)
                        if paid and permanent.tapped:
                            self._spend_upkeep_mana(controller, mana)
                            permanent.tapped = False
                            self.log.append(f"{controller.name} paid to untap {permanent.card.name}")
                        break

                    if cond == "upkeep_enchanted_controller" and kind == "upkeep_pay_to_untap_enchanted":
                        # Paralyze: "that player may pay {N}. If the player does, untap
                        # the creature." The enchanted creature's controller decides.
                        attached = permanent.metadata.get("attached_to")
                        if attached is None:
                            break
                        attached_controller_idx = next(
                            (i for i, p in enumerate(self.players) if attached in p.battlefield),
                            None,
                        )
                        if attached_controller_idx != player_index:
                            break
                        payer = self.players[player_index]
                        mana = trig.instruction.payload.get("mana", {})
                        if human_choices is not None and permanent.card.name in human_choices:
                            paid = human_choices[permanent.card.name]
                        else:
                            paid = True
                        paid = paid and self.can_pay_upkeep_mana(payer, mana)
                        if paid and attached.tapped:
                            self._spend_upkeep_mana(payer, mana)
                            attached.tapped = False
                            self.log.append(f"{payer.name} paid to untap {attached.card.name}")
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

                    if cond == "upkeep_self" and kind == "upkeep_sacrifice_land_conditional_damage":
                        # Serendib Djinn: "Sacrifice a land. If you sacrifice an
                        # Island this way, this creature deals 3 damage to you."
                        # No choice is modeled for which land (matching the
                        # existing Demonic-Hordes-style forced-land-sacrifice
                        # precedent above) — the first land is sacrificed.
                        land_type = str(trig.instruction.payload.get("land_type", "")).lower()
                        damage_amt = int(trig.instruction.payload.get("damage", 0))
                        for idx, land in enumerate(controller.battlefield):
                            if land.card.primary_type != "land":
                                continue
                            removed = controller.battlefield.pop(idx)
                            controller.graveyard.append(removed.card)
                            self.log.append(f"{permanent.card.name} forced sacrifice of {removed.card.name}")
                            was_matching_type = (
                                land_type in removed.card.type_line.lower()
                                or land.metadata.get("land_type_override") == land_type
                            )
                            if was_matching_type:
                                dealt = self._deal_damage_to_player(controller, damage_amt, source=permanent)
                                self.log.append(f"{permanent.card.name} dealt {dealt} damage to {controller.name}")
                            break
                        break

                    if cond == "upkeep_self" and kind == "grant_forestwalk_until_next_upkeep":
                        # Erhnam Djinn: no interactive target-choice channel
                        # exists for upkeep triggers yet, so the first legal
                        # non-Wall creature an opponent controls is chosen
                        # (matching the deterministic-fallback precedent used
                        # throughout this engine for untargeted resolution).
                        target_perm = next(
                            (
                                perm
                                for opponent in self.players
                                if opponent is not controller
                                for perm in opponent.battlefield
                                if perm.is_creature and "wall" not in perm.effective_card.type_line.lower()
                            ),
                            None,
                        )
                        if target_perm is not None:
                            target_perm.metadata["has_forestwalk"] = True
                            target_perm.metadata["forestwalk_until_next_upkeep_of"] = self.players.index(controller)
                            self.log.append(
                                f"{permanent.card.name} grants {target_perm.card.name} forestwalk until {controller.name}'s next upkeep"
                            )
                        break

                    if cond == "upkeep_self" and kind == "upkeep_most_life_gains_control":
                        # Ghazbân Ogre: control passes to whichever player has
                        # STRICTLY more life than every other (a tie for the
                        # lead means no change). Living players only (CR
                        # 800.4a: a player who's left the game has no life
                        # total to compare).
                        living = [p for p in self.players if not p.lost]
                        sole_leader = None
                        if living:
                            top_life = max(p.life for p in living)
                            leaders = [p for p in living if p.life == top_life]
                            if len(leaders) == 1:
                                sole_leader = leaders[0]
                        if sole_leader is not None and sole_leader is not controller:
                            controller.battlefield.remove(permanent)
                            sole_leader.battlefield.append(permanent)
                            self.log.append(
                                f"{sole_leader.name} gains control of {permanent.card.name} (most life)"
                            )
                        break

                    if cond == "upkeep_self" and kind == "upkeep_sacrifice_other_creature_or_deal_damage":
                        # Lord of the Pit: "sacrifice a creature other than this
                        # creature. If you can't, this creature deals N damage to
                        # you." The controller chooses which other creature (a human
                        # is prompted; AI/headless picks inline). With no other
                        # creature, the damage consequence applies instead.
                        self.arm_forced_sacrifice(
                            self.players.index(controller),
                            1,
                            filter="creature",
                            exclude=permanent,
                            reason=permanent.card.name,
                            on_short={"kind": "damage", "amount": int(trig.instruction.payload.get("damage", 0))},
                        )
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
                        # Living Artifact: "you MAY remove a vitality counter ...
                        # If you do, you gain 1 life." Honor the player's yes/no
                        # (surfaced by get_optional_upkeep_triggers); AI/headless
                        # runs (optional_choices is None) take the beneficial default.
                        counters = int(permanent.metadata.get("vitality_counters", 0))
                        if optional_choices is None:
                            accepted = True
                        else:
                            accepted = bool(optional_choices.get(permanent.card.name, False))
                        if counters > 0 and accepted:
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
                prog = compile_card_oracle(permanent.effective_card)
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
                _enqueue_upkeep_damage(permanent, self.players.index(controller), player_index, amount)

        # Handle enchant-land auras with optional upkeep life gain (e.g. Farmstead)
        for controller in self.players:
            for permanent in controller.battlefield:
                if permanent.card.primary_type != "enchantment":
                    continue
                prog = compile_card_oracle(permanent.effective_card)
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

        # Vesuvan Doppelganger's upkeep re-copy: apply an accepted choice to the
        # player-chosen creature. Declined (or target-less) prompts do nothing;
        # AI/headless runs (optional_choices is None) keep the current copy.
        for perm in list(owner.battlefield):
            if not perm.metadata.get("may_recopy_each_upkeep"):
                continue
            if optional_choices is None or not optional_choices.get(perm.card.name, False):
                continue
            chosen = (recopy_targets or {}).get(perm.card.name)
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
            self._apply_creature_copy(perm, source)
            self.log.append(f"{perm.card.name} becomes a copy of {source.card.name}")
            self._refresh_dynamic_creatures()

        # Put the collected non-interactive upkeep triggers on the stack in APNAP
        # order; they resolve through the upkeep priority window opened below.
        self._enqueue_triggered_batch(upkeep_events)

        self._close_or_defer_step(phase, step, defer_priority)
