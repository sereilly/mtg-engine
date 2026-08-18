"""Protection a *player* has from a card **name** (CR 702.16i).

"You have protection from the chosen card name." (Runed Halo.) Its own module
because it is the one protection in the engine whose bearer is a player rather
than a permanent, and whose quality is a name rather than a colour or a type:
:mod:`engine.prevention` shields a recipient from an *amount*, and
``_protection_qualities`` answers about a permanent. Neither can be asked this.

Three consequences, and the card states all three (CR 702.16i): the player
can't be **targeted**, **dealt damage**, or **enchanted** by anything with that
name. Each is enforced where that question is already asked — the cast's target
check, the player-damage path, the Aura attach — rather than by a fourth
mechanism that would have to be remembered at each.

Derived from the controlling permanents' own text and metadata rather than
stamped on the player: the protection ends when Runed Halo leaves, and there is
nothing to clear.
"""

from __future__ import annotations

PROTECTION_FROM_NAMED_TEXT = "you have protection from the chosen card name"


def named_protection_line(line: str) -> bool:
    """Whether one printed line is the protection this module implements, in
    full.

    Read by the support gate *and* by the parse-coverage report, so what the
    engine carries out and what it claims to have read cannot drift — the same
    seam ``enter_effect_line`` is. The reminder text in parentheses is part of
    the printed line and is stripped before comparing, because every printing
    carries it and an anchored match would otherwise never fire.
    """
    text = line.strip().lower()
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text.rstrip(".") == PROTECTION_FROM_NAMED_TEXT


def names_protecting(game, player_index: int) -> frozenset[str]:
    """Every card name *player_index* currently has protection from.

    A set, because two Runed Halos name two cards and both apply. Empty is the
    ordinary case and is what every caller below treats as "no protection", so
    the question costs nothing to ask on a board without one.
    """
    protecting: set[str] = set()
    for permanent in game.controlled_by(player_index):
        text = (permanent.effective_card.oracle_text or "").lower()
        if PROTECTION_FROM_NAMED_TEXT not in text:
            continue
        named = permanent.metadata.get("chosen_card_name")
        if named:
            protecting.add(str(named))
    return frozenset(protecting)


def protected_from(game, player_index: int, source) -> bool:
    """Whether *source* is something *player_index* is protected from.

    *source* is a ``CardDefinition`` (a spell) or a ``Permanent``; both answer
    to a name, and the permanent answers with its **effective** card so a Clone
    of the named card is caught too (CR 707.2).
    """
    if source is None:
        return False
    card = getattr(source, "effective_card", None) or getattr(source, "card", source)
    name = getattr(card, "name", None)
    return bool(name) and name in names_protecting(game, player_index)


__all__ = [
    "PROTECTION_FROM_NAMED_TEXT",
    "named_protection_line",
    "names_protecting",
    "protected_from",
]
