"""Maximum hand size (CR 402.2), and the printed lines that change it.

Seven is the rule, not a constant anyone chose, so it lives here with the two
sentences the pool prints against it rather than as a literal inside the cleanup
step:

* **"You have no maximum hand size."** (Library of Leng, Reflecting Mirror.)
  and **"Players have no maximum hand size."** (Anvil of Bogardan.) — one
  sentence with its scope changed, so one pattern with the scope as payload.
  Both are *continuous statics* derived here on every read, for the reason the
  Rack's is: CR 611.3a ends a static ability with its source. The controller
  form used to be an **entry** effect that stamped
  ``PlayerState.has_no_max_hand_size`` and nothing ever cleared it, so a
  destroyed Library of Leng left its controller with no maximum hand size for
  the rest of the game — the identical bug the two mana-spending permissions
  beside it were moved out of ``enter_effects`` to fix, and it was the last of
  that family still stamped. The field survives for an effect that really does
  set the permission on a player with no permanent behind it, and the
  battlefield is consulted whether or not it is set.
* **"The chosen player's maximum hand size is four."** (Cursed Rack.) A
  *continuous* static about a player the permanent chose as it entered, so it is
  derived here on every read rather than stamped: the limit ends when the Rack
  leaves, and nothing has to remember to take it off.

* **"Your maximum hand size is reduced by two."** (Thought Nibbler, Thought
  Eater, Thought Devourer.) Not a limit but a change to whatever the limit
  is, and the direction is payload — "increased by" is the same sentence.

**The sentences are applied in timestamp order** (CR 613.11: an effect that
modifies a player's maximum hand size affects a game rule, and "all other such
effects are applied in timestamp order"). That is what makes a *change*
meaningful at all: Cursed Rack and then Thought Eater is one card, the
opposite order is four, and Spellbook after Recycle is no maximum where Recycle
after Spellbook is two — each of those is the cards' own printed ruling. The
reader took "the lowest limit, and no maximum wins" until the first card that
changes the number instead of setting it arrived, which was wrong for every
pair of the shipped sentences that disagree and invisible while each stood
alone.

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


#: "Your maximum hand size is two." (Recycle.) The Rack's sentence with the
#: controller in place of the chosen player, and its own pattern rather than an
#: alternation inside that one because the two name **different seats**: a
#: reader that admitted either and answered with the number alone would apply
#: Recycle's limit to whoever the permanent had chosen, and the Rack's to its
#: controller. The number is payload, so a card printing another needs no code.
_CONTROLLER_LIMIT = re.compile(
    rf"^your maximum hand size is (?P<size>{'|'.join(_NUMBER_WORDS)}|\d+)$"
)

#: "Players have no maximum hand size." (Anvil of Bogardan) / "You have no
#: maximum hand size." (Library of Leng, Reflecting Mirror). One sentence whose
#: scope is the printed subject, so the subject is payload and not a second
#: pattern — a card printing either wording needs no code.
_NO_LIMIT = re.compile(r"^(?:(?P<all>players)|you) have no maximum hand size$")

#: "Your maximum hand size is reduced by two." (Thought Nibbler.) The verb is
#: the sign, so "increased by" is this row and not a second one. Anchored on
#: the whole sentence like its neighbours — "…reduced by one for each …" is a
#: count this file does not take, and a prefix match would claim it and then
#: subtract one.
_CONTROLLER_CHANGE = re.compile(
    r"^your maximum hand size is (?P<verb>reduced|increased) by "
    rf"(?P<size>{'|'.join(_NUMBER_WORDS)}|\d+)$"
)

#: What :func:`no_maximum_hand_size_scope` answers: the sentence removes the
#: limit for everybody, or for the source's controller alone.
ALL_PLAYERS = "all"
CONTROLLER = "controller"


def _normalized(line: str) -> str:
    """One printed line as the tables here read it.

    Lowercased, whitespace collapsed, the trailing stop dropped and the typographic
    apostrophe folded — the same normalization every text-keyed reader in this
    engine does, spelled once here because two readers in one module is already
    one copy too many.
    """
    text = " ".join((line or "").strip().lower().rstrip(".").split())
    return text.replace("’", "'")


def no_maximum_hand_size_scope(line: str) -> str | None:
    """Whose maximum hand size *line* removes — :data:`ALL_PLAYERS`, :data:`CONTROLLER`, or None."""
    match = _NO_LIMIT.match(_normalized(line))
    if match is None:
        return None
    return ALL_PLAYERS if match.group("all") else CONTROLLER


def chosen_player_hand_size(line: str) -> int | None:
    """The limit *line* sets on the permanent's chosen player, or None.

    Reminder text and the trailing stop are stripped the way every other
    text-keyed reader here strips them, so the printed line and the normalized
    one give the same answer.
    """
    match = _CHOSEN_PLAYER_LIMIT.match(_normalized(line))
    if match is None:
        return None
    size = match.group("size")
    return int(size) if size.isdigit() else _NUMBER_WORDS[size]


def controller_hand_size(line: str) -> int | None:
    """The limit *line* sets on the permanent's own controller, or None.

    :func:`chosen_player_hand_size` one seat over. Kept apart from it all the
    way down — pattern, reader and the branch in :func:`maximum_hand_size` —
    because the seat is the whole content of the difference: fold them and
    Recycle limits whoever Cursed Rack pointed at.
    """
    match = _CONTROLLER_LIMIT.match(_normalized(line))
    if match is None:
        return None
    size = match.group("size")
    return int(size) if size.isdigit() else _NUMBER_WORDS[size]


def controller_hand_size_change(line: str) -> int | None:
    """How far *line* moves its controller's maximum hand size, or None.

    Signed: "reduced by two" is ``-2`` and "increased by one" is ``1``. A
    change and not a limit, so it has no meaning apart from the limit it is
    applied to — which is why :func:`maximum_hand_size` orders what it reads.
    """
    match = _CONTROLLER_CHANGE.match(_normalized(line))
    if match is None:
        return None
    size = match.group("size")
    amount = int(size) if size.isdigit() else _NUMBER_WORDS[size]
    return -amount if match.group("verb") == "reduced" else amount


#: The three things a printed sentence does to the limit, as
#: :func:`hand_size_effect` reports them.
NO_MAXIMUM = "no_maximum"
SET_MAXIMUM = "set"
CHANGE_MAXIMUM = "change"

#: The third seat a sentence can name, beside :data:`ALL_PLAYERS` and
#: :data:`CONTROLLER`: the player the permanent chose as it entered.
CHOSEN_PLAYER = "chosen_player"


def hand_size_effect(line: str) -> tuple[str, int, str] | None:
    """What one printed line does to a maximum hand size, or None.

    ``(kind, amount, seat)``: *kind* is :data:`NO_MAXIMUM`, :data:`SET_MAXIMUM`
    or :data:`CHANGE_MAXIMUM`; *amount* is the limit or the signed change (zero
    for no maximum); *seat* is whose — everybody's, the controller's, or the
    chosen player's. The one classification the support gate, the
    parse-coverage report and the cleanup step all read, so a sentence is
    claimed exactly when something applies it.
    """
    scope = no_maximum_hand_size_scope(line)
    if scope is not None:
        return (NO_MAXIMUM, 0, scope)
    # "**Your** maximum hand size is two." (Recycle.) and "The **chosen
    # player's** maximum hand size is four." (Cursed Rack.) are one effect
    # naming two different seats, and the seat is the whole content of the
    # difference: fold them and Recycle limits whoever the Rack pointed at.
    size = controller_hand_size(line)
    if size is not None:
        return (SET_MAXIMUM, size, CONTROLLER)
    size = chosen_player_hand_size(line)
    if size is not None:
        return (SET_MAXIMUM, size, CHOSEN_PLAYER)
    change = controller_hand_size_change(line)
    if change is not None:
        return (CHANGE_MAXIMUM, change, CONTROLLER)
    return None


def hand_size_line(line: str) -> bool:
    """Whether one printed line is a hand-size rule this module carries out."""
    return hand_size_effect(line) is not None


def hand_size_effects(game, player_index: int) -> list[tuple[str, int]]:
    """Every hand-size effect that applies to *player_index*, as
    ``(kind, amount)`` in the order CR 613.11 applies them: by timestamp.

    A static ability's effect has its object's timestamp (CR 613.7a), so the
    order is the permanents' own, and two sentences on one permanent keep
    their printed order. Whether a sentence applies to this player is the
    sentence's own subject, asked of the seat it names.
    """
    found: list[tuple[int, int, str, int]] = []
    for permanent in game.all_permanents():
        controlled = None
        lines = (permanent.effective_card.oracle_text or "").splitlines()
        for position, line in enumerate(lines):
            effect = hand_size_effect(line)
            if effect is None:
                continue
            kind, amount, seat = effect
            if seat == CHOSEN_PLAYER:
                if permanent.metadata.get("chosen_player_index") != player_index:
                    continue
            elif seat == CONTROLLER:
                # Read lazily: `controller_index_of` walks the control seam,
                # and most permanents print none of these sentences.
                if controlled is None:
                    controlled = game.controller_index_of(permanent) == player_index
                if not controlled:
                    continue
            found.append((permanent.timestamp, position, kind, amount))
    found.sort(key=lambda entry: (entry[0], entry[1]))
    return [(kind, amount) for _stamp, _position, kind, amount in found]


def maximum_hand_size(game, player_index: int) -> int | None:
    """How many cards *player_index* may keep at cleanup, or None for no maximum.

    Seven (CR 402.2) with every effect :func:`hand_size_effects` names applied
    to it in timestamp order (CR 613.11): "no maximum" removes the number, a
    printed limit replaces whatever stood there — a number or none — and a
    change moves the number that is there. A change applied to *no* maximum
    leaves none: there is no number for it to move, and a later limit starts
    from its own.

    The running value may go below zero (Thought Devourer and Thought Eater
    together are seven less seven; a third beast is less than that) and is
    kept so, because a later "increased by" is arithmetic on the value and not
    on what the cleanup step would have done with it. The answer handed back
    is never negative (CR 107.1b): nobody discards down to fewer than no
    cards.

    ``PlayerState.has_no_max_hand_size`` is a permission set on a player with
    no permanent behind it, so it has no timestamp to be ordered by and is
    still checked first.
    """
    player = game.players[player_index]
    if getattr(player, "has_no_max_hand_size", False):
        return None
    limit: int | None = DEFAULT_MAXIMUM_HAND_SIZE
    for kind, amount in hand_size_effects(game, player_index):
        if kind == NO_MAXIMUM:
            limit = None
        elif kind == SET_MAXIMUM:
            limit = amount
        elif limit is not None:
            limit += amount
    return None if limit is None else max(0, limit)


__all__ = [
    "ALL_PLAYERS",
    "CHANGE_MAXIMUM",
    "CHOSEN_PLAYER",
    "CONTROLLER",
    "DEFAULT_MAXIMUM_HAND_SIZE",
    "NO_MAXIMUM",
    "SET_MAXIMUM",
    "chosen_player_hand_size",
    "controller_hand_size",
    "controller_hand_size_change",
    "hand_size_effect",
    "hand_size_effects",
    "hand_size_line",
    "maximum_hand_size",
    "no_maximum_hand_size_scope",
]
