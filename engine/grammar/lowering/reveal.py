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
somebody has been *shown*; everything left in ``library`` is a look, or a card
moved out of a pile nobody saw.

**That sentence was false from the day it was written until Invasion, and what
it was false about was a hand.** The cut that formed this module took the
reveals of a *library's top* and left every reveal of a *hand* behind:
``_lower_reveal_hand``, the card revealed at random, the two "discards it unless
they pay life" offers, Duress's reveal-and-choose and Stromgald Spy's standing
reveal. So the family line ran through the middle of two records. A step that
turned one card up wrote ``revealed_card``, and ``_lower_bin_revealed_card``
demanded it here while ``_lower_discard_revealed_unless_pay_life`` demanded it
there; ``_lower_reveal_cards_from_hand`` (Metalworker, which arrived here
directly at Urza's Destiny) writes ``REVEALED_HAND_CARDS`` and the "for each …
card revealed this way" discard that requires it sat a module away. They came
across at the Phase 0 between Invasion's two waves, when ``library`` was thirty
lines under the guard, and they are the second block below. (It also said "a
search", which had been ``lowering/search.py``'s since Visions.)

The line is drawn per **node**, so one function carries a look across with it
and says so: ``RevealHandAndChoose`` is one node and one instruction for
"reveals their hand. You choose …" (Duress) and for "Look at target player's
hand and choose …" (Mind Warp, the ``looked_at`` key), because the pick, the
picker and the fate of what was picked are identical either way. ``library``
carries the mirror image — "**Reveal** a number of cards …" as a ``revealed``
key on its look-and-pick. A bare look at a hand chooses nothing and stays
there.

``_lower_reveal_hand_and_choose`` is the half of the hand block that grows:
every narrowing a new printing puts on "a … card from it" lands in it and in
``_REVEALED_HAND_FIELDS`` above it.

Nothing here calls anything left in ``library`` and nothing there calls
anything here, which is what lets the two sit side by side as families.
"""

from __future__ import annotations

from ...oracle_types import (CHOSEN_COLOR_THIS_WAY, LAST_TARGET_CONTROLLER,
                             OracleInstruction, REVEALED_HAND_CARDS,
                             REVEALED_THIS_WAY)
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS,
    _amount_payload,
    _describe_targets,
    _restrictions_beyond,
    _targets_only,
    dropped_narrowings,
)
from ._events import (
    _DAMAGED_PLAYER_EVENTS,
    _DEFENDING_PLAYER_EVENTS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_PLAYER,
)


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
    if (
        node.under_owners_control or node.gains
        or node.sacrifice_when_control_lost or node.tapped
    ):
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


# ---------------------------------------------------------------------------
# A hand revealed whole, and what the sentence behind the reveal does with it.
#
# Moved here from `lowering/library.py` at the Phase 0 between Invasion's two
# waves, byte-identical — see the module docstring for why they were there and
# why they are not now.
# ---------------------------------------------------------------------------


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
#: ``excluded_supertypes`` is the fifth, and it arrived with Encroach's "a
#: **nonbasic** land card". A supertype exclusion rather than the basic-land
#: pair beside it: the noun phrase has already said "land", so what the "non"
#: excludes is CR 205.4a's word alone — and ``search_matches`` reads it off the
#: printed type line's supertype half, which is what a card outside the
#: battlefield has instead of characteristics (CR 613.1).
_REVEALED_HAND_FIELDS = frozenset(
    {"excluded_types", "is_card", "excluded_basic_lands", "card_types",
     "excluded_supertypes"}
)


def _lower_reveal_hand(
    node: ast.RevealHand, event: str | None = None
) -> tuple[OracleInstruction, ...]:
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
    # "Whenever Crosis deals combat damage to a player, … **that player**
    # reveals their hand …" (Crosis, the Purger; Darigaaz, the Igniter.) The
    # seat the damage froze (CR 603.10), under the word ``discard_hand`` already
    # spells it with — and admitted only under an event whose fire site really
    # recorded a damaged player, the gate that sentence is held to: under any
    # other trigger the words name nobody, and the handler's fallback is the
    # ability's own controller.
    if node.player.kind == "that_player" and event in _DAMAGED_PLAYER_EVENTS:
        return (OracleInstruction("reveal_hand", "", {"who": "damaged_player"}),)
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
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"Target opponent reveals their hand. You choose a noncreature, nonland
    card from it. That player discards that card." (Duress.)

    One instruction for the whole template: the reveal is what makes the choice
    legal, and the discard is what the choice was for, so splitting them would
    put a chosen card between two instructions with nothing carrying it.
    """
    # "Choose a color. … you choose a card **of that color** from it." (Addle.)
    # CR 608.2d's colour, admitted only behind a step that chose one and
    # carried as the scratchpad key Persecute's discard reads.
    of_that_color = (
        node.filter.color_chosen_this_way and CHOSEN_COLOR_THIS_WAY in produced
    )
    leftover = _restrictions_beyond(
        node.filter,
        _REVEALED_HAND_FIELDS | ({"color_chosen_this_way"} if of_that_color else set()),
    )
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
    if of_that_color:
        payload["color_filter_from"] = CHOSEN_COLOR_THIS_WAY
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
    if node.filter.excluded_supertypes:
        # "…a **nonbasic** land card from it." (Encroach.) Emitted only when the
        # card prints it, so every earlier printing's payload stays
        # byte-identical — and emitted at all for the reason the two keys around
        # it are: a phrase the production consumes and the payload drops is a
        # picker offering a Plains while the card says otherwise.
        payload["exclude_supertypes"] = list(node.filter.excluded_supertypes)
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
    if node.player.kind == "that_player" and event in _DAMAGED_PLAYER_EVENTS:
        # "Whenever this creature deals combat damage to a player, look at
        # **that player's** hand and choose a card from it." (Doomsday
        # Specter.) The seat the damage froze (CR 603.10), under the word the
        # reveal above and every Specter's discard already spell it with — a
        # different fire site from the row below and so a different record,
        # which is why the two are told apart by the event rather than tried in
        # turn at resolution.
        payload["victim"] = "damaged_player"
        return (OracleInstruction("reveal_hand_and_choose", "", payload),)
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
