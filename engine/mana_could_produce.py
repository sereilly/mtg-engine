"""What mana a board "could produce" (CR 106.7).

Three printed cards ask this question of a *set* of permanents rather than of
one named object:

* "Add one mana of any **type that a land you control** could produce."
  (Reflecting Pool.)
* "Add one mana of any **color that a land an opponent controls** could
  produce." (Fellwar Stone, Exotic Orchard's mirror.)
* — and any later card printing either phrase about another board.

The naive reading is a union of ``Permanent.effective_produced_mana`` over the
lands, and it is wrong in the direction that makes the card strictly better than
the one printed. Scryfall records Reflecting Pool's own ``produced_mana`` as all
five colours, so a lone Reflecting Pool would tap for anything. CR 106.7 says
the opposite: a permanent's "could produce" set is what an ability of *that*
permanent would produce if it resolved now, and "if that permanent wouldn't
produce any mana under these conditions, or no type of mana can be defined this
way, there's no type of mana it could produce." The rule's own example is this
family:

    Exotic Orchard has the ability "{T}: Add one mana of any color that a land
    an opponent controls could produce." If your opponent controls no lands,
    activating Exotic Orchard's mana ability will produce no mana. The same is
    true if you and your opponent each control no lands other than Exotic
    Orchards. However, if you control a Forest and an Exotic Orchard, and your
    opponent controls an Exotic Orchard, then each Exotic Orchard could produce
    {G}.

So the answer is a **fixpoint**, not a scan: a derived land contributes whatever
the board it reads contributes, and two derived lands reading each other
contribute nothing. :func:`could_produce_by_seat` computes it once for every
seat, and both printed phrases read it — one reader, so the two cards cannot
disagree about a board they can both see.

The phrase is matched here as well as in ``engine/grammar/effects/mana.py``,
and the two readers answer different questions of it: that one asks *what this
ability does* and this one asks *what this land could make*, which is a question
about a permanent somebody else's ability is looking at. The same split
``cast_permissions.self_permission_zone`` and ``cast_costs`` already keep over
one sentence.
"""

from __future__ import annotations

import re

#: The boards a "could produce" phrase can name, as ``phrase -> board``.
#: Anchored on the words that pick the board out, not on the whole sentence: a
#: card printing the phrase inside a longer ability is still a land whose own
#: production is derived, which is the only thing this module asks.
_DERIVED_BOARDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"that a land you control could produce"),
        "controlled_lands",
    ),
    (
        re.compile(r"that a land an opponent controls could produce"),
        "opponent_lands",
    ),
)

#: CR 106.1b's six types: the five colours and colourless. "Colour" is the
#: subset a phrase printing the word *color* names, and the difference is the
#: whole reason Reflecting Pool and Fellwar Stone cannot share a branch — a land
#: tapping for {C} answers the first and not the second.
COLORS = frozenset("WUBRG")


def derived_producer_board(card) -> str | None:
    """Which board *card*'s own mana production is derived from, or None.

    None is the ordinary land, whose ``produced_mana`` says what it makes.
    """
    text = (getattr(card, "oracle_text", "") or "").lower()
    if "could produce" not in text:
        return None
    for pattern, board in _DERIVED_BOARDS:
        if pattern.search(text):
            return board
    return None


def could_produce_by_seat(game) -> dict[int, frozenset[str]]:
    """CR 106.7's answer for every seat: the mana types the lands that seat
    controls could produce, as upper-case symbols.

    Through the control seam, because "controls" is a seat question (CR 109.5)
    and ``player.battlefield`` is only a projection of it — and through
    ``has_type``, so an animated land still counts and a permanent that stopped
    being one does not (CR 613 layer 4).

    The loop is the fixpoint the rule's example describes. A derived land
    contributes the set of the board it *reads*; recomputing until nothing
    changes is what makes "you control a Forest and an Orchard, your opponent
    controls an Orchard" come out at {G} for both Orchards, and what makes two
    Orchards facing each other with no other land come out empty. It terminates
    because the sets only grow and there are six types.
    """
    seats = range(len(game.players))
    direct: dict[int, set[str]] = {}
    derived: dict[int, list[str]] = {}
    for seat in seats:
        direct[seat] = set()
        derived[seat] = []
        for perm in game.controlled_by(seat):
            if not perm.has_type("land"):
                continue
            board = derived_producer_board(perm.effective_card)
            if board is None:
                direct[seat] |= {
                    str(symbol).upper() for symbol in perm.effective_produced_mana
                }
            else:
                derived[seat].append(board)

    answer = {seat: set(direct[seat]) for seat in seats}
    # At most one round per seat plus one to observe stability: each round
    # propagates one link of the "reads" chain, and no chain is longer than the
    # number of seats.
    for _ in range(len(game.players) + 1):
        changed = False
        for seat in seats:
            for board in derived[seat]:
                if board == "controlled_lands":
                    # A Reflecting Pool reading its own controller's lands
                    # offers exactly what that board already offers, so it adds
                    # nothing — which is the rule's "no type of mana can be
                    # defined this way" for a board with nothing else on it.
                    contributed = answer[seat]
                else:
                    contributed = set().union(
                        *(answer[other] for other in game.opponents_of(seat)),
                        set(),
                    )
                if not contributed <= answer[seat]:
                    answer[seat] |= contributed
                    changed = True
        if not changed:
            break
    return {seat: frozenset(types) for seat, types in answer.items()}


def types_a_land_you_control_could_produce(game, seat: int) -> frozenset[str]:
    """"…any type that a land you control could produce." (Reflecting Pool.)"""
    return could_produce_by_seat(game).get(seat, frozenset())


def colors_a_land_an_opponent_controls_could_produce(
    game, seat: int
) -> frozenset[str]:
    """"…any color that a land an opponent controls could produce." (Fellwar
    Stone.)

    The same fixpoint narrowed to CR 106.1b's five colours, because the printed
    word is *color*: an opponent whose only land taps for {C} offers this card
    nothing.
    """
    by_seat = could_produce_by_seat(game)
    types: set[str] = set()
    for opponent in game.opponents_of(seat):
        types |= by_seat.get(opponent, frozenset())
    return frozenset(types & COLORS)


__all__ = [
    "COLORS",
    "colors_a_land_an_opponent_controls_could_produce",
    "could_produce_by_seat",
    "derived_producer_board",
    "types_a_land_you_control_could_produce",
]
