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

**Each target's colour is fixed as it is chosen** (the ruling: "if the card
you targeted as a blue card is red when All Suns' Dawn resolves, the card is
an illegal target, even if the spell doesn't target another red card").
:func:`record_per_color_assignment` writes the colour each stamped card was
given onto the stack object (:data:`PER_COLOR_ASSIGNMENT`) as the targets are
stamped, and the resolution keeps a card only while it still has that colour.
The pool reaches this: Celestial Dawn makes its owner's graveyard white, so a
Disenchant or a Sleight of Mind on it in response recolours a card the spell
targeted (until Fifth Dawn's wave 2 the resolution re-matched over the colours
*then*, and returned it).

The residual left: the assignment is the deterministic matching
(:func:`assign_colors`, WUBRG order) — nobody is asked *which* colour a
multicoloured card is targeted as, so a lone blue-and-white card is the white
one. That differs from a person's answer only when the card later loses
exactly the colour the matching picked.
"""

from __future__ import annotations

#: The payload / spec key: the target list is one card per colour.
ONE_TARGET_PER_COLOR = "one_target_per_color"

#: The ``StackItem.choices`` key holding the colour each stamped graveyard
#: target was chosen as, one entry per stamp in stamp order (``None`` for a
#: card the matching could not give a colour) — declared in
#: ``game_types.CHOICE_KEYS``.
PER_COLOR_ASSIGNMENT = "per_color_assignment"

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


def record_per_color_assignment(game, item) -> None:
    """Write the colour each of *item*'s stamped graveyard targets is chosen
    as (:data:`PER_COLOR_ASSIGNMENT`), read off the cards' colours **now** —
    the moment CR 601.2c chooses them. Called where the stamps are made
    (``Game._stamp_stack_targets``), for a spec that is one card per colour.
    """
    stamps = list(getattr(item, "target_graveyard_card", None) or ())
    if not stamps:
        return
    colors = [
        tuple(zone_cards_colors(game, game.players[stamp.seat], [stamp.card])[0])
        if 0 <= stamp.seat < len(game.players) else ()
        for stamp in stamps
    ]
    item.choices[PER_COLOR_ASSIGNMENT] = tuple(assign_colors(colors))


def kept_as_assigned(game, owner, named, assignment) -> list:
    """The cards of *named* (one per stamp, ``None`` for a stamp whose card
    is gone) that still have the colour *assignment* recorded for them — CR
    608.2b's legal targets of a one-card-per-colour list."""
    kept = []
    for card, color in zip(named, assignment):
        if card is None or color is None:
            continue
        if color in zone_cards_colors(game, owner, [card])[0]:
            kept.append(card)
    return kept


def holds_assigned_color(game, stamp, color) -> bool:
    """Whether the graveyard card *stamp* names still has *color*, the colour
    it was targeted as — CR 608.2b's question of one target of the list."""
    if color is None or not 0 <= stamp.seat < len(game.players):
        return False
    return color in zone_cards_colors(game, game.players[stamp.seat], [stamp.card])[0]


def zone_cards_colors(game, owner, cards) -> list[tuple[str, ...]]:
    """The colours of *cards* in *owner*'s zone, through the one reader of a
    card's colour off the battlefield (``object_colors.card_colors``, which
    asks the layers — CR 613.1: under its owner's Celestial Dawn a nonland
    card in that graveyard is white)."""
    from .object_colors import card_colors

    return [tuple(card_colors(game, card, owner)) for card in cards]
