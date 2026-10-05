"""How much damage a clause computes, and which seat it lands on.

A **floor**, not a family: `damage.py` reads it, `upkeep.py` reads its one
predicate and `where_x.py` its one characteristic set, and it reads none of the
three back — inside `lowering/` a module a family imports has to sit below the
families (`_bites` is a floor for exactly that reason, one cut earlier off the
same original file). The direction cannot be reversed either —
`_lower_halved_damage` stays in `damage.py` because it lowers the quantity
*underneath* by re-entering the damage lowering, which is the one amount that
has to know about the shapes.

Split out of `_amounts` at Tempest's Phase 0, along the second half of the
sentence that module's own docstring had already drawn round its subject:

    "Split out of `damage.py` at the 1,000-line guard, along the line CR
    107.2/107.3 already draw: a printed quantity that is **counted** — off a
    board, out of the resolution's own scratchpad, or off a cast the player
    picked — **against the sentence that spends it**."

`_amounts` keeps the quantity — `count_spec`, the halving over it, the printed
P/T change, the X definition written onto the sentence that reads one. Every
sentence in that file that *spent* a count was a damage sentence, and those are
here.

That is the half that **grows with the pool**, the playbook's tiebreak when
both halves are dispatch: this file is one branch per printed shape of counted
damage — the three cost channels (a permanent tapped, sacrificed, or its
counters removed), the difference, the named board count, the per-seat record,
the chosen cast — and a set adds a shape to it far oftener than it teaches
`count_spec` a new zone or narrowing.

`_damaged_player_is` travelled with them for the reason it moved down in the
first place: the counted amounts ask it and so does the pay-or-else prompt in
`upkeep.py`, and a predicate two modules need is not one module's property.
"""

import dataclasses

from ...oracle_types import (
    CHOSEN_COLOR_THIS_WAY, DISCARDED_BY_SEAT, OracleInstruction,
    REVEALED_HAND_CARDS, X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT,
)
from .. import ast
from ..errors import LoweringError
from ._amounts import TARGET_OPPONENT_SCOPE, count_spec, seat_scoped_count_spec
from ._cost_records import COST_RECORD_CHANNELS
from ._common import _describe_targets, _is_target
from ._filters import dropped_narrowings, split_bound_card_type
from ._events import (CHOSEN_CAST_DAMAGE, CHOSEN_PLAYER,
                      EVENT_SUBJECT_PLAYER, _DAMAGED_PLAYER_EVENTS,
                      _EVENT_SUBJECT_PLAYERS)


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


def _recipient_seat_count(node: ast.DealDamage, multiplier: int = 1) -> dict | None:
    """The count spec for "…equal to the number of <filter> **that player**
    controls", or None when the clause does not narrow to the recipient.

    Scoped to the recipient **seat**, which is what names it apart from
    ``_sweeps._per_recipient_multiplier``, a number taken once per struck
    *permanent*. Both were ``_per_recipient_count`` until VIS wave 4.

    The controller narrowing is stripped before :func:`count_spec` sees it, for
    the reason that function refuses it: nothing downstream tests a controller
    key, so the count has to be *scoped* to a player instead of *filtered* by
    one. Scoping it is exactly what the per-recipient loop does.
    """
    assert isinstance(node.amount, ast.CountOf)
    # The floor's reading, shared with the life loss that prints the same
    # phrase ("…for each creature **they** control", Stronghold Discipline).
    return seat_scoped_count_spec(node.amount.filter, node, multiplier=multiplier)


#: Characteristics of a cost-eaten permanent that ``count_from_payload``
#: actually reads back (``engine/handlers/_common.py``). A mana value comes off
#: the card and survives anything; a power or a toughness is the *effective*
#: one the permanent last had on the battlefield (CR 608.2h), which the
#: `Permanent` object still carries after it leaves — the same read
#: `target_gains_life` has made for Life Chisel since that card landed.
#:
#: Written down because a characteristic this lowering emits and the evaluator
#: cannot answer is a card that reports supported and deals nothing — and read
#: off ``_cost_records.COST_RECORD_CHANNELS`` rather than spelled here, so a
#: where-clause's X and a damage's amount answer one table.
_READABLE_COST_SACRIFICE_CHARACTERISTICS = COST_RECORD_CHANNELS[ast.SacrificedForCost][1]


#: The characteristics of a **cost-tapped** permanent ``count_from_payload``
#: reads back. All three, and unlike the sacrifice channel beside it none of
#: them is last-known information: the creature is still on the battlefield when
#: the effect resolves, so the power is simply its power.
_READABLE_COST_TAP_CHARACTERISTICS = COST_RECORD_CHANNELS[ast.TappedForCost][1]


def _payment_channel_damage(
    node: ast.DealDamage, count: dict[str, object]
) -> tuple[OracleInstruction, ...]:
    """A counted damage whose number is *count*, aimed at the sentence's one
    recipient.

    The shared tail of the three payment-channel lowerings below — what the
    ability's own cost sacrificed, tapped, or removed in counters. Each carried
    a verbatim copy of this block with one dict literal changed, which is one
    refusal to forget per channel: a rider dropped here is a damage carrying a
    printed clause nobody performs, and a recipient admitted here is a damage
    aimed at whatever permanent the resolution context happened to hold — which
    is also why the seat is recorded (`_lower_counted_damage`'s reason).
    """
    if node.riders != ast.DamageRiders():
        raise LoweringError("a counted damage carries no riders yet", node=node)
    if len(node.recipients) != 1:
        raise LoweringError("a counted damage reaches one recipient", node=node)
    recipient = node.recipients[0]
    payload: dict[str, object] = {"amount": "x", X_FROM_COUNT: count}
    if isinstance(recipient, ast.PlayerRef):
        if recipient.kind not in ("target_player", "target_opponent", "you"):
            raise LoweringError("no handler aims this counted damage", node=node)
        payload["recipient"] = "caster" if recipient.kind == "you" else "target_player"
    elif not (
        _is_target(recipient)
        or (isinstance(recipient, ast.TargetSpec)
            and recipient.quantifier == "any_target")
    ):
        raise LoweringError("no handler aims this counted damage", node=node)
    _describe_targets(payload, recipient)
    return (OracleInstruction("deal_damage", "", payload),)


def _lower_cost_tap_damage(
    node: ast.DealDamage,
) -> tuple[OracleInstruction, ...]:
    """"This artifact deals damage equal to **the tapped creature's power** to
    target attacking or blocking creature with flying." (Unerring Sling.)

    :func:`_lower_cost_sacrifice_damage` with the payment one verb over. Its own
    refusal is the characteristic the evaluator cannot answer; the rider and
    recipient refusals are :func:`_payment_channel_damage`'s.
    """
    assert isinstance(node.amount, ast.TappedForCost)
    characteristic = node.amount.characteristic
    if characteristic not in _READABLE_COST_TAP_CHARACTERISTICS:
        raise LoweringError(
            f"no handler reads the tapped permanent's {characteristic!r}",
            node=node,
        )
    return _payment_channel_damage(
        node, {"cost_tap_characteristic": characteristic}
    )


def _lower_cost_counters_removed_damage(
    node: ast.DealDamage,
) -> tuple[OracleInstruction, ...]:
    """"It deals damage to target creature equal to **the number of pain
    counters removed this way**." (Torture Chamber.)

    :func:`_lower_cost_tap_damage` with the payment one kind over, and no
    refusal of its own. CR 601.2h is what makes the number a *payment* rather
    than a board read: the counters came off before the ability reached the
    stack, and the cost clause is what pins which store they came from.
    """
    assert isinstance(node.amount, ast.CountersRemovedForCost)
    return _payment_channel_damage(
        node, {"cost_counters_removed": node.amount.counter}
    )


#: The characteristics of a **cost-discarded** card ``count_from_payload`` reads
#: back. Mana value alone, and the narrowest of the four channels for a reason
#: CR 613.1 states outright: what the record holds is a *card* in a graveyard,
#: which has no computed characteristics at all — its printed mana value is a
#: characteristic of the card (CR 202.3) and its power is not.
_READABLE_COST_DISCARD_CHARACTERISTICS = COST_RECORD_CHANNELS[ast.DiscardedForCost][1]


def _lower_cost_discard_damage(
    node: ast.DealDamage,
) -> tuple[OracleInstruction, ...]:
    """"This enchantment deals damage to any target equal to **the mana value of
    the discarded card**." (Pyromancy.)

    The fourth payment channel, beside its three siblings and for their reason:
    a quantity the ability's own cost produced rather than a count of anything on
    a board. CR 601.2h discards the card before the ability is on the stack, so
    by resolution it is one card among everything else that ever reached that
    graveyard — the payment path's record (``discarded_for_cost``) is the only
    thing that says which.
    """
    assert isinstance(node.amount, ast.DiscardedForCost)
    characteristic = node.amount.characteristic
    if characteristic not in _READABLE_COST_DISCARD_CHARACTERISTICS:
        raise LoweringError(
            f"no handler reads the discarded card's {characteristic!r}",
            node=node,
        )
    return _payment_channel_damage(
        node, {"cost_discard_characteristic": characteristic}
    )


def _lower_cost_sacrifice_damage(
    node: ast.DealDamage,
) -> tuple[OracleInstruction, ...]:
    """"…deals damage to any target equal to **the sacrificed creature's
    power**." (Freyalise Supplicant, halved by the caller.)

    The number is a characteristic of the permanent the ability's own cost ate
    (CR 601.2h), so it is not on any board by the time this resolves — it is
    read off the record the activation kept, through the one ``x_from_count``
    channel every other computed amount already travels on. That is what lets
    the printed "half … , rounded down" ride along: `_lower_halved_damage`
    stamps the rounding onto the same spec and the count evaluator applies it
    once, where the number is computed.
    """
    assert isinstance(node.amount, ast.SacrificedForCost)
    characteristic = node.amount.characteristic
    if characteristic not in _READABLE_COST_SACRIFICE_CHARACTERISTICS:
        raise LoweringError(
            "no handler reads the sacrificed permanent's "
            f"{characteristic!r}",
            node=node,
        )
    return _payment_channel_damage(
        node, {"cost_sacrifice_characteristic": characteristic}
    )


#: Re-exported from ``_amounts``, where the constant now lives. It was written
#: here when Superior Numbers' subtrahend was the only phrase that named a
#: targeted seat; Reap prints the same narrowing on a plain count, so
#: ``count_spec`` lifts it now — and the floor every family reads cannot import
#: a family. The name keeps its address for the readers below.


def lower_difference_damage(node: ast.DealDamage) -> tuple[OracleInstruction, ...]:
    """"…deals damage to target creature equal to the number of creatures you
    control **in excess of** the number of creatures target opponent controls."
    (Superior Numbers.)

    One quantity with two halves, so it is one `x_from_count` with the
    subtrahend nested under it rather than two instructions — there is nothing
    for a second step to do, and a `sequence` would have to record a number the
    printed sentence never names.

    Both halves go through :func:`count_spec`, which is the point: a difference
    of two counts must mean, on each side, exactly what the same noun phrase
    means printed on its own. The only thing the right-hand side does not share
    is *whose* board it reads, and that is a scope rather than a narrowing.
    """
    amount = node.amount
    assert isinstance(amount, ast.Minus)
    if not (
        isinstance(amount.left, ast.CountOf) and isinstance(amount.right, ast.CountOf)
    ):
        raise LoweringError("a printed difference counts two sets", node=node)
    if node.riders != ast.DamageRiders():
        raise LoweringError("a counted damage carries no riders yet", node=node)
    if len(node.recipients) != 1 or not _is_target(node.recipients[0]):
        raise LoweringError("no handler aims this counted damage", node=node)
    right = amount.right.filter
    if right.controller != "target_opponent" or right.zone_owner is not None:
        # Every other seat the subtrahend could name would be one the handler
        # cannot resolve, and a scope dropped is the whole board counted — the
        # spell dealing more damage than it prints while reporting supported.
        raise LoweringError(
            "the subtrahend of a difference is counted on a target opponent's "
            "battlefield",
            node=node,
        )
    spec = count_spec(amount.left.filter, node)
    subtrahend = count_spec(dataclasses.replace(right, controller=None), node)
    subtrahend["owner"] = TARGET_OPPONENT_SCOPE
    spec["minus"] = subtrahend
    payload: dict[str, object] = {"amount": "x", X_FROM_COUNT: spec}
    _describe_targets(payload, node.recipients[0])
    return (OracleInstruction("deal_damage", "", payload),)


def _damaged_player_is(recipients: tuple[ast.Recipient, ...], kind: str) -> bool:
    """Whether the damage lands on exactly one player reference of *kind*."""
    return (
        len(recipients) == 1
        and isinstance(recipients[0], ast.PlayerRef)
        and recipients[0].kind == kind
    )


def _lower_counted_damage(
    node: ast.DealDamage, event: str | None = None, *, multiplier: int = 1
) -> tuple[OracleInstruction, ...]:
    """"…deals damage to that player equal to the number of Swamps they control."
    (Karma.)

    Both halves are checked, not just the count: the handler damages the player
    whose upkeep is resolving, so lowering a clause that damages someone else
    onto it would hit the wrong seat while the card still reported as supported.

    *multiplier* is the printed factor in front of the count — "equal to
    **twice** the number of nonbasic lands that player controls" (Price of
    Progress) — unwrapped by the caller and handed to ``count_spec``, which is
    where every other scaled count in this engine carries it (``_scaled``
    applies it once, for every aggregate). It reaches each spec-building branch
    below rather than being applied to a number here, because there is no
    number here: the count is taken at resolution, per seat.
    """
    assert isinstance(node.amount, ast.CountOf)
    if (
        node.amount.filter == _SWAMPS_THEY_CONTROL
        and _damaged_player_is(node.recipients, "that_player")
        and node.riders == ast.DamageRiders()
        # Karma's fused kind carries no number of its own — it counts Swamps and
        # deals that much — so a factor lowered onto it would be dropped. A
        # multiplied printing falls through to the general per-seat spec below,
        # which does carry one.
        and multiplier == 1
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
        per_recipient = _recipient_seat_count(node, multiplier)
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
            # "…deals damage to **you** equal to the number of creatures
            # **that opponent** controls." (Goblin Lyre.) Not a loop either:
            # the damage lands on one fixed seat — the ability's own controller
            # — while the counted board belongs to the seat the sentence in
            # front of this one chose. So there is one number, and the phrase
            # is a *scope* on the count rather than a filter on it, which is
            # exactly what `owner` is. `that_player` is the spelling every
            # other spec already uses for that seat ("the number of cards in
            # **that player's** hand" reaches `count_from_payload` the same
            # way), so no new vocabulary and no second answer.
            if recipient.kind == "you":
                return (
                    OracleInstruction(
                        "deal_damage", "",
                        {
                            "amount": "x",
                            "recipient": "caster",
                            X_FROM_COUNT: {**per_recipient, "owner": "that_player"},
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
        "amount": "x",
        X_FROM_COUNT: count_spec(node.amount.filter, node, multiplier=multiplier),
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


def lower_revealed_this_way_damage(
    node: ast.DealDamage, produced: frozenset[str], *, multiplier: int = 1,
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Choose a card type. Target opponent reveals their hand. Blood Oath deals
    3 damage to that player **for each card of the chosen type revealed this
    way**."

    The third reading of a counted damage and the one this module had no branch
    for: :func:`_lower_counted_damage` counts a **board**, ``recorded_count_spec``
    one file down reads a scratchpad slot holding a **number**, and this counts
    the entries of a recorded **list of cards** against a printed noun phrase.
    The channel itself is not new — ``count_from_payload``'s ``recorded_cards``
    branch has answered it for Song of Blood's pump and Reprocess's draw since
    those cards landed — so what is added here is the damage sentence's way in,
    and every rider, scaling and recipient key stays the one every other
    ``deal_damage`` payload carries.

    *multiplier* is the printed rate, unwrapped by the caller: "deals **3**
    damage … for each card" is three times the count, and it rides the spec's
    own ``multiplier`` key, which ``handlers/_common._scaled`` already applies
    to every aggregate. No handler learns a new key.

    Three refusals, each the direction that fails loudly:

    * **The recipient is the player the reveal named.** "That player" is the one
      seat the resolution can resolve, and the reveal in front of this sentence
      is what put them in the context. A clause damaging anybody else while
      counting this record has no handler at all, and admitting it is how a
      supported card hits the wrong face.
    * **A step of this same effect must have revealed a hand.** With no producer
      the words name nothing and the count would be a zero the card never
      printed — the gate every back-reference in this grammar carries.
    * **Only what is printed on a card is testable** (CR 613.1,
      ``subject_filters.CARD_ONLY_FILTER_KEYS``): the record holds cards in a
      hand, which have no computed characteristics. "Of the chosen type" is the
      one narrowing beyond that list, and it travels as its own payload key —
      ``split_bound_card_type`` strips the relation off the filter and
      ``resolve_chosen_card_type_in_resolution`` spends it at resolution, the
      same pair Turnabout's tap sweep already uses one family over.
    """
    assert isinstance(node.amount, ast.CountOfRevealsThisWay)
    if node.riders != ast.DamageRiders():
        raise LoweringError("a counted damage carries no riders yet", node=node)
    if len(node.recipients) != 1 or not _damaged_player_is(
        node.recipients, "that_player"
    ):
        raise LoweringError(
            "no handler aims a revealed-card count at this recipient", node=node
        )
    if REVEALED_HAND_CARDS not in produced:
        raise LoweringError(
            f"back-reference to {REVEALED_HAND_CARDS!r} with no producer in "
            "this effect",
            node=node,
        )
    from ...subject_filters import card_only_filter

    filt, bound = split_bound_card_type(node.amount.filter)
    if filt.color_chosen_this_way:
        # "…the number of cards **of that color** revealed this way" (Darigaaz,
        # the Igniter). The second narrowing beyond what is printed on a card,
        # and carried the way the first is: lifted off before the card-only
        # gate — no card matcher holds a resolution — and put back as the key
        # ``count_from_payload`` resolves out of the scratchpad. Admitted only
        # behind a step that chose: with none the matcher refuses every card,
        # which is a zero the card never printed.
        if CHOSEN_COLOR_THIS_WAY not in produced:
            raise LoweringError(
                "'of that color' with no step in this effect that chose one",
                node=node,
            )
        filt = dataclasses.replace(filt, color_chosen_this_way=False)
        bound = {**bound, "color_chosen_this_way": True}
    payload_filter = filt.to_payload()
    described = card_only_filter(payload_filter)
    if described is None or dropped_narrowings(filt, payload_filter):
        raise LoweringError(
            "a revealed-card count cannot test this restriction", node=node
        )
    spec: dict[str, object] = {
        "recorded_cards": REVEALED_HAND_CARDS, "filter": {**described, **bound},
    }
    if multiplier != 1:
        # Omitted at 1 for ``count_spec``'s reason: a spec written without the
        # factor stays byte-identical.
        spec["multiplier"] = multiplier
    # "Whenever Darigaaz deals combat damage to a player, … that player reveals
    # their hand and Darigaaz deals damage to **the player** …". Under a damage
    # trigger nobody targeted anyone: the player is the one the damage froze
    # (CR 603.10), the seat the reveal in front of this sentence read under the
    # same word — so the count and the damage cannot land on two players.
    recipient = "damaged_player" if event in _DAMAGED_PLAYER_EVENTS else "target_player"
    return (
        OracleInstruction(
            "deal_damage", "",
            {"amount": "x", X_FROM_COUNT: spec, "recipient": recipient},
        ),
    )


#: Named counts whose number is **one per seat** and comes out of this
#: resolution's own scratchpad rather than off the board, mapped to the key the
#: earlier step recorded it under. They lower onto the same looping recipients
#: `_recipient_seat_count` does and refuse everywhere else, for that
#: function's
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
