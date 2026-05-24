from __future__ import annotations

import re
from dataclasses import dataclass, field

from .classifier import CardClassification, classify_card
from .models import CardDefinition, Permanent, PlayerState
from .oracle import OracleInstruction, compile_card_oracle, parse_activated_ability_cost


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}

_COLOR_WORD_TO_SYMBOL = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
}


@dataclass
class SimulationResult:
    card_name: str
    supported: bool
    effect_kind: str
    details: str


@dataclass
class StackItem:
    card: CardDefinition
    caster_index: int
    target_player_index: int | None
    x_value: int | None


@dataclass
class OracleExecutionContext:
    caster: PlayerState
    target: PlayerState
    card: CardDefinition
    x_value: int | None = None
    source_permanent: Permanent | None = None


class OracleStateMachine:
    def __init__(self, game: Game, context: OracleExecutionContext) -> None:
        self.game = game
        self.context = context
        self.state = "ready"

    def run(self, instruction: OracleInstruction) -> tuple[bool, str]:
        self.state = "running"
        supported, details = self.game._execute_oracle_instruction(instruction, self.context)
        self.state = "completed" if supported else "failed"
        return supported, details


@dataclass
class Game:
    players: list[PlayerState]
    enforce_mana_costs: bool = False
    turn: int = 1
    current_phase: str = "main"
    lands_played_this_turn: dict[int, int] = field(default_factory=lambda: {0: 0, 1: 0})
    stack: list[StackItem] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    extra_turns: dict[int, int] = field(default_factory=dict)
    combat_damage_prevented_until_eot: bool = False

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

    def cast_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        x_value: int | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            x_value=x_value,
        )
        if not queued.supported:
            return queued

        self.resolve_stack()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")

    def activate_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
    ) -> SimulationResult:
        controller = self.players[controller_index]
        resolved = self._find_controlled_permanent(controller, permanent_name, permanent_index)
        if resolved is None:
            raise ValueError(f"Permanent not found: {permanent_name}")
        _, permanent = resolved

        program = compile_card_oracle(permanent.card)
        target_idx = target_player_index if target_player_index is not None else (1 - controller_index)
        target_player = self.players[target_idx]

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

        required_cost = dict(ability.cost.mana)
        requires_tap = ability.cost.requires_tap
        if self.enforce_mana_costs and any(required_cost.values()):
            if not self._pay_mana_cost(controller, required_cost):
                details = f"insufficient mana to activate {permanent.card.name}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        if requires_tap:
            if permanent.tapped:
                details = f"{permanent.card.name} is already tapped"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            permanent.tapped = True

        state_machine = OracleStateMachine(
            self,
            OracleExecutionContext(
                caster=controller,
                target=target_player,
                card=permanent.card,
                source_permanent=permanent,
            ),
        )
        supported, details = state_machine.run(ability.instruction)
        return SimulationResult(permanent.card.name, supported, ability.effect_kind, details)

    def _parse_activated_ability_cost(self, oracle_text: str) -> tuple[dict[str, int], bool]:
        if not oracle_text:
            empty = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
            return empty, False

        for raw_line in oracle_text.splitlines():
            line = raw_line.strip()
            if ":" not in line:
                continue
            parsed = parse_activated_ability_cost(line)
            return dict(parsed.mana), parsed.requires_tap

        empty = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
        return empty, False

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
            if self.lands_played_this_turn.get(caster_index, 0) >= 1:
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

        if not classification.supported:
            self.log.append(f"Unsupported card: {card.name} ({classification.reason})")
            return SimulationResult(card.name, False, classification.effect_kind, classification.reason)

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

        if card.primary_type in {"instant", "sorcery"}:
            self.stack.append(
                StackItem(
                    card=card,
                    caster_index=caster_index,
                    target_player_index=target_player_index,
                    x_value=resolved_x_value,
                )
            )
            self.log.append(f"{card.name} added to stack")
            return SimulationResult(card.name, True, classification.effect_kind, "queued")

        self._resolve_card(
            caster_index=caster_index,
            card=card,
            classification=classification,
            target_player_index=target_player_index,
            x_value=resolved_x_value,
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")

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
            item = self.stack.pop()
            classification = classify_card(item.card)
            self._resolve_card(
                caster_index=item.caster_index,
                card=item.card,
                classification=classification,
                target_player_index=item.target_player_index,
                x_value=item.x_value,
            )

    def _resolve_card(
        self,
        caster_index: int,
        card: CardDefinition,
        classification: CardClassification,
        target_player_index: int | None,
        x_value: int | None = None,
    ) -> None:
        caster = self.players[caster_index]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment"}:
            permanent = Permanent(card=card)
            if x_value is not None:
                permanent.metadata["cast_x_value"] = x_value
            caster.battlefield.append(permanent)
            self._initialize_permanent_state(permanent, caster_index, target_player_index)
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            self._apply_aura_effect(caster_index, permanent, target_player_index)
            self._apply_cast_triggers(caster_index, card)
            self._refresh_dynamic_creatures()
            if primary_type == "land":
                if self.enforce_mana_costs:
                    self.lands_played_this_turn[caster_index] = self.lands_played_this_turn.get(caster_index, 0) + 1
                self._process_land_enters(caster_index)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target = self.players[target_idx]

        self._apply_spell_text(caster, target, card, x_value=x_value)
        caster.graveyard.append(card)
        self.log.append(f"{card.name} resolved and moved to graveyard")

    def _select_executable_instruction(self, card: CardDefinition) -> OracleInstruction | None:
        program = compile_card_oracle(card)
        return next((instruction for instruction in program.instructions if instruction.kind != "spell_pattern"), None)

    def _execute_oracle_instruction(
        self,
        instruction: OracleInstruction,
        context: OracleExecutionContext,
    ) -> tuple[bool, str]:
        caster = context.caster
        target = context.target
        card = context.card
        source_permanent = context.source_permanent
        x_value = context.x_value

        if instruction.kind == "draw_target_cards":
            amount = instruction.payload.get("amount", 0)
            count = max(0, x_value or 0) if amount == "x" else int(amount)
            drawn = target.draw(count)
            self.log.append(f"{target.name} drew {drawn} cards")
            return True, "resolved"

        if instruction.kind == "discard_hand_ante_then_draw_seven":
            while caster.hand:
                caster.graveyard.append(caster.hand.pop(0))
            if caster.library:
                caster.graveyard.append(caster.library.pop(0))
            drawn = caster.draw(7)
            self.log.append(f"{card.name} resolved: discarded hand and drew {drawn} cards")
            return True, "resolved"

        if instruction.kind == "each_player_antes_top_card":
            anted = 0
            for player in self.players:
                if player.library:
                    player.graveyard.append(player.library.pop(0))
                    anted += 1
            self.log.append(f"{card.name} anted {anted} card(s) in simplified model")
            return True, "resolved"

        if instruction.kind == "exchange_ante_with_top_library":
            if caster.library:
                caster.graveyard.append(caster.library.pop(0))
                self.log.append(f"{card.name} exchanged top library card with simulated ante zone")
            else:
                self.log.append(f"{card.name} resolved with no library card to exchange")
            return True, "resolved"

        if instruction.kind == "copy_top_stack_spell":
            if self.stack:
                copied = self.stack[-1]
                self._apply_spell_text(caster, target, copied.card, x_value=copied.x_value)
                self.log.append(f"{card.name} copied {copied.card.name}")
            else:
                self.log.append(f"{card.name} resolved with no spell to copy")
            return True, "resolved"

        if instruction.kind == "balance_resources":
            min_lands = min(sum(1 for perm in player.battlefield if perm.card.primary_type == "land") for player in self.players)
            min_creatures = min(sum(1 for perm in player.battlefield if perm.card.primary_type == "creature") for player in self.players)
            min_hand = min(len(player.hand) for player in self.players)
            for player in self.players:
                lands_kept = 0
                creatures_kept = 0
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "land":
                        if lands_kept < min_lands:
                            lands_kept += 1
                            survivors.append(permanent)
                        else:
                            player.graveyard.append(permanent.card)
                        continue
                    if permanent.card.primary_type == "creature":
                        if creatures_kept < min_creatures:
                            creatures_kept += 1
                            survivors.append(permanent)
                        else:
                            player.graveyard.append(permanent.card)
                        continue
                    survivors.append(permanent)
                player.battlefield = survivors
                while len(player.hand) > min_hand:
                    player.graveyard.append(player.hand.pop(0))
            self.log.append("Balance normalized lands, creatures, and hands")
            return True, "resolved"

        if instruction.kind == "grant_unlimited_blocking":
            blocker = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if blocker is not None:
                blocker.metadata["must_block_all_until_eot"] = True
            self.log.append(f"{card.name} created a forced blocking assignment")
            return True, "resolved"

        if instruction.kind == "randomize_blockers":
            self.log.append(f"{card.name} set up random pile blocking this turn")
            return True, "resolved"

        if instruction.kind == "remove_creature_from_combat":
            removed = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if removed is not None:
                removed.metadata["removed_from_combat"] = True
            self.log.append(f"{card.name} removed a blocker from combat")
            return True, "resolved"

        if instruction.kind == "left_right_combat_division":
            self.log.append(f"{card.name} established left/right combat division")
            return True, "resolved"

        if instruction.kind == "deal_damage":
            amount = instruction.payload.get("amount", 0)
            damage = max(0, x_value or 0) if amount == "x" else int(amount)
            damage = self._prevent_damage(target, damage)
            if damage > 0:
                target.life -= damage
            if source_permanent is not None:
                self.log.append(f"{card.name} dealt {damage} damage")
            else:
                self.log.append(f"{target.name} took {damage} damage")
            return True, "resolved"

        if instruction.kind == "deal_damage_and_self_damage":
            damage = self._prevent_damage(target, int(instruction.payload.get("amount", 0)))
            if damage > 0:
                target.life -= damage
            caster.life -= int(instruction.payload.get("self_damage", 0))
            self.log.append(f"{card.name} dealt {damage} damage and 3 self-damage")
            return True, "resolved"

        if instruction.kind == "reanimate_creature":
            reanimated = self._reanimate_creature_to_battlefield(caster)
            self.log.append("Reanimated creature to battlefield" if reanimated else "No creature to reanimate")
            return True, "resolved"

        if instruction.kind == "bounce_target_creature":
            bounced = self._bounce_target_creature(target)
            self.log.append("Returned creature to hand" if bounced else "No creature to return")
            return True, "resolved"

        if instruction.kind == "prevent_all_combat_damage":
            self.combat_damage_prevented_until_eot = True
            self.log.append("Combat damage prevented until end of turn")
            return True, "resolved"

        if instruction.kind == "wheel_of_fortune":
            for player in self.players:
                while player.hand:
                    player.graveyard.append(player.hand.pop(0))
                player.draw(7)
            self.log.append("Wheel effect resolved for all players")
            return True, "resolved"

        if instruction.kind == "timetwister":
            for player in self.players:
                pool = player.library + player.hand + player.graveyard
                player.library = list(pool)
                player.hand = []
                player.graveyard = []
                player.draw(7)
            self.log.append("Timetwister effect resolved for all players")
            return True, "resolved"

        if instruction.kind == "tutor_top_card":
            if caster.library:
                caster.hand.append(caster.library.pop(0))
            self.log.append(f"{caster.name} tutored a card")
            return True, "resolved"

        if instruction.kind == "grant_extra_turn":
            caster_index = self.players.index(caster)
            self.extra_turns[caster_index] = self.extra_turns.get(caster_index, 0) + 1
            self.log.append(f"{caster.name} gained an extra turn")
            return True, "resolved"

        if instruction.kind == "reorder_target_library_top":
            top = target.library[:3]
            rest = target.library[3:]
            target.library = list(reversed(top)) + rest
            self.log.append(f"{card.name} reordered top {len(top)} cards of {target.name}'s library")
            return True, "resolved"

        if instruction.kind == "mark_text_modified":
            if target.battlefield:
                target.battlefield[0].metadata["text_modified"] = True
            self.log.append(f"{card.name} applied a text change effect")
            return True, "resolved"

        if instruction.kind == "peek_hand_and_force_play":
            seen = len(target.hand)
            if target.hand:
                played = target.hand.pop(0)
                target.graveyard.append(played)
                self.log.append(f"{card.name} forced {target.name} to play {played.name}")
            else:
                self.log.append(f"{card.name} looked at {target.name}'s hand ({seen} cards)")
            return True, "resolved"

        if instruction.kind == "sacrifice_creature_for_black_mana":
            sacrificed = self._sacrifice_creature_for_mana(caster)
            if sacrificed is not None:
                caster.mana_pool["B"] += int(sacrificed.cmc)
                self.log.append(f"{caster.name} sacrificed {sacrificed.name} for {int(sacrificed.cmc)} black mana")
            else:
                self.log.append(f"{caster.name} had no creature to sacrifice")
            return True, "resolved"

        if instruction.kind == "recolor_target_from_text":
            changed = self._set_target_color(target, card.oracle_text)
            self.log.append("Changed target color" if changed else "No valid permanent to recolor")
            return True, "resolved"

        if instruction.kind == "destroy_all_creatures":
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "creature" and permanent.regeneration_shield > 0:
                        permanent.regeneration_shield -= 1
                        permanent.tapped = True
                        survivors.append(permanent)
                    elif permanent.card.primary_type == "creature":
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All creatures were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_all_lands":
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "land":
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All lands were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_target_permanent":
            oracle_text = str(instruction.payload.get("oracle_text", card.oracle_text))
            destroyed = self._destroy_target_permanent(target, oracle_text)
            if destroyed:
                if source_permanent is not None:
                    self.log.append(f"{card.name} destroyed {destroyed.name}")
                else:
                    self.log.append(f"Destroyed {destroyed.name}")
            else:
                self.log.append("No valid target permanent found")
            return True, "resolved"

        if instruction.kind == "return_creature_from_graveyard_to_hand":
            returned = self._return_creature_from_graveyard(caster)
            self.log.append("Returned creature from graveyard" if returned else "No creature to return")
            return True, "resolved"

        if instruction.kind == "discard_target_cards":
            actual = min(int(instruction.payload.get("amount", 0)), len(target.hand))
            for _ in range(actual):
                discarded = target.hand.pop(0)
                target.graveyard.append(discarded)
            self.log.append(f"{target.name} discarded {actual} cards")
            return True, "resolved"

        if instruction.kind == "target_loses_life":
            amount = int(instruction.payload.get("amount", 0))
            before = target.life
            target.life -= amount
            self.log.append(f"{card.name}: {target.name} lost {amount} life ({before} -> {target.life})")
            return True, "resolved"

        if instruction.kind == "target_gains_life":
            amount = instruction.payload.get("amount", 0)
            life_gain = max(0, x_value or 0) if amount == "x" else int(amount)
            before = target.life
            target.life += life_gain
            self.log.append(f"{card.name}: {target.name} gained {life_gain} life ({before} -> {target.life})")
            return True, "resolved"

        if instruction.kind == "untap_target_land":
            untapped = False
            for perm in target.battlefield:
                if perm.card.primary_type == "land":
                    perm.tapped = False
                    untapped = True
                    break
            self.log.append("Untapped target land" if untapped else "No land to untap")
            return True, "resolved"

        if instruction.kind == "untap_target_permanent":
            untapped = self._tap_or_untap_target(target, make_tapped=False)
            self.log.append("Untapped target permanent" if untapped else "No valid permanent to untap")
            return True, "resolved"

        if instruction.kind == "tap_target_permanent":
            tapped = self._tap_or_untap_target(target, make_tapped=True)
            self.log.append("Tapped target permanent" if tapped else "No valid permanent to tap")
            return True, "resolved"

        if instruction.kind == "grant_prevention_shield":
            amount = int(instruction.payload.get("amount", 0))
            recipient = target if source_permanent is not None else caster
            recipient.damage_prevention_pool += amount
            if source_permanent is not None and "would deal damage to you this turn" in card.oracle_text.lower():
                self.log.append("Color protection shield granted")
            elif source_permanent is not None:
                self.log.append("Prevention shield granted by activated ability")
            else:
                self.log.append(f"{caster.name} gains prevention shield for {amount} damage")
            return True, "resolved"

        if instruction.kind == "grant_forcefield_shield":
            caster.combat_damage_cap_one_charges += 1
            self.log.append("Forcefield shield granted")
            return True, "resolved"

        if instruction.kind == "grant_regeneration_to_target_creature":
            regenerated = self._grant_regeneration_shield(target)
            self.log.append("Regeneration shield granted" if regenerated else "No valid creature to regenerate")
            return True, "resolved"

        if instruction.kind == "grant_regeneration_to_self":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.regeneration_shield += 1
            self.log.append(f"{card.name} gains regeneration shield")
            return True, "resolved"

        if instruction.kind == "pump_self":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.power_bonus += int(instruction.payload.get("power", 0))
            source_permanent.toughness_bonus += int(instruction.payload.get("toughness", 0))
            self.log.append(
                f"{card.name} gets +{int(instruction.payload.get('power', 0))}/+{int(instruction.payload.get('toughness', 0))} until end of turn"
            )
            return True, "resolved"

        if instruction.kind == "grant_self_flying_until_eot":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["gains_flying_until_eot"] = True
            self.log.append(f"{card.name} gains flying until end of turn")
            return True, "resolved"

        if instruction.kind == "grant_banding_to_target":
            target_creature = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if target_creature is None:
                self.log.append("No valid creature target for banding effect")
                return False, "no valid creature target for banding effect"
            target_creature.metadata["gains_banding_until_eot"] = True
            self.log.append(f"{target_creature.card.name} gains banding until end of turn")
            return True, "resolved"

        if instruction.kind == "add_counter_to_self":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.power_bonus += int(instruction.payload.get("power", 0))
            source_permanent.toughness_bonus += int(instruction.payload.get("toughness", 0))
            self.log.append(f"{card.name} gets a +1/+1 counter")
            return True, "resolved"

        if instruction.kind == "sacrifice_self_for_mana":
            if source_permanent is None:
                return False, "ability not implemented"
            caster.mana_pool[str(instruction.payload.get("color", "G"))] += int(instruction.payload.get("amount", 0))
            caster.graveyard.append(source_permanent.card)
            caster.battlefield = [perm for perm in caster.battlefield if perm is not source_permanent]
            self.log.append(f"{card.name} sacrificed for mana")
            return True, "resolved"

        if instruction.kind == "draw_controller_cards":
            drawn = caster.draw(int(instruction.payload.get("amount", 0)))
            self.log.append(f"{card.name} drew {drawn} card")
            return True, "resolved"

        if instruction.kind == "grant_unblockable_to_low_power_target":
            target_creature = next(
                (perm for perm in target.battlefield if perm.card.primary_type == "creature" and perm.effective_power <= 2),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["cant_be_blocked_until_eot"] = True
                self.log.append(f"{target_creature.card.name} can't be blocked this turn")
            else:
                self.log.append("No valid low-power creature for unblockable effect")
            return True, "resolved"

        if instruction.kind == "change_target_land_type":
            target_land = next((perm for perm in target.battlefield if perm.card.primary_type == "land"), None)
            if target_land is not None:
                target_land.metadata["land_type_override"] = str(instruction.payload.get("land_type", "forest"))
                self.log.append(f"{target_land.card.name} became a Forest")
            else:
                self.log.append("No target land for Forest effect")
            return True, "resolved"

        if instruction.kind == "mark_non_wall_target_to_attack":
            target_creature = next(
                (
                    perm
                    for perm in target.battlefield
                    if perm.card.primary_type == "creature" and "wall" not in perm.card.type_line.lower()
                ),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["must_attack_until_eot"] = True
                target_creature.metadata["destroy_if_did_not_attack_eot"] = True
                self.log.append(f"{target_creature.card.name} marked to attack this turn")
            else:
                self.log.append("No non-Wall target for Nettling Imp effect")
            return True, "resolved"

        if instruction.kind == "grant_flying_and_delayed_destruction":
            if source_permanent is None:
                return False, "ability not implemented"
            target_creature = next(
                (
                    perm
                    for perm in caster.battlefield
                    if perm.card.primary_type == "creature" and perm.effective_toughness < source_permanent.effective_power
                ),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["gains_flying_until_eot"] = True
                target_creature.metadata["destroy_at_next_end_step"] = True
                self.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
            else:
                self.log.append("No valid target for Stone Giant effect")
            return True, "resolved"

        if instruction.kind == "redirect_one_damage_to_owner":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["redirect_one_damage_to_owner_until_eot"] = int(
                source_permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0)
            ) + 1
            self.log.append(f"{card.name} will redirect next 1 damage to its owner")
            return True, "resolved"

        if instruction.kind == "animate_self_until_end_of_combat":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["absolute_power"] = int(instruction.payload.get("power", 0))
            source_permanent.metadata["absolute_toughness"] = int(instruction.payload.get("toughness", 0))
            source_permanent.metadata["animate_until_end_of_combat"] = True
            self.log.append(f"{card.name} is animated until end of combat")
            return True, "resolved"

        if instruction.kind == "create_wasp_token":
            wasp = CardDefinition(
                name="Wasp",
                mana_cost="",
                cmc=0.0,
                type_line="Artifact Creature — Insect",
                oracle_text="Flying",
                colors=(),
                color_identity=(),
                keywords=("Flying",),
                produced_mana=(),
                raw={"name": "Wasp", "type_line": "Artifact Creature — Insect", "power": "1", "toughness": "1"},
            )
            caster.battlefield.append(Permanent(card=wasp))
            self.log.append(f"{card.name} created a Wasp token")
            return True, "resolved"

        if instruction.kind == "look_at_target_hand":
            seen = len(target.hand)
            self.log.append(f"{card.name} looked at {target.name}'s hand ({seen} cards)")
            return True, "resolved"

        if instruction.kind == "add_mire_counter_to_target_land":
            target_land = next(
                (
                    perm
                    for perm in target.battlefield
                    if perm.card.primary_type == "land"
                    and "swamp" not in perm.card.type_line.lower()
                ),
                None,
            )
            if target_land is not None:
                target_land.metadata["land_type_override"] = "swamp"
                target_land.metadata["mire_counter"] = True
                self.log.append(f"{target_land.card.name} became a Swamp due to mire counter")
            else:
                self.log.append("No valid non-Swamp land for mire counter")
            return True, "resolved"

        if instruction.kind == "add_mana_from_text":
            self._add_mana_from_text(caster, str(instruction.payload.get("oracle_text", card.oracle_text)))
            self.log.append(f"{card.name} produced mana")
            return True, "resolved"

        if instruction.kind == "counter_top_stack_spell":
            if self.stack:
                countered = self.stack.pop()
                self.players[countered.caster_index].graveyard.append(countered.card)
                self.log.append(f"{card.name} countered {countered.card.name}")
            else:
                self.log.append(f"{card.name} resolved with no spell to counter")
            return True, "resolved"

        self.log.append(f"Resolved supported pattern for {card.name} without state mutation")
        return True, "resolved"

    def _apply_spell_text(
        self,
        caster: PlayerState,
        target: PlayerState,
        card: CardDefinition,
        x_value: int | None = None,
    ) -> None:
        instruction = self._select_executable_instruction(card)
        if instruction is None:
            self.log.append(f"Resolved supported pattern for {card.name} without state mutation")
            return

        state_machine = OracleStateMachine(
            self,
            OracleExecutionContext(caster=caster, target=target, card=card, x_value=x_value),
        )
        state_machine.run(instruction)

    def _destroy_target_permanent(self, target: PlayerState, oracle_text: str) -> CardDefinition | None:
        lowered = oracle_text.lower()
        type_filter: str | None = None
        if "target creature" in lowered:
            type_filter = "creature"
        elif "target artifact" in lowered:
            type_filter = "artifact"
        elif "target enchantment" in lowered:
            type_filter = "enchantment"
        elif "target land" in lowered:
            type_filter = "land"

        color_filter: str | None = None
        for word, symbol in _COLOR_WORD_TO_SYMBOL.items():
            if f" {word} " in f" {lowered} ":
                color_filter = symbol
                break

        for idx, permanent in enumerate(target.battlefield):
            if type_filter and permanent.card.primary_type != type_filter:
                continue
            if color_filter and color_filter not in permanent.card.colors:
                continue
            removed = target.battlefield.pop(idx)
            target.graveyard.append(removed.card)
            return removed.card

        return None

    def _tap_or_untap_target(self, target: PlayerState, make_tapped: bool) -> bool:
        for permanent in target.battlefield:
            permanent.tapped = make_tapped
            return True
        return False

    def _grant_regeneration_shield(self, target: PlayerState) -> bool:
        for permanent in target.battlefield:
            if permanent.card.primary_type == "creature":
                permanent.regeneration_shield += 1
                return True
        return False

    def _prevent_damage(self, target: PlayerState, damage: int) -> int:
        if damage > 1 and target.combat_damage_cap_one_charges > 0:
            target.combat_damage_cap_one_charges -= 1
            damage = 1
        if damage <= 0 or target.damage_prevention_pool <= 0:
            return damage
        prevented = min(damage, target.damage_prevention_pool)
        target.damage_prevention_pool -= prevented
        return damage - prevented

    def _add_mana_from_text(self, controller: PlayerState, text: str) -> None:
        symbols = re.findall(r"\{([WUBRGC])\}", text.upper())
        if symbols:
            for symbol in symbols:
                controller.mana_pool[symbol] += 1
            return

        if "one mana of any color" in text:
            controller.mana_pool["G"] += 1

    def _return_creature_from_graveyard(self, caster: PlayerState) -> bool:
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                caster.hand.append(caster.graveyard.pop(idx))
                return True
        return False

    def _reanimate_creature_to_battlefield(self, caster: PlayerState) -> bool:
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                revived = caster.graveyard.pop(idx)
                caster.battlefield.append(Permanent(card=revived))
                return True
        return False

    def _bounce_target_creature(self, target: PlayerState) -> bool:
        for idx, permanent in enumerate(target.battlefield):
            if permanent.card.primary_type == "creature":
                target.hand.append(permanent.card)
                target.battlefield.pop(idx)
                return True
        return False

    def _sacrifice_creature_for_mana(self, caster: PlayerState) -> CardDefinition | None:
        for idx, permanent in enumerate(caster.battlefield):
            if permanent.card.primary_type == "creature":
                removed = caster.battlefield.pop(idx)
                caster.graveyard.append(removed.card)
                return removed.card
        return None

    def _set_target_color(self, target: PlayerState, text: str) -> bool:
        symbol = None
        for word, mapped in _COLOR_WORD_TO_SYMBOL.items():
            if f"becomes {word}" in text:
                symbol = mapped
                break
        if symbol is None:
            return False
        if target.battlefield:
            target.battlefield[0].metadata["color_override"] = symbol
            return True
        return False

    def resolve_upkeep(self, player_index: int) -> None:
        self.current_phase = "upkeep"
        for controller in self.players:
            for permanent in controller.battlefield:
                text = permanent.card.oracle_text.lower()
                if "at the beginning of your upkeep, sacrifice this enchantment unless you pay" in text:
                    # Simplified upkeep payment: pay from white mana pool if possible, otherwise sacrifice.
                    if controller.mana_pool.get("W", 0) >= 2:
                        controller.mana_pool["W"] -= 2
                        self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                    else:
                        controller.battlefield = [p for p in controller.battlefield if p is not permanent]
                        controller.graveyard.append(permanent.card)
                        self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")
                        continue

                if "at the beginning of the chosen player's upkeep" in text:
                    chosen = permanent.metadata.get("chosen_player_index")
                    if chosen != player_index:
                        continue
                    victim = self.players[player_index]
                    damage = max(0, len(victim.hand) - 4)
                    if damage > 0:
                        damage = self._prevent_damage(victim, damage)
                        if damage > 0:
                            victim.life -= damage
                    self.log.append(f"{permanent.card.name} dealt {damage} upkeep damage")

                if "at the beginning of your upkeep, this creature deals 8 damage to you unless you pay" in text:
                    if controller.mana_pool.get("G", 0) >= 4:
                        controller.mana_pool["G"] -= 4
                        self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                    else:
                        controller.life -= 8
                        self.log.append(f"{permanent.card.name} dealt 8 upkeep damage to {controller.name}")

                if "at the beginning of your upkeep, unless you pay {b}{b}{b}, tap this creature and sacrifice a land of an opponent's choice" in text:
                    if controller.mana_pool.get("B", 0) >= 3:
                        controller.mana_pool["B"] -= 3
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

                if "at the beginning of your upkeep, sacrifice a creature other than this creature" in text:
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
                        controller.life -= 7
                        self.log.append(f"{permanent.card.name} dealt 7 upkeep damage to {controller.name}")

                if "at the beginning of your upkeep, sacrifice this creature unless you pay {u}" in text:
                    if controller.mana_pool.get("U", 0) >= 1:
                        controller.mana_pool["U"] -= 1
                        self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                    else:
                        controller.battlefield = [p for p in controller.battlefield if p is not permanent]
                        controller.graveyard.append(permanent.card)
                        self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")
                        continue

                if "when you control no islands, sacrifice this creature" in text:
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
                        continue

    def _initialize_permanent_state(
        self,
        permanent: Permanent,
        caster_index: int,
        target_player_index: int | None,
    ) -> None:
        text = permanent.card.oracle_text.lower()
        if "as this artifact enters, choose an opponent" in text:
            chosen = target_player_index if target_player_index is not None else (1 - caster_index)
            permanent.metadata["chosen_player_index"] = chosen

        if "enters with seven +1/+0 counters on it" in text:
            permanent.power_bonus += 7

        if "enters with x +1/+1 counters on it" in text:
            # For X-cost creatures, use provided cast x_value when available.
            x_value = permanent.metadata.get("cast_x_value")
            if isinstance(x_value, int) and x_value > 0:
                permanent.power_bonus += x_value
                permanent.toughness_bonus += x_value

        if "you may have this creature enter as a copy of any creature on the battlefield" in text:
            source = next(
                (
                    perm
                    for player in self.players
                    for perm in player.battlefield
                    if perm is not permanent and perm.card.primary_type == "creature"
                ),
                None,
            )
            if source is not None:
                permanent.metadata["copied_from"] = source.card.name
                permanent.metadata["absolute_power"] = source.effective_power
                permanent.metadata["absolute_toughness"] = source.effective_toughness

        if "you may have this enchantment enter as a copy of any artifact on the battlefield" in text:
            source = next(
                (
                    perm
                    for player in self.players
                    for perm in player.battlefield
                    if perm is not permanent and perm.card.primary_type == "artifact"
                ),
                None,
            )
            if source is not None:
                permanent.metadata["copied_from"] = source.card.name
                if "power" in source.card.raw and str(source.card.raw.get("power", "")).isdigit():
                    permanent.metadata["absolute_power"] = source.effective_power
                if "toughness" in source.card.raw and str(source.card.raw.get("toughness", "")).isdigit():
                    permanent.metadata["absolute_toughness"] = source.effective_toughness

        if "you have no maximum hand size" in text:
            self.players[caster_index].has_no_max_hand_size = True

        if "you may spend white mana as though it were red mana" in text:
            self.players[caster_index].can_spend_white_as_red = True

    def _apply_cast_triggers(self, caster_index: int, card: CardDefinition) -> None:
        if card.primary_type != "enchantment":
            return

        caster = self.players[caster_index]
        for permanent in caster.battlefield:
            if permanent.card.name == "Verduran Enchantress":
                drawn = caster.draw(1)
                self.log.append(f"Verduran Enchantress trigger: {caster.name} drew {drawn} card")

    def _refresh_dynamic_creatures(self) -> None:
        all_permanents = [perm for player in self.players for perm in player.battlefield]
        kormus_active = any(perm.card.name == "Kormus Bell" for perm in all_permanents)
        living_lands_active = any(perm.card.name == "Living Lands" for perm in all_permanents)

        for player in self.players:
            non_wall_creatures = sum(
                1
                for perm in player.battlefield
                if perm.card.primary_type == "creature" and "wall" not in perm.card.type_line.lower()
            )
            swamp_count = sum(
                1
                for perm in player.battlefield
                if "swamp" in perm.card.type_line.lower() or perm.metadata.get("land_type_override") == "swamp"
            )
            plague_rats_total = sum(
                1 for p in self.players for perm in p.battlefield if perm.card.name == "Plague Rats"
            )

            for permanent in player.battlefield:
                text = permanent.card.oracle_text.lower()
                if "keldon warlord's power and toughness are each equal to the number of non-wall creatures you control" in text:
                    permanent.metadata["absolute_power"] = non_wall_creatures
                    permanent.metadata["absolute_toughness"] = non_wall_creatures

                if "plague rats's power and toughness are each equal to the number of creatures named plague rats on the battlefield" in text:
                    permanent.metadata["absolute_power"] = plague_rats_total
                    permanent.metadata["absolute_toughness"] = plague_rats_total

                if "nightmare's power and toughness are each equal to the number of swamps you control" in text:
                    permanent.metadata["absolute_power"] = swamp_count
                    permanent.metadata["absolute_toughness"] = swamp_count

                if "gets +1/+1 as long as you control a swamp" in text:
                    previous = int(permanent.metadata.get("conditional_swamp_bonus", 0))
                    if previous:
                        permanent.power_bonus -= previous
                        permanent.toughness_bonus -= previous
                    current = 1 if swamp_count > 0 else 0
                    if current:
                        permanent.power_bonus += current
                        permanent.toughness_bonus += current
                    permanent.metadata["conditional_swamp_bonus"] = current

                if kormus_active and "swamp" in permanent.card.type_line.lower() and permanent.card.primary_type == "land":
                    permanent.metadata["land_animated"] = True
                    permanent.metadata["absolute_power"] = 1
                    permanent.metadata["absolute_toughness"] = 1
                    permanent.metadata["color_override"] = "B"

                if living_lands_active and "forest" in permanent.card.type_line.lower() and permanent.card.primary_type == "land":
                    permanent.metadata["land_animated"] = True
                    permanent.metadata["absolute_power"] = 1
                    permanent.metadata["absolute_toughness"] = 1

    def can_attack(self, attacker: Permanent, defending_player_index: int) -> bool:
        text = attacker.card.oracle_text.lower()
        if "can't attack unless defending player controls an island" in text:
            defending = self.players[defending_player_index]
            has_island = any("island" in perm.card.type_line.lower() for perm in defending.battlefield)
            return has_island

        if "defender" in text and not attacker.metadata.get("can_attack_as_though_no_defender"):
            return False
        return True

    def resolve_draw_step(self, player_index: int) -> int:
        self.current_phase = "draw"
        player = self.players[player_index]
        bonus = 0
        for controller in self.players:
            for permanent in controller.battlefield:
                if permanent.card.name == "Howling Mine" and not permanent.tapped:
                    bonus += 1
        drawn = player.draw(1 + bonus)
        self.log.append(f"{player.name} drew {drawn} card(s) in draw step")
        return drawn

    def resolve_untap_step(self, player_index: int) -> int:
        self.current_phase = "untap"
        player = self.players[player_index]
        all_permanents = [perm for pl in self.players for perm in pl.battlefield]

        if any(perm.card.name == "Stasis" for perm in all_permanents):
            self.log.append(f"{player.name} skipped untap due to Stasis")
            return 0

        max_untap_creatures = 999
        if any(perm.card.name == "Smoke" for perm in all_permanents):
            max_untap_creatures = 1

        max_untap_lands = 999
        if any(perm.card.name == "Winter Orb" and not perm.tapped for perm in all_permanents):
            max_untap_lands = 1

        meekstone_active = any(perm.card.name == "Meekstone" for perm in all_permanents)

        untapped = 0
        creatures_untapped = 0
        lands_untapped = 0
        for permanent in player.battlefield:
            if not permanent.tapped:
                continue

            if permanent.card.primary_type == "creature":
                if meekstone_active and permanent.effective_power >= 3:
                    continue
                if creatures_untapped >= max_untap_creatures:
                    continue
                creatures_untapped += 1

            if permanent.card.primary_type == "land":
                if lands_untapped >= max_untap_lands:
                    continue
                lands_untapped += 1

            permanent.tapped = False
            untapped += 1

        self.log.append(f"{player.name} untapped {untapped} permanent(s)")
        return untapped

    def tap_land_for_mana(
        self,
        player_index: int,
        land_name: str,
        chosen_color: str = "G",
        permanent_index: int | None = None,
    ) -> bool:
        player = self.players[player_index]
        resolved = self._find_controlled_permanent(player, land_name, permanent_index)
        land = resolved[1] if resolved else None
        if land is not None and land.card.primary_type != "land":
            land = None
        if land is None or land.tapped:
            return False

        land.tapped = True
        mana_symbol = chosen_color
        if land.card.produced_mana:
            mana_symbol = land.card.produced_mana[0]
        else:
            land_types = [str(land.metadata.get("land_type_override", "")).lower(), land.card.type_line.lower()]
            if any("plains" in value for value in land_types):
                mana_symbol = "W"
            elif any("island" in value for value in land_types):
                mana_symbol = "U"
            elif any("swamp" in value for value in land_types):
                mana_symbol = "B"
            elif any("mountain" in value for value in land_types):
                mana_symbol = "R"
            elif any("forest" in value for value in land_types):
                mana_symbol = "G"
        player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1

        all_permanents = [perm for pl in self.players for perm in pl.battlefield]
        if any(perm.card.name == "Mana Flare" for perm in all_permanents):
            player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1

        self.log.append(f"{player.name} tapped {land_name} for mana")
        return True

    def end_combat(self) -> None:
        for player in self.players:
            for permanent in player.battlefield:
                if permanent.metadata.get("animate_until_end_of_combat"):
                    permanent.metadata.pop("animate_until_end_of_combat", None)
                    permanent.metadata.pop("absolute_power", None)
                    permanent.metadata.pop("absolute_toughness", None)
        self.combat_damage_prevented_until_eot = False
        for player in self.players:
            player.combat_damage_cap_one_charges = 0

    def _process_land_enters(self, land_controller_index: int) -> None:
        for controller in self.players:
            for permanent in controller.battlefield:
                text = permanent.card.oracle_text.lower()
                if "whenever a land enters" not in text:
                    continue
                victim = self.players[land_controller_index]
                damage = self._prevent_damage(victim, 2)
                if damage > 0:
                    victim.life -= damage
                self.log.append(f"{permanent.card.name} triggered for {damage} damage")

    def _apply_global_buff(self, caster: PlayerState, source: CardDefinition) -> None:
        text = source.oracle_text.lower().strip()
        if "all swamps are 1/1 black creatures that are still lands" in text:
            self._refresh_dynamic_creatures()
            return

        if "all forests are 1/1 creatures that are still lands" in text:
            self._refresh_dynamic_creatures()
            return

        if "attacking creatures you control get +1/+0" in text:
            for permanent in caster.battlefield:
                if permanent.card.primary_type == "creature":
                    permanent.power_bonus += 1
            return

        if "untapped creatures you control get +0/+2" in text:
            for permanent in caster.battlefield:
                if permanent.card.primary_type == "creature" and not permanent.tapped:
                    permanent.toughness_bonus += 2
            return

        match = re.search(r"(white|blue|black|red|green)?\s*creatures(?: you control)? get \+(\d+)/\+(\d+)", text)
        if not match:
            return

        color_word, power_inc, toughness_inc = match.groups()
        color_symbol = _COLOR_WORD_TO_SYMBOL.get(color_word) if color_word else None
        power_bonus = int(power_inc)
        toughness_bonus = int(toughness_inc)

        target_players = [caster]
        if "you control" not in text:
            target_players = self.players

        for player in target_players:
            for permanent in player.battlefield:
                if permanent.card.primary_type != "creature":
                    continue
                if color_symbol and color_symbol not in permanent.card.colors:
                    continue
                permanent.power_bonus += power_bonus
                permanent.toughness_bonus += toughness_bonus

    def _apply_aura_effect(
        self,
        caster_index: int,
        aura_permanent: Permanent,
        target_player_index: int | None,
    ) -> None:
        text = aura_permanent.card.oracle_text.lower()
        if not text.startswith("enchant "):
            return

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target_player = self.players[target_idx]

        if text.startswith("enchant creature"):
            target_creature = next(
                (perm for perm in target_player.battlefield if perm.card.primary_type == "creature"),
                None,
            )
            if not target_creature:
                return

            buff_match = re.search(r"gets \+(-?\d+)/\+(-?\d+)", text)
            if buff_match:
                target_creature.power_bonus += int(buff_match.group(1))
                target_creature.toughness_bonus += int(buff_match.group(2))

            if "has " in text and "walk" in text:
                self.log.append(f"{target_creature.card.name} gains landwalk from {aura_permanent.card.name}")

            if "has protection from" in text:
                self.log.append(f"{target_creature.card.name} gains protection from aura")

        elif text.startswith("enchant land"):
            self.log.append(f"{aura_permanent.card.name} enchants a land (mana bonus handling is simplified)")
        elif text.startswith("enchant wall"):
            target_wall = next(
                (perm for perm in target_player.battlefield if "wall" in perm.card.type_line.lower()),
                None,
            )
            if target_wall:
                target_wall.metadata["can_attack_as_though_no_defender"] = True
                self.log.append(f"{target_wall.card.name} can attack as though it didn't have defender")
        elif text.startswith("enchant artifact"):
            self.log.append(f"{aura_permanent.card.name} enchants an artifact (complex behavior simplified)")

