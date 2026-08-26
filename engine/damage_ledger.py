"""What every source dealt this turn, in one record.

Two cards in this pool ask a question the board cannot answer, because what
they ask about is over:

- **Blazing Effigy** — "3 plus the amount of damage dealt to this creature this
  turn by other sources named Blazing Effigy". The creature is in a graveyard
  by the time the question is asked, and the damage marked on it went with it.
- **Backdraft** — "half the damage dealt by one of those sorcery spells this
  turn". The spell resolved and left the stack; a sorcery is never anywhere a
  board read could find it.

Both are the same fact — *how much damage did this source deal this turn* —
asked of a different kind of source, so they are one record and not two. That
matters more than it sounds: a per-card record would have been declined a
fourth time (rounds 24, 28 and 32 each declined Blazing Effigy on exactly the
grounds that one card is not a mechanism), and two records would have been the
same refusal twice.

**The record is written at the seam, not at the fire sites.** ``deal_damage``
is the one place every damage event in this engine passes through — there is no
half-event entry point — so the entry is written there, for the same reason
``damage_source_seat`` is derived there and ``Game.put_card_into_hand`` exists
at all. Thirty fire sites is twenty-nine places to forget it.

**Identity is the whole difficulty.** ``event["source"]`` for a spell is its
printed ``CardDefinition``: one object, shared by every copy in every deck,
controlled by nobody (round 26). Two casts of the same sorcery are therefore
indistinguishable by their source, and a record keyed on it would tell Backdraft
that the second Lava Burst dealt what both of them dealt together. So a spell's
damage is keyed on the ``StackItem`` — one object per **cast** — reached through
``Game.resolving_items``, which is where the damage paths can see which cast is
running. A permanent's damage is keyed on ``permanent_id``, which CR 400.7 makes
one object per *time on the battlefield*: a Blazing Effigy that died and came
back is a different source, and the card's "other sources" is honest about that.

**Casts are recorded even when they deal nothing**, which is why this holds two
lists rather than one. "One of those sorcery spells" is a choice its controller
makes, and the spells that dealt no damage are exactly the ones they want when
the only player who cast a sorcery this turn is themselves — a ledger of damage
alone could not offer them, and the prompt would silently drop the best answer.

Lifetime is the turn: cleared by ``begin_turn_bookkeeping`` beside
``spells_cast_this_turn``, which is the same "this turn" every clause here
prints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DamageEntry:
    """One damage event, as much of it as a later question can ask about.

    ``amount`` is CR 120.4b's *dealt*, never 120.4c's result: "the amount of
    damage dealt to this creature" is what the source dealt, and Ali from Cairo
    capping the life lost does not change what was dealt.
    """

    amount: int
    source_name: str | None
    source_permanent_id: int | None
    source_cast: Any | None
    source_seat: int | None
    recipient_seat: int | None
    recipient_permanent_id: int | None


@dataclass(frozen=True)
class CastEntry:
    """One cast, by its per-cast identity.

    ``item`` is the ``StackItem`` and is the key the damage entries above join
    on; ``card`` and ``seat`` are what a prompt renders and what "a player who
    cast one or more sorcery spells" filters on. Kept after the spell has left
    the stack, because that is precisely when it is asked about.
    """

    item: Any
    card: Any
    seat: int


@dataclass
class DamageLedger:
    entries: list[DamageEntry] = field(default_factory=list)
    casts: list[CastEntry] = field(default_factory=list)

    def clear(self) -> None:
        self.entries.clear()
        self.casts.clear()


def ledger(game) -> DamageLedger:
    """The game's ledger, tolerating a stand-in Game a test built by hand."""
    existing = getattr(game, "damage_ledger", None)
    if isinstance(existing, DamageLedger):
        return existing
    fresh = DamageLedger()
    try:
        game.damage_ledger = fresh
    except Exception:  # pragma: no cover - a frozen stand-in
        pass
    return fresh


def source_name_of(source) -> str | None:
    """The printed name of whatever dealt the damage.

    A ``Permanent`` answers through its card; a spell's source *is* a card.
    ``effective_card`` first, because "sources **named** Blazing Effigy" is
    CR 201.2's name comparison and a name is a characteristic — layer 1's copy
    (CR 707.2) changes it, so a Clone of a Blazing Effigy is one, and the
    printed read would miss exactly that. The printed card is the fallback for
    a source that has no layers to ask: a spell, or a permanent that has left.
    """
    if source is None:
        return None
    try:
        card = getattr(source, "effective_card", None)
    except Exception:  # pragma: no cover - a permanent the layers cannot reach
        card = None
    if card is None:
        card = getattr(source, "card", source)
    name = getattr(card, "name", None)
    return str(name) if name else None


def _source_cast(game, source):
    """Which *cast* dealt this damage, or None if a cast did not deal it.

    The innermost resolving object whose card **is** the damage's source: a
    spell deals damage during its own resolution and carries its printed card as
    the source, so identity between the two is the exact test. A permanent's
    ability fails it — its source is a ``Permanent``, never a
    ``CardDefinition`` — which is right, since an ability of a permanent is not
    a spell and the clause that reads this asks about spells.
    """
    if source is None:
        return None
    for item in reversed(getattr(game, "resolving_items", None) or ()):
        if getattr(item, "card", None) is source:
            return item
    return None


def record_cast(game, item) -> None:
    """Record one cast, at the single site that puts a spell on the stack."""
    seat = getattr(item, "caster_index", None)
    if seat is None:
        return
    ledger(game).casts.append(CastEntry(item=item, card=item.card, seat=int(seat)))


def record_damage(game, event: dict, dealt: int) -> None:
    """Record one damage event, from inside ``deal_damage``.

    Nothing is recorded for a 0-damage event: CR 120.8 makes it no damage event
    at all, and an entry for it would let "one of those sorcery spells" join
    against a spell that dealt nothing *twice*.
    """
    if dealt <= 0:
        return
    from .models import PlayerState

    source = event.get("source")
    recipient = event.get("recipient")
    recipient_seat = None
    recipient_permanent_id = None
    if isinstance(recipient, PlayerState):
        try:
            recipient_seat = game.players.index(recipient)
        except ValueError:  # pragma: no cover - a player not in this game
            recipient_seat = None
    else:
        recipient_permanent_id = getattr(recipient, "permanent_id", None)
    ledger(game).entries.append(
        DamageEntry(
            amount=int(dealt),
            source_name=source_name_of(source),
            source_permanent_id=getattr(source, "permanent_id", None),
            source_cast=_source_cast(game, source),
            source_seat=event.get("source_seat"),
            recipient_seat=recipient_seat,
            recipient_permanent_id=recipient_permanent_id,
        )
    )


def clear_for_new_turn(game) -> None:
    ledger(game).clear()


def damage_dealt_to_permanent(
    game,
    permanent_id: int | None,
    *,
    source_name: str | None = None,
    exclude_source_permanent_id: int | None = None,
) -> int:
    """How much damage was dealt to one permanent this turn, narrowed by source.

    *source_name* is CR 201.2's comparison — "sources **named** …" — and
    *exclude_source_permanent_id* is CR 109.5's "**other** sources", which is an
    identity comparison and not a property of anything. Both are passed by the
    reader that knows them; neither is spelled into this file, because the name
    a card compares against is data it printed and this module dispatches on
    nothing.
    """
    if permanent_id is None:
        return 0
    total = 0
    for entry in ledger(game).entries:
        if entry.recipient_permanent_id != permanent_id:
            continue
        if source_name is not None and entry.source_name != source_name:
            continue
        if (
            exclude_source_permanent_id is not None
            and entry.source_permanent_id == exclude_source_permanent_id
        ):
            continue
        total += entry.amount
    return total


def damage_dealt_by_cast(game, item) -> int:
    """How much damage one *cast* dealt this turn (CR 109.5's per-cast source)."""
    if item is None:
        return 0
    return sum(
        entry.amount for entry in ledger(game).entries if entry.source_cast is item
    )


def cast_options(
    game, *, seat: int | None = None, card_type: str | None = None
) -> list[tuple[int, CastEntry]]:
    """The casts this turn with their ledger positions, narrowed.

    The position travels because a prompt's answer is JSON and cannot carry a
    ``StackItem``. Nothing is removed from the list within a turn, so a position
    means the same thing when the answer comes back as it did when the prompt
    was rendered.
    """
    return [
        (index, entry)
        for index, entry in enumerate(ledger(game).casts)
        if (seat is None or entry.seat == seat)
        and (
            card_type is None
            or getattr(entry.card, "primary_type", None) == card_type
        )
    ]


def casts_this_turn(game, *, seat: int | None = None, card_type: str | None = None):
    """The casts this turn, newest last, narrowed by caster and printed type."""
    return [entry for _index, entry in cast_options(game, seat=seat, card_type=card_type)]


def seats_that_cast(game, card_type: str) -> list[int]:
    """Every seat that cast one or more spells of *card_type* this turn."""
    seats: list[int] = []
    for entry in casts_this_turn(game, card_type=card_type):
        if entry.seat not in seats:
            seats.append(entry.seat)
    return seats


def cast_by_index(game, index: int):
    """The ledger's *index*-th cast, or None — how a prompt's answer names one.

    A prompt's answer travels as JSON, so it cannot carry the ``StackItem``
    itself; it carries the position in this list, which nothing removes from
    within a turn.
    """
    casts = ledger(game).casts
    if 0 <= index < len(casts):
        return casts[index]
    return None
