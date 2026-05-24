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
    enforce_mana_costs: bool = False
    turn: int = 1
    current_phase: str = "main"
    lands_played_this_turn: dict[int, int] = field(default_factory=lambda: {0: 0, 1: 0})
    stack: list[StackItem] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    extra_turns: dict[int, int] = field(default_factory=dict)
    combat_damage_prevented_until_eot: bool = False

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

        if "this creature gets +1/+0 until end of turn" in text:
            permanent.power_bonus += 1
            self.log.append(f"{permanent.card.name} gets +1/+0 until end of turn")
            return SimulationResult(permanent.card.name, True, "activated_pump", "resolved")

        if "this creature gets +0/+1 until end of turn" in text:
            permanent.toughness_bonus += 1
            self.log.append(f"{permanent.card.name} gets +0/+1 until end of turn")
            return SimulationResult(permanent.card.name, True, "activated_pump", "resolved")

        if "this creature gets +1/+1 until end of turn" in text:
            permanent.power_bonus += 1
            permanent.toughness_bonus += 1
            self.log.append(f"{permanent.card.name} gets +1/+1 until end of turn")
            return SimulationResult(permanent.card.name, True, "activated_pump", "resolved")

        if "this creature gains flying until end of turn" in text:
            permanent.metadata["gains_flying_until_eot"] = True
            self.log.append(f"{permanent.card.name} gains flying until end of turn")
            return SimulationResult(permanent.card.name, True, "activated_keyword", "resolved")

        if "target creature gains banding until end of turn" in text:
            target_creature = next(
                (perm for perm in target_player.battlefield if perm.card.primary_type == "creature"),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["gains_banding_until_eot"] = True
                self.log.append(f"{target_creature.card.name} gains banding until end of turn")
            else:
                self.log.append("No valid creature target for banding effect")
            return SimulationResult(permanent.card.name, True, "activated_keyword", "resolved")

        if "put a +1/+1 counter on this creature" in text:
            permanent.power_bonus += 1
            permanent.toughness_bonus += 1
            self.log.append(f"{permanent.card.name} gets a +1/+1 counter")
            return SimulationResult(permanent.card.name, True, "activated_counter", "resolved")

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

        if "would deal damage to you this turn, prevent that damage" in text:
            target_player.damage_prevention_pool += 1
            self.log.append("Color protection shield granted")
            return SimulationResult(permanent.card.name, True, "activated_prevent", "resolved")

        if "the next time an unblocked creature of your choice would deal combat damage to you this turn, prevent all but 1 of that damage" in text:
            controller.combat_damage_cap_one_charges += 1
            self.log.append("Forcefield shield granted")
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

        if "draw a card" in text:
            drawn = controller.draw(1)
            self.log.append(f"{permanent.card.name} drew {drawn} card")
            return SimulationResult(permanent.card.name, True, "activated_draw", "resolved")

        if "target creature with power 2 or less can't be blocked this turn" in text:
            target_creature = next(
                (perm for perm in target_player.battlefield if perm.card.primary_type == "creature" and perm.effective_power <= 2),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["cant_be_blocked_until_eot"] = True
                self.log.append(f"{target_creature.card.name} can't be blocked this turn")
                return SimulationResult(permanent.card.name, True, "activated_evasion", "resolved")
            self.log.append("No valid low-power creature for unblockable effect")
            return SimulationResult(permanent.card.name, True, "activated_evasion", "resolved")

        if "target land becomes a forest" in text:
            target_land = next((perm for perm in target_player.battlefield if perm.card.primary_type == "land"), None)
            if target_land is not None:
                target_land.metadata["land_type_override"] = "forest"
                self.log.append(f"{target_land.card.name} became a Forest")
            else:
                self.log.append("No target land for Forest effect")
            return SimulationResult(permanent.card.name, True, "activated_landtype", "resolved")

        if "choose target non-wall creature" in text:
            target_creature = next(
                (
                    perm
                    for perm in target_player.battlefield
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
            return SimulationResult(permanent.card.name, True, "activated_combat", "resolved")

        if "target creature you control with toughness less than this creature's power gains flying until end of turn" in text:
            target_creature = next(
                (
                    perm
                    for perm in controller.battlefield
                    if perm.card.primary_type == "creature" and perm.effective_toughness < permanent.effective_power
                ),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["gains_flying_until_eot"] = True
                target_creature.metadata["destroy_at_next_end_step"] = True
                self.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
            else:
                self.log.append("No valid target for Stone Giant effect")
            return SimulationResult(permanent.card.name, True, "activated_keyword", "resolved")

        if "the next 1 damage that would be dealt to this creature this turn is dealt to its owner instead" in text:
            permanent.metadata["redirect_one_damage_to_owner_until_eot"] = int(
                permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0)
            ) + 1
            self.log.append(f"{permanent.card.name} will redirect next 1 damage to its owner")
            return SimulationResult(permanent.card.name, True, "activated_prevent", "resolved")

        if "this artifact becomes a 3/6 golem artifact creature until end of combat" in text:
            permanent.metadata["absolute_power"] = 3
            permanent.metadata["absolute_toughness"] = 6
            permanent.metadata["animate_until_end_of_combat"] = True
            self.log.append(f"{permanent.card.name} is animated until end of combat")
            return SimulationResult(permanent.card.name, True, "activated_animate", "resolved")

        if "create a 1/1 colorless insect artifact creature token with flying named wasp" in text:
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
            controller.battlefield.append(Permanent(card=wasp))
            self.log.append(f"{permanent.card.name} created a Wasp token")
            return SimulationResult(permanent.card.name, True, "activated_token", "resolved")

        if "look at target player's hand" in text:
            seen = len(target_player.hand)
            self.log.append(f"{permanent.card.name} looked at {target_player.name}'s hand ({seen} cards)")
            return SimulationResult(permanent.card.name, True, "activated_look", "resolved")

        if "put a mire counter on target non-swamp land" in text:
            target_land = next(
                (
                    perm
                    for perm in target_player.battlefield
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
            return SimulationResult(permanent.card.name, True, "activated_landtype", "resolved")

        if "add {" in text:
            self._add_mana_from_text(controller, text)
            self.log.append(f"{permanent.card.name} produced mana")
            return SimulationResult(permanent.card.name, True, "activated_mana", "resolved")

        self.log.append(f"No implemented activated ability for {permanent.card.name}")
        return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")

    def tap_permanent(self, controller_index: int, permanent_name: str) -> bool:
        controller = self.players[controller_index]
        permanent = next((p for p in controller.battlefield if p.card.name == permanent_name), None)
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

        if self.enforce_mana_costs and card.primary_type != "land":
            cost = self._parse_mana_cost(card.mana_cost, x_value=x_value, extra_generic=extra_generic_tax)
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
            x_value=x_value,
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")

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

        temp = dict(pool)
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

        if "discard your hand, ante the top card of your library, then draw seven cards" in text:
            while caster.hand:
                caster.graveyard.append(caster.hand.pop(0))
            if caster.library:
                caster.graveyard.append(caster.library.pop(0))
            drawn = caster.draw(7)
            self.log.append(f"{card.name} resolved: discarded hand and drew {drawn} cards")
            return

        if "each player antes the top card of their library" in text:
            anted = 0
            for player in self.players:
                if player.library:
                    player.graveyard.append(player.library.pop(0))
                    anted += 1
            self.log.append(f"{card.name} anted {anted} card(s) in simplified model")
            return

        if "you own target card in the ante. exchange that card with the top card of your library" in text:
            if caster.library:
                caster.graveyard.append(caster.library.pop(0))
                self.log.append(f"{card.name} exchanged top library card with simulated ante zone")
            else:
                self.log.append(f"{card.name} resolved with no library card to exchange")
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

        if "copy target instant or sorcery spell" in text:
            if self.stack:
                copied = self.stack[-1]
                self._apply_spell_text(caster, target, copied.card, x_value=copied.x_value)
                self.log.append(f"{card.name} copied {copied.card.name}")
            else:
                self.log.append(f"{card.name} resolved with no spell to copy")
            return

        if "each player chooses a number of lands they control equal to the number of lands controlled by the player who controls the fewest" in text:
            min_lands = min(
                sum(1 for perm in player.battlefield if perm.card.primary_type == "land")
                for player in self.players
            )
            min_creatures = min(
                sum(1 for perm in player.battlefield if perm.card.primary_type == "creature")
                for player in self.players
            )
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
            return

        if "target creature defending player controls can block any number of creatures this turn" in text:
            blocker = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if blocker is not None:
                blocker.metadata["must_block_all_until_eot"] = True
            self.log.append(f"{card.name} created a forced blocking assignment")
            return

        if "this turn, instead of declaring blockers" in text:
            self.log.append(f"{card.name} set up random pile blocking this turn")
            return

        if "remove target creature defending player controls from combat" in text:
            removed = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if removed is not None:
                removed.metadata["removed_from_combat"] = True
            self.log.append(f"{card.name} removed a blocker from combat")
            return

        if "whenever one or more creatures you control attack, each defending player divides all creatures without flying" in text:
            self.log.append(f"{card.name} established left/right combat division")
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

        if "return target creature to its owner's hand" in text:
            bounced = self._bounce_target_creature(target)
            self.log.append("Returned creature to hand" if bounced else "No creature to return")
            return

        if "prevent all combat damage that would be dealt this turn" in text:
            self.combat_damage_prevented_until_eot = True
            self.log.append("Combat damage prevented until end of turn")
            return

        if "each player discards their hand, then draws seven cards" in text:
            for player in self.players:
                while player.hand:
                    player.graveyard.append(player.hand.pop(0))
                player.draw(7)
            self.log.append("Wheel effect resolved for all players")
            return

        if "each player shuffles their hand and graveyard into their library, then draws seven cards" in text:
            for player in self.players:
                pool = player.library + player.hand + player.graveyard
                player.library = list(pool)
                player.hand = []
                player.graveyard = []
                player.draw(7)
            self.log.append("Timetwister effect resolved for all players")
            return

        if "search your library for a card, put that card into your hand, then shuffle" in text:
            if caster.library:
                caster.hand.append(caster.library.pop(0))
            self.log.append(f"{caster.name} tutored a card")
            return

        if "take an extra turn after this one" in text:
            caster_index = self.players.index(caster)
            self.extra_turns[caster_index] = self.extra_turns.get(caster_index, 0) + 1
            self.log.append(f"{caster.name} gained an extra turn")
            return

        if "look at the top three cards of target player's library, then put them back in any order" in text:
            top = target.library[:3]
            rest = target.library[3:]
            target.library = list(reversed(top)) + rest
            self.log.append(f"{card.name} reordered top {len(top)} cards of {target.name}'s library")
            return

        if "change the text of target spell or permanent by replacing all instances of one basic land type with another" in text:
            if target.battlefield:
                target.battlefield[0].metadata["text_modified"] = True
            self.log.append(f"{card.name} applied a text change effect")
            return

        if "change the text of target spell or permanent by replacing all instances of one color word with another" in text:
            if target.battlefield:
                target.battlefield[0].metadata["text_modified"] = True
            self.log.append(f"{card.name} applied a text change effect")
            return

        if "look at target opponent's hand and choose a card from it" in text:
            seen = len(target.hand)
            if target.hand:
                played = target.hand.pop(0)
                target.graveyard.append(played)
                self.log.append(f"{card.name} forced {target.name} to play {played.name}")
                return
            self.log.append(f"{card.name} looked at {target.name}'s hand ({seen} cards)")
            return

        if "as an additional cost to cast this spell, sacrifice a creature" in text:
            sacrificed = self._sacrifice_creature_for_mana(caster)
            if sacrificed is not None:
                caster.mana_pool["B"] += int(sacrificed.cmc)
                self.log.append(f"{caster.name} sacrificed {sacrificed.name} for {int(sacrificed.cmc)} black mana")
            else:
                self.log.append(f"{caster.name} had no creature to sacrifice")
            return

        if "becomes red" in text or "becomes black" in text or "becomes blue" in text or "becomes green" in text or "becomes white" in text:
            changed = self._set_target_color(target, text)
            self.log.append("Changed target color" if changed else "No valid permanent to recolor")
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

    def tap_land_for_mana(self, player_index: int, land_name: str, chosen_color: str = "G") -> bool:
        player = self.players[player_index]
        land = next((perm for perm in player.battlefield if perm.card.name == land_name and perm.card.primary_type == "land"), None)
        if land is None or land.tapped:
            return False

        land.tapped = True
        mana_symbol = chosen_color
        if land.card.produced_mana:
            mana_symbol = land.card.produced_mana[0]
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

