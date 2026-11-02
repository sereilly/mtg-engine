"""Damage several sources deal at once is **one** event (CR 603.2c, CR 510.2).

"All combat damage that's been assigned is dealt simultaneously" (CR 510.2),
and "an ability triggers only once each time its trigger event occurs" (CR
603.2c) — so a creature blocked by two creatures is dealt damage once, for the
total, and a trampler that hits its blocker and the defending player deals
damage once. ``engine/damage_events.deal_damage`` runs one event per chunk —
one source, one recipient — because that is the unit CR 120.4 and CR 616.1
process: each chunk has its own shields, its own redirects and its own
affected player to ask. What it cannot see from inside one chunk is which
other chunks it was dealt *with*. This module is that: a record of one
simultaneous dealing, opened by whatever deals damage at once and finished
when the last chunk has been dealt, which the triggers that read the event
whole are announced from.

**Which triggers read the event whole is the printed sentence's**, by the ends
of the event it names:

* **The recipient alone** — "whenever this creature is dealt damage", "whenever
  you're dealt damage" (:data:`RECIPIENT`). Once per recipient, for the total
  every source dealt it. Fungusaur's ruling (2004-10-04): "If more than one
  creature damages it at one time, it only gets one counter"; Boros
  Reckoner's (2017-03-14): "dealt damage by multiple sources at once, such as
  by two creatures blocking it, its ability triggers once and one target is
  dealt that much damage"; Sporeweb Weaver's, Wrathful Raptors' and Vengeful
  Pharaoh's ("If multiple creatures deal combat damage to you simultaneously,
  Vengeful Pharaoh will only trigger once") say the same. Several recipients
  are several occurrences: "If Wrathful Raptors and one or more other
  Dinosaurs you control are dealt damage at the same time, Wrathful Raptors's
  ability triggers for itself and for each of those Dinosaurs".
* **The source alone** — "whenever this creature deals damage", "whenever a
  red creature or spell deals damage" (:data:`SOURCE`). Once per source, for
  the total it dealt to every recipient. Drinker of Sorrow's ruling
  (2004-10-04): "You only sacrifice one permanent, no matter how many things
  it deals damage to"; Justice's: "If a single source does damage to multiple
  targets at once, Justice will add up all the damage done and deal damage to
  the source's controller at one time (not multiple separate damagings)".
* **Both ends** — "whenever this creature deals damage to a player", "whenever
  a source deals damage to this creature" (:data:`PAIR`). Once per chunk,
  which is exactly what each ``deal_damage`` already announces: Pain
  Magnification's ruling has a source dealing 3 to two opponents at once
  trigger "once for each of those opponents", and Vengeful Pharaoh's has
  damage to you and to a planeswalker trigger twice.

So a chunk dealt inside a dealing is still announced as it is dealt — for the
pair-keyed triggers — marked :data:`CHUNK`, which the recipient- and
source-keyed ones decline; and the dealing announces each recipient's and each
source's total once, as it finishes.

**Who opens a dealing.** The combat damage step, once per strike pass (CR 510.2,
510.4), for every combat chunk — a redirected one included, since damage
redirected during combat is still combat damage (Wall of Souls' ruling,
2004-10-04). And a sweep (``handlers/damage_sweeps._sweep``): one source dealing
damage to each member of a set at once, for that source's chunks. Anything
else is a dealing of one chunk, announced whole as it is dealt.

**The combat dealing also carries the two tallies the step used to keep in its
own closures**, because they are facts about the same simultaneous event and a
redirected chunk never reached the step's closures: the life lifelink gains
(CR 702.15b, gained once the damage is dealt — CR 510.2's one life-gain event
per controller) and which creatures dealt combat damage to each player (the
batched "one or more … deal combat damage to a player").

``Game.simultaneous_damage`` is None outside a dealing — bookkeeping to every
``vars()`` walker, since nothing is ever left open across a priority window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Permanent, PlayerState

#: A damage trigger that reads the event from the recipient's side: "whenever
#: <recipient> is dealt damage". Also the value a recipient's total is
#: announced under (``occurrence`` on the ``damage_dealt`` payload).
RECIPIENT = "recipient"
#: …from the source's side, naming no recipient: "whenever <source> deals
#: damage". Also the value a source's total is announced under.
SOURCE = "source"
#: …naming both ends: "whenever <source> deals damage to <recipient>".
PAIR = "pair"
#: The ``occurrence`` a chunk dealt inside a dealing is announced under: only
#: a :data:`PAIR` trigger answers it, the others answering the totals.
CHUNK = "chunk"

#: The ``damage_dealt`` condition payload keys that name the event's
#: recipient — the "to <recipient>" half of the active row, and the passive
#: row's seat. A condition carrying none of them names its source alone.
_RECIPIENT_KEYS = (
    "damage_recipient", "damaged_self", "damaged_filter",
    "damage_recipient_seat", "damage_recipient_seat_after",
)
#: The passive row's marker: "whenever you're dealt damage" names no source at
#: all (``whenever_triggers``), which is what makes it read from the
#: recipient's side even though ``damage_recipient`` is a recipient key.
RECEIVED_MARKER = "damage_received"


def occurrence(condition_payload: dict) -> str:
    """Which end of the event a ``damage_dealt`` condition is once per —
    :data:`RECIPIENT`, :data:`SOURCE` or :data:`PAIR` — from its printed
    words alone (this module's docstring)."""
    if RECEIVED_MARKER in condition_payload:
        return RECIPIENT
    if any(key in condition_payload for key in _RECIPIENT_KEYS):
        return PAIR
    return SOURCE


def answers(condition_payload: dict, announced: str | None) -> bool:
    """Whether a ``damage_dealt`` trigger with *condition_payload* answers an
    announcement made under *announced* (``None``: a chunk dealt alone, which
    is the whole event and so every trigger's)."""
    if announced is None:
        return True
    reading = occurrence(condition_payload)
    if announced == CHUNK:
        return reading == PAIR
    return announced == reading


@dataclass(eq=False)
class _Tally:
    """One party's share of a dealing: who, how much, and the announcement
    payload of its first chunk, whose seat and identity keys the total reuses
    (CR 603.10: frozen as the chunk was dealt)."""

    party: Any
    amount: int = 0
    payload: dict = field(default_factory=dict)


@dataclass(eq=False)
class SimultaneousDamage:
    """One simultaneous dealing, from its first chunk to its finish.

    combat  -- the combat damage step's dealing (CR 510.2): every combat chunk
               joins. Otherwise a sweep's, which only its *source*'s chunks join.
    source  -- the sweep's one source; None for the combat dealing.
    """

    combat: bool
    source: Any = None
    players: list[_Tally] = field(default_factory=list)
    creatures: list[_Tally] = field(default_factory=list)
    sources: list[_Tally] = field(default_factory=list)
    #: Seat -> life its lifelink sources gain, in the order first dealt
    #: (CR 702.15b); combat only — elsewhere lifelink is gained as dealt.
    lifelink: dict[int, int] = field(default_factory=dict)
    #: Damaged player's seat -> the creatures that dealt it combat damage, for
    #: the batched "one or more … deal combat damage to a player" triggers.
    damagers_by_defender: dict[int, list] = field(default_factory=dict)

    def joins(self, *, combat: bool, source) -> bool:
        """Whether a chunk with this *combat* flag and *source* is part of
        this dealing."""
        if self.combat:
            return bool(combat)
        return not combat and source is not None and source is self.source


def _tally(rows: list[_Tally], party, amount: int, payload: dict) -> None:
    for row in rows:
        if row.party is party:
            row.amount += amount
            return
    rows.append(_Tally(party=party, amount=amount, payload=dict(payload)))


def begin(game, *, combat: bool, source=None) -> SimultaneousDamage | None:
    """Open a dealing, or None when one is already open (the chunks then join
    that one, and only its opener finishes it).

    A combat damage pass never starts inside another dealing — the previous
    pass finished its own, and nothing deals combat damage in between — so a
    dealing still open when one starts was abandoned part-way (a question
    nobody answered) and is dropped rather than joined: joined, it would hold
    this pass's triggers for a finish that never comes."""
    if getattr(game, "simultaneous_damage", None) is not None and not combat:
        return None
    dealing = SimultaneousDamage(combat=combat, source=source)
    game.simultaneous_damage = dealing
    return dealing


def joined(game, *, combat: bool, source) -> SimultaneousDamage | None:
    """The open dealing a chunk with this *combat* flag and *source* is part
    of, or None when it is a dealing of its own."""
    dealing = getattr(game, "simultaneous_damage", None)
    if dealing is None or not dealing.joins(combat=combat, source=source):
        return None
    return dealing


def record_chunk(dealing: SimultaneousDamage, payload: dict, dealt: int) -> None:
    """One chunk's share of the totals, from its ``damage_dealt`` payload.

    The recipient's total is kept for a **player** only: a permanent's
    recipient-side triggers are ``creature_dealt_damage``, which arrive
    through :func:`record_creature` from the creature seam's own fire site.
    """
    if dealt <= 0:
        return
    recipient = payload.get("recipient")
    source = payload.get("subject")
    if isinstance(recipient, PlayerState):
        _tally(dealing.players, recipient, dealt, payload)
    if source is not None:
        _tally(dealing.sources, source, dealt, payload)


def record_creature(dealing: SimultaneousDamage, permanent, dealt: int) -> None:
    """A permanent's share, for its "is dealt damage" triggers at the finish."""
    if dealt > 0:
        _tally(dealing.creatures, permanent, dealt, {})


def record_lifelink(dealing: SimultaneousDamage, seat: int | None, gained: int) -> None:
    if gained > 0 and isinstance(seat, int):
        dealing.lifelink[seat] = dealing.lifelink.get(seat, 0) + gained


def record_combat_damager(dealing: SimultaneousDamage, defender_seat: int, source) -> None:
    if isinstance(source, Permanent):
        dealing.damagers_by_defender.setdefault(defender_seat, []).append(source)


def finish(game, dealing: SimultaneousDamage | None) -> None:
    """Close *dealing* and announce what it held: each recipient's total and
    each source's total once (this module's docstring), then the combat
    dealing's batched triggers and its lifelink.

    A *dealing* of None — one that joined an already open dealing — does
    nothing: the opener finishes it.
    """
    if dealing is None or getattr(game, "simultaneous_damage", None) is not dealing:
        return
    game.simultaneous_damage = None
    from .events import emit

    combat = dealing.combat
    for row in dealing.creatures:
        game._announce_dealt_damage_triggers(row.party, row.amount, combat=combat)
    for row in dealing.players:
        emit(
            game, "damage_dealt",
            subject=None, amount=row.amount, combat=combat,
            recipient=row.party,
            defending_player_index=row.payload.get("defending_player_index"),
            occurrence=RECIPIENT,
        )
    for row in dealing.sources:
        payload = {
            key: row.payload[key]
            for key in (
                "damager_seat", "event_subject_controller",
                "event_subject_permanent_id", "damager_is_spell",
            )
            if key in row.payload
        }
        emit(
            game, "damage_dealt",
            subject=row.party, amount=row.amount, combat=combat,
            recipient=None, occurrence=SOURCE, **payload,
        )
    if dealing.damagers_by_defender:
        game._fire_batched_combat_damage_triggers(dealing.damagers_by_defender)
    # CR 702.15b, after the damage (CR 510.2: one life-gain event per
    # controller), in APNAP order of the gaining seats.
    for seat in game.apnap_seats(dealing.lifelink, include_lost=True):
        game._gain_life(game.players[seat], dealing.lifelink[seat], source_name="lifelink")
