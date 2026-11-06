"""Mana pools that do not empty as steps and phases end (CR 500.5, CR 106.4).

    "Players don't lose unspent mana as steps and phases end." (Upwelling.)

CR 500.5: "As a step or phase ends, … any unspent mana left in a player's mana
pool empties. This is a turn-based action that doesn't use the stack." This
sentence is a static ability that switches that turn-based action off while its
permanent is on the battlefield — not a CR 614 replacement (it says no
"instead" and replaces no event: the emptying is a rule of the game, not an
event something causes), so it is a text-keyed table asked at the one place the
rule is carried out, ``Game.clear_mana_pools`` (``mixins/helpers.py``).

**It asks the board as each step ends**, which is the whole of the 2009-10-01
ruling: "once it leaves the battlefield, they have until the end of the current
step (or phase) to use the mana before it disappears." The mana that floated
while the enchantment was out is simply in the pool; the first step or phase
that ends without one on the battlefield empties it. Nothing is recorded.

Mana an *effect* takes away ("that player loses all unspent mana", Drain Power,
Power Sink) is not the turn-based action and is not asked about: those handlers
empty the pool themselves, and this sentence names only steps and phases ending.

**Who keeps mana is payload**, read the way ``engine/life_prohibitions.py``
reads its subjects, so "You don't lose unspent mana …" needs no code; the
sentence is anchored whole.

Asked by three callers, as every text-keyed table here is: the seam that
enforces it, the support gate (``derived_static_claims``) and the parse claim
(``grammar/registries.py``), with ``scripts/parse_coverage_claims.py``'s channel
beside them.
"""

from __future__ import annotations

import re

#: Which seats a printed subject covers, as scope names (who "you" is depends on
#: who controls the permanent, which is the board scan's question).
_SCOPES: dict[str, str] = {
    "players": "each_player",
    "you": "you",
    "your opponents": "opponents",
}

_KEEPS_UNSPENT_MANA = re.compile(
    rf"^(?P<subject>{'|'.join(_SCOPES)}) (?:don't|doesn't) lose unspent mana "
    r"as steps and phases end$"
)


def unspent_mana_kept_line(line: str) -> str | None:
    """The seat scope *line* keeps unspent mana for, or None."""
    text = " ".join((line or "").strip().lower().rstrip(".").split())
    text = text.replace("’", "'")
    match = _KEEPS_UNSPENT_MANA.match(text)
    if match is None:
        return None
    return _SCOPES[match.group("subject")]


def seats_keeping_unspent_mana(game) -> frozenset[int]:
    """The seats whose pools a permanent on the board keeps from emptying as a
    step or phase ends.

    The whole board, because the printed subject decides the reach ("players"
    is everybody, the enchantment's controller included), and the **effective**
    card (CR 707.2, CR 612.1), so a copy of Upwelling keeps the mana too and one
    whose text was changed does not. One scan for every seat, because the
    caller asks at every step's end.
    """
    seats: set[int] = set()
    everyone = range(len(game.players))
    for controller, permanent in game.permanents_with_controller():
        text = permanent.effective_card.oracle_text or ""
        if "unspent mana" not in text.lower():
            continue
        for line in text.splitlines():
            scope = unspent_mana_kept_line(line)
            if scope == "each_player":
                seats.update(everyone)
            elif scope == "you":
                seats.add(controller)
            elif scope == "opponents":
                seats.update(seat for seat in everyone if seat != controller)
    return frozenset(seats)


__all__ = ["seats_keeping_unspent_mana", "unspent_mana_kept_line"]
