"""How a printed condition becomes the payload an evaluator reads.

The lowering-side mirror of ``ast/conditions.py``, split from ``_common`` at the
same guard and on the same reasoning: `_common` is the *shape a payload takes* —
target descriptions, filter payloads, amount encoding — while this is one
question with one answer, "what does this clause test?", asked by the trigger
head (CR 603.4's intervening-if), by a sentence-level ``Conditional``, and by a
static's own condition.

Shared rather than a family, and named beside `_common` in the layering guard's
tuple for the reason `_events` is: three callers in three different places read
it, and a condition living in one family would couple the rest to that family.

What the evaluator does with the payload is `engine/handlers/control_flow.py`'s
``evaluate_condition``. The pair is the usual arrangement here — a gate and a
dispatch that must read one rule — and the refusals below are what keep it: a
condition this file cannot describe refuses the line rather than lowering onto a
payload the evaluator would answer False to forever.
"""

from __future__ import annotations

from ...damage_deaths import DAMAGED_BY_SOURCE_DIED
from ...oracle_types import MILLED_THIS_WAY
from .. import ast
from ..errors import LoweringError
from ...subject_filters import card_only_filter, untestable_filter_keys
from ._common import _filter_payload, _is_enchanted, _restrictions_beyond
from ._events import (ATTACHED_PERMANENT_CONTROLLER, _EVENT_SUBJECT_PLAYERS, COUNTED_NUMBER,
                      EVENT_SUBJECT_PLAYER)

#: What ``targets.kind`` on a guarded effect says the pronoun "it" names, and
#: therefore which half of the resolution context answers a question about it.
#: A closed map: a target kind not in it leaves the referent unbound, and an
#: unbound referent refuses rather than picking one.
_PRONOUN_REFERENTS: dict[str, str] = {"spell": "spell", "object": "permanent"}


def pronoun_target_referent(instructions) -> str | None:
    """Which object "it" names, read off the effect the clause guards.

    "Counter target spell **if it's red**" and "Destroy target permanent **if
    it's red**" (Hydroblast, Pyroblast) print the identical condition about two
    different kinds of object — a spell on the stack and a permanent on the
    battlefield — which are resolved from different halves of the resolution
    context. Nothing in the condition's own words separates them, so the
    referent is taken from the branch beside it: CR 608.2c makes the
    instruction and its "if" one sentence, and this is the only place both are
    in view.

    Deliberately strict. One instruction, one recognized target kind, or None —
    and None refuses at the caller. A resolver picked by trying one half of the
    context and then the other would answer about whichever object happened to
    be there, which is the "the branch and the effect disagree about which
    object the pronoun meant" bug the keyword condition beside it already
    names.
    """
    if len(instructions) != 1:
        return None
    described = instructions[0].payload.get("targets") or {}
    return _PRONOUN_REFERENTS.get(described.get("kind"))


def _condition_seat(condition, player, event, what: str) -> str:
    """Which seat a condition's player reference names, as a payload word.

    "…**if that player** controls a Plains" (Spiritual Sanctuary) was the card
    that made this a function rather than a default. Left as "that_player" it
    reached `evaluate_condition`'s fallback, which scans *every* player — so the
    card asked "does anybody control a Plains", answered yes off the opponent's
    board and gave the life away on a condition its own controller had met.
    Silent in both directions and invisible from the card.

    So the referent is resolved **here**, where the firing event is known, and
    a trigger that froze no seat refuses the clause rather than guessing. Three
    conditions ask it now — a board count, a zone count and a life total — and
    one reader is what keeps them from disagreeing about a pronoun.
    """
    kind = player.kind
    if kind != "that_player":
        return kind
    if event not in _EVENT_SUBJECT_PLAYERS:
        raise LoweringError(
            f"'that player' names no seat under this trigger, so this {what} "
            "cannot be asked",
            node=condition,
        )
    return EVENT_SUBJECT_PLAYER


#: The events that freeze the object "the same name" is compared against.
#: Only a cast trigger does today (``cast_card`` in the trigger's context), and
#: the set is the gate rather than a comment: a condition asking about a name
#: nobody recorded answers False forever, which is an ability that never fires.
_SAME_NAME_EVENTS = frozenset({"player_casts_spell", "spell_cast"})


def _lower_condition(
    condition: ast.Condition,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
    referent: str | None = None,
) -> dict[str, object]:
    """*produced* names the scratchpad values earlier steps of this same effect
    recorded. It defaults to empty, which is what refuses a coin-flip condition
    on an intervening-if (CR 603.4): that condition is checked when the trigger
    would fire, where no flip of this resolution can have happened yet.

    *event* is the firing trigger's condition kind, threaded for the same reason
    the effect lowerings take it: "that player" is only a resolvable referent
    when the event named a player, and which events do is
    :data:`_EVENT_SUBJECT_PLAYERS` rather than a rule.

    *referent* is :func:`pronoun_target_referent`'s answer for the effect this
    condition guards — what "it" names. Only the conditional lowering can supply
    it, so every other caller leaves it None and the clauses that need one
    refuse there.
    """
    if isinstance(condition, ast.SelfInGraveyardWithCardsAbove):
        # CR 113.6b and CR 404.3 in one payload. ``functions_from`` is the same
        # derived key ``lowering/returns.py`` stamps from a printed "from your
        # graveyard" (CR 113.6m) and ``engine/events.py``'s graveyard scan
        # reads — declared here because on these cards the *condition* is the
        # only place the zone is named at all, and an ability nothing scans for
        # is one that compiles clean and never fires.
        #
        # It rides the condition payload rather than being stamped on the
        # instruction here: this function returns a condition, and the
        # instruction it guards is assembled a layer up (``lower.py``), which is
        # the only place both are in view.
        return {
            "kind": "self_in_graveyard_with_cards_above",
            "card_type": condition.card_type,
            "count": condition.count,
            "op": "ge" if condition.at_least else "eq",
            "directly": condition.directly,
            "functions_from": "graveyard",
        }
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
    if isinstance(condition, ast.AttackersAimedAtYou):
        # The batch rides the trigger's captured context — the fire site records
        # how many of the declared attackers are aimed at this permanent's
        # controller — rather than being recounted at resolution, where combat
        # may already have moved on (CR 603.4 checks the condition when the
        # trigger would fire *and* again on resolution, and both readings want
        # the number the declaration had).
        return {"kind": "attackers_aimed_at_you", "count": condition.count}
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
    if isinstance(condition, ast.ItIsColor):
        # "Counter target spell **if it's red**." (Hydroblast, Pyroblast.) The
        # pronoun names the object this effect targets, the same referent the
        # keyword clause below reads — and under a trigger it names the event's
        # subject instead, which nothing here can tell apart, so it refuses
        # there for that clause's reason.
        if event is not None:
            raise LoweringError(
                "'it' names no chosen target under this trigger", node=condition
            )
        if referent is None:
            # No branch to read the referent off, or a branch that targets
            # something this cannot ask about. Refusing is what keeps the
            # condition from being answered about the wrong half of the
            # resolution context — silently, and forever the same way.
            raise LoweringError(
                "'it' has no target to be a colour of here", node=condition
            )
        return {
            "kind": "target_is_color",
            "color": condition.color,
            "negated": condition.negated,
            "target": referent,
        }
    if isinstance(condition, ast.ObjectHasKeyword):
        # "If **it** doesn't have rampage" (Rapid Fire). The pronoun names the
        # object the sentence in front of it chose — which for a spell or an
        # activated ability is its target, and that is the referent the rider
        # that admitted this clause already bound the *grant* half to.
        #
        # Under a trigger it is not: "it" there most often names the event's
        # subject, and nothing here can tell the two apart — so the clause
        # refuses rather than asking the question of the wrong permanent, which
        # is a branch that would take silently.
        if event is not None:
            raise LoweringError(
                "'it' names no chosen target under this trigger", node=condition
            )
        return {
            "kind": "target_has_keyword",
            "keywords": list(condition.keywords),
            "negated": condition.negated,
        }
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
        if "discarded_cards" not in produced:
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
    if isinstance(condition, ast.BlockersOfBoundCreature):
        # "that creature" is the creature the *firing event* named, and only a
        # block event names one. Under anything else the referent is nothing —
        # the evaluator would read an absent context key and answer False
        # forever while the card compiled clean, which is the silent gate this
        # whole file exists to refuse. `creature_blocks` alone, and deliberately
        # narrow: the "becomes blocked by" half of the joined sentence records
        # the *blocker*, not what was blocked, so it cannot answer this clause.
        if event != "creature_blocks":
            raise LoweringError(
                "'that creature' names nothing that was blocked under this "
                "trigger",
                node=condition,
            )
        return {
            "kind": "blockers_of_bound_creature",
            "filter": condition.filter.to_payload(),
            "op": condition.comparison.op,
            "count": condition.comparison.value.value,
        }
    if isinstance(condition, ast.EveryOf):
        # Lowered whole rather than folded into one flattened payload: each part
        # keeps its own kind, so a conjunction of two *different* condition
        # kinds costs nothing extra here or in the evaluator.
        return {
            "kind": "all_of",
            "conditions": [
                # The referent travels down with the rest: "it" means the same
                # object in every part of one printed "if", so a conjunction
                # that dropped it would refuse a clause the same sentence
                # answers on its own.
                _lower_condition(part, produced, event, referent)
                for part in condition.conditions
            ],
        }
    if isinstance(condition, ast.SomeOf):
        # The disjunction twin of the conjunction above, and lowered the same
        # way for the same reason: each part keeps its own kind, so joining two
        # *different* condition kinds with "or" costs nothing here or in the
        # evaluator.
        return {
            "kind": "any_of",
            "conditions": [
                _lower_condition(part, produced, event, referent)
                for part in condition.conditions
            ],
        }
    if isinstance(condition, ast.SameNamedObject):
        # "a card **with the same name** is in a graveyard" (Bazaar of Wonders).
        # The name is the *firing event's* — CR 201.2 compared against the spell
        # the trigger fired on — so this refuses under any event that does not
        # freeze one. An unfrozen name reads as no name at all, which would make
        # the condition answer False on every board and turn Bazaar's counter
        # into an ability that never fires: a card compiling supported and doing
        # nothing, which is the failure this whole file's gates exist for.
        if event not in _SAME_NAME_EVENTS:
            raise LoweringError(
                f"no event named {event!r} freezes the name 'the same name' "
                "compares against"
            )
        return {
            "kind": "same_named_object",
            "zone": condition.zone,
            "nontoken": bool(condition.nontoken),
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
    if isinstance(condition, ast.OnBattlefield):
        # No seat travels down: the payload names the zone and the noun phrase,
        # and the evaluator counts the board. The comparison is always set by
        # the production (the quantifier *is* the comparison), so there is no
        # unbounded reading to fall back to here.
        if condition.comparison.op in ("even", "odd"):
            # "if the number of permanents is even" (Chaos Lord). A parity
            # prints no threshold, so no ``count`` is emitted: a zero carried
            # here would be a number the evaluator could read as one, and
            # `_compare_count` answers the parity before it looks.
            return {
                "kind": "on_battlefield",
                "filter": condition.filter.to_payload(),
                "op": condition.comparison.op,
            }
        return {
            "kind": "on_battlefield",
            "filter": condition.filter.to_payload(),
            "count": condition.comparison.value.value,
            "op": condition.comparison.op,
        }
    if isinstance(condition, ast.Controls):
        who = _condition_seat(condition, condition.who, event, "board count")
        payload = {
            "kind": "controls",
            "who": who,
            "filter": condition.filter.to_payload(),
        }
        if condition.comparison is not None and isinstance(condition.comparison.value, ast.Fixed):
            payload["count"] = condition.comparison.value.value
            payload["op"] = condition.comparison.op
        if condition.shared_name:
            # The threshold is what the relation is *for*: "permanents with the
            # same name as one another" with no number would be read as
            # "count > 0" downstream and hold for a single permanent, which is
            # the opposite of what the words say. No card prints it that way, so
            # it refuses rather than picking a number the text did not print.
            if "count" not in payload:
                raise LoweringError(
                    "'with the same name as one another' needs the printed "
                    "threshold it qualifies",
                    node=condition,
                )
            payload["shared_name"] = True
        return payload
    if isinstance(condition, ast.SubjectCharacteristicIs):
        # The bound must be a printed number: the evaluator compares an integer,
        # and an X or a board count would be compared against a node. Refused
        # rather than coerced, so the day a card prints one the gate is visibly
        # missing instead of silently answering about the wrong quantity.
        if not isinstance(condition.comparison.value, ast.Fixed):
            raise LoweringError(
                "a characteristic gate compares against a printed number",
                node=condition,
            )
        # Which object is asked is payload, and only two answers exist because
        # only two objects a resolution can name without a second choice: the
        # ability's own source (Lesser Werewolf) and the target the clause
        # itself announced (Blood Lust). A subject that is neither describes a
        # permanent nothing looks up, so it refuses rather than being answered
        # about whichever object the resolver happened to hold.
        subject = condition.subject
        if isinstance(subject, ast.TargetSpec) and subject.targeted:
            asked = "target"
        elif isinstance(subject, ast.TargetSpec) and subject.filter.is_source:
            asked = "source"
        else:
            raise LoweringError(
                "a characteristic gate asks about the source or about its own "
                "target",
                node=condition,
            )
        return {
            "kind": "subject_characteristic_is",
            "subject": asked,
            "characteristic": condition.characteristic,
            "op": condition.comparison.op,
            "count": condition.comparison.value.value,
        }
    if isinstance(condition, ast.IsState):
        payload = {
            "kind": "is_state",
            "state": condition.state,
            "negated": condition.negated,
        }
        # "…if **it** didn't attack this turn" on an Aura (Aggression): the
        # pronoun was rebound to the permanent the source is attached to, and
        # the evaluator has to ask that permanent rather than the Aura. Which
        # object, as payload — the question and the reading are identical.
        if _is_enchanted(condition.subject):
            payload["subject"] = "attached"
        return payload
    if isinstance(condition, ast.SourceOnBattlefield):
        # "if this enchantment is on the battlefield" (Tombstone Stairwell).
        # The evaluator asks the game which zone the source is in, so a rebound
        # pronoun — an Aura's "it", meaning the creature it enchants — would be
        # answered about the wrong object. Refused rather than answered: no
        # card in the pool prints that reading, and guessing would make a
        # CR 603.4 gate open on somebody else's permanent.
        if _is_enchanted(condition.subject):
            raise LoweringError(
                "\"on the battlefield\" is asked of the ability's own source",
                node=condition,
            )
        return {"kind": "source_on_battlefield", "negated": condition.negated}
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
    if isinstance(condition, ast.ZoneHasCards):
        # "If your library has ten or more cards in it" (Phyrexian Portal); "if
        # that player has five or more cards in hand" (Misers' Cage). The seat
        # is carried rather than defaulted: a wording naming somebody else's
        # pile is a question about a different deck, and a condition answered
        # about the wrong one is a gate that opens when it should not.
        bound = condition.comparison.value
        if not isinstance(bound, ast.Fixed):
            raise LoweringError(
                "a zone count compares against a printed number", node=condition
            )
        return {
            "kind": "zone_card_count",
            "player": _condition_seat(condition, condition.player, event, "zone count"),
            "zone": condition.zone,
            "op": condition.comparison.op,
            "value": bound.value,
        }
    if isinstance(condition, ast.PlayerLifeIs):
        # "If that player has 5 or less life" (Razor Pendulum). The twin of the
        # zone count above, and it shares the seat reader for the reason the
        # seat reader exists: "that player" means the seat the firing event
        # froze, and a clause that fell back to "you" would ask about the wrong
        # life total without failing.
        bound = condition.comparison.value
        if not isinstance(bound, ast.Fixed):
            raise LoweringError(
                "a life gate compares against a printed number", node=condition
            )
        return {
            "kind": "player_life",
            "player": _condition_seat(condition, condition.player, event, "life gate"),
            "op": condition.comparison.op,
            "value": bound.value,
        }
    if isinstance(condition, ast.LifeTotalDifference):
        # "If the difference between your life total and target player's life
        # total is 5 or less" (Psychic Transfer). Two seats through the *same*
        # reader the one-seat gate above uses, so a pronoun means the same
        # thing in both — and both are carried, because the number compared is
        # the distance between them and belongs to neither.
        bound = condition.comparison.value
        if not isinstance(bound, ast.Fixed):
            raise LoweringError(
                "a life-difference gate compares against a printed number",
                node=condition,
            )
        return {
            "kind": "life_total_difference",
            "player": _condition_seat(
                condition, condition.first, event, "life-difference gate"
            ),
            "other": _condition_seat(
                condition, condition.second, event, "life-difference gate"
            ),
            "op": condition.comparison.op,
            "value": bound.value,
        }
    if isinstance(condition, ast.ChosenNameMilledThisWay):
        # Two producers, both demanded: a back-reference names its producers or
        # refuses. Without the name the comparison is against nothing and
        # answers False for ever; without the mill there is no set to compare
        # it to — and either way the card would compile clean and never draw.
        missing = sorted(
            {"chosen_card_name", MILLED_THIS_WAY} - set(produced)
        )
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
    if isinstance(condition, ast.SourceExiledWithCounter):
        # The counter word is payload the whole way down, so a card printing a
        # differently-named counter needs nothing here.
        return {"kind": "source_exiled_with_counter", "counter": condition.counter}
    if isinstance(condition, ast.SourceCounterCount):
        return {
            "kind": "source_counter_count",
            "counter": condition.counter,
            "count": condition.count,
            "comparison": condition.comparison,
        }
    if isinstance(condition, ast.AttachedCounterCount):
        # "if **that creature** has three or more +1/+0 counters on it"
        # (Consuming Ferocity). The host, read at resolution off the
        # attachment, which is why the printed subject is the whole of what
        # this carries: the counter kind and the threshold are the card's, and
        # the object is always the one the Aura is on.
        #
        # "That creature" names it only because the step in front named it, and
        # that is checked here rather than trusted: with no such step the words
        # name nothing, and a condition that answered off the attachment anyway
        # would be reading a card that never said "enchanted".
        if condition.bound and ATTACHED_PERMANENT_CONTROLLER not in produced:
            raise LoweringError(
                "\"that creature\" names an object no step of this effect "
                "attached to",
                node=condition,
            )
        return {
            "kind": "attached_counter_count",
            "counter": condition.counter,
            "count": condition.count,
            "comparison": condition.comparison,
        }
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
    if isinstance(condition, ast.AttackedOrBlockedThisCombat):
        # No payload for the sibling's reason: the sentence names no side of
        # the combat and no other window, and the object is the ability's own
        # source. The evaluator reads the answer the fire site froze.
        return {"kind": "attacked_or_blocked_this_combat"}
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
    if isinstance(condition, ast.LifeGainedThisTurn):
        # The seat rides the payload rather than being baked into the kind, so
        # "if an opponent gained…" is the same condition with a different `who`
        # the day a card prints it.
        return {
            "kind": "life_gained_this_turn",
            "who": condition.who.kind,
            "amount": condition.amount,
        }
    if isinstance(condition, ast.TurnIsYours):
        # "During your turn" / "During turns other than yours" (Vibrating
        # Sphere). ``engine/static_bonuses.conditional_static_holds`` already
        # answers ``your_turn`` for the derivation table's spelling of the same
        # clause (Radha, Heart of Keld), so this is that payload with the
        # printed negation carried beside it rather than a second kind — one
        # evaluator, so the two front ends cannot disagree about whose turn it
        # is.
        payload: dict[str, object] = {"kind": "your_turn"}
        if condition.negated:
            payload["negated"] = True
        return payload
    raise LoweringError(f"no lowering for condition {type(condition).__name__}", node=condition)
