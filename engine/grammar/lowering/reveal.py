"""Lowering what a card **reveals** — CR 701.20a, the public half of a look.

The mirror of ``effects/reveal.py``, formed one wave after it: that module split
off ``effects/library.py`` at Tempest's second wave and this file's note in
``tests/engine/test_grammar_layering.py`` said the lowering side would stay put,
because "a reveal lowers to one instruction however elaborately its sentence is
printed". That was a claim about a *size*, and the size changed the same day —
Wood Sage's sorted reveal, Phyrexian Grimoire's graveyard pick and Scroll Rack's
library-to-hand took ``lowering/library.py`` to 1,001 lines. It is the move
``search`` made at Visions' first wave, for the same reason and in the same
direction.

The line is the one ``effects/reveal.py`` already draws and CR draws inside one
rule: a **reveal** (CR 701.20a) shows a card to all players, and a **look**
(CR 701.20e) "follows the same rules as revealing a card, except that the card
is shown only to the specified player". Everything here starts from a pile
somebody has been *shown*; everything left in ``library`` is a look, a search,
or a card moved out of a pile nobody saw.

Nothing here calls anything left in ``library`` and nothing there calls
anything here, which is what lets the two sit side by side as families.
"""

from __future__ import annotations

from ...oracle_types import (LAST_TARGET_CONTROLLER, OracleInstruction,
                             REVEALED_HAND_CARDS, REVEALED_THIS_WAY)
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import _amount_payload, _describe_targets


def _lower_reveal_until(
    node: ast.RevealUntil, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """Transmogrify's reveal-until-match, as one instruction.

    Demands the producer, like every other back-reference: "that creature's
    controller" is the seat the *exile* step recorded, and without that step
    there is nobody to read the library of — the effect would silently fall back
    to the caster, which is the opposite player from the one the card names.
    """
    if node.whose == LAST_TARGET_CONTROLLER and node.whose not in produced:
        raise LoweringError(
            "\"that creature's controller\" with no exile before it", node=node,
        )
    described = card_only_filter(node.filter.to_payload())
    if described is None:
        raise LoweringError(
            "the reveal cannot test this restriction on a card", node=node,
        )
    return (
        OracleInstruction(
            "reveal_until_match", "",
            {
                "whose": node.whose,
                "filter": described,
                "destination": node.destination,
                "rest": node.rest,
            },
        ),
    )


def _lower_reveal_top(node: ast.RevealTopToHandOrBottom) -> tuple[OracleInstruction, ...]:
    """"Reveal the top card of your library. If it's a <filter> card, put it
    into your hand. Otherwise, put it on the bottom of your library." (Garruk,
    Savage Herald's +1.) The filter is the whole decision, so it is carried as
    payload the handler tests with primary_type."""
    if not node.filter.is_card or len(node.filter.card_types) != 1:
        raise LoweringError("the reveal-top handler tests one card type", node=node)
    return (
        OracleInstruction(
            "reveal_top_to_hand_or_bottom", "", {"card_type": node.filter.card_types[0]}
        ),
    )


def _lower_reveal_top_sorting_by_chosen_name(
    node: "ast.RevealTopSortingByChosenName", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"Reveal the top four cards of your library and put all of them with
    **that name** into your hand. Put the rest into your graveyard." (Wood
    Sage.)

    ``produced`` is the whole gate. "That name" is the one an earlier step of
    this same ability chose (``choose_card_name``), and with no such step the
    words name nothing — the sort would then match no card and put the whole
    revealed pile in the graveyard, which is a card that plays, compiles and
    reads supported while doing the opposite of what it prints. Refused by name
    instead, exactly as ``_lower_reveal_until`` refuses a library nobody named.
    """
    if "chosen_card_name" not in produced:
        raise LoweringError(
            "\"that name\" names a card no step of this effect chose",
            node=node,
        )
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count <= 0:
        raise LoweringError(
            "the revealed pile is a fixed number of cards", node=node
        )
    return (
        OracleInstruction(
            "reveal_top_sorting_by_chosen_name", "",
            {
                "amount": count,
                "match_zone": node.match_zone,
                "rest_zone": node.rest_zone,
            },
        ),
    )


def _lower_reveal_top_sorting_by_filter(
    node: "ast.RevealTopSortingByFilter",
) -> tuple[OracleInstruction, ...]:
    """"Reveal the top four cards of your library. Put all **land cards**
    revealed this way into your hand and the rest into your graveyard." (Mulch.)

    :func:`_lower_reveal_top_sorting_by_chosen_name` with the predicate printed
    on the card, which is why this one takes no ``produced``: the sentence
    carries its own test, so there is no earlier step whose absence could turn
    the sort into a mill.

    The filter goes through ``card_only_filter`` for
    :func:`_lower_reveal_until`'s reason — a pile off a library is cards
    (CR 400.1), so a restriction that can only be tested on a permanent is one
    the sort would silently drop, and dropping it here would put the whole pile
    in the hand.
    """
    described = card_only_filter(node.filter.to_payload())
    if described is None:
        raise LoweringError(
            "the sorted reveal cannot test this restriction on a card",
            node=node,
        )
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count <= 0:
        raise LoweringError(
            "the revealed pile is a fixed number of cards", node=node
        )
    # "**Each player** reveals the top five cards of **their** library."
    # (Clear the Land.) Whose pile, and the only value beside the absent one:
    # "your" is the caster's, which is what every printing before this said by
    # saying nothing. A seat the handler cannot loop over refuses rather than
    # turning the table's libraries into one.
    whose = node.whose.kind if node.whose is not None else None
    if whose not in (None, "you", "each_player"):
        raise LoweringError(
            f"the sorted reveal opens your own library or each player's, "
            f"not {whose!r}",
            node=node,
        )
    extra: dict[str, object] = {}
    if whose == "each_player":
        extra["whose"] = "each_player"
    # "…onto the battlefield **tapped**" — CR 110.5b, and only ever on the
    # match half, which is where the word is printed. Carried only when the
    # sentence prints it, so Mulch's payload stays byte-identical.
    if node.tapped:
        if node.match_zone != "battlefield":
            raise LoweringError(
                "only a find that enters the battlefield can arrive tapped",
                node=node,
            )
        extra["match_tapped"] = True
    return (
        OracleInstruction(
            "reveal_top_sorting_by_filter", "",
            {
                "amount": count,
                "filter": described,
                "match_zone": node.match_zone,
                "rest_zone": node.rest_zone,
                **extra,
            },
        ),
    )


def _lower_graveyard_top_opponent_chooses(
    node: "ast.GraveyardTopOpponentChooses",
) -> tuple[OracleInstruction, ...]:
    """"Target opponent chooses one of the top two cards of your graveyard.
    Exile that card and put the other one into your hand." (Phyrexian
    Grimoire.)

    One instruction, for :func:`_lower_reveal_top_opponent_chooses`' reason:
    the pick is made **from** the pile the first half names and both fates are
    about what the pick left behind.

    The chooser is required to be a targeted opponent, for that function's
    reason exactly: CR 608.2c makes the ability's controller the actor for
    anything a sentence does not say otherwise about, so a seat this cannot
    name would silently become the chooser — which on this card is the
    controller choosing which of their own cards they keep.
    """
    if node.chooser.kind != "target_opponent":
        raise LoweringError(
            f"no flow lets {node.chooser.kind!r} choose from a graveyard's top",
            node=node,
        )
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count <= 0:
        raise LoweringError(
            "the graveyard pile is a fixed number of cards", node=node
        )
    payload: dict[str, object] = {
        "count": count,
        "from_zone": "graveyard",
        "fate": node.chosen_fate,
        "other_fate": node.other_fate,
    }
    _describe_targets(payload, node.chooser)
    return (
        OracleInstruction("reveal_top_opponent_chooses", "", payload),
    )


def _lower_reveal_top_opponent_chooses(
    node: ast.RevealTopOpponentChooses,
) -> tuple[OracleInstruction, ...]:
    """"Reveal the top three cards of your library. Target opponent chooses one
    of those cards. Put that card into your graveyard, then draw two cards."
    (Thran Tome.)

    Two instructions, not one. The reveal, the pick and the binning are a single
    step because the pick is made **from** what the reveal showed and the
    binning is what the pick was for \u2014 ``RevealHandAndChoose`` one zone over
    records the same reasoning. The draw behind them is an ordinary effect that
    happens afterwards (CR 608.2), so it composes as its own step; the prompt
    suspends the sequence, which is what keeps it from drawing before the
    opponent has chosen.

    The chooser is required to be a targeted opponent. CR 608.2c makes the
    ability's controller the actor for everything a spell does not say
    otherwise about, so a seat this cannot name would silently become the
    revealer \u2014 which is the card choosing its own discard.
    """
    if node.chooser.kind != "target_opponent":
        raise LoweringError(
            f"no flow lets {node.chooser.kind!r} choose from a revealed pile",
            node=node,
        )
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count <= 0:
        raise LoweringError(
            "the revealed pile is a fixed number of cards", node=node
        )
    payload: dict[str, object] = {"count": count, "fate": node.fate}
    _describe_targets(payload, node.chooser)
    steps = [OracleInstruction("reveal_top_opponent_chooses", "", payload)]
    if node.then_draw is not None:
        drawn = _amount_payload(node.then_draw)
        if not isinstance(drawn, int) or drawn <= 0:
            raise LoweringError("this draw takes a printed number", node=node)
        steps.append(
            OracleInstruction("draw_controller_cards", "", {"amount": drawn})
        )
    if len(steps) == 1:
        return (steps[0],)
    return (OracleInstruction("sequence", "", {"steps": tuple(steps)}),)


def _lower_bin_revealed_card(
    node: ast.BinRevealedCard, produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"…**put it into that player's graveyard**." (Wand of Denial.)

    A back-reference names its producer or refuses: without a step in front of
    it that turned a card up, "it" names nothing and the handler would answer
    "no card" forever while the line compiled clean.

    Only the looked-at player's own graveyard, which is where CR 400.3 sends the
    card anyway — a phrase naming somebody else's would be describing a move
    this cannot make.
    """
    if "revealed_card" not in produced:
        raise LoweringError(
            "'it' with nothing in this effect that turned a card up", node=node
        )
    if node.player.kind not in ("that_player", "target_player"):
        raise LoweringError(
            f"a looked-at card goes to its owner's graveyard, not "
            f"{node.player.kind!r}'s",
            node=node,
        )
    return (OracleInstruction("bin_revealed_card", "", {}),)


def _lower_put_revealed_card_onto_battlefield(
    node: ast.PutOntoBattlefield, produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"Reveal the top card of your library. If it's a creature card, **put it
    onto the battlefield**." (Call of the Wild.)

    ``_lower_bin_revealed_card``'s sibling one destination over, and here for
    its reason: "it" is the card an earlier step of this same effect turned up,
    which is still on top of the library (CR 701.20 moves nothing), so the
    handler has to take it out of the pile rather than read a target index.

    A back-reference names its producer or refuses. Without a reveal in front of
    it the pronoun names the ability's own source, which for this destination is
    a permanent putting itself onto the battlefield it is already on — so this
    returns None rather than raising, and the ordinary battlefield lowering
    keeps its reading and its refusal.
    """
    if "revealed_card" not in produced:
        return ()
    # "…put **those cards** onto the battlefield under their owners' control."
    # (Game Preserve.) The plural back-reference, which is a different record —
    # one card per seat rather than the single ``revealed_card`` this branch
    # reads — and so a different handler. Declined rather than refused, so the
    # battlefield lowering keeps its reading: a per-player reveal writes *both*
    # records, and without this the singular reading claimed the plural
    # sentence and failed it on the owner clause.
    if (
        isinstance(node.target, ast.TargetSpec)
        and node.target.quantifier == "those"
    ):
        return ()
    if node.under_owners_control or node.gains or node.sacrifice_when_control_lost:
        raise LoweringError(
            "the revealed card enters under its owner's control with no rider",
            node=node,
        )
    return (OracleInstruction("put_revealed_card_onto_battlefield", "", {}),)


def _lower_reveal_cards_from_hand(
    node: ast.RevealCardsFromHand,
) -> tuple[OracleInstruction, ...]:
    """"Reveal any number of artifact cards in your hand." (Metalworker.)

    The reveal alone: nothing moves and nothing is spent, and the sentence
    after it reads the count off the record this writes. Two records for the
    one step, because the two questions a following sentence can ask are
    different ones — see ``oracle_types.REVEALED_THIS_WAY``.

    ``zone`` and ``zone_owner`` are honoured **by construction** rather than
    carried in the payload — this instruction reads one hand and it is the hand
    of the seat performing the effect — so they are dropped here and everything
    else in the printed phrase has to survive ``card_only_filter``. A narrowing
    that cannot be tested refuses the line rather than being dropped, because a
    prompt offering a wider set than the card prints is a card that reports
    supported and cheats: "reveal any number of blue cards" that offered the
    whole hand is Brine Seer countering for the size of a hand.
    """
    from ._common import _restrictions_beyond, _PAYLOAD_HONOURED_FILTER_FIELDS

    filt = node.filter
    # The gate ``card_only_filter`` below cannot supply: ``to_payload`` emits
    # **nothing** for a relative narrowing, so a phrase this cannot honour
    # would arrive here already reduced to the bare noun and the reveal would
    # offer a wider set than the card prints. Refused rather than widened —
    # the same check ``_lower_choose_cards_in_hand`` makes of the same zone.
    leftover = _restrictions_beyond(
        filt,
        _PAYLOAD_HONOURED_FILTER_FIELDS | {"is_card", "zone", "zone_owner"},
    )
    if leftover:
        raise LoweringError(
            f"the reveal does not honour {leftover[0]!r}", node=node
        )
    payload_filter = filt.to_payload()
    payload_filter.pop("zone", None)
    payload_filter.pop("zone_owner", None)
    described = card_only_filter(payload_filter)
    if described is None:
        raise LoweringError(
            "the reveal cannot test this restriction on a card in a hand",
            node=node,
        )
    return (
        OracleInstruction(
            "reveal_cards_from_hand", "",
            {
                "card_filter": described,
                # The printed offer: nought to as many as answer the phrase.
                # A key rather than a count of -1, because "how many may I
                # pick" and "how many must I pick" are two questions and the
                # prompt has to gate on both.
                #
                # "Reveal **a** creature card in your hand" (Assembly Hall)
                # prints a number instead, and the prompt reads both keys —
                # ``_how_many_cards_to_choose`` takes the count and
                # ``_may_choose_fewer_cards_in_hand`` the flag — so a card that
                # names one card owes one where the hand holds it. Every payload
                # written before this stays byte-identical: absent means "any
                # number", which is what those cards print.
                "any_number": node.count is None,
                **({} if node.count is None else {"count": int(node.count)}),
                # CR 701.20a: what is picked is shown to *all* players. Its own
                # key rather than the count below, because the two are separate
                # questions — Sylvan Library's pick records a set and is not
                # public — and the shared prompt reads this one to say so.
                "reveal": True,
                "result_key": REVEALED_HAND_CARDS,
                "count_key": REVEALED_THIS_WAY,
            },
        ),
    )
