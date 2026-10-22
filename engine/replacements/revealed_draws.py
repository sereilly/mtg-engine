"""A draw replaced by a look at, or a reveal of, the library's top (CR 614.11).

The draw replacements that put cards in front of someone before — or instead
of — the draw: revealing until a card of a kind turns up (Abundance), looking
at the top cards and drawing one (Aladdin's Lamp), revealing the top card and
acting on it (Enduring Renewal), revealing the card and letting any other
player pay life to bin it (Zur's Weirding), and the drawn creature card that is
discarded unless its drawer pays life (Breathstealer's Crypt). One that waits
on an answer finishes through its registered resolver or prompt, handing back
the draws its suspension parked (``draws.py``'s queue).

Split out of ``replacements.py`` at the 2,000-line cap's split round, the half
of the draw replacements that grew with the pool.
"""

from __future__ import annotations

from ..replacement_choices import (
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
)
from ..search_filters import card_has_type
from .draws import QUEUED_EXCLUDES, draws_behind, queued_excludes
from .registry import (DRAW_LOOKING_AT_TOP, DRAW_REVEALED_AND_TAXED,
                       DRAW_REVEALED_UNLESS_PAID, DRAW_REVEALS_TOP,
                       DRAW_REVEALS_UNTIL_KIND, ReplacementOutcome,
                       replacement_effect)


#: Abundance. One printed line, two sentences, and the constant is both because
#: the interceptor performs both - the reveal-until and the two destinations the
#: second sentence names. A claim stopping at the first would admit a card that
#: reveals its library and puts nothing anywhere.
REVEAL_UNTIL_KIND_TEXT = (
    "if you would draw a card, you may instead choose land or nonland and "
    "reveal cards from the top of your library until you reveal a card of the "
    "chosen kind. put that card into your hand and put all other cards "
    "revealed this way on the bottom of your library in any order"
)


def _reveal_until_kind_sources(game, payload: dict) -> list:
    """The permanents whose replacement this draw answers to.

    "If **you** would draw a card" is CR 109.5's seat: the sentence is about the
    controller of the enchantment, so the scan is over the *drawing* player's
    own battlefield and an Abundance an opponent controls never sees this draw.

    The exclusion is CR 614.5, and it is what stops the declined branch - which
    goes back through the seam to draw the card after all - from putting the
    same question again forever. A *second* Abundance is a different effect and
    does apply, which is why it names the source rather than the wording.
    """
    exclude = set(payload.get("exclude_sources") or ())
    seat = game.players.index(payload["player"])
    return [
        perm
        for perm in game.controlled_by(seat)
        if REVEAL_UNTIL_KIND_TEXT in (perm.effective_card.oracle_text or "").lower()
        and perm.permanent_id not in exclude
    ]


def _applies_reveal_until_kind(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(
        _reveal_until_kind_sources(game, payload)
    )


@replacement_effect(
    "draw", DRAW_REVEALS_UNTIL_KIND, applies=_applies_reveal_until_kind
)
def _reveal_until_kind_instead_of_drawing(game, payload: dict) -> ReplacementOutcome | None:
    """Abundance: "If you would draw a card, you may instead choose land or
    nonland and reveal cards from the top of your library until you reveal a
    card of the chosen kind. Put that card into your hand and put all other
    cards revealed this way on the bottom of your library in any order."

    Two decisions in one sentence - whether to replace the draw at all, and
    which kind - offered as one prompt because they are one announcement
    (CR 614.1: the choice is made as the replacement applies). That is why this
    is a :class:`ReplacementChoice` rather than an interceptor that simply acts:
    ``apply_replacements`` returns synchronously and the answer arrives on a
    later request from a human.

    One draw at a time (CR 121.2), with the draws queued behind it made through
    the seam again by the resolver - so a second replacement armed alongside
    still gets its own. Declining is the third option and is carried out by the
    resolver too, as a fresh draw with this source excluded: an optional
    replacement not applied leaves the event to whatever is behind it, and the
    exclusion is what keeps this one from asking again about the draw it just
    let through.

    **The card that arrives is put into a hand, not drawn** (CR 121.1: a draw is
    the top card of a library, and this is not it), which is also why nothing
    here recurses - Abundance replaces draws and makes none.
    """
    player = payload["player"]
    count = int(payload["count"])
    source = min(
        _reveal_until_kind_sources(game, payload), key=lambda perm: perm.permanent_id
    )
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="reveal_until_kind_draw",
            player_index=game.players.index(player),
            options=("Nonland", "Land", "Draw a card"),
            # What a player would normally do with an Abundance they paid for:
            # the card is played to turn draws into spells, and the default is
            # the option that does it. Never the decline - a null default would
            # make the enchantment inert in every AI and headless game, which is
            # the one outcome that reads as "implemented" and is not.
            default_option=0,
            data={
                "remaining_draws": count - 1,
                "exclude_sources": tuple(payload.get("exclude_sources") or ()),
                QUEUED_EXCLUDES: queued_excludes(payload),
                "source_id": source.permanent_id,
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} may reveal until a land or nonland card "
            f"({source.card.name})"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("reveal_until_kind_draw")
def _resolve_reveal_until_kind_draw(
    game, choice: ReplacementChoice, option_index: int
) -> int:
    """Carry out the answer to Abundance's offer.

    The reveal stops at the **first** card of the chosen kind, and the whole run
    is one reveal event to a client (CR 701.20a). A library holding no such card
    is revealed entirely and every card goes back to the bottom: the sentence
    names a card to put into a hand and there is none, so nothing is put
    anywhere and no card is drawn.

    The rest go back **in the order they were revealed**, which is one of the
    orders "in any order" permits and the only one that is seed-reproducible.
    """
    player = game.players[choice.player_index]
    excludes = tuple(choice.data.get("exclude_sources") or ()) + (
        int(choice.data["source_id"]),
    )
    remaining = int(choice.data.get("remaining_draws", 0))
    drawn = 0
    if option_index >= 2:
        # Declined. The draw happens after all, through the seam so every other
        # armed replacement still gets its own opportunity - with this source
        # excluded, because CR 614.5 gives an effect one opportunity per event
        # and it has just had it.
        drawn += game._draw_with_replacements(player, 1, exclude_sources=excludes)
    else:
        wants_land = option_index == 1
        revealed: list = []
        found = None
        while player.library:
            card = player.library.pop(0)
            revealed.append(card)
            if card_has_type(card, "land") is wants_land:
                found = card
                break
        if revealed:
            game.record_reveal(
                choice.player_index, [card.name for card in revealed]
            )
        if found is not None:
            revealed.pop()
            # Through the hand seam, never a bare append: CR 903.9b has no
            # single fire site, and "would be put into its owner's hand from
            # anywhere" is exactly what this is.
            game.put_card_into_hand(player, found)
            game.log.append(
                f"{player.name} revealed {len(revealed) + 1} card(s) and put "
                f"{found.name} into their hand (Abundance)"
            )
        else:
            game.log.append(
                f"{player.name} revealed their whole library and found no "
                f"{'land' if wants_land else 'nonland'} card (Abundance)"
            )
        bottomed = sum(
            1 for card in revealed if game.put_card_into_library(player, card)
        )
        # "…on the bottom of your library **in any order**" is the owner's
        # order to choose (CR 401.4), asked of an interactive seat by the
        # prompt the look-and-pick family already uses. It was the one such
        # look left unasked, because on a two-card draw the order prompt sat
        # beside the next draw's offer and each refused the other; the draws
        # behind now wait for it (``Game._draw_prompt_open``), which is also
        # what keeps "the last N cards" the pile this reveal laid down.
        game.offer_library_bottom_order(player, bottomed)
    # The draws queued behind this one are their own draws (CR 121.2) and get
    # their own trip through the seam - including this replacement again,
    # which is what a two-card draw under Abundance is. A draw the decline
    # above remade and another replacement is now asking about is still in
    # front of them: the seam parks these until it is answered.
    drawn += draws_behind(
        game, player, remaining, choice.data.get(QUEUED_EXCLUDES) or ()
    )
    return drawn


def _applies_lamp_draw(game, payload: dict) -> bool:
    """Armed, not "will do something". The charge is spent even when the library
    turns out to be too short to look at anything (CR 614.1), so the short-library
    case has to be inside the effect rather than in front of it — a predicate
    that declined there would leave the charge unspent."""
    return bool(game.lamp_draw_replacements.get(game.players.index(payload["player"])))


@replacement_effect("draw", DRAW_LOOKING_AT_TOP, applies=_applies_lamp_draw)
def _look_at_top_cards_and_draw_one(game, payload: dict) -> ReplacementOutcome | None:
    """Aladdin's Lamp: the next draw is replaced by "look at the top X cards of
    your library, draw one of them, then put the rest on the bottom in a random
    order". The charge is spent even when the library is too short to look at
    anything, in which case the draw happens normally (CR 614.1)."""
    player = payload["player"]
    player_index = game.players.index(player)
    x = game.lamp_draw_replacements.pop(player_index)
    x = min(int(x), len(player.library))
    if x <= 0:
        return None
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="lamp_draw",
            player_index=player_index,
            options=tuple(card.name for card in player.library[:x]),
            default_option=0,
            data={
                "remaining_draws": payload["count"] - 1,
                QUEUED_EXCLUDES: queued_excludes(payload),
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} looks at the top {x} card(s) of their library (Aladdin's Lamp)"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("lamp_draw")
def _resolve_lamp_draw(game, choice: ReplacementChoice, option_index: int) -> int:
    player = game.players[choice.player_index]
    looked_at = min(len(choice.options), len(player.library))
    drawn = game._finish_lamp_draw(choice.player_index, option_index, looked_at)
    drawn += draws_behind(
        game, player, int(choice.data.get("remaining_draws", 0)),
        choice.data.get(QUEUED_EXCLUDES) or (),
    )
    return drawn


#: Enduring Renewal, all three printed sentences. The constant is the whole
#: line because the interceptor performs the whole line — the reveal, the
#: graveyard for a creature card and the draw for anything else. A claim
#: stopping at the first sentence would admit the card with two-thirds of it
#: doing nothing.
REVEAL_TOP_INSTEAD_OF_DRAW_TEXT = (
    "if you would draw a card, reveal the top card of your library instead. "
    "if it's a creature card, put it into your graveyard. otherwise, draw a card"
)


def _reveal_top_sources(game, payload: dict) -> list:
    """Every permanent whose text is this replacement, on the **drawing
    player's** board, that has not already had its opportunity on this event
    (CR 614.5).

    One seat's board and not every board, because the sentence says "**you**":
    an Enduring Renewal an opponent controls replaces *their* draws. Chains of
    Mephistopheles one function down scans every board for exactly the opposite
    reason — it says "a player" — which is why the scope is written per card
    rather than shared.

    The exclusion is what stops the "otherwise, draw a card" branch from
    replacing the draw it just created and looping forever. A *second* Enduring
    Renewal is a different effect and does apply, which is why it names the
    source rather than the wording.
    """
    exclude = set(payload.get("exclude_sources") or ())
    seat = game.players.index(payload["player"])
    return [
        perm
        for perm in game.controlled_by(seat)
        if REVEAL_TOP_INSTEAD_OF_DRAW_TEXT in (perm.effective_card.oracle_text or "").lower()
        and perm.permanent_id not in exclude
    ]


def _applies_reveal_top_instead_of_draw(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(
        _reveal_top_sources(game, payload)
    )


@replacement_effect(
    "draw", DRAW_REVEALS_TOP, applies=_applies_reveal_top_instead_of_draw
)
def _reveal_top_instead_of_drawing(game, payload: dict) -> ReplacementOutcome | None:
    """Enduring Renewal: "If you would draw a card, reveal the top card of your
    library instead. If it's a creature card, put it into your graveyard.
    Otherwise, draw a card."

    One draw at a time, because that is what the sentence replaces (CR 121.2
    makes an N-card draw N individual draws). The event is consumed and the
    draws queued behind it are made through the seam again, so a second
    replacement armed alongside still gets its own.

    The "otherwise" branch is a **new draw**, not a resumption of the replaced
    one, and it goes back through the seam carrying this source in
    ``exclude_sources`` — CR 614.5 gives a replacement one opportunity per
    event, so it must not replace the draw it just created and loop. A second
    Enduring Renewal is a different effect and does apply, which is why the
    exclusion names the source rather than the wording.

    An empty library reveals nothing and draws nothing: CR 704.5b fires on an
    *attempted* draw, and the attempt was replaced.
    """
    player = payload["player"]
    count = int(payload["count"])
    source = min(
        _reveal_top_sources(game, payload), key=lambda perm: perm.permanent_id
    )
    excludes = tuple(payload.get("exclude_sources") or ()) + (source.permanent_id,)
    drawn = 0
    if player.library:
        revealed = player.library[0]
        game.record_reveal(game.players.index(player), [revealed.name])
        if card_has_type(revealed, "creature"):
            player.library.pop(0)
            game.put_card_into_graveyard(player, revealed, from_zone="library")
            game.log.append(
                f"{player.name} revealed {revealed.name} and put it into their "
                f"graveyard ({source.card.name})"
            )
        else:
            game.log.append(
                f"{player.name} revealed {revealed.name} and draws it "
                f"({source.card.name})"
            )
            drawn += game._draw_with_replacements(
                player, 1, exclude_sources=excludes
            )
    else:
        game.log.append(
            f"{player.name} has no card to reveal ({source.card.name})"
        )
    # The draws queued behind this one are their own draws (CR 121.2) and get
    # their own trip through the seam — including this replacement again, which
    # is what a two-card draw under Enduring Renewal is. The seam parks them
    # while the "otherwise, draw a card" above is waiting on another
    # replacement's offer.
    drawn += draws_behind(game, player, count - 1, queued_excludes(payload))
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


#: Zur's Weirding, all four printed sentences. The constant is the whole line
#: because the interceptor performs the whole line — the reveal, the offer to
#: every other player, the graveyard behind a payment and the draw behind none.
#: A claim stopping at the first sentence would admit a card whose whole point
#: is the three behind it.
#:
#: The 2 is part of the constant rather than payload. It could be read as a
#: shape the way Forethought Amulet's cap is, but nothing would be gained: one
#: card in the pool prints this sentence, and a constant is what
#: ``replacement_claims_line`` can compare a whole line against without a second
#: reader to keep in step.
REVEAL_DRAW_UNLESS_PAID_TEXT = (
    "if a player would draw a card, they reveal it instead. then any other "
    "player may pay 2 life. if a player does, put that card into its owner's "
    "graveyard. otherwise, that player draws a card"
)

#: What the offer costs, read by the interceptor, the prompt and the payment so
#: the three cannot disagree about the number the card prints.
REVEAL_DRAW_LIFE_COST = 2


def _zurs_weirding_sources(game, payload: dict) -> list:
    """Every permanent whose text is this replacement and that has not already
    had its opportunity on this event (CR 614.5).

    The whole board, not one seat's: the sentence says "**a** player", so the
    enchantment replaces its controller's own draws as well as their opponents'
    — ``_chains_sources`` scans the same way for the same printed word, and
    ``_reveal_top_sources`` scans one seat's because Enduring Renewal says
    "you".
    """
    exclude = set(payload.get("exclude_sources") or ())
    return [
        perm
        for perm in game.all_permanents()
        if REVEAL_DRAW_UNLESS_PAID_TEXT in (perm.effective_card.oracle_text or "").lower()
        and perm.permanent_id not in exclude
    ]


def _applies_reveal_draw_unless_paid(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(
        _zurs_weirding_sources(game, payload)
    )


@replacement_effect(
    "draw", DRAW_REVEALED_UNLESS_PAID, applies=_applies_reveal_draw_unless_paid
)
def _reveal_draw_unless_paid(game, payload: dict) -> ReplacementOutcome | None:
    """Zur's Weirding: "If a player would draw a card, they reveal it instead.
    Then any other player may pay 2 life. If a player does, put that card into
    its owner's graveyard. Otherwise, that player draws a card."

    One draw at a time, because that is what the sentence replaces (CR 121.2
    makes an N-card draw N individual draws); the draws queued behind it ride
    the prompt and are made through the seam again when it is answered.

    The offer is put to **every other player in turn order** (CR 101.4) and the
    first to pay ends the round — so it is the ordinary pending-choice queue
    with the rest of the poll carried in the prompt's own data, the arrangement
    Chains of Mephistopheles uses one order over: arm the prompt, hang the draw
    on it. An interactive seat answers it; every other seat takes the stated
    default where the offer stands, so headless and AI play never block.

    The card is **not** moved here. It is revealed and left on top: until
    somebody pays, it is still the card the drawing player is about to draw, and
    CR 121.1's draw is what puts it in a hand. Moving it early would make a
    declined offer a draw of the *second* card down.

    An empty library reveals nothing and draws nothing: CR 704.5b fires on an
    *attempted* draw, and the attempt was replaced.
    """
    player = payload["player"]
    seat = game.players.index(player)
    count = int(payload["count"])
    source = min(
        _zurs_weirding_sources(game, payload), key=lambda perm: perm.permanent_id
    )
    excludes = tuple(payload.get("exclude_sources") or ()) + (source.permanent_id,)
    drawn = 0
    if not player.library:
        game.log.append(
            f"{player.name} has no card to reveal ({source.card.name})"
        )
        if count > 1:
            drawn += game._draw_with_replacements(
                player, count - 1,
                exclude_sources=tuple(payload.get("exclude_sources") or ()),
            )
        payload["drawn"] = drawn
        return ReplacementOutcome(replaced=True)
    revealed = player.library[0]
    game.record_reveal(seat, [revealed.name])
    game.log.append(
        f"{player.name} reveals {revealed.name} instead of drawing "
        f"({source.card.name})"
    )
    game.offer_revealed_draw_buyout(
        seat,
        card_name=revealed.name,
        source_name=source.card.name,
        queued_draws=max(0, count - 1),
        exclude_sources=excludes,
        queued_exclude_sources=tuple(payload.get("exclude_sources") or ()),
    )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


#: Breathstealer's Crypt, both printed sentences. The constant is the whole line
#: because the interceptor performs the whole line — the draw, the reveal, and
#: the offer behind a creature card. A claim stopping at the first sentence
#: would admit a card whose entire effect is the second.
REVEALED_DRAW_TAXED_TEXT = (
    "if a player would draw a card, instead they draw a card and reveal it. "
    "if it's a creature card, that player discards it unless they pay 3 life"
)

#: What the offer costs, read by the interceptor and the prompt so the two
#: cannot disagree about the number the card prints.
REVEALED_DRAW_TAX_LIFE = 3


def _revealed_draw_tax_sources(game, payload: dict) -> list:
    """Every permanent whose text is this replacement and that has not already
    had its opportunity on this event (CR 614.5).

    The whole board, not one seat's: the sentence says "**a** player", so the
    enchantment taxes its controller's own draws as well as their opponents' —
    the same scope ``_chains_sources`` and ``_zurs_weirding_sources`` take for
    the same printed word, against ``_reveal_top_sources``' one seat for "you".
    """
    exclude = set(payload.get("exclude_sources") or ())
    return [
        perm
        for perm in game.all_permanents()
        if REVEALED_DRAW_TAXED_TEXT in (perm.effective_card.oracle_text or "").lower()
        and perm.permanent_id not in exclude
    ]


def _applies_revealed_draw_tax(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(
        _revealed_draw_tax_sources(game, payload)
    )


@replacement_effect(
    "draw", DRAW_REVEALED_AND_TAXED, applies=_applies_revealed_draw_tax
)
def _revealed_draw_taxed(game, payload: dict) -> ReplacementOutcome | None:
    """Breathstealer's Crypt: "If a player would draw a card, instead they draw
    a card and reveal it. If it's a creature card, that player discards it
    unless they pay 3 life."

    The one draw replacement in this package that **does not take the draw away**.
    CR 614.1 replaces the event with a modified one, and the modification here
    is a reveal and a rider — so the card really is drawn, and the offer is put
    about a card that is already in its owner's hand.

    The draw goes back through ``_draw_with_replacements`` rather than
    ``player.draw``: that is the seam every armed replacement is asked at, and
    reaching past it is what skips a second one. It carries this source in
    ``exclude_sources`` so the draw it just created is not replaced by the same
    enchantment again (CR 614.5) — a loop, not a tax. A *second* Crypt is a
    different effect and does apply, which is why the exclusion names the
    source rather than the wording.

    One draw at a time, because that is what the sentence replaces (CR 121.2
    makes an N-card draw N individual draws); the draws queued behind it are
    made through the seam again and each gets its own reveal.

    The card is identified **by the hand growing**, not by reading the top of
    the library before the draw: a replacement armed underneath this one may
    have changed which card arrives, and the sentence reveals the card that was
    drawn rather than the one that was going to be.
    """
    player = payload["player"]
    seat = game.players.index(player)
    count = int(payload["count"])
    source = min(
        _revealed_draw_tax_sources(game, payload), key=lambda perm: perm.permanent_id
    )
    excludes = tuple(payload.get("exclude_sources") or ()) + (source.permanent_id,)
    queued = max(0, count - 1)
    queued_excludes = tuple(payload.get("exclude_sources") or ())
    before = len(player.hand)
    drawn = game._draw_with_replacements(player, 1, exclude_sources=excludes)
    revealed = player.hand[-1] if len(player.hand) > before else None
    if revealed is not None:
        game.record_reveal(seat, [revealed.name])
        game.log.append(
            f"{player.name} drew and revealed {revealed.name} ({source.card.name})"
        )
    if revealed is not None and card_has_type(revealed, "creature"):
        # The offer is the second sentence, and it is put to the drawing player
        # rather than performed: "unless they pay" is a decision, so it goes on
        # the standing queue like every other one.
        #
        # **The draws queued behind this one ride the prompt**, the arrangement
        # Zur's Weirding uses one interceptor over: an interactive seat answers
        # on a later request, so a loop here would make the rest of a two-card
        # draw happen while the offer was still open — and CR 608.2 says nothing
        # of the resolution may run until it is answered. The resolver makes
        # them once the answer is in. A non-interactive seat answers at once
        # (``default_at_arm``), so headless and AI play still finish the draw
        # here, in order.
        game.arm_discard_unless_pay_life(
            seat,
            card=revealed,
            life=REVEALED_DRAW_TAX_LIFE,
            source_name=source.card.name,
            queued_draws=queued,
            queued_exclude_sources=queued_excludes,
            # CR 109.5: the discard is this permanent's ability's doing, so
            # its controller is who "causes" it — an opponent's Crypt puts a
            # Dodecapod onto the battlefield and your own does not.
            cause_seat=game.controller_index_of(source),
        )
        payload["drawn"] = drawn
        return ReplacementOutcome(replaced=True)
    # No offer to make, so the draws queued behind this one happen here. They
    # are their own events (CR 121.2) and get their own trip through the seam —
    # including this replacement again, which is what a two-card draw under a
    # Crypt is.
    if queued:
        drawn += game._draw_with_replacements(
            player, queued, exclude_sources=queued_excludes,
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)
