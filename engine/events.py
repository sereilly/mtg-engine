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
from typing import TYPE_CHECKING, Callable

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


# ---------------------------------------------------------------------------
# Applicability filters
# ---------------------------------------------------------------------------


_COLOR_SYMBOLS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}


def _cast_card(event: Event) -> CardDefinition | None:
    card = event.subject
    return card if card is not None and hasattr(card, "colors") else None


@event_filter("self_put_into_graveyard_from_library")
def _moved_card_only_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """CR 113.6k's other half, and the only thing that enforces it.

    "When **this card** is put into your graveyard from your library" cannot
    trigger from the battlefield: a permanent is not in a library, so the move
    the condition names is one it can never make. The battlefield scan in
    :func:`collect` has no such notion — it matches on the condition's kind
    alone — so a permanent carrying this ability would fire on every other
    card's mill. ``moved_card_trigger_events`` is what announces it instead, and
    that one is scoped to the object that moved.
    """
    return False


@event_filter("card_put_into_graveyard")
def _card_put_into_graveyard_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """One kind, two printed narrowings, read as **data** rather than as kinds.

    "When a card is put into **your** graveyard from anywhere, sacrifice this
    enchantment." (Energy Field.) — and — "Whenever **another** card is put into
    a graveyard from anywhere, exile that card." (Planar Void.)

    The move is the same event and `Game.put_card_into_graveyard` is the same
    seam; what differs is which cards each card's own sentence admits. So the
    condition is one kind and each row carries its narrowing as an empty named
    group, which is CLAUDE.md's rule stated the other way round: a narrowing is
    data, not a kind. Two kinds here would be two names for one event, and two
    *filters* is not an option either — `event_filter` allows one per kind, by
    design, and USG's wave-2 integration is where that stopped being academic:
    both cards arrived on different branches, each with its own filter, and the
    merge silently left one of them undecorated.

    **your**: the watching permanent's controller (CR 109.5), never the card's
    owner and never the seat that caused the move — an opponent milling their
    own library must not break the Field, and the same card reaching *its*
    controller's graveyard must, however it got there. Read through the control
    seam, so a Field somebody has taken control of watches **their** graveyard
    from the moment they take it (CR 613 layer 2).

    **another**: the ability's own source is excluded and nothing else is.
    Compared by `CardDefinition` identity, which is the identity this engine
    has — a deck repeats one immutable definition per copy, so a second Planar
    Void milled while the first is on the battlefield is skipped. That is the
    wrong half of a rare pair and it is chosen deliberately: the other reading
    has Planar Void exiling itself as it dies, which is the one case the printed
    word forbids.

    A row carrying neither marker admits every card, which is what the sentence
    without either word says.
    """
    payload = trig.condition.payload
    if "your_graveyard" in payload:
        return game.controller_index_of(permanent) == event.payload.get("owner_index")
    if "another_card" in payload:
        return event.subject is not permanent.card
    # "Whenever **a black card** is put into **an opponent's** graveyard from
    # anywhere." (Compost.) The third printed narrowing of this one condition,
    # and the first that is two narrowings at once — what the card is, and whose
    # pile it landed in. Both are tested here for the reason the two above are:
    # the move is one event and one seam, and what differs between the cards is
    # only which arrivals each sentence admits.
    #
    # **whose pile**: an opponent of the *watching permanent's* controller
    # (CR 109.5), read through the control seam so a Compost somebody has taken
    # control of watches their opponents from the moment they take it (CR 613
    # layer 2). Never the seat that caused the move — a player milling their own
    # library fills their own graveyard, and it is the pile the sentence names.
    #
    # **what the card is**: the phrase, through the card matcher, because the
    # object is in a graveyard and has no controller, no layers and no board
    # position. Dropped, Compost would draw on every card reaching any
    # opponent's pile, which is a strictly larger card than the one printed and
    # one every census in this repo reads as implemented.
    described = payload.get("graveyard_card_filter")
    if "opponent_graveyard" in payload or described:
        watcher = game.controller_index_of(permanent)
        owner = event.payload.get("owner_index")
        if "opponent_graveyard" in payload:
            if watcher is None or owner is None or watcher == owner:
                return False
        if described:
            from .handlers._common import _card_matches_filter

            card = event.subject
            if card is None or not _card_matches_filter(
                card, described, game=game,
                owner=game.players[owner] if isinstance(owner, int) else None,
            ):
                return False
    return True


@event_filter("you_play_card")
def _controller_played_card_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"When you play a card" (Juju Bubble) — only for the player's own
    permanents.

    Its own filter rather than a name added to the cast filter below, because
    the event is not a cast: CR 701.18b makes playing a land half of what this
    watches, and that half has no spell, no colours and no type line for the
    cast narrowings to test. What it shares with a cast is only the word
    "you", which is this whole predicate.
    """
    seat = event.payload.get("caster_index")
    return seat is not None and game.controller_index_of(permanent) == seat


@event_filter("opponent_casts_nth_spell_each_turn")
def _opponent_nth_cast_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever an opponent casts their **second** spell each turn" (Mangara).

    The ordinal is asked of the *caster's* record of what they have cast this
    turn — the spell that fired this event is already on it, so "their second"
    means exactly two. Counted rather than flagged, because CR 121.2's per-spell
    reading is what makes "their third" a different card and not this one.
    """
    caster_index = event.payload.get("caster_index")
    if caster_index is None:
        return False
    if game.players.index(_controller_of(game, permanent)) == caster_index:
        return False
    wanted = _NUMBER_WORDS.get(str(trig.condition.payload.get("spell_ordinal", "")))
    if wanted is None:
        return False
    return len(game.players[caster_index].spells_cast_this_turn) == wanted


_NUMBER_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
}


@event_filter("cumulative_upkeep_unpaid")
def _own_cumulative_upkeep_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"When a player doesn't pay **this enchantment's** cumulative upkeep, …"
    (Thought Lash.)

    The printed possessive is the whole of the narrowing: the ability watches
    its *own* upkeep, not any unpaid one. Without this a second permanent with
    the same trigger would fire off the first one's non-payment — two
    libraries emptied for one missed payment.
    """
    return event.subject is permanent


@event_filter("opponent_attackers_declared")
def _opponent_attack_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever an **opponent** attacks with creatures" (Mangara).

    Only for a permanent whose controller is not the attacking seat, and the
    intervening-if's number is stamped into the trigger's context here — the
    count is per *seat*, and this is the one place that knows which seat is
    asking.
    """
    attacking_seat = event.payload.get("seat")
    seat = game.players.index(_controller_of(game, permanent))
    if attacking_seat is None or seat == attacking_seat:
        return False
    aimed = event.payload.get("aimed_by_seat") or {}
    event.payload["attackers_aimed"] = int(aimed.get(seat, 0))
    return True


@event_filter("permanent_becomes_untapped")
def _self_untapped_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever **this** creature becomes untapped" — the permanent's own
    event and nobody else's, so a board of Pilferers does not all fire when one
    untaps. By identity, because two of them compare equal by value."""
    return event.subject is permanent


@event_filter("self_cast")
def _self_cast_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"When you cast this spell" never fires from the battlefield.

    CR 113.6a: a permanent's abilities function on the battlefield, and this one
    is about *this spell* — an object that is on the stack and that a permanent
    on the battlefield is not. Without this, a resolved Mana Vortex would counter
    every later spell its controller cast, because the battlefield scan matches
    on the condition kind alone and the kind is the same one.
    ``cast_trigger_events`` is what does fire it, over the card being cast.
    """
    return False


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
    # The type narrowing goes through the shared helper below, which the
    # ordinal-counting path already used. This branch used to read a
    # `card_type` key **no pattern in the compiler ever emitted** — a
    # dispatcher reading a narrowing nothing produced, which is round 1's
    # shape with the halves swapped: harmless while dead, and a second
    # opinion about what "an artifact spell" means the moment it was not.
    return _cast_narrowing_admits(
        game, permanent, trig, card, event.payload.get("caster_index")
    )


def _cast_colors(game: Game, card, caster: int | None) -> tuple[str, ...]:
    """The colours the cast spell has (CR 105 through CR 613.1e).

    Its own two lines because three narrowings ask it — the singular colour
    word, Quirion Dryad's colour list and Invoke Prejudice's "doesn't share a
    color" — and three copies of ``card.colors`` is how all three came to be
    blind to Celestial Dawn at once.
    """
    from .object_colors import card_colors

    return card_colors(game, card, caster)


def _cast_colour_union_admits(printed: str | None, colors) -> bool:
    """Whether *colors* answers a printed colour **union** ("green or white").

    CR 105.2b: an object with more than one colour is each of those colours, so
    a listed colour anywhere in the spell's set admits it. Its own two lines
    because three rows now carry the key — Quirion Dryad's "that's white, blue,
    black, or red" and the two board-wide cast kinds — and three copies of the
    split is how the single-colour narrowing above came to be read in one
    dispatcher and dropped in the others.

    An empty or unreadable list admits everything: a narrowing nothing could
    parse must not silently stop the trigger the card prints.
    """
    if not printed:
        return True
    wanted = {
        _COLOR_SYMBOLS[word]
        for word in str(printed).replace(",", " ").split()
        if word in _COLOR_SYMBOLS
    }
    return not wanted or bool(wanted & set(colors))


def _cast_narrowing_admits(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, card,
    caster: int | None = None,
) -> bool:
    """Whether *card* answers this cast trigger's printed narrowing.

    The ordinal has to count the *same* set the trigger fires on — "your first
    **instant or sorcery** spell" counts instants and sorceries and nothing
    else — so the narrowing is asked once here and reused, rather than the
    counting loop growing its own copy of the type tests below.

    *caster* is who cast it (CR 109.5), for the colour narrowings alone: a
    spell's colour is a layer-5 characteristic of an object (CR 613.1), so
    "casts a **blue** spell" asks what the spell is now and not what its mana
    cost was printed as. A caller with no seat gets the printed reading.

    *game* and *permanent* are here for the one narrowing that is not about the
    cast card alone: "…that doesn't share a color with a creature you control"
    compares it against a board, and "you" is the seat that controls the ability
    (CR 109.5). Answering that one at a single fire site instead would put it
    outside the set the ordinal counts, which is exactly the disagreement this
    function exists to prevent.
    """
    type_line = card.type_line.lower()
    # The compiler captures the colour word from the trigger's own text
    # ("…casts a *blue* spell") into the condition payload. Read here rather
    # than in one fire site, for this function's own reason: the three cast
    # kinds ask one narrowing, and a colour tested only under "a player casts"
    # is a colour the opponent-scoped spelling silently ignores — Freyalise's
    # Charm and Leshrac's Sigil would have fired on an opponent's every spell.
    colour_word = trig.condition.payload.get("color_word")
    if colour_word and _COLOR_SYMBOLS.get(colour_word) not in _cast_colors(
        game, card, caster
    ):
        return False
    # "…casts a **green or white** spell" (Putrefaction, Snake Pit). The same
    # narrowing over a set: CR 105.2b makes a multicoloured object *each* of its
    # colours, so any listed colour answers. One key rather than a second
    # condition kind, and read here rather than only in `_controller_cast_filter`
    # — a union tested for "you cast" alone is a union the two board-wide cast
    # kinds silently ignore, which is the widening the single-colour row above
    # already had to be told about once.
    if not _cast_colour_union_admits(
        trig.condition.payload.get("cast_colors"), _cast_colors(game, card, caster)
    ):
        return False
    # "…casts a **multicolored** spell" (Rewards of Diversity). CR 105.2b's
    # count over the same effective colours the two rows above read, through
    # the one reader of the relation — so a gold card a Celestial Dawn has made
    # white is not multicoloured as it is cast. A marker key, so it is tested by
    # presence: the group captures nothing and its value is the empty string.
    if "cast_multicolored" in trig.condition.payload:
        from .object_colors import is_multicolored

        if not is_multicolored(_cast_colors(game, card, caster)):
            return False
    # "…casts a spell **of the chosen color**" (Jeweled Torque). CR 614.1c's
    # choice, recorded on the permanent as it entered — so, unlike every
    # narrowing above, the colour is not in the trigger's text at all and the
    # answer comes off the *source*. Read here beside the printed colours
    # because it is the same question of the same event, and a dispatcher of its
    # own would be a second opinion about what "a spell of that colour" means.
    #
    # Nothing recorded fires nothing: a permanent with no colour on it is one
    # whose entry choice never happened, and a trigger with no colour to compare
    # would answer every spell — the widest possible reading of a sentence that
    # names one. The same reading ``grant_prevention_shield`` takes of the same
    # record one file over.
    if "cast_chosen_color" in trig.condition.payload:
        recorded = (getattr(permanent, "metadata", {}) or {}).get("chosen_color")
        if not recorded or str(recorded) not in _cast_colors(game, card, caster):
            return False
    cast_types = trig.condition.payload.get("cast_types")
    if cast_types and not any(word in type_line for word in cast_types.split(" or ")):
        return False
    cast_type = trig.condition.payload.get("cast_type")
    if cast_type:
        if cast_type.startswith("non"):
            if cast_type[3:] in type_line:
                return False
        elif cast_type not in type_line:
            return False
    # "…a creature spell **with flying**" (Hidden Spider). An ability of the
    # spell rather than a word of its type line, so it is asked of the card's
    # keywords — the printed ones, because a spell on the stack is not a
    # permanent and layer 6 has nothing on it to read. A trigger naming a
    # keyword the card does not have does not fire, which is the direction that
    # leaves the Spider an enchantment.
    cast_keyword = trig.condition.payload.get("cast_keyword")
    if cast_keyword and cast_keyword not in {
        str(word).lower() for word in (card.keywords or ())
    }:
        return False
    # "…a creature spell **that doesn't share a color with a creature you
    # control**" (Invoke Prejudice). CR 105.2: an object's colours are a set, so
    # "shares a colour" is a non-empty intersection — a colourless spell shares
    # a colour with nothing, which is the reading that makes an artifact
    # creature answer this trigger.
    unshared = trig.condition.payload.get("unshared_color_filter")
    if unshared:
        from .subject_filters import subject_matches

        observer = game.players.index(_controller_of(game, permanent))
        cast_colors = set(_cast_colors(game, card, caster))
        for candidate in game.all_permanents():
            if not subject_matches(
                game, candidate, dict(unshared), observer=observer,
                source=permanent,
            ):
                continue
            if cast_colors & game._effective_colors(candidate):
                return False
    return True


@event_filter("revealed_drawn_card")
def _revealed_drawn_card_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever you reveal **a basic land card** this way, draw a card." (Rowen.)

    Two narrowings, and both are printed. "**You**" is the ability's controller,
    so a Rowen on one battlefield does not fire on the other seat's reveal — the
    announcement is already scoped to the drawing player, and this compares it
    against the seat that controls the source (CR 109.5). And the noun phrase
    describes the *card* that was revealed, which is a card in a hand rather
    than a permanent, so it goes through the card matcher exactly as a cast
    trigger's does.
    """
    card = event.subject
    if card is None or not hasattr(card, "type_line"):
        return False
    drawer = event.payload.get("event_subject_player")
    if drawer != game.players.index(_controller_of(game, permanent)):
        return False
    described = trig.condition.payload.get("revealed_filter")
    if not described:
        return True
    from .handlers._common import _card_matches_filter

    return _card_matches_filter(card, dict(described))


@event_filter("you_cast_spell", "enchantment_cast", "you_cast_first_spell_each_turn")
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
    # colour (CR 105.2b — a multicoloured object *is* each of its colours).
    if not _cast_colour_union_admits(
        trig.condition.payload.get("cast_colors"),
        _cast_colors(game, card, caster_index),
    ):
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
    # "…a **Dog** spell" (Rin and Seri). The printed subtype, read through the
    # same reader the layer seed uses rather than as a substring of the type
    # line — a substring match would let "Dog" answer for a "Dogpile", and would
    # answer for a card *type* word too, which is the row above's job.
    # "an **instant or sorcery** spell" — a printed union, so any of the listed
    # types answers it (CR 205.2b — an object with several card types satisfies
    # an effect applying to any of them). Its own key because
    # the single-type row above tests "this one" and a union tests "any of
    # these", and folding them would make one of the two silently wrong.
    cast_types = trig.condition.payload.get("cast_types")
    if cast_types:
        type_line = card.type_line.lower()
        if not any(word in type_line for word in cast_types.split(" or ")):
            return False
    # "…your **first** … spell each turn" (Double Vision). The ordinal is asked
    # of the caster's own record of what they have cast this turn, counting only
    # the spells this condition's narrowing admits — the spell that fired this
    # event is already on that list, so being the first one means exactly one
    # match. Asked here rather than by a separate fire site because the *event*
    # is the ordinary cast; only the question differs.
    if trig.condition.kind == "you_cast_first_spell_each_turn":
        caster = game.players[caster_index]
        matching = [
            spell for spell in caster.spells_cast_this_turn
            if _cast_narrowing_admits(game, permanent, trig, spell, caster_index)
        ]
        if len(matching) != 1 or matching[0] is not card:
            return False
    cast_subtype = trig.condition.payload.get("cast_subtype")
    if cast_subtype:
        from .layer_bridge import printed_shape

        _, subtypes = printed_shape(card)
        if cast_subtype.lower() not in subtypes:
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
    if game.players.index(_controller_of(game, permanent)) == caster_index:
        return False
    # "…from anywhere other than their **hand**" (Ghostly Pilferer). The zone
    # the spell was cast from, which the cast records on the event — the same
    # field "if this spell was cast from anywhere other than your hand" (See the
    # Truth) reads. An event with no zone recorded is treated as a cast from the
    # hand, which is the ordinary case and the one that must not fire.
    not_from = trig.condition.payload.get("not_from_zone")
    if not_from and event.payload.get("cast_from_zone", "hand") == not_from:
        return False
    # "…**other than the first instant spell that player casts each turn**"
    # (Ichneumon Druid). An ordinal *exclusion*, and the mirror of the
    # first-spell ordinal above: both count the caster's own record of the
    # spells this condition's narrowing admits, and the spell that fired this
    # event is already on it — so its position in that list is the list's
    # length. The trigger fires once that position is past the exempted one.
    after = trig.condition.payload.get("after_spell_ordinal")
    if after is not None:
        exempt = _NUMBER_WORDS.get(str(after))
        if exempt is None:
            # An ordinal this engine cannot count. Refusing is the safe
            # direction: firing would ignore the exemption the card prints.
            return False
        caster = game.players[caster_index]
        matching = [
            spell for spell in caster.spells_cast_this_turn
            if _cast_narrowing_admits(game, permanent, trig, spell, caster_index)
        ]
        if len(matching) <= exempt:
            return False
    # "…a spell **that targets you or a creature you control**"
    # (Reparations). A narrowing on what the spell *pointed at*, which nothing
    # on the board can answer once the spell has resolved — so it is read off
    # what the cast announcement froze (CR 601.2c settles the targets as the
    # object goes on the stack). "You" is the trigger's own controller
    # (CR 109.5), which is what keeps the enchantment silent while its opponents
    # shoot at each other.
    if "targets_you_or_your_creature" in trig.condition.payload:
        observer = game.players.index(_controller_of(game, permanent))
        if observer not in (event.payload.get("targeted_seats") or ()):
            mine = [
                found
                for permanent_id in event.payload.get("targeted_permanent_ids") or ()
                for found in (game.permanent_by_id(permanent_id),)
                if found is not None
                and found.is_creature
                and game.controls(observer, found)
            ]
            if not mine:
                return False
    # "…casts an **artifact** spell" (Citanul Druid), asked of the same helper
    # the other two cast kinds use.
    return _cast_narrowing_admits(game, permanent, trig, card, caster_index)


# The controller clause of a "whenever a <filter> becomes tapped" condition, as
# the legacy trigger table captures it, mapped to whose permanents qualify.
# Whose spell or ability did the targeting. Absent means anyone's.
_TARGETING_CONTROLLER_SCOPES = {
    "an opponent controls": "opponent",
    "you control": "you",
}

# Absent means any player's.
_TAPPED_CONTROLLER_SCOPES = {
    "an opponent controls": "opponent",
    "you control": "you",
}


@event_filter("self_becomes_target")
def _self_becomes_target_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever this creature becomes the target of a spell or ability an
    opponent controls…" (Warden of the Woods).

    "**This** creature", so the event's subject must be the very permanent whose
    ability this is — by identity, because a look-alike on the same battlefield
    is a different permanent and would otherwise draw its controller two cards.
    Where the condition says "**enchanted** creature" instead (Spinal Graft) the
    subject must be the permanent this one is *attached to*, by the same
    identity test.

    Whose spell it must be is read off the trigger's own parsed condition, so
    the unnarrowed wording and "you control" are the same dispatcher with
    different data.

    **What** it must be is read the same way. "…the target of a spell"
    (Forsaken Wastes) is narrower than "…of a spell or ability", and a
    narrowing nothing tests is an ability that fires more often than the card
    allows — silent, and in the player's favour. An absent key is the
    unnarrowed printing and admits both.
    """
    # "When **enchanted creature** becomes the target of a spell or ability, …"
    # (Spinal Graft.) The same event watched by something attached to the
    # targeted permanent rather than by the permanent itself — one condition
    # kind, two dispatch scopes, told apart by the narrowing the condition's own
    # table wrote. The same arrangement `attached_subject_triggers` makes for
    # the damage and combat events, and the printed noun is tested here for its
    # reason: "enchanted **creature**" is not satisfied by an Equipment on an
    # artifact no animation has made a creature (CR 613 layer 4).
    attached_noun = trig.condition.payload.get("targeted_attached")
    if attached_noun:
        host = permanent.metadata.get("attached_to")
        if host is None or host is not event.subject:
            return False
        if not host.has_type(str(attached_noun)):
            return False
    elif "targets_you_or_your_permanent" in trig.condition.payload:
        # "Whenever **you or a permanent you control** becomes the target of a
        # spell or ability an opponent controls" (Rayne, Academy Chancellor).
        # The **third dispatch scope** for this event: an observer that is
        # neither the targeted object nor attached to it, so neither branch
        # above can reach it — exactly Death Pits of Rath's position on
        # `creature_dealt_damage`, and admitted the same way, by a narrowing the
        # condition carries as data.
        #
        # Two halves, because the printed subject really is two things. The
        # **player** half is the seat the announcement names when a spell or
        # ability targeted a face at all; the **permanent** half is the targeted
        # object tested for whose it is, through the control seam (CR 613 layer
        # 2), so a permanent that changed hands is counted where it is now.
        #
        # "A permanent", not "a creature": CR 110.1's word covers the whole
        # board, and the noun is what makes this Rayne rather than Reparations.
        observer = game.players.index(_controller_of(game, permanent))
        seat = event.payload.get("targeted_seat")
        subject = event.subject
        if isinstance(seat, int):
            if seat != observer:
                return False
        elif subject is None or not game.controls(observer, subject):
            return False
    elif trig.condition.payload.get("targeted_filter") is not None:
        # "Whenever **a creature** becomes the target of a spell or ability"
        # (Cowardice). The **fourth dispatch scope**: an observer watching a
        # described set on every battlefield rather than itself, its host or its
        # own side — so the test is the printed noun phrase asked of the
        # targeted object, through the one matcher every other printed phrase in
        # this engine goes through.
        #
        # The observer's seat is the source's (CR 109.5), which is what a
        # relative key like "you control" would be read against. A targeted
        # *player* announces this event with no subject at all, and a phrase
        # about an object cannot be answered for a seat — so no subject is no
        # match, never a free pass.
        from .subject_filters import subject_matches

        if event.subject is None:
            return False
        observer = game.players.index(_controller_of(game, permanent))
        if not subject_matches(
            game, event.subject, dict(trig.condition.payload["targeted_filter"]),
            observer=observer, source=permanent,
        ):
            return False
    elif event.subject is not permanent:
        # The **self** scope, and the last branch rather than the first because
        # the three above are the narrowed readings: "this creature" means the
        # very permanent whose ability this is, by identity, because a
        # look-alike on the same battlefield is a different permanent and would
        # otherwise draw its controller two cards.
        return False
    wanted = trig.condition.payload.get("targeted_by")
    if wanted in ("a spell", "an ability"):
        if event.payload.get("targeted_by") != wanted:
            return False
    if wanted == "an aura spell":
        # "…the target of **an Aura spell**" (Fugitive Druid). A spell, and a
        # narrower class of one: an activated ability is out by the first test
        # and everything else by the subtype. Read through `printed_shape`, the
        # same reader a cast trigger's `cast_subtype` narrowing goes through —
        # a spell on the stack is not a permanent, so the layer system has no
        # answer and the printed face is the whole of what is testable.
        if event.payload.get("targeted_by") != "a spell":
            return False
        from .layer_bridge import printed_shape

        card = event.payload.get("targeted_by_card")
        if card is None:
            return False
        _, subtypes = printed_shape(card)
        if "aura" not in subtypes:
            return False
    scope = _TARGETING_CONTROLLER_SCOPES.get(
        trig.condition.payload.get("targeting_controller")
    )
    if scope is None:
        return True
    source_seat = event.payload.get("source_seat")
    if not isinstance(source_seat, int):
        return False
    observer = game.players.index(_controller_of(game, permanent))
    return (source_seat == observer) if scope == "you" else (source_seat != observer)


# The compound kind shares this filter: both its events name the same subject —
# the permanent that tapped, or the one whose ability was activated — and the
# printed narrowing ("an artifact", "an artifact an opponent controls") is the
# same question about it either way.
#: The printed noun that names **every** object on the battlefield (CR 110.1).
#: ``has_type`` answers card types and "permanent" is not one, so a narrowing
#: spelled with this word is no narrowing at all — and testing it with
#: ``has_type`` does not widen the trigger, it silences it. Freyalise's Winds
#: ("Whenever **a permanent** becomes tapped") is the first card in the pool to
#: print it, and the trigger fired on nothing at all.
_UNIVERSAL_NOUN = "permanent"


def _noun_matches(obj, noun: str) -> bool:
    """Whether *obj* answers to a printed head noun, universal word included.

    One reader for the two filters below that read a captured noun, so the word
    cannot mean everything in one of them and nothing in the other.
    """
    return noun == _UNIVERSAL_NOUN or obj.has_type(noun)


@event_filter("permanent_tapped_or_ability_activated")
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
    # "Whenever **enchanted artifact** becomes tapped…" (Artifact Possession,
    # Psychic Venom, Blight, Spirit Shackle). The subject is the one permanent
    # this Aura is attached to rather than a class of them, so the narrowing is
    # an identity check — and by identity, because two copies of a permanent
    # compare equal by value and the Aura is on exactly one of them.
    if trig.condition.payload.get("tapped_attached"):
        return permanent.metadata.get("attached_to") is tapped
    # "Whenever **this land** becomes tapped…" (City of Brass). The source
    # itself, and by identity for the same reason: a second City of Brass on
    # the same battlefield is a different permanent and must not take the
    # damage its look-alike's tap deals.
    if trig.condition.payload.get("tapped_self"):
        return tapped is permanent
    # "Whenever a **Swamp, Mountain, black permanent, or red permanent**
    # becomes tapped" (Royal Decree). A whole noun phrase rather than a word,
    # read through the one reader of what a printed noun phrase means -- with
    # the trigger's own controller as observer (CR 109.5), exactly as every
    # other subject-narrowed condition reads one. The compiler admits the
    # phrase only when every key it produces is testable, so nothing here can
    # be silently dropped.
    described = trig.condition.payload.get("tapped_filter")
    if described:
        from .subject_filters import subject_matches

        if not subject_matches(
            game, tapped, described,
            observer=game.players.index(_controller_of(game, permanent)),
            source=permanent,
        ):
            return False
    subtype = trig.condition.payload.get("tapped_subtype")
    if subtype and not _noun_matches(tapped, str(subtype)):
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


@event_filter("nonmana_ability_activated")
def _nonmana_ability_activated_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever a player activates an ability of **enchanted creature** with
    {T} in its activation cost that isn't a mana ability" (Imprison).

    Both printed narrowings are read off the trigger's own condition, so one
    dispatcher covers every card written this way and no card name appears
    here. The attached half is an *identity* check for the reason the tap
    filter's is: two copies of a permanent compare equal by value and this Aura
    is on exactly one of them.

    ``has_type`` rather than the printed line for the noun, so a permanent made
    a creature by an animation answers to a card that says "creature"
    (CR 613 layer 4) — the same reader the tap filter's subtype uses.
    """
    subject = event.subject
    if subject is None or not hasattr(subject, "metadata"):
        return False
    payload = trig.condition.payload
    noun = payload.get("activated_attached")
    if noun:
        if permanent.metadata.get("attached_to") is not subject:
            return False
        if not _noun_matches(subject, str(noun)):
            return False
    # "**with** {T} in its activation cost" — the printed word, tested rather
    # than assumed. A card printing "without" is the opposite half of the same
    # event, and an ignored word here would fire it on both.
    wanted = payload.get("activated_requires_tap")
    if wanted is not None:
        if bool(event.payload.get("requires_tap")) != (wanted == "with"):
            return False
    return True


# The printed recipient of a damage event, as `engine/oracle.py`'s table
# captures it, mapped to the question the filter asks of the event. Absent
# means the card named no recipient and every one qualifies.
#
# Each takes the recipient and the seat it belongs to — its own for a player,
# its controller's for a permanent, which is the key Garruk's Harbinger's
# walker half already read — plus the observing permanent's seat, because
# "you" and "an opponent" are CR 109.5 questions about the trigger's own
# controller.
#: What each printed recipient word means, tested against the event's recipient
#: and the seat that took the damage.
#:
#: Every row takes the *game* as well, and only one row reads it — "defending
#: player" is the one word here that names a relation to the **combat** rather
#: than to the ability's controller, and no fact carried on the event can
#: answer it. A widened signature rather than a second table or a parked
#: reference: five rows ignoring an argument is cheaper than two tables that can
#: disagree about which words this engine tests.
_DAMAGE_RECIPIENT_TESTS = {
    "a player": lambda game, recipient, seat, observer: _is_player(recipient),
    "an opponent": lambda game, recipient, seat, observer: (
        _is_player(recipient) and seat != observer
    ),
    "you": lambda game, recipient, seat, observer: (
        _is_player(recipient) and seat == observer
    ),
    "a planeswalker": lambda game, recipient, seat, observer: _is_walker(recipient),
    "a player or planeswalker": lambda game, recipient, seat, observer: (
        _is_player(recipient) or _is_walker(recipient)
    ),
    # "…deals combat damage to **defending player**" (Electryte). CR 506.2: the
    # player the attack was declared against. Deliberately not a spelling of
    # "an opponent" — in a multiplayer game an attacker's controller has
    # opponents who are not defending this combat, and the printed word names
    # exactly the one who is. Outside combat there is no such seat and the word
    # matches nothing, which is the honest answer for a condition that also
    # requires combat damage.
    "defending player": lambda game, recipient, seat, observer: (
        _is_player(recipient)
        and seat is not None
        and seat == getattr(game, "combat_defending_player_index", None)
    ),
}


#: The bare seat words a recipient union may end with, mapped to the spelling
#: :data:`_DAMAGE_RECIPIENT_TESTS` is keyed by. "a creature **or opponent**"
#: (Flesh Reaver) is "an opponent" with the article left out because the phrase
#: in front of it already carried one.
_SUFFIX_SEAT_WORDS = {"opponent": "an opponent", "you": "you"}


def _is_player(recipient) -> bool:
    """Whether a damage event's recipient is a player rather than a permanent.

    The import is deferred because this module keeps ``models`` under
    ``TYPE_CHECKING`` — ``damage_kind`` in `engine/damage_events.py` asks the
    same question the same way, and the two are the only readings of it.
    """
    from .models import PlayerState

    return isinstance(recipient, PlayerState)


def _is_walker(recipient) -> bool:
    return not _is_player(recipient) and bool(
        getattr(recipient, "has_type", None) and recipient.has_type("planeswalker")
    )


@event_filter("damage_dealt")
def _damage_dealt_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """CR 120.4b's event, narrowed by what the card printed on either side of
    the verb.

    One dispatcher for what was five conditions and three fire sites. Both
    halves are read off the trigger's own parsed condition — who dealt the
    damage and who took it — so the "combat" in Jeskai Elder's line and the
    "to you" in Backfire's are data rather than a choice of where to announce
    from. The observer for "you"/"an opponent" is this permanent's own
    controller (CR 109.5), never anything the event carries.
    """
    payload = trig.condition.payload
    observer = game.controller_index_of(permanent)
    combat = payload.get("damage_combat")
    if combat == "combat" and not event.payload.get("combat"):
        return False
    if combat == "noncombat" and event.payload.get("combat"):
        return False

    damager = event.subject
    if payload.get("damager_self"):
        # "**This** creature deals damage" — by identity, because a look-alike
        # on the same battlefield is a different permanent.
        if damager is not permanent:
            return False
    elif payload.get("damager_attached"):
        if permanent.metadata.get("attached_to") is not damager:
            return False
    elif payload.get("damager_controller") == "you":
        # "A source you control" is a seat question, and deliberately not a
        # permanent one: a spell is a source too (CR 109.5), and the seam
        # derives the seat for both.
        if event.payload.get("damager_seat") != observer:
            return False
    elif "damager_any" in payload:
        # "Whenever **a source** deals damage to this creature" (Crag Saurian);
        # "Whenever **you're dealt damage**" (Blood Hound), which is the same
        # thing said by leaving the damager out of the sentence entirely.
        #
        # Tested by **presence**, not by truthiness: the passive row carries the
        # marker as an empty named group — this table's documented idiom for a
        # narrowing a row states by matching rather than by capturing text — and
        # an empty string is falsy, so a truthiness test sent the one card that
        # prints no damager at all down to the `else` that refuses.
        #
        # No narrowing on the damager at all: CR 109.5's "source" is a spell, an
        # ability or a permanent, and the card watches every one of them. The
        # *recipient* half below is what keeps this from firing on the whole
        # board — which is why this branch is a marker the table produces rather
        # than the absence of one, and why the `else` beneath still refuses.
        pass
    elif "damager_filter" in payload:
        # A noun phrase describes *permanents*, and a damage source need not be
        # one: for a spell it is the printed card (CR 109.5), which has no
        # controller, no types the layers have computed and nothing the matcher
        # can ask. So a card is simply not in the set the phrase names — the
        # same answer the retired planeswalker fire site gave by refusing to
        # announce at all, kept here where the phrase is instead of where the
        # damage is.
        if getattr(damager, "permanent_id", None) is None:
            # …unless the card *said* "or spell" (Justice). Then the union names
            # the spell half explicitly, and the only word that distributes onto
            # it is the colour — the condition table refuses the phrase outright
            # when it says anything else (`_SPELL_UNION_FILTER_KEYS`), so there
            # is exactly one thing left to test here.
            #
            # Read off the printed card, **not** through the damage-source
            # colour Ghostly Flame overrides: that static makes a red spell a
            # *colorless source of damage* and leaves the spell red, and this
            # sentence asks about the spell.
            if damager is None or not payload.get("damager_includes_spells"):
                return False
            colour = payload["damager_filter"].get("color_filter")
            if colour not in (getattr(damager, "colors", ()) or ()):
                return False
        elif not trigger_subject_matches(
            game, trig, "damager", damager, observer=observer, source=permanent,
        ):
            return False
    else:
        # No narrowing at all would fire every such trigger on the board for
        # every point of damage in the game. The condition table cannot produce
        # one; refusing here is the second lock rather than an unreachable
        # branch's cost.
        return False

    recipient = event.payload.get("recipient")
    seat = event.payload.get("defending_player_index")
    if payload.get("damaged_self"):
        # "Whenever a source deals damage **to this creature**" (Crag Saurian).
        # The recipient is the very permanent whose ability this is, by
        # identity — a look-alike on the same battlefield is a different
        # permanent (CR 400.7), and this card hands *itself* over, so matching
        # by value would give away the wrong Saurian.
        #
        # Asked before every other recipient reading and returning outright,
        # because none of them can express it: a marker is not a filter, and
        # falling through to "no narrowing printed" would fire this on every
        # point of damage in the game.
        return recipient is permanent
    # "…deals damage to **you or a white creature you control**" (Mangara's
    # Equity). A recipient the sentence describes two ways: one seat word and
    # one noun phrase. Whichever the event's recipient *is* decides which half
    # answers, so the two are not ANDed — a player is never a creature you
    # control, and a creature is never a seat.
    #
    # Read before the fixed-word test below, and never beside it: the two keys
    # cannot both be present (the regex alternates), and asking the union first
    # is what keeps a union payload from falling through to "no narrowing" and
    # firing on every point of damage in the game.
    union_seat = payload.get("damage_recipient_seat")
    if union_seat is None:
        # "…to a creature **or opponent**" (Flesh Reaver). The seat half printed
        # after the noun phrase, where English drops its article — folded to the
        # spelling the seat-first arm produces so both word orders reach the one
        # test below rather than growing a second branch that could disagree.
        union_seat = _SUFFIX_SEAT_WORDS.get(
            payload.get("damage_recipient_seat_after")
        )
    if union_seat is not None:
        if _is_player(recipient):
            return bool(
                _DAMAGE_RECIPIENT_TESTS[union_seat](game, recipient, seat, observer)
            )
        return trigger_subject_matches(
            game, trig, "damaged", recipient, observer=observer, source=permanent,
        )
    test = _DAMAGE_RECIPIENT_TESTS.get(payload.get("damage_recipient"))
    if test is None:
        # "…deals damage **to a creature**" (Bellowing Fiend). A recipient
        # described by a noun phrase and by no seat word at all — so it is
        # neither of the two branches above, and it must not fall through to
        # "no narrowing printed", which fires on every point of damage the card
        # narrows away.
        #
        # A noun phrase never names a seat: the words that do are the fixed list
        # this test came from. So a player recipient is simply not in the set the
        # phrase describes, which is the same answer the damager half gives a
        # spell it cannot ask about.
        if "damaged_filter" in payload:
            if _is_player(recipient):
                return False
            return trigger_subject_matches(
                game, trig, "damaged", recipient,
                observer=observer, source=permanent,
            )
        return True
    return bool(test(game, recipient, seat, observer))


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
    # "Whenever **you** lose life" (Oath of Lim-Dûl). The mirror of the gain
    # above and scoped the same way: an opponent's life leaving them is not
    # this enchantment's controller losing any.
    "you_lose_life",
    "draws_second_card",
    "you_sacrifice_permanent",
    # "Whenever a spell **you've cast** is countered" (Multani's Presence).
    # The seat is the *caster* of the countered spell, which is the only seat
    # the announcement could carry — CR 108.4 gives the card in the graveyard
    # no controller by the time anything reads it, and CR 603.10e says an
    # ability triggering on a countering looks back in time, so the seat has to
    # travel on the event rather than be re-derived from the object.
    "your_spell_countered",
})


@event_filter(*_SEAT_SCOPED_EVENTS)
def _seat_scoped_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever **you** gain life / draw your second card / sacrifice a
    permanent" — only the acting seat's own permanents."""
    seat = event.payload.get("seat")
    return seat is not None and game.controller_index_of(permanent) == seat


@event_filter("land_played")
def _land_played_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever **an opponent** plays a land" (Dirtcowl Wurm).

    The seat half of :func:`_draws_card_filter` below, word for word and for
    its reason: one game-wide announcement, made at CR 305.1's special action,
    with the printed seat as the trigger's own narrowing rather than a second
    event kind. "You" is the permanent's controller (CR 109.5); "an opponent"
    is any *other* seat, which is what makes the unnarrowed reading wrong in a
    three-player game rather than merely inverted.

    An announcement with no seat on it fires nothing, which is the safe
    direction: a land play whose player nobody recorded cannot be compared
    against the word the card printed.
    """
    seat = event.payload.get("seat")
    if seat is None:
        return False
    observer = game.controller_index_of(permanent)
    if observer is None:
        return False
    if trig.condition.payload.get("other_land"):
        # "When you play **another** land" (City of Traitors) — CR 109.2's
        # "another" is "not this object", and a land watching land drops is on
        # the battlefield by the time its own play is announced
        # (``_process_land_enters`` runs first), so without this the card would
        # sacrifice itself the moment it arrived.
        #
        # Compared by ``permanent_id`` rather than by the played card: a deck
        # repeats one immutable ``CardDefinition`` per copy, so a second City of
        # Traitors would be the *same* object as the first and the exclusion
        # would suppress a trigger the card makes. An announcement carrying no
        # id fires nothing, which is this filter's own safe direction one
        # narrowing up.
        played = event.payload.get("played_permanent_id")
        if played is None or played == permanent.permanent_id:
            return False
    # "…plays a **nonbasic** land" (Hidden Herd). CR 205.4a's supertype read
    # off the card that was played, which is what the announcement carries as
    # its subject — the permanent it became is already on the battlefield and
    # would answer through the layers, but a land whose supertype an effect
    # changed between the play and this check is a card nobody prints and the
    # printed line is what the trigger names.
    #
    # An announcement with no card on it fires nothing, the same safe direction
    # the seat check above takes.
    wanted_supertype = trig.condition.payload.get("played_land_supertype")
    if wanted_supertype:
        from .layer_bridge import printed_supertypes

        played_card = event.subject
        if played_card is None or not hasattr(played_card, "type_line"):
            return False
        basic = "basic" in printed_supertypes(played_card.type_line)
        if basic != (wanted_supertype == "basic"):
            return False
    land_player = trig.condition.payload.get("land_player")
    if land_player == "an opponent":
        return seat != observer
    if land_player == "a player":
        # "Whenever **a player** plays a land" (Horn of Greed) — unnarrowed, so
        # every seat's land drop fires it, the controller's included. The
        # printed word is the whole narrowing here, exactly as it is one event
        # over in :func:`_draws_card_filter`.
        return True
    return seat == observer


@event_filter("draws_card")
def _draws_card_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever **you** draw a card" (Lorescale Coatl) beside "whenever **an
    opponent** draws a card" (Underworld Dreams).

    One announcement, made game-wide by the draw sweep, and the printed seat is
    the trigger's own narrowing rather than a second event — so this reads the
    condition payload instead of belonging to `_SEAT_SCOPED_EVENTS`, whose whole
    narrowing is the word "you". "You" is the permanent's controller (CR 109.5)
    either way; "an opponent" is any *other* seat, which is what makes the
    unnarrowed reading wrong in a three-player game rather than merely inverted.
    """
    seat = event.payload.get("seat")
    if seat is None:
        return False
    observer = game.controller_index_of(permanent)
    if observer is None:
        return False
    drawer = trig.condition.payload.get("drawer")
    if drawer == "an opponent":
        return seat != observer
    if drawer == "the chosen player":
        # "When **the chosen player** draws a card **with the chosen name**"
        # (Booby Trap). Both narrowings are answered off the permanent's own
        # entry record (CR 614.1c), which is the only place either can be read:
        # the seat was chosen as the artifact entered and the name with it, and
        # neither is anything the announcement could carry.
        #
        # A permanent that recorded nothing names nobody, which is the honest
        # reading of a trap that entered with no opponent to choose — and it is
        # a refusal rather than a fall-back to the controller, who is the one
        # seat this card cannot be aimed at.
        chosen = permanent.metadata.get("chosen_player_index")
        if not isinstance(chosen, int) or chosen != seat:
            return False
        if not trig.condition.payload.get("drawn_name"):
            return True
        named = str(permanent.metadata.get("chosen_card_name") or "").strip()
        if not named:
            # Nothing was named, so no card answers the description. Not "every
            # card": that would spring the trap on the first draw, which is the
            # opposite of what an empty choice means.
            return False
        return str(event.payload.get("drawn_card_name") or "") == named
    return seat == observer


# ---------------------------------------------------------------------------
# A trigger whose subject is a set of objects
# ---------------------------------------------------------------------------


@event_filter("attackers_declared")
def _attack_declaration_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """A trigger on the attack *declaration* (CR 508.1) — the only announcement
    that can answer "how many creatures attacked".

    Two printed spellings, one event, and the difference between them is
    payload the compiler read off the line rather than two kinds:

    - "Whenever you attack with **two or more creatures with flying**" (Tide
      Skimmer) counts the attackers that answer a noun phrase, so a card printed
      "three or more Zombies" needs nothing here.
    - "Whenever **this creature and at least two** other creatures attack"
      (Makeshift Battalion, under the ability word "Battalion") counts the
      *others*, so the source must itself be among the attackers — by identity,
      because a look-alike in the same declaration is a different permanent.

    "You" is the trigger's own controller in both (CR 109.5), which is what
    leaves the Skimmer silent through an opponent's alpha strike.

    - "Whenever **a player** attacks with one or more creatures" (Total War) is
      the third, and the one that does *not* narrow by seat: any declaration
      wakes it, the ability's controller's included. A third row rather than a
      third kind, because the announcement is the same announcement and only
      the question differs — which is the rule the two rows above already
      follow. The marker is an empty named group in the pattern, so it is read
      by membership rather than by truth.
    """
    seat = game.controller_index_of(permanent)
    if seat is None:
        return False
    payload = trig.condition.payload
    attackers = event.payload.get("attackers") or ()
    if "attackers_defending_you" in payload:
        # "Whenever one or more creatures attack **you**." (Orim's Prayer.) The
        # trigger's controller is CR 506.2's *defending* player, never the
        # attacking one, so the seat test above is the wrong way round for it —
        # and the attackers counted are only the ones aimed here. The rest of
        # this function then asks its ordinary question of that narrowed list,
        # so "one or more" is the default threshold of 1 and a card printing
        # "two or more Zombies attack you" would need no code.
        defenders = event.payload.get("defenders") or ()
        attackers = [
            attacker
            for attacker, defender in zip(attackers, defenders)
            if defender == seat
        ]
        if not attackers:
            return False
    elif "any_attacking_seat" not in payload and seat != event.payload.get("seat"):
        return False
    described = payload.get("attacker_filter")
    if "all_attackers" in payload:
        # "Whenever **all** non-Wall creatures you control attack." (Mob
        # Mentality.) Not a count: the question is whether the set the noun
        # phrase describes and the set that attacked are the same one, so it is
        # asked of the board rather than of the declaration's length — a seat
        # with three Walls and one Bear attacks with one creature and has
        # attacked with all of them.
        #
        # The board is read at the announcement, which is where an attacking
        # creature still is (CR 508.1 has not left combat): `controlled_by` is
        # the control seam, and matching by *identity* against the declaration
        # is what keeps a look-alike of an attacker from standing in for one
        # that stayed home.
        #
        # An empty set does not fire. "All" over nothing is vacuously true and
        # no creature attacked, which is not what the sentence describes; the
        # non-empty check is what says so rather than a count nobody printed.
        eligible = [
            perm
            for perm in game.controlled_by(seat)
            if subject_matches(
                game, perm, described, observer=seat, source=permanent
            )
        ]
        if not eligible:
            return False
        return all(
            any(attacker is perm for attacker in attackers) for perm in eligible
        )
    if "others_count" in payload:
        if not any(attacker is permanent for attacker in attackers):
            return False
        return len(attackers) >= int(payload["others_count"]) + 1
    matching = sum(
        1
        for attacker in attackers
        if subject_matches(game, attacker, described, observer=seat, source=permanent)
    )
    return matching >= int(payload.get("attackers_count", 1))


# The events announced game-wide whose *whole* applicability is the trigger's
# own subject filter, and the payload key each records it under. One filter per
# event, so the registration is a row rather than a predicate.
_SUBJECT_LED_FILTER_KEYS: dict[str, str] = {
    "matching_creature_attacks": "attacker",
    "matching_permanent_enters": "enterer",
    # "Whenever a nontoken creature leaves the battlefield" (Dual Nature). The
    # filter is asked while the subject is still on a battlefield — the fire
    # site collects before the rebuild (CR 603.10a) — so "nontoken creature"
    # is answered by the same layered accessors as every other subject here.
    "matching_permanent_leaves_battlefield": "leaver",
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


#: The two board-wide block events, and which payload key each one's *partner*
#: filter lives under. The combatant's own filter is ``combatant_filter`` on
#: both, exactly as ``engine/oracle.py``'s ``combatant_subject`` group writes it.
_BOARD_WIDE_BLOCK_PARTNER_KEYS = {
    "matching_creature_becomes_blocked": "blocker",
    "matching_creature_blocks": "blocked",
}


@event_filter(*_BOARD_WIDE_BLOCK_PARTNER_KEYS)
def _board_wide_block_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever a creature becomes blocked by a creature with lesser power"
    (No Quarter) — CR 509.1a's pair, both halves described.

    Two noun phrases, and the second is the reason this is not
    ``_subject_led_filter`` with another row: the partner's phrase is answered
    **against the combatant**. "Lesser power" is lesser than the creature on the
    other side of the block, not than the enchantment watching it, so the
    ``source`` handed to the partner's match is the combatant — which is the
    same thing the two source-scoped block scans pass when they test a narrowed
    condition, one screen apart in ``phases/declare_blockers_step.py``.

    The combatant's own phrase takes the ability's source, like every other
    board-wide narrowing: "you control" in it is CR 109.5's, the watcher's seat.

    An unnarrowed condition would fire on every block on the table, which is why
    the compiler refuses a phrase it cannot test rather than admitting an empty
    filter here.
    """
    combatant = event.subject
    partner = game.permanent_by_id(event.payload.get("partner_permanent_id"))
    observer = game.controller_index_of(permanent)
    partner_key = _BOARD_WIDE_BLOCK_PARTNER_KEYS[event.kind]
    # **Which of the two announcements this condition answers to.** The fire
    # site makes both - one per pair, one per creature - because CR 509.3c and
    # CR 509.3d count a bare condition and a narrowed one differently, and the
    # count is what an ``emit`` makes rather than something a filter can undo.
    # So the condition's own partner phrase decides, exactly as it does in the
    # two source-scoped scans, and a trigger answering to both would fire twice
    # on every block.
    narrowed = bool(trig.condition.payload.get(partner_key + "_filter"))
    if narrowed != bool(event.payload.get("pair_announcement")):
        return False
    if not trigger_subject_matches(
        game, trig, "combatant", combatant, observer=observer, source=permanent,
    ):
        return False
    if not narrowed:
        # Nothing to ask about the other side: the only phrase the card printed
        # was about the creature the event is *about*, and the line above has
        # already tested it.
        return True
    return trigger_subject_matches(
        game, trig, partner_key, partner,
        observer=observer, source=combatant,
    )


# The one event narrowed on **both** axes: the actor and the object. "Whenever
# **you** activate a loyalty ability of **a Chandra planeswalker**" (Keral Keep
# Disciples) is the seat scoping of `_SEAT_SCOPED_EVENTS` — CR 109.5's "you",
# the trigger's own controller — over the subject filter of
# `_SUBJECT_LED_FILTER_KEYS`, and neither half alone is the card: without the
# seat, an opponent ticking up their own Chandra pings them for you; without the
# filter, any planeswalker does. One predicate rather than a third table,
# because there is one card; a second one makes the pair a row.
@event_filter("you_activate_loyalty_ability")
def _loyalty_activation_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever you activate a loyalty ability of a Chandra planeswalker …"

    Announced from the CR 606.4 payment in ``mixins/stack/activation.py`` — the
    loyalty counters moving *is* the activation's cost being paid — and held
    there until the ability is on the stack by ``deferring_triggers``, so the
    trigger sits above it (CR 603.3) and resolves first.
    """
    seat = event.payload.get("seat")
    if seat is None or game.controller_index_of(permanent) != seat:
        return False
    return trigger_subject_matches(
        game, trig, "walker", event.subject, observer=seat, source=permanent,
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
