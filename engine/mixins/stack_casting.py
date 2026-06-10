from __future__ import annotations

import random
import re

from ..classifier import CardClassification, classify_card
from ..game_types import OracleExecutionContext, OracleStateMachine, SimulationResult, StackItem
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import OracleInstruction, _COLOR_WORD_TO_SYMBOL, compile_card_oracle, lex_oracle_text
from ._constants import _MANA_SYMBOLS

# Maps an "enchant X" noun to a predicate matching legal battlefield targets.
_ENCHANT_TARGET_MATCHERS = {
    "artifact": lambda perm: "artifact" in perm.card.type_line.lower(),
    "creature": lambda perm: perm.card.primary_type == "creature",
    "land": lambda perm: perm.card.primary_type == "land",
    "enchantment": lambda perm: "enchantment" in perm.card.type_line.lower(),
    "wall": lambda perm: "wall" in perm.card.type_line.lower(),
}


def aura_enchant_noun(card: CardDefinition) -> str | None:
    """Return the battlefield enchant noun for an Aura card, or None.

    Returns None for non-Auras and for Auras that don't enchant battlefield
    permanents (e.g. Animate Dead's "enchant creature card in a graveyard").
    """
    if "Aura" not in card.type_line:
        return None
    first_line = card.oracle_text.lower().split("\n")[0]
    first_line = re.sub(r"\([^)]*\)", "", first_line).strip()  # drop reminder text
    if not first_line.startswith("enchant "):
        return None
    noun = first_line[len("enchant "):].strip()
    if "graveyard" in noun:
        return None
    return noun


def permanent_matches_enchant_noun(permanent: Permanent, noun: str) -> bool:
    matcher = _ENCHANT_TARGET_MATCHERS.get(noun)
    if matcher is None:
        return True  # unknown enchant type — treat any permanent as legal
    return matcher(permanent)


class StackCastingMixin:
    def cast_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=x_value,
        )
        if not queued.supported:
            return queued

        self.resolve_stack()
        self.check_state_based_actions()
        self.clear_priority_window()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")

    def activate_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
    ) -> SimulationResult:
        queued = self.queue_permanent_ability(
            controller_index,
            permanent_name,
            target_player_index=target_player_index,
            permanent_index=permanent_index,
            mana_color=mana_color,
        )
        if not queued.supported:
            return queued
        if queued.details == "queued":
            self.resolve_stack()
            self.clear_priority_window()
            return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")
        return queued

    def confirm_search_library(self, caster_index: int, library_index: int) -> bool:
        pending = self.pending_search_library
        if pending is None or pending["caster_index"] != caster_index:
            return False
        caster = self.players[caster_index]
        if library_index < 0 or library_index >= len(caster.library):
            return False
        card = caster.library.pop(library_index)
        caster.hand.append(card)
        random.shuffle(caster.library)
        self.pending_search_library = None
        self.log.append(f"{caster.name} searched library and put {card.name} into hand")
        return True

    def confirm_reorder_library(self, caster_index: int, new_order: list) -> bool:
        pending = self.pending_reorder_library
        if pending is None or pending["caster_index"] != caster_index:
            return False
        target = self.players[pending["target_index"]]
        top_count = pending["top_count"]
        top = target.library[:top_count]
        rest = target.library[top_count:]
        if len(new_order) != top_count or sorted(new_order) != list(range(top_count)):
            return False
        target.library = [top[i] for i in new_order] + rest
        self.pending_reorder_library = None
        self.log.append(f"Top {top_count} cards of {target.name}'s library reordered")
        return True

    def queue_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
    ) -> SimulationResult:
        controller = self.players[controller_index]
        resolved = self._find_controlled_permanent(controller, permanent_name, permanent_index)
        if resolved is None:
            raise ValueError(f"Permanent not found: {permanent_name}")
        _, permanent = resolved

        program = compile_card_oracle(permanent.card)
        target_idx = target_player_index if target_player_index is not None else (1 - controller_index)
        target_player = self.players[target_idx]



        # Special handling for Basalt Monolith: only allow tap if untapped, untap if tapped
        if permanent.card.name == "Basalt Monolith" and len(program.activated_abilities) == 2:
            tap_ability = None
            untap_ability = None
            for ab in program.activated_abilities:
                if ab.cost.requires_tap:
                    tap_ability = ab
                elif ab.cost.mana.get("generic", 0) == 3 and not ab.cost.requires_tap:
                    untap_ability = ab
            if not permanent.tapped:
                ability = tap_ability
            else:
                ability = untap_ability
            # If trying to tap when tapped, or untap when untapped, block
            if ability is None:
                self.log.append(f"No implemented activated ability for {permanent.card.name} in current state")
                return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")
            if ability == tap_ability and permanent.tapped:
                self.log.append(f"Cannot tap Basalt Monolith when already tapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already tapped")
            if ability == untap_ability and not permanent.tapped:
                self.log.append(f"Cannot untap Basalt Monolith when already untapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already untapped")
        else:
            ability = next((item for item in program.activated_abilities if item.supported and item.instruction is not None), None)

        if ability is None or ability.instruction is None:
            self.log.append(f"No implemented activated ability for {permanent.card.name}")
            return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")

        if ability.instruction.kind == "grant_banding_to_target":
            has_valid_target = any(perm.card.primary_type == "creature" for perm in target_player.battlefield)
            if not has_valid_target:
                details = "no valid creature target for banding effect"
                self.log.append("No valid creature target for banding effect")
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        if ability.instruction.kind == "counter_top_stack_spell":
            color_filter = ability.instruction.payload.get("color_filter")
            has_valid_target = any(
                not color_filter or color_filter in (item.card.colors or [])
                for item in self.stack
            )
            if not has_valid_target:
                details = f"no valid target for {permanent.card.name}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        required_cost = dict(ability.cost.mana)
        requires_tap = ability.cost.requires_tap
        if self.enforce_mana_costs and any(required_cost.values()):
            if not self._pay_mana_cost(controller, required_cost):
                details = f"insufficient mana to activate {permanent.card.name}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        if requires_tap:
            if self._is_summoning_sick(permanent):
                details = f"{permanent.card.name} has summoning sickness"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            if permanent.tapped:
                details = f"{permanent.card.name} is already tapped"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            permanent.tapped = True

        instruction = ability.instruction
        if (
            instruction.kind in {"sacrifice_self_for_mana", "add_mana_from_text"}
            and instruction.payload.get("any_color", False)
        ):
            selected_color = self._normalize_mana_color(mana_color)
            if selected_color is not None:
                instruction = OracleInstruction(
                    instruction.kind,
                    instruction.value,
                    {**instruction.payload, "color": selected_color},
                )


        mana_like_kinds = {
            "add_mana_from_text",
            "sacrifice_self_for_mana",
            "sacrifice_creature_for_black_mana",
        }
        if instruction.kind in mana_like_kinds:
            # For Basalt Monolith, block add_mana_from_text if untapped is required and it's already untapped
            if permanent.card.name == "Basalt Monolith" and instruction.kind == "add_mana_from_text" and not permanent.tapped:
                self.log.append(f"Cannot tap Basalt Monolith for mana when already untapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already untapped")
            state_machine = OracleStateMachine(
                self,
                OracleExecutionContext(
                    caster=controller,
                    target=target_player,
                    card=permanent.card,
                    source_permanent=permanent,
                ),
            )
            supported, details = state_machine.run(instruction)
            return SimulationResult(permanent.card.name, supported, ability.effect_kind, details)

        self.stack.append(
            StackItem(
                card=permanent.card,
                caster_index=controller_index,
                target_player_index=target_idx,
                target_permanent_index=None,
                x_value=None,
                ability_instruction=instruction,
                ability_effect_kind=ability.effect_kind,
                source_permanent=permanent,
                ability_text=ability.source_line,
            )
        )
        self.log.append(f"{permanent.card.name} ability added to stack")
        return SimulationResult(permanent.card.name, True, ability.effect_kind, "queued")

    def tap_permanent(
        self,
        controller_index: int,
        permanent_name: str,
        permanent_index: int | None = None,
    ) -> bool:
        controller = self.players[controller_index]
        resolved = self._find_controlled_permanent(controller, permanent_name, permanent_index)
        permanent = resolved[1] if resolved else None
        if permanent is None or permanent.tapped:
            return False

        permanent.tapped = True
        self.log.append(f"{controller.name} tapped {permanent_name}")
        return True

    def queue_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
    ) -> SimulationResult:
        caster = self.players[caster_index]
        try:
            hand_index = next(i for i, card in enumerate(caster.hand) if card.name == card_name)
        except StopIteration as exc:
            raise ValueError(f"Card not in hand: {card_name}") from exc

        card = caster.hand[hand_index]
        classification = classify_card(card)
        extra_generic_tax = 0

        if self.enforce_mana_costs and card.primary_type == "land":
            lands_played = self.lands_played_this_turn.get(caster_index, 0)
            if lands_played >= 1 and self._fastbond_count(caster_index) <= 0:
                details = "already played a land this turn"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        if "W" in card.colors:
            has_gloom = any(
                perm.card.name == "Gloom"
                for player in self.players
                for perm in player.battlefield
            )
            if has_gloom:
                extra_generic_tax = 3
                self.log.append(f"{card.name} is taxed by Gloom")

        # Accept cards with supported triggered abilities (match classifier logic)
        if not classification.supported:
            if classification.reason == "unsupported triggered ability":
                from .oracle import compile_card_oracle
                program = compile_card_oracle(card)
                if any(getattr(program, "triggered_abilities", ())):
                    if any(t.supported for t in program.triggered_abilities):
                        return SimulationResult(card.name, True, program.effect_kind, "supported triggered ability")
            self.log.append(f"Unsupported card: {card.name} ({classification.reason})")
            return SimulationResult(card.name, False, classification.effect_kind, classification.reason)

        if "cast this spell only during your declare attackers step" in card.oracle_text.lower():
            if self.current_step != "declare_attackers" or self.active_player_index != caster_index:
                details = "can only be cast during your declare attackers step"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        target_ok, target_reason = self._validate_cast_targets(
            card, caster_index, target_player_index, target_permanent_index
        )
        if not target_ok:
            self.log.append(target_reason)
            return SimulationResult(card.name, False, classification.effect_kind, target_reason)

        resolved_x_value = x_value
        if resolved_x_value is None and "{X}" in card.mana_cost.upper():
            resolved_x_value = self._infer_x_value(caster, card.mana_cost, extra_generic_tax)

        if self.enforce_mana_costs and card.primary_type != "land":
            cost = self._parse_mana_cost(card.mana_cost, x_value=resolved_x_value, extra_generic=extra_generic_tax)
            if not self._pay_mana_cost(caster, cost):
                details = f"insufficient mana for {card.name}"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        card = caster.hand.pop(hand_index)

        if card.primary_type != "land":
            target_stack_name_val: str | None = None
            if self.stack and "counter target" in card.oracle_text.lower():
                color_match = re.search(r"counter target (\w+) spell", card.oracle_text.lower())
                color_filter: str | None = None
                if color_match:
                    color_filter = _COLOR_WORD_TO_SYMBOL.get(color_match.group(1))
                matching = [it for it in self.stack if not color_filter or color_filter in it.card.colors]
                if matching:
                    target_stack_name_val = matching[-1].card.name
            self.stack.append(
                StackItem(
                    card=card,
                    caster_index=caster_index,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    x_value=resolved_x_value,
                    target_stack_name=target_stack_name_val,
                )
            )
            self.log.append(f"{card.name} added to stack")
            return SimulationResult(card.name, True, classification.effect_kind, "queued")

        self._resolve_card(
            caster_index=caster_index,
            card=card,
            classification=classification,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=resolved_x_value,
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")

    def _validate_cast_targets(
        self,
        card: CardDefinition,
        caster_index: int,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
    ) -> tuple[bool, str]:
        """Return (True, 'valid') if all required targets exist, else (False, reason).

        Only instants and sorceries execute effects at cast time; permanents enter
        the battlefield regardless of whether their activated abilities have targets.
        """
        if card.primary_type not in ("instant", "sorcery"):
            # Aura spells are always targeted: a legal enchant target must be
            # chosen when the spell is cast (MTG Rules 115.1b, 601.2c)
            if "Aura" in card.type_line:
                enchant_noun = aura_enchant_noun(card)
                if enchant_noun is not None:
                    if not isinstance(target_permanent_index, int):
                        return False, f"{card.name} requires a target"
                    target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
                    if target_idx < 0 or target_idx >= len(self.players):
                        target_idx = 1 - caster_index
                    battlefield = self.players[target_idx].battlefield
                    if not (0 <= target_permanent_index < len(battlefield)) or not permanent_matches_enchant_noun(
                        battlefield[target_permanent_index], enchant_noun
                    ):
                        return False, f"no valid target for {card.name}"
                else:
                    first_line = card.oracle_text.lower().split("\n")[0].strip()
                    if first_line.startswith("enchant ") and "graveyard" in first_line:
                        # e.g. "enchant creature card in a graveyard" (Animate Dead)
                        has_target = any(
                            c.primary_type == "creature"
                            for player in self.players
                            for c in player.graveyard
                        )
                        if not has_target:
                            return False, f"no valid target for {card.name}"
            return True, "valid"

        program = compile_card_oracle(card)
        primary = next(
            (instr for instr in program.instructions if instr.kind != "spell_pattern"),
            None,
        )
        if primary is None:
            return True, "valid"

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        if target_idx < 0 or target_idx >= len(self.players):
            target_idx = 1 - caster_index
        target = self.players[target_idx]

        if primary.kind == "destroy_target_permanent":
            type_filter = primary.payload.get("type_filter")
            color_filter = primary.payload.get("color_filter")
            has_target = any(
                (not type_filter or type_filter in p.card.type_line.lower())
                and (not color_filter or color_filter in p.card.colors)
                for p in target.battlefield
            )
            if not has_target:
                return False, f"no valid target for {card.name}"

        elif primary.kind == "counter_top_stack_spell":
            color_filter = primary.payload.get("color_filter")
            if not self.stack:
                return False, f"no valid target for {card.name}"
            if color_filter and not any(color_filter in item.card.colors for item in self.stack):
                return False, f"no valid target for {card.name}"

        elif primary.kind in (
            "pump_target_creature_until_eot",
            "grant_target_flying_until_eot",
            "grant_regeneration_to_target_creature",
            "berserk_pump",
            "grant_unlimited_blocking",
            "bounce_target_creature",
            "exile_target_creature_until_eot",
        ):
            if not any(p.card.primary_type == "creature" for p in target.battlefield):
                return False, f"no valid target for {card.name}"

        elif primary.kind in ("tap_target_permanent", "untap_target_permanent"):
            if not target.battlefield:
                return False, f"no valid target for {card.name}"

        elif primary.kind == "recolor_target_from_text":
            any_permanent = any(p.battlefield for p in self.players)
            if not any_permanent:
                return False, f"no valid target for {card.name}"

        elif primary.kind in ("return_creature_from_graveyard_to_hand", "reanimate_creature_to_battlefield"):
            caster = self.players[caster_index]
            if not any(c.primary_type == "creature" for c in caster.graveyard):
                return False, f"no valid target for {card.name}"

        return True, "valid"

    def _infer_x_value(self, player: PlayerState, mana_cost: str, extra_generic: int = 0) -> int:
        required = self._parse_mana_cost(mana_cost, x_value=0, extra_generic=extra_generic)
        temp = {symbol: player.mana_pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}

        if temp.get("W", 0) < required["W"]:
            return 0
        if temp.get("U", 0) < required["U"]:
            return 0
        if temp.get("B", 0) < required["B"]:
            return 0
        if temp.get("G", 0) < required["G"]:
            return 0
        if temp.get("C", 0) < required["C"]:
            return 0

        available_red = temp.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += temp.get("W", 0)
        if available_red < required["R"]:
            return 0

        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return 0
            if temp.get("W", 0) < red_to_pay:
                return 0
            temp["W"] -= red_to_pay

        available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
        if available_generic < required["generic"]:
            return 0

        return available_generic - required["generic"]

    def _parse_mana_cost(self, mana_cost: str, x_value: int | None, extra_generic: int = 0) -> dict[str, int]:
        required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": max(0, extra_generic)}
        if not mana_cost:
            return required

        for token in re.findall(r"\{([^}]+)\}", mana_cost.upper()):
            if token.isdigit():
                required["generic"] += int(token)
                continue
            if token == "X":
                required["generic"] += max(0, x_value or 0)
                continue
            if token in {"W", "U", "B", "R", "G", "C"}:
                required[token] += 1
        return required

    def _pay_mana_cost(self, player: PlayerState, required: dict[str, int]) -> bool:
        pool = player.mana_pool

        if pool.get("W", 0) < required["W"]:
            return False
        if pool.get("U", 0) < required["U"]:
            return False
        if pool.get("B", 0) < required["B"]:
            return False
        if pool.get("G", 0) < required["G"]:
            return False
        if pool.get("C", 0) < required["C"]:
            return False

        available_red = pool.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += pool.get("W", 0)
        if available_red < required["R"]:
            return False

        temp = {symbol: pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}
        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return False
            if temp.get("W", 0) < red_to_pay:
                return False
            temp["W"] -= red_to_pay

        generic = required["generic"]
        if generic > 0:
            available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
            if available_generic < generic:
                return False

            for sym in ("C", "W", "U", "B", "R", "G"):
                spend = min(temp.get(sym, 0), generic)
                temp[sym] -= spend
                generic -= spend
                if generic == 0:
                    break

        player.mana_pool = temp
        return True

    def resolve_stack(self) -> None:
        while self.stack:
            self.resolve_top_of_stack()

    def resolve_top_of_stack(self) -> bool:
        if not self.stack:
            return False

        item = self.stack.pop()
        if item.ability_instruction is not None:
            caster = self.players[item.caster_index]
            target_idx = item.target_player_index if item.target_player_index is not None else (1 - item.caster_index)
            target = self.players[target_idx]
            state_machine = OracleStateMachine(
                self,
                OracleExecutionContext(
                    caster=caster,
                    target=target,
                    card=item.card,
                    target_permanent_index=item.target_permanent_index,
                    x_value=item.x_value,
                    source_permanent=item.source_permanent,
                ),
            )
            supported, details = state_machine.run(item.ability_instruction)
            if supported:
                self.log.append(f"{item.card.name} ability resolved")
            else:
                self.log.append(f"{item.card.name} ability fizzled: {details}")
            return True

        classification = classify_card(item.card)
        self._resolve_card(
            caster_index=item.caster_index,
            card=item.card,
            classification=classification,
            target_player_index=item.target_player_index,
            target_permanent_index=item.target_permanent_index,
            x_value=item.x_value,
        )
        return True

    def _resolve_card(
        self,
        caster_index: int,
        card: CardDefinition,
        classification: CardClassification,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
    ) -> None:
        caster = self.players[caster_index]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment"}:
            permanent = Permanent(card=card)
            if x_value is not None:
                permanent.metadata["cast_x_value"] = x_value
            self._put_permanent_onto_battlefield(caster_index, permanent, target_player_index)
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            self._apply_aura_effect(caster_index, permanent, target_player_index, target_permanent_index)
            # An Aura that failed to attach (its target left the battlefield while the
            # spell was on the stack) goes to its owner's graveyard instead of
            # remaining on the battlefield unattached (MTG Rule 303.4g)
            if (
                "Aura" in card.type_line
                and card.oracle_text.lower().split("\n")[0].strip().startswith("enchant")
                and permanent.metadata.get("attached_to") is None
            ):
                for player in self.players:
                    if permanent in player.battlefield:
                        player.battlefield.remove(permanent)
                        break
                caster.graveyard.append(card)
                self.log.append(f"{card.name} had no legal target and was put into {caster.name}'s graveyard")
                self._refresh_dynamic_creatures()
                return
            self._apply_cast_triggers(caster_index, card)
            self._refresh_dynamic_creatures()
            if primary_type == "land":
                if self.enforce_mana_costs:
                    self.lands_played_this_turn[caster_index] = self.lands_played_this_turn.get(caster_index, 0) + 1
                    if self.lands_played_this_turn.get(caster_index, 0) > 1:
                        fastbond_count = self._fastbond_count(caster_index)
                        if fastbond_count > 0:
                            damage = self._prevent_damage(caster, fastbond_count)
                            if damage > 0:
                                caster.life -= damage
                            self.log.append(f"Fastbond dealt {damage} damage to {caster.name}")
                self._process_land_enters(caster_index)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target = self.players[target_idx]

        self._apply_spell_text(
            caster,
            target,
            card,
            target_permanent_index=target_permanent_index,
            x_value=x_value,
        )
        self._apply_spell_resolved_triggers(caster_index, card)
        caster.graveyard.append(card)
        self.log.append(f"{card.name} resolved and moved to graveyard")

    def _select_executable_instruction(self, card: CardDefinition) -> OracleInstruction | None:
        program = compile_card_oracle(card)
        return next((instruction for instruction in program.instructions if instruction.kind != "spell_pattern"), None)
