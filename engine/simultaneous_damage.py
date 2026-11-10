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
2004-10-04). And **every spell or ability that deals damage to several
recipients at once** (CR 608.2f: "Some spells and abilities include actions
taken on multiple players and/or objects. In most cases, each such action is
processed simultaneously"): a sweep, a divided Fireball, "each of up to two
target creatures", "each opponent", "each player", The Fallen's opponents and
planeswalkers, Winter Blast's recorded creatures, Cuombajj Witches' two
halves, a fight's two (CR 701.14a), the bites — through :func:`deal_at_once`,
the one loop they share — and a printed sentence the lowering split into
several instructions ("…2 damage to any target **and** 3 damage to you",
Orcish Artillery; "…to target player **and** each creature that player
controls", Heart of Bogardan), whose ``sequence`` carries
``oracle_types.ONE_DEALING``. A non-combat dealing is joined only by the chunks
of the sources it names (:attr:`SimultaneousDamage.dealers`). Anything else is
a dealing of one chunk, announced whole as it is dealt.

**A split sentence is dealt as one loop over its chunks** (:func:`begin_sentence`,
:func:`deal_sentence`). CR 616.1's last sentence: "If two or more players have
to make these choices at the same time, choices are made in APNAP order (see
rule 101.4)" — and every chunk of one dealing is dealt at the same time, so
every affected player's questions about the whole sentence are asked before the
next player's. A sweep already deals its own recipients in APNAP order, but a
sentence of two sweeps, or of a sweep and a player, asked step by step — the
active player and then the other about Disorder's white creatures, and then
both again about themselves. So while a split sentence's steps run, the
dealing *collects* (:attr:`SimultaneousDamage.agenda`): each chunk that joins
it is recorded at the two damage seams (``Game._mark_damage_on_permanent``,
``Game._deal_damage_to_player``) with its recipient, instead of being dealt,
and each loop's last step (:func:`deal_at_once`'s *then*, a sweep's summary)
waits beside them. Once every step has run, the chunks are dealt in APNAP order
of the seat each one's question goes to — within one seat in the order the
steps produced them, the printed order (CR 101.4c) — then the loops' last
steps, then the finish. The recipient is the one the handler resolved, read at
the seam, so no second copy of what a step's recipient key means is kept here.

**What is not one dealing**, each with its reason: the combat damage step's
first-strike and regular passes (CR 510.4: two steps, two dealings); Mana
Clash's flips ("Each point of damage is dealt separately", its ruling,
2004-10-04); a modal spell's modes chosen twice (Fiery Confluence's ruling,
2015-11-04: "each of those modes represents a separate damage-dealing event");
and two printed sentences ("This creature deals damage … **.** That creature
deals damage …", Tracker — "Tracker will deal damage to itself equal to its
power, then immediately do it again", 2009-10-01).

**The dealing also carries the tallies a simultaneous event's results need**,
because they are facts about the same event and a redirected chunk never
reached a loop's closures: the life lifelink gains — once per *source* per
dealing (CR 702.15e: "If multiple sources with lifelink deal damage at the same
time, they cause separate life gain events"; Ajani's Pridemate's ruling,
2024-11-08: a single lifelinker dealing combat damage to several recipients at
once triggers it "only once", two lifelinkers twice) — and which creatures
dealt combat damage to each player (the batched "one or more … deal combat
damage to a player").

**Delayed damage triggers** (CR 603.7) read the same ends of the same event:
"whenever target creature deals damage" (Spiritualize) and "whenever that
creature deals combat damage this turn" (Vigorous Charge) name the source
alone; "whenever that creature is dealt damage by an attacking creature this
turn" (Glyph of Life) names the recipient, and its "that much" is only the
damage the sources it names dealt (CR 120.9); "whenever target creature deals
combat damage to a non-Wall creature this turn" (Acidic Dagger) names both
(:func:`delayed_occurrence`).

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
    return _reading_answers(occurrence(condition_payload), announced)


def _reading_answers(reading: str | None, announced: str | None) -> bool:
    if announced is None or reading is None:
        return True
    if announced == CHUNK:
        return reading == PAIR
    return announced == reading


#: The delayed damage events (CR 603.7, ``delayed_triggers.DELAYED_EVENTS``),
#: and which end of the event each is once per: (unnarrowed, narrowed by an
#: ``agent_filter``). The agent is the *other* end from the object the entry
#: watches, so on a "deals" event a narrowing names the recipient — "…deals
#: combat damage **to a non-Wall creature**" (Acidic Dagger) is both ends —
#: while on the "is dealt" event it names the sources, which CR 120.9 makes a
#: narrowing of what the total counts rather than a second end: "dealt damage
#: **by an attacking creature**" (Glyph of Life) is once per recipient for the
#: damage the attacking creatures dealt it.
DELAYED_DAMAGE_EVENTS: dict[str, tuple[str, str]] = {
    "bound_permanent_dealt_damage": (RECIPIENT, RECIPIENT),
    "bound_permanent_deals_damage": (SOURCE, PAIR),
    "bound_permanent_deals_combat_damage": (SOURCE, PAIR),
}


def delayed_occurrence(event: str, agent_filter) -> str | None:
    """Which end of a damage event a delayed entry armed for *event* is once
    per (:data:`DELAYED_DAMAGE_EVENTS`), or None for an event that is not a
    damage event."""
    row = DELAYED_DAMAGE_EVENTS.get(event)
    if row is None:
        return None
    return row[1] if agent_filter else row[0]


def delayed_answers(event: str, agent_filter, announced: str | None) -> bool:
    """Whether a delayed entry armed for *event* answers an announcement made
    under *announced* — :func:`answers`, for the entries ``emit`` never
    reaches."""
    return _reading_answers(delayed_occurrence(event, agent_filter), announced)


@dataclass(eq=False)
class _Tally:
    """One party's share of a dealing: who, how much, and the announcement
    payload of its first chunk, whose seat and identity keys the total reuses
    (CR 603.10: frozen as the chunk was dealt). *parts* is each chunk's other
    end and amount, in the order dealt — what a delayed trigger narrowed by
    that end counts (CR 120.9)."""

    party: Any
    amount: int = 0
    payload: dict = field(default_factory=dict)
    parts: list = field(default_factory=list)


@dataclass(eq=False)
class SimultaneousDamage:
    """One simultaneous dealing, from its first chunk to its finish.

    combat  -- the combat damage step's dealing (CR 510.2): every combat chunk
               joins. Otherwise one spell's or ability's, which only the
               chunks of its *dealers* join.
    dealers -- the non-combat dealing's sources, by identity: the one object
               a sweep or a divided spell deals as, or each biter of a bite;
               empty for the combat dealing.
    """

    combat: bool
    dealers: tuple = ()
    players: list[_Tally] = field(default_factory=list)
    creatures: list[_Tally] = field(default_factory=list)
    sources: list[_Tally] = field(default_factory=list)
    #: Each permanent a chunk was dealt to, with each chunk's source and
    #: amount (``_Tally.parts``) — the delayed "is dealt damage by <agent>"
    #: totals (Glyph of Life). The creature's own "is dealt damage" triggers
    #: are :attr:`creatures`, fed by the creature seam's fire site.
    damaged: list[_Tally] = field(default_factory=list)
    #: Each lifelink source's gain, in the order first dealt, with the seat it
    #: goes to in ``payload["seat"]`` — one life-gain event per source
    #: (CR 702.15e), gained as the dealing finishes.
    lifelink: list[_Tally] = field(default_factory=list)
    #: Damaged player's seat -> the creatures that dealt it combat damage, for
    #: the batched "one or more … deal combat damage to a player" triggers.
    damagers_by_defender: dict[int, list] = field(default_factory=dict)
    #: While a split damage sentence's steps run (:func:`begin_sentence`): each
    #: chunk that joins this dealing, as ``(recipient, deal)`` — *deal* is the
    #: damage seam's own call, made again once every step has run — in the
    #: order the steps produced them. None for every other dealing, and once
    #: :func:`deal_sentence` starts dealing them.
    agenda: list | None = None
    #: The last steps (*then*) of the loops that ran while :attr:`agenda` was
    #: collecting, run after the collected chunks have been dealt.
    closers: list = field(default_factory=list)
    #: CR 615.8: one instance of damage from a source is everything it deals
    #: in this dealing. Each source-keyed "next time" shield, redirect or
    #: mirror (``next_damage.DamageMirror``) spent on one of its chunks opened
    #: a ``shields.SharedNextTime`` here — and so did each recipient-keyed one
    #: (Glarecaster), whose time is the dealing too
    #: (``SharedNextTime.use`` appends it), open for that source's other
    #: chunks and closed as the dealing finishes.
    occasions: list = field(default_factory=list)
    #: The same rule for the riders a source carries
    #: (``engine/next_damage.py``, Desperate Gambit and Impulsive Maneuvers):
    #: each ``(source, key)`` whose rider this dealing has spent, which the
    #: source's other chunks carry without spending another.
    next_time_riders: list = field(default_factory=list)
    #: CR 615.5's "the rest of the effect takes place immediately afterward",
    #: for a source-keyed shield spent across this dealing's chunks: one entry
    #: per shield (``[shield, effect, first chunk's event, shields used,
    #: total prevented]``), run once, with the total, as the dealing finishes
    #: (Shadowbane's life, Honorable Passage's damage back).
    afterward: list = field(default_factory=list)

    def joins(self, *, combat: bool, source) -> bool:
        """Whether a chunk with this *combat* flag and *source* is part of
        this dealing."""
        if self.combat:
            return bool(combat)
        return (
            not combat and source is not None
            and any(source is dealer for dealer in self.dealers)
        )


def _tally(rows: list[_Tally], party, amount: int, payload: dict, part=None) -> None:
    for row in rows:
        if row.party is party:
            row.amount += amount
            if part is not None:
                row.parts.append(part)
            return
    rows.append(_Tally(
        party=party, amount=amount, payload=dict(payload),
        parts=[part] if part is not None else [],
    ))


def begin(game, *, combat: bool, source=None, sources=()) -> SimultaneousDamage | None:
    """Open a dealing by *source* (or each of *sources*), or None when one is
    already open (the chunks then join that one, and only its opener finishes
    it).

    A non-combat dealing opened inside another non-combat one is part of the
    same action — a split sentence's sweep half (Heart of Bogardan), a loop
    inside a sentence a ``sequence`` marks — so its sources join the open one.
    A non-combat loop inside the combat dealing does not: combat damage and
    the damage an effect deals are two events.

    A combat damage pass never starts inside another dealing — the previous
    pass finished its own, and nothing deals combat damage in between — so a
    dealing still open when one starts was abandoned part-way (a question
    nobody answered) and is dropped rather than joined: joined, it would hold
    this pass's triggers for a finish that never comes."""
    dealers = tuple(sources) + ((source,) if source is not None else ())
    open_dealing = getattr(game, "simultaneous_damage", None)
    if open_dealing is not None and not combat:
        if not open_dealing.combat:
            open_dealing.dealers += tuple(
                dealer for dealer in dealers
                if not any(dealer is known for known in open_dealing.dealers)
            )
        return None
    if open_dealing is not None:
        # Abandoned: whatever "next time" it opened is over with it, or the
        # records would stay neither open nor spent until the cleanup step.
        _close_occasions(game, open_dealing)
    dealing = SimultaneousDamage(combat=combat, dealers=() if combat else dealers)
    game.simultaneous_damage = dealing
    return dealing


def deal_at_once(
    game, items, step, *, source=None, sources=(), then=None, affected=None,
) -> None:
    """*step* each of *items* as **one** simultaneous dealing by *source* (or
    *sources*), and then run *then* — the loop every spell or ability that
    deals damage to several recipients at once runs (CR 608.2f).

    One resumable loop (``engine/resumption.py``): a step whose event stops to
    ask which effect applies first (CR 616.1e) takes the rest with it, and the
    dealing stays open across the answer — its finish is the loop's last step,
    before *then*. So, like every resumable loop, this must be the last thing
    its caller does.

    The items are dealt in APNAP order of the seat each one's question goes to
    (CR 616.1's last sentence, ``effect_ordering.in_apnap_order``; *affected*
    maps an item to its recipient where the item is something else).

    Inside a split sentence still collecting (:func:`begin_sentence`) the loop
    runs as ever, but each item's chunk is collected at the damage seam rather
    than dealt, so *then* waits with them (:attr:`SimultaneousDamage.closers`)
    instead of reporting damage not dealt yet."""
    from .effect_ordering import in_apnap_order
    from .resumption import run_resumable

    dealing = begin(game, combat=False, source=source, sources=sources)
    held = game.simultaneous_damage if dealing is None else None
    if then is not None and held is not None and held.agenda is not None:
        held.closers.append(then)
        then = None

    def last() -> None:
        finish(game, dealing)
        if then is not None:
            then()

    run_resumable(
        game, in_apnap_order(game, items, affected=affected), step, then=last,
    )


def begin_sentence(game, *, source) -> SimultaneousDamage | None:
    """Open the dealing of one split damage sentence by *source* (a
    ``sequence`` marked ``oracle_types.ONE_DEALING``), collecting its chunks
    until :func:`deal_sentence` — or None when a dealing is already open: the
    sentence's chunks then join that one, collected there if it is collecting
    (and dealt by its opener), otherwise dealt as each step reaches them. No
    road to that is known — a split sentence resolves from the stack or an
    activation, after any dealing that fired it has finished — so the last
    branch is a fallback that keeps the damage, not an ordering anyone gets."""
    dealing = begin(game, combat=False, source=source)
    if dealing is not None:
        dealing.agenda = []
    return dealing


def collect(game, recipient, deal, *, combat: bool, source) -> bool:
    """Record a chunk for its split sentence's one APNAP-ordered loop instead
    of dealing it: True when the open dealing is collecting
    (:func:`begin_sentence`) and the chunk joins it, and then the caller — one
    of the two damage seams — returns at once, as it does for an event that
    stopped to ask (nothing has happened; *deal* is the call made again, its
    ``then`` with it). False: deal it now."""
    dealing = joined(game, combat=combat, source=source)
    if dealing is None or dealing.agenda is None:
        return False
    dealing.agenda.append((recipient, deal))
    return True


def deal_sentence(game, dealing: SimultaneousDamage | None) -> None:
    """Deal a split sentence's collected chunks as one resumable loop, in APNAP
    order of the seat each one's CR 616.1 question goes to (CR 616.1's last
    sentence, 101.4) — the printed order within a seat (CR 101.4c) — then the
    last steps of the loops that collected them, then finish the dealing.

    The last step of the sentence's own loop (``control_flow.sequence``), so,
    like every resumable loop, the last thing its caller does: a chunk whose
    event stops to ask takes the chunks behind it with it, and the dealing
    stays open across the answer. *dealing* None — the sentence joined one
    already open — does nothing."""
    from .effect_ordering import in_apnap_order
    from .resumption import run_resumable

    if dealing is None:
        return
    chunks, dealing.agenda = dealing.agenda or [], None
    closers, dealing.closers = dealing.closers, []
    ordered = in_apnap_order(game, chunks, affected=lambda chunk: chunk[0])
    run_resumable(
        game, [deal for _recipient, deal in ordered] + closers,
        lambda step: step(), then=lambda: finish(game, dealing),
    )


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
    elif isinstance(recipient, Permanent):
        _tally(dealing.damaged, recipient, dealt, {}, part=(source, dealt))
    if source is not None:
        _tally(
            dealing.sources, source, dealt, payload,
            part=(recipient if isinstance(recipient, Permanent) else None, dealt),
        )


def record_creature(dealing: SimultaneousDamage, permanent, dealt: int) -> None:
    """A permanent's share, for its "is dealt damage" triggers at the finish."""
    if dealt > 0:
        _tally(dealing.creatures, permanent, dealt, {})


def record_lifelink(
    dealing: SimultaneousDamage, source, seat: int | None, gained: int,
) -> None:
    """*source*'s lifelink gain for one chunk, gained once for the source's
    total as the dealing finishes (CR 702.15e)."""
    if gained > 0 and isinstance(seat, int):
        _tally(dealing.lifelink, source, gained, {"seat": seat})


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
    # CR 615.8: the instance each source-keyed "next time" was spent on is
    # over — its source's next damage is dealt normally.
    _close_occasions(game, dealing)
    from .delayed_triggers import fire_delayed_totals
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
    # The delayed abilities watching one end (CR 603.7), which ``emit`` cannot
    # reach: each permanent's total from the sources an entry names (Glyph of
    # Life, CR 120.9), then each permanent source's total (Spiritualize; and,
    # in the combat dealing, Vigorous Charge).
    for row in dealing.damaged:
        fire_delayed_totals(
            game, "bound_permanent_dealt_damage", subject=row.party,
            parts=[
                (source if isinstance(source, Permanent) else None, dealt)
                for source, dealt in row.parts
            ],
            occurrence=RECIPIENT,
        )
    for row in dealing.sources:
        if not isinstance(row.party, Permanent):
            continue
        events = ("bound_permanent_deals_damage",) + (
            ("bound_permanent_deals_combat_damage",) if combat else ()
        )
        for event in events:
            fire_delayed_totals(
                game, event, subject=row.party, parts=row.parts,
                occurrence=SOURCE,
            )
    if dealing.damagers_by_defender:
        game._fire_batched_combat_damage_triggers(dealing.damagers_by_defender)
    # CR 702.15b, after the damage: one life-gain event per lifelink source
    # (CR 702.15e), in APNAP order of the gaining seats and, within a seat, in
    # the order the sources first dealt.
    by_seat: dict[int, list[_Tally]] = {}
    for row in dealing.lifelink:
        by_seat.setdefault(row.payload["seat"], []).append(row)
    for seat in game.apnap_seats(by_seat, include_lost=True):
        for row in by_seat[seat]:
            game._gain_life(game.players[seat], row.amount, source_name="lifelink")
    # CR 615.5, after the damage: each source-keyed shield's additional effect
    # once, for everything it prevented in this dealing (one instance,
    # CR 615.8), in the order the shields were first spent.
    for _shield, effect, event, used, prevented in dealing.afterward:
        effect(game, event, used, prevented)


def defer_afterward(dealing: SimultaneousDamage, shield, effect, event, used, prevented: int) -> None:
    """Hold a source-keyed shield's CR 615.5 additional effect for the end of
    *dealing*, adding *prevented* to what it has already prevented there."""
    for entry in dealing.afterward:
        if entry[0] is shield and entry[1] is effect:
            entry[4] += prevented
            return
    dealing.afterward.append([shield, effect, dict(event), list(used), prevented])


def _close_occasions(game, dealing: SimultaneousDamage) -> None:
    """Close every "next time" occasion *dealing* opened, and forget the
    records that are spent by it."""
    if not dealing.occasions:
        return
    for occasion in dealing.occasions:
        occasion.closed = True
    dealing.occasions = []
    from . import damage_redirects, next_damage, shields

    for holder in (*game.players, *game.all_permanents()):
        shields.drop_spent(holder)
        damage_redirects.drop_spent(holder)
        next_damage.drop_spent_mirrors(holder)
