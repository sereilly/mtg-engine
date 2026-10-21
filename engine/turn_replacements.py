"""Replacement effects a **resolving spell** creates for the rest of the turn
(CR 614, CR 611.2a), as state.

    "If any source would deal 1 or more damage to a permanent or player this
    turn, it deals 2 damage to that permanent or player instead."
                                                        (Equal Treatment.)
    "Until end of turn, if target player would draw a card, instead that player
    skips that draw and you draw a card."                (Plagiarize.)
    "If a creature would deal combat damage to a creature this turn, it deals
    double that damage to that creature instead."        (Blind Fury.)

A static replacement (Furnace of Rath, Lich) reads its own printed line off the
battlefield at every event. These cannot: the spell that printed the line has
left the stack, so there is no line anywhere to read, and the effect has to be
**recorded** by the resolution that created it with a lifetime the cleanup step
ends (CR 514.2). That is the shape ``engine/shields.py`` (prevention),
``engine/damage_redirects.py`` (CR 614.9) and ``engine/land_mana_swaps.py``
(CR 106.12b) already have, and this module is the same shape a fourth time:

- the records hang off the **seat that controls the effect** (CR 109.5's "you"
  — the spell's controller), as an attribute rather than a ``PlayerState`` or
  ``Game`` field, so a new kind of record needs no new field;
- each carries its ``lifetime``, and :func:`clear_turn_replacements` is the one
  sweep that ends them, so a new kind needs no new clearing line either;
- the interceptors that *apply* them are registered in
  ``engine/replacements.py``, where every CR 614 effect goes and where CR 616.1
  orders them against everything else.

Blind Fury was the precedent and the shape this replaced: a dedicated
``Game.combat_damage_doubled_between_creatures`` list with its own clearing
line in the cleanup step, which a second and a third card would each have
copied. It is a record here now.

**What a record says** is a small closed set of facts, none of them a card
name:

- ``event`` — which event it watches: :data:`DAMAGE` (CR 120.4b, the damage
  *dealt*) or :data:`DRAW` (CR 121);
- for damage, the printed narrowings, each tested rather than dropped:
  ``combat_only``, ``source_creature``, ``recipient_creature``, and the
  printed floor ``at_least`` ("1 or more");
- for damage, what it becomes: ``multiplier`` ("double that damage") or
  ``becomes`` ("it deals 2 damage … instead");
- for a draw, ``affected_seat`` — whose draws it takes — and the controller
  draws instead (``seat``);
- ``key`` — the effect's identity, for CR 614.5 ("a replacement effect gets
  only one opportunity to affect an event or any modified events that may
  replace it"), which the draw seam carries as ``exclude_sources``.

**Purity.** Every reader here only reads; the interceptors decide and the draw
seam spends. Nothing is used up — these last the turn — so CR 616.1's counting
round can ask about them freely.

A third card of this kind adds a **field** if it prints a narrowing none of
these is (a source colour, "you control"), a value of ``event`` if it watches
an event neither of these is (a life gain: "if a player would gain life this
turn, …"), and an interceptor in ``engine/replacements.py`` for that event —
never a ``Game`` field or a cleanup line.
"""

from __future__ import annotations

from dataclasses import dataclass

from .shields import END_OF_TURN

#: The damage-dealt half of a damage event (CR 120.4b).
DAMAGE = "damage"
#: One draw (CR 121.2).
DRAW = "draw"


@dataclass
class TurnReplacement:
    """One replacement effect a resolution created, sitting on its controller.

    seat               -- the seat controlling the effect (CR 109.5's "you")
    event              -- DAMAGE or DRAW
    source_name        -- the card whose resolution created it, for the log
    key                -- this effect's identity (CR 614.5)
    combat_only        -- "would deal **combat** damage"
    source_creature    -- "if **a creature** would deal …"
    recipient_creature -- "… damage **to a creature**"
    at_least           -- "would deal **1 or more** damage"; 1 says nothing
    multiplier         -- "it deals **double** that damage instead"
    becomes            -- "it deals **2** damage … instead"
    affected_seat      -- whose draws a DRAW record takes
    lifetime           -- END_OF_TURN; :func:`clear_turn_replacements` ends it
    """

    seat: int
    event: str
    source_name: str | None = None
    key: str = ""
    combat_only: bool = False
    source_creature: bool = False
    recipient_creature: bool = False
    at_least: int = 1
    multiplier: int = 1
    becomes: int | None = None
    affected_seat: int | None = None
    lifetime: str = END_OF_TURN


#: Where the list hangs off a player, for ``engine/shields.py``'s reason: a
#: ``PlayerState`` carries it without learning what a turn replacement is.
_ATTR = "_turn_replacements"
#: How many records a seat has ever armed, so each ``key`` is unique within a
#: game and deterministic across a deep copy (the AI's rehearsals copy games).
_COUNT_ATTR = "_turn_replacements_armed"


def turn_replacements_on(player) -> list[TurnReplacement]:
    """The records *player* controls, created on first use."""
    records = getattr(player, _ATTR, None)
    if records is None:
        records = []
        setattr(player, _ATTR, records)
    return records


def arm_turn_replacement(game, record: TurnReplacement) -> TurnReplacement:
    """Put *record* on its controller's seat, give it its identity, and return
    it. Two resolutions arm two records: CR 614.5 makes each its own effect."""
    player = game.players[record.seat]
    armed = int(getattr(player, _COUNT_ATTR, 0)) + 1
    setattr(player, _COUNT_ATTR, armed)
    record.key = f"turn-replacement:{record.seat}:{armed}"
    turn_replacements_on(player).append(record)
    return record


def armed_turn_replacements(game, event: str) -> list[TurnReplacement]:
    """Every record watching *event*, in APNAP-independent seat order and, on
    each seat, the order they were armed. Pure.

    Read through ``getattr`` rather than :func:`turn_replacements_on`: every
    damage event and every draw asks this, and creating an empty list on every
    seat to answer "none" would be a write on the hot path.
    """
    return [
        record
        for player in game.players
        for record in (getattr(player, _ATTR, None) or ())
        if record.event == event
    ]


def clear_turn_replacements(player, lifetime: str | None = None) -> None:
    """Expire records whose duration has run out — the shape
    ``shields.clear_shields`` and ``damage_redirects.clear_redirects`` have, so
    the cleanup step's sweep stays one call."""
    records = getattr(player, _ATTR, None)
    if records:
        records[:] = [r for r in records if lifetime is not None and r.lifetime != lifetime]


def damage_record_answers(record: TurnReplacement, payload: dict) -> bool:
    """Whether a DAMAGE *record* answers to this damage event. Pure.

    Every printed narrowing is a test here: "combat" (a ping ability is not),
    "a creature" at either end (a Lightning Bolt is not a creature source, and
    a player is not a creature recipient), and the printed floor. CR 109.5
    makes a creature's own ability's source the permanent, which is why the
    source test is the object's type and the combat test the event's flag.
    """
    from .models import Permanent

    amount = int(payload.get("amount") or 0)
    if amount <= 0 or amount < record.at_least:
        return False
    if record.combat_only and not payload.get("combat"):
        return False
    if record.recipient_creature:
        recipient = payload.get("recipient")
        if not isinstance(recipient, Permanent) or not recipient.is_creature:
            return False
    if record.source_creature:
        source = payload.get("source")
        if not isinstance(source, Permanent) or not source.is_creature:
            return False
    return True
