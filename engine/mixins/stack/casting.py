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

from ...cast_permissions import consume as consume_permission, permission_for
from ...auras import aura_enchant_clause
from ...cast_costs import AdditionalCost, additional_costs
from ...cast_restrictions import check_cast_timing
from ...classifier import classify_card
from ...cost_modifiers import (
    CostReduction, cost_reduction_for_cast, reduce_cost, spell_cost_tax,
    spell_life_tax,
)
from ...game_types import SimulationResult, StackItem
from ...handlers._common import graveyard_card_matches, permanent_matches_filter
from ...models import CardDefinition, Permanent, PlayerState
from ...oracle import _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ...oracle_types import x_spend_color_from_text
from ...targeting import graveyard_target_spec
from ...subject_filters import filter_head_noun, subject_matches
from ...targeting import derive_cast_spec

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

    The enchant line is *found*, not assumed to be the first one. Every Aura in
    the shipped pool prints it first, so reading line 0 was right until Capture
    Sphere printed "Flash" above it — and the failure was silent in the worst
    way: the Aura resolved, entered the battlefield, and attached to nothing.
    """
    if "Aura" not in card.type_line:
        return None
    for raw_line in card.oracle_text.lower().split("\n"):
        line = re.sub(r"\([^)]*\)", "", raw_line).strip()  # drop reminder text
        if not line.startswith("enchant "):
            continue
        noun = line[len("enchant "):].strip()
        return None if "graveyard" in noun else noun
    return None


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
        # The chosen targets' stable ids, when the caller already knows them.
        # A pair of targets may sit on two battlefields, which one
        # `target_player_index` cannot express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        from_zone: str = "hand",
        use_free_permission: bool | None = None,
        # Which permanent / which card in hand pays a printed additional cost
        # (CR 601.2b). The same shape `activate_permanent_ability` takes, and
        # for the same reason: the payer chooses, a cost is paid *during*
        # casting, and a queued prompt would put the spell on the stack before
        # its cost was collected. A seat that names neither gets the
        # deterministic pick, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        cost_hand_index: int | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            x_value=x_value,
            new_color=new_color,
            target_stack_index=target_stack_index,
            mode_index=mode_index,
            old_color=old_color,
            divided_targets=divided_targets,
            from_zone=from_zone,
            use_free_permission=use_free_permission,
            cost_permanent_index=cost_permanent_index,
            cost_hand_index=cost_hand_index,
        )
        if not queued.supported:
            return queued

        # Resolve the spell, then drain any triggers it (or the deaths it causes)
        # put on the stack, interleaving state-based-action checks (CR 704.3/603.3).
        self._settle()
        self.clear_priority_window()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")
    def queue_from_hand(self, *args, **kwargs) -> SimulationResult:
        """Cast a spell — CR 601, start to finish — leaving it on the stack.

        A wrapper around the whole process for one reason, and the reason is the
        wrapper's shape: **everything CR 601.2 describes is one announcement**,
        and a trigger that fires part-way through it waits for the end of that
        announcement rather than going on the stack in the middle. Goremand
        sacrifices a creature to be cast; Havoc Jester's answer to that belongs
        *above* the Demon, not under it. See ``deferring_triggers``.
        """
        with self.deferring_triggers():
            return self._cast_onto_stack(*args, **kwargs)

    def _cast_onto_stack(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them.
        # A pair of targets may sit on two battlefields, which one
        # `target_player_index` cannot express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        from_zone: str = "hand",
        use_free_permission: bool | None = None,
        # Which permanent / which card in hand pays a printed additional cost
        # (CR 601.2b). The same shape `activate_permanent_ability` takes, and
        # for the same reason: the payer chooses, a cost is paid *during*
        # casting, and a queued prompt would put the spell on the stack before
        # its cost was collected. A seat that names neither gets the
        # deterministic pick, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        cost_hand_index: int | None = None,
    ) -> SimulationResult:
        caster = self.players[caster_index]
        # Casting from the hand is a rule; casting from anywhere else is an
        # effect (CR 601.3), asked of the permission seam. The lookup prefers a
        # covered occurrence so a duplicate without permission cannot shadow
        # the copy that has it.
        permission = None
        if from_zone == "hand":
            source_zone = caster.hand
            try:
                hand_index = next(i for i, card in enumerate(caster.hand) if card.name == card_name)
            except StopIteration as exc:
                raise ValueError(f"Card not in hand: {card_name}") from exc
        else:
            if from_zone not in ("graveyard", "exile"):
                raise ValueError(f"cannot cast from {from_zone!r}")
            source_zone = getattr(caster, from_zone)
            hand_index = None
            for i, candidate in enumerate(source_zone):
                if candidate.name != card_name:
                    continue
                if hand_index is None:
                    hand_index = i
                grant = permission_for(
                    self, caster_index, candidate, from_zone,
                    as_land=candidate.primary_type == "land",
                )
                if grant is not None:
                    hand_index, permission = i, grant
                    break
            if hand_index is None:
                raise ValueError(f"Card not in {from_zone}: {card_name}")
            if permission is None:
                details = (
                    f"no effect allows playing {card_name} from "
                    f"{caster.name}'s {from_zone} (CR 601.3)"
                )
                self.log.append(details)
                return SimulationResult(
                    card_name, False,
                    classify_card(source_zone[hand_index]).effect_kind, details,
                )

        card = source_zone[hand_index]
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

        # "…that target this creature cost an additional 3 life to cast."
        # (Terror of the Peaks.) A tax in life rather than mana, scoped to what
        # the spell *targets* — so it is charged here, where the chosen targets
        # are known (CR 601.2c chooses them before 601.2h pays), and refused
        # rather than clamped when the caster cannot pay: CR 118.4 makes an
        # unpayable cost an uncastable spell, not a free one.
        aimed_at = [
            found
            for found in (
                self.permanent_by_id(pid)
                for pid in (target_permanent_ids or [])
                if isinstance(pid, int)
            )
            if found is not None
        ]
        if not aimed_at and target_permanent_index is not None:
            found = self.permanent_at(
                target_player_index
                if target_player_index is not None else caster_index,
                target_permanent_index,
            )
            if found is not None:
                aimed_at = [found]
        life_tax, life_taxing_names = spell_life_tax(self, caster_index, aimed_at)
        if life_tax:
            if caster.life < life_tax:
                details = (
                    f"{caster.name} cannot pay {life_tax} life to cast {card.name} "
                    f"({', '.join(life_taxing_names)})"
                )
                self.log.append(details)
                return SimulationResult(
                    card.name, False, classification.effect_kind, details
                )
            caster.life -= life_tax
            self.log.append(
                f"{caster.name} paid {life_tax} life to cast {card.name} "
                f"({', '.join(life_taxing_names)})"
            )

        # CR 601.2f: increases first, then reductions.
        cost_reduction, reducing_names = cost_reduction_for_cast(self, caster_index, card)
        if cost_reduction:
            self.log.append(f"{card.name} costs less to cast ({', '.join(reducing_names)})")

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

        # A printed additional cost (CR 601.2b). Checked here, before a single
        # mana is spent: CR 601.2h says an unpayable cost can't be paid, and the
        # consequence is that the spell can't be cast at all — not that it is
        # cast for free, which is what happened while the phrase lived in the
        # spell-pattern whitelist. Paid further down, once every other cost has
        # cleared and the card itself has left the hand.
        cast_costs = additional_costs(card)
        unpayable = self._unpayable_additional_cost(
            caster_index, card, cast_costs, spell_hand_index=hand_index,
            from_zone=from_zone,
        )
        if unpayable is not None:
            self.log.append(unpayable)
            return SimulationResult(card.name, False, classification.effect_kind, unpayable)

        # Resolve the named discard **here**, while `cost_hand_index` still
        # indexes the hand the caster was looking at. The spell leaves that hand
        # further down, and every card after it slides up a slot — so an index
        # read afterwards names the neighbour, and one past the shortened end
        # fell through to a bare `0` and discarded the *first* card in hand. A
        # cast that names a card it cannot pay with is refused rather than
        # silently repointed, before any mana is spent.
        cost_hand_card, cost_denial = self._resolve_discard_cost_card(
            caster_index, card, cast_costs,
            cost_hand_index=cost_hand_index,
            spell_hand_index=hand_index if from_zone == "hand" else None,
        )
        if cost_denial is not None:
            self.log.append(cost_denial)
            return SimulationResult(card.name, False, classification.effect_kind, cost_denial)

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
            resolved_x_value = self._infer_x_value(
                caster, card.mana_cost, extra_generic_tax, x_color=x_color,
                reduction=cost_reduction,
            )

        # A cost waiver ("cast spells from your hand without paying their mana
        # costs", Chandra, Flame's Catalyst's −8). An X spell defaults to
        # *paying*, because a waived {X} is locked to 0 (CR 107.3b) and paying
        # for X=5 usually beats a free X=0 — an explicit request wins either way.
        free_grant = permission if (permission is not None and permission.free) else None
        if (
            free_grant is None
            and card.primary_type != "land"
            and use_free_permission is not False
            and (use_free_permission or "{X}" not in card.mana_cost.upper())
        ):
            waiver = permission_for(self, caster_index, card, "hand")
            if waiver is not None and from_zone == "hand":
                free_grant = waiver
                if permission is None:
                    permission = waiver
        if free_grant is not None and card.primary_type != "land":
            if "{X}" in card.mana_cost.upper():
                resolved_x_value = 0  # CR 107.3b: the only legal choice for X
            self.log.append(
                f"{card.name} cast without paying its mana cost"
                + (f" ({free_grant.source_name})" if free_grant.source_name else "")
            )
        elif self.enforce_mana_costs and card.primary_type != "land":
            # CR 118.6: an object with no mana cost (as opposed to {0}) has an
            # unpayable cost — attempting to cast it is illegal. (118.6a: a
            # waiver above is an alternative cost and may still be paid.)
            if not card.mana_cost.strip():
                details = f"{card.name} has no mana cost; the cost is unpayable (CR 118.6)"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)
            cost = reduce_cost(
                self._parse_mana_cost(
                    card.mana_cost, x_value=resolved_x_value,
                    extra_generic=extra_generic_tax, x_color=x_color,
                ),
                cost_reduction,
            )
            if not self._pay_mana_cost(
                caster, cost, spell=card
            ):
                details = f"insufficient mana for {card.name}"
                if x_color is not None:
                    details = f"insufficient mana for {card.name} (X can be paid only with {x_color} mana)"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        card = source_zone.pop(hand_index)
        # Now, and not before: the spell is no longer in the hand, so it cannot
        # be discarded to pay for itself, and the creature it eats is gone from
        # the battlefield before the spell is on the stack.
        sacrificed_for_cost = self._pay_additional_costs(
            caster_index, card, cast_costs,
            cost_permanent_index=cost_permanent_index,
            cost_hand_card=cost_hand_card,
        )
        if permission is not None:
            consume_permission(self, permission, card)
        if from_zone != "hand":
            self.log.append(f"{card.name} cast from {caster.name}'s {from_zone}")

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
                    target_permanent_id=target_permanent_ids,
                    x_value=resolved_x_value,
                    target_stack_item=target_stack_item_val,
                    chosen_mode_index=mode_index,
                    cast_from_zone=from_zone,
                    exile_instead_of_graveyard=bool(
                        permission is not None and permission.exile_instead
                    ),
                    choices={
                        "divided_targets": divided_targets,
                        "new_color": new_color,
                        "old_color": old_color,
                        # What the additional cost ate, for the spell whose
                        # effect asks about it ("…equal to the sacrificed
                        # creature's mana value"). The Permanent is off the
                        # battlefield by now, so this is last-known information
                        # (CR 608.2h) held on the stack item rather than a
                        # second lookup that could not succeed.
                        "sacrificed_for_cost": sacrificed_for_cost,
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
            choices={"sacrificed_for_cost": sacrificed_for_cost},
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")
    # ------------------------------------------------------------------
    # Printed additional costs (CR 601.2b)
    # ------------------------------------------------------------------

    def _additional_cost_candidates(self, caster_index: int, cost: AdditionalCost) -> list[Permanent]:
        """The permanents that could pay *cost*'s sacrifice, by identity.

        Never by index: an index would be held across the removal that paying
        performs, and would then name whichever permanent slid into the slot.
        """
        if cost.sacrifice_filter is None:
            return []
        return [
            perm
            for perm in self.controlled_by(caster_index)
            if subject_matches(self, perm, cost.sacrifice_filter)
        ]

    def _unpayable_additional_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        spell_hand_index: int | None,
        from_zone: str,
    ) -> str | None:
        """Why *card*'s printed additional costs can't be paid, or None.

        CR 601.2h: "Unpayable costs can't be paid" — and CR 601.2 makes the
        whole casting a rewind, so the answer is that the spell is not cast,
        never that it is cast without the cost. Asked before any mana leaves the
        pool, so a refusal costs the caster nothing.
        """
        caster = self.players[caster_index]
        for cost in costs:
            if cost.sacrifice_filter is not None:
                if not self._additional_cost_candidates(caster_index, cost):
                    return (
                        f"{card.name} can't be cast: no "
                        f"{filter_head_noun(cost.sacrifice_filter)} to "
                        f"sacrifice for its additional cost (CR 601.2h)"
                    )
            if cost.discard_cards:
                # The spell itself is still in the zone it is being cast from,
                # and it is about to be on the stack — so it cannot be one of
                # the cards discarded to pay for itself.
                available = len(caster.hand)
                if from_zone == "hand" and spell_hand_index is not None:
                    available -= 1
                if available < cost.discard_cards:
                    return (
                        f"{card.name} can't be cast: not enough cards in hand to "
                        f"discard for its additional cost (CR 601.2h)"
                    )
        return None

    def _resolve_discard_cost_card(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        cost_hand_index: int | None,
        spell_hand_index: int | None,
    ) -> tuple["CardDefinition | None", str | None]:
        """The card a named ``cost_hand_index`` picks, or why it picks none.

        CR 601.2b's choices are announced while the spell is still being cast,
        so the index is into the hand the caster can see — the one that still
        holds the spell. Resolving it to a *card* here is what makes the answer
        survive the spell leaving that hand: an index is only meaningful
        alongside the list it was read from, which is the instability this
        engine addresses with ids on the battlefield and cannot here, because a
        hand holds ``CardDefinition``s and two copies of a card are one object.

        The spell itself is refused: CR 601.2a puts it on the stack before its
        costs are paid, so it is not in the hand to be discarded. Nothing named
        means the deterministic default, which keeps AI and headless play
        unblocked.
        """
        if cost_hand_index is None or not any(cost.discard_cards for cost in costs):
            return None, None
        hand = self.players[caster_index].hand
        if not 0 <= cost_hand_index < len(hand):
            return None, (
                f"{card.name} can't be cast: no card at hand position "
                f"{cost_hand_index} to discard for its additional cost"
            )
        if cost_hand_index == spell_hand_index:
            return None, (
                f"{card.name} can't be cast: it is on the stack (CR 601.2a) and "
                "cannot be discarded to pay for itself"
            )
        return hand[cost_hand_index], None

    def _pay_additional_costs(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        cost_permanent_index: int | None,
        cost_hand_card: "CardDefinition | None",
    ) -> Permanent | None:
        """Perform *card*'s printed additional costs, returning what was
        sacrificed (for the spell whose effect asks about it).

        The payer chooses (CR 601.2b), and the choice arrives with the action
        rather than through the pending-choice queue — a queued prompt would put
        the spell on the stack before its cost was collected, which is the
        reasoning ``activate_permanent_ability`` already records for the
        identically-shaped activation costs. A seat that names nothing gets a
        deterministic pick so AI and headless play stay unblocked.
        """
        caster = self.players[caster_index]
        sacrificed: Permanent | None = None
        for cost in costs:
            if cost.sacrifice_filter is not None:
                candidates = self._additional_cost_candidates(caster_index, cost)
                if not candidates:
                    continue  # gated above; a board that changed since is a no-op
                named = (
                    self.permanent_at(caster, cost_permanent_index)
                    if isinstance(cost_permanent_index, int)
                    else None
                )
                chosen = (
                    named
                    # `in` compares Permanents by value and would match a
                    # look-alike; membership is by identity.
                    if any(perm is named for perm in candidates)
                    else self.default_sacrifice_pick(candidates)
                )
                name = chosen.card.name
                if self.sacrifice_permanent(chosen) is not None:
                    sacrificed = chosen
                    self.log.append(
                        f"{caster.name} sacrificed {name} to cast {card.name}"
                    )
            if cost.discard_cards:
                for _ in range(cost.discard_cards):
                    if not caster.hand:
                        break
                    # The chosen card was resolved before the spell left the
                    # hand; find it by identity now. Two copies of one card are
                    # the same object, which is fine — either pays the cost, and
                    # discarding "the first equal one" is the whole choice.
                    index = 0
                    if cost_hand_card is not None:
                        index = next(
                            (
                                i for i, held in enumerate(caster.hand)
                                if held is cost_hand_card
                            ),
                            0,
                        )
                        cost_hand_card = None  # one named card pays once
                    discarded = caster.hand.pop(index)
                    self._discard_card(caster, discarded)
                    self.log.append(
                        f"{caster.name} discarded {discarded.name} to cast {card.name}"
                    )
                    # One named index pays one card; the rest take the default.
                    cost_hand_index = None
        return sacrificed

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
                    clause = aura_enchant_clause(card.oracle_text)
                    if clause is not None and "graveyard" in clause:
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

        # CR 601.2c: the caster announces how many targets a variable-target
        # spell will have, and the maximum is what the card printed. The picker
        # and the AI both cap themselves, so this is the re-check of a number
        # they were *told* (idiom #9) — read from `derive_cast_spec`, the same
        # derivation that told them, so the cap and the prompt cannot disagree.
        # Fewer is legal, including none. Which permanents were named is not
        # checkable here: the slots are indices on one seat and a several-target
        # description may legitimately span two battlefields, so the identities
        # only exist as the ids on the stack item and the handler enforces them
        # there.
        #
        # Placed above the per-kind arms rather than in one: a card whose
        # `primary` is a `sequence` wrapper (Frost Breath) reaches none of them,
        # so a cast naming three targets was accepted and the handler silently
        # capped at two.
        announced = (
            len(target_permanent_index)
            if isinstance(target_permanent_index, list)
            else None
        )
        maximum = (derive_cast_spec(card, program) or {}).get("max_targets")
        if isinstance(maximum, int) and announced is not None and announced > maximum:
            return False, f"too many targets for {card.name}"

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        if target_idx < 0 or target_idx >= len(self.players):
            target_idx = 1 - caster_index
        target = self.players[target_idx]

        # CR 702.16b: a spell can't be cast targeting a creature with protection
        # from the spell's quality (or with shroud). Reject the illegal target at
        # cast time, mirroring the resolution-time check, so it is never offered.
        # Every chosen slot is checked, not just the first: a spell naming "up to
        # two target creatures" chooses each of them separately (CR 601.2c), and
        # one illegal choice makes the cast illegal however many others are fine.
        #
        # **Only where the slot is a battlefield slot.** A graveyard target's
        # index counts into a different list, and reading it here refused Raise
        # Dead over a White Knight the spell never named: CR 702.16b is about
        # the spell's own targets, and a card in a graveyard is not a permanent
        # (CR 115.2), so it has no protection to check in the first place.
        chosen_slots = (
            ()
            if graveyard_target_spec(card, program, mode_index=mode_index) is not None
            else target_permanent_index
            if isinstance(target_permanent_index, list)
            else [target_permanent_index]
        )
        for slot in chosen_slots:
            if not isinstance(slot, int) or not (0 <= slot < len(target.battlefield)):
                continue
            chosen = target.battlefield[slot]
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
            targets_desc = primary.payload.get("targets") or {}
            several = (
                isinstance(targets_desc, dict)
                and isinstance(targets_desc.get("count"), int)
                and targets_desc["count"] > 1
            )
            if several:
                # "Up to two target creature cards ...": CR 601.2c lets the
                # caster announce *zero* targets, so an empty graveyard is not a
                # reason to refuse the cast. What is refused is a named slot that
                # is not a legal choice - the picker's list is a hint and this is
                # the re-check (idiom #9).
                slots = (
                    target_permanent_index
                    if isinstance(target_permanent_index, list)
                    else ([] if target_permanent_index is None else [target_permanent_index])
                )
                if slots and target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                if len(slots) > targets_desc["count"]:
                    return False, f"too many targets for {card.name}"
                for slot in slots:
                    if not isinstance(slot, int) or not (0 <= slot < len(caster.graveyard)):
                        return False, f"no valid target for {card.name}"
                    if not graveyard_card_matches(primary.payload, caster.graveyard[slot]):
                        return False, f"no valid target for {card.name}"
            elif isinstance(target_permanent_index, int):
                if target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                if not (0 <= target_permanent_index < len(caster.graveyard)) or (
                    not graveyard_card_matches(
                        primary.payload, caster.graveyard[target_permanent_index]
                    )
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(
                graveyard_card_matches(primary.payload, c) for c in caster.graveyard
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
        self, player: PlayerState, mana_cost: str, extra_generic: int = 0,
        x_color: str | None = None, reduction: CostReduction | None = None,
    ) -> int:
        # The reduction is applied before X is inferred, because X is whatever
        # is left after the rest of the cost is paid — inferring it from the
        # undiscounted cost would spend the discount on nothing.
        required = reduce_cost(
            self._parse_mana_cost(mana_cost, x_value=0, extra_generic=extra_generic),
            reduction or CostReduction(),
        )
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
        self, player: PlayerState, required: dict[str, int], *, spell=None
    ) -> bool:
        # "Spend this mana only to…" (CR 106.6b): a restricted bucket joins the
        # pool only for a spell its own restriction admits, and whatever the
        # payment consumes is attributed to the restricted bucket first (its
        # units are otherwise lost, so spending them first is the only rational
        # attribution).
        #
        # *spell* is the card being cast, or None for an activation — an
        # activated ability is not a spell at all, so no "only to cast" mana may
        # pay for one, and None admitting nothing is that rule rather than a
        # missing argument.
        restricted = _spendable_restricted_mana(player, spell)
        if restricted and any(restricted.values()):
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
                    _debit_restricted_mana(player, spell, sym, from_restricted)
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


def _spendable_restricted_mana(player, spell) -> dict[str, int]:
    """Every restricted bucket *spell* may be paid from, merged by symbol.

    Merged rather than tried one at a time because a payment is one operation:
    two buckets that both admit the spell are, to CR 601.2g, simply mana in the
    pool. Which of them a spent unit came out of is settled afterwards by
    :func:`_debit_restricted_mana`, in the same order this merge walked.
    """
    from ...restricted_mana import restriction_admits

    merged: dict[str, int] = {}
    if spell is None:
        return merged
    for key, bucket in (player.restricted_mana or {}).items():
        if not any(bucket.values()) or not restriction_admits(key, spell):
            continue
        for symbol, amount in bucket.items():
            merged[symbol] = merged.get(symbol, 0) + amount
    return merged


def _debit_restricted_mana(player, spell, symbol: str, amount: int) -> None:
    """Take *amount* of *symbol* out of the buckets that paid for *spell*.

    In the merge's own order, so the attribution matches what was offered. The
    order between two admitting buckets is arbitrary and does not matter: both
    are spendable on this spell and both empty at the same step boundary, so no
    observable differs.
    """
    from ...restricted_mana import restriction_admits

    remaining = amount
    for key, bucket in (player.restricted_mana or {}).items():
        if remaining <= 0:
            break
        if not restriction_admits(key, spell):
            continue
        taken = min(remaining, bucket.get(symbol, 0))
        if taken:
            bucket[symbol] = bucket.get(symbol, 0) - taken
            remaining -= taken
