"""Whether an AI seat keeps its opening hand, and which cards a London
mulligan puts on the bottom (CR 103.5).

**No AI seat ever mulliganed.** The simulator called ``keep_hand`` for each
seat and the web table kept every AI seat's hand as it was dealt, so a
one-land seven was played out — Onslaught's second smoke game ended on turn
16 with the AI still on one land. This is the decision both now ask, and the
one place it is made: ``ai_simulator.run_ai_simulation`` through
:func:`take_opening_mulligans`, and ``web/pregame.py`` through
:func:`keeps_opening_hand` and :func:`opening_hand_bottom` (and
:func:`take_opening_mulligans` for a table dealt with no pregame).

**What it reads.** The seat's own hand, how many cards it still owes the
bottom (``Game.mulligan_effective_count``: CR 103.5c's free first mulligan in
a multiplayer or Brawl game is already discounted there), and the share of
its deck that is land — a composition the seat knows from its decklist, read
as a count over its hand and library, never their order (CR 400.2). Nothing
about another seat.

**The choice is made over the last seven drawn.** CR 103.5 has a player draw
seven and put N on the bottom as the mulligan is taken; the web table lets a
person choose the N as they keep, which is the same choice out of the same
seven cards. Both call sites ask in that one shape — the hand as drawn and the
count owed — so a hand is judged as it will be kept: :func:`keeps` evaluates
the hand left after :func:`bottom_choice`, and the cards that go are the ones
:func:`bottom_choice` names when the hand is kept.

**The rule: lands against the curve.** A kept hand of *k* cards holds between
``KEEP_WINDOW[k]`` lands (fewest, most) — 2 to 5 of seven, 2 to 4 of six, 1
to 4 of five — and a hand of ``ALWAYS_KEEP_AT`` cards or fewer is kept, since
a fourth mulligan costs more than any hand it could fix. A hand at the
window's floor of two lands must also hold a play those two lands can begin:
a spell (any face of it, or a morph's face-down {3}) of mana value at most
three whose coloured symbols the lands make. The window scales with the deck:
its floor is never above ``floor(k * share)`` and its ceiling never below
``ceil(k * share) + 1``, so a deck with no lands keeps every hand and a deck
that is two-thirds land is not mulliganed for holding them. Each number is
the census's, below, and a reason:

* **Seven: 2 to 5.** The simulator's 40-card, 17-land decks (CR 100.2b) deal
  0 lands 1.2% of the time, 1 land 9.3%, 6 lands 1.4% and 7 lands 0.1% (4,000
  opening sevens: ten shipped sets, 200 seeds, both seats; ``kg2`` round,
  ``scratch/kg2/mulligan/census_deal.py``). A one-lander needs two of its next
  few draws to be lands to cast a two-drop on time; a six-lander is one spell.
* **Six: 2 to 4.** After the bottom choice — which puts excess lands on the
  bottom first — a seven drawn after one mulligan is kept unless it holds 0–1
  or 6–7 lands.
* **Five: 1 to 4.** Going to four is worse than a one-land or four-land five.

What that did to the same 4,000 sevens: 490 seats mulligan (12.3% — every
0–1 and 6–7-land seven, and 8 of 1,012 two-landers with no play), 84 of them
twice, none three times. Seats with at most one land among the cards they
can reach by their own sixth turn go from 7 to 0, at most two from 83 to 28.
Played out (the seven stuck deals and five one-landers that reached two
lands, ``census_targeted.py``), the seats on one land at their sixth turn go
from 6 of 12 to 1 — that one mulliganed into three lands and sacrificed two of
them to its own City in a Bottle.

**The bottom: the lands down to the deck's share, then the dearest spells.**
Of the N cards, as many are lands as bring the kept lands down to
``ceil(k * share)`` (three of six, three of five for a 17/40 deck — screw
loses more games than flood in a short hand), never a land while the hand is
short of that, and never fewer lands than the spells it holds force. The
land that goes is the one whose loss costs the fewest colours the hand's
spells ask for; the spells that go are the dearest — mana value, plus two
for a spell the kept lands cannot colour. Ties go to the card later in the
hand, so the choice is a function of the hand.

The decision consumes no randomness; the shuffles a mulligan makes are the
engine's (``Game.pregame_mulligan_draw``), from the module RNG a seeded run
seeds.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Iterable, Sequence

from .face_down import morph_cost
from .faces import castable_faces
from .search_filters import card_has_type

if TYPE_CHECKING:  # pragma: no cover
    from .game import Game
    from .models import CardDefinition


#: The fewest and the most lands a kept hand of each size holds, for a deck
#: whose land share is a limited deck's 17/40 (the window scales with the
#: deck — :func:`keep_window`). Sizes above seven read the seven row.
KEEP_WINDOW: dict[int, tuple[int, int]] = {7: (2, 5), 6: (2, 4), 5: (1, 4)}

#: A kept hand this size or smaller is kept whatever it holds.
ALWAYS_KEEP_AT = 4

#: A hand at the window's floor of lands (two or more) needs a spell of this
#: mana value or less, beyond its lands, that those lands can colour.
EARLY_PLAY_REACH = 1

_SYMBOL = re.compile(r"\{([^}]+)\}")
_COLORS = frozenset("WUBRG")


# -- what a card is, to a hand ------------------------------------------------


def _is_land(card) -> bool:
    return card_has_type(card, "land")


def _land_colors(card) -> frozenset[str]:
    """The colours a land **card** makes. The printed summary
    (``produced_mana``): a card in hand is not a permanent, so the engine's
    per-ability answer for one cannot be asked — the reason
    ``ai_policy._land_drop_value`` reads the same field."""
    return frozenset(str(symbol).upper() for symbol in (card.produced_mana or ()))


def _color_needs(face) -> tuple[frozenset[str], ...]:
    """One entry per coloured symbol of *face*'s mana cost, each the set of
    colours that would pay it: ``{G}`` is ``{"G"}``, a hybrid ``{W/U}`` is
    either. A symbol that something other than a colour can pay — generic,
    ``{X}``, a ``{2/W}``, a Phyrexian ``{W/P}`` — needs no colour."""
    needs = []
    for symbol in _SYMBOL.findall(face.mana_cost or ""):
        parts = symbol.upper().split("/")
        if any(not part or part not in _COLORS and part != "C" for part in parts):
            continue
        needs.append(frozenset(parts))
    return tuple(needs)


def _colored_by(face, colors: frozenset[str]) -> bool:
    return all(need & colors for need in _color_needs(face))


def _wanted_colors(spells: Iterable) -> frozenset[str]:
    return frozenset(
        color
        for spell in spells
        for face in castable_faces(spell)
        for need in _color_needs(face)
        for color in need
    )


def _cheapest_play(card, colors: frozenset[str]) -> float | None:
    """The least mana value *card* can be cast for with *colors* to pay its
    coloured symbols — any face (CR 709.3), or face down for {3} (a morph,
    CR 702.37c) — or None if the colours cast no face of it."""
    costs = [
        float(face.cmc or 0) for face in castable_faces(card) if _colored_by(face, colors)
    ]
    if morph_cost(card) is not None:
        costs.append(3.0)
    return min(costs) if costs else None


def _keep_price(card, colors: frozenset[str]) -> float:
    """How dear a spell is to keep: its mana value, plus two when the kept
    lands cannot colour any face of it. The bottom choice sends the dearest."""
    play = _cheapest_play(card, colors)
    if play is not None:
        return play
    return min(float(face.cmc or 0) for face in castable_faces(card)) + 2.0


# -- the window -----------------------------------------------------------------


def keep_window(kept_size: int, land_share: float) -> tuple[int, int]:
    """The fewest and most lands a kept hand of *kept_size* cards may hold,
    for a deck that is *land_share* land (see the module docstring)."""
    floor_, ceiling = KEEP_WINDOW.get(min(kept_size, 7), (0, kept_size))
    expected = kept_size * max(0.0, land_share)
    floor_ = min(floor_, math.floor(expected))
    ceiling = min(kept_size, max(ceiling, math.ceil(expected) + 1))
    return floor_, ceiling


def _land_target(kept_size: int, land_share: float) -> int:
    floor_, ceiling = keep_window(kept_size, land_share)
    return min(max(math.ceil(kept_size * max(0.0, land_share)), floor_), ceiling)


# -- the two answers over a hand --------------------------------------------------


def bottom_choice(
    hand: Sequence["CardDefinition"], count: int, *, land_share: float
) -> list[int]:
    """Indices into *hand* of the *count* cards a London mulligan puts on the
    bottom (CR 103.5), in the order they go."""
    count = max(0, min(count, len(hand)))
    if count == 0:
        return []
    kept_size = len(hand) - count
    lands = [index for index, card in enumerate(hand) if _is_land(card)]
    spells = [index for index, card in enumerate(hand) if not _is_land(card)]
    lands_out = len(lands) - _land_target(kept_size, land_share)
    lands_out = max(count - len(spells), min(count, len(lands), max(0, lands_out)))

    wanted = _wanted_colors(hand[index] for index in spells)
    kept_lands = list(lands)
    chosen: list[int] = []
    for _ in range(lands_out):
        covered = frozenset().union(*(_land_colors(hand[i]) for i in kept_lands)) & wanted

        def cost_of_losing(index: int) -> tuple[int, int, int]:
            rest = frozenset().union(
                *(_land_colors(hand[i]) for i in kept_lands if i != index)
            )
            lost = len(covered - rest)
            return (lost, len(_land_colors(hand[index]) & wanted), -index)

        going = min(kept_lands, key=cost_of_losing)
        kept_lands.remove(going)
        chosen.append(going)

    colors = frozenset().union(*(_land_colors(hand[i]) for i in kept_lands))
    spells_by_price = sorted(
        spells, key=lambda index: (-_keep_price(hand[index], colors), -index)
    )
    chosen.extend(spells_by_price[: count - lands_out])
    return chosen


def keeps(
    hand: Sequence["CardDefinition"], to_bottom: int, *, land_share: float
) -> bool:
    """Whether a seat keeps *hand* (the cards drawn), owing *to_bottom* of
    them to the bottom of its library."""
    going = set(bottom_choice(hand, to_bottom, land_share=land_share))
    kept = [card for index, card in enumerate(hand) if index not in going]
    if len(kept) <= ALWAYS_KEEP_AT:
        return True
    lands = [card for card in kept if _is_land(card)]
    floor_, ceiling = keep_window(len(kept), land_share)
    if not floor_ <= len(lands) <= ceiling:
        return False
    if len(lands) == floor_ and floor_ >= 2:
        colors = frozenset().union(*(_land_colors(card) for card in lands))
        reach = len(lands) + EARLY_PLAY_REACH
        return any(
            (play := _cheapest_play(card, colors)) is not None and play <= reach
            for card in kept
            if not _is_land(card)
        )
    return True


# -- asked of a game ------------------------------------------------------------


def deck_land_share(game: "Game", seat: int) -> float:
    """The share of *seat*'s deck that is land, counted over its hand and
    library — the composition its decklist tells it, not the order."""
    player = game.players[seat]
    cards = list(player.hand) + list(player.library)
    if not cards:
        return 0.0
    return sum(1 for card in cards if _is_land(card)) / len(cards)


def keeps_opening_hand(game: "Game", seat: int) -> bool:
    """Whether the AI at *seat* keeps the hand it holds — the last seven it
    drew — owing the bottom what its mulligans so far owe."""
    if game.mulligan_effective_count(seat) >= 7:
        return True  # CR 103.5: no mulligan past a hand of zero cards
    return keeps(
        game.players[seat].hand,
        game.mulligan_bottom_owed(seat),
        land_share=deck_land_share(game, seat),
    )


def exchanges_opening_hand(game: "Game", seat: int) -> bool:
    """Whether the AI at *seat* takes an exchange "any time you could
    mulligan" (CR 103.5b, Serum Powder) — exile the hand, draw that many —
    before it declares.

    For a hand it would not keep, and always in preference to the mulligan:
    the exchange is the same fresh look at the library without the card a
    mulligan costs, and the seat then declares again with the new hand
    (another Powder in it may exchange again). A hand it keeps is kept. The
    bottom the exchange owes first is chosen as a keep chooses it
    (:func:`exchange_bottom`), and it never bottoms the card that grants
    the exchange.
    """
    from .mulligan_exchanges import exchange_sources

    if not exchange_sources(game, seat) or keeps_opening_hand(game, seat):
        return False
    return exchange_bottom(game, seat) is not None


def exchange_bottom(game: "Game", seat: int) -> "list[int] | None":
    """The cards *seat* bottoms as it exchanges — what it owes, chosen as a
    keep chooses them (:func:`bottom_choice`) out of the hand less one card
    that grants the exchange, which stays to make it — or None when the hand
    cannot pay the bottom and keep that card."""
    from .mulligan_exchanges import exchange_sources

    sources = exchange_sources(game, seat)
    if not sources:
        return None
    owed = game.mulligan_bottom_owed(seat)
    hand = game.players[seat].hand
    others = [index for index in range(len(hand)) if index != sources[0]]
    if len(others) < owed:
        return None
    picked = bottom_choice(
        [hand[index] for index in others], owed, land_share=deck_land_share(game, seat)
    )
    return [others[index] for index in picked]


def take_hand_exchanges(game: "Game", seat: int) -> int:
    """Every exchange the AI at *seat* takes before declaring (CR 103.5b),
    as many as its hands keep asking for; returns how many."""
    taken = 0
    while exchanges_opening_hand(game, seat):
        if not game.pregame_hand_exchange(seat, exchange_bottom(game, seat) or ()):
            break
        taken += 1
    return taken


def opening_hand_bottom(game: "Game", seat: int, count: int | None = None) -> list[int]:
    """Indices into *seat*'s hand of the cards it puts on the bottom as it
    keeps: *count* of them, by default what its mulligans owe."""
    if count is None:
        count = game.mulligan_bottom_owed(seat)
    return bottom_choice(
        game.players[seat].hand, count, land_share=deck_land_share(game, seat)
    )


def take_opening_mulligans(
    game: "Game", starting_player: int, *, deciding: Iterable[int] | None = None
) -> int:
    """CR 103.5's mulligan rounds, once every opening hand is dealt: the seats
    in *deciding* (default every seat) ask :func:`keeps_opening_hand`, the
    rest keep what they were dealt. Returns how many mulligans were taken.

    "First, the starting player declares whether they will take a mulligan.
    Then each other player in turn order does the same. Once each player has
    made a declaration, all players who decided to take mulligans do so at
    the same time … This process is then repeated until no player takes a
    mulligan." A seat that keeps puts what it owes on the bottom as it keeps
    (``Game.keep_opening_hand``).
    """
    seats = len(game.players)
    deciders = set(range(seats) if deciding is None else deciding)
    undecided = [(starting_player + offset) % seats for offset in range(seats)]
    taken = 0
    while undecided:
        mulliganing = []
        for seat in undecided:
            if seat in deciders:
                # CR 103.5b: an exchange "any time you could mulligan" is
                # made before the declaration it precedes.
                take_hand_exchanges(game, seat)
            if seat in deciders and not keeps_opening_hand(game, seat):
                mulliganing.append(seat)
            else:
                game.keep_opening_hand(seat, opening_hand_bottom(game, seat))
        undecided = []
        for seat in mulliganing:
            if game.pregame_mulligan_draw(seat):
                taken += 1
                undecided.append(seat)
            else:
                game.keep_opening_hand(seat, opening_hand_bottom(game, seat))
    return taken
