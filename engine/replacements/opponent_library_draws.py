"""A draw replaced by an exile off an **opponent's** library (Shared Fate).

"If a player would draw a card, that player exiles the top card of one of
their opponents' libraries face down instead." Every player's draws, from a
permanent any seat may control, so the sources are the whole board's — and
mandatory: "Replacing your draws isn't optional. You can't draw cards from
your own library, even if all your opponents' libraries are empty." (Ruling
2004-12-01.) An empty library exiled from is simply nothing exiled; no draw
was attempted, so CR 704.5b has nothing to see.

Each card exiled goes into its **owner's** exile pile (the engine keeps one
per player) face down (CR 406.3) and is linked to the permanent it was exiled
with (CR 607.2a,
``engine/linked_exile.py``) **with the seat that exiled it**, because what the
enchantment's second ability lets a player look at and play is "cards *they*
exiled with this enchantment" (``engine/exiler_grants.py``). The log counts
the card and never names it: ``game.log`` is every seat's.

"If more than one Shared Fate is on the battlefield, you choose which one
replaces each card draw, but you can replace a draw only once." (Ruling
2004-12-01.) One instance per permanent (CR 616.1e asks the drawer which), and
the draw is consumed by whichever applies — so the second never sees it.

Where the drawer has several opponents, which one's library is the drawer's
choice (``opponent_library_draw``, a CR 614 offer). With one, nothing is
asked.

**The drawer's own card, face up** (Uba Mask, at the foot of the file): "If a
player would draw a card, that player exiles that card face up instead." The
same shape with nothing to choose — "that card" is the one the draw would
have taken, the top of the drawer's own library — exiled face up, linked with
its exiler **and the turn** (``exiler_grants.EXILED_TURN_KEY``), because the
Mask's second line lets each player play "cards they exiled with this
artifact this turn". An empty library exiles nothing and loses nothing: CR
614.11 applies a draw replacement even when no card could be drawn, and the
draw it replaced was never attempted (CR 704.5b).
"""

from __future__ import annotations

from ..replacement_choices import (ReplacementChoice, offer_replacement_choice,
                                   replacement_choice)
from .draws import QUEUED_EXCLUDES, draws_behind, queued_excludes
from .registry import (DRAW_EXILED_FACE_UP, DRAW_EXILES_OPPONENT_TOP,
                       ReplacementOutcome, replacement_effect)


#: The phrase the interceptor self-selects on, imported by ``lines.py``'s
#: ``REPLACEMENT_LINES`` so the claim and the interceptor are one string.
OPPONENT_LIBRARY_DRAW_TEXT = (
    "if a player would draw a card, that player exiles the top card of one of "
    "their opponents' libraries face down instead"
)


def opponent_library_draw_line(line: str) -> bool:
    """Whether *line* is, in full, the replacement above."""
    return (
        " ".join((line or "").split()).strip().lower().rstrip(".")
        == OPPONENT_LIBRARY_DRAW_TEXT
    )


def _opponent_library_draw_sources(game, payload: dict) -> list:
    """Every permanent on the battlefield printing the replacement, less those
    this event has already been through (CR 614.5). "**A** player" names every
    seat, so the whole board is asked, not the drawer's side. Read off
    ``effective_card`` (CR 707.2, 612.1). Pure."""
    exclude = set(payload.get("exclude_sources") or ())
    return [
        permanent
        for permanent in game.all_permanents()
        if permanent.permanent_id not in exclude
        and any(
            opponent_library_draw_line(line)
            for line in (permanent.effective_card.oracle_text or "").splitlines()
        )
    ]


def _opponent_library_draw_instances(game, payload: dict) -> list:
    """One CR 616.1 instance per permanent printing it: two Shared Fates are
    two effects, and the drawer picks which replaces each draw. Pure."""
    return [
        (str(permanent.permanent_id), permanent.card.name)
        for permanent in _opponent_library_draw_sources(game, payload)
    ]


def _applies_opponent_library_draw(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(
        _opponent_library_draw_sources(game, payload)
    )


def _default_opponent(game, seat: int, opponents: list[int]) -> int:
    """Which opponent a seat nobody asks exiles from, weighed by the one
    thing about the choice the drawer may know: how many cards each library
    holds (CR 402.3's count, one zone over — a library's size is public).

    A library with a card first — a card exiled is a card the drawer may
    play, and an empty library gives nothing — and among those the
    **smallest**: the card itself is the same unknown from any library, so
    what the choice decides is whose library runs down, and the opponent
    nearest to running out is the one a draw they cannot replace will cost
    the game once the enchantment is gone. Ties go in turn order from the
    drawer. Every library empty, the first opponent: nothing is exiled
    either way."""
    count = len(game.players)
    ordered = sorted(opponents, key=lambda other: (other - seat) % count)
    holding = [other for other in ordered if game.players[other].library]
    if not holding:
        return ordered[0]
    return min(holding, key=lambda other: len(game.players[other].library))


def exile_opponent_top_for_draw(game, source, drawer_seat: int, opponent_seat) -> None:
    """Exile the top card of *opponent_seat*'s library face down, linked to
    *source* with *drawer_seat* as its exiler. Nothing to exile — no opponent,
    or an empty library — is nothing done (CR 614.6, 609.3)."""
    from ..linked_exile import keep_face_down_after_departure, link_exiled_card

    drawer = game.players[drawer_seat]
    by = source.card.name
    if opponent_seat is None:
        game.log.append(f"{drawer.name} has no opponent to exile from ({by})")
        return
    opponent = game.players[opponent_seat]
    if not opponent.library:
        game.log.append(
            f"{drawer.name} exiles nothing instead of drawing: "
            f"{opponent.name}'s library is empty ({by})"
        )
        return
    held = game.put_card_into_exile(opponent, opponent.library.pop(0))
    link_exiled_card(
        source, held, opponent_seat, face_down=True, exiler_index=drawer_seat,
    )
    if not game.is_on_battlefield(source):
        # The permanent left while the drawer chose an opponent (CR 614.1
        # applied the replacement when it was offered): the card is still
        # exiled face down, and with nobody's static left to show it.
        keep_face_down_after_departure(game, source)
    game.log.append(
        f"{drawer.name} exiles the top card of {opponent.name}'s library face "
        f"down instead of drawing ({by})"
    )


@replacement_effect(
    "draw", DRAW_EXILES_OPPONENT_TOP, applies=_applies_opponent_library_draw,
    sources=_opponent_library_draw_sources,
    instances=_opponent_library_draw_instances,
    label="Exile the top card of an opponent's library face down instead",
)
def _exile_opponent_top_instead_of_drawing(
    game, payload: dict, instance: str | None = None,
) -> ReplacementOutcome | None:
    """Shared Fate: one draw at a time (CR 121.2), each consumed whole. The
    draws queued behind this one go back through the seam, where each is
    replaced again — by this permanent or, CR 616.1e, another.

    Nothing is drawn, so this reports 0 and "whenever you draw a card" sees
    no draw."""
    player = payload["player"]
    seat = game.players.index(player)
    sources = _opponent_library_draw_sources(game, payload)
    source = next(
        (
            permanent for permanent in sources
            if instance is not None and str(permanent.permanent_id) == instance
        ),
        sources[0],
    )
    opponents = game.opponents_of(seat)
    remaining = int(payload["count"]) - 1
    if len(opponents) > 1:
        default_seat = _default_opponent(game, seat, opponents)
        suspended, drawn = offer_replacement_choice(
            game,
            ReplacementChoice(
                kind="opponent_library_draw",
                player_index=seat,
                options=tuple(game.players[other].name for other in opponents),
                default_option=opponents.index(default_seat),
                data={
                    "opponent_seats": list(opponents),
                    "source_id": source.permanent_id,
                    # The object itself, engine-private: the replacement was
                    # applied as it was offered (CR 614.1), so its record is
                    # this permanent's even if it leaves while the drawer
                    # chooses.
                    "_source": source,
                    "source_name": source.card.name,
                    "remaining_draws": remaining,
                    QUEUED_EXCLUDES: queued_excludes(payload),
                },
            ),
        )
        if suspended:
            game.log.append(
                f"{player.name} chooses an opponent whose top card to exile "
                f"instead of drawing ({source.card.name})"
            )
        payload["drawn"] = drawn
        return ReplacementOutcome(replaced=True)
    exile_opponent_top_for_draw(
        game, source, seat, opponents[0] if opponents else None,
    )
    payload["drawn"] = draws_behind(game, player, remaining, queued_excludes(payload))
    return ReplacementOutcome(replaced=True)


@replacement_choice("opponent_library_draw")
def _resolve_opponent_library_draw(
    game, choice: ReplacementChoice, option_index: int,
) -> int:
    """Exile from the chosen opponent's library, then make the draws queued
    behind this one. Zero cards drawn: the draw was replaced."""
    seats = list(choice.data.get("opponent_seats") or ())
    chosen = seats[option_index] if 0 <= option_index < len(seats) else None
    exile_opponent_top_for_draw(
        game, choice.data["_source"], choice.player_index, chosen,
    )
    return draws_behind(
        game, game.players[choice.player_index],
        int(choice.data.get("remaining_draws", 0)),
        choice.data.get(QUEUED_EXCLUDES) or (),
    )


#: "If a player would draw a card, that player exiles that card face up
#: instead." (Uba Mask.) The phrase the interceptor self-selects on, imported
#: by ``lines.py``'s ``REPLACEMENT_LINES`` so the claim and the interceptor
#: are one string.
FACE_UP_DRAW_EXILE_TEXT = (
    "if a player would draw a card, that player exiles that card face up instead"
)


def face_up_draw_exile_line(line: str) -> bool:
    """Whether *line* is, in full, Uba Mask's replacement."""
    return (
        " ".join((line or "").split()).strip().lower().rstrip(".")
        == FACE_UP_DRAW_EXILE_TEXT
    )


def _face_up_draw_exile_sources(game, payload: dict) -> list:
    """Every permanent on the battlefield printing Uba Mask's replacement,
    less those this event has already been through (CR 614.5). "**A** player"
    names every seat, so the whole board is asked. Read off ``effective_card``
    (CR 707.2, 612.1). Pure."""
    exclude = set(payload.get("exclude_sources") or ())
    return [
        permanent
        for permanent in game.all_permanents()
        if permanent.permanent_id not in exclude
        and any(
            face_up_draw_exile_line(line)
            for line in (permanent.effective_card.oracle_text or "").splitlines()
        )
    ]


def _face_up_draw_exile_instances(game, payload: dict) -> list:
    """One CR 616.1 instance per Mask: two Masks are two effects, and the
    drawer picks which replaces each draw (CR 616.1e) — the card is linked to
    that one, and only that one's second line lets it be played. Pure."""
    return [
        (str(permanent.permanent_id), permanent.card.name)
        for permanent in _face_up_draw_exile_sources(game, payload)
    ]


def _applies_face_up_draw_exile(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(
        _face_up_draw_exile_sources(game, payload)
    )


def exile_drawn_card_face_up(game, source, drawer_seat: int) -> None:
    """Exile the top card of *drawer_seat*'s library — the card the draw would
    have taken — face up, linked to *source* with *drawer_seat* as its exiler
    and stamped with the turn being taken. Nothing to exile is nothing done
    (CR 614.11: the replacement applies to a draw from an empty library, and
    the draw it replaced was never attempted)."""
    from ..linked_exile import link_exiled_card
    from ..turn_state import current_turn_stamp

    drawer = game.players[drawer_seat]
    by = source.card.name
    if not drawer.library:
        game.log.append(
            f"{drawer.name} exiles nothing instead of drawing: their library "
            f"is empty ({by})"
        )
        return
    held = game.put_card_into_exile(drawer, drawer.library.pop(0))
    link_exiled_card(
        source, held, drawer_seat, exiler_index=drawer_seat,
        exiled_turn=current_turn_stamp(game),
    )
    # Face up (CR 406.3), so every seat may see it and the log may name it.
    game.log.append(f"{drawer.name} exiles {held.name} face up instead of drawing ({by})")


@replacement_effect(
    "draw", DRAW_EXILED_FACE_UP, applies=_applies_face_up_draw_exile,
    sources=_face_up_draw_exile_sources,
    instances=_face_up_draw_exile_instances,
    label="Exile that card face up instead",
)
def _exile_drawn_card_face_up_instead(
    game, payload: dict, instance: str | None = None,
) -> ReplacementOutcome | None:
    """Uba Mask: one draw at a time (CR 121.2), each consumed whole; the draws
    queued behind go back through the seam, where each is replaced again — by
    this Mask or, CR 616.1e, another. Nothing is drawn, so this reports 0 and
    "whenever you draw a card" sees no draw."""
    player = payload["player"]
    seat = game.players.index(player)
    sources = _face_up_draw_exile_sources(game, payload)
    source = next(
        (
            permanent for permanent in sources
            if instance is not None and str(permanent.permanent_id) == instance
        ),
        sources[0],
    )
    exile_drawn_card_face_up(game, source, seat)
    payload["drawn"] = draws_behind(
        game, player, int(payload["count"]) - 1, queued_excludes(payload)
    )
    return ReplacementOutcome(replaced=True)
