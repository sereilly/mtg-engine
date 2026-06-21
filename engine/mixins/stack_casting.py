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
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=x_value,
            new_color=new_color,
            target_stack_index=target_stack_index,
            mode_index=mode_index,
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
        target_permanent_index: int | None = None,
        target_stack_index: int | None = None,
        ability_index: int | None = None,
        x_value: int | None = None,
    ) -> SimulationResult:
        queued = self.queue_permanent_ability(
            controller_index,
            permanent_name,
            target_player_index=target_player_index,
            permanent_index=permanent_index,
            mana_color=mana_color,
            target_permanent_index=target_permanent_index,
            target_stack_index=target_stack_index,
            ability_index=ability_index,
            x_value=x_value,
        )
        if not queued.supported:
            return queued
        if queued.details == "queued":
            self.resolve_stack()
            self.check_state_based_actions()
            self.clear_priority_window()
            return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")
        return queued

    def activate_prevent_one_emblem(self, controller_index: int, emblem_index: int = 0) -> SimulationResult:
        """Activate a Guardian Angel emblem: pay {1} to prevent the next 1 damage to
        the emblem's stored target (the original spell's "that permanent or player").
        Repeatable while the emblem exists."""
        from ..handlers.prevention import apply_prevention_shield

        label = "Prevention Emblem"
        controller = self.players[controller_index]
        emblems = controller.prevent_one_damage_emblems
        if not (0 <= emblem_index < len(emblems)):
            return SimulationResult(label, False, "unsupported", "no prevention emblem available")
        entry = emblems[emblem_index]

        target_idx = entry.get("target_player_index")
        if target_idx is None or not (0 <= target_idx < len(self.players)):
            return SimulationResult(label, False, "unsupported", "emblem target is no longer valid")
        target_player = self.players[target_idx]
        target_perm_idx = entry.get("target_permanent_index")
        # "That permanent" — if the original creature target has left play, the
        # ability has no legal target and does nothing.
        if isinstance(target_perm_idx, int):
            if not (0 <= target_perm_idx < len(target_player.battlefield)
                    and target_player.battlefield[target_perm_idx].card.primary_type == "creature"):
                return SimulationResult(label, False, "unsupported", "emblem target is no longer in play")

        if self.enforce_mana_costs:
            required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 1}
            if not self._pay_mana_cost(controller, required):
                return SimulationResult(label, False, "unsupported", "insufficient mana to activate emblem")

        apply_prevention_shield(self, target_player, target_perm_idx, 1)
        return SimulationResult(label, True, "activated_prevent_one", "resolved")

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

    def confirm_reorder_library(self, caster_index: int, new_order: list, shuffle: bool = False) -> bool:
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
        # "You may have that player shuffle" (Natural Selection): only honored when
        # the effect allows it.
        if shuffle and pending.get("may_shuffle"):
            random.shuffle(target.library)
            self.log.append(f"{target.name}'s library was shuffled")
        else:
            self.log.append(f"Top {top_count} cards of {target.name}'s library reordered")
        self.pending_reorder_library = None
        return True

    def queue_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
        target_permanent_index: int | None = None,
        target_stack_index: int | None = None,
        ability_index: int | None = None,
        x_value: int | None = None,
    ) -> SimulationResult:
        controller = self.players[controller_index]
        resolved = self._find_controlled_permanent(controller, permanent_name, permanent_index)
        if resolved is None:
            raise ValueError(f"Permanent not found: {permanent_name}")
        _, permanent = resolved

        program = compile_card_oracle(permanent.card)
        target_idx = target_player_index if target_player_index is not None else (1 - controller_index)
        target_player = self.players[target_idx]

        # An explicitly chosen spell on the stack (e.g. Deathgrip: "{B}{B}: Counter
        # target green spell"). target_stack_index indexes self.stack (bottom-first).
        target_stack_item = None
        if target_stack_index is not None and 0 <= target_stack_index < len(self.stack):
            target_stack_item = self.stack[target_stack_index]



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
        elif ability_index is not None:
            # The caller chose which ability to activate (cards with more than one
            # activated ability, e.g. Rock Hydra's {R} prevention vs {R}{R}{R} pump).
            usable = [
                item
                for item in program.activated_abilities
                if item.supported and item.instruction is not None
            ]
            ability = usable[ability_index] if 0 <= ability_index < len(usable) else None
        else:
            ability = next((item for item in program.activated_abilities if item.supported and item.instruction is not None), None)

        if ability is None or ability.instruction is None:
            # Zombie Master grants other Zombies '{B}: Regenerate this permanent.'
            if permanent.metadata.get("granted_regen_ability"):
                permanent.regeneration_shield += 1
                self.log.append(f"{permanent.card.name} regenerates (ability granted by lord)")
                return SimulationResult(permanent.card.name, True, "activated_regenerate", "resolved")
            self.log.append(f"No implemented activated ability for {permanent.card.name}")
            return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")

        if ability.instruction.kind == "grant_banding_to_target":
            # Banding grants go to the controller's own creatures, not the opponent's.
            target_idx = controller_index
            target_player = self.players[target_idx]
            has_valid_target = any(perm.card.primary_type == "creature" for perm in target_player.battlefield)
            if not has_valid_target:
                details = "no valid creature target for banding effect"
                self.log.append("No valid creature target for banding effect")
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        if ability.instruction.kind == "counter_top_stack_spell":
            color_filter = ability.instruction.payload.get("color_filter")
            if target_stack_item is not None:
                # A specific spell was chosen — it must itself be a legal target.
                if target_stack_item not in self.stack or (
                    color_filter and color_filter not in (target_stack_item.card.colors or [])
                ):
                    details = f"no valid target for {permanent.card.name}"
                    self.log.append(details)
                    return SimulationResult(permanent.card.name, False, "unsupported", details)
            else:
                has_valid_target = any(
                    not color_filter or color_filter in (item.card.colors or [])
                    for item in self.stack
                )
                if not has_valid_target:
                    details = f"no valid target for {permanent.card.name}"
                    self.log.append(details)
                    return SimulationResult(permanent.card.name, False, "unsupported", details)

        # Scavenging Ghoul: 'Remove a corpse counter from this creature: Regenerate
        # this creature.' — the counter removal is the activation cost.
        if (
            ability.instruction.kind == "grant_regeneration_to_self"
            and "remove a corpse counter from this creature" in program.normalized_text
        ):
            corpse_counters = int(permanent.metadata.get("corpse_counters", 0))
            if corpse_counters <= 0:
                details = f"{permanent.card.name} has no corpse counters to remove"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            permanent.metadata["corpse_counters"] = corpse_counters - 1

        # "Activate only during your upkeep." (Cyclopean Tomb, the Clockwork
        # creatures). The ability is legal only while it's the controller's own
        # upkeep step.
        if "activate only during your upkeep" in permanent.card.oracle_text.lower():
            if not (self.current_step == "upkeep" and self.active_player_index == controller_index):
                details = f"{permanent.card.name} can only be activated during your upkeep"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        required_cost = dict(ability.cost.mana)
        requires_tap = ability.cost.requires_tap
        # Abilities with an "{X}" in their cost (e.g. Clockwork Beast's
        # "{X}, {T}: Put up to X +1/+0 counters") charge X generic mana on top of
        # the printed symbols, where X is the amount the player chose.
        if x_value and "{x}" in (ability.source_line or "").lower():
            required_cost["generic"] = required_cost.get("generic", 0) + int(x_value)
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
                target_permanent_index=target_permanent_index,
                x_value=x_value,
                ability_instruction=instruction,
                ability_effect_kind=ability.effect_kind,
                source_permanent=permanent,
                ability_text=ability.source_line,
                target_stack_item=target_stack_item,
                target_stack_name=target_stack_item.card.name if target_stack_item is not None else None,
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
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
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

        if "cast this spell only during the declare blockers step" in card.oracle_text.lower():
            if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
                details = "can only be cast during the declare blockers step"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        if "cast this spell only during an opponent's turn, before attackers are declared" in card.oracle_text.lower():
            if self.current_turn_phase == "combat":
                before_attackers = (
                    self.current_step in ("beginning_of_combat", "declare_attackers")
                    and not self.combat_attackers_locked
                )
            else:
                before_attackers = self.current_turn_phase in ("beginning", "precombat_main")
            if self.active_player_index == caster_index or not before_attackers:
                details = "can only be cast during an opponent's turn, before attackers are declared"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        # Resolve an explicitly chosen target spell on the stack (Counterspell,
        # Fork). target_stack_index indexes into self.stack (bottom-first).
        target_stack_item = None
        if target_stack_index is not None and 0 <= target_stack_index < len(self.stack):
            target_stack_item = self.stack[target_stack_index]

        target_ok, target_reason = self._validate_cast_targets(
            card, caster_index, target_player_index, target_permanent_index, target_stack_item,
            mode_index=mode_index,
        )
        if not target_ok:
            self.log.append(target_reason)
            return SimulationResult(card.name, False, classification.effect_kind, target_reason)

        # Fireball-style spells cost {1} more to cast for each target beyond the
        # first. Count the chosen targets (a list of creature indices, or a
        # single creature/player) and tax the extras as generic mana.
        if "costs {1} more to cast for each target beyond the first" in card.oracle_text.lower():
            if isinstance(target_permanent_index, list):
                num_targets = len([i for i in target_permanent_index if isinstance(i, int)])
            else:
                num_targets = 1
            extra_generic_tax += max(0, num_targets - 1)

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
            # Determine which stack spell this one targets. An explicit choice
            # (target_stack_item) wins; otherwise fall back to the topmost legal
            # spell so AI and untargeted casts still work.
            target_stack_item_val = target_stack_item
            if target_stack_item_val is None and self.stack and "counter target" in card.oracle_text.lower():
                color_match = re.search(r"counter target (\w+) spell", card.oracle_text.lower())
                color_filter: str | None = None
                if color_match:
                    color_filter = _COLOR_WORD_TO_SYMBOL.get(color_match.group(1))
                matching = [it for it in self.stack if not color_filter or color_filter in it.card.colors]
                if matching:
                    target_stack_item_val = matching[-1]
            target_stack_name_val = target_stack_item_val.card.name if target_stack_item_val is not None else None
            self.stack.append(
                StackItem(
                    card=card,
                    caster_index=caster_index,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    x_value=resolved_x_value,
                    target_stack_name=target_stack_name_val,
                    target_stack_item=target_stack_item_val,
                    new_color=new_color,
                    chosen_mode_index=mode_index,
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
        target_stack_item=None,
        mode_index: int | None = None,
    ) -> tuple[bool, str]:
        """Return (True, 'valid') if all required targets exist, else (False, reason).

        Only instants and sorceries execute effects at cast time; permanents enter
        the battlefield regardless of whether their activated abilities have targets.

        For a "Choose one —" modal spell, the chosen mode's instruction (not the
        first one) determines what the spell targets.
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
                    # A permanent that "can't be enchanted by other Auras" (Consecrate
                    # Land) is an illegal target for any other Aura spell.
                    if battlefield[target_permanent_index].metadata.get("cant_be_enchanted_by_auras"):
                        return False, f"{battlefield[target_permanent_index].card.name} can't be enchanted by other Auras"
                    # CR 702.16b/c: an Aura with a quality can't be cast targeting a
                    # permanent with protection from that quality.
                    if not self._can_be_targeted(battlefield[target_permanent_index], card):
                        return False, f"no valid target for {card.name}"
                else:
                    first_line = card.oracle_text.lower().split("\n")[0].strip()
                    if first_line.startswith("enchant ") and "graveyard" in first_line:
                        # e.g. "enchant creature card in a graveyard" (Animate Dead).
                        # If the player chose a specific graveyard card, validate that
                        # choice; otherwise require at least one legal creature card.
                        if isinstance(target_permanent_index, int):
                            gy_idx = target_player_index if target_player_index is not None else caster_index
                            if gy_idx < 0 or gy_idx >= len(self.players):
                                gy_idx = caster_index
                            graveyard = self.players[gy_idx].graveyard
                            if not (0 <= target_permanent_index < len(graveyard)) or (
                                graveyard[target_permanent_index].primary_type != "creature"
                            ):
                                return False, f"no valid target for {card.name}"
                        else:
                            has_target = any(
                                c.primary_type == "creature"
                                for player in self.players
                                for c in player.graveyard
                            )
                            if not has_target:
                                return False, f"no valid target for {card.name}"
            return True, "valid"

        program = compile_card_oracle(card)
        if (
            mode_index is not None
            and program.modes
            and 0 <= mode_index < len(program.modes)
            and program.modes[mode_index].instruction is not None
        ):
            primary = program.modes[mode_index].instruction
        else:
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

        # CR 702.16b: a spell can't be cast targeting a creature with protection
        # from the spell's quality (or with shroud). Reject the illegal target at
        # cast time, mirroring the resolution-time check, so it is never offered.
        if isinstance(target_permanent_index, int) and 0 <= target_permanent_index < len(target.battlefield):
            chosen = target.battlefield[target_permanent_index]
            if chosen.card.primary_type == "creature" and not self._can_be_targeted(chosen, card):
                return False, f"{chosen.card.name} is an illegal target for {card.name}"

        if primary.kind == "destroy_target_permanent":
            type_filter = primary.payload.get("type_filter")
            color_filter = primary.payload.get("color_filter")
            subtype_filter = primary.payload.get("subtype_filter")
            tapped_only = primary.payload.get("tapped_only", False)
            exclude_colors = primary.payload.get("exclude_colors") or []
            exclude_types = primary.payload.get("exclude_types") or []

            def _type_matches(p, tf):
                if not tf:
                    return True
                if tf == "artifact_or_enchantment":
                    return p.card.primary_type in ("artifact", "enchantment")
                return tf in p.card.type_line.lower()

            def _is_legal(p):
                if not _type_matches(p, type_filter):
                    return False
                if subtype_filter and subtype_filter not in p.card.type_line.lower():
                    return False
                if tapped_only and not p.tapped:
                    return False
                if color_filter and color_filter not in p.card.colors:
                    return False
                if exclude_colors and any(c in p.card.colors for c in exclude_colors):
                    return False
                if exclude_types and any(t in p.card.type_line.lower() for t in exclude_types):
                    return False
                return True

            if isinstance(target_permanent_index, int):
                # A specific target was chosen — it must itself be legal (601.2c).
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or not _is_legal(
                    battlefield[target_permanent_index]
                ):
                    return False, f"no valid target for {card.name}"
            else:
                # No specific choice: destruction can target a permanent controlled
                # by anyone, so a legal target on the caster's own battlefield (e.g.
                # Disenchant on one's own artifact) is enough to make the cast legal.
                has_target = any(_is_legal(p) for pl in self.players for p in pl.battlefield)
                if not has_target:
                    return False, f"no valid target for {card.name}"

        elif primary.kind == "counter_top_stack_spell":
            color_filter = primary.payload.get("color_filter")
            if not self.stack:
                return False, f"no valid target for {card.name}"
            if target_stack_item is not None:
                # A specific spell was chosen — it must itself be a legal target.
                if target_stack_item not in self.stack:
                    return False, f"no valid target for {card.name}"
                if color_filter and color_filter not in target_stack_item.card.colors:
                    return False, f"no valid target for {card.name}"
            elif color_filter and not any(color_filter in item.card.colors for item in self.stack):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "bounce_target_creature":
            # "Return target creature to its owner's hand" (Unsummon) can target a
            # creature controlled by ANY player. When a specific target is chosen it
            # must itself be a creature; otherwise any creature on any battlefield
            # makes the cast legal.
            if isinstance(target_permanent_index, int):
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or (
                    battlefield[target_permanent_index].card.primary_type != "creature"
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(
                p.card.primary_type == "creature"
                for pl in self.players
                for p in pl.battlefield
            ):
                return False, f"no valid target for {card.name}"

        elif primary.kind in (
            "pump_target_creature_until_eot",
            "grant_target_flying_until_eot",
            "grant_regeneration_to_target_creature",
            "berserk_pump",
            "grant_unlimited_blocking",
            "exile_target_creature_until_eot",
            "exile_creature_gain_life_equal_to_power",
        ):
            # These spells can target a creature controlled by ANY player (Death
            # Ward regenerates your own creature; Swords to Plowshares exiles any
            # creature). A specific choice must itself be a creature; otherwise any
            # creature on any battlefield makes the cast legal.
            if isinstance(target_permanent_index, int):
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or (
                    battlefield[target_permanent_index].card.primary_type != "creature"
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(
                p.card.primary_type == "creature"
                for pl in self.players
                for p in pl.battlefield
            ):
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

        elif primary.kind == "simulacrum_redirect":
            # Simulacrum deals damage to "target creature you control" — only a
            # creature the caster controls is a legal target. A specific choice must
            # be one of the caster's creatures (targeting an opponent's creature is
            # illegal); with no explicit choice, the caster just needs one creature.
            caster = self.players[caster_index]
            if isinstance(target_permanent_index, int):
                if target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                battlefield = caster.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or (
                    battlefield[target_permanent_index].card.primary_type != "creature"
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(p.card.primary_type == "creature" for p in caster.battlefield):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "copy_top_stack_spell":
            # Fork copies a target instant or sorcery spell, so it requires one on
            # the stack (excluding Fork itself, which isn't on the stack yet).
            if target_stack_item is not None:
                if target_stack_item not in self.stack or target_stack_item.card.primary_type not in ("instant", "sorcery"):
                    return False, f"no valid target for {card.name}"
            elif not any(item.card.primary_type in ("instant", "sorcery") for item in self.stack):
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
                    stack_target=item.target_stack_item,
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
            new_color=item.new_color,
            stack_target=item.target_stack_item,
            chosen_mode_index=item.chosen_mode_index,
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
        new_color: str | None = None,
        stack_target=None,
        chosen_mode_index: int | None = None,
    ) -> None:
        caster = self.players[caster_index]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment"}:
            permanent = Permanent(card=card)
            if x_value is not None:
                permanent.metadata["cast_x_value"] = x_value
            # A "copy as it enters" permanent (Clone) records the chosen copy
            # target so initialization can copy the player-selected creature
            # rather than an arbitrary one.
            if target_permanent_index is not None:
                permanent.metadata["copy_target"] = (
                    target_player_index if target_player_index is not None else caster_index,
                    target_permanent_index,
                )
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
                            damage = self._deal_damage_to_player(caster, fastbond_count)
                            self.log.append(f"Fastbond dealt {damage} damage to {caster.name}")
                self._process_land_enters(caster_index)
            else:
                # A resolving permanent spell (creature/artifact/enchantment) is
                # still a spell that was cast, so it triggers "whenever a player
                # casts a [color] spell" effects like the Rod/Cup/Sphere cycle.
                self._apply_spell_resolved_triggers(caster_index, card)
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
            new_color=new_color,
            stack_target=stack_target,
            mode_index=chosen_mode_index,
        )
        self._apply_spell_resolved_triggers(caster_index, card)
        self._apply_self_resolved_hook(caster_index, card, target_idx, target_permanent_index)
        caster.graveyard.append(card)
        self.log.append(f"{card.name} resolved and moved to graveyard")

    def _select_executable_instruction(
        self, card: CardDefinition, mode_index: int | None = None
    ) -> OracleInstruction | None:
        program = compile_card_oracle(card)
        # A modal spell resolves the player's chosen mode; fall back to the first
        # instruction (mode 0) when no mode was chosen (e.g. AI casts).
        if mode_index is not None and program.modes and 0 <= mode_index < len(program.modes):
            mode = program.modes[mode_index]
            if mode.instruction is not None:
                return mode.instruction
        return next((instruction for instruction in program.instructions if instruction.kind != "spell_pattern"), None)
