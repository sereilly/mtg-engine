"""Maximum hand size (CR 402.2), and the printed lines that change it.

Seven is the rule, not a constant anyone chose, so it lives here with the two
sentences the pool prints against it rather than as a literal inside the cleanup
step:

* **"You have no maximum hand size."** (Library of Leng, Reflecting Mirror.) A
  permission stamped on its controller as the permanent enters — read off
  ``PlayerState.has_no_max_hand_size``, which ``engine/enter_effects.py`` sets.
* **"The chosen player's maximum hand size is four."** (Cursed Rack.) A
  *continuous* static about a player the permanent chose as it entered, so it is
  derived here on every read rather than stamped: the limit ends when the Rack
  leaves, and nothing has to remember to take it off.

The number is payload, like every other text-keyed table's parameter — a card
printing five needs no code. And the reader is asked by three callers for the
one reason this repo keeps writing down: the cleanup step that enforces it, the
support gate that decides whether the card is implemented, and the parse-coverage
report that decides whether the sentence was read. Three copies of one sentence
drift; one function does not.
"""

from __future__ import annotations

import re

#: CR 402.2. A player with more cards than this discards down at cleanup.
DEFAULT_MAXIMUM_HAND_SIZE = 7

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

#: "The chosen player's maximum hand size is four." Anchored on the whole
#: sentence: a line saying more than this is a rule this file does not carry
#: out, and a prefix match would claim it and then enforce only the part it
#: recognised.
_CHOSEN_PLAYER_LIMIT = re.compile(
    rf"^the chosen player's maximum hand size is (?P<size>{'|'.join(_NUMBER_WORDS)}|\d+)$"
)


def chosen_player_hand_size(line: str) -> int | None:
    """The limit *line* sets on the permanent's chosen player, or None.

    Reminder text and the trailing stop are stripped the way every other
    text-keyed reader here strips them, so the printed line and the normalized
    one give the same answer.
    """
    text = " ".join((line or "").strip().lower().rstrip(".").split())
    text = text.replace("’", "'")
    match = _CHOSEN_PLAYER_LIMIT.match(text)
    if match is None:
        return None
    size = match.group("size")
    return int(size) if size.isdigit() else _NUMBER_WORDS[size]


def hand_size_line(line: str) -> bool:
    """Whether one printed line is a hand-size rule this module carries out."""
    return chosen_player_hand_size(line) is not None


def maximum_hand_size(game, player_index: int) -> int | None:
    """How many cards *player_index* may keep at cleanup, or None for no maximum.

    The lowest limit any permanent sets, because two of them are two separate
    static abilities and both apply (CR 613.6 has nothing to order here — they
    do not depend on one another). "No maximum" is checked first and wins: it is
    a permission that removes the rule rather than a number competing with one.
    """
    player = game.players[player_index]
    if getattr(player, "has_no_max_hand_size", False):
        return None
    limit = DEFAULT_MAXIMUM_HAND_SIZE
    for permanent in game.all_permanents():
        if permanent.metadata.get("chosen_player_index") != player_index:
            continue
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            size = chosen_player_hand_size(line)
            if size is not None:
                limit = min(limit, size)
    return limit


__all__ = [
    "DEFAULT_MAXIMUM_HAND_SIZE",
    "chosen_player_hand_size",
    "hand_size_line",
    "maximum_hand_size",
]
