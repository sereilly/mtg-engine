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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterable

from .subject_filters import subject_matches
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


def emblem_trigger_events(game: Game, kind: str, players=None) -> list[dict]:
    """Every emblem-borne trigger matching *kind*, as enqueueable event dicts.

    Emblems function from the command zone (CR 114.4), so no battlefield scan
    can find them — every site that collects a condition's triggers over
    permanents asks this beside it. The emblem's detached Permanent stands in
    as the source, so the stack item and the resolution context read it like
    any other trigger's.
    """
    from .oracle import compile_emblem_text

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
    # An emblem's ability fires from the command zone (CR 114.4) — collected
    # beside the permanents', through the same event, so APNAP ordering and
    # the enqueue path treat both alike.
    events.extend(
        emblem_trigger_events(
            game, event.kind,
            list(event.players) if event.players is not None else None,
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
    # "…a spell that's white, blue, black, or red" (Quirion Dryad): the
    # colour list arrives as condition payload, the raw captured phrase; the
    # trigger fires only when the cast spell shares at least one listed
    # colour (CR 105.4 — an "or" list of qualities is a union).
    cast_colors = trig.condition.payload.get("cast_colors")
    if cast_colors:
        wanted = {
            _COLOR_SYMBOLS[word]
            for word in cast_colors.replace(",", " ").split()
            if word in _COLOR_SYMBOLS
        }
        if wanted and not (wanted & set(card.colors)):
            return False
    # "…a noncreature spell" (Spellgorger Weird): the type word from the
    # trigger's own text, tested against the cast card's type line — "non"
    # negates, so a noncreature trigger stays silent for a creature spell.
    cast_type = trig.condition.payload.get("cast_type")
    if cast_type:
        type_line = card.type_line.lower()
        if cast_type.startswith("non"):
            if cast_type[3:] in type_line:
                return False
        elif cast_type not in type_line:
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


@event_filter("counters_put_on_creature")
def _counters_put_on_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever one or more +1/+1 counters are put on another non-Hydra
    creature you control" (Wildwood Scourge).

    "You control" is the observer's own seat, "another" excludes the observer
    itself (CR 109.5), and the excluded subtype arrives as condition payload
    from the trigger's own text — so a card printed with a different tribe
    needs no code here.
    """
    counted = event.subject
    if counted is None or event.payload.get("seat") is None:
        return False
    if game.controller_index_of(permanent) != event.payload["seat"]:
        return False
    if counted is permanent:
        return False
    excluded = trig.condition.payload.get("counters_excluded_subtype")
    # has_type, not the printed line: a creature *made* a Hydra by layer 4 is
    # one, which is the same reading every other subtype test in the engine
    # makes.
    return not (excluded and counted.has_type(excluded))


# The events whose whole narrowing is the word "you": announced once,
# game-wide, carrying the seat it happened to, and matching only that seat's own
# permanents. "You" on a permanent's triggered ability is that permanent's
# controller (CR 109.5) — so an opponent's lifelink swing leaves Vito silent,
# and an opponent feeding their own Altar leaves Havoc Jester silent.
#
# A set rather than three identical predicates. The third one (the sacrifice)
# is what turned the shape into a table: two copies of a two-line body is a
# coincidence, three is a rule that had been written down three times.
_SEAT_SCOPED_EVENTS = frozenset({
    "you_gain_life",
    "draws_second_card",
    "you_sacrifice_permanent",
    # "a source **you** control deals noncombat damage to an opponent"
    # (Chandra's Pyreling). The seat here is the *source's* controller, not the
    # damaged player's — an opponent burning you leaves the Pyreling silent —
    # which is the same "you" the three above carry and the reason this is a row
    # rather than a fourth predicate.
    "source_you_control_damages_opponent",
})


@event_filter(*_SEAT_SCOPED_EVENTS)
def _seat_scoped_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever **you** gain life / draw your second card / sacrifice a
    permanent" — only the acting seat's own permanents."""
    seat = event.payload.get("seat")
    return seat is not None and game.controller_index_of(permanent) == seat


# ---------------------------------------------------------------------------
# A trigger whose subject is a set of objects
# ---------------------------------------------------------------------------


# The events announced game-wide whose *whole* applicability is the trigger's
# own subject filter, and the payload key each records it under. One filter per
# event, so the registration is a row rather than a predicate.
_SUBJECT_LED_FILTER_KEYS: dict[str, str] = {
    "matching_creature_attacks": "attacker",
    "matching_creature_damages_planeswalker": "damager",
    "matching_permanent_enters": "enterer",
}


@event_filter(*_SUBJECT_LED_FILTER_KEYS)
def _subject_led_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever a creature you control with deathtouch attacks / deals damage
    to a planeswalker …" (Hooded Blightfang).

    The announcement is game-wide and every narrowing the card prints is in the
    trigger's own noun phrase — "you control" included, which is why the
    observer is the permanent's own controller (CR 109.5) rather than anything
    the event carries. An *unnarrowed* condition would therefore fire for every
    permanent on the board, which is why the compiler refuses one it cannot
    test rather than admitting an empty filter here.
    """
    return trigger_subject_matches(
        game, trig, _SUBJECT_LED_FILTER_KEYS[event.kind], event.subject,
        observer=game.controller_index_of(permanent), source=permanent,
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


__all__ = ["EVENT_FILTERS", "Event", "collect", "emit", "event_filter"]
