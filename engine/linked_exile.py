"""Cards exiled *with* a permanent — the linked-exile record (CR 400.7, 610.3).

Five printed abilities in this pool exile cards and then talk about them again
later: Kitesail Freebooter ("exile that card until this creature leaves the
battlefield"), Idol of Endurance, Tawnos's Coffin, and Knowledge Vault's three
lines.  CR 610.3 calls the pair *linked*: the second ability refers to exactly
the objects the first one moved, and to nothing else.

**One record, one writer, one reader.**  The record is a list of entries under
``RECORD_KEY`` in the exiling permanent's ``metadata``; :func:`link_exiled_card`
(and :func:`put_back_linked_entry`, for an entry a sweep drained and kept)
are the only things that append to it and :func:`linked_entries` /
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

from .exiled_records import live_records
from .exiler_grants import EXILER_KEY, exiler_may_look

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


def until_leaves_has_ended(game, source: "Permanent | None") -> bool:
    """Whether an effect that lasts "until [this] leaves the battlefield" is
    already over before it began, because *source* has left (CR 610.3a/b).

    "If a resolving triggered ability creates the initial one-shot effect that
    causes the object to change zones, and the specified event has already
    occurred before that one-shot effect would occur but after that ability
    triggered, the object doesn't move." Each handler that moves something
    until its source leaves asks this **before it moves anything**: once the
    source is gone there is no event left to end the effect, so a card exiled
    then is exiled for good and a creature phased out then never phases in.

    Unreachable while a permanent's entry trigger was resolved inline, as the
    permanent entered; reachable from the day it became a stack object, since
    the source can be destroyed in response. ROADMAP had said so in advance,
    naming Idol of Endurance, and the first drive after that change found it on
    all three cards the pool prints the phrase on.

    **A phased-out source has not left.** CR 702.26d: "the phasing event
    doesn't actually cause a permanent to change zones", and Reality Ripple,
    Vodalian Illusionist, Sapphire Charm and Vision Charm can each phase one of
    these sources out in response to its own trigger. This engine takes a
    phased-out permanent off the battlefield lists, so ``is_on_battlefield``
    alone would call that source gone and the effect would be skipped for a
    permanent that is coming back next untap step.
    """
    if source is None:
        return True
    return not (game.is_on_battlefield(source) or source.metadata.get("phased_out"))


def until_leaves_source(game, permanent_id) -> "Permanent | None":
    """The permanent an "until this leaves the battlefield" effect is tied to,
    by id: on the battlefield, **or phased out** (CR 702.26d - see
    :func:`until_leaves_has_ended`). None once it has really left.

    ``Game.permanent_by_id`` answers for the battlefield alone, which is right
    for a target (CR 702.26b: a phased-out permanent is treated as though it
    does not exist) and wrong for a duration, which asks only whether the
    leaving has happened.
    """
    found = game.permanent_by_id(permanent_id)
    if found is not None or permanent_id is None:
        return found
    for player in game.players:
        for permanent in player.phased_out:
            if permanent.permanent_id == permanent_id:
                return permanent
    return None


def link_exiled_card(
    source: "Permanent",
    card: "CardDefinition",
    owner_index: int,
    *,
    to: str | None = None,
    ends_on: Iterable[str] = (),
    face_down: bool = False,
    looker_index: int | None = None,
    exiler_index: int | None = None,
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
    # "Each player may look at cards **they exiled** with this enchantment,
    # and they may play lands and cast spells from among those cards."
    # (Shared Fate.) Who exiled the card, when that is not the permanent's
    # controller — every player's draw exiles with the same enchantment. Not
    # a look permission by itself: the permanent's static grants one
    # (``engine/exiler_grants.py``), and only while it is there to.
    if exiler_index is not None:
        entry[EXILER_KEY] = int(exiler_index)
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


def put_back_linked_entry(source: "Permanent", entry: dict[str, Any]) -> None:
    """Return a drained *entry* to *source*'s record, **as it was**.

    A sweep that drains the pile and keeps part of it ("Return each creature
    card exiled with this artifact", Cold Storage; "all other cards you own",
    Duplicity) puts the rest back. Rebuilt through :func:`link_exiled_card`,
    each kept entry lost whatever that call was not handed — a Cold Storage
    pile's face-down flag, a look permission, its destination — and a card
    exiled face down came back to the record face up. The same dict goes back
    instead, so every fact on it survives.
    """
    held = list(source.metadata.get(RECORD_KEY) or ())
    held.append(entry)
    source.metadata[RECORD_KEY] = held


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


def cards_still_exiled_with(
    game, source: "Permanent | None"
) -> list[tuple["CardDefinition", int]]:
    """**"The exiled card"** (CR 607.2a): every card *source*'s linked ability
    exiled that is **still in its owner's exile**, as ``(card, owner_index)``
    in the order it was exiled.

    The noun imprint's second ability prints ("any of the exiled card's
    colors", Chrome Mox; "protection from each of the exiled card's card
    types", Mirror Golem; "a copy of the exiled card", Soul Foundry and
    Isochron Scepter). One reader for all of them, because the two facts that
    make the answer are the same for every printing:

    * **The record is the permanent's**, so a permanent that left and came back
      is a new object with no record at all (CR 400.7) — and a source that has
      left still answers for an ability already on the stack (Isochron
      Scepter's 2020-08-07 ruling: the ability "can still make a copy").
    * **A card that left exile is gone from the answer**, by identity
      (Isochron Scepter's ruling: "if the imprinted card leaves the exile zone
      while the activated ability is on the stack, the copy can't be made").
      Two copies of one card are the same ``CardDefinition`` object, and
      ``Game.put_card_into_exile`` makes a distinct one on a collision, so the
      object in the entry is in an exile exactly while that exiling stands.

    Several entries is CR 607.3's case (the exile was copied): each reader
    gets every card and decides what "the" card means for it.
    """
    found: list[tuple["CardDefinition", int]] = []
    for entry in linked_entries(source):
        card = entry.get("card")
        owner = int(entry.get("owner_index", -1))
        if card is None or not 0 <= owner < len(game.players):
            continue
        if any(held is card for held in game.players[owner].exile):
            found.append((card, owner))
    return found


def shares_a_name_with_an_exiled_card(game, source: "Permanent | None", card) -> bool:
    """Whether *card* has the same name as one of the cards *source*'s linked
    ability exiled and still in exile — "a land **with the same name as the
    exiled card**" (Extraplanar Lens), "a card … **with the same name as one of
    the cards exiled with this artifact**" (Spellweaver Helix).

    CR 201.2a: two objects share a name when they have at least one in common,
    so each name of a split card is asked (the Helix's 2017-04-18 ruling),
    through the reader every name question goes through
    (``counted_names.card_answers_to_name``).
    """
    from .counted_names import card_answers_to_name
    from .faces import card_names

    return any(
        card_answers_to_name(card, name)
        for exiled, _owner in cards_still_exiled_with(game, source)
        for name in card_names(exiled)
    )


def take_linked_entry_at(
    source: "Permanent | None", position: int
) -> dict[str, Any] | None:
    """Remove and return the entry at *position* in *source*'s record, leaving
    every other entry where it was — or None when there is no such entry.

    One card out of a pile that stays a pile: "Return **a card** you own exiled
    with this artifact to your hand" (Gustha's Scepter) names the position its
    controller picked, and "Choose a card **at random** that was exiled with
    Skyship Weatherlight" names the one chance did. Both are positions into
    :func:`linked_entries` rather than cards, for the reason the whole record
    is entries: two copies of one card in a deck are the same
    ``CardDefinition`` object, so a card cannot say which entry is meant.
    """
    if source is None:
        return None
    held = list(source.metadata.get(RECORD_KEY) or ())
    if not 0 <= position < len(held):
        return None
    taken = held.pop(position)
    if held:
        source.metadata[RECORD_KEY] = held
    else:
        source.metadata.pop(RECORD_KEY, None)
    return taken


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
    scan is over permanents on the battlefield; a permanent that leaves (or
    phases out) hands its face-down entries to the game's register as it goes
    (:func:`keep_face_down_after_departure`), so a card exiled face down stays
    face down after its exiler is gone — CR 406.3 has no ending.

    **Two registers, one question.** A *spell* that exiles face down (Three
    Wishes) never becomes a permanent, so its record lives on the game
    (``engine/exiled_records.py``) instead. Both are scanned here rather than by
    two functions the web layer would have to remember to call: "which of these
    cards are face down to me" has one answer, and a second entry point is how a
    viewer comes to be shown half a hidden pile.
    """
    hidden: list["CardDefinition"] = []
    for permanent in game.all_permanents():
        for entry in linked_entries(permanent):
            if not entry.get("face_down") or entry.get(HANDED_TO_REGISTER):
                continue
            if int(entry.get("owner_index", -1)) != owner_index:
                continue
            if (
                viewer_index is not None
                and entry.get("looker_index") == viewer_index
            ):
                continue
            # The seat that exiled it, while the permanent's static lets that
            # seat look (Shared Fate, ``exiler_grants.exiler_may_look``).
            if (
                viewer_index is not None
                and EXILER_KEY in entry
                and exiler_may_look(permanent, entry, viewer_index)
            ):
                continue
            hidden.append(entry["card"])
    for record in live_records(game):
        if not record.face_down or record.owner_index != owner_index:
            continue
        if viewer_index is not None and record.looker_index == viewer_index:
            continue
        hidden.append(record.card)
    return hidden


#: Stamped on a face-down entry whose fact the game's register now holds
#: (:func:`keep_face_down_after_departure`), so a source that phases back in —
#: or an entry read again — is not a second record of one hidden card.
HANDED_TO_REGISTER = "face_down_registered"


def keep_face_down_after_departure(game, permanent: "Permanent") -> None:
    """A permanent leaving the battlefield, or phasing out, keeps what it
    exiled face down hidden (CR 406.3).

    "Exile the top card of your library face down" (Necropotence) and "exile
    them in a face-down pile" (Mangara's Tome) record the fact on the exiling
    permanent, which is the only object that can tell one copy of a card from
    another. :func:`face_down_exiled_cards` scans the battlefield, so the moment
    the permanent left — sacrificed to Kyren Archive's own cost, destroyed with
    Necropotence's card still waiting for the end step, or phased out — every
    one of its face-down cards read face up to every viewer, for the rest of
    the game. Nothing in the rules turns them up: a card exiled face down stays
    so until an instruction says otherwise.

    So each such entry whose card is still in its owner's exile goes on the
    game's register (``engine/exiled_records.py``, the record Three Wishes and
    Memory Jar already keep), with the seat that may look at it, and the entry
    is stamped :data:`HANDED_TO_REGISTER`. The entry itself stays where it is:
    the linked abilities that read it after the permanent is gone (Knowledge
    Vault's sacrifice, then "put all cards exiled with it") still drain it, and
    the card's departure from exile retires the record
    (``Game.take_card_from_exile``).
    """
    from .exiled_records import record_exiled_card

    for entry in linked_entries(permanent):
        if not entry.get("face_down") or entry.get(HANDED_TO_REGISTER):
            continue
        owner_index = int(entry.get("owner_index", -1))
        if not 0 <= owner_index < len(game.players):
            continue
        card = entry["card"]
        if not any(held is card for held in game.players[owner_index].exile):
            continue
        record_exiled_card(
            game, card, owner_index, face_down=True,
            looker_index=entry.get("looker_index"),
        )
        entry[HANDED_TO_REGISTER] = True


def forget_exiler_entries(game, owner_index: int, card) -> None:
    """*card* has just left seat *owner_index*'s exile: drop every entry
    naming it that records who exiled it (``EXILER_KEY``).

    Those entries are read by derivation — "cards they exiled with this
    enchantment" is a scan of the record for a card still in exile — and CR
    400.7 is the rule a derivation breaks: a card cast from exile that later
    comes back to exile (the same object, when no exile holds it) is a new
    object the permanent never exiled. Left behind, the entry would hand its
    exiler the card again and hide it from everyone else. Called by the one
    departure seam (``Game.take_card_from_exile``); a phased-out permanent's
    record is cleaned too, since it is still the object it was (CR 702.26d).
    """
    holders = list(game.all_permanents()) + [
        permanent for player in game.players for permanent in player.phased_out
    ]
    for permanent in holders:
        held = list(permanent.metadata.get(RECORD_KEY) or ())
        kept = [
            entry for entry in held
            if not (
                EXILER_KEY in entry
                and entry.get("card") is card
                and int(entry.get("owner_index", -1)) == owner_index
            )
        ]
        if len(kept) == len(held):
            continue
        if kept:
            permanent.metadata[RECORD_KEY] = kept
        else:
            permanent.metadata.pop(RECORD_KEY, None)


#: The zones only their owner may look into (CR 400.2: a library and a hand are
#: hidden zones). A card going into one of them from a face-down exile was never
#: shown to anybody on its way.
HIDDEN_ZONES = frozenset({"hand", "library"})


def is_exiled_face_down(game, card) -> bool:
    """Whether *card* — the object, never a look-alike — is in some seat's exile
    face down (CR 406.3), to anybody at all.

    Exact, because no exile holds one object twice
    (``Game.put_card_into_exile``): a face-up copy beside a face-down one is
    another object. Fail-closed only for a pile written directly (a test, the
    Debug Menu's injection), where a face-up copy sharing the object reads
    "face down" — the answer that cannot give the hidden one away.
    """
    return any(
        held is card
        for seat in range(len(game.players))
        for held in face_down_exiled_cards(game, seat)
    )


def exiled_cards_for_the_log(game, cards) -> str:
    """*cards*, each in exile, as ``game.log`` may name them: every face-up one
    by name and the face-down ones counted (CR 406.3).

    ``game.log`` is one list served whole to every seat and every spectator
    (``engine/refusals.py``), so a line in it is an announcement — and a card
    exiled face down is one no player may examine, its owner included, unless
    an instruction lets one look (Three Wishes, Gustha's Scepter). A permission
    to look is one seat's view, never the table's, so it changes nothing here.
    """
    shown: list[str] = []
    hidden = 0
    for card in cards:
        if is_exiled_face_down(game, card):
            hidden += 1
        else:
            shown.append(card.name)
    if hidden:
        shown.append(f"{hidden} face-down card(s)")
    return ", ".join(shown)


def entry_name_for_the_log(entry: dict[str, Any], zone: str) -> str:
    """How ``game.log`` names a linked entry's card as it goes to *zone*: by
    name, unless it was exiled face down and goes where nobody sees it (a
    hand, a library — CR 406.3, 400.2). A face-down card going anywhere public
    is seen arriving, so its name is the table's then."""
    if entry.get("face_down") and zone in HIDDEN_ZONES:
        return "a face-down card"
    return entry["card"].name
