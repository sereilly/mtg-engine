"""One target **per colour**: "For each color, return up to one target card of
that color from your graveyard to your hand." (All Suns' Dawn.)

CR 105.1 names five colours, and the sentence is one instance of the word
"target" repeated over them: up to five targets, one for each colour (the
card's 2004-12-01 rulings). "You choose the color each target must be when you
choose it as a target … You can target two blue-and-white multicolored cards by
choosing one as the blue card and one as the white card." So an announcement
is legal when its cards can be given **distinct colours, each one a colour of
its card** — a matching between the chosen cards and the five colours — and
two mono-blue cards are not a legal announcement however many other cards
there are.

The list is still an ordinary several-card graveyard target (the picker, the
CR 115.3 distinctness, the slot stamps), narrowed to coloured cards by
``graveyard_colors``; what this module adds is the one question that list
cannot ask of a card alone — whether a *set* of cards is one per colour — and
the assignment that answers it, asked by the cast gate, the AI's choice and
the resolution.

**The residual, stated.** The rulings fix each target's colour at the moment
it is chosen. The engine records no colour per target: the resolution re-asks
for a matching over the cards' colours *then* (``assign_colors``), so a card
whose colour changed while the spell was on the stack is judged by the colour
it has rather than the one it was targeted as. No card in the pool changes the
colour of a card in a graveyard at instant speed, which is why this is a
residual and not a defect anyone can reach today.
"""

from __future__ import annotations

#: The payload / spec key: the target list is one card per colour.
ONE_TARGET_PER_COLOR = "one_target_per_color"

#: CR 105.1's five colours, in the symbols every colour reader in the engine
#: speaks, in WUBRG order.
FIVE_COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")


def assign_colors(card_colors) -> "list[str | None]":
    """A colour for each entry of *card_colors* (an iterable of colour sets,
    one per chosen card), distinct across the entries, each one of that
    card's colours — as many entries answered as can be (a maximum
    matching), ``None`` for an entry left without a colour.

    Deterministic: the augmenting search walks cards in the order given and
    colours in WUBRG order, so one board always answers the same way (CR's
    "you choose" is the announcing player's; a seat that named no assignment
    takes this one).
    """
    wanted = [
        [color for color in FIVE_COLORS if color in set(colors or ())]
        for colors in card_colors
    ]
    holder: dict[str, int] = {}

    def augment(index: int, seen: set[str]) -> bool:
        for color in wanted[index]:
            if color in seen:
                continue
            seen.add(color)
            if color not in holder or augment(holder[color], seen):
                holder[color] = index
                return True
        return False

    for index in range(len(wanted)):
        augment(index, set())
    assigned: list[str | None] = [None] * len(wanted)
    for color, index in holder.items():
        assigned[index] = color
    return assigned


def one_per_color(card_colors) -> bool:
    """Whether the cards whose colours *card_colors* lists can be one per
    colour — every card given a distinct colour of its own."""
    colors = list(card_colors)
    return len(colors) <= len(FIVE_COLORS) and None not in assign_colors(colors)


def one_per_color_slots(game, seat: int, slots) -> list[int]:
    """*slots* of seat *seat*'s graveyard, best first as given, kept while the
    kept set can still be one card per colour — the announcement a chooser
    that ranked the slots (the AI's ``ranked_graveyard_slots``) makes from its
    ranking: the most valuable card of each colour it can fill, never two
    cards the gate would refuse together."""
    pile = game.players[seat]
    kept: list[int] = []
    for slot in slots:
        if not (isinstance(slot, int) and 0 <= slot < len(pile.graveyard)):
            continue
        trial = kept + [slot]
        if one_per_color(zone_cards_colors(
            game, pile, [pile.graveyard[index] for index in trial],
        )):
            kept = trial
        if len(kept) == len(FIVE_COLORS):
            break
    return kept


def zone_cards_colors(game, owner, cards) -> list[tuple[str, ...]]:
    """The colours of *cards* in *owner*'s zone, through the one reader of a
    card's colour off the battlefield (``object_colors.card_colors``, which
    asks the layers — CR 613.1: under its owner's Celestial Dawn a nonland
    card in that graveyard is white)."""
    from .object_colors import card_colors

    return [tuple(card_colors(game, card, owner)) for card in cards]
