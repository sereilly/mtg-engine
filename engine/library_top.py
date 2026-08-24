"""Playing with, and from, the top card of your library.

Three printed permissions that share one question — *what is on top of whose
library, and who may see or play it?* — and each is a static ability of a
permanent (CR 113.6d), derived from its text while it is on the battlefield:

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

Nothing here stores state. A permission that ended when its source left would
need clearing; one that is *derived* simply stops being true.
"""

from __future__ import annotations

import re

REVEALED_TEXT = "play with the top card of your library revealed"
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


def top_is_public(game, player_index: int) -> bool:
    """Whether *player_index*'s top card is revealed to everyone (CR 400.2).

    Two printed scopes answer it: the player's own "Play with the top card of
    your library revealed." (Conspicuous Snoop — read off that player's
    battlefield alone), and "Players play with the top card of their libraries
    revealed." (Field of Dreams — anyone's battlefield reveals everyone's).
    """
    if any(
        REVEALED_TEXT in " ".join(_lines(perm.effective_card))
        for perm in game.controlled_by(player_index)
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
        LOOK_ANY_TIME_TEXT in " ".join(_lines(perm.effective_card))
        for perm in game.controlled_by(player_index)
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
            if (
                line == _PLAY_LANDS_FROM_TOP
                or line.endswith(f", and {_PLAY_LANDS_FROM_TOP}")
            ) and "land" in (card.type_line or "").lower():
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
    "LOOK_ANY_TIME_TEXT",
    "PLAYERS_REVEALED_TEXT",
    "REVEALED_TEXT",
    "granted_top_abilities",
    "library_top_line",
    "top_castable",
    "top_is_public",
    "top_is_visible",
]
