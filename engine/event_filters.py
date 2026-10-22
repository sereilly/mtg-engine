"""Applicability filters for every announced event but a cast.

``engine/events.py`` is the bus: game code announces what happened and every
permanent whose compiled trigger names that kind is collected. Whether one
permanent's trigger answers one event is a second question, asked per kind by a
predicate registered with ``events.event_filter`` — and the answer is read off
the trigger's own condition payload, because a narrowing is data, not a kind:
"an opponent controls", "with flying" and "defending player" ride the condition
the compiler wrote, and one filter tests them for every card printing the
kind.

The cast family is ``engine/cast_event_filters.py``. This module is the rest,
in the order the bus grew them: a card moving to a graveyard, a cumulative
upkeep left unpaid, an opponent's attack, untapping, targets chosen and
becoming a target, tapping and activating, damage dealt, counters, the events
whose whole narrowing is the word "you", lands played and cards drawn, the
attack and block declarations, loyalty activations and destruction.

Registered at import. ``engine/events.py`` imports this module last, so
importing the bus is what fills ``EVENT_FILTERS``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .subject_filters import subject_matches
from .events import (Event, _controller_of, destroyed_trigger_applies,
                     event_filter, trigger_subject_matches)

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent, PlayerState
    from .oracle_types import ParsedTriggeredAbility


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
    # "…**from your library**" (Pedantic Learning). The one narrowing here that
    # is about where the card came *from*, tested first because it is the
    # cheapest and rules out the most: a discard, a death and a spell finishing
    # all reach this seam with another source zone or none. The seam names the
    # library for every caller that moves a card out of one.
    if "from_library" in payload and event.payload.get("graveyard_from_zone") != "library":
        return False
    described = payload.get("graveyard_card_filter")
    if "your_graveyard" in payload:
        if game.controller_index_of(permanent) != event.payload.get("owner_index"):
            return False
        if not described:
            return True
        # …and the phrase, where the sentence printed one ("a **land** card"):
        # Energy Field's "a card" carries none and returned above.
        from .handlers._filters import _card_matches_filter

        card = event.subject
        return card is not None and _card_matches_filter(
            card, described, game=game,
            owner=game.players[event.payload["owner_index"]],
        )
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
    if "opponent_graveyard" in payload or described:
        watcher = game.controller_index_of(permanent)
        owner = event.payload.get("owner_index")
        if "opponent_graveyard" in payload:
            if watcher is None or owner is None or watcher == owner:
                return False
        if described:
            from .handlers._filters import _card_matches_filter

            card = event.subject
            if card is None or not _card_matches_filter(
                card, described, game=game,
                owner=game.players[owner] if isinstance(owner, int) else None,
            ):
                return False
    return True


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
    from .handlers._filters import _card_matches_filter

    return _card_matches_filter(card, dict(described))


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


@event_filter("player_chooses_targets")
def _player_chooses_targets_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """"Whenever a player chooses one or more targets" (Psychic Battle), and
    the one printed exception to it.

    "Changing targets this way **doesn't trigger abilities of permanents named
    Psychic Battle**." The change *is* a player choosing targets, so it is
    announced like any other (`Game.announce_targets_chosen`) and carries the
    name that must not answer. The comparison is by the observer's
    **effective** name (CR 707.2: a Clone of the enchantment is "named" what it
    copies), against the name the changing permanent had when it made the
    change — two names read off two permanents, neither of them written here.
    """
    from .stack_targets import TARGETS_CHANGED_SILENTLY_FOR

    silenced = event.payload.get(TARGETS_CHANGED_SILENTLY_FOR)
    if silenced is None:
        return True
    return permanent.effective_card.name != silenced


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
    # "Whenever **you** win a coin flip" (Chance Encounter). The seat is the
    # flipper's, which is the only seat that can win it (CR 705.2) — so an
    # opponent winning their own flip, or losing one, leaves this silent.
    "you_win_coin_flip",
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
    if drawer == "a player":
        # "Whenever **a player** draws a card" (Phyrexian Tyranny) — the
        # unnarrowed spelling, so every seat's draw fires it, the controller's
        # own included. The printed word is the whole narrowing, exactly as it
        # is one event over in :func:`_land_played_filter`.
        return True
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
    # "Whenever a creature attacks or blocks" (Powerstone Minefield). One noun
    # phrase and no partner, so it is a row here rather than in the block
    # pair's filter below: the subject is whichever creature was declared, as
    # an attacker (CR 508.1) or as a blocker (CR 509.1), and the announcement
    # at each of those two sites names it.
    "matching_creature_attacks_or_blocks": "combatant",
    "matching_permanent_enters": "enterer",
    # "Whenever a nontoken creature leaves the battlefield" (Dual Nature). The
    # filter is asked while the subject is still on a battlefield — the fire
    # site collects before the rebuild (CR 603.10a) — so "nontoken creature"
    # is answered by the same layered accessors as every other subject here.
    "matching_permanent_leaves_battlefield": "leaver",
    # "Whenever a permanent is returned to a player's hand" (Warped Devotion).
    # Asked while the subject is still on a battlefield for the row above's
    # reason — ``Game.put_card_into_hand`` announces before the caller removes
    # it (CR 603.10a) — so a narrower phrase ("a creature …") is answered by
    # the layered accessors like every other subject here.
    "permanent_returned_to_hand": "returned",
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
    condition, one screen apart in ``phases/block_triggers.py``.

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


@event_filter("permanent_destroyed")
def _permanent_destroyed_filter(
    game: Game, permanent: Permanent, trig: ParsedTriggeredAbility, event: Event
) -> bool:
    """The watcher on the battlefield: its seat is the control seam's."""
    return destroyed_trigger_applies(
        game, permanent, game.controller_index_of(permanent), trig, event,
    )
