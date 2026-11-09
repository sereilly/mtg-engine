"""A coin flip replaced by more coins (CR 614.1a over CR 705).

    "If you would flip a coin, instead flip two coins and ignore one."
    (Krark's Thumb.)

**The event is one flip by one player** (``coin_flip``: ``{player, coins,
exclude_sources}``), raised by the two seams a flip goes through —
``handlers/_common.flip_coin_for`` (a flip its flipper wins or loses, CR 705.2)
and ``handlers/_common.flip_face_for`` (a flip that only comes up heads or
tails). Each seam asks this registry for how many coins the one flip becomes,
flips them all, and keeps one: the flipper's choice of which to ignore.

The ruling (2019-01-25): "If an effect tells you to flip more than one coin at
once, this replaces each individual coin flip" — which is why the event is one
flip and a sentence printing several raises several. **Copies multiply**
(``_damage_multiplier``'s and ``_doubled_draw_count``'s reason): CR 614.5 gives
each Thumb one opportunity at the event or the events it became, so a second
Thumb doubles the two flips the first made — four coins, three ignored — and
each Thumb is excluded from the coins it made by the same ``exclude_sources``
key the draw doubler uses.

**Which coin is ignored is not asked.** For a flip that is won or lost the
flipper keeps a win whenever one came up; for a heads-or-tails flip, heads.
Neither is a guess at a preference: every effect in the pool that reads a won
flip rewards the win, and every reader of a face (Goblin Assassin's sacrifice,
Mana Clash's damage) punishes tails, so the kept coin is the one a player
would keep. A card that rewarded the other face would need the choice put to
its flipper, and this module would have to arm a prompt mid-flip — which no
flip site can suspend for.
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


__all__ = ["FLIP_TWO_COINS_TEXT"]
