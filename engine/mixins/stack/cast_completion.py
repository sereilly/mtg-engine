"""What a cast does once its mana is paid (CR 601.2h–i): every other cost,
and the spell put on the stack.

The mana payment is ``_cast_onto_stack``'s hinge: every refusal above it,
every payment from it on, so a refused cast has nothing to give back
(CR 733.1, ``refusals.take_back_refused_attempt``). These are its two steps
below the hinge, and neither refuses. ``_pay_cast_costs`` takes the card out
of its zone and pays everything the price holds besides mana at one moment
(CR 601.2h). ``_put_cast_spell_on_stack`` builds the stack object from the
announcement — everything the cast decided that the resolution reads back,
on ``StackItem`` and its ``choices`` — pushes it, and makes what CR 601.2i
makes true once the spell is cast: the cast records, the cast triggers, an
opponent's mode choice. A graveyard target's slot is re-counted for a spell
that has left that pile (``_rebase_graveyard_targets``).

Split out of ``casting.py`` at the 2,000-line cap, and composed onto ``Game``
with the other parts of ``SpellCastingMixin``; each step is moved out of
``_cast_onto_stack`` whole and called from it in its order.
"""

from __future__ import annotations

import re

from ...cast_costs import kicked, optional_x_offers
from ...cast_permissions import consume as consume_permission
from ...cast_timing import (
    CAST_AT_INSTANT_SPEED, cast_by_its_own_flash_permission,
    sacrifices_at_cleanup_if_cast_at_instant_speed,
)
from ...counter_conditions import spend_next_spell_promises
from ...damage_ledger import record_cast
from ...enter_effects import COPY_DECLINED
from ...flashback import is_flashback
from ...game_types import (
    as_graveyard_stamps, as_target_ids, as_target_slots, chosen_damage_source,
    SimulationResult, StackItem, target_slots,
)
from ...mana_combination import MANA_COMBINATION
from ...oracle import compile_card_oracle
from ...oracle_types import _COLOR_WORD_TO_SYMBOL
from ...target_keywords import ANTE_INDEX
from ...target_roles import ANNOUNCED_TARGET_CONTROLLERS, ROLE_SEATS
from ...targeting import graveyard_target_spec


class CastCompletionMixin:
    def _pay_cast_costs(
        self, *, alternative_card, alternative_others, alternative_permanents,
        card, cast_costs, caster, caster_index, chosen_alternative,
        cost_graveyard_indices, cost_hand_cards, cost_permanent_ids,
        cost_permanent_index, from_zone, hand_index, held, life_owed,
        life_taxing_names, optional_paid, owed, permission, resolved_x_value,
        source_seat, source_zone, spell_graveyard_slot,
    ):
        """Every cost but the mana, paid at one moment once the mana payment
        has gone through (CR 601.2h), so nothing here refuses.

        The card leaves the zone it was cast from (out of exile through the
        departure seam); then the alternative cost's part that is not mana, the
        life a tax determined, the printed additional costs — paid beside an
        alternative cost too (CR 118.9d), their spoils kept for the stack
        object — Drought's imposed sacrifices, the permission spent, the
        commander's cast recorded (CR 903.8), and the line naming the zone a
        card cast from anywhere but a hand left.

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns ``(cost_spoils, exiled_for_cost, sacrificed_for_cost)``.
        """
        # A card played out of exile leaves it deliberately (CR 400.7 makes it a
        # new object wherever it lands), so the record that said it was face
        # down stops speaking for it — otherwise the *next* effect to exile the
        # same card would find that record alive and hide it from the table.
        # That retirement is the departure seam's, which is why this is not a
        # ``pop``: one transition out of exile, thirteen sites, one place for
        # anything that must happen when a card leaves.
        if from_zone == "exile":
            self.take_card_from_exile(source_seat, held)
        else:
            del source_zone[hand_index]
        # Now, and not before: the spell is no longer in the hand, so it cannot
        # be discarded to pay for itself, and the creature it eats is gone from
        # the battlefield before the spell is on the stack.
        # CR 118.9d keeps the additional costs in force alongside an
        # alternative one, so both are paid, in the order CR 601.2h leaves free.
        # The graveyard slots the caster named, re-counted for a spell that has
        # just left the same pile (every slot above it slid down one) — the
        # arrangement the additional costs' exile below makes.
        renumbered_slots = (
            cost_graveyard_indices
            if cost_graveyard_indices is None or spell_graveyard_slot is None
            else [
                slot - 1 if slot > spell_graveyard_slot else slot
                for slot in cost_graveyard_indices
            ]
        )
        self._pay_alternative_cost(
            caster_index, card, chosen_alternative, alternative_card,
            named_permanents=alternative_permanents,
            other_cards=alternative_others,
            # "Flashback—{1}{U}, Exile X blue cards from your graveyard" / "…,
            # Sacrifice X Mountains": the X the cast announced, and the cards
            # named for the exile when no additional cost has the channel.
            x_value=resolved_x_value,
            graveyard_slots=(
                renumbered_slots
                if self.alternative_takes_named_graveyard_slots(
                    cast_costs, chosen_alternative, optional_paid,
                )
                else None
            ),
        )
        # CR 601.2f's increases, in life. Gated far above, where the targets
        # settle what they come to, and paid here with every other cost —
        # nothing between the two points spends anything, so a refusal up there
        # costs the caster exactly nothing.
        if life_owed:
            caster.life -= life_owed
            self.log.append(
                f"{caster.name} paid {life_owed} life to cast {card.name} "
                f"({', '.join(life_taxing_names)})"
            )
        cost_spoils = self._pay_additional_costs(
            caster_index, card, cast_costs,
            cost_permanent_index=cost_permanent_index,
            cost_permanent_ids=cost_permanent_ids,
            cost_hand_cards=cost_hand_cards,
            x_value=resolved_x_value,
            taken=optional_paid,
            # Re-counted for a spell that has just left the same pile: the
            # gate above refused the spell's own slot, and every slot above it
            # slid down one when it went to the stack.
            cost_graveyard_indices=renumbered_slots,
        )
        sacrificed_for_cost = cost_spoils["sacrificed_for_cost"]
        exiled_for_cost = cost_spoils["exiled_for_cost"]
        # Drought's imposed sacrifices, paid with the printed ones and at the
        # same moment. The victims were picked before the mana was spent, so a
        # board that has not changed since pays exactly what the gate measured.
        self._pay_sacrifice_tax(owed, f"to cast {card.name}")
        if permission is not None:
            consume_permission(self, permission, held)
        if from_zone == "command":
            # CR 903.8's "each previous time" is counted once the cast is
            # announced and paid for, so the tax charged above is the one this
            # cast owed and the next one is {2} higher. A cast that failed
            # anywhere above returned before here and costs nothing.
            self.record_commander_cast(caster_index, held)
        if from_zone != "hand":
            # Whose pile it left, which is not always the caster's: a grant may
            # open somebody else's exile (Grinning Totem). The permission is the
            # only thing that knows, so it is asked rather than assumed.
            pile_seat = (
                permission.zone_seat if permission is not None else caster_index
            )
            # A land is played, never cast (CR 305.1): Future Sight's "play
            # lands … from the top of your library" comes through this path as
            # the land drop, and the log called it a cast.
            verb = "played" if card.primary_type == "land" else "cast"
            self.log.append(
                f"{card.name} {verb} from {self.players[pile_seat].name}'s {from_zone}"
            )
        return cost_spoils, exiled_for_cost, sacrificed_for_cost

    def _put_cast_spell_on_stack(
        self, *, ante_index, card, cast_costs, caster, caster_index,
        chosen_alternative, chosen_modes, chosen_source_permanent_index,
        chosen_source_seat, chosen_source_stack_index, chosen_type_word,
        classification, copy_declined, cost_spoils, divided_targets,
        exiled_for_cost, from_zone, hand_index, mana_combination, mode_index,
        new_color, old_color, optional_paid, permission, resolved_x_value,
        role_graveyard_stamps, role_seats, sacrificed_for_cost, source_seat,
        target_permanent_ids, target_permanent_index, target_player_index,
        target_stack_item, x_mana_spent,
    ):
        """The spell put on the stack, and cast (CR 601.2i).

        The stack spell it targets, defaulted where none was named; the stack
        object built from the announcement — everything the cast decided that
        the resolution reads back, on ``StackItem`` and its ``choices``; the
        push; and then what CR 601.2i makes true once the spell is there: the
        log lines an opponent decides by (a chosen number, a kick), the turn's
        cast records, a promise the next spell spends, the cast triggers, and
        an opponent's mode choice (CR 700.2e).

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the cast's result.
        """
        # Determine which stack spell this one targets. An explicit choice
        # (target_stack_item) wins; otherwise fall back to the topmost legal
        # spell so AI and untargeted casts still work.
        target_stack_item_val = target_stack_item
        enumerated = False
        if target_stack_item_val is None:
            # The gate's own enumeration first (`default_stack_target`):
            # the topmost object the printed phrase admits, so the default
            # is a target `cast_stack_target_refusal` would have accepted
            # by name. The text reading below is what is left for the
            # shape that gate declines — a permanent spell, whose "counter
            # target spell" is an entry trigger's — and it is not consulted
            # where the enumeration answered, an answer of "nothing"
            # included. A modal spell is always answered, for the mode it
            # announced.
            enumerated, target_stack_item_val = self.default_stack_target(
                caster_index, card, from_zone=from_zone,
                mode_index=mode_index,
            )
        if (
            not enumerated
            and target_stack_item_val is None
            and self.stack
            and "counter target" in card.oracle_text.lower()
        ):
            color_match = re.search(r"counter target (\w+) spell", card.oracle_text.lower())
            color_filter: str | None = None
            if color_match:
                color_filter = _COLOR_WORD_TO_SYMBOL.get(color_match.group(1))
            # The spell's colours through ``object_colors``, so a stack
            # object Celestial Dawn has made white is what "counter target
            # white spell" finds — the same reading `_shares_a_color`
            # twenty lines up already makes for the other half of CR 105.
            # The stack object's own colour reader — a Lace's recolour
            # and a text-changed colour included — not its printed card's.
            matching = [
                it for it in self.stack
                if not color_filter
                or color_filter in self._stack_item_colors(it)
            ]
            if matching:
                target_stack_item_val = matching[-1]
        spell_item = StackItem(
                card=card,
                caster_index=caster_index,
                # CR 108.3/400.3: the seat whose pile the card left owns
                # it — the caster's for a hand, a command zone or their own
                # graveyard, the opponent's for Grinning Totem's exile — and
                # that seat's zones are where it goes when it leaves the
                # stack, whoever cast it.
                owner_index=source_seat,
                target_player_index=target_player_index,
                target_permanent_index=as_target_slots(target_permanent_index),
                target_permanent_id=as_target_ids(target_permanent_ids),
                # A roles announcement's graveyard slots (see the top of
                # this method); None for every other cast, whose graveyard
                # target is stamped as the item is pushed.
                target_graveyard_card=as_graveyard_stamps(role_graveyard_stamps),
                x_value=resolved_x_value,
                target_stack_item=target_stack_item_val,
                chosen_mode_index=mode_index,
                chosen_modes=chosen_modes,
                cast_from_zone=from_zone,
                # CR 707.12: a copy of a card cast under the grant that
                # made it (``engine/copy_casts.py``) is a copy on the stack
                # (CR 707.10a): it resolves and ceases to exist.
                is_copy=bool(permission is not None and permission.cast_as_copy),
                exile_instead_of_graveyard=bool(
                    permission is not None and permission.exile_instead
                ),
                # CR 702.34a: "If the flashback cost was paid, exile this
                # card instead of putting it anywhere else any time it
                # would leave the stack." Whether it was paid is this
                # cast's own fact — the cost it was announced under — and
                # the stack object is the only thing that outlives the
                # announcement to say so.
                flashback=is_flashback(chosen_alternative),
                choices={
                    "divided_targets": divided_targets,
                    "new_color": new_color,
                    MANA_COMBINATION: mana_combination,
                    "old_color": old_color,
                    # What the additional cost ate, for the spell whose
                    # effect asks about it ("…equal to the sacrificed
                    # creature's mana value"). The Permanent is off the
                    # battlefield by now, so this is last-known information
                    # (CR 608.2h) held on the stack item rather than a
                    # second lookup that could not succeed.
                    # How many times each CR 601.2b optional additional
                    # cost was taken. The pool is empty by resolution
                    # (CR 500.5) and the spell is on the stack, so nothing
                    # in the game state can answer "for each additional
                    # {1}{R} you paid" — this is where the announcement
                    # survives, beside the other costs' spoils and for the
                    # same reason.
                    "additional_costs_paid": optional_paid,
                    # CR 609.7a's chosen damage source, resolved to the
                    # object it names. On the same channel the activation
                    # path writes, because the handler behind it is the same
                    # handler: `handlers/prevention.chosen_shield_source`
                    # reads this key first, ahead of every fallback that
                    # reads a target slot instead. Without it a *spell* that
                    # names a source could only be given one by spending one
                    # of its own target slots, which is what kept Honorable
                    # Passage sourceless and Kor Chant unsupported.
                    "chosen_source": chosen_damage_source(
                        self,
                        seat=chosen_source_seat,
                        permanent_index=chosen_source_permanent_index,
                        stack_index=chosen_source_stack_index,
                    ),
                    "sacrificed_for_cost": sacrificed_for_cost,
                    # …the cards a *discard* cost took, on the channel the
                    # activation path records them on and for its reason:
                    # the card is in a graveyard by now (CR 400.7: a
                    # different object), so the announcement is the only
                    # thing that can say which of that pile's cards it was.
                    "discarded_for_cost": cost_spoils["discarded_for_cost"],
                    # …and what an *exile* cost ate, on the channel the
                    # activation path already records it on. Last-known
                    # information for the same reason (CR 608.2h): the
                    # permanent left the battlefield before the spell was
                    # on the stack, so nothing on the board can be asked
                    # what it was.
                    "exiled_for_cost": exiled_for_cost,
                    # CR 601.2h's answer to "the amount of {B} spent on X"
                    # (Soul Burn). Decided as the cost was built rather than
                    # measured as a pool delta afterwards: this card costs
                    # {X}{2}{B}, so a black unit missing from the pool may
                    # have paid the mandatory pip, the generic {2} or X, and
                    # a delta cannot tell those apart. The allocation is the
                    # cost, so the number is exact.
                    "x_mana_spent": x_mana_spent,
                    # The word CR 601.2b made the caster choose. Here
                    # rather than nowhere because the spell has no
                    # permanent yet and the permanent it becomes is a new
                    # object (CR 400.7), so the announcement is the only
                    # place the answer survives the trip to resolution —
                    # the cost spoils above are on this channel for exactly
                    # that reason. `_resolve_permanent_spell` copies it
                    # onto the permanent as it is built.
                    "chosen_creature_type": chosen_type_word,
                    # Every seat the announcement named, by role, where it
                    # named two or more (`target_roles.ROLE_SEATS`) — beside
                    # `target_player_index` above, which then holds the
                    # first. None for every other cast.
                    ROLE_SEATS: role_seats,
                    # "If you cast it any time a sorcery couldn't have been
                    # cast, …" (Mirage's five flash Auras). Answered *here*
                    # because here is the only moment it can be: CR 601.3d's
                    # timing is about the game state as the spell is
                    # announced, and by resolution the stack has emptied
                    # down to this spell and the step may have moved on.
                    # Stamped only for a card whose text asks — see
                    # `cast_permissions`, whose whole rider this feeds —
                    # and only when its **own** permission is what lets
                    # it be cast now: cast under Vernal Equinox's or a
                    # Rootwater Shaman's, it is not sacrificed (the
                    # cycle's rulings, 2022-12-08).
                    CAST_AT_INSTANT_SPEED: (
                        sacrifices_at_cleanup_if_cast_at_instant_speed(
                            card.oracle_text or ""
                        )
                        and cast_by_its_own_flash_permission(
                            self, caster_index, card
                        )
                    ),
                },
        )
        if from_zone == "graveyard":
            self._rebase_graveyard_targets(spell_item, source_seat, hand_index)
        # "For each opponent, … target permanent that player controls"
        # (Blatant Thievery): who controlled each named permanent as it was
        # targeted, for CR 608.2b to ask again (``target_roles.
        # ANNOUNCED_TARGET_CONTROLLERS``). Absent for every other cast.
        controllers = self.announced_target_controllers(
            card, target_permanent_ids, mode_index=mode_index,
        )
        if controllers is not None:
            spell_item.choices[ANNOUNCED_TARGET_CONTROLLERS] = controllers
        # The declined copy rides to resolution on the announcement's
        # channel, the one the chosen creature type rides on — the
        # permanent does not exist yet (``_resolve_permanent_spell``
        # copies it on). Only where declined, so every other stack item is
        # unchanged.
        if copy_declined:
            spell_item.choices[COPY_DECLINED] = True
        if ante_index is not None:
            spell_item.choices[ANTE_INDEX] = ante_index
        self._stack_push(spell_item)
        self.log.append(f"{card.name} added to stack")
        if any(cost.choose_number is not None for cost in cast_costs):
            # "As an additional cost to cast this spell, choose a number
            # between 0 and 5." (Liquid Fire.) Said in the log for the
            # reason a kick is, one block down: CR 601.2b makes the choice
            # part of the announcement so that an opponent deciding whether
            # to respond knows which spell this is — five damage to the
            # creature or five to its controller's face.
            self.log.append(
                f"{caster.name} chose {int(resolved_x_value or 0)} "
                f"for {card.name}"
            )
        if kicked(card, spell_item.choices):
            # CR 702.33d: the spell is kicked from the moment its
            # controller declared the intention to pay, which is now. Said
            # in the log because nothing else on the table shows it -- the
            # mana is spent either way, and an opponent deciding whether to
            # counter Kavu Titan needs to know which Kavu Titan it is.
            self.log.append(
                f"{caster.name} kicked {card.name}"
                + (f" (X={resolved_x_value})" if optional_x_offers(
                    card, from_zone=from_zone
                ) else "")
            )
        # "Whenever a player casts a [color] spell" triggers (Rod/Cup/Sphere)
        # and "whenever you cast an X spell" triggers (Verduran Enchantress)
        # fire now, as the spell is put on the stack, and go on the stack above
        # it (CR 603.3) — so the trigger resolves while the triggering spell is
        # still on the stack, not after it has already resolved.
        # The record every ordinal reads — "you've cast an instant or
        # sorcery spell this turn" (Stormwing Entity), "their second spell
        # each turn" (Mangara), "other than the first instant spell that
        # player casts each turn" (Ichneumon Druid). CR 601.2i finishes the
        # casting before anything can respond, so the spell is on the list
        # before *any* of the announcements below, not just the ones that
        # used to follow it: it was appended inside `_apply_cast_triggers`,
        # which runs second, so an opponent-scoped ordinal counted a list
        # missing the very spell that fired it and every such trigger was
        # one cast late.
        if 0 <= caster_index < len(self.players):
            self.players[caster_index].spells_cast_this_turn.append(card)
        # The same record, by the identity that list cannot carry: a
        # `CardDefinition` is shared by every copy in every deck, so two
        # casts of one sorcery are one entry there and two here. Backdraft's
        # "one of those sorcery spells" is a choice **between** them.
        record_cast(self, spell_item)
        # "The next instant or sorcery spell you cast this turn can't be
        # countered." (Overmaster.) Spent here, where CR 601.2i makes the
        # spell cast — the next matching spell is this one, before any
        # counter can be announced at it.
        spend_next_spell_promises(self, spell_item)
        self._apply_spell_cast_any_triggers(
            caster_index, card, from_zone, item=spell_item
        )
        self._apply_cast_triggers(caster_index, card, item=spell_item)
        # "An opponent chooses one —" (CR 700.2e): the other player chooses
        # "when the spell's controller normally would", which is CR 601.2b.
        # Armed here rather than earlier because CR 601.2i finishes the
        # casting first — the spell is on the stack and the cast triggers
        # are announced, and the prompt holds priority, so nobody acts
        # between the two. A non-interactive chooser takes the default where
        # this stands (`default_at_arm`), which is what keeps AI and
        # headless play from stopping on a decision nobody will make.
        self._arm_opponent_mode_choice(caster_index, card, spell_item)
        return SimulationResult(card.name, True, classification.effect_kind, "queued")

    def _rebase_graveyard_targets(
        self, item: StackItem, pile_seat: int, left_slot: int
    ) -> None:
        """Re-count *item*'s graveyard target slots now that the spell itself
        has left *pile_seat*'s graveyard from *left_slot*.

        A graveyard target is announced as a slot, and the announcement is
        made against the pile **the caster is looking at** — the spell still
        in it, which is the list the picker enumerated and the list the
        announcement gates above just checked the slot against. The card then
        leaves that pile (CR 601.2a), every later slot slides down one, and
        ``_stack_push`` names the target by the slot it is handed. Read
        unshifted, Morgue Theft flashed back from under two creature cards
        returned the *other* one, and a slot past the shortened end named
        nothing and fell back to the first legal card.

        Only where the slot counts into the pile the spell left: the same
        ``graveyard_target_seat`` the stamp is about to ask, so the two cannot
        disagree about whose pile an index is into. The spell's own slot never
        arrives here — the picker does not offer it and
        ``cast_target_refusal`` has refused it (``targeting.CAST_FROM_GRAVEYARD``).
        """
        spec = graveyard_target_spec(
            item.card, compile_card_oracle(item.card),
            mode_index=item.chosen_mode_index,
        )
        if spec is None or self.graveyard_target_seat(item, spec) != pile_seat:
            return

        def rebased(slot):
            return slot - 1 if isinstance(slot, int) and slot > left_slot else slot

        if item.target_permanent_index is not None:
            item.target_permanent_index = [
                rebased(slot) for slot in target_slots(item.target_permanent_index)
            ]
