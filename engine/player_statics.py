"""Keywords a static ability grants to a **player** (CR 702.18a).

"You have shroud." (Ivory Mask.) CR 702.18a defines shroud as "This permanent
**or player** can't be the target of spells or abilities", so the word really
does apply to a seat — a fact ``engine/game.py`` asserted the opposite of for
several sets, beside ``targeting_bans``, which is CR 115.1 denied outright for a
stated window (Peace Talks) and is a different mechanism: a window is state a
resolution wrote and a sweep counts down, and this is a continuous ability
derived from a permanent that is on the battlefield right now (CR 611.3).

Two halves, and they are here together for the reason every derivation table in
this engine gives: **what the grammar may admit** and **what the engine can
carry out** are one list. A word admitted with no reader behind it is a static
that compiles, reports supported and does nothing — the failure mode this file
exists to make impossible, so the gate and the reader read one frozenset.

The reader scans the board rather than stamping a flag on the seat, which is
what makes the grant end the instant the source leaves (CR 611.3b) with no sweep
to remember.
"""

from __future__ import annotations

#: One kind for the family: which keyword and whose seat are payload, so a card
#: printing "you have hexproof" needs no dispatch once the word is implemented.
PLAYER_KEYWORD_STATIC_KIND = "player_keyword_static"

#: The keywords this engine answers **about a player**. Shroud alone today, and
#: the set is the gate: `engine/grammar/statics.py` admits a line only for a
#: word in here, so "you have hexproof" refuses and names the clause rather than
#: compiling into a static nothing reads.
#:
#: Not `vocabulary.IMPLEMENTED_KEYWORDS`, which is a claim about *permanents*:
#: flying is implemented and a player cannot have it, and admitting the word
#: here because a creature can have it is exactly the drift this pair of lists
#: is arranged against.
GRANTABLE_PLAYER_KEYWORDS = frozenset({"shroud"})


def seat_has_player_keyword(game, seat: int, keyword: str) -> bool:
    """Whether any permanent on the battlefield grants *keyword* to *seat*.

    "You" is the granting permanent's own controller (CR 109.5), read through
    the control seam so a stolen Ivory Mask protects the thief.

    Derived on every ask rather than stamped, so the ability ends with the
    permanent (CR 611.3b) and a control change moves it with no sweep involved.
    """
    from .oracle import compile_card_oracle

    for controller_index, permanent in game.permanents_with_controller():
        if controller_index != seat:
            continue
        for instruction in compile_card_oracle(
            permanent.effective_card
        ).instructions:
            if instruction.kind != PLAYER_KEYWORD_STATIC_KIND:
                continue
            if keyword in (instruction.payload.get("keywords") or ()):
                return True
    return False


__all__ = [
    "GRANTABLE_PLAYER_KEYWORDS",
    "PLAYER_KEYWORD_STATIC_KIND",
    "seat_has_player_keyword",
]
