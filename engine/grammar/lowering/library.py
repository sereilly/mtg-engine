"""Lowering the hidden-zone flows: search, reveal and look-at.

Every shape here pivots on a pile of cards in a hidden zone offered through a
picker — a library search, a revealed hand, the top cards looked at, a
graveyard exiled wholesale. The search filter fields the flow can actually
honour are closed sets, because a filter it cannot honour must refuse rather
than be dropped.

**"and exile linkage" used to be the fourth conjunct of that first line**, and
it is `lowering/exile.py`'s now: the module crossed the thousand-line guard, and
the trailing conjunct was what had stopped being a lodger. Every shape that
moved pivots on the linked-exile record (`engine/linked_exile.py`) and on what
may later be cast out of it, which is that module's stated subject rather than
this one's, and the cut needed no import in either direction because the call
graph had already fallen apart there.
"""

from ...oracle_types import (PER_OBJECT_SEAT_RECORDS, REVEALED_HAND_CARDS,
                             OracleInstruction)
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (
    chargeable_card_filter,
    graveyard_position_payload,
    dropped_narrowings,
    _amount_payload,
    _describe_targets,
    _is_target,
    _restrictions_beyond,
    _targets_only,
)
from ._events import (
    _DEFENDING_PLAYER_EVENTS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_PLAYER,
    _back_reference_payload,
)






# The ``ObjectFilter`` fields the revealed-hand picker can test. The exclusion
# is the only narrowing any printing of this template uses, and
# `search_filters.search_matches` is what tests it — so a field outside this set
# refuses the line rather than leaving the caster choosing from the whole hand
# while the card claims a restriction. Same rule the search lowering follows,
# and the same predicate underneath it.
#: What the revealed-hand picker can narrow by. ``excluded_basic_lands`` is
#: the third, and it arrived with Lobotomy's "a card **other than a basic land
#: card**" — one printed phrase, read by ``search_filters.search_matches``,
#: which is the one predicate the engine, the AI and the web picker all answer
#: with. A field admitted here without that reader behind it would be a picker
#: offering the whole hand while the card named less of it.
#: ``card_types`` is the fourth, and it is the *positive* form of the first —
#: "You choose **a creature card** from it" (Ostracize) asks the same question
#: as "a **noncreature, nonland** card" with the answer the other way up, and
#: ``search_matches`` answers it under ``card_type``. Admitted only because that
#: reader was already there: a positive type narrowing the picker could not test
#: would be Ostracize discarding a land.
_REVEALED_HAND_FIELDS = frozenset(
    {"excluded_types", "is_card", "excluded_basic_lands", "card_types"}
)


def _lower_reveal_hand(node: ast.RevealHand) -> tuple[OracleInstruction, ...]:
    """"Target player **reveals their hand**" (CR 701.20), on its own.

    The first half of Amnesia and Rag Man, lowered as its own step so the
    discard behind it is the ordinary discard instruction rather than a second
    fused kind. "Each player reveals their hand" is still refused: it would be a
    loop nothing here performs.

    **"You reveal your hand" is not a no-op**, and refusing it was this
    function's one wrong reading — the reason given was that the revealer
    "already sees" the zone, which is true of the revealer and of nobody else at
    the table. CR 701.20a shows the cards to *every* player, and on Manabond
    that is the whole price of the offer: the hand becomes public and is then
    discarded. It carries no ``targets`` key, so the handler reads the seat off
    ``who`` rather than off whatever the resolution context happened to be
    holding — the distinction Detonate's sequence made necessary one family
    over.

    The rest of the payload is who reveals, because a reveal narrows nothing and
    chooses nothing — what the sentence after it does with the revealed hand is
    that sentence's business, and on Inquisition that is an ordinary counted
    damage.
    """
    if node.player.kind == "you":
        return (OracleInstruction("reveal_hand", "", {"who": "you"}),)
    if node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"no handler reveals {node.player.kind!r}'s hand", node=node
        )
    return (OracleInstruction("reveal_hand", "", _targets_only(node.player)),)


def _lower_reveal_random_from_hand(
    node: "ast.RevealRandomFromHand",
) -> tuple[OracleInstruction, ...]:
    """"Target player **reveals a card at random from their hand**." (Wand of
    Ith.) One card nobody chose, and the record it leaves is the one every "if
    it's a …" already reads, so the sentences behind it need no new referent.

    **"You" is admitted here and refused by ``_lower_reveal_hand``**, and the
    difference is what "at random" does. Revealing your own *hand* shows you
    nothing you did not already know, which is why that one refuses; revealing
    one card of it **at random** picks a card nobody chose and shows it to every
    player, which is the whole of Cursed Scroll — the sentence behind it asks
    which card the randomness landed on, and the answer is information the
    revealer did not have either.
    """
    if node.player.kind not in ("you", "target_player", "target_opponent"):
        raise LoweringError(
            f"no handler reveals a card from {node.player.kind!r}'s hand",
            node=node,
        )
    if node.player.kind == "you":
        # ``revealer`` rather than a ``targets`` payload, and **stated** rather
        # than left to the handler's fallback. That fallback reads
        # ``context.target``, which is the *ability's* target — and on Cursed
        # Scroll the ability targets somebody else for its damage, so an
        # unstated revealer opened the opponent's hand while the card says
        # "your hand". A target payload would have been worse: the picker would
        # then offer a player this sentence never names.
        return (
            OracleInstruction(
                "reveal_random_card_from_hand", "", {"revealer": "you"}
            ),
        )
    return (
        OracleInstruction(
            "reveal_random_card_from_hand", "", _targets_only(node.player)
        ),
    )


def _lower_discard_revealed_unless_pay_life(
    node: "ast.DiscardRevealedUnlessPayLife", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"That player **discards it unless they pay 1 life**." (Wand of Ith.)

    ``produced`` is the whole gate, and the same one ``RevealedCardIs`` takes:
    "it" names the card a reveal earlier in this effect recorded, and with no
    reveal in front of it there is nothing to discard — an offer bought off
    against nothing would charge a player life for keeping a card that was
    never named.
    """
    if "revealed_card" not in produced:
        raise LoweringError(
            "'it' with nothing in this effect that revealed a card", node=node
        )
    if node.player.kind not in ("target_player", "that_player", "target_opponent"):
        raise LoweringError(
            f"no handler makes {node.player.kind!r} discard the revealed card",
            node=node,
        )
    payload: dict[str, object] = {}
    if node.mana_value_of_revealed:
        payload["life"] = "revealed_mana_value"
    else:
        amount = _amount_payload(node.amount)
        if not isinstance(amount, int) or amount < 0:
            raise LoweringError("a life payment is a printed number", node=node)
        payload["life"] = amount
    return (
        OracleInstruction("discard_revealed_unless_pay_life", "", payload),
    )


def _lower_discard_revealed_matching_unless_pay_life(
    node: "ast.DiscardRevealedMatchingUnlessPayLife", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"For each blue instant card revealed this way, **that player discards
    that card unless they pay 4 life**." (Sirocco.)

    ``produced`` is the gate, and it names the *hand* reveal rather than the
    single-card one: "this way" is the set the sentence in front showed, and
    with no reveal behind it the loop would walk an empty record and the spell
    would silently do nothing.

    The narrowing is carried or the line refuses. Every key has to be one
    ``card_matches_filter`` answers — the objects are cards in a hand, so
    nothing about the battlefield is in the question, and a dropped adjective
    here is a spell discarding cards its own text did not name.
    """
    if REVEALED_HAND_CARDS not in produced:
        raise LoweringError(
            "'revealed this way' with nothing in this effect that revealed a "
            "hand", node=node,
        )
    if node.player.kind not in ("target_player", "that_player", "target_opponent"):
        raise LoweringError(
            f"no handler makes {node.player.kind!r} discard the revealed cards",
            node=node,
        )
    # ``to_payload`` directly, not ``_filter_payload``: that reader refuses
    # every card-scoped filter by construction, because the handlers it feeds
    # search the battlefield. These objects are cards in a hand, so the gate is
    # ``card_only_filter`` instead — and ``dropped_narrowings`` beside it,
    # because a phrase that left no key at all would widen the discard to every
    # card the reveal showed.
    payload = node.filter.to_payload()
    described = card_only_filter(payload)
    lost = dropped_narrowings(node.filter, payload)
    if described is None or lost:
        raise LoweringError(
            "the revealed-card discard cannot test that phrase", node=node
        )
    amount = _amount_payload(node.amount)
    if not isinstance(amount, int) or amount < 0:
        raise LoweringError("a life payment is a printed number", node=node)
    return (
        OracleInstruction(
            "discard_revealed_matching_unless_pay_life", "",
            {"filter": described, "life": amount},
        ),
    )


def _lower_reveal_hand_and_choose(
    node: ast.RevealHandAndChoose, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Target opponent reveals their hand. You choose a noncreature, nonland
    card from it. That player discards that card." (Duress.)

    One instruction for the whole template: the reveal is what makes the choice
    legal, and the discard is what the choice was for, so splitting them would
    put a chosen card between two instructions with nothing carrying it.
    """
    leftover = _restrictions_beyond(node.filter, _REVEALED_HAND_FIELDS)
    if leftover:
        raise LoweringError(
            "the revealed-hand picker cannot narrow by: " + ", ".join(leftover),
            node=node,
        )
    if node.filter.type_match != "any":  # pragma: no cover - no card prints it
        # A printed type *union* is an OR everywhere in this engine, and
        # ``search_matches`` reads ``card_type`` that way. An "all" match would
        # be a narrower question than the predicate behind the picker asks, so
        # it refuses rather than being widened to the union.
        raise LoweringError(
            "the revealed-hand picker reads a type union, not an intersection",
            node=node,
        )
    payload: dict[str, object] = {"fate": node.fate}
    if node.filter.card_types:
        # "You choose **a creature card** from it." (Ostracize.) The positive
        # twin of ``exclude_types`` below, emitted only when the card prints it
        # so Duress's payload stays byte-identical — and emitted at all for that
        # key's reason: what the picker offers and what an answer is checked
        # against are one predicate, so a type only the handler knew about is a
        # client offering the whole hand.
        payload["card_types"] = list(node.filter.card_types)
    if node.filter.excluded_types:
        payload["exclude_types"] = list(node.filter.excluded_types)
    if node.filter.excluded_basic_lands:
        # Emitted only when the card prints it, so Duress's payload stays
        # byte-identical — and emitted at all, because a phrase the production
        # consumes and the payload drops is a picker offering a Mountain while
        # the card says otherwise.
        payload["exclude_basic_lands"] = True
    # Both keys are emitted only when the card carries them, so Duress's payload
    # stays byte-identical and no behaviour signature moves.
    amount = _amount_payload(node.count)
    if amount != 1:
        payload["count"] = amount
    if node.up_to:
        # "…choose **up to** X cards from it" (Discordant Dirge). CR 601.2c's
        # ceiling, carried so the prompt lets the chooser stop early. Emitted
        # only when the card prints the words, for the reason the two keys above
        # are: every earlier printing names exactly as many as it says, and its
        # payload stays byte-identical.
        payload["up_to"] = True
    if not node.revealed:
        payload["looked_at"] = True
    if node.player.kind == "that_player":
        # "Look at **that player's** hand …" (Leshrac's Sigil). Nothing was
        # targeted, so there is no choice to read the seat off: it is the one
        # the firing event froze (CR 603.10), on the key its fire site stamps.
        # Refused under any other event rather than left to `context.target`,
        # which for a trigger that chose nothing is whatever the resolution
        # happened to be carrying — an opponent's hand emptied by accident.
        if event not in _EVENT_SUBJECT_PLAYERS:
            raise LoweringError(
                f"no event named {event!r} freezes the seat 'that player' names",
                node=node,
            )
        payload["victim"] = EVENT_SUBJECT_PLAYER
        return (OracleInstruction("reveal_hand_and_choose", "", payload),)
    _describe_targets(payload, node.player)
    if "targets" not in payload:
        raise LoweringError(
            f"the revealed-hand picker cannot name the {node.player.kind}",
            node=node,
        )
    return (OracleInstruction("reveal_hand_and_choose", "", payload),)


def _lower_exile_graveyard(node: ast.ExileGraveyard) -> tuple[OracleInstruction, ...]:
    """"Exile target player's graveyard." (Tormod's Crypt.)

    The whole zone, so there is no filter to carry and no card to resolve —
    only which player's graveyard, which is the target description.

    "Exile **all graveyards**" (Bazaar of Wonders) is the same move over every
    seat, and it is the *absence* of a target description that says so: the
    handler sweeps every player when nothing named one, and the picker asks for
    nothing because ``targets`` is not there to be read. One kind rather than
    two, because what happens to each pile is identical — only how many piles
    differs.
    """
    if node.player is None:
        return (OracleInstruction("exile_target_graveyard", "", {"every": True}),)
    return (
        OracleInstruction("exile_target_graveyard", "", _targets_only(node.player)),
    )


def _lower_look_at_hand(node: ast.LookAtHand) -> tuple[OracleInstruction, ...]:
    """"Look at target player's hand." (Glasses of Urza.)

    ``look_at_target_hand`` reads one chosen player off the resolution context
    and builds a single reveal from their hand. "Each opponent's hand" would
    need a loop it does not have and "your hand" is not an effect at all, so
    only the targeted form has a contract to lower onto.
    """
    if node.player.kind != "target_player":
        raise LoweringError(
            f"no handler for looking at {node.player.kind!r}'s hand", node=node
        )
    payload = dict(_targets_only(node.player))
    if node.random_card:
        # "…**a card at random** in target player's hand" (Urza's Bauble). How
        # much of the hand is shown, emitted only when the card narrows it, so
        # Glasses of Urza's payload stays byte-identical.
        payload["random_card"] = True
    return (OracleInstruction("look_at_target_hand", "", payload),)


def _lower_separate_library_top_into_piles(
    node: "ast.SeparateLibraryTopIntoPiles",
) -> tuple[OracleInstruction, ...]:
    """Phyrexian Portal's whole procedure, one instruction.

    The splitter travels as a *targets* description rather than as a bare seat
    word, because "target opponent" is a choice made at announcement (CR
    601.2c) and the picker reads that payload - a card whose splitter was a
    literal would offer no picker and let the client send a bare activation.

    The count is payload; the shape is not. Two piles, face down, one exiled
    and the other searched is what the card *is*, and a wording that differed
    refuses at the production rather than arriving here as another key.
    """
    if node.splitter.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"no pile split names {node.splitter.kind!r} as its divider",
            node=node,
        )
    payload: dict[str, object] = {"count": _amount_payload(node.count)}
    _describe_targets(payload, node.splitter)
    return (
        OracleInstruction("separate_library_top_into_piles", "", payload),
    )


def _lower_look_top_cycle_for_life(
    node: "ast.LookTopCycleForLife",
) -> tuple[OracleInstruction, ...]:
    """Lim-Dul's Vault's whole procedure, one instruction (CR 701.24).

    Both numbers travel as payload for the reason every parameter in this
    pipeline does: a card cycling three cards for 2 life needs no code. What
    does *not* travel is the shape - the bottom, the shuffle and the stack on
    top are the effect itself, so a wording that sorted them elsewhere refuses
    at the production rather than arriving here as a fourth key.
    """
    return (
        OracleInstruction(
            "look_top_cycle_and_stack", "",
            {
                "count": _amount_payload(node.count),
                "life_cost": _amount_payload(node.life_cost),
            },
        ),
    )


def _lower_put_library_top_into_hand(
    node: "ast.PutLibraryTopIntoHand", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"Put **that many** cards from the top of your library into your hand."
    (Scroll Rack.)

    Not a draw, which is the whole reason there is an instruction here rather
    than a ``Draw`` — see the node. What the lowering has to settle is the
    count, and on the one card printing this sentence it is a back-reference to
    the exile in front of it: ``_back_reference_payload`` decides where it is
    read from, once, so a card printing a number instead needs no code.
    """
    if isinstance(node.count, ast.ThatMuch):
        payload: dict[str, object] = {
            "amount": 0, **_back_reference_payload(node.count, produced, None),
        }
    else:
        payload = {"amount": _amount_payload(node.count)}
    return (OracleInstruction("put_library_top_into_hand", "", payload),)












def _lower_graveyard_top_to_library(
    node: ast.GraveyardTopToLibrary,
) -> tuple[OracleInstruction, ...]:
    """"If the top card of target player's graveyard is a creature card, put
    that card on top of that player's library." (Guiding Spirit.)

    Only a chosen player has a flow, for :func:`_lower_look_at_library_top`'s
    reason one function down: the handler reads one seat off the resolution
    context, and a phrase naming several would need a loop it does not have.

    The filter is tested against a **card**, not a permanent — a graveyard holds
    cards (CR 400.1) — so it goes through the card matcher's own gate, which
    refuses a narrowing that matcher cannot answer rather than dropping it. A
    dropped narrowing here is a card moved when the printed sentence said it
    should stay.
    """
    if node.player.kind != "target_player":
        raise LoweringError(
            f"no flow reads the top of {node.player.kind!r}'s graveyard",
            node=node,
        )
    described = card_only_filter(node.filter.to_payload())
    if described is None:
        raise LoweringError(
            "the graveyard's top card cannot be tested for this", node=node
        )
    return (
        OracleInstruction(
            "graveyard_top_to_library", "",
            {"filter": described, **_targets_only(node.player)},
        ),
    )


def _lower_look_at_library_top(
    node: ast.LookAtLibraryTop,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top five cards of target player's library. You may then
    have that player shuffle that library." (Visions.)

    Only a chosen player has a contract to lower onto, for the reason
    :func:`_lower_look_at_hand` gives: the handler reads one player off the
    resolution context, and "each opponent" would need a loop it does not have.

    How many cards and whether the shuffle is offered are both payload. The
    number is obvious; the offer is the one that matters, because the handler
    that reads it today derived the same fact for Natural Selection by matching
    a substring of the card's oracle text — a card printing the offer in any
    other words would have been given a prompt with the option missing.
    """
    # "…of **defending player's** library" (Coral Fighters). CR 506.2's seat,
    # which the combat fire site froze into the trigger's context — not a
    # target, so no picker offers it and nothing here describes one. Admitted
    # only for the bottoming offer below, which is the one card in the pool
    # printing it: a *targeted* look is a spell's choice and this one is a fact
    # about a combat, and the handler reads them from different places.
    defending = node.player.kind == "defending_player"
    # "Look at the top four cards of **your** library, then put them back in
    # any order." (Sage Owl.) The looker's own pile, which is its own kind and
    # not this one with a seat swapped: `reorder_target_library_top` is
    # registered in `engine/targeting.py` as targeting a player, so lowering
    # Sage Owl's trigger onto it would put an ability on the stack asking for a
    # target its printed line never offers. Nothing is looked at *and* nothing
    # is chosen, so the rearrange is the whole effect and the other two offers
    # refuse.
    if node.player.kind == "you":
        if not node.may_reorder or node.may_shuffle or node.may_bottom:
            raise LoweringError(
                "the own-library look only rearranges what it saw", node=node
            )
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError("the library look needs a printed number", node=node)
        return (
            OracleInstruction(
                "reorder_own_library_top", "", {"amount": node.count.value}
            ),
        )
    # "…of **target opponent's** library" (Precognition). The same targeted
    # look, narrowed to which seats the picker may offer (CR 115.4) — that
    # narrowing rides on the targets description ``_targets_only`` builds, and
    # the handler reads ``context.target`` either way. It was refused because
    # the one card printing a targeted look happened to say "player"; reading it
    # as a plain target player instead would have let the caster look at their
    # own library, which is a card that does nothing.
    if node.player.kind not in (
        "target_player", "target_opponent",
    ) and not (defending and node.may_bottom):
        raise LoweringError(
            f"no handler looks at the top of {node.player.kind!r}'s library", node=node
        )
    if not isinstance(node.count, ast.Fixed):
        raise LoweringError("the library look needs a printed number", node=node)
    payload: dict[str, object] = {
        "amount": node.count.value,
        "may_shuffle": node.may_shuffle,
    }
    if defending:
        payload["who"] = "defending_player"
    else:
        payload.update(_targets_only(node.player))
    # "**You may put that card on the bottom of that player's library.**"
    # (Coral Fighters.) Its own kind rather than a flag on the look, for
    # `may_reorder`'s stated reason one field over: the permission is enforced
    # where the prompt is answered, so a card that only looks can never be
    # handed the offer.
    if node.may_bottom:
        if node.may_shuffle or node.may_reorder:
            raise LoweringError(
                "one look offers one thing to do with what it saw", node=node
            )
        return (
            OracleInstruction("look_at_library_top_then_bottom", "", payload),
        )
    # "…then put them back in any order" is the *other* handler, not a flag on
    # this one: `may_reorder` is enforced where the prompt is answered, so a
    # card that only looks can never be handed a rearrangement.
    kind = (
        "reorder_target_library_top" if node.may_reorder
        else "look_at_target_library_top"
    )
    return (OracleInstruction(kind, "", payload),)


def _lower_look_top_pick(
    node: ast.LookTopPickToHand, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top three cards of your library. Put one of those cards
    into your hand and the rest on the bottom of your library in any order.
    …" (See the Truth.) The handler asks its controller through the
    pending-choice queue when cast from the hand, and skips the choice
    entirely when the cast came from anywhere else — the conditional reads
    ``OracleExecutionContext.cast_from_zone``."""
    payload: dict[str, object] = {}
    # "Look at **that many** cards" (Garruk's Harbinger): the count is the
    # firing event's number, read out of the trigger's captured context by the
    # same channel every other back-reference uses. Demanded of the event rather
    # than assumed: under a trigger that records no quantity the words name
    # nothing, and a silent zero would look at no cards at all.
    if isinstance(node.count, ast.ThatMuch):
        payload.update(_back_reference_payload(node.count, frozenset(), event))
    else:
        amount = _amount_payload(node.count)
        # "…the top **X** cards" (Sealed Fate). The announced value (CR 601.2b),
        # which the handler resolves against ``context.x_value`` — the same
        # channel every other counted zone effect reads. Admitted beside a
        # printed number rather than instead of it: what is refused is a count
        # this handler has no way to take at all, which is what "the pick takes
        # a fixed count" was really saying.
        if amount != "x" and (not isinstance(amount, int) or amount <= 0):
            raise LoweringError("the look-top pick takes a fixed count", node=node)
        payload["amount"] = amount
    # "Put **two** of them into your hand" (Ancestral Memories). Emitted only
    # when the card prints a number other than one, so every payload written
    # before this is byte-identical.
    picks = _amount_payload(node.pick_count)
    if not isinstance(picks, int) or picks <= 0:
        raise LoweringError("the look-top pick takes a fixed pick count", node=node)
    if picks > 1:
        # Several picks are a *chain* of one-card prompts (see
        # ``_resolve_look_top_pick``), and each link looks at what is left of
        # the same pile. So a destination that puts the card **back** in that
        # pile refuses: "puts one of them back on top of their library"
        # (Ashnod's Cylix) names a single card by construction, and a chain
        # spelled that way would re-offer the card it just placed. The two
        # destinations that take the card out of the library entirely — a hand
        # (Ancestral Memories) and exile (Ancestral Knowledge) — are the chain's
        # whole vocabulary, and ``optional`` rides along because "exile **any
        # number of** them" is a chain the looker may stop at any link.
        if node.pick_destination not in ("hand", "exile"):
            raise LoweringError(
                "several picks leave the library, and this destination puts one "
                "back in it",
                node=node,
            )
        payload["pick_count"] = picks
    if node.filters:
        described = [chargeable_card_filter(filt) for filt in node.filters]
        if any(entry is None for entry in described):
            raise LoweringError(
                "the pick cannot test this restriction on a card", node=node
            )
        payload["filters"] = tuple(described)
    if node.optional:
        payload["optional"] = True
    if node.rest_order != "any":
        payload["rest_order"] = node.rest_order
    if node.rest_destination != "library_bottom":
        payload["rest_destination"] = node.rest_destination
    if node.pick_destination != "hand":
        payload["pick_destination"] = node.pick_destination
    if node.all_to_hand_if_cast_elsewhere:
        payload["all_to_hand_if_cast_elsewhere"] = True
    # Who looks, when the sentence names them. Only the one seat this handler
    # can find without a second question: "target player" is chosen as the
    # ability is activated (CR 602.2b) and arrives as ``context.target``.
    # Anything else refuses rather than defaulting to the controller — a look
    # at the wrong library is a card doing something it never said, and the
    # pile is hidden, so nobody would see it happen.
    if node.looker is not None:
        if node.looker.kind != "target_player":
            raise LoweringError(
                "the look-top pick reads the library of the player the ability "
                "chose",
                node=node,
            )
        payload["looker"] = "target_player"
    # "…the top X cards of **target opponent's** library" (Sealed Fate). The
    # pile is the chosen player's and the decisions are the caster's, which is
    # the other half of the seat question ``looker`` answers with one word.
    # Only a chosen seat, for ``looker``'s reason: an unchosen one would send
    # the look at whichever library the resolution happened to be carrying, and
    # the pile is hidden, so nobody would see it happen.
    if node.pile_owner is not None:
        if node.pile_owner.kind not in ("target_player", "target_opponent"):
            raise LoweringError(
                "the look-top pick reads the library of the player the spell "
                "chose",
                node=node,
            )
        payload["pile_owner"] = node.pile_owner.kind
        _describe_targets(payload, node.pile_owner)
    return (OracleInstruction("look_top_pick_to_hand", "", payload),)


def _lower_look_top_exile_random(
    node: ast.LookTopExileRandom,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top eight cards of your library. Exile four of them at
    random, then put the rest on top of your library in any order." (Orcish
    Librarian.)

    Both counts are fixed numbers the card prints. A back-reference would have
    to name an event this statement has no access to, and an X would have to
    survive to a resolution that happens after the cost is paid — neither is a
    shape any printing of this sentence has, so both refuse rather than
    resolving to a silent zero.
    """
    looked = _amount_payload(node.count)
    exiled = _amount_payload(node.exile_count)
    if not isinstance(looked, int) or looked <= 0:
        raise LoweringError("the look-and-exile takes a fixed count", node=node)
    if not isinstance(exiled, int) or exiled <= 0:
        raise LoweringError("the random exile takes a fixed count", node=node)
    if exiled > looked:
        raise LoweringError(
            "more cards are exiled than are looked at", node=node
        )
    return (
        OracleInstruction(
            "look_top_exile_random", "",
            {"amount": looked, "exile_count": exiled},
        ),
    )


def _lower_graveyard_pick_onto_battlefield(
    node: ast.PutOntoBattlefield,
) -> tuple[OracleInstruction, ...] | None:
    """"Put **a** creature card from the graveyard of <player> onto the
    battlefield **under its owner's control**." (Glyph of Reincarnation.)

    Here rather than beside the rest of the "put … onto the battlefield" family
    in ``lowering/zones``, because what it emits decides the family: no
    ``target`` is printed, so the card is not chosen until the effect resolves
    (CR 115.1b), and a pick made during resolution out of a named zone is a
    *search prompt* — the same instruction ``_lower_search_library`` above
    emits, narrowed to a graveyard. Sending it to the reanimation handler
    instead would have made it a cast-time target, which is a different card:
    the graveyard it comes out of is named by a referent nobody can evaluate
    until the earlier sentence has run.

    Returns None for every other "put onto the battlefield", so ``lower.py``
    falls through to that family and a line this is not keeps the refusal it
    already had.
    """
    target = node.target
    if not isinstance(target, ast.TargetSpec) or _is_target(target):
        return None
    filt = target.filter
    if filt.zone != "graveyard" or filt.zone_owner is None:
        return None
    record = PER_OBJECT_SEAT_RECORDS.get(filt.zone_owner.kind)
    if record is None:
        # Every *other* graveyard referent — "your graveyard", "that player's"
        # — is a seat the resolving player knows without any earlier step
        # having recorded it, and none of them is this shape. Handing them back
        # rather than refusing keeps this production additive.
        return None
    if not filt.is_card or filt.card_types != ("creature",):
        raise LoweringError(
            "this graveyard pick only moves creature cards", node=node
        )
    if _restrictions_beyond(
        filt, frozenset({"card_types", "is_card", "zone", "zone_owner"})
    ):
        raise LoweringError(
            "no graveyard pick reads a card narrowed this way", node=node
        )
    if not node.under_owners_control:
        # The card enters under whoever owns the graveyard it left, and that is
        # what the printed rider says. A sentence naming some *other* seat would
        # need a second reference here rather than this one standing in for it.
        raise LoweringError(
            "this graveyard pick only puts the card back under its owner's "
            "control", node=node,
        )
    return (
        OracleInstruction(
            "search_library",
            "",
            {
                "count": 1,
                "card_type": "creature",
                # A graveyard is an open zone, so nothing is revealed and
                # nothing is shuffled — the prompt is a pick, and the resolver
                # already tells the two apart by the zone it was armed with.
                "zones": ["graveyard"],
                "restrictions": {},
                "destination": "battlefield",
                # Whose graveyard, and whose battlefield. The same seat by
                # CR 404.1 — a card in a graveyard is in its owner's — but
                # written twice because the card prints both halves, and a
                # reader that inferred the second would be inferring it for
                # every card that names only the first.
                "zone_owner": record,
                "battlefield_owner": record,
            },
        ),
    )


def _lower_put_graveyard_position_onto_battlefield(
    node: "ast.PutGraveyardPositionOntoBattlefield", event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Put **the top creature card of defending player's graveyard** onto the
    battlefield under your control." (Bone Dancer.)

    Here beside ``_lower_graveyard_pick_onto_battlefield`` because the two
    answer one question — which card leaves a graveyard for the battlefield
    when the sentence names no target — and differ in the one way that decides
    the instruction: that one is a *pick* made as the effect resolves
    (CR 115.1b), and this one names the card by its **position** in an ordered
    pile (CR 404.2), so nobody chooses and no prompt is armed.

    That pair is not in ``lowering/zones``, where the *targeted* reanimation
    lives, and the honest reason is worth recording rather than dressing up:
    the sibling arrived here because of the instruction it emits, this one
    arrived beside the sibling, and ``zones`` is at its thousand-line guard with
    no seam this round found. A later round that splits that module should take
    the three readings of "put a card onto the battlefield" with it.

    Three refusals, each in the direction that cannot widen the effect.

    The **seat** must be one the firing event froze. "Defending player" is
    CR 506.2's, stamped by the combat fire sites, and under any other event the
    words name nobody — the handler would find no pile while the card compiled
    supported. ``graveyard_position_payload`` is the shared gate every reader of
    the phrase runs through; the seat set is *passed* rather than added to its
    default, because a cost paid out of the defending player's graveyard is a
    shape the payment path has no seat for.

    The **count** must be one: a position naming several cards is a sentence
    this handler does not move.

    ``under your control`` is **required**, and it is the whole of the card at a
    table. CR 404.1 puts the card in its owner's graveyard, so the default
    arrival (CR 400.3) is under the seat being attacked — a sentence that shed
    the rider would hand the defending player a creature.
    """
    payload = graveyard_position_payload(
        node.position, seats=frozenset({"defending_player"})
    )
    if payload is None:
        raise LoweringError(
            "no handler reads that graveyard position onto the battlefield",
            node=node,
        )
    if event not in _DEFENDING_PLAYER_EVENTS:
        raise LoweringError(
            "'defending player's graveyard' names the seat the combat "
            "froze, and this event records none",
            node=node,
        )
    if payload.get("count") != 1:
        raise LoweringError(
            "the graveyard-position reanimation moves one card", node=node
        )
    if not node.under_your_control:
        raise LoweringError(
            "the graveyard-position reanimation only puts the card under your "
            "control", node=node,
        )
    payload["graveyard_owner"] = payload.pop("owner")
    return (
        OracleInstruction("reanimate_graveyard_position", "", payload),
    )


def _lower_play_with_hand_revealed(
    node: "ast.PlayWithHandRevealed", event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """Stromgald Spy: "…have **defending player play with their hand revealed
    for as long as this creature remains on the battlefield**."

    Two refusals, both by name.

    The **duration** must be the linked one. That is the whole of what makes the
    effect implementable without a sweep: the record goes on the source and
    ``engine/revealed_hands.py`` scans the battlefield for it, so a permanent
    that leaves stops contributing (CR 611.2b) and a returning one is a new
    object with no record (CR 400.7). Any other duration would need something
    to end it, and nothing does.

    The **seat** must be one an event froze. "Defending player" is CR 506.2's,
    stamped by the combat fire sites, and outside those events nothing recorded
    it — an effect that silently revealed nobody's hand rather than one somebody
    declined.
    """
    if node.duration.kind != "while_source_on_battlefield":
        raise LoweringError(
            "a hand is revealed for as long as the source is on the "
            f"battlefield, not {node.duration.kind or 'indefinitely'}",
            node=node,
        )
    if node.player.kind != "defending_player":
        raise LoweringError(
            f"no seat record names {node.player.kind!r} for a revealed hand",
            node=node,
        )
    if event not in _DEFENDING_PLAYER_EVENTS:
        raise LoweringError(
            '"defending player" names a seat this event did not record',
            node=node,
        )
    return (
        OracleInstruction("reveal_hand_while_source_present", "", {
            "player": node.player.kind,
        }),
    )
