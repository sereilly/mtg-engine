"""Printed prohibitions on gaining life (CR 119.7).

"Players can't gain life." (Forsaken Wastes.) A continuous effect from a static
ability that takes an event away rather than replacing it — which is exactly the
distinction CR 119.7 draws, and the reason this is not an entry in
``engine/replacements.py``:

    If an effect says that a player can't gain life, … a **replacement effect
    that would replace a life gain event affecting that player won't do
    anything**.

So the ban is not a member of CR 616.1's contention set. Put there it would be
one candidate among several and the affected player could choose Lich's "if you
would gain life, draw that many cards instead" ahead of it — drawing cards off a
gain the rules say never happened. ``Game._gain_life`` asks this module *before*
it gathers replacements, and the rule falls out with nothing to order.

**Who is banned is payload, not a second mechanism.** The three printed subjects
this reads name the three seat scopes the engine already spells everywhere else,
so a card printing "Your opponents can't gain life" needs no code here. The
sentence is anchored whole: a line that says more than this is a rule this module
does not carry out, and a prefix match would claim it and then enforce only the
half it recognised.

And the reader is asked by three callers, for the reason every other text-keyed
table in this engine is: the seam that enforces it, the support gate that decides
whether the card is implemented (``oracle._derived_static_claims``), and the
parse-coverage report that decides whether the sentence was read. A permanent
whose only ability is one of these produces no instruction, so without the claim
it would report unsupported however well the ban works.
"""

from __future__ import annotations

import re

#: Which seats a printed subject bans. The values are the scope names, not seat
#: numbers: who "you" and "your opponents" are depends on who controls the
#: permanent, and that is the board scan's question rather than the text's.
_BAN_SCOPES: dict[str, str] = {
    "players": "each_player",
    "each player": "each_player",
    "you": "you",
    "your opponents": "opponents",
    "opponents": "opponents",
}

_LIFE_GAIN_BAN = re.compile(
    rf"^(?P<subject>{'|'.join(_BAN_SCOPES)}) can't gain life$"
)


def life_gain_ban_line(line: str) -> str | None:
    """The seat scope *line* bans from gaining life, or None.

    Reminder text and the trailing stop are stripped the way every other
    text-keyed reader here strips them, so the printed line and the normalized
    one give the same answer.
    """
    text = " ".join((line or "").strip().lower().rstrip(".").split())
    text = text.replace("’", "'")
    match = _LIFE_GAIN_BAN.match(text)
    return None if match is None else _BAN_SCOPES[match.group("subject")]


def life_gain_banned(game, player) -> bool:
    """Whether any permanent on the board forbids *player* from gaining life.

    Scanned over the whole board rather than one seat's, because the printed
    subject decides the reach: "players" is everybody, so the enchantment stops
    its own controller as well as their opponents. Reading only the gaining
    player's own permanents would make it a one-sided card, which is the
    narrowing this pool keeps producing.

    The **effective** card (CR 707.2/612.1), so a Clone of Forsaken Wastes locks
    the game too and a text change that rewrote the sentence stops being read.
    """
    for seat, permanent in game.permanents_with_controller():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            scope = life_gain_ban_line(line)
            if scope is None:
                continue
            if scope == "each_player":
                return True
            source_seat_player = game.players[seat]
            if scope == "you":
                if source_seat_player is player:
                    return True
            elif scope == "opponents":
                if source_seat_player is not player:
                    return True
    return False


__all__ = ["life_gain_ban_line", "life_gain_banned"]
