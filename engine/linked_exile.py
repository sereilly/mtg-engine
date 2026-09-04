"""Cards exiled *with* a permanent — the linked-exile record (CR 400.7, 610.3).

Five printed abilities in this pool exile cards and then talk about them again
later: Kitesail Freebooter ("exile that card until this creature leaves the
battlefield"), Idol of Endurance, Tawnos's Coffin, and Knowledge Vault's three
lines.  CR 610.3 calls the pair *linked*: the second ability refers to exactly
the objects the first one moved, and to nothing else.

**One record, one writer, one reader.**  The record is a list of entries under
``RECORD_KEY`` in the exiling permanent's ``metadata``; :func:`link_exiled_card`
is the only thing that appends to it and :func:`linked_entries` /
:func:`take_linked_entries` are the only things that read or drain it.  It lives
on the *permanent* rather than on the game for two reasons: a record on the
permanent goes wherever the permanent does, and — the reason the whole file is
here rather than being a field — ``Permanent.permanent_id`` is stamped fresh
every time a permanent enters (CR 400.7), so a link keyed on an id could not
survive the permanent's own sacrifice.  Knowledge Vault's ``{0}`` ability
sacrifices the artifact and *then* reads what it exiled, so the record has to be
the object itself.

**What ends a link is per entry, not per record.**  ``ends_on`` names the events
that give the cards back on their own: Kitesail Freebooter and Idol of Endurance
say "until this permanent leaves the battlefield" (:data:`LEAVES`), Tawnos's
Coffin says "leaves the battlefield **or becomes untapped**"
(:data:`UNTAPPED` as well), and Knowledge Vault says neither — its cards stay in
exile until one of its own linked abilities moves them.  That distinction used
to be missing, and its absence was a live bug: ``become_untapped`` ended *every*
linked exile, so Idol of Endurance — which taps for its own ability and untaps
in the next untap step — emptied its pile back into the graveyard every turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import CardDefinition, Permanent


#: Where the entries live on the permanent.  A single spelling, imported rather
#: than repeated, because a second copy of the key is a second record.
RECORD_KEY = "linked_exile"

#: The permanent left the battlefield (CR 400.7).
LEAVES = "leaves_battlefield"
#: The permanent became untapped — Tawnos's Coffin's second ending, and only
#: its own: an entry that does not name it is untouched by an untap.
UNTAPPED = "untapped"


def link_exiled_card(
    source: "Permanent",
    card: "CardDefinition",
    owner_index: int,
    *,
    to: str | None = None,
    ends_on: Iterable[str] = (),
    face_down: bool = False,
    looker_index: int | None = None,
    tapped: bool = False,
    counters: dict[str, int] | None = None,
    attach_to_returned: bool = False,
) -> dict[str, Any]:
    """Record one card as exiled with *source*, and return its entry.

    *to* is the zone an automatic ending puts the card back into — the zone it
    came from, because a card returned somewhere it never was is a card the
    effect created out of nothing.  It is meaningless without *ends_on* and is
    left off there: Knowledge Vault's cards go wherever the ability that moves
    them says, which is not always the same zone twice.
    """
    entry: dict[str, Any] = {
        "owner_index": int(owner_index),
        "card": card,
        "ends_on": tuple(ends_on),
    }
    if to is not None:
        entry["to"] = to
    if face_down:
        entry["face_down"] = True
    # "You may look at it for as long as it remains exiled." (Gustha's
    # Scepter.) A face-down exiled card is hidden from **every** player, its
    # owner included (CR 406.3), so a card whose next sentence grants its
    # controller a look has to record who that is. Beside ``face_down`` rather
    # than replacing it: the card is still face down to everyone else, which is
    # the whole point of the ability.
    if looker_index is not None:
        entry["looker_index"] = int(looker_index)
    if tapped:
        entry["tapped"] = True
    if counters:
        entry["counters"] = dict(counters)
    if attach_to_returned:
        entry["attach_to_returned"] = True
    held = list(source.metadata.get(RECORD_KEY) or ())
    held.append(entry)
    source.metadata[RECORD_KEY] = held
    return entry


def shuffle_linked_pile(source: "Permanent", shuffler) -> None:
    """Randomise the order of everything exiled with *source* (Mangara's Tome:
    "…exile them in a face-down pile, **and shuffle that pile**").

    Here rather than at the call site because the record's list is this
    module's — one writer and one reader is the arrangement the whole file is
    built on, and a caller reordering ``metadata[RECORD_KEY]`` itself would be
    a second writer with no comment saying so.

    *shuffler* is passed in rather than imported so the caller's RNG is the one
    used: ``run_ai_simulation`` seeds the module RNG and a given seed has to
    replay a run exactly, which a private ``random`` here would break.
    """
    held = list(source.metadata.get(RECORD_KEY) or ())
    if len(held) < 2:
        return
    shuffler(held)
    source.metadata[RECORD_KEY] = held


def take_top_linked_entry(source: "Permanent | None") -> dict[str, Any] | None:
    """Remove and return the **top** entry of *source*'s pile, or None when it
    is empty (Mangara's Tome: "put the top card of the exiled pile into its
    owner's hand").

    The top is the front of the record. Which end that is makes no observable
    difference for the one card in the pool that asks — the pile was shuffled
    as it was made, so its order is random by construction — and taking from
    the front is what leaves the rest in a stable order across the several
    draws one turn can replace.
    """
    if source is None:
        return None
    held = list(source.metadata.get(RECORD_KEY) or ())
    if not held:
        return None
    top = held.pop(0)
    if held:
        source.metadata[RECORD_KEY] = held
    else:
        source.metadata.pop(RECORD_KEY, None)
    return top


def linked_entries(source: "Permanent | None") -> tuple[dict[str, Any], ...]:
    """Everything currently exiled with *source*, read without draining it."""
    if source is None:
        return ()
    return tuple(source.metadata.get(RECORD_KEY) or ())


def take_linked_entries(
    source: "Permanent | None", *, ending: str | None = None
) -> list[dict[str, Any]]:
    """Drain the entries *ending* ends, leaving the rest on the permanent.

    ``ending=None`` drains the lot, which is what a linked ability naming the
    pile ("put all cards exiled with this artifact into their owner's hand")
    does: it moves them, so they are no longer exiled with anything.  Draining
    is what stops Knowledge Vault's leaves-the-battlefield trigger from finding
    the cards its ``{0}`` ability just returned to a hand.
    """
    if source is None:
        return []
    held = list(source.metadata.get(RECORD_KEY) or ())
    if not held:
        return []
    if ending is None:
        source.metadata.pop(RECORD_KEY, None)
        return held
    taken = [entry for entry in held if ending in (entry.get("ends_on") or ())]
    kept = [entry for entry in held if ending not in (entry.get("ends_on") or ())]
    if kept:
        source.metadata[RECORD_KEY] = kept
    else:
        source.metadata.pop(RECORD_KEY, None)
    return taken


def face_down_exiled_cards(
    game, owner_index: int, viewer_index: int | None = None
) -> list["CardDefinition"]:
    """The cards in seat *owner_index*'s exile that are face down (CR 406.3) —
    face down **to** *viewer_index*, when one is named.

    The viewer matters because a look permission is per seat: Gustha's Scepter
    exiles a card face down and then says "you may look at it for as long as it
    remains exiled", so the same card is hidden from the table and readable by
    the seat that exiled it. ``viewer_index=None`` is the pile as the rules
    describe it with no permission applied, which is what a caller asking
    "which of these are face down at all" wants.

    Derived from the same record rather than stored beside it, because a card
    in exile has no identity of its own to hang a flag on: two copies of one
    card in a deck are the *same* ``CardDefinition`` object, so the only sound
    key for "this exiled card is face down" is the record of the exiling.  The
    scan is over permanents on the battlefield; a card exiled face down by a
    permanent that has since left is face up to the reader for the window
    between the permanent leaving and its linked trigger resolving, which is
    the one place this derivation is looser than the record.
    """
    hidden: list["CardDefinition"] = []
    for permanent in game.all_permanents():
        for entry in linked_entries(permanent):
            if not entry.get("face_down"):
                continue
            if int(entry.get("owner_index", -1)) != owner_index:
                continue
            if (
                viewer_index is not None
                and entry.get("looker_index") == viewer_index
            ):
                continue
            hidden.append(entry["card"])
    return hidden
