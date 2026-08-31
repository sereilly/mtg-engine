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

from .. import ast
from ..errors import LoweringError
from ...subject_filters import untestable_filter_keys
from ._common import _filter_payload, _is_enchanted, _restrictions_beyond
from ._events import _EVENT_SUBJECT_PLAYERS, EVENT_SUBJECT_PLAYER

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
            raise LoweringError(
                "'it' with nothing in this effect that revealed a card",
                node=condition,
            )
        leftover = _restrictions_beyond(
            condition.filter, {"card_types", "is_card", "type_match"}
        )
        if leftover:
            raise LoweringError(
                "the revealed-card test cannot ask this of a card: "
                + ", ".join(leftover),
                node=condition,
            )
        if not condition.filter.card_types:
            raise LoweringError(
                "'it's …' reads a card's printed type line", node=condition
            )
        payload = {
            "kind": "revealed_card_is",
            "card_types": list(condition.filter.card_types),
            "type_match": condition.filter.type_match,
        }
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
    if isinstance(condition, ast.OnBattlefield):
        # No seat travels down: the payload names the zone and the noun phrase,
        # and the evaluator counts the board. The comparison is always set by
        # the production (the quantifier *is* the comparison), so there is no
        # unbounded reading to fall back to here.
        return {
            "kind": "on_battlefield",
            "filter": condition.filter.to_payload(),
            "count": condition.comparison.value.value,
            "op": condition.comparison.op,
        }
    if isinstance(condition, ast.Controls):
        who = condition.who.kind
        # "…**if that player** controls a Plains" (Spiritual Sanctuary). Left as
        # "that_player" this reached `evaluate_condition`'s fallback, which
        # scans *every* player — so the card asked "does anybody control a
        # Plains", answered yes off the opponent's board and gave the life away
        # on a condition its own controller had met. Silent in both directions
        # and impossible to see from the card, which is why the referent is
        # resolved here, where the event is known, rather than guessed there.
        if who == "that_player":
            if event not in _EVENT_SUBJECT_PLAYERS:
                raise LoweringError(
                    "'that player' names no seat under this trigger", node=condition
                )
            who = EVENT_SUBJECT_PLAYER
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
    if isinstance(condition, ast.DiedThisTurn):
        return {"kind": "died_this_turn", "filter": condition.filter.to_payload()}
    if isinstance(condition, ast.ReturnedToHandThisTurn):
        return {"kind": "returned_to_hand_this_turn"}
    if isinstance(condition, ast.HadPlus1Counter):
        return {"kind": "had_plus1_counter"}
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
