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
    from .line_rewrites import expand_card_lines

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

    **A counter with rules meaning brings its P/T with it** (CR 122.1a, layer
    7c) — the exact symmetry :func:`remove_counters` already states and this
    half did not have. Written as a store write alone, this function put a
    "-0/-2" counter's *record* on a creature and left it its size, which is a
    counter that reads as placed and does nothing; the removal half learned the
    same lesson from Triskelion and Wiitigo. The P/T write goes through
    ``pt.add_pt_counters``, so there is still exactly one implementation of
    "place a P/T counter" and it is the one ``engine/pt.py`` documents.
    """
    if count <= 0:
        return counters_on(permanent, kind)
    current = counters_on(permanent, kind)
    total = current + count
    # "…can't have more than seven dream counters on it." (Rasputin
    # Dreamweaver.) Enforced here, at the one write, rather than at whichever
    # path was putting the counter on: a maximum the entry state honoured and a
    # trigger did not is a maximum that is not one.
    cap = counter_cap(permanent, kind)
    if cap is not None:
        total = min(total, cap)
    from .pt import add_pt_counters, pt_counter_deltas, pt_counter_key

    # ``hasattr`` rather than a type check, and it is not defensive coding: the
    # other thing this function is handed is an ``ExiledRecord``, which carries
    # the same ``metadata`` dict on purpose so "how many scream counters are on
    # it" is one question for a permanent and for an exiled card. A record has
    # no layer-7c channel to write to — the card it names is in exile, where
    # nothing in this engine reads a P/T — so it takes the record alone.
    if pt_counter_deltas(kind) is not None and hasattr(permanent, "power_bonus"):
        # The cap decides how many actually land, and only that many may move
        # the P/T: a placement clipped by the cap that still added its full
        # delta would leave the creature a size its counters do not explain.
        if total > current:
            add_pt_counters(permanent, kind, total - current)
        return total
    # ``pt_counter_key``, which is what :func:`counters_on` and
    # :func:`remove_counters` already read. The two spellings agree for every
    # kind but the three CR 122.1a pairs the engine keeps under established
    # names, and for those they did not: this line wrote ``"-1/-1_counters"``
    # while every reader looked in ``"minus_counters"``, so a P/T counter
    # placed through this store was written where nothing would ever find it.
    # One key, and the module docstring's "one store, not two" is finally true
    # of both ends of it.
    permanent.metadata[pt_counter_key(kind)] = total
    return total


#: "{T}, Remove **a counter** from a permanent you control: …" (Power Conduit).
#: CR 122.1's open kind space asked the other way round: any kind answers. It
#: rides ``ActivatedAbilityCost.remove_counter`` where a printed word would, so
#: every reader of that field that is not taught it below asks for counters of
#: a kind named this — which no card places — and finds none: the direction
#: that refuses a payment rather than taking it for free. Never written to a
#: store; :func:`counter_kind_to_remove` turns it into a real kind at payment.
ANY_COUNTER_KIND = "<counter of any kind>"

#: "{1}{R}, Remove **a +1/+1 counter or a charge counter** from a permanent you
#: control: …" (Ion Storm.) The same open choice narrowed to the kinds the
#: cost lists — the payer gives up one counter of whichever listed kind the
#: chosen permanent holds (CR 602.2b). Spelled into the one string field
#: ``ActivatedAbilityCost.remove_counter`` the way :data:`ANY_COUNTER_KIND`
#: is, and for its reason: a reader not taught it asks for counters of a kind
#: named this, which nothing places, and refuses the payment. Built and read
#: by the two functions below only.
_KINDS_OPEN = "<counter of kind "
_KINDS_OR = " or "
_KINDS_CLOSE = ">"


def counter_kind_alternatives(kinds) -> str:
    """The ``remove_counter`` spelling of "a <kind> counter or a <kind>
    counter" — one of *kinds*, in printed order."""
    return f"{_KINDS_OPEN}{_KINDS_OR.join(kinds)}{_KINDS_CLOSE}"


def listed_counter_kinds(kind: str) -> "tuple[str, ...] | None":
    """The kinds a :func:`counter_kind_alternatives` spelling lists, or None
    for any other kind (a printed one, or :data:`ANY_COUNTER_KIND`)."""
    if not (
        isinstance(kind, str) and kind.startswith(_KINDS_OPEN)
        and kind.endswith(_KINDS_CLOSE)
    ):
        return None
    return tuple(kind[len(_KINDS_OPEN):-len(_KINDS_CLOSE)].split(_KINDS_OR))


def counter_kind_words(kind: str) -> str:
    """*kind* as a sentence says it before "counter": the printed word, the
    listed words joined by "or", or nothing for :data:`ANY_COUNTER_KIND` —
    so a refusal reads "a +1/+1 or charge counter" and "a counter", never
    the sentinel spelling."""
    if kind == ANY_COUNTER_KIND:
        return ""
    listed = listed_counter_kinds(kind)
    if listed is not None:
        return _KINDS_OR.join(listed) + " "
    return f"{kind} "

#: The CR 122.1a kinds this engine keeps under a key of their own, read back
#: from the key. The inverse of ``pt._PT_COUNTER_KEYS``, spelled here rather
#: than imported because a store reader must not depend on the layer module.
_KINDS_BY_KEY = {
    "plus_counters": "+1/+1",
    "minus_counters": "-1/-1",
    "plus_1_0_counters": "+1/+0",
}


def counter_kinds_on(permanent) -> dict[str, int]:
    """Every counter on *permanent*, ``{kind: count}`` (CR 122.1).

    Read off the stores :func:`add_counters` and ``pt.add_pt_counters`` write —
    ``<kind>_counters`` for every kind, under the three P/T keys for those —
    so a kind is named exactly as :func:`remove_counters` addresses it, and
    taking one of these off reaches the counter this counted.
    """
    found: dict[str, int] = {}
    for key, value in (getattr(permanent, "metadata", None) or {}).items():
        if not isinstance(key, str) or not key.endswith("_counters"):
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            continue
        kind = _KINDS_BY_KEY.get(key, key[: -len("_counters")])
        found[kind] = found.get(kind, 0) + value
    return found


def counters_held(permanent, kind: str) -> int:
    """How many counters a cost naming *kind* can take off *permanent*:
    :func:`counters_on` for a printed kind, every counter for
    :data:`ANY_COUNTER_KIND`."""
    if kind == ANY_COUNTER_KIND:
        return sum(counter_kinds_on(permanent).values())
    listed = listed_counter_kinds(kind)
    if listed is not None:
        return sum(counters_on(permanent, each) for each in listed)
    return counters_on(permanent, kind)


#: The order a payer nobody asks gives up a counter of any kind in: the one
#: whose loss helps first (a -1/-1 counter, CR 122.1a), then the inert markers
#: (CR 122.3: nothing reacts to their loss but the card counting them), then
#: the ones that size a creature, and loyalty — the permanent's life — last.
_UNASKED_REMOVAL_ORDER = ("-1/-1",)
_UNASKED_REMOVAL_LAST = ("+1/+0", "+1/+1", "loyalty")


def counter_kind_to_remove(
    permanent, named: "str | None" = None, *, among: "tuple[str, ...] | None" = None,
) -> "str | None":
    """Which counter "remove a counter from <it>" takes off *permanent*, or None.

    *named* is the payer's announcement (CR 602.2b's choices through CR
    601.2b): answered when the permanent holds that kind and refused (None)
    when it does not — a named payment is paid as named or not at all. With
    nothing named, a permanent holding one kind needs no choice, and one
    holding several takes :data:`_UNASKED_REMOVAL_ORDER`'s deterministic pick.

    *among* narrows every answer to the kinds a cost lists ("a +1/+1 counter
    or a charge counter", Ion Storm): a kind named outside them is refused
    like a kind the permanent does not hold.
    """
    held = counter_kinds_on(permanent)
    if among is not None:
        held = {kind: count for kind, count in held.items() if kind in among}
    if named:
        return named if held.get(str(named), 0) > 0 else None
    if not held:
        return None
    for kind in _UNASKED_REMOVAL_ORDER:
        if kind in held:
            return kind
    inert = sorted(kind for kind in held if kind not in _UNASKED_REMOVAL_LAST)
    if inert:
        return inert[0]
    return next(kind for kind in _UNASKED_REMOVAL_LAST if kind in held)


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
    "how many are on it" and "take one off" address the same store.

    **A counter with rules meaning takes its P/T with it** (CR 122.1a, layer
    7d). This used to say the opposite — that a caller holding a +1/+1 counter
    wanted ``pt.remove_plus1_counters`` instead — and the two callers that could
    be handed one did not know: Triskelion's "Remove a +1/+1 counter from this
    creature:" cost and Wiitigo's "Otherwise, remove a +1/+1 counter from it"
    both decremented the record and left the creature its size. A rule stated in
    a docstring is a rule two call sites can each be unaware of; stated here it
    is one. ``pt.add_pt_counters`` already made the placing half symmetric for
    exactly this reason.
    """
    from .pt import add_pt_modifier, pt_counter_deltas, pt_counter_key

    current = counters_on(permanent, kind)
    if count <= 0 or current <= 0:
        return current
    taken = min(count, current)
    total = current - taken
    deltas = pt_counter_deltas(kind)
    if deltas is not None:
        power, toughness = deltas
        add_pt_modifier(permanent, -power * taken, -toughness * taken)
    permanent.metadata[pt_counter_key(kind)] = total
    if total == 0:
        emptied = set(permanent.metadata.get(EMPTIED_KINDS_MARK) or ())
        permanent.metadata[EMPTIED_KINDS_MARK] = emptied | {kind}
        # "That land is an Island **for as long as it has a flood counter on
        # it**." (Quicksilver Fountain.) The last counter of the kind is gone,
        # so the change it held up ends — here, at the one write that takes a
        # counter away, so every road out of the counter ends it.
        from .land_types import end_counter_tied_land_type

        end_counter_tied_land_type(permanent, kind)
    return total


__all__ = [
    "ANY_COUNTER_KIND",
    "CAP_CLAIM",
    "EMPTIED_KINDS_MARK",
    "add_counters",
    "counter_cap",
    "counter_cap_line",
    "counter_kind_alternatives",
    "counter_kind_to_remove",
    "counter_kind_words",
    "counter_kinds_on",
    "counters_held",
    "counters_key",
    "counters_on",
    "listed_counter_kinds",
    "remove_counters",
]
