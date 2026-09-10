"""How a condition that asks what already **happened** becomes its payload.

The lowering-side mirror of ``ast/records.py``, and it is the same cut that
module took. Its docstring states the line, and states that the line was here
first:

    "What stays there is a condition answered by looking at the game *now* — a
    board count, a zone’s height, a life total, a permanent’s
    characteristics, whose turn it is — and what moved is a condition answered
    by looking at a record of something that has already been done. The
    distinction is the one ``lowering/conditions.py`` had already been writing
    in prose card by card ("that one asks the board and this one reads the
    scratchpad"), which is the sign that the seam was there before the guard
    found it."

Split out of ``conditions`` at Exodus’ second wave, when that module sat
five lines under the thousand-line guard. The seam was taken as a *lead* and
then measured rather than assumed, because a mirror is not a fact: every one of
``_lower_condition``’s forty-nine branches is a bare ``isinstance`` on a
distinct node class, so each was read against which half of ``ast`` defines its
node. Not one branch tests a node from both halves, and the two halves turned
out to share **no helper and no import** beyond ``ast`` and ``LoweringError`` —
``_condition_seat``, ``pronoun_target_referent``, ``_subject_could_be_counted``
and ``_SAME_NAME_EVENTS`` are read by the board half alone, and
``card_only_filter``, ``untestable_filter_keys``, ``_filter_payload``,
``_restrictions_beyond``, ``MILLED_THIS_WAY``, ``COUNTED_NUMBER`` and
``DAMAGED_BY_SOURCE_DIED`` by this one alone. A seam that divides the imports
as cleanly as it divides the branches is the seam, not a place to have put the
overflow.

Order is not part of the division and could not be: the dispatch is forty-nine
mutually exclusive ``isinstance`` tests with no ``elif`` among them, so which
half reads a node first cannot change what any of them answers. ``conditions``
hands the sentence down here as the last thing it does, in place of the
fall-through refusal, which is the arrangement ``_bound_returns`` has with
``_described_returns`` — one call still covers every condition and the callers
did not move.

**The name.** The mirror’s word is ``records``, and ``lowering/_records.py``
is already taken by a sibling of the same subject — the ``_PRODUCES`` table,
"what each instruction kind records in the resolution scratchpad". So this
carries the word and disambiguates by what it holds, exactly as
``_record_keys`` did when the *spellings* of those keys left ``_events``. Three
modules, one word, three questions: what a step records, what the key is
called, and what a sentence may ask of it.

A floor rather than a family, for ``conditions``’ own stated reason one line
below its title: three callers in three different places read a condition, and a
condition living in one family would couple the rest to that family. Its only
reader is ``conditions``, and it reads nothing back.
"""

from __future__ import annotations

from ...damage_deaths import DAMAGED_BY_SOURCE_DIED
from ...oracle_types import (CHOSEN_COLOR_THIS_WAY, CHOSEN_NUMBER_THIS_WAY,
                             MILLED_THIS_WAY, REVEALED_HAND_CARDS)
from ...subject_filters import card_only_filter, untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import _filter_payload, _restrictions_beyond
from ._events import COUNTED_NUMBER
# The one name this file shares with the table that declares it: which key a
# discard cost writes. Imported rather than spelled, because a producer gate and
# the declaration it reads are exactly the pair a second spelling makes vacuous —
# which is what these two files did to each other until Pyromancy gave the
# channel a second reader.
from ._cost_records import DISCARDED_FOR_COST


def lower_record_condition(
    condition: ast.Condition,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
    referent: str | None = None,
    event_subject=None,
) -> dict[str, object]:
    """The half of :func:`_lower_condition` that reads a record.

    Reached as that function’s tail call, so a condition neither half knows
    refuses here with the message it always carried.
    """
    if isinstance(condition, ast.CoinFlipResult):
        # A back-reference names its producer or refuses (round 33). Without a
        # flip earlier in the same effect there is nothing to read, and
        # `evaluate_condition` would quietly answer False — so a card printing
        # only "If you win the flip, …" would compile supported and do nothing.
        if "coin_flip" not in produced:
            raise LoweringError(
                "'the flip' with no coin flip before it in this effect",
                node=condition,
            )
        return {"kind": "coin_flip", "won": condition.won}
    if isinstance(condition, ast.EnteredFrom):
        # CR 603.4's intervening-if, asked of the permanent that fired the
        # trigger. Both halves ride the payload; the evaluator asks about the
        # zone it came from and, when `or_cast` is set, about the zone the spell
        # was cast from — two different records, because a reanimation and a
        # cast are two different events that leave the same card in the same
        # place.
        return {
            "kind": "entered_from",
            "zone": condition.zone,
            "or_cast": condition.or_cast,
        }
    if isinstance(condition, ast.RevealedCardIs):
        # The pronoun's referent again, and the same discipline: a reveal
        # earlier in this same effect has to have recorded what it showed, or
        # there is nothing for "it" to name and the branch would answer False
        # forever while the card compiled clean (idiom #7).
        if "revealed_card" not in produced:
            # "Untap target Griffin. **If it's a creature**, it gets +1/+1
            # until end of turn." (Griffin Canyon.) The same printed words
            # asking a different question, and **the parse cannot tell them
            # apart**: Prophecy prints "reveal the top card …, if it's a land"
            # and this prints "untap target Griffin, if it's a creature" —
            # one clause, one shape, two referents. What separates them is the
            # *producer*, and the producer is only in view here. That is the
            # arrangement ``ItIsColor`` beside this already documents for the
            # colour half of the same pronoun ("which object the pronoun names
            # is not settled here; lowering reads it off the effect this
            # condition guards"), and CR 608.2c is why it can be: the
            # instruction and its "if" are one sentence.
            #
            # So a reveal claims the clause first, and only a line with no
            # reveal at all falls through to the target reading — which still
            # refuses when the guarded branch names no object, rather than
            # asking the question of whichever half of the resolution context
            # happened to hold something.
            if referent == "permanent":
                leftover = _restrictions_beyond(
                    condition.filter, {"card_types", "is_card", "type_match"}
                )
                if leftover or not condition.filter.card_types:
                    raise LoweringError(
                        "'it's …' reads a printed type line here too: "
                        + ", ".join(leftover or ("no type at all",)),
                        node=condition,
                    )
                return {
                    "kind": "target_is_type",
                    "card_types": list(condition.filter.card_types),
                    "type_match": condition.filter.type_match,
                    "negated": condition.negated,
                    "target": referent,
                }
            raise LoweringError(
                "'it' with nothing in this effect that revealed a card",
                node=condition,
            )
        leftover = _restrictions_beyond(
            condition.filter,
            {"card_types", "is_card", "type_match", "excluded_types"},
        )
        if leftover:
            raise LoweringError(
                "the revealed-card test cannot ask this of a card: "
                + ", ".join(leftover),
                node=condition,
            )
        if not condition.filter.card_types and not condition.filter.excluded_types:
            raise LoweringError(
                "'it's …' reads a card's printed type line", node=condition
            )
        payload = {
            "kind": "revealed_card_is",
            "card_types": list(condition.filter.card_types),
            "type_match": condition.filter.type_match,
        }
        if condition.filter.excluded_types:
            # "If it's a **nonland** card" (Wand of Denial). The exclusion the
            # noun phrase carries, emitted only when printed so every payload
            # written before this stays byte-identical — and emitted at all,
            # because a word the production consumes and the payload drops is a
            # test that passes for every card.
            payload["excluded_types"] = list(condition.filter.excluded_types)
        # "If it **isn't** a land card" (Wand of Ith). Carried rather than
        # lowered into a separate kind, so the two spellings reach the one
        # evaluator that knows how to read the record — and emitted only when
        # the word was printed, the way every other optional narrowing in this
        # pipeline is.
        if condition.negated:
            payload["negated"] = True
        return payload
    if isinstance(condition, ast.ItWas):
        # The pronoun's referent, resolved here because only here is the
        # sentence in front of it known. One producer answers it today — the
        # card an exile step of this same effect took out of a graveyard — and
        # a second producer means a second key, never this one widened, for the
        # reason `amount_from` and `amount_from_trigger` are two keys.
        #
        # "…that player reveals the top card of their library. **If that card
        # is a land card**, …" (Paroxysm.) The second producer, and it gets the
        # second *key* rather than a widening of this one: the sentence is
        # asking exactly what ``RevealedCardIs`` asks, so it is re-asked as that
        # node instead of growing a branch here. Which producer ran is the whole
        # question — Chaos Harlequin prints the same four words after an exile —
        # and it is only in view at this point, which is what the branch below
        # already says about the exile reading.
        if "exiled_cards" not in produced and "revealed_card" in produced:
            return lower_record_condition(
                ast.RevealedCardIs(condition.filter),
                produced, event, referent, event_subject,
            )
        if "exiled_cards" not in produced:
            raise LoweringError(
                "'it' with nothing in this effect that named what it moved",
                node=condition,
            )
        leftover = _restrictions_beyond(
            condition.filter, {"card_types", "is_card", "type_match"}
        )
        if leftover:
            raise LoweringError(
                "the last-known-information test cannot ask this of a card: "
                + ", ".join(leftover),
                node=condition,
            )
        if not condition.filter.is_card or not condition.filter.card_types:
            raise LoweringError(
                "'it was …' reads a card's printed type line", node=condition
            )
        return {
            "kind": "exiled_card_was",
            "card_types": list(condition.filter.card_types),
        }
    if isinstance(condition, ast.DestroyedTargetWas):
        # "Destroy target land. **If that land was a snow land**, …" The
        # referent is the permanent the destroy in front of this chose, so a
        # step that destroyed one must be in front of it — round 33's rule for
        # every back-reference: with nothing to read, `evaluate_condition` would
        # answer False and the card would compile supported and never do its
        # second half.
        if "destroyed_target" not in produced:
            raise LoweringError(
                "'that <noun> was …' with nothing in this effect that "
                "destroyed one",
                node=condition,
            )
        described = _filter_payload(condition.filter)
        if not described or untestable_filter_keys(described):
            # The object has left the battlefield, so what is asked of it is
            # last-known information — but it is still asked through the one
            # matcher, and a narrowing that matcher cannot test would be a
            # condition answering about a different set than the card names.
            raise LoweringError(
                "the last-known-information test cannot ask this of a "
                "permanent", node=condition,
            )
        return {"kind": "destroyed_target_was", "filter": described}
    if isinstance(condition, ast.CostObjectWas):
        # "…**if the exiled creature was a Thrull**" (Soul Exchange);
        # "…**if the sacrificed creature was a Thrull**" (Ebon Praetor). The
        # channel is named in the printed words, so the payload is the channel
        # plus the noun phrase and nothing is guessed.
        #
        # **No producer gate here, deliberately, and this is the one
        # back-reference that has to do without one.** The producer is a *cost*,
        # and a cost is not a step of the effect: for an activated ability it is
        # the clause left of the colon, and for a spell it is a **different
        # printed line** of the same card (``engine/cast_costs.py``), which this
        # line cannot see at all. `produced` names what steps of *this* clause
        # recorded, so gating on it would refuse Soul Exchange outright. What
        # stands in for the gate is that the phrase names its own channel — no
        # pronoun to resolve — and an unpaid channel is honestly False rather
        # than ambiguous: nothing was sacrificed, so the sacrificed creature was
        # not a Thrull.
        described = _filter_payload(condition.filter)
        # Tested against a *card* as well as a permanent — the payment channels
        # carry a `Permanent` on the cast side and a `CardDefinition` on the
        # activation side — so the filter must be one the narrower of the two
        # matchers can answer. Anything wider refuses, which is the direction
        # that cannot make the condition true about a larger set than the card
        # names.
        if not described or card_only_filter(described) is None:
            raise LoweringError(
                "the cost-object test cannot ask this of what a cost ate",
                node=condition,
            )
        return {
            "kind": "cost_object_was",
            "channel": f"{condition.channel}_for_cost",
            "filter": described,
        }
    if isinstance(condition, ast.DiscardedCardWas):
        # Same discipline as the two back-references above, with the producer
        # named in the printed words: an ability that discarded nothing has no
        # record to read, and the evaluator would answer False forever while the
        # card compiled clean. The one producer today is the ability's own
        # discard cost (CR 601.2h / 602.2b), seeded by `lower_ability` off the
        # cost clause — the only place the cost and the effect are both in view.
        if DISCARDED_FOR_COST not in produced:
            raise LoweringError(
                "'the discarded card' with nothing in this ability that "
                "discarded one",
                node=condition,
            )
        leftover = _restrictions_beyond(
            condition.filter, {"card_types", "is_card", "type_match"}
        )
        if leftover:
            raise LoweringError(
                "the discarded-card test cannot ask this of a card: "
                + ", ".join(leftover),
                node=condition,
            )
        if not condition.filter.card_types:
            raise LoweringError(
                "'the discarded card was …' reads a card's printed type line",
                node=condition,
            )
        return {
            "kind": "discarded_card_was",
            "card_types": list(condition.filter.card_types),
            "type_match": condition.filter.type_match,
        }
    if isinstance(condition, ast.CountedNumber):
        # "**If the number** is odd" (Chaos Moon). The count in front of it is
        # what the condition reads, so a clause with no producer refuses — the
        # same rule every other back-reference in this file is held to, and the
        # reason it matters here is that an unproduced record evaluates False
        # for *both* parities: the card would silently do neither branch.
        if COUNTED_NUMBER not in produced:
            raise LoweringError(
                "'the number' has no count in front of it", node=condition
            )
        return {"kind": "counted_number", "op": condition.comparison.op}
    if isinstance(condition, ast.StartedTheTurnState):
        # Its own kind, not `is_state` with a flag: the evaluator reads a
        # different thing (the untap step's record, not the board), so a payload
        # key the present-tense branch could ignore would answer the wrong
        # question silently.
        return {
            "kind": "started_turn_state",
            "state": condition.state,
            "negated": condition.negated,
        }
    if isinstance(condition, ast.SharedColorMilledThisWay):
        # One producer, demanded like every other back-reference: with no mill
        # before it there is no set to compare, and Grindstone's loop would
        # read an empty record, stop after one round, and compile clean.
        if MILLED_THIS_WAY not in produced:
            raise LoweringError(
                "'cards that share a color were milled this way' with no mill "
                "before it in this effect",
                node=condition,
            )
        if condition.count < 2:
            raise LoweringError(
                "a shared colour is a relation between two or more cards",
                node=condition,
            )
        return {
            "kind": "shared_color_milled_this_way", "count": condition.count,
        }
    if isinstance(condition, ast.RevealedCardHasChosenName):
        # Both producers demanded, for the mill's reason below: without the
        # name the comparison is against nothing and answers False for ever,
        # and without the reveal there is no card to compare — and either way
        # Cursed Scroll would compile clean and never deal its damage.
        missing = sorted({"chosen_card_name", "revealed_card"} - set(produced))
        if missing:
            raise LoweringError(
                "'that card has the chosen name' with no "
                + " and no ".join(
                    {
                        "chosen_card_name": "name chosen",
                        "revealed_card": "reveal",
                    }[key]
                    for key in missing
                )
                + " before it in this effect",
                node=condition,
            )
        return {"kind": "revealed_card_has_chosen_name"}
    if isinstance(condition, ast.RevealedChosenColorCount):
        # "**If that opponent reveals exactly the chosen number of cards of the
        # chosen color**, you draw a card." (Scrying Glass.) *Three* producers,
        # all demanded, which is the rule every back-reference above follows
        # multiplied by the number of records the sentence reads.
        #
        # Each absence fails a different way and all of them silently: with no
        # number the comparison is against nothing, with no colour every card
        # counts or none does, and with no reveal the count is taken over an
        # empty record. Every one of them answers the branch False (or, worse,
        # True on an empty hand) while the card reports itself supported — so
        # the clause refuses here instead, naming what is missing.
        missing = sorted(
            {CHOSEN_NUMBER_THIS_WAY, CHOSEN_COLOR_THIS_WAY, REVEALED_HAND_CARDS}
            - set(produced)
        )
        if missing:
            raise LoweringError(
                "'reveals … the chosen number of cards of the chosen color' "
                "with no "
                + " and no ".join(
                    {
                        CHOSEN_NUMBER_THIS_WAY: "number chosen",
                        CHOSEN_COLOR_THIS_WAY: "colour chosen",
                        REVEALED_HAND_CARDS: "hand revealed",
                    }[key]
                    for key in missing
                )
                + " before it in this effect",
                node=condition,
            )
        return {"kind": "revealed_chosen_color_count", "op": condition.op}
    if isinstance(condition, ast.ChosenNameMilledThisWay):
        # Two producers, both demanded: a back-reference names its producers or
        # refuses. Without the name the comparison is against nothing and
        # answers False for ever; without the mill there is no set to compare
        # it to — and either way the card would compile clean and never draw.
        missing = sorted({"chosen_card_name", MILLED_THIS_WAY} - set(produced))
        if missing:
            raise LoweringError(
                "'a card with the chosen name was milled this way' with no "
                + " and no ".join(
                    {
                        "chosen_card_name": "name chosen",
                        MILLED_THIS_WAY: "mill",
                    }[key]
                    for key in missing
                )
                + " before it in this effect",
                node=condition,
            )
        return {"kind": "chosen_name_milled_this_way"}
    if isinstance(condition, ast.MilledThisWay):
        # "If one or more creature cards were put into that graveyard this
        # way" (Helm of Obedience). The producer is demanded for
        # `ItWas`'s reason above: with no loop in front of it the words name a
        # set nothing wrote, and an unwritten record reads as empty - so the
        # branch would never run and the card would still compile supported.
        if MILLED_THIS_WAY not in produced:
            raise LoweringError(
                "'put into that graveyard this way' with no repeated mill in "
                "this effect",
                node=condition,
            )
        leftover = _restrictions_beyond(
            condition.filter, {"card_types", "is_card", "type_match"}
        )
        if leftover:
            raise LoweringError(
                "the milled-this-way test cannot ask this of a card: "
                + ", ".join(leftover),
                node=condition,
            )
        if not condition.filter.is_card or not condition.filter.card_types:
            raise LoweringError(
                "'put into that graveyard this way' reads a printed card type",
                node=condition,
            )
        # The *condition* kind, which is a different namespace that happens
        # to spell the same words — ``handlers/control_flow`` dispatches on it
        # and never looks it up in ``context.results``. Left as a literal
        # deliberately: swapping in ``MILLED_THIS_WAY`` here would tie two facts
        # together that are only coincidentally equal.
        return {
            "kind": "milled_this_way",
            "card_types": list(condition.filter.card_types),
        }
    if isinstance(condition, ast.SacrificedThisWay):
        # A back-reference names its producer or refuses, as every other "this
        # way" in this function does: with no sacrifice earlier in this effect
        # the record is never written, `evaluate_condition` would quietly answer
        # False, and the card would report supported with a branch that can
        # never run.
        if "sacrificed_cards" not in produced:
            raise LoweringError(
                "'sacrifice … this way' with no sacrifice before it in this "
                "effect",
                node=condition,
            )
        described = card_only_filter(condition.filter.to_payload())
        if described is None:
            # What went is a **card** in a graveyard by the time this is asked
            # (CR 400.7), so only what `_card_matches_filter` can read off a
            # printed line is testable. A phrase reaching past that would be
            # dropped by the matcher and the branch would run for any sacrifice
            # at all — the widening direction, which is the one that must fail.
            raise LoweringError(
                "'sacrifice … this way' names a card the matcher cannot test",
                node=condition,
            )
        return {
            "kind": "sacrificed_this_way_matches",
            "key": "sacrificed_cards",
            "filter": described,
        }
    if isinstance(condition, ast.DiscardedThisWay):
        # A back-reference names its producer or refuses, as every other "this
        # way" in this function does. The record is the count the discard prompt
        # writes when it is answered ("discarded_count"), and an absent one reads
        # as zero — which is exactly what an empty hand leaves, so the branch is
        # skipped rather than run off a discard that never took a card.
        if "discarded_count" not in produced:
            raise LoweringError(
                "'discards a card this way' with no discard before it in this "
                "effect",
                node=condition,
            )
        return {"kind": "it_happened", "key": "discarded_count"}
    if isinstance(condition, ast.DestroyedThisWay):
        # A back-reference names its producer or refuses, as the coin flip above
        # does: with no earlier step of this effect that armed a destruction,
        # "this way" names nothing and `evaluate_condition` would quietly answer
        # False on a card reporting itself supported.
        if "end_of_combat_destruction" not in produced:
            raise LoweringError(
                "'destroyed this way' with no earlier step in this effect that "
                "set up a destruction",
                node=condition,
            )
        if condition.subject.to_payload() != {"type_filter": "creature"}:
            raise LoweringError(
                "'destroyed this way' names what the earlier step marked and "
                "cannot be narrowed further",
                node=condition,
            )
        # Named rather than implied, exactly as the loop over "died this way"
        # names its key: the record is what ties the two sentences together.
        return {"kind": "destroyed_this_way", "key": "end_of_combat_destruction"}
    if isinstance(condition, ast.DamagedBySourceDiedThisTurn):
        # No filter and no event: the relation is to the ability's own source,
        # and the evaluator reads the ledger that permanent carries.
        return {"kind": DAMAGED_BY_SOURCE_DIED}
    if isinstance(condition, ast.DiedThisTurn):
        return {"kind": "died_this_turn", "filter": condition.filter.to_payload()}
    if isinstance(condition, ast.AdditionalCostWasPaid):
        # "**If this spell's additional cost was paid**, …" (Undergrowth.) No
        # symbols in the payload: the card prints "the" additional cost and
        # names none, so the evaluator asks whether *any* offer was taken. A
        # card printing two offers and then asking about "the" one would be a
        # sentence with no referent, and the reading that guessed which is the
        # one that silently answers about the wrong price — so this stays the
        # unqualified question and the counted form beside it carries symbols.
        return {"kind": "additional_cost_paid"}
    if isinstance(condition, ast.ReturnedToHandThisTurn):
        return {"kind": "returned_to_hand_this_turn"}
    if isinstance(condition, ast.HadPlus1Counter):
        return {"kind": "had_plus1_counter"}
    if isinstance(condition, ast.HadNamedCounter):
        # The counter word is payload the whole way down, exactly as it is for
        # ``SourceExiledWithCounter`` below — a card printing a differently
        # named counter needs nothing here.
        return {"kind": "had_named_counter", "counter": condition.counter}
    if isinstance(condition, ast.SourceAbilityActivations):
        # The number and the comparison travel; what they are measured against
        # is the per-turn activation ledger `engine/activation_restrictions.py`
        # keeps, which the evaluator reads through that module's own accessor
        # rather than off the metadata key — one reader, so the refusal a
        # printed cap makes and the question this clause asks cannot come to
        # disagree about how many activations there have been.
        return {
            "kind": "source_ability_activations",
            "count": condition.count,
            "comparison": condition.comparison,
        }
    if isinstance(condition, ast.ManaAddedWithThisAbility):
        # The polarity travels; what it is measured against is the per-turn
        # stamp ``engine/mana_ability_records.py`` keeps, which the evaluator
        # reads through that module's own accessor rather than off the metadata
        # key — one reader, beside the one write site, so the note this
        # ability makes and the question it asks cannot come to disagree.
        #
        # The **record name** travels too, and it is the same constant the
        # mana instruction is stamped with (``MANA_ADDED_WITH_THIS_ABILITY``):
        # the two halves of this card are lowered from one ability node, and
        # naming the record in the payload is what lets a later card print a
        # second such clause without either half guessing which note it meant.
        from ...mana_ability_records import MANA_ADDED_WITH_THIS_ABILITY

        return {
            "kind": "mana_added_with_this_ability",
            "record": MANA_ADDED_WITH_THIS_ABILITY,
            "negated": condition.negated,
        }
    if isinstance(condition, ast.AttackedOrBlockedThisCombat):
        # No payload for the sibling's reason: the sentence names no side of
        # the combat and no other window, and the object is the ability's own
        # source. The evaluator reads the answer the fire site froze.
        return {"kind": "attacked_or_blocked_this_combat"}
    if isinstance(condition, ast.CameUnderControlSinceLastUpkeep):
        # CR 702.30a. No payload, for the sibling below's reason exactly: the
        # sentence names no seat other than "your" — the ability's controller,
        # which the evaluator has — no object other than the ability's own
        # source, and no window but the one the production spelled out in full.
        return {"kind": "came_under_your_control_since_your_last_upkeep"}
    if isinstance(condition, ast.InABlockSinceLastUpkeep):
        # No payload: the sentence names no seat, no side of the block and no
        # other window. "Your" is the ability's controller, which the evaluator
        # has, and the source is the object the condition is about.
        return {"kind": "in_a_block_since_your_last_upkeep"}
    if isinstance(condition, ast.DealtDamageThisTurn):
        # The recipient rides the payload, exactly as the seat does on the life
        # clause below: "…to a player" is the same question asked of a wider
        # set of seats, not a second condition.
        return {
            "kind": "dealt_damage_this_turn",
            "who": condition.recipient,
        }
    if isinstance(condition, ast.SeatWasDealtDamageThisTurn):
        # Whose opponents, as the referent the evaluator resolves — the seat the
        # firing event was about, or the ability's controller. Payload for the
        # reason the recipient above is: the two spellings are one question
        # asked about two seats.
        return {
            "kind": "seat_dealt_damage_this_turn",
            "opponents_of": condition.who,
        }
    if isinstance(condition, ast.SeatCastSpellThisTurn):
        # The seat and the sign both ride the payload, for the reason the two
        # conditions above do: "that player didn't cast a spell" and "you cast a
        # spell" are one question with two referents and two signs, and a kind
        # per combination is four kinds for one record.
        return {
            "kind": "seat_cast_spell_this_turn",
            "who": condition.who,
            "negated": bool(condition.negated),
        }
    if isinstance(condition, ast.LifeGainedThisTurn):
        # The seat rides the payload rather than being baked into the kind, so
        # "if an opponent gained…" is the same condition with a different `who`
        # the day a card prints it.
        return {
            "kind": "life_gained_this_turn",
            "who": condition.who.kind,
            "amount": condition.amount,
        }
    raise LoweringError(
        f"no lowering for condition {type(condition).__name__}", node=condition
    )
