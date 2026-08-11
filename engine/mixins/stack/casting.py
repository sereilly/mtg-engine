"""Casting a spell from hand (CR 601): put it on the stack, having chosen
targets, modes and X, and paid its cost.

Everything here runs *before* the spell resolves. ``cast_from_hand`` is the
entry point and ``queue_from_hand`` does the work; ``_validate_cast_targets`` is
the gate the UI's target enumerator also runs through
(``engine/legality.py``), so a target the picker offers is one resolution will
accept.

The Aura enchant-noun helpers live here because an Aura chooses what it attaches
to as it is cast. ``engine/targeting.py`` answers the same question from the
compiled program and the two share a vocabulary deliberately — see its
``enchant_line_subject``.
"""

from __future__ import annotations

import re

from ...cast_restrictions import check_cast_timing
from ...classifier import classify_card
from ...cost_modifiers import spell_cost_tax
from ...game_types import SimulationResult, StackItem
from ...handlers._common import permanent_matches_filter
from ...models import CardDefinition, Permanent, PlayerState
from ...oracle import _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ...oracle_types import x_spend_color_from_text

# Maps an "enchant X" noun to a predicate matching legal battlefield targets.
# "creature" uses Permanent.is_creature so animated lands (Kormus Bell / Living
# Lands) accept creature Auras while they are creatures.
_ENCHANT_TARGET_MATCHERS = {
    "artifact": lambda perm: perm.has_type("artifact"),
    "creature": lambda perm: perm.is_creature,
    "land": lambda perm: perm.card.primary_type == "land",
    "enchantment": lambda perm: perm.has_type("enchantment"),
    "wall": lambda perm: perm.has_type("wall"),
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


class SpellCastingMixin:
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
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
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
            old_color=old_color,
            divided_targets=divided_targets,
        )
        if not queued.supported:
            return queued

        # Resolve the spell, then drain any triggers it (or the deaths it causes)
        # put on the stack, interleaving state-based-action checks (CR 704.3/603.3).
        self._settle()
        self.clear_priority_window()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")
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
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
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
            if not self._may_play_another_land(caster_index):
                details = "already played a land this turn"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        banning_card = self._set_lockout_banning_card(card)
        if banning_card is not None:
            details = f"can't cast or play {card.name}: banned by {banning_card}"
            self.log.append(details)
            return SimulationResult(card.name, False, classification.effect_kind, details)

        spell_tax, taxing_names = spell_cost_tax(self, caster_index, card)
        if spell_tax:
            extra_generic_tax += spell_tax
            self.log.append(f"{card.name} is taxed by {', '.join(taxing_names)}")

        # Accept cards with supported triggered abilities (match classifier logic)
        if not classification.supported:
            if classification.reason == "unsupported triggered ability":
                # `compile_card_oracle` is imported at module level. The
                # function-level `from .oracle import ...` that stood here
                # resolved to `engine.mixins.stack.oracle`, which does not
                # exist — a leftover from the stack decomposition that raised
                # ModuleNotFoundError on every card reaching this branch.
                # Nothing caught it because it is only reachable for an
                # *unsupported* card, and every card in the pool was supported
                # until M21 arrived with 33 of them.
                program = compile_card_oracle(card)
                if any(getattr(program, "triggered_abilities", ())):
                    if any(t.supported for t in program.triggered_abilities):
                        return SimulationResult(card.name, True, program.effect_kind, "supported triggered ability")
            self.log.append(f"Unsupported card: {card.name} ({classification.reason})")
            return SimulationResult(card.name, False, classification.effect_kind, classification.reason)

        timing_denial = check_cast_timing(self, caster_index, card.oracle_text.lower())
        if timing_denial is not None:
            self.log.append(timing_denial)
            return SimulationResult(card.name, False, classification.effect_kind, timing_denial)

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

        # A divided spell's cross-seat target list: sanity-check every entry so a
        # stale battlefield index can't crash resolution.
        if divided_targets is not None:
            cleaned: list[tuple[int, int | None]] = []
            for entry in divided_targets:
                seat, index = entry
                if not (isinstance(seat, int) and 0 <= seat < len(self.players)):
                    return SimulationResult(card.name, False, classification.effect_kind, "invalid divided target seat")
                if index is not None and not (
                    isinstance(index, int) and 0 <= index < len(self.players[seat].battlefield)
                ):
                    return SimulationResult(card.name, False, classification.effect_kind, "invalid divided target")
                cleaned.append((seat, index))
            divided_targets = cleaned or None

        # Fireball-style spells cost {1} more to cast for each target beyond the
        # first. Count the chosen targets (the cross-seat divided list, a list of
        # creature indices, or a single creature/player) and tax the extras as
        # generic mana.
        if "costs {1} more to cast for each target beyond the first" in card.oracle_text.lower():
            if divided_targets is not None:
                num_targets = len(divided_targets)
            elif isinstance(target_permanent_index, list):
                num_targets = len([i for i in target_permanent_index if isinstance(i, int)])
            else:
                num_targets = 1
            extra_generic_tax += max(0, num_targets - 1)

        x_color = x_spend_color_from_text(card.oracle_text)
        resolved_x_value = x_value
        if resolved_x_value is None and "{X}" in card.mana_cost.upper():
            resolved_x_value = self._infer_x_value(caster, card.mana_cost, extra_generic_tax, x_color=x_color)

        if self.enforce_mana_costs and card.primary_type != "land":
            # CR 118.6: an object with no mana cost (as opposed to {0}) has an
            # unpayable cost — attempting to cast it is illegal.
            if not card.mana_cost.strip():
                details = f"{card.name} has no mana cost; the cost is unpayable (CR 118.6)"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)
            cost = self._parse_mana_cost(
                card.mana_cost, x_value=resolved_x_value, extra_generic=extra_generic_tax, x_color=x_color
            )
            if not self._pay_mana_cost(
                caster, cost, creature_spell=card.primary_type == "creature"
            ):
                details = f"insufficient mana for {card.name}"
                if x_color is not None:
                    details = f"insufficient mana for {card.name} (X can be paid only with {x_color} mana)"
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
            self._stack_push(
                StackItem(
                    card=card,
                    caster_index=caster_index,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    x_value=resolved_x_value,
                    target_stack_item=target_stack_item_val,
                    chosen_mode_index=mode_index,
                    choices={
                        "divided_targets": divided_targets,
                        "new_color": new_color,
                        "old_color": old_color,
                    },
                )
            )
            self.log.append(f"{card.name} added to stack")
            # "Whenever a player casts a [color] spell" triggers (Rod/Cup/Sphere)
            # and "whenever you cast an X spell" triggers (Verduran Enchantress)
            # fire now, as the spell is put on the stack, and go on the stack above
            # it (CR 603.3) — so the trigger resolves while the triggering spell is
            # still on the stack, not after it has already resolved.
            self._apply_spell_cast_any_triggers(caster_index, card)
            self._apply_cast_triggers(caster_index, card)
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
    def _destroy_target_legal(self, payload: dict, perm: Permanent) -> bool:
        """Whether *perm* satisfies a ``destroy_target_permanent`` instruction's
        target filters (type/subtype/colour/tapped + exclusions). Shared by cast
        validation and the legality enumerator so a destroy ability (Royal
        Assassin's "target tapped creature", Northern Paladin's "target black
        permanent") offers exactly the permanents it can legally destroy."""
        return permanent_matches_filter(perm, payload)
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
                    if self._cant_be_enchanted(battlefield[target_permanent_index]):
                        return False, f"{battlefield[target_permanent_index].card.name} can't be enchanted by other Auras"
                    # CR 702.16b/c: an Aura with a quality can't be cast targeting a
                    # permanent with protection from that quality (or hexproof
                    # from an opponent's side, CR 702.11b).
                    if not self._can_be_targeted(
                        battlefield[target_permanent_index], card, caster_index=caster_index
                    ):
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
            if chosen.is_creature and not self._can_be_targeted(
                chosen, card, caster_index=caster_index
            ):
                return False, f"{chosen.card.name} is an illegal target for {card.name}"

        if primary.kind == "destroy_target_permanent":
            if isinstance(target_permanent_index, int):
                # A specific target was chosen — it must itself be legal (601.2c).
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or not self._destroy_target_legal(
                    primary.payload, battlefield[target_permanent_index]
                ):
                    return False, f"no valid target for {card.name}"
            else:
                # No specific choice: destruction can target a permanent controlled
                # by anyone, so a legal target on the caster's own battlefield (e.g.
                # Disenchant on one's own artifact) is enough to make the cast legal.
                has_target = any(
                    self._destroy_target_legal(primary.payload, p)
                    for p in self.all_permanents()
                )
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
                if color_filter and color_filter not in self._stack_item_colors(target_stack_item):
                    return False, f"no valid target for {card.name}"
            elif color_filter and not any(color_filter in self._stack_item_colors(item) for item in self.stack):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "bounce_target_creature":
            # "Return target creature to its owner's hand" (Unsummon) can target a
            # creature controlled by ANY player. When a specific target is chosen it
            # must itself be a creature; otherwise any creature on any battlefield
            # makes the cast legal.
            if isinstance(target_permanent_index, int):
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or (
                    not battlefield[target_permanent_index].is_creature
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(p.is_creature for p in self.all_permanents()):
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
            blocking_only = bool(primary.payload.get("blocking_only"))

            def _legal_pump_target(p) -> bool:
                if not p.is_creature:
                    return False
                # Righteousness only targets a creature that is currently blocking.
                if blocking_only and not self._is_blocking_creature(p):
                    return False
                return True

            if isinstance(target_permanent_index, int):
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or not _legal_pump_target(
                    battlefield[target_permanent_index]
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(_legal_pump_target(p) for p in self.all_permanents()):
                return False, f"no valid target for {card.name}"

        elif primary.kind in ("tap_target_permanent", "untap_target_permanent"):
            if not target.battlefield:
                return False, f"no valid target for {card.name}"

        elif primary.kind == "recolor_target_from_text":
            # "Target spell or permanent becomes [color]" (the Lace cards). A spell
            # on the stack is a legal target, as is any permanent on any battlefield.
            if target_stack_item is not None:
                if target_stack_item not in self.stack:
                    return False, f"no valid target for {card.name}"
            else:
                any_target = bool(self.stack) or any(p.battlefield for p in self.players)
                if not any_target:
                    return False, f"no valid target for {card.name}"

        elif primary.kind in (
            "return_creature_from_graveyard_to_hand",
            "reanimate_creature_to_battlefield",
            "reanimate_creature",
        ):
            # Raise Dead / Resurrection target a creature card in *your* graveyard,
            # so an opponent's graveyard is never a legal target. Regrowth targets
            # "target card" — any type (any_card in the parsed payload). Only
            # enforce the ownership/index check when the caster made an explicit
            # graveyard pick; an untargeted cast just needs a legal card there.
            caster = self.players[caster_index]
            any_card = bool(primary.payload.get("any_card"))
            if isinstance(target_permanent_index, int):
                if target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                if not (0 <= target_permanent_index < len(caster.graveyard)) or (
                    not any_card
                    and caster.graveyard[target_permanent_index].primary_type != "creature"
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(
                any_card or c.primary_type == "creature" for c in caster.graveyard
            ):
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
                    not battlefield[target_permanent_index].is_creature
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(p.is_creature for p in self.controlled_by(caster)):
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
    def _infer_x_value(
        self, player: PlayerState, mana_cost: str, extra_generic: int = 0, x_color: str | None = None
    ) -> int:
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

        if x_color in {"W", "U", "B", "R", "G", "C"}:
            # X may only be paid in one color: reserve it by covering the generic
            # part from the other colors first.
            other_available = available_generic - max(0, temp.get(x_color, 0))
            generic_from_x_color = max(0, required["generic"] - other_available)
            return max(0, temp.get(x_color, 0) - generic_from_x_color)

        return available_generic - required["generic"]
    def _parse_mana_cost(
        self, mana_cost: str, x_value: int | None, extra_generic: int = 0, x_color: str | None = None
    ) -> dict[str, int]:
        required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": max(0, extra_generic)}
        if not mana_cost:
            return required

        for token in re.findall(r"\{([^}]+)\}", mana_cost.upper()):
            if token.isdigit():
                required["generic"] += int(token)
                continue
            if token == "X":
                # "Spend only black mana on X" (Drain Life): the X portion is a
                # colored requirement, not generic payable from anything.
                if x_color in {"W", "U", "B", "R", "G", "C"}:
                    required[x_color] += max(0, x_value or 0)
                else:
                    required["generic"] += max(0, x_value or 0)
                continue
            if token in {"W", "U", "B", "R", "G", "C"}:
                required[token] += 1
        return required
    def _pay_mana_cost(
        self, player: PlayerState, required: dict[str, int], *, creature_spell: bool = False
    ) -> bool:
        # Metamorphosis: mana restricted to creature spells joins the pool for
        # a creature-spell payment only, and whatever the payment consumes is
        # attributed to the restricted bucket first (its units are otherwise
        # lost, so spending them first is the only rational attribution).
        restricted = player.creature_only_mana
        if creature_spell and restricted and any(restricted.values()):
            snapshot = dict(player.mana_pool)
            player.mana_pool = {
                sym: snapshot.get(sym, 0) + restricted.get(sym, 0)
                for sym in ("W", "U", "B", "R", "G", "C")
            }
            if not self._pay_mana_cost(player, required):
                player.mana_pool = snapshot
                return False
            for sym in ("W", "U", "B", "R", "G", "C"):
                spent = snapshot.get(sym, 0) + restricted.get(sym, 0) - player.mana_pool.get(sym, 0)
                from_restricted = min(spent, restricted.get(sym, 0))
                if from_restricted:
                    restricted[sym] = restricted.get(sym, 0) - from_restricted
                snapshot[sym] = snapshot.get(sym, 0) - (spent - from_restricted)
            player.mana_pool = snapshot
            return True
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
