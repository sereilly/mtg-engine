"""Counters with no rules meaning of their own (CR 122.1, CR 122.3).

"Put a **page** counter on this artifact" (Mazemind Tome). A counter whose kind
is a word the card invents: nothing in the rules reacts to it, and the only
thing that reads it is the card that put it there. That is exactly why it is
separate from ``engine/pt.py``'s +1/+1 channel and from the loyalty one — those
counters *do* have rules meaning (layer 7d, CR 606), and routing an inert marker
through either would make it change a creature's size or a walker's survival.

One metadata key per kind, ``"<word>_counters"``, because the kinds are open:
the next set invents another word and needs no code here.

**One store, not two.** This module arrived (round 127) alongside an older
spelling — Armageddon Clock's doom counters and Cyclone's wind counters were
already `metadata["<word>_counters"]`, written and read by the upkeep registry
and the removal handler. Two stores for one concept is how a card ends up
putting counters somewhere nothing reads, which is exactly what happened the
moment the grammar learned to read "put a soul counter on this Equipment": the
placement went to one store and the card's own P/T grant looked in the other.
So the key here *is* the old spelling, and the older readers were already
right.

The counters travel with the permanent and die with it, which CR 400.7 already
gives for free — a permanent that leaves and returns is a new object with no
counters, and nothing has to clear them.
"""

from __future__ import annotations

import re

#: The claim string the support gates use for the cap below.
CAP_CLAIM = "named_counter_cap"

#: "Rasputin can't have more than seven dream counters on it." A **maximum** on
#: the store, printed as a static ability of the permanent carrying it. Both the
#: number and the counter word are payload, for the reason every other parameter
#: in this engine is: a card printing a different many of a differently-named
#: counter is the same sentence.
#:
#: Not the same rule as ``riders._attach_counter_cap``, which reads Clockwork
#: Beast's "**This ability** can't cause the total number of +1/+0 counters on
#: this creature to be greater than seven". That one bounds one ability and is
#: enforced where that ability resolves; this one bounds the permanent and is
#: enforced at the store, so *every* way a counter could arrive is covered —
#: which is the only reading of "can't have" that is true.
_COUNTER_CAP = re.compile(
    r"^this [a-z]+ can't have more than (?P<count>[a-z]+) "
    r"(?P<counter>[a-z]+) counters on it$"
)


def counter_cap_line(line: str, card_name: str | None = None) -> tuple[int, str] | None:
    """``(maximum, counter word)`` *line* imposes, or None.

    Read by the support gate *and* by :func:`add_counters`, so what is claimed
    and what is enforced cannot drift. *card_name* collapses a card that names
    itself, through the collapser every other restriction table uses.
    """
    from .grammar.vocabulary import NUMBER_WORDS
    from .oracle import _restriction_line, normalize_creature_line

    text = (
        _restriction_line(line, card_name)
        if card_name
        else normalize_creature_line(line)
    )
    match = _COUNTER_CAP.match(text)
    if match is None:
        return None
    count = NUMBER_WORDS.get(match.group("count"))
    # A number word the table does not know refuses the line rather than
    # defaulting: a cap of one where the card prints seven is a strictly smaller
    # card, and a cap of zero would make the permanent's own abilities inert.
    return None if count is None else (count, match.group("counter"))


def counter_cap(permanent, kind: str) -> int | None:
    """The maximum number of *kind* counters *permanent* may have, or None.

    Read off the **effective** card, so a copied or text-changed permanent is
    asked what it says now (CR 613 layers 1 and 3) — the same reading
    ``target_immunity`` gives its own restriction.
    """
    from .oracle import expand_card_lines

    card = getattr(permanent, "effective_card", None) or permanent.card
    for line in expand_card_lines(card):
        capped = counter_cap_line(line, card.name)
        if capped is not None and capped[1] == kind:
            return capped[0]
    return None


def counters_key(kind: str) -> str:
    """The metadata key *kind* counters live under."""
    return f"{kind}_counters"


def counters_on(permanent, kind: str) -> int:
    """How many *kind* counters are on *permanent*.

    Through ``pt.pt_counter_key`` rather than :func:`counters_key` directly, so
    "how many +1/+1 counters are on it" is the *same* question as "how many doom
    counters are on it" and gets the same reader. A P/T counter is recorded in
    the persistent P/T channel under a key of its own (CR 122.1a), and reading
    it here by this file's spelling would have answered zero for every card that
    counts one — silently, because a missing key is a legal zero.
    """
    from .pt import pt_counter_key

    return int(permanent.metadata.get(pt_counter_key(kind), 0) or 0)


def add_counters(permanent, kind: str, count: int = 1) -> int:
    """Put *count* counters of *kind* on *permanent*; returns the new total.

    No CR 614 event and no replacement contention, unlike
    ``Game.place_plus1_counters``: a counter with no rules meaning has nothing
    to modify and nothing to trigger on its own. A card that *does* react to one
    reads the total, which is what Mazemind Tome's state trigger does.
    """
    if count <= 0:
        return counters_on(permanent, kind)
    total = counters_on(permanent, kind) + count
    # "…can't have more than seven dream counters on it." (Rasputin
    # Dreamweaver.) Enforced here, at the one write, rather than at whichever
    # path was putting the counter on: a maximum the entry state honoured and a
    # trigger did not is a maximum that is not one.
    cap = counter_cap(permanent, kind)
    if cap is not None:
        total = min(total, cap)
    permanent.metadata[counters_key(kind)] = total
    return total


#: The kinds of counter a permanent has been emptied of and not yet announced
#: for. Written by :func:`remove_counters`, drained by the state-based sweep in
#: ``engine/mixins/game_ending.py``.
#:
#: A record rather than an announcement, because removal has four call sites --
#: the ``remove_counter_from_self`` handler, an activation cost, an upkeep
#: registry entry and a damage shield -- and a list of fire sites is only ever
#: as complete as the last card that touched it. That is the same argument the
#: draw and second-draw triggers in that file are written with, and Divine
#: Intervention is the card that would have paid for getting it wrong: its whole
#: text is "the game is a draw" when the last counter comes off.
EMPTIED_KINDS_MARK = "_counter_kinds_emptied"


def remove_counters(permanent, kind: str, count: int = 1) -> int:
    """Take *count* counters of *kind* off *permanent*; returns the new total.

    The twin of :func:`add_counters` and the one write that takes counters away.
    Removing from zero is a no-op, not a negative count, and removing more than
    are there takes what is there (CR 608.2b: do as much as possible).

    Through ``pt.pt_counter_key``, the same reader :func:`counters_on` uses, so
    "how many are on it" and "take one off" address the same store. Callers with
    a +1/+1 or -1/-1 counter in hand still want ``pt.remove_plus1_counters``:
    those have rules meaning (layer 7d) and a persistent P/T channel beside the
    record, which this function does not touch.
    """
    from .pt import pt_counter_key

    current = counters_on(permanent, kind)
    if count <= 0 or current <= 0:
        return current
    total = max(0, current - count)
    permanent.metadata[pt_counter_key(kind)] = total
    if total == 0:
        emptied = set(permanent.metadata.get(EMPTIED_KINDS_MARK) or ())
        permanent.metadata[EMPTIED_KINDS_MARK] = emptied | {kind}
    return total


__all__ = [
    "CAP_CLAIM",
    "EMPTIED_KINDS_MARK",
    "add_counters",
    "counter_cap",
    "counter_cap_line",
    "counters_key",
    "counters_on",
    "remove_counters",
]
