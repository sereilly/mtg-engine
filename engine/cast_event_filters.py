"""Applicability filters for the cast events: "whenever a player casts …".

``engine/events.py`` is the bus: game code announces what happened and every
permanent whose compiled trigger names that kind is collected. Whether one
permanent's trigger answers one event is a second question, asked per kind by a
predicate registered with ``events.event_filter``. This module holds that
family's predicates for one kind of event: a spell becoming cast (CR 601.2i)
and a card being played — by its caster, by an opponent, by anyone, the Nth
spell of a turn, this spell itself.

Every printed narrowing of the cast is asked of one reader,
:func:`_cast_narrowing_admits` — a colour, a colour union, a type, a subtype,
"that doesn't share a color with a creature you control" — because a narrowing
one cast scope asked and another did not was a trigger that fired more often
than its card allows, and because "your first instant or sorcery spell each
turn" has to count the same set its trigger fires on. Every other event's
filters are ``engine/event_filters.py``.

Registered at import. ``engine/events.py`` imports this module last, so
importing the bus is what fills ``EVENT_FILTERS``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .subject_filters import subject_matches
from .events import Event, _controller_of, event_filter

if TYPE_CHECKING:
    from .game import Game
    from .models import CardDefinition, Permanent
    from .oracle_types import ParsedTriggeredAbility


_COLOR_SYMBOLS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}


def _cast_card(event: Event) -> CardDefinition | None:
    card = event.subject
    return card if card is not None and hasattr(card, "colors") else None


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
    # "Whenever a player **kicks** a spell" (Saproling Infestation). The cast
    # event narrowed by CR 702.33d's fact about the cast, which the
    # announcement carries (``_apply_spell_cast_any_triggers``) because it is
    # settled there and nowhere on the card. Asked first: a spell that was not
    # kicked answers no whatever else the trigger prints.
    if "cast_kicked" in trig.condition.payload and not event.payload.get("kicked"):
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
    # "…cast a **nonred** spell" (Dwarven Patrol). The colour rows above with
    # the answer turned over, and over the same effective colours: a red-green
    # spell *is* red (CR 105.2b) and does not answer, a colourless one is not
    # and does (CR 105.2c) -- and a land is not a spell, so playing one never
    # reaches here at all (the card's own ruling).
    excluded_colour = trig.condition.payload.get("cast_excluded_color")
    if excluded_colour and _COLOR_SYMBOLS.get(excluded_colour) in _cast_colors(
        game, card, caster
    ):
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
    # "…a **Dog** spell" (Rin and Seri). The printed subtype, read through the
    # same reader the layer seed uses rather than as a substring of the type
    # line — a substring match would let "Dog" answer for a "Dogpile", and would
    # answer for a card *type* word too, which is the `cast_type` row's job.
    cast_subtype = trig.condition.payload.get("cast_subtype")
    if cast_subtype:
        from .layer_bridge import printed_shape

        _, subtypes = printed_shape(card)
        if cast_subtype.lower() not in subtypes:
            return False
    return True


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
    # Every printed narrowing of the cast — a colour, a colour list, a type, a
    # union of types, a subtype — is asked of the one helper the other two cast
    # scopes ask. This filter used to test four of them inline and none of the
    # rest, so a narrowing the table carried on this scope and the helper
    # alone read was dropped here in silence: "whenever you cast a
    # **multicolored** spell" fired on every spell its controller cast.
    if not _cast_narrowing_admits(game, permanent, trig, card, caster_index):
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
