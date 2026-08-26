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
from ._common import _filter_payload, _restrictions_beyond
from ._events import _EVENT_SUBJECT_PLAYERS, EVENT_SUBJECT_PLAYER

def _lower_condition(
    condition: ast.Condition,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> dict[str, object]:
    """*produced* names the scratchpad values earlier steps of this same effect
    recorded. It defaults to empty, which is what refuses a coin-flip condition
    on an intervening-if (CR 603.4): that condition is checked when the trigger
    would fire, where no flip of this resolution can have happened yet.

    *event* is the firing trigger's condition kind, threaded for the same reason
    the effect lowerings take it: "that player" is only a resolvable referent
    when the event named a player, and which events do is
    :data:`_EVENT_SUBJECT_PLAYERS` rather than a rule.
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
        return {
            "kind": "revealed_card_is",
            "card_types": list(condition.filter.card_types),
            "type_match": condition.filter.type_match,
        }
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
    if isinstance(condition, ast.EveryOf):
        # Lowered whole rather than folded into one flattened payload: each part
        # keeps its own kind, so a conjunction of two *different* condition
        # kinds costs nothing extra here or in the evaluator.
        return {
            "kind": "all_of",
            "conditions": [
                _lower_condition(part, produced, event)
                for part in condition.conditions
            ],
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
    if isinstance(condition, ast.SubjectPowerIs):
        # The bound must be a printed number: the evaluator compares an integer,
        # and an X or a board count would be compared against a node. Refused
        # rather than coerced, so the day a card prints one the gate is visibly
        # missing instead of silently answering about the wrong quantity.
        if not isinstance(condition.comparison.value, ast.Fixed):
            raise LoweringError(
                "the power gate compares against a printed number",
                node=condition,
            )
        return {
            "kind": "source_power_is",
            "op": condition.comparison.op,
            "count": condition.comparison.value.value,
        }
    if isinstance(condition, ast.IsState):
        return {"kind": "is_state", "state": condition.state, "negated": condition.negated}
    if isinstance(condition, ast.DiedThisTurn):
        return {"kind": "died_this_turn", "filter": condition.filter.to_payload()}
    if isinstance(condition, ast.ReturnedToHandThisTurn):
        return {"kind": "returned_to_hand_this_turn"}
    if isinstance(condition, ast.HadPlus1Counter):
        return {"kind": "had_plus1_counter"}
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
    raise LoweringError(f"no lowering for condition {type(condition).__name__}", node=condition)
