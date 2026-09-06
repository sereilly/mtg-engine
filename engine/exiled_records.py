"""Cards that keep working *from exile* — the exile register (CR 400.7, 406.2).

"Exile All Hallow's Eve with two scream counters on it. At the beginning of
your upkeep, if this card is exiled with a scream counter on it, remove a
scream counter from it." A sorcery whose whole card happens after it has left
the stack, from a zone with no objects in it: ``PlayerState.exile`` is a list of
``CardDefinition``, and a ``CardDefinition`` is shared by every copy in the
catalog. So "the counters on *that* exiled card" has nowhere to live and no key
to live under.

**Why not ``engine/linked_exile.py``.** That file records cards exiled *with a
permanent*, and it hangs the record on the exiling permanent for a reason it
states: a ``Permanent`` is the one object that survives its own
``permanent_id`` being restamped. A sorcery exiling *itself* never becomes a
permanent, so there is no such object; and its ``ends_on`` is nothing, because
it leaves exile by its own upkeep trigger rather than by an event anything
watches. Different holder, different ending — a second file rather than a sixth
parameter.

**One record per exiled object, and its identity is the record.** Two copies of
All Hallow's Eve are the *same* ``CardDefinition``, so a register keyed on the
card would merge their counters and take both off with one removal. Each
exiling appends its own :class:`ExiledRecord`, and everything downstream — the
upkeep scan, the trigger's stack item, the counter handlers — carries that
object.

**A record is live only while its card is actually in that seat's exile.**
Derived rather than maintained: asking the zone means a card pulled out of
exile by anything at all silently retires its record, and the register never
speaks for a card that is not there.

**Derivation alone is not enough, and CR 400.7 says why.** An object that
changes zones "becomes a new object with no memory of, or relation to, its
previous existence" — and CR 406.7 extends that to a card already in exile that
becomes exiled again. A *derived* record is inert while its card is elsewhere
and then **comes back to life the moment the same card is exiled by something
else**, still saying "face down", still carrying somebody else's scream
counters. That is precisely the memory the rule forbids. So the departure needs
a seam after all, and it is affordable because the two sides of this zone are
nothing like the same size: 52 sites in ``engine/`` and ``web/`` *append* to
``player.exile`` and none of them has to know about this file, while only
thirteen take a card back out. ``Game.take_card_from_exile`` is that
transition, and ``tests/engine/test_exile_removal_seam.py`` is what keeps it
the only one — the same arrangement ``remove_from_battlefield`` and
``take_card_from_hand`` already have, for the same reason each of those was
written.

The record carries a ``metadata`` dict under the *same* key spelling
``engine/named_counters.py`` uses on a permanent, so ``counters_on`` /
``add_counters`` / ``remove_counters`` read an exiled card and a permanent
through one reader. That is the point: "how many scream counters are on it" is
one question, and a second store for the exile answer is how a card ends up
counting counters nothing put there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import CardDefinition


@dataclass(frozen=True)
class StackAnnouncement:
    """What was decided about a spell when it was announced (CR 601.2), frozen
    so a *copy* of it can be put onto the stack later (CR 707.10).

    "Target spell's controller exiles it with X delay counters on it. … the
    player puts it onto the stack as a copy of the original spell."
    (Ertai's Meddling.) CR 707.10 says a copy "copies both the characteristics
    of the spell and all decisions made for it, including modes, targets, the
    value of X" — and CR 400.7 destroys the ``StackItem`` those decisions live
    on the moment the card leaves the stack. Turns later there is nothing left
    to read them off, so they are written down here.

    A declared schema rather than a loose dict, for :class:`DelayedTrigger`'s
    stated reason one file over: six keys written in one place and read in
    another is a shape nobody declares, and a key spelled differently at one end
    reads as absent. Frozen, because a copy that could be edited afterwards
    would be a record of decisions nobody made.

    Not the ``StackItem`` itself, and that is CR 400.7 again: the object is
    gone, and holding it would be exactly the "memory of its previous existence"
    the rule forbids — a live handle onto a mutable object two zone changes out
    of date.
    """

    caster_index: int
    target_player_index: int | None = None
    target_permanent_index: object = None
    target_permanent_id: object = None
    target_graveyard_card: object = None
    x_value: int | None = None
    chosen_mode_index: int | None = None
    chosen_modes: tuple = ()
    #: CR 707.10's "targets" where the target was another object on the stack
    #: (Ertai's Meddling exiling a Counterspell). Carried as it stood; by the
    #: time the copy is made the object may have resolved, which CR 608.2b
    #: answers at the copy's own resolution rather than here.
    target_stack_item: object = None
    #: Everything the caster picked beyond the target itself — the same dict
    #: ``StackItem.choices`` carries, copied rather than shared so the record
    #: cannot be edited through the object it was read from.
    choices: dict = field(default_factory=dict)


@dataclass
class ExiledRecord:
    """One card in exile that something still reads.

    ``metadata`` is deliberately the same attribute name a ``Permanent``
    carries, so a handler that reads counters off "the ability's source" needs
    no branch: the source is either a permanent or one of these, and both
    answer ``.card`` and ``.metadata``.
    """

    card: "CardDefinition"
    owner_index: int
    #: Whose abilities these are (CR 108.4 — the owner, for a card in exile
    #: with no controller). Kept separately because the two can differ for a
    #: card an opponent's effect exiled, and "at the beginning of **your**
    #: upkeep" needs the seat the ability belongs to rather than the seat that
    #: moved it.
    controller_index: int
    #: CR 406.3 — exiled face down, hidden from every player including its
    #: owner. The same fact ``linked_exile`` records on the exiling *permanent*,
    #: recorded here for the exiler that never becomes one: "Exile the top three
    #: cards of your library face down" (Three Wishes) is a **spell**, so there
    #: is no permanent to hang the record on and the flag would otherwise have
    #: nowhere to live. Which is this file's own opening argument, arriving from
    #: the other side — the identity of the exiled object is the record.
    face_down: bool = False
    #: The one seat that may read it anyway: "You may look at those cards for as
    #: long as they remain exiled" (Three Wishes, Gustha's Scepter). Beside
    #: :attr:`face_down` rather than replacing it, exactly as the linked-exile
    #: entry keeps both — the card is still face down to everyone else, which is
    #: the whole point of the permission.
    looker_index: int | None = None
    #: CR 707.10's copiable decisions, for a card exiled **off the stack** that
    #: something will later put back onto it as a copy of the spell it was
    #: (Ertai's Meddling). None for every other exile: nothing was announced, so
    #: there is nothing to copy, and a handler that finds none makes no copy
    #: rather than guessing at targets nobody chose.
    announcement: "StackAnnouncement | None" = None
    metadata: dict = field(default_factory=dict)


#: The register's attribute on ``Game``.
RECORDS_ATTR = "exiled_records"

#: The trigger-context key a record travels under — written by the upkeep scan
#: that fires an exiled card's own trigger, and by the exile of a spell whose
#: next sentence creates a delayed ability about the card
#: (``handlers/stack.exile_target_spell``); read by :func:`record_in_context`,
#: which is the one reader.
#:
#: Declared here because this file is where the reader is and because it imports
#: nothing from the engine — so the handler layer and the grammar's lowering can
#: both name it without either importing the other. A producer and a consumer
#: two sentences apart is exactly where two spellings of a string come apart.
EXILE_RECORD_KEY = "exile_record"

#: …and the seat the exiled spell's controller was, for a delay that names
#: "each of **that player's** upkeeps". Beside the record rather than read back
#: off it, because ``create_delayed_trigger``'s ``binds_player`` reads a *seat*
#: out of the resolution scratchpad and a record is not one.
EXILED_SPELL_CONTROLLER_KEY = "exiled_spell_controller"


def record_exiled_card(
    game,
    card: "CardDefinition",
    owner_index: int,
    controller_index: int | None = None,
    *,
    counters: dict[str, int] | None = None,
    face_down: bool = False,
    looker_index: int | None = None,
    announcement: "StackAnnouncement | None" = None,
) -> ExiledRecord:
    """Register *card* as exiled, and return its record.

    Written where the exile is *decided* rather than where the card lands,
    because a spell exiling itself does neither in one place: CR 608.2n bins the
    card at the very end of its own resolution (``_bin_spell_card``), long after
    the instruction that said so. The liveness derivation above is what makes
    that safe — a record whose card has not arrived in exile yet reads as not
    live, exactly like one whose card has left.
    """
    from .named_counters import add_counters

    record = ExiledRecord(
        card=card,
        owner_index=int(owner_index),
        controller_index=int(
            owner_index if controller_index is None else controller_index
        ),
        face_down=bool(face_down),
        looker_index=None if looker_index is None else int(looker_index),
        announcement=announcement,
    )
    for kind, count in (counters or {}).items():
        add_counters(record, kind, int(count))
    getattr(game, RECORDS_ATTR).append(record)
    return record


def is_live(game, record: ExiledRecord) -> bool:
    """Whether *record*'s card is in its owner's exile right now."""
    if not 0 <= record.owner_index < len(game.players):
        return False
    return any(card is record.card for card in game.players[record.owner_index].exile)


def live_records(game) -> Iterator[ExiledRecord]:
    """Every registered card that is still in exile, in registration order."""
    for record in list(getattr(game, RECORDS_ATTR, ()) or ()):
        if is_live(game, record):
            yield record


def forget_record(game, record: ExiledRecord) -> None:
    """Drop *record* — the card it speaks for has been moved on deliberately.

    Dropped by identity, never by value: two copies of one card produce two
    equal-looking records and removing "the first equal one" is the look-alike
    bug this whole file exists to avoid.
    """
    held = getattr(game, RECORDS_ATTR, None)
    if not held:
        return
    for index, candidate in enumerate(held):
        if candidate is record:
            held.pop(index)
            return


def record_in_context(context) -> ExiledRecord | None:
    """The exile record a resolving trigger was fired for, if any.

    The upkeep scan stamps it into the trigger context (CR 603.10 — the ability
    is on the stack independently of its source), and this is the one reader.
    """
    return (context.trigger_context or {}).get(EXILE_RECORD_KEY)


def source_object(context):
    """What "it"/"this card" means for the resolving ability: a permanent or a record.

    One reader for the two answers, so a handler that reads ``.card`` and
    ``.metadata`` off "the source" does not have to know which zone the source
    is in — and, more to the point, so the *gate* on an optional action and the
    *handler* that performs it cannot disagree about where the counters are.
    """
    if context.source_permanent is not None:
        return context.source_permanent
    return record_in_context(context)


def newest_record_for(game, owner_index: int, card) -> ExiledRecord | None:
    """The most recently registered **live** record for *card* in seat
    *owner_index*'s exile, or None.

    The singular, owner-scoped sibling of :func:`records_for_cards`, and it
    exists for the departure seam: when one copy of a card leaves a pile that
    holds two, exactly one record has to stop speaking, and the two records are
    not interchangeable — one may be face down with counters and the other
    neither. Which of the two the departing copy "was" is unanswerable (they are
    the same ``CardDefinition`` object), so this picks the newest, which is the
    rule :func:`records_for_cards` already uses; one rule beats two.

    Scoped to the seat because the same object can sit in two players' exiles at
    once — a deck repeats one immutable definition per copy and the catalog is
    shared between seats — so a game-wide identity match would retire the wrong
    player's record.

    Must be asked **before** the card is removed: liveness is derived from the
    pile, so a record read afterwards answers None when the last copy has gone,
    which is exactly the case that needs retiring.
    """
    newest: ExiledRecord | None = None
    for record in getattr(game, RECORDS_ATTR, ()) or ():
        if record.owner_index != owner_index or record.card is not card:
            continue
        if is_live(game, record):
            newest = record
    return newest


def records_for_cards(game, cards) -> list[ExiledRecord]:
    """The live records speaking for *cards*, one record per card, newest first.

    Matched by **identity**, one record consumed per card, because two copies of
    one card in a deck are the same ``CardDefinition`` object: a value match
    would hand the same record back twice and leave the second copy unrecorded.
    Newest first because a card exiled twice has two records and the sentence
    asking is always about the exile it just performed.

    The one reader is a permission granted over what an earlier step of the same
    resolution exiled ("you may look at those cards"), which is why this lives
    beside the register rather than in the handler: the register's liveness rule
    is the only thing that decides which of two equal-looking records is still
    speaking for a card.
    """
    live = list(live_records(game))
    matched: list[ExiledRecord] = []
    for card in cards:
        for record in reversed(live):
            if record.card is card and not any(held is record for held in matched):
                matched.append(record)
                break
    return matched
