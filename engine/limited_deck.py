"""CR 100.2b's limited deck and CR 100.4b's sideboard, dealt out of a card pool.

What each simulated seat is dealt (``ai_simulator.run_ai_simulation``): forty
cards, seventeen of them lands, singleton spells drawn from what the chosen
colours can cast, cheapest first, with the basics from the pool or, when the
set prints none, from the manifest — and beside the deck, the sideboard: the
rest of the pool the deck was built from, which is what a Wish or Ring of
Ma'rûf brings in from outside the game.

The simulator's setup rather than its play: nothing here reads a game. Split
out of ``engine/ai_simulator.py`` at the size band (round kg3).
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence
import random

from .card_loader import load_cards
from .models import CardDefinition


def _find(cards: dict[str, CardDefinition], name: str) -> CardDefinition:
    if name not in cards:
        # Named the pool "LEA data" back when the path was hardcoded; the pool
        # is now whichever set the caller chose, and a set that lacks a card
        # this decklist needs has to say which card rather than which set file.
        raise ValueError(f"the card pool has no {name!r}, which the simulator's deck needs")
    return cards[name]


# CR 100.2b's limited deck: 40 cards minimum, built from one product plus basic
# land cards. 17 lands to 23 spells is the ratio limited play settled on, and it
# is what makes the AI cast anything — a deck drawn uniformly from a set is
# mostly spells it cannot pay for.
LIMITED_DECK_SIZE = 40
LIMITED_LAND_COUNT = 17

_BASIC_LAND_TYPES = ("Plains", "Island", "Swamp", "Mountain", "Forest")

# Colour a basic land taps for, by its subtype (CR 305.6). Used to pick a mana
# base for the colours a deck actually plays, not to *define* the land — the
# card definitions come from the pool like every other card.
_BASIC_LAND_COLORS = {
    "Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G",
}

_basic_land_cache: dict[str, CardDefinition] | None = None


def _is_land(card: CardDefinition) -> bool:
    return "land" in (card.type_line or "").lower()


def _basic_land_pool(cards: dict[str, CardDefinition]) -> dict[str, CardDefinition]:
    """The five basics, preferring *cards*' own printings.

    CR 100.2b builds a limited deck from "this product **and basic land
    cards**", so basics are not part of the set being tested — which is what
    makes the rest of this work at all. Antiquities, Legends and The Dark print
    no basic land between them, and a deck of their coloured spells with their
    own lands casts nothing: the run would report no illegal interactions over
    games where nothing was ever paid for. Where the set does print them (a base
    set, 4ED) its own copies are used, so the deck is that set's cards.

    The fallback reads the manifest through ``card_loader``'s helpers rather
    than inventing five ``CardDefinition``s, because a synthesized basic is card
    data nobody ingested and it would drift from the printed one silently.
    """
    from_pool = {
        subtype: cards[subtype] for subtype in _BASIC_LAND_TYPES if subtype in cards
    }
    if len(from_pool) == len(_BASIC_LAND_TYPES):
        return from_pool

    global _basic_land_cache
    if _basic_land_cache is None:
        from .card_loader import manifest_set_paths

        found: dict[str, CardDefinition] = {}
        for path in manifest_set_paths():
            for card in load_cards(str(path)):
                if card.name in _BASIC_LAND_TYPES and card.name not in found:
                    found[card.name] = card
            if len(found) == len(_BASIC_LAND_TYPES):
                break
        _basic_land_cache = found
    return {**_basic_land_cache, **from_pool}


def _castable_colors(card: CardDefinition) -> frozenset[str]:
    """The colours a deck must produce to cast this card.

    ``color_identity`` rather than ``colors``: a card's activated abilities cost
    mana too, and a deck that can cast Prodigal Sorcerer but never untap-tap it
    is not exercising the card.
    """
    return frozenset(card.color_identity or ())


def _choose_colors(
    spells: list[CardDefinition], rng: random.Random, count: int = 2
) -> frozenset[str]:
    """Pick the deck's colours by weight of what the pool actually prints.

    Weighted rather than uniform so a set's shape decides its decks: Antiquities
    is almost entirely artifacts and lands in colourless decks that cast their
    whole pool, while a base set spreads across all five.
    """
    weights = Counter(color for spell in spells for color in _castable_colors(spell))
    if not weights:
        return frozenset()
    population = sorted(weights)
    chosen: set[str] = set()
    for _ in range(min(count, len(population))):
        remaining = [color for color in population if color not in chosen]
        picks = rng.choices(remaining, weights=[weights[c] for c in remaining], k=1)
        chosen.add(picks[0])
    return frozenset(chosen)


def build_limited_deck(
    cards: dict[str, CardDefinition],
    seed: int,
    *,
    size: int = LIMITED_DECK_SIZE,
    land_count: int = LIMITED_LAND_COUNT,
    required: Sequence[str] = (),
) -> list[CardDefinition]:
    """A random, deterministic limited deck out of *cards*.

    Singleton spells rather than playsets: the simulator exists to find bad
    interactions across a set, so 23 different cards per deck is 23 times the
    coverage of the four-of decklist this replaced — which played eight cards
    and could only be built from a base set.

    *required* names cards the deck must contain, for a regression test that
    needs its subject in play. Everything else is drawn at random from what the
    chosen colours can cast, cheapest-weighted so the AI can actually pay.
    """
    rng = random.Random(seed)

    pinned = [_find(cards, name) for name in required]
    basics = _basic_land_pool(cards)
    pool = [card for card in cards.values() if card.name not in basics]

    spells = [card for card in pool if not _is_land(card)]
    colors = _choose_colors(spells, rng) | frozenset(
        color for card in pinned for color in _castable_colors(card)
    )

    playable = [
        card for card in spells
        if _castable_colors(card) <= colors and card not in pinned
    ]
    # Cheap cards first, with a random tiebreak: a deck of six-drops is a deck
    # the AI never casts, and a run that casts nothing reports a clean sweep
    # over games that never happened.
    rng.shuffle(playable)
    playable.sort(key=lambda card: card.cmc or 0)
    spell_count = max(0, size - land_count)
    chosen_spells = (pinned + playable)[:spell_count]

    nonbasic = [
        card for card in pool
        if _is_land(card) and set(card.produced_mana or ()) & (colors | {"C"})
    ]
    rng.shuffle(nonbasic)
    deck_lands = nonbasic[: max(0, land_count // 4)]

    wanted = sorted(colors) or ["C"]
    for index in range(land_count - len(deck_lands)):
        color = wanted[index % len(wanted)]
        subtype = next(
            (name for name, c in _BASIC_LAND_COLORS.items() if c == color), "Wastes"
        )
        if subtype in basics:
            deck_lands.append(basics[subtype])
        elif basics:
            deck_lands.append(basics[sorted(basics)[index % len(basics)]])

    deck = chosen_spells + deck_lands
    rng.shuffle(deck)
    return deck


def limited_sideboard(
    cards: dict[str, CardDefinition], deck: Sequence[CardDefinition],
) -> list[CardDefinition]:
    """The sideboard of a seat dealt *deck* out of *cards* — CR 100.4b: "In
    limited play involving individual players, all cards in a player's card
    pool not included in their deck are in that player's sideboard."

    **The seat's card pool is every card of *cards* but the basic lands**,
    because that is what :func:`build_limited_deck` built the deck from: it
    looked at the whole of it (``pool`` there) and chose by colour and cost,
    so each card it passed over was one it had and did not play. The basics
    are not part of it — CR 100.2b builds a limited deck from "this product
    **and basic land cards**", the land station's and nobody's pool, which is
    why the builder sets them apart too. One copy of each, as the deck's own
    spells are singletons.

    No randomness: the leftovers of a deck are a function of the deck, so the
    deal, and every deck dealt before it, is exactly what it was before seats
    had a sideboard (the run's RNG is not touched). In the order *cards* was
    loaded in, so a seed reproduces the sideboard positions a Wish picks by.
    """
    basics = _basic_land_pool(cards)
    in_deck = {card.name for card in deck}
    return [
        card for name, card in cards.items()
        if name not in basics and name not in in_deck
    ]
