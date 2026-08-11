"""Game event bus for triggered abilities.

Before this, a triggered ability only fired if some piece of engine code
explicitly went looking for it: twenty-three hand-placed
``iter_triggered_abilities(condition_kinds={...})`` scans spread across the
phase modules and mixins. That has two consequences at scale.

The first is that support is invisible from the card's side. The oracle
compiler recognizes trigger conditions it has no dispatcher for — ``spell_cast``,
``creature_enters``, ``artifact_enters``, ``draws_card`` and others parse
happily and then never fire, so cards needing them get routed to a name-keyed
hook in ``card_hooks.py`` instead. Six cards were name-keyed for cast triggers
the parser already understood.

The second is that adding a trigger condition means finding or creating a fire
site rather than adding a registry row — the opposite of how the rest of the
engine grows.

This module inverts that: game code announces *what happened*
(``emit(game, "spell_cast", ...)``) and every permanent whose compiled trigger
matches is enqueued, in APNAP order, by the existing stack machinery. Trigger
conditions keep the kind strings the compiler already produces, so a fire site
converts to an ``emit`` without touching the cards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterable

from .trigger_utils import iter_triggered_abilities, make_trigger_event

if TYPE_CHECKING:
    from .game import Game
    from .models import CardDefinition, Permanent, PlayerState
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
        events.append(
            make_trigger_event(
                controller_index,
                permanent,
                trig,
                trigger_context=dict(event.payload) or None,
            )
        )
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


# ---------------------------------------------------------------------------
# Applicability filters
# ---------------------------------------------------------------------------


_COLOR_SYMBOLS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}


def _cast_card(event: Event) -> CardDefinition | None:
    card = event.subject
    return card if card is not None and hasattr(card, "colors") else None


@event_filter("spell_cast")
def _spell_cast_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever a player casts a spell …", optionally narrowed by the spell's
    color or type.

    The narrowing lives in the trigger's own text rather than in a per-card
    hook, which is what lets the five Rod/Cup/Sphere artifacts and every future
    "whenever a player casts a ___ spell" card share one dispatcher.
    """
    card = _cast_card(event)
    if card is None:
        return False
    # The compiler captures the colour word from the trigger's own text
    # ("…casts a *blue* spell") into the condition payload.
    colour_word = trig.condition.payload.get("color_word")
    if colour_word and _COLOR_SYMBOLS.get(colour_word) not in card.colors:
        return False
    wanted_type = trig.condition.payload.get("card_type")
    if wanted_type and wanted_type not in card.type_line.lower():
        return False
    return True


@event_filter("you_cast_spell", "enchantment_cast")
def _controller_cast_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever you cast a[n enchantment] spell" — only for the caster's own
    permanents."""
    card = _cast_card(event)
    if card is None:
        return False
    caster_index = event.payload.get("caster_index")
    if caster_index is None or game.players.index(_controller_of(game, permanent)) != caster_index:
        return False
    if trig.condition.kind == "enchantment_cast" and "enchantment" not in card.type_line.lower():
        return False
    return True


@event_filter("opponent_casts_spell")
def _opponent_cast_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    card = _cast_card(event)
    if card is None:
        return False
    caster_index = event.payload.get("caster_index")
    if caster_index is None:
        return False
    return game.players.index(_controller_of(game, permanent)) != caster_index


# The controller clause of a "whenever a <filter> becomes tapped" condition, as
# the legacy trigger table captures it, mapped to whose permanents qualify.
# Absent means any player's.
_TAPPED_CONTROLLER_SCOPES = {
    "an opponent controls": "opponent",
    "you control": "you",
}


@event_filter("permanent_becomes_tapped")
def _becomes_tapped_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever a Forest an opponent controls becomes tapped …" (Lifetap).

    Both halves of the restriction are read from the trigger's own parsed
    condition — the type the tapped permanent must have, and whose it must be —
    so one dispatcher covers every card written this way and no card name
    appears here. ``has_type`` rather than the printed type line, so a land made
    a Forest by Magical Hack counts (CR 613 layer 4).
    """
    tapped = event.subject
    if tapped is None or not hasattr(tapped, "tapped"):
        return False
    subtype = trig.condition.payload.get("tapped_subtype")
    if subtype and not tapped.has_type(str(subtype)):
        return False
    scope = _TAPPED_CONTROLLER_SCOPES.get(trig.condition.payload.get("tapped_controller"))
    if scope is None:
        return True
    observer = game.players.index(_controller_of(game, permanent))
    tapped_controller = game.controller_index_of(tapped)
    if tapped_controller is None:
        return False
    if scope == "opponent":
        return tapped_controller != observer
    return tapped_controller == observer


def _controller_of(game: Game, permanent: Permanent) -> PlayerState:
    seat = game.controller_index_of(permanent)
    return game.players[0 if seat is None else seat]


__all__ = ["EVENT_FILTERS", "Event", "collect", "emit", "event_filter"]
