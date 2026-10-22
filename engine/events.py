"""Game event bus for triggered abilities.

Before this, a triggered ability only fired if some piece of engine code
explicitly went looking for it: twenty-three hand-placed
``iter_triggered_abilities(condition_kinds={...})`` scans spread across the
phase modules and mixins. That has two consequences at scale.

The first is that support is invisible from the card's side. The oracle
compiler recognizes trigger conditions it has no dispatcher for — ``spell_cast``,
``creature_enters``, ``artifact_enters``, ``draws_card`` and others parsed
happily and then never fired, so cards needing them got routed to a name-keyed
hook in ``card_hooks.py`` instead. Six cards were name-keyed for cast triggers
the parser already understood. (Two of those examples are gone rather than
fixed: nothing in the pool printed the bare "whenever a creature/artifact
enters", and the narrowed form every real card *does* print now fires through
``matching_permanent_enters``. A row with no dispatcher and no card is the
failure this module is about, in its quietest form.)

The second is that adding a trigger condition means finding or creating a fire
site rather than adding a registry row — the opposite of how the rest of the
engine grows.

This module inverts that: game code announces *what happened*
(``emit(game, "spell_cast", ...)``) and every permanent whose compiled trigger
matches is enqueued, in APNAP order, by the existing stack machinery. Trigger
conditions keep the kind strings the compiler already produces, so a fire site
converts to an ``emit`` without touching the cards.

Whether one permanent's trigger answers one event is the second question, and
it is asked per kind by a predicate registered with :func:`event_filter`
("whenever a player casts a *blue* spell" needs the spell's colours). Those
predicates are most of the vocabulary and live beside this module, one family
each: ``cast_event_filters`` (a spell cast, a card played) and
``event_filters`` (every other kind). They are imported at the bottom of this
one, so importing the bus is what fills :data:`EVENT_FILTERS`. What stays here
is the bus — the event, the registry, the zone scans, ``collect`` and
``emit`` — and the readers both the filters and the fire sites ask:
:func:`trigger_subject_matches`, :func:`destroyed_trigger_applies`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from .subject_filters import subject_matches
from .trigger_utils import iter_triggered_abilities, make_trigger_event

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent, PlayerState
    from .oracle_types import ParsedTriggeredAbility


@dataclass(frozen=True)
class Event:
    """Something that happened in the game.

    ``kind`` is the trigger-condition vocabulary the oracle compiler emits
    ("creature_dies", "spell_cast", "upkeep_self", …). ``payload`` carries the
    event's details through to the trigger's handler as ``trigger_context``.
    """

    kind: str
    payload: dict = field(default_factory=dict)
    # The object the event is about (the spell cast, the creature that died).
    subject: object | None = None
    # Restrict which players' permanents are scanned. None means every player.
    players: "Iterable[PlayerState] | None" = None


# A predicate deciding whether one permanent's trigger actually applies to an
# event — "whenever a player casts a *blue* spell" needs the spell's colors.
# Registered per condition kind; kinds with no filter always fire.
EventFilter = Callable[["Game", "Permanent", "ParsedTriggeredAbility", Event], bool]

EVENT_FILTERS: dict[str, EventFilter] = {}


def event_filter(*kinds: str) -> Callable[[EventFilter], EventFilter]:
    """Register a per-kind applicability predicate."""

    def decorator(fn: EventFilter) -> EventFilter:
        for kind in kinds:
            if kind in EVENT_FILTERS:
                raise ValueError(f"duplicate event filter for {kind!r}")
            EVENT_FILTERS[kind] = fn
        return fn

    return decorator


def emblem_trigger_events(game: Game, kind: str, players=None) -> list[dict]:
    """Every emblem-borne trigger matching *kind*, as enqueueable event dicts.

    Emblems function from the command zone (CR 114.4), so no battlefield scan
    can find them — every site that collects a condition's triggers over
    permanents asks this beside it. The emblem's detached Permanent stands in
    as the source, so the stack item and the resolution context read it like
    any other trigger's.
    """
    from .line_classification import compile_emblem_text

    events: list[dict] = []
    for seat, player in enumerate(game.players):
        if players is not None and not any(p is player for p in players):
            continue
        for emblem in getattr(player, "emblems", ()):
            for trig in compile_emblem_text(emblem["name"], emblem["oracle_text"]):
                if not trig.supported or trig.condition.kind != kind:
                    continue
                events.append(make_trigger_event(seat, emblem.get("_permanent"), trig))
    return events


#: The payload key an instruction carries when its effect moves the ability's
#: own source out of a zone, and therefore the zone the ability *functions* from
#: (CR 113.6m — whose own example is "Return this card from your graveyard to the
#: battlefield tapped"). Stamped by the lowering from the zone the sentence
#: names, so no card name and no list of instruction kinds decides which
#: abilities work from a graveyard: the sentence does.
FUNCTIONS_FROM = "functions_from"


def _functions_from(trig, zone: str) -> bool:
    """Whether *trig*'s effect declares it functions from *zone*."""
    instruction = trig.instruction
    if instruction is None:
        return False
    return (instruction.payload or {}).get(FUNCTIONS_FROM) == zone


def graveyard_trigger_events(game: Game, kind: str, players=None) -> list[dict]:
    """Every graveyard-resident trigger matching *kind*, as enqueueable event dicts.

    The third zone a trigger can fire from, after the battlefield
    (``iter_triggered_abilities``) and the command zone
    (:func:`emblem_trigger_events`) — and narrow on purpose. CR 113.6 says an
    object's abilities function only on the battlefield *unless* the ability says
    otherwise, so scanning every graveyard card's triggers would fire abilities
    that do not function there at all. The gate is CR 113.6m read off the
    compiled effect: the ability functions in the graveyard exactly when what it
    does is move its own source out of one.

    A graveyard card is not a permanent and gets no stand-in for one. It rides
    the event as ``card``, which ``_enqueue_triggered_ability`` already accepts
    beside ``source_permanent`` — so the stack item names the card and the
    resolution context has ``source_permanent=None``, which is the truth. An
    emblem needs its detached ``Permanent`` because CR 114 gives it one; a card
    in a graveyard is a card.

    The seat is the graveyard's **owner** (CR 108.4a: the controller of a card
    that has none is its owner), which is what "**your** end step" means for a
    card nobody controls.
    """
    from .trigger_utils import matching_triggers

    events: list[dict] = []
    for seat, player in enumerate(game.players):
        if players is not None and not any(p is player for p in players):
            continue
        for card in list(player.graveyard):
            for trig in matching_triggers(card, condition_kinds={kind}):
                if not _functions_from(trig, "graveyard"):
                    continue
                events.append({
                    "controller_index": seat,
                    "source_permanent": None,
                    "card": card,
                    "instruction": trig.instruction,
                    "effect_kind": trig.effect_kind,
                    "ability_text": trig.source_line,
                })
    return events


#: Trigger conditions that fire **from the stack**, about the object being cast
#: (CR 603.6d, CR 113.6a). A condition rather than a ``FUNCTIONS_FROM`` stamp,
#: because here the condition *is* the claim: "when you cast this spell" can
#: only ever be about the object being cast, so there is nothing for a card to
#: declare and nothing for a second reader to disagree with.
_STACK_CAST_CONDITIONS: frozenset[str] = frozenset({"self_cast"})


def cast_trigger_events(game: Game, event: Event) -> list[dict]:
    """The cast object's own triggers matching *event*, as enqueueable dicts.

    The fourth zone a trigger can fire from, after the battlefield, the command
    zone and a graveyard — and the one where the object is not a permanent at
    all. CR 603.6d: an ability that triggers on its own object being cast
    triggers from the stack, and only for that object; CR 113.6a is why no
    battlefield scan can answer it, and ``_self_cast_filter`` below is why one
    does not try.

    The seat is the caster's (CR 109.5), and the card rides the event as
    ``card`` for :func:`graveyard_trigger_events`'s reason: a spell on the
    stack is a card, not a permanent, and giving it a stand-in permanent would
    be inventing an object the game does not have.
    """
    if event.kind not in _STACK_CAST_CONDITIONS:
        return []
    from .trigger_utils import matching_triggers

    card = event.payload.get("cast_card")
    seat = event.payload.get("caster_index")
    if card is None or not isinstance(seat, int):
        return []
    return [
        {
            "controller_index": seat,
            "source_permanent": None,
            "card": card,
            "instruction": trig.instruction,
            "effect_kind": trig.effect_kind,
            "ability_text": trig.source_line,
            "trigger_context": dict(event.payload) or None,
        }
        for trig in matching_triggers(card, condition_kinds={event.kind})
        if trig.instruction is not None
    ]


#: Trigger conditions that fire about **the card that just moved**, from
#: wherever it landed (CR 113.6k: a trigger condition that cannot trigger from
#: the battlefield functions in every zone it can trigger from). A condition
#: rather than a ``FUNCTIONS_FROM`` stamp, for ``_STACK_CAST_CONDITIONS``'
#: reason: "when **this card** is put into your graveyard from your library"
#: (Gaea's Blessing) can only ever be about the object that moved, so there is
#: nothing for a card to declare and nothing for a second reader to disagree
#: with.
#: Keyed by **event kind**, because the two are not always the same word. A
#: card whose condition names a move nothing else watches announces itself under
#: a kind of its own (``self_put_into_graveyard_from_library``); where a
#: board-wide condition already announces the same move, the moved card rides
#: that one announcement rather than a second — Serra Avatar's "when this
#: creature is put into a graveyard **from anywhere**" and Planar Void's
#: "whenever another card is put into a graveyard from anywhere" are one event
#: asked from two places, and two emits would split one move's triggers across
#: two batches where CR 603.3b puts simultaneous triggers on together.
_MOVED_CARD_CONDITIONS: dict[str, frozenset[str]] = {
    "self_put_into_graveyard_from_library": frozenset(
        {"self_put_into_graveyard_from_library"}
    ),
    "card_put_into_graveyard": frozenset(
        {"self_put_into_graveyard_from_anywhere"}
    ),
}


def moved_card_trigger_events(game: Game, event: Event) -> list[dict]:
    """The moved card's own triggers matching *event*, as enqueueable dicts.

    The fifth fire site, and the one scoped to a **single object** rather than
    to a zone. ``graveyard_trigger_events`` beside it scans every graveyard,
    which is the wrong shape here twice over: a second copy of Gaea's Blessing
    already lying in the pile would fire for a card that never moved, and the
    scan cannot see a card the event sent somewhere other than a graveyard at
    all.

    The seat is the card's **owner** — CR 404.1 files a card in its owner's
    graveyard and CR 108.4a makes the controller of a card that has none its
    owner, so "shuffle **your** graveyard into **your** library" is that
    player's.
    """
    conditions = _MOVED_CARD_CONDITIONS.get(event.kind)
    if conditions is None:
        return []
    from .trigger_utils import matching_triggers

    card = event.subject
    seat = event.payload.get("owner_index")
    if card is None or not isinstance(seat, int):
        return []
    return [
        {
            "controller_index": seat,
            "source_permanent": None,
            "card": card,
            "instruction": trig.instruction,
            "effect_kind": trig.effect_kind,
            "ability_text": trig.source_line,
            "trigger_context": dict(event.payload) or None,
        }
        for trig in matching_triggers(card, condition_kinds=conditions)
        if trig.instruction is not None
    ]


def collect(game: Game, event: Event) -> list[dict]:
    """Every trigger that fires for *event*, as enqueueable event dicts.

    Separate from :func:`emit` so callers that need to inspect or augment the
    batch before it goes on the stack can, and so this is testable without a
    stack.
    """
    predicate = EVENT_FILTERS.get(event.kind)
    events: list[dict] = []
    for controller_index, permanent, trig in iter_triggered_abilities(
        game,
        condition_kinds={event.kind},
        players=list(event.players) if event.players is not None else None,
        first_match_only=False,
    ):
        # A permanent never triggers off its own departure-style events unless
        # the event says so; the subject check keeps "whenever a creature dies"
        # from firing on the dying creature itself where that is not intended.
        if event.subject is permanent and not event.payload.get("include_subject", True):
            continue
        if predicate is not None and not predicate(game, permanent, trig, event):
            continue
        enqueued = make_trigger_event(
            controller_index,
            permanent,
            trig,
            trigger_context=dict(event.payload) or None,
        )
        # The object the event was **about**, promoted from the payload onto the
        # stack item. A trigger that acts on it ("destroy that planeswalker")
        # reads it from there rather than from the trigger context, and it is
        # carried by id because an index is not an identity (CR 400.7). Done
        # here rather than at each announcement: the two fire sites that used to
        # stamp it did so by hand, and a third would have had to remember.
        for key in ("target_permanent_id", "target_player_index"):
            bound = event.payload.get(key)
            if bound is not None:
                enqueued[key] = bound
        events.append(enqueued)
    # An emblem's ability fires from the command zone (CR 114.4) — collected
    # beside the permanents', through the same event, so APNAP ordering and
    # the enqueue path treat both alike.
    scoped = list(event.players) if event.players is not None else None
    events.extend(emblem_trigger_events(game, event.kind, scoped))
    # And from a graveyard (CR 113.6m), for the same reason: no battlefield scan
    # can find a card that is not on one.
    events.extend(graveyard_trigger_events(game, event.kind, scoped))
    # And from the stack, for the object being cast (CR 603.6d). Beside the
    # other two rather than at the cast site, so APNAP ordering and the enqueue
    # path treat every zone's triggers alike.
    events.extend(cast_trigger_events(game, event))
    # And about one card that just changed zones, wherever it landed
    # (CR 113.6k). Beside the other three for their reason, and *after* the
    # graveyard scan so a card that both resides in a graveyard and just
    # arrived in one is still collected once per matching condition.
    events.extend(moved_card_trigger_events(game, event))
    return events


def emit(game: Game, kind: str, /, **payload) -> int:
    """Announce an event and put every matching trigger on the stack.

    Returns how many triggers fired. Ordering is APNAP (CR 603.3b), handled by
    ``_enqueue_triggered_batch``.
    """
    subject = payload.pop("subject", None)
    players = payload.pop("players", None)
    event = Event(kind=kind, payload=payload, subject=subject, players=players)
    events = collect(game, event)
    if events:
        game._enqueue_triggered_batch(events)
    return len(events)


def destroyed_trigger_applies(
    game: Game,
    observer: Permanent,
    observer_seat: int | None,
    trig: ParsedTriggeredAbility,
    event: Event,
) -> bool:
    """"Whenever a spell or ability an opponent controls destroys a noncreature
    permanent you control" (Karmic Justice) — CR 701.8's event, asked for one
    watching ability.

    Two narrowings, and the condition's payload names both:

    * ``destroyed_cause`` — **whose** spell or ability did it. The event
      carries the seat (``cause_seat``) or None, and None is an answer: lethal
      damage destroys a creature and no spell or ability did (CR 704.5g),
      whoever dealt the damage. "An opponent" is every seat but the watcher's
      own (CR 102.2, CR 102.3). A cause word this does not know refuses, which
      is the direction a trigger must fail in.
    * ``destroyed_filter`` — **what** was destroyed, through the one matcher
      every printed noun phrase is read by. Asked while the permanent is still
      on its battlefield (CR 603.10a): its types are layer 4's, so a land an
      effect animated is a creature at the moment it is destroyed.

    *observer_seat* is passed rather than read off the board, and that is the
    reason this is a function apart from the registered filter
    (``event_filters._permanent_destroyed_filter``): a watcher destroyed
    earlier in the same simultaneous event still sees the rest of it
    (CR 603.10a), and it has no controller to ask by then
    (``destruction_events.DestructionLedger.departed``).
    """
    if observer_seat is None:
        return False
    payload = trig.condition.payload
    cause = payload.get("destroyed_cause")
    if cause is not None:
        causer = event.payload.get("cause_seat")
        if not isinstance(causer, int):
            return False
        if cause != "an opponent" or causer == observer_seat:
            return False
    return subject_matches(
        game,
        event.subject,
        payload.get("destroyed_filter"),
        observer=observer_seat,
        source=observer,
    )


def trigger_subject_matches(
    game: Game,
    trig: ParsedTriggeredAbility,
    key: str,
    obj: Permanent | None,
    *,
    observer: int | None,
    source: Permanent | None = None,
) -> bool:
    """Whether *obj* is in the set *trig*'s condition names under ``<key>_filter``.

    The matching itself is :func:`engine.subject_filters.subject_matches`, shared
    with every other reader of a printed noun phrase; this is only the part that
    is about a *trigger* — which payload key the condition keeps its filter
    under, and that an absent one is no narrowing at all. CR 509.3c/509.3d say
    the difference between "whenever this creature blocks" and "…blocks a
    creature" is how often it fires, which is the fire site's business rather
    than this predicate's.
    """
    return subject_matches(
        game,
        obj,
        trig.condition.payload.get(f"{key}_filter"),
        observer=observer,
        source=source,
    )


def _controller_of(game: Game, permanent: Permanent) -> PlayerState:
    seat = game.controller_index_of(permanent)
    return game.players[0 if seat is None else seat]


# The filters themselves, one module per family of event — ``cast_event_filters``
# (a spell cast, a card played) and ``event_filters`` (every other kind).
# Imported last and for their side effect: each ``@event_filter`` row fills
# EVENT_FILTERS, which ``collect`` reads, and both modules import ``Event``,
# ``event_filter`` and the shared readers above from here.
from . import cast_event_filters, event_filters  # noqa: E402,F401


__all__ = ["EVENT_FILTERS", "Event", "collect", "emit", "event_filter"]
