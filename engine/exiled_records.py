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
Derived rather than maintained, which is what makes this safe without an exile
*seam*: ~28 places in the engine append to ``player.exile`` and none of them
knows about this file, so a register that had to be told when a card left would
go stale in twenty-eight ways. Asking the zone instead means a card pulled out
of exile by anything at all silently retires its record, and the register never
speaks for a card that is not there.

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
    metadata: dict = field(default_factory=dict)


#: The register's attribute on ``Game``.
RECORDS_ATTR = "exiled_records"


def record_exiled_card(
    game,
    card: "CardDefinition",
    owner_index: int,
    controller_index: int | None = None,
    *,
    counters: dict[str, int] | None = None,
    face_down: bool = False,
    looker_index: int | None = None,
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
    return (context.trigger_context or {}).get("exile_record")


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
