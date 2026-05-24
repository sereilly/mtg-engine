from __future__ import annotations

import re
from dataclasses import dataclass, field

from .classifier import CardClassification, classify_card
from .models import CardDefinition, Permanent, PlayerState


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
class Game:
    players: list[PlayerState]
    turn: int = 1
    stack: list[StackItem] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

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
    ) -> SimulationResult:
        controller = self.players[controller_index]
        permanent = next((p for p in controller.battlefield if p.card.name == permanent_name), None)
        if permanent is None:
            raise ValueError(f"Permanent not found: {permanent_name}")

        text = permanent.card.oracle_text.lower()
        target_idx = target_player_index if target_player_index is not None else (1 - controller_index)
        target_player = self.players[target_idx]

        if "{t}" in text:
            permanent.tapped = True

        if "deals 1 damage to any target" in text:
            damage = self._prevent_damage(target_player, 1)
            if damage > 0:
                target_player.life -= damage
            self.log.append(f"{permanent.card.name} dealt {damage} damage")
            return SimulationResult(permanent.card.name, True, "activated_damage", "resolved")

        if "deals 2 damage to any target and 3 damage to you" in text:
            damage = self._prevent_damage(target_player, 2)
            if damage > 0:
                target_player.life -= damage
            controller.life -= 3
            self.log.append(f"{permanent.card.name} dealt {damage} damage and 3 self-damage")
            return SimulationResult(permanent.card.name, True, "activated_damage", "resolved")

        if "destroy target" in text:
            destroyed = self._destroy_target_permanent(target_player, text)
            if destroyed:
                self.log.append(f"{permanent.card.name} destroyed {destroyed.name}")
            return SimulationResult(permanent.card.name, True, "activated_destroy", "resolved")

        if "untap target land" in text:
            untapped = False
            for perm in target_player.battlefield:
                if perm.card.primary_type == "land":
                    perm.tapped = False
                    untapped = True
                    break
            self.log.append("Untapped target land" if untapped else "No land to untap")
            return SimulationResult(permanent.card.name, True, "activated_untap", "resolved")

        if "prevent the next 1 damage" in text:
            target_player.damage_prevention_pool += 1
            self.log.append("Prevention shield granted by activated ability")
            return SimulationResult(permanent.card.name, True, "activated_prevent", "resolved")

        if "regenerate this creature" in text:
            permanent.regeneration_shield += 1
            self.log.append(f"{permanent.card.name} gains regeneration shield")
            return SimulationResult(permanent.card.name, True, "activated_regenerate", "resolved")

        if "add three mana of any one color" in text:
            controller.mana_pool["G"] += 3
            controller.graveyard.append(permanent.card)
            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
            self.log.append(f"{permanent.card.name} sacrificed for mana")
            return SimulationResult(permanent.card.name, True, "activated_mana", "resolved")

        if "add {" in text:
            self._add_mana_from_text(controller, text)
            self.log.append(f"{permanent.card.name} produced mana")
            return SimulationResult(permanent.card.name, True, "activated_mana", "resolved")

        self.log.append(f"No implemented activated ability for {permanent.card.name}")
        return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")

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

        card = caster.hand.pop(hand_index)
        classification = classify_card(card)

        if not classification.supported:
            caster.hand.append(card)
            self.log.append(f"Unsupported card: {card.name} ({classification.reason})")
            return SimulationResult(card.name, False, classification.effect_kind, classification.reason)

        if card.primary_type in {"instant", "sorcery"}:
            self.stack.append(
                StackItem(
                    card=card,
                    caster_index=caster_index,
                    target_player_index=target_player_index,
                    x_value=x_value,
                )
            )
            self.log.append(f"{card.name} added to stack")
            return SimulationResult(card.name, True, classification.effect_kind, "queued")

        self._resolve_card(
            caster_index=caster_index,
            card=card,
            classification=classification,
            target_player_index=target_player_index,
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")

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
            caster.battlefield.append(permanent)
            self._initialize_permanent_state(permanent, caster_index, target_player_index)
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            self._apply_aura_effect(caster_index, permanent, target_player_index)
            if primary_type == "land":
                self._process_land_enters(caster_index)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target = self.players[target_idx]

        if "counter target spell" in card.oracle_text.lower():
            if self.stack:
                countered = self.stack.pop()
                self.players[countered.caster_index].graveyard.append(countered.card)
                self.log.append(f"{card.name} countered {countered.card.name}")
            else:
                self.log.append(f"{card.name} resolved with no spell to counter")
        else:
            self._apply_spell_text(caster, target, card, x_value=x_value)
        caster.graveyard.append(card)
        self.log.append(f"{card.name} resolved and moved to graveyard")

    def _apply_spell_text(
        self,
        caster: PlayerState,
        target: PlayerState,
        card: CardDefinition,
        x_value: int | None = None,
    ) -> None:
        text = card.oracle_text.lower()

        if "target player draws x cards" in text:
            count = max(0, x_value or 0)
            drawn = target.draw(count)
            self.log.append(f"{target.name} drew {drawn} cards")
            return

        draw_match = re.search(r"target player draws (\w+) cards?", text)
        if draw_match:
            token = draw_match.group(1)
            count = _NUMBER_WORDS.get(token, 0)
            if token.isdigit():
                count = int(token)
            if count > 0:
                drawn = target.draw(count)
                self.log.append(f"{target.name} drew {drawn} cards")
                return

        if "deals x damage" in text:
            damage = max(0, x_value or 0)
            damage = self._prevent_damage(target, damage)
            if damage > 0:
                target.life -= damage
            self.log.append(f"{target.name} took {damage} damage")
            return

        dmg_match = re.search(r"deals (\d+) damage", text)
        if dmg_match:
            damage = int(dmg_match.group(1))
            damage = self._prevent_damage(target, damage)
            if damage > 0:
                target.life -= damage
            self.log.append(f"{target.name} took {damage} damage")
            return

        if "from your graveyard to the battlefield" in text or "from a graveyard onto the battlefield" in text:
            reanimated = self._reanimate_creature_to_battlefield(caster)
            self.log.append("Reanimated creature to battlefield" if reanimated else "No creature to reanimate")
            return

        if "destroy all creatures" in text:
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
            return

        if "destroy all lands" in text:
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "land":
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All lands were destroyed")
            return

        if "destroy target" in text:
            destroyed = self._destroy_target_permanent(target, text)
            if destroyed:
                self.log.append(f"Destroyed {destroyed.name}")
            else:
                self.log.append("No valid target permanent found")
            return

        if "from your graveyard to your hand" in text:
            returned = self._return_creature_from_graveyard(caster)
            self.log.append("Returned creature from graveyard" if returned else "No creature to return")
            return

        discard_match = re.search(r"target player discards (\w+) cards?", text)
        if discard_match:
            token = discard_match.group(1)
            count = _NUMBER_WORDS.get(token, 0)
            if token.isdigit():
                count = int(token)
            actual = min(count, len(target.hand))
            for _ in range(actual):
                discarded = target.hand.pop(0)
                target.graveyard.append(discarded)
            self.log.append(f"{target.name} discarded {actual} cards")
            return

        lose_life_match = re.search(r"target player loses (\d+) life", text)
        if lose_life_match:
            amount = int(lose_life_match.group(1))
            target.life -= amount
            self.log.append(f"{target.name} lost {amount} life")
            return

        if "untap target" in text:
            untapped = self._tap_or_untap_target(target, make_tapped=False)
            self.log.append("Untapped target permanent" if untapped else "No valid permanent to untap")
            return

        if "tap target" in text:
            tapped = self._tap_or_untap_target(target, make_tapped=True)
            self.log.append("Tapped target permanent" if tapped else "No valid permanent to tap")
            return

        prevent_match = re.search(r"prevent the next (\d+) damage", text)
        if prevent_match:
            amount = int(prevent_match.group(1))
            caster.damage_prevention_pool += amount
            self.log.append(f"{caster.name} gains prevention shield for {amount} damage")
            return

        if "regenerate target creature" in text:
            regenerated = self._grant_regeneration_shield(target)
            self.log.append("Regeneration shield granted" if regenerated else "No valid creature to regenerate")
            return

        if "gain" in text and "life" in text:
            gain_match = re.search(r"gain (\d+) life", text)
            if gain_match:
                amount = int(gain_match.group(1))
                caster.life += amount
                self.log.append(f"{caster.name} gained {amount} life")
                return

        # Pattern-supported but no deterministic action in MVP.
        self.log.append(f"Resolved supported pattern for {card.name} without state mutation")

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

    def resolve_upkeep(self, player_index: int) -> None:
        for controller in self.players:
            for permanent in controller.battlefield:
                text = permanent.card.oracle_text.lower()
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
        elif text.startswith("enchant artifact"):
            self.log.append(f"{aura_permanent.card.name} enchants an artifact (complex behavior simplified)")
