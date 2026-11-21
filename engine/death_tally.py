"""The turn's death tally: how many creatures died this turn, and of what type.

"…for each creature that died this turn" (Canopy Stalker), "…for each
nontoken creature that died this turn" (Gadrak), "…for each **Zubera** that
died this turn" (the five Zubera). One question asked of the game's own record,
because the creatures counted are exactly the ones no zone still holds — a
token died and ceased to exist (CR 111.7), a card may have left its graveyard
since — so no scan of any pile can answer it.

The record is written at the one seam every creature death passes through
(``mixins/deaths.py``), asked live as the creature dies, which is last-known
information (CR 603.10a): a Mistform that became a Zubera dies a Zubera. It is
kept on ``Game`` (``creatures_died_this_turn``, its nontoken twin, and
``creature_types_died_this_turn`` by creature type) and reset each turn in
``begin_turn_bookkeeping``.

What a spec may ask is decided at lowering (``grammar/lowering/_amounts.
died_this_turn_count_spec``): a history name, and at most one creature type.
:func:`died_this_turn_count` is the one reader every handler spending such a
count goes through — the token count, the life gain's multiplier and the
shared count evaluator — so the three cannot come to disagree about what a
narrowed tally means.
"""

from __future__ import annotations

#: The game-wide tallies a ``{"history": ...}`` spec names, and the ``Game``
#: field each one reads. A name outside this table counts nothing.
GAME_DEATH_TALLIES: dict[str, str] = {
    "creatures_died_this_turn": "creatures_died_this_turn",
    "nontoken_creatures_died_this_turn": "nontoken_creatures_died_this_turn",
}

#: The spec key narrowing a game-wide tally to one creature type.
CREATURE_TYPE_KEY = "creature_type"


def record_creature_death(game, creature_types) -> None:
    """Count one creature death against each creature type it had as it died."""
    tally = getattr(game, "creature_types_died_this_turn", None)
    if not isinstance(tally, dict):
        tally = {}
        game.creature_types_died_this_turn = tally
    for creature_type in sorted({str(word).lower() for word in creature_types}):
        tally[creature_type] = int(tally.get(creature_type, 0)) + 1


def is_game_death_tally(spec) -> bool:
    """Whether *spec* is a ``{"history": …}`` count of this table's."""
    return isinstance(spec, dict) and spec.get("history") in GAME_DEATH_TALLIES


def died_this_turn_count(game, spec: dict) -> int:
    """How many creatures died this turn, as *spec* asks it.

    ``{"history": "creatures_died_this_turn"}`` is every creature death;
    ``…"nontoken_creatures_died_this_turn"`` the ones that were cards; and a
    ``creature_type`` beside the first narrows it to that type's deaths. A
    spec this table does not know counts nothing, never a wider number.
    """
    if not is_game_death_tally(spec):
        return 0
    creature_type = spec.get(CREATURE_TYPE_KEY)
    if creature_type is not None:
        if spec["history"] != "creatures_died_this_turn":
            return 0
        tally = getattr(game, "creature_types_died_this_turn", None) or {}
        return max(0, int(tally.get(str(creature_type).lower(), 0) or 0))
    return max(0, int(getattr(game, GAME_DEATH_TALLIES[spec["history"]], 0) or 0))


__all__ = [
    "CREATURE_TYPE_KEY",
    "GAME_DEATH_TALLIES",
    "died_this_turn_count",
    "is_game_death_tally",
    "record_creature_death",
]
