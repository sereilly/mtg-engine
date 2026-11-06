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

**The one-shot half.** "You gain shroud until end of turn." (Gilded Light.)
The same word granted to the same seat, by a *resolving* spell rather than a
permanent: the spell has left the stack by the time anybody targets, so there
is no line anywhere to scan and the grant has to be **recorded**, with a
lifetime the cleanup step ends (CR 514.2, CR 611.2a). It hangs off the seat as
an attribute rather than a ``PlayerState`` field — the shape
``engine/turn_replacements.py`` and ``engine/shields.py`` already have — and
:func:`seat_has_player_keyword` reads it beside the board, so the one reader
every targeting gate asks (``legality_enumeration._enumerate_targets``, which
the picker, the announcement gates and CR 608.2b's resolution re-check all go
through) answers both halves and no gate can learn one without the other.
"""

from __future__ import annotations

#: One kind for the family: which keyword and whose seat are payload, so a card
#: printing "you have hexproof" needs no dispatch once the word is implemented.
PLAYER_KEYWORD_STATIC_KIND = "player_keyword_static"

#: The one-shot grant's instruction kind: "You gain shroud until end of turn."
#: (Gilded Light.) Which keywords is payload, for the static kind's reason, and
#: the word is gated on :data:`GRANTABLE_PLAYER_KEYWORDS` by the same lowering
#: rule, so "you gain hexproof until end of turn" refuses until the reader
#: below answers it.
PLAYER_KEYWORD_GRANT_KIND = "grant_player_keyword_until_eot"

#: Where the one-shot grants hang off a seat, for ``engine/shields.py``'s
#: reason: a ``PlayerState`` carries them without learning what one is. Each
#: entry is ``{"keywords": (...), "source_name": ...}``.
_GRANTS_ATTR = "_player_keyword_grants"

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
    """Whether *seat* has *keyword*: a resolved grant still in its window, or
    a permanent on the battlefield granting it.

    "You" is the granting permanent's own controller (CR 109.5), read through
    the control seam so a stolen Ivory Mask protects the thief.

    The static half is derived on every ask rather than stamped, so the ability
    ends with the permanent (CR 611.3b) and a control change moves it with no
    sweep involved; the one-shot half (:func:`grant_player_keyword_until_eot`)
    is the record its resolution left, ended by the cleanup step.
    """
    from .oracle import compile_card_oracle

    # The one-shot half first (Gilded Light): a record a resolution left on the
    # seat, which lasts the turn wherever its spell has gone.
    for grant in getattr(game.players[seat], _GRANTS_ATTR, None) or ():
        if keyword in grant.get("keywords", ()):
            return True
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


def grant_player_keyword_until_eot(
    game, seat: int, keywords, source_name: str | None = None
) -> None:
    """Give *seat* every word in *keywords* until the turn ends.

    "You gain shroud until end of turn." (Gilded Light.) Recorded rather than
    derived, because the spell that printed the sentence is gone by the time
    anything asks (this module's docstring). Only words in
    :data:`GRANTABLE_PLAYER_KEYWORDS` are recorded — the lowering admits no
    other, and a word recorded with no reader would be a grant reported as
    made and asked by nobody.
    """
    words = tuple(word for word in keywords if word in GRANTABLE_PLAYER_KEYWORDS)
    if not words:
        return
    player = game.players[int(seat)]
    grants = list(getattr(player, _GRANTS_ATTR, None) or ())
    grants.append({"keywords": words, "source_name": source_name})
    setattr(player, _GRANTS_ATTR, grants)


def clear_player_keyword_grants(player) -> None:
    """End every one-shot grant on *player* (CR 514.2's "until end of turn").

    The attribute is removed rather than emptied, so a seat whose grant has
    ended is the seat it was before it gained one: ``ai_rehearsal`` digests
    every field a seat carries, and an empty list left behind would read as a
    lasting change made by a spell whose effect is over.
    """
    vars(player).pop(_GRANTS_ATTR, None)


__all__ = [
    "GRANTABLE_PLAYER_KEYWORDS",
    "PLAYER_KEYWORD_GRANT_KIND",
    "PLAYER_KEYWORD_STATIC_KIND",
    "clear_player_keyword_grants",
    "grant_player_keyword_until_eot",
    "seat_has_player_keyword",
]
