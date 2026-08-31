"""How much damage a clause computes, and which seat it lands on.

A **floor**, not a family: `damage.py` reads it and it reads nothing back, and
inside `lowering/` a module a family imports has to sit below the families
(`ast/_primitives.py` is a floor for the same reason, one package over). The direction
cannot be reversed either — `_lower_halved_damage` stays in `damage.py` because
it lowers the quantity *underneath* by re-entering the damage lowering, which is
the one amount that has to know about the shapes.

Split out of `damage.py` at the 1,000-line guard, along the line CR 107.2/107.3
already draw: a printed quantity that is **counted** — off a board, out of the
resolution's own scratchpad, or off a cast the player picked — against the
sentence that spends it. The handlers these lower to perform the whole
arithmetic themselves, which is why the noun phrase counted *is* each one's
contract and a filter that differs in any way must refuse rather than count the
wrong thing.

`_damaged_player_is` sits here rather than in `damage.py` for the reason a
fragment ever moves down: the counted amounts ask it and so does the pay-or-else
prompt left behind, and a predicate two modules need is not one module's
property.
"""

import dataclasses

from ...oracle_types import (
    DISCARDED_BY_SEAT, OracleInstruction, X_FROM_COUNT,
    X_FROM_COUNT_PER_RECIPIENT,
)
from .. import ast
from ..errors import LoweringError
from ._common import _describe_targets, _is_target, dropped_narrowings
from ._events import (CHOSEN_CAST_DAMAGE, CHOSEN_PLAYER,
                      EVENT_SUBJECT_PLAYER, _EVENT_SUBJECT_PLAYERS)


# Counted damage whose arithmetic a dedicated handler performs in full. Keyed
# by the exact noun phrase counted, because that phrase *is* the handler's
# contract: `_on__upkeep_each__deal_damage_equal_to_swamps` counts the Swamps
# controlled by the player whose upkeep is resolving and reads an empty payload,
# so a filter that differs in any way — a different land type, a different
# controller — has no handler and must refuse rather than count the wrong thing.
_SWAMPS_THEY_CONTROL = ast.ObjectFilter(subtypes=("swamp",), controller="that_player")

# Named board counts (ast.BoardCount) mapped to the instruction that computes
# them. `deal_damage` appears here for `untapped_lands_at_turn_start` because
# that is genuinely how the engine encodes Power Surge today: the upkeep
# handlers read `amount == "x"` as "untapped lands the player controlled at the
# start of this turn" (engine/phases/upkeep_effects.py). The coupling is
# implicit in the handler, so it is written down here rather than left to be
# rediscovered — and it is the reason an unnamed X may never lower to this kind.
_BOARD_COUNT_DAMAGE: dict[str, tuple[str, dict[str, object]]] = {
    # The direction is payload on the legacy side, so the grammar carries it
    # too — the differential compares payloads, and a bare {} here would report
    # a disagreement rather than a match. The *threshold* is no longer written
    # here: it comes off ``BoardCount.base``, because Black Vise's 4 and The
    # Rack's 3 are one arithmetic with one number changed.
    "cards_in_hand_over_base": (
        "upkeep_chosen_player_hand_overflow_damage",
        {"direction": "overflow"},
    ),
    # The mirror, and the branch the handler has computed since Black Vise
    # landed while nothing in the grammar could reach it (The Rack got there
    # through a card hook instead).
    "base_over_cards_in_hand": (
        "upkeep_chosen_player_hand_overflow_damage",
        {"direction": "deficit"},
    ),
    "untapped_lands_at_turn_start": ("deal_damage", {"amount": "x"}),
}

# Board counts whose handler needs the constant the phrase captured. Named
# rather than inferred from ``base is not None``: a count that grew an optional
# constant would otherwise start silently forwarding it to a handler that reads
# no such key.
_BOARD_COUNTS_WITH_BASE = frozenset(
    {"cards_in_hand_over_base", "base_over_cards_in_hand"}
)


# Recipients that are a *list of seats* rather than one. "…equal to the number
# of Islands **that player** controls" (Typhoon) is counted once per seat, so
# the phrase is only lowerable onto a handler branch that loops — these two —
# and refuses anywhere else rather than counting the caster's Islands and
# dealing one number to everybody.
_LOOPED_PLAYER_RECIPIENTS = frozenset({"each_player", "each_opponent"})


def _per_recipient_count(node: ast.DealDamage) -> dict | None:
    """The count spec for "…equal to the number of <filter> **that player**
    controls", or None when the clause does not narrow to the recipient.

    The controller narrowing is stripped before :func:`count_spec` sees it, for
    the reason that function refuses it: nothing downstream tests a controller
    key, so the count has to be *scoped* to a player instead of *filtered* by
    one. Scoping it is exactly what the per-recipient loop does.
    """
    assert isinstance(node.amount, ast.CountOf)
    filt = node.amount.filter
    if filt.controller != "that_player":
        return None
    if filt.zone_owner is not None:
        # The phrase would then name two different players — the zone's owner
        # and "that player" — and only one of them can be the recipient.
        raise LoweringError(
            "a per-recipient count cannot also name a zone owner", node=node
        )
    spec = count_spec(dataclasses.replace(filt, controller=None), node)
    # `owner` is how the *single*-X evaluator picks a seat, and this spec is
    # never read through that path — the loop hands it each recipient directly.
    # Dropped rather than left saying "you", which is the one seat the phrase
    # certainly does not mean.
    spec.pop("owner", None)
    return spec


def _damaged_player_is(recipients: tuple[ast.Recipient, ...], kind: str) -> bool:
    """Whether the damage lands on exactly one player reference of *kind*."""
    return (
        len(recipients) == 1
        and isinstance(recipients[0], ast.PlayerRef)
        and recipients[0].kind == kind
    )


def _lower_counted_damage(
    node: ast.DealDamage, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"…deals damage to that player equal to the number of Swamps they control."
    (Karma.)

    Both halves are checked, not just the count: the handler damages the player
    whose upkeep is resolving, so lowering a clause that damages someone else
    onto it would hit the wrong seat while the card still reported as supported.
    """
    assert isinstance(node.amount, ast.CountOf)
    if (
        node.amount.filter == _SWAMPS_THEY_CONTROL
        and _damaged_player_is(node.recipients, "that_player")
        and node.riders == ast.DamageRiders()
    ):
        return (OracleInstruction("deal_damage_equal_to_swamps", "", {}),)
    # "…deals damage to any target equal to the number of Dogs you control."
    # (Rin and Seri, Inseparable.) The general form, through the one counting
    # evaluator every other computed amount already uses — Karma's fused kind
    # above stays because its *recipient* is the upkeep's player rather than a
    # chosen target, which is not something this shape can express.
    if node.riders != ast.DamageRiders():
        raise LoweringError("a counted damage carries no riders yet", node=node)
    if len(node.recipients) != 1:
        raise LoweringError("a counted damage reaches one recipient", node=node)
    recipient = node.recipients[0]
    # "…deals damage to each opponent equal to the number of Islands **that
    # player** controls" (Typhoon). One number per seat, so it travels on its
    # own key and only onto the two recipients whose handler branch loops.
    if isinstance(recipient, ast.PlayerRef):
        per_recipient = _per_recipient_count(node)
        if per_recipient is not None:
            # "At the beginning of **each player's** upkeep, this enchantment
            # deals damage to **that player** equal to the number of snow lands
            # **they** control." (Cold Snap.) Not a loop at all: the recipient
            # and the counted board are the *same single seat*, the one the
            # firing event froze (CR 603.10), so there is one number and it is
            # taken on that seat's battlefield. The two halves are checked
            # together for `_lower_counted_damage`'s own stated reason — a
            # clause counting one player's board while damaging another's face
            # has no handler, and admitting it is how a supported card hits the
            # wrong seat.
            if (
                recipient.kind == "that_player"
                and event in _EVENT_SUBJECT_PLAYERS
            ):
                return (
                    OracleInstruction(
                        "deal_damage", "",
                        {
                            "amount": "x",
                            "recipient": EVENT_SUBJECT_PLAYER,
                            X_FROM_COUNT: {
                                **per_recipient, "owner": EVENT_SUBJECT_PLAYER,
                            },
                        },
                    ),
                )
            if recipient.kind not in _LOOPED_PLAYER_RECIPIENTS:
                raise LoweringError(
                    "no handler counts this damage per recipient", node=node
                )
            return (
                OracleInstruction(
                    "deal_damage", "",
                    {
                        "recipient": recipient.kind,
                        X_FROM_COUNT_PER_RECIPIENT: per_recipient,
                    },
                ),
            )
    # "any target" (CR 115.4) is a quantifier of its own, not a narrower
    # "target": it admits a player, a planeswalker or a creature, which is
    # exactly what `deal_damage`'s resolver already picks between.
    if not (
        _is_target(recipient)
        or (isinstance(recipient, ast.TargetSpec)
            and recipient.quantifier == "any_target")
        or (isinstance(recipient, ast.PlayerRef)
            and recipient.kind in ("target_player", "target_opponent"))
        # "Target player reveals their hand. … deals damage to **that player**
        # equal to the number of white cards in **their** hand." (Inquisition.)
        # Admitted only when the count is taken in *that same player's* zone,
        # and that is a property of the handler rather than a courtesy: it
        # resolves exactly one seat off the resolution context, and uses it both
        # as the damage's recipient and as the counted zone's owner. A clause
        # naming two different seats — "damage to that player equal to the
        # number of Swamps **you** control" — has no handler at all, and
        # admitting it would count one player's board and damage the other's
        # face on a card reporting itself supported.
        or (_damaged_player_is(node.recipients, "that_player")
            and node.amount.filter.zone_owner is not None
            and node.amount.filter.zone_owner.kind != "you")
    ):
        raise LoweringError("no handler aims this counted damage", node=node)
    payload: dict[str, object] = {
        "amount": "x", X_FROM_COUNT: count_spec(node.amount.filter, node),
    }
    if isinstance(recipient, ast.PlayerRef):
        # The seat comes off the resolution context either way — but *that a
        # seat is what this clause names* is recorded, for the reason
        # `_lower_damage` records it: a sequence whose earlier sentence acted on
        # a permanent leaves that permanent's index in the context, and a clause
        # about a player with no key would be dealt to the permanent instead.
        payload["recipient"] = "target_player"
    _describe_targets(payload, recipient)
    return (OracleInstruction("deal_damage", "", payload),)


#: Named counts whose number is **one per seat** and comes out of this
#: resolution's own scratchpad rather than off the board, mapped to the key the
#: earlier step recorded it under. They lower onto the same looping recipients
#: `_per_recipient_count` does and refuse everywhere else, for that function's
#: reason: one number per seat cannot be folded into the single X.
_PER_SEAT_RECORD_COUNTS: dict[str, str] = {
    "base_over_discarded_this_way": DISCARDED_BY_SEAT,
}

#: The producer each of those counts needs to have run first. "This way" names
#: what a step of *this same effect* did, so with no such step the phrase names
#: nothing (idiom 7) — and here it would name nothing while still computing a
#: number, the printed base, which is the quiet way to be wrong.
_PER_SEAT_RECORD_PRODUCERS: dict[str, str] = {
    "base_over_discarded_this_way": "discarded_count",
}


def _lower_per_seat_record_damage(
    node: ast.DealDamage, record: str, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """Mind Bomb: "…deals damage to each player equal to 3 minus the number of
    cards they discarded this way."

    Every refusal is a way the sentence could otherwise mean more than it says:

    * the recipients must be the looping ones. "They" is the seat being
      damaged, so there is one number per seat and nowhere to put it on a
      clause naming a single recipient.
    * the base must be printed. Without it the arithmetic has no left-hand side
      and the damage would be however many cards the player discarded, which is
      the card upside down.
    * a step of this same effect must actually record the count. "This way" is
      a back-reference, and one with no producer names nothing — here it would
      silently compute the base and deal 3 to everybody.
    """
    recipient = node.recipients[0] if len(node.recipients) == 1 else None
    if not (
        isinstance(recipient, ast.PlayerRef)
        and recipient.kind in _LOOPED_PLAYER_RECIPIENTS
    ):
        raise LoweringError("no handler counts this damage per recipient", node=node)
    if node.riders != ast.DamageRiders():
        raise LoweringError("a counted damage carries no riders yet", node=node)
    if node.amount.base is None:
        raise LoweringError(
            f"the {node.amount.name!r} count needs the constant it subtracts "
            "against",
            node=node,
        )
    producer = _PER_SEAT_RECORD_PRODUCERS[node.amount.name]
    if producer not in produced:
        raise LoweringError(
            f"nothing in this effect records the {node.amount.name!r} count",
            node=node,
        )
    return (
        OracleInstruction(
            "deal_damage", "",
            {
                "recipient": recipient.kind,
                X_FROM_COUNT_PER_RECIPIENT: {
                    "resolution_record": record,
                    "base": node.amount.base,
                },
            },
        ),
    )


def _lower_board_count_damage(
    node: ast.DealDamage, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """Damage sized by a named board count (Black Vise, Power Surge)."""
    assert isinstance(node.amount, ast.BoardCount)
    record = _PER_SEAT_RECORD_COUNTS.get(node.amount.name)
    if record is not None:
        return _lower_per_seat_record_damage(node, record, produced)
    found = _BOARD_COUNT_DAMAGE.get(node.amount.name)
    if found is None:
        raise LoweringError(
            f"nothing computes the {node.amount.name!r} count", node=node
        )
    # Both handlers damage the player whose upkeep is resolving — they take the
    # seat from the upkeep context, not from the instruction — so a clause
    # aimed anywhere else has no handler.
    if not _damaged_player_is(node.recipients, "that_player"):
        raise LoweringError("this counted damage only reaches 'that player'", node=node)
    if node.riders != ast.DamageRiders():
        raise LoweringError("no counted-damage handler carries damage riders", node=node)
    kind, payload = found
    payload = dict(payload)
    if node.amount.name in _BOARD_COUNTS_WITH_BASE:
        if node.amount.base is None:
            raise LoweringError(
                f"the {node.amount.name!r} count needs the constant it "
                "subtracts against",
                node=node,
            )
        payload["base"] = node.amount.base
    return (OracleInstruction(kind, "", payload),)



def _lower_chosen_cast_damage(
    node: ast.DealDamage,
    chosen: "tuple[ast.DamageDealtByChosenCast, str | None]",
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """Backdraft's second sentence — **two instructions**, because it contains
    a decision: "one of those" is a pick the resolution makes, and it must
    happen before the damage that reads it. A step rather than a branch inside
    the handler, so the pick is visible to ``_PRODUCES``, answerable through the
    prompt queue, and suspends the resolution as every other mid-resolution
    choice does. Gated on the earlier sentence having chosen a player.
    """
    definition, rounding = chosen
    if CHOSEN_PLAYER not in produced:
        raise LoweringError("'one of those spells' with no player chosen", node=node)
    if not _damaged_player_is(node.recipients, "that_player"):
        raise LoweringError("this damage reaches the chosen player", node=node)
    if node.riders != ast.DamageRiders():
        raise LoweringError("a chosen-cast damage carries no riders", node=node)
    spec: dict[str, object] = {"back_reference": CHOSEN_CAST_DAMAGE}
    if rounding is not None:
        spec["half"] = rounding
    return (
        OracleInstruction(
            "choose_cast_this_turn", "",
            {"card_type": definition.card_type, "by_result": CHOSEN_PLAYER,
             "result_key": CHOSEN_CAST_DAMAGE},
        ),
        OracleInstruction(
            "deal_damage", "",
            {"amount": "x", X_FROM_COUNT: spec, "recipient": CHOSEN_PLAYER},
        ),
    )


# ---------------------------------------------------------------------------
# The count itself — the spec a resolution or a continuous recompute evaluates.
#
# Here rather than in `_common` for this module's own reason, and it is the
# reason the module exists: a printed quantity that is *counted* is CR
# 107.2/107.3's subject, and `_common` reached the thousand-line guard holding
# it. Every family that spends a count imports it from the floor that reads
# one.
# ---------------------------------------------------------------------------
# The zones a count can be taken over, and what may narrow it there. On the
# battlefield the ordinary object filter applies, because the counter asks
# `permanent_matches_filter` — the same question every target of the same words
# asks. In any other zone the objects are *cards*, which have no computed
# characteristics at all, so only the printed type union and a card's name are
# testable and anything else refuses rather than being counted as if it were
# not there.
# "the number of cards in their library" (Peer into the Abyss). The evaluator
# reads the zone off the owner by name, so the library needed no counting code —
# only saying so here. It is listed last because it is the one zone whose count a
# player cannot see, which changes nothing about the arithmetic and everything
# about what a *picker* built on the same spec could offer.
_COUNTABLE_ZONES = ("battlefield", "graveyard", "hand", "exile", "library")
# What a *card* in a hidden or public non-battlefield zone can be tested for.
# Held to `subject_filters.CARD_ONLY_FILTER_KEYS`, which is what the matcher
# behind the count actually answers: a key admitted here and unanswered there is
# a narrowing dropped on the floor, and a count that ignores its adjective is
# larger than the card printed.
_CARD_ZONE_KEYS = frozenset({"type_filter", "named", "color_filter"})


def count_spec(
    filt: "ast.ObjectFilter", node, *, aggregate: str = "count", multiplier: int = 1,
    offset: int = 0,
) -> dict:
    """What ``count_from_payload`` needs to take this count at resolution.

    One reader for both callers — the where-clause that *defines* an X and the
    amount that *is* one ("draw cards equal to the number of …"). They ask the
    same question of the same noun phrase, so a restriction one of them refused
    and the other silently dropped would be the same count meaning two things.
    """
    if filt.zone not in _COUNTABLE_ZONES:
        raise LoweringError(f"no count reads the {filt.zone}", node=node)
    payload = dict(filt.to_payload())
    # The same gate `_filter_payload` puts in front of every other consumer of a
    # noun phrase, and it was missing here: `to_payload` emits nothing for a
    # *relative* narrowing, so "for each creature **blocking it**" reduced to
    # "for each creature" and the count read the whole of its owner's
    # battlefield. A count that is too large is a pump that is too big — the
    # dropped-rider bug with an arithmetic face — so a narrowing with no payload
    # form refuses the sentence rather than widening it.
    #
    # `blocking_source` is the one such field a count *can* answer, carried
    # separately below the way `attached_to` is: it is a relation to one named
    # permanent, which the matcher cannot test and the evaluator resolves.
    dropped = tuple(
        field for field in dropped_narrowings(filt, payload)
        if field != "blocking_source"
    )
    if dropped:
        raise LoweringError(
            f"a count cannot test {', '.join(dropped)}", node=node
        )
    if filt.zone != "battlefield" and set(payload) - _CARD_ZONE_KEYS:
        raise LoweringError(
            f"a {filt.zone} count cannot test {sorted(set(payload) - _CARD_ZONE_KEYS)}",
            node=node,
        )
    # Whose objects are counted is the *zone owner*, and the counter reads it
    # off there. A filter narrowing by controller as well ("the number of
    # Mountains **they** control") is asking a question the count cannot answer
    # — `permanent_matches_filter` does not test a controller, so the key would
    # be handed over and silently ignored, and the count taken on the wrong
    # player's battlefield. Refused rather than dropped.
    controller = payload.pop("controller", None)
    if controller not in (None, "you"):
        raise LoweringError(
            f"a count cannot be narrowed to the {controller}'s permanents", node=node
        )
    spec: dict = {
        "zone": filt.zone,
        "owner": (filt.zone_owner.kind if filt.zone_owner else "you"),
        "filter": payload,
    }
    # "the number of Auras **attached to it**" (Rabid Wombat). A relation to one
    # named permanent, not a property of each object, so it rides the spec
    # rather than the filter — ``permanent_matches_filter`` cannot test it, and
    # a key handed to that matcher is a key silently ignored. It also settles
    # *which pile* is counted: what is attached to a permanent is recorded on
    # that permanent, so the count is not a battlefield scan and does not
    # inherit the owner scope above (an opponent's Aura on your creature is
    # attached to your creature).
    if filt.attached_to is not None:
        if filt.attached_to != "source":
            raise LoweringError(
                f"no count resolves an attachment to the {filt.attached_to}",
                node=node,
            )
        spec["attached_to"] = filt.attached_to
    # "…for each creature **blocking it** beyond the first" (Johtull Wurm).
    # A relation to the ability's own source (CR 509.1a), not a property of
    # each creature counted — so it rides the spec beside `attached_to` for
    # that key's reason exactly, and it also settles which pile is counted: a
    # blocker is on the *defending* player's battlefield, which the owner scope
    # above would have read as the source controller's.
    if filt.blocking_source:
        spec["blocking_source"] = True
    # Omitted when it is the default, so every spec written before aggregates
    # existed is byte-identical.
    if aggregate != "count":
        spec["aggregate"] = aggregate
    # "**Twice** the number of white creatures that player controls" (Jovial
    # Evil). Carried on the spec rather than folded into whatever reads it,
    # because the same spec is read by the resolution-time evaluator and by the
    # continuous recompute — a factor applied in one of them would make the
    # same printed count mean two numbers. Omitted at 1, for the reason the
    # aggregate is: an untouched spec stays byte-identical.
    if multiplier != 1:
        spec["multiplier"] = multiplier
    # "…for each creature blocking it **beyond the first**" (Johtull Wurm).
    # Applied where the multiplier is, and for its reason: one place scales
    # every aggregate, and an offset honoured at one of the evaluator's return
    # sites and forgotten at the rest is the dropped-rider bug with an
    # arithmetic face. Omitted at 0 so an untouched spec stays byte-identical.
    if offset:
        spec["offset"] = offset
    return spec


def halved_count_spec(amount: "ast.Amount", node) -> dict | None:
    """The spec for a computed amount that may be halved, or None if it is not one.

    "Half the number of cards in their library" and "half their life" (Peer into
    the Abyss) are the same shape: something the resolution computes, divided,
    and rounded. So the halving rides on the *spec* rather than becoming a second
    amount vocabulary — one evaluator still answers, which is the rule round 64
    wrote down when the pump handler was found carrying its own counter.

    A player's life total is not a pile to scan, so it arrives as a *named* board
    count rather than a filter: ``evaluate_count`` maps the name onto the one
    thing that computes it and answers 0 for a name it has no computation for,
    which is why the name is minted here and nowhere else.
    """
    rounding = None
    if isinstance(amount, ast.Half):
        rounding = amount.rounding
        amount = amount.of
    if isinstance(amount, ast.CountOf):
        spec = count_spec(amount.filter, node)
    elif isinstance(amount, ast.BoardCount) and amount.name == "their_life":
        spec = {"board_count": "their_life", "owner": "target"}
    else:
        return None
    if rounding is not None:
        spec["half"] = rounding
    return spec


# ---------------------------------------------------------------------------
# How big a printed P/T change is.
#
# Beside the count itself, and for the same reason: "+1/+1 **for each** …",
# "+X/+0 **where X is** …" and "…**beyond the first**" are three spellings of
# one quantity, and `lowering/characteristics.py` reached the thousand-line
# guard holding them. They read the count spec above and nothing reads them
# back, which is what makes them floor rather than family.
# ---------------------------------------------------------------------------
def _static_x_amount(amount: ast.Amount, negative: bool, node) -> int | str:
    """One half of a computed static bonus: the string "x" or a literal.

    A negated X refuses. The refresh resolves the amount against the computed
    value and nothing carries a sign for it, so admitting "-X/-0" here would be
    a bonus applied with the wrong sign — the direction that makes a creature
    bigger when the card shrinks it.
    """
    if isinstance(amount, ast.Var):
        if negative:
            raise LoweringError("a static computed bonus cannot be negative", node=node)
        return "x"
    if isinstance(amount, ast.Fixed):
        return -amount.value if negative else amount.value
    raise LoweringError("a static computed bonus needs X or a number", node=node)


def _per_each_amount(amount: ast.Amount, negative: bool, node) -> dict | int:
    """One half of a "for each" bonus: how much *each* repetition is worth.

    ``{"times_x": n}`` is what ``resolve_amount`` multiplies by the count. A
    printed 0 stays a plain 0 — nothing times a count is still nothing, and the
    literal keeps every payload written before this existed byte-identical.
    """
    if not isinstance(amount, ast.Fixed):
        raise LoweringError(
            'a "for each" bonus needs a printed number to repeat', node=node
        )
    value = -amount.value if negative else amount.value
    return {"times_x": value} if value else 0


def _x_definition_spec(definition: ast.Amount, node) -> dict:
    """The spec behind a where-clause's X, whichever aggregate it names."""
    if isinstance(definition, ast.GreatestPowerAmong):
        return count_spec(definition.filter, node, aggregate="greatest_power")
    if isinstance(definition, ast.ColorsAmong):
        return count_spec(definition.filter, node, aggregate="distinct_colors")
    if isinstance(definition, ast.CountOf):
        return count_spec(definition.filter, node)
    if isinstance(definition, ast.CharacteristicOfSubject):
        # "…, where X is **its** mana value" (Great Defender, Subdue, Kry
        # Shield), "…, where X is **its toughness minus 1**" (Blood Lust). Not
        # an aggregate over a set: the object is the one the sentence already
        # named, and the resolution reads the characteristic off it — mana
        # value off the card (CR 202.3), power and toughness through the layers
        # (CR 613), which is the resolution's business rather than this one's.
        return {
            "object_characteristic": {
                "object": "target",
                "characteristic": definition.characteristic,
                "offset": definition.offset,
            }
        }
    raise LoweringError("only a count or a maximum can define X here", node=node)


def _per_each_offset(node: ast.Pump) -> int:
    """"…beyond the first" as the count spec's offset."""
    return -1 if node.per_each_beyond_first else 0
