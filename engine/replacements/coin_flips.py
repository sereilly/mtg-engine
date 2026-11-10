"""A coin flip replaced by more coins (CR 614.1a over CR 705).

    "If you would flip a coin, instead flip two coins and ignore one."
    (Krark's Thumb.)

**The event is one flip by one player** (``coin_flip``: ``{player, coins,
exclude_sources}``), raised by the one seam a flip goes through —
``handlers/_common.flip_coins_for``, for a flip its flipper wins or loses and
for one that only comes up heads or tails (CR 705.2) alike. The seam asks this
registry for how many coins the one flip becomes and flips them all; which one
is kept is the flipper's choice of which to ignore.

The ruling (2019-01-25): "If an effect tells you to flip more than one coin at
once, this replaces each individual coin flip" — which is why the event is one
flip and a sentence printing several raises several. **Copies multiply**
(``_damage_multiplier``'s and ``_doubled_draw_count``'s reason): CR 614.5 gives
each Thumb one opportunity at the event or the events it became, so a second
Thumb doubles the two flips the first made — four coins, three ignored — and
each Thumb is excluded from the coins it made by the same ``exclude_sources``
key the draw doubler uses.

**Which coin is ignored is asked**, after every coin is flipped — the
card's rulings: "You will know the results of all simultaneous flips before
choosing which to ignore" (2019-01-25), "you can see your opponent's result
before choosing which result to keep" (2004-10-04). The question is
``handlers/coin_runs.flip_together``'s (the ``ignore_coin`` prompt), armed
only where the coins disagree; a seat nobody asks keeps a win, or heads. Not
every reader rewards the win: Puppet's Verdict's lost flip destroys the big
creatures, Winter Sky's draws a card each.
"""

from __future__ import annotations

from ..effect_ordering import source_names
from .registry import COIN_FLIP_DOUBLED, ReplacementOutcome, replacement_effect

#: The printed line, as the interceptor below and the support claim
#: (``replacements.lines.REPLACEMENT_LINES``) both read it.
FLIP_TWO_COINS_TEXT = "if you would flip a coin, instead flip two coins and ignore one"


def _coin_doublers(game, payload: dict) -> list:
    """The permanents the flipper controls whose text doubles their flips and
    which have not had this event yet (CR 614.5). Read off ``effective_card``
    (CR 707.2, CR 612.1), so a copy doubles and a text-changed one does not."""
    player = payload.get("player")
    if player is None or player not in game.players:
        return []
    exclude = set(payload.get("exclude_sources") or ())
    return [
        perm
        for perm in game.controlled_by(player)
        if perm.permanent_id not in exclude
        and any(
            line.strip().lower().rstrip(".") == FLIP_TWO_COINS_TEXT
            for line in (perm.effective_card.oracle_text or "").splitlines()
        )
    ]


def coin_doubler_names(game, player) -> list[str]:
    """The names of the permanents doubling *player*'s flips, once each —
    what the ``ignore_coin`` prompt names as the reason it is asked."""
    return source_names(_coin_doublers(game, {"player": player}))


def _applies_two_coins(game, payload: dict) -> bool:
    return bool(_coin_doublers(game, payload))


@replacement_effect(
    "coin_flip", COIN_FLIP_DOUBLED, applies=_applies_two_coins,
    sources=_coin_doublers, label="Flip two coins and ignore one",
)
def _flip_two_coins_instead(game, payload: dict) -> ReplacementOutcome | None:
    """Krark's Thumb: the flip becomes two flips, one of them ignored.

    A *modifying* replacement: the flip still happens, with more coins, so
    nothing is consumed. Every Thumb the flipper controls doubles the count
    once and is then excluded from the coins it made (CR 614.5).
    """
    doublers = _coin_doublers(game, payload)
    before = int(payload.get("coins", 1) or 1)
    payload["coins"] = before * (2 ** len(doublers))
    payload["exclude_sources"] = tuple(payload.get("exclude_sources") or ()) + tuple(
        perm.permanent_id for perm in doublers
    )
    game.log.append(
        f"{payload['player'].name} flips {payload['coins']} coins instead of "
        f"{before} and ignores all but one ({', '.join(source_names(doublers))})"
    )
    return ReplacementOutcome()


__all__ = ["FLIP_TWO_COINS_TEXT", "coin_doubler_names"]
