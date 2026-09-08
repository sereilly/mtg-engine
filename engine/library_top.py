"""Playing with, and from, the top card of your library.

Three printed permissions that share one question — *what is on top of whose
library, and who may see or play it?* — and each is printed as a static
ability of a permanent (CR 113.6's *default*, not one of its lettered
exceptions: an ability of a permanent functions while it is on the
battlefield), derived from its text while it is there:

* "Play with the top card of your library revealed." (Conspicuous Snoop.) The
  card is a *public* object (CR 400.2): visible to every player.
* "You may look at the top card of your library any time." (Radha.) Visible to
  its controller alone — a different permission from the one above, and the
  weaker one.
* "You may cast <filter> spells from the top of your library." / "…play lands
  from the top of your library." (both cards.) CR 601.3's permission to begin
  casting from somewhere other than the hand.

The third is the one with teeth, and it is deliberately **not** routed through
``engine/cast_permissions.py``: every grant there is an effect's, put on
``game.cast_permissions`` and taken away again, where these are read off the
permanent's own text for as long as it is in play. The same distinction round
114 drew for Demonic Embrace, one zone over.

**One question, two producers.** Every permission above is *derived*: a
permanent prints one, and it stops being true when the permanent stops being
there — nothing to clear, which is what the paragraph that stood here said, and
it is still the whole reason those are not ``CastPermission`` records.

What changed at Urza's Saga is that the first of them can also arrive as an
**effect's grant**. "Shuffle your library, then reveal the top card. Until end
of turn, for as long as that card remains on top of your library, play with the
top card of your library revealed …" (Temporal Aperture) creates the
permission by resolving, so there is no text on a board to read it off and no
permanent whose departure ends it. That is a record with a lifetime, and it
lives here rather than beside the cast permissions because the *question* it
answers is this module's: who may see the top of whose library.
``engine/land_mana_swaps.py`` is the shape — one derived producer, one granted
one, and :func:`top_is_public` the single answer, so no caller has to know
which kind it got.

The grant hangs off the player as an attribute rather than as a
``PlayerState`` field, exactly as ``engine/shields.py`` and
``engine/land_mana_swaps.py`` hang theirs: a second kind of grant needs no new
field and no new clearing line, and the cleanup step's one call expires it.

**Its duration is two durations, and only one of them is swept.** "Until end of
turn" is CR 611.2a's moment and the cleanup sweep ends it; "for as long as that
card remains on top of your library" is CR 611.2b's state and nothing schedules
it at all — :func:`grant_holds` re-asks it on every read, which is the same
non-mechanism ``cast_permissions``' ``while_exiled`` duration already is one
zone over. The two compose because they are answered at different times, which
is why a compound duration needed no representation of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .shields import END_OF_TURN

REVEALED_TEXT = "play with the top card of your library revealed"

#: The condition the *granted* form of that sentence holds under —
#: "…for as long as **that card remains on top of your library**" (Temporal
#: Aperture). CR 611.2b's half of a compound duration: a state something
#: re-asks rather than a moment something sweeps at.
#:
#: Here rather than in the grammar for ``REVEALED_TEXT``'s reason, and the
#: reason ``replacements.REPLACEMENT_LINES`` is where it is: this module is
#: what finally *asks* the condition (:func:`grant_holds`), so the parse side
#: that attaches the clause and the lowering that translates it both name the
#: implementer's own constant, and a rename cannot leave one of them behind.
WHILE_REVEALED_CARD_ON_TOP = "while_revealed_card_on_top"
#: The same reveal scoped to *every* player — "Players play with the top card
#: of their libraries revealed." (Field of Dreams.) One question, two printed
#: scopes: Conspicuous Snoop's form reveals its own controller's top card, this
#: form reveals everyone's from wherever the source stands (CR 401.5).
PLAYERS_REVEALED_TEXT = "players play with the top card of their libraries revealed"
LOOK_ANY_TIME_TEXT = "you may look at the top card of your library any time"

#: "You may cast <filter> spells from the top of your library" — the filter is
#: the printed noun phrase, read by the noun parser like every other narrowing,
#: so a card naming a different tribe or type needs no code here.
_CAST_FROM_TOP = re.compile(
    r"^you may cast (?P<subject>.+?) spells from the top of your library$"
)
_PLAY_LANDS_FROM_TOP = "you may play lands from the top of your library"


def _lines(card) -> list[str]:
    return [
        line.strip().lower().rstrip(".")
        for line in (getattr(card, "oracle_text", "") or "").split("\n")
    ]


def library_top_line(line: str) -> bool:
    """Whether one printed line is one of the permissions above, in full.

    Read by the support gate *and* by the readers below, so what the engine
    carries out and what it claims to have read cannot drift — the same seam
    ``enter_effect_line`` is. The compound spelling ("You may look … , and you
    may play lands …") is one printed line stating two permissions, so it is
    matched as itself rather than split: splitting would claim half a line.
    """
    text = line.strip().lower().rstrip(".")
    if text in (REVEALED_TEXT, PLAYERS_REVEALED_TEXT, LOOK_ANY_TIME_TEXT, _PLAY_LANDS_FROM_TOP):
        return True
    if text == f"{LOOK_ANY_TIME_TEXT}, and {_PLAY_LANDS_FROM_TOP}":
        return True
    if _TOP_GRANTS_ABILITIES.match(text) is not None:
        return True
    return _CAST_FROM_TOP.match(text) is not None


def states_permission(line: str, phrase: str) -> bool:
    """Whether one printed *line* states *phrase* as a clause of its own.

    Every reader below asks this rather than testing the phrase as a substring,
    and the difference is a card. ``top_is_public`` used to look for
    :data:`REVEALED_TEXT` anywhere in a permanent's joined text, which is what
    let Radha's compound line ("You may look …, **and** you may play lands …")
    be read as the two permissions it states — and also what made **Temporal
    Aperture** reveal its controller's top card from the moment it hit the
    battlefield, for ever, because the phrase is printed inside its *activated
    ability*. A permission an effect has to grant was being read as a static
    the artifact already had.

    So the question is asked in two parts. :func:`library_top_line` decides
    whether the **whole line** is one of these permissions at all, which no
    ability line is; then the clause boundary decides which of them it states.
    A phrase surrounded by other words is a card talking *about* the
    permission, not printing it.
    """
    text = line.strip().lower().rstrip(".")
    if not library_top_line(text):
        return False
    return (
        text == phrase
        or text.endswith(f", and {phrase}")
        or text.startswith(f"{phrase}, and ")
    )


@dataclass
class TopRevealGrant:
    """One effect's "play with the top card of your library revealed".

    card       -- the card the CR 611.2b half of the duration is about. The
                  grant holds for as long as *this* card is the library's
                  first, which is why it is stored rather than re-read: the
                  next card up is a different object and the effect is over.
    lifetime   -- END_OF_TURN; the cleanup sweep that clears shields clears
                  these.
    source_name-- the card that armed it, for the log.
    """

    card: object
    lifetime: str = END_OF_TURN
    source_name: str = ""


#: Where the list hangs off a player, for ``engine/shields.py``'s reason: a
#: ``PlayerState`` carries it without learning what a grant is.
_GRANTS_ATTR = "_top_reveal_grants"


def reveal_grants_on(player) -> list[TopRevealGrant]:
    """The granted top-of-library reveals *player* holds, created on first use."""
    records = getattr(player, _GRANTS_ATTR, None)
    if records is None:
        records = []
        setattr(player, _GRANTS_ATTR, records)
    return records


def add_reveal_grant(player, grant: TopRevealGrant) -> TopRevealGrant:
    """Put *grant* on *player* and return it."""
    reveal_grants_on(player).append(grant)
    return grant


def clear_reveal_grants(player, lifetime: str | None = None) -> None:
    """Expire records whose duration has run out — the same shape
    ``shields.clear_shields`` and ``land_mana_swaps.clear_swaps`` have, so a
    turn-step sweep stays one call."""
    records = reveal_grants_on(player)
    records[:] = [r for r in records if lifetime is not None and r.lifetime != lifetime]


def grant_holds(player, grant: TopRevealGrant) -> bool:
    """Whether *grant*'s "for as long as" condition is still true (CR 611.2b).

    Identity, not name: a library repeats one immutable ``CardDefinition`` per
    copy, so a value test would answer "yes" for a second copy that happened to
    be shuffled to the top — a card the effect never revealed.

    Re-asked rather than swept, which is the whole of what a state-shaped
    duration costs: nothing has to notice the card leaving, because nothing
    ever believed anything but this.

    **The gap that leaves is CR 401.6**, and it is named here rather than left
    to be rediscovered: a card that stops being revealed and is then revealed
    again "becomes a new object", so a card that leaves the top of the library
    and returns to it during the turn is not the card this grant is about — and
    a re-asked condition covers it again. Closing that needs the record to end
    when the condition is *observed* false rather than when it is asked, which
    is a sweep at CR 704.3's moment; the engine's two other "for as long as"
    durations (``while_source_tapped``, ``while_source_on_battlefield``) have
    the same shape and the same gap, so it is one change to all three rather
    than a latch on this one.
    """
    library = getattr(player, "library", ())
    return bool(library) and library[0] is grant.card


def top_is_public(game, player_index: int) -> bool:
    """Whether *player_index*'s top card is revealed to everyone (CR 400.2).

    Three producers answer it, and the third is not a permanent's text at all:
    the player's own "Play with the top card of your library revealed."
    (Conspicuous Snoop — read off that player's battlefield alone), "Players
    play with the top card of their libraries revealed." (Field of Dreams —
    anyone's battlefield reveals everyone's), and a live
    :class:`TopRevealGrant` an effect put on this seat (Temporal Aperture).

    The grant is asked first because it is the narrowest and the cheapest — one
    seat, one card, no board scan — where the two scans below compile every
    permanent's text.
    """
    if any(
        grant_holds(game.players[player_index], grant)
        for grant in reveal_grants_on(game.players[player_index])
    ):
        return True
    if any(
        states_permission(line, REVEALED_TEXT)
        for perm in game.controlled_by(player_index)
        for line in _lines(perm.effective_card)
    ):
        return True
    return any(
        PLAYERS_REVEALED_TEXT in _lines(perm.effective_card)
        for perm in game.all_permanents()
    )


def top_is_visible(game, player_index: int) -> bool:
    """Whether *player_index* may see their own top card.

    True when it is revealed to everyone, and also when the weaker
    look-at-any-time permission is in play — a player who may look is a player
    who may see, and the difference between the two is only who *else* can.
    """
    if top_is_public(game, player_index):
        return True
    return any(
        states_permission(line, LOOK_ANY_TIME_TEXT)
        for perm in game.controlled_by(player_index)
        for line in _lines(perm.effective_card)
    )


def top_castable(game, player_index: int, card) -> bool:
    """Whether *card*, on top of *player_index*'s library, may be cast or played
    from there right now.

    Two printed permissions answer this — a narrowed cast ("Goblin spells") and
    a land play — and both are asked of the *card on top*, never of a card the
    caller merely names: CR 601.3 opens the top of the library, not the library.
    """
    from .subject_filters import card_matches_any

    library = game.players[player_index].library
    if not library or library[0] is not card:
        return False
    for perm in game.controlled_by(player_index):
        for line in _lines(perm.effective_card):
            # The clause, whether printed alone or as the second half of the
            # compound line Radha carries ("You may look …, and you may play
            # lands …"). One printed line stating two permissions grants both,
            # so the reader asks whether the clause is *in* it — matched at a
            # clause boundary, not as a bare substring, so a line merely
            # mentioning the words does not grant it.
            if states_permission(line, _PLAY_LANDS_FROM_TOP) and "land" in (
                card.type_line or ""
            ).lower():
                return True
            match = _CAST_FROM_TOP.match(line)
            if match is None:
                continue
            described = _filter_for(match.group("subject"))
            if described is not None and card_matches_any(card, (described,)):
                return True
    return False


#: "As long as the top card of your library is a <filter> card, this creature
#: has all activated abilities of that card." (Conspicuous Snoop.) A layer-6
#: grant whose source is not a permanent at all but the card on top — so it is
#: recomputed on every read rather than stamped: the library changes underneath
#: it constantly, and a stamped grant would go stale on the next draw.
_TOP_GRANTS_ABILITIES = re.compile(
    r"^as long as the top card of your library is (?P<subject>.+?) card, "
    r"this creature has all activated abilities of that card$"
)


def granted_top_abilities(game, permanent) -> tuple[str, ...]:
    """The activated-ability lines *permanent* currently has from the top card.

    Empty unless the permanent prints the clause *and* the top card answers its
    filter. Only the **activated** lines are taken, because that is what the
    card says: a Goblin with a triggered ability on top grants nothing, and
    handing over the whole text would give the Snoop abilities it never had.
    """
    from .subject_filters import card_matches_any

    seat = game.controller_index_of(permanent)
    if seat is None:
        return ()
    library = game.players[seat].library
    if not library:
        return ()
    top = library[0]
    granted: list[str] = []
    for line in _lines(permanent.effective_card):
        match = _TOP_GRANTS_ABILITIES.match(line)
        if match is None:
            continue
        described = _filter_for(match.group("subject").removeprefix("a ").removeprefix("an "))
        if described is None or not card_matches_any(top, (described,)):
            continue
        granted.extend(
            raw.strip()
            for raw in (top.oracle_text or "").splitlines()
            if ":" in raw and not raw.strip().lower().startswith("when")
        )
    return tuple(granted)


def _filter_for(phrase: str) -> dict | None:
    """The printed noun phrase as a card-filter payload, or None to refuse.

    Through the grammar's own reader, so "Goblin spells" and "artifact spells"
    are one rule — and a phrase the card matcher cannot answer refuses rather
    than opening the top of the library to everything.
    """
    from .grammar import card_filter_payload

    return card_filter_payload(f"a {phrase} card")


__all__ = [
    "END_OF_TURN",
    "LOOK_ANY_TIME_TEXT",
    "TopRevealGrant",
    "WHILE_REVEALED_CARD_ON_TOP",
    "add_reveal_grant",
    "clear_reveal_grants",
    "grant_holds",
    "PLAYERS_REVEALED_TEXT",
    "REVEALED_TEXT",
    "granted_top_abilities",
    "library_top_line",
    "reveal_grants_on",
    "states_permission",
    "top_castable",
    "top_is_public",
    "top_is_visible",
]
