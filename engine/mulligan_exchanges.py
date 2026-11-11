"""An action a player may perform "any time [they] could mulligan" (CR 103.5b).

"Any time you could mulligan and this card is in your hand, you may exile all
the cards from your hand, then draw that many cards. (You can do this in
addition to taking mulligans.)" (Serum Powder.)

CR 103.5b: "If an effect allows a player to perform an action 'any time [that
player] could mulligan,' the player may perform that action at a time they
would declare whether they will take a mulligan. This need not be in the first
round of mulligans. Other players may have already made their mulligan
declarations by the time the player has the option to perform this action. If
the player performs the action, they then declare whether they will take a
mulligan." So the exchange is offered **inside a declaration**, to the seat
declaring, and the seat then declares — keep, mulligan, or the exchange again
if the new hand holds another such card. The rulings (2017-11-17): the exiled
cards stay exiled for the rest of the game (a later mulligan does not shuffle
them back), and "Using the ability doesn't prevent you from taking further
mulligans, and taking a mulligan doesn't prevent you from using a Serum
Powder's ability if you happen to draw one in your new hand."

**A mulligan's bottom comes first.** CR 103.5 puts the cards a mulligan owes
on the bottom as the mulligan is taken, so the hand exchanged after one is the
hand *without* them. This engine defers that choice to the keep (the web table
and the AI choose the N out of the seven drawn as they keep, the same choice);
an exchange made while cards are owed takes the bottom choice with it, puts
those cards on the bottom, then exiles the rest — and the keep owes nothing
more (``Game.mulligan_bottom_owed``). Exchanging all seven and choosing the
bottom out of the fresh seven would be a choice the rules never give.

The pieces:

* :func:`mulligan_exchange_line` — the registry claim
  (``grammar/registries.py``): the line is carried out here, off the card's
  text, and lowers to no instruction;
* :func:`exchange_sources` — which cards in a seat's hand grant it, read off
  their printed text (a card in a hand has no layers applied, CR 613.1);
* ``Game.pregame_hand_exchange`` (``mixins/turn_management``) — the action;
* ``ai_mulligan`` — whether an AI seat takes it (a hand it would not keep, in
  preference to a mulligan, which costs a card the exchange does not);
* ``web/pregame.py`` / ``web/action_pregame.py`` — the offer on the
  keep-or-mulligan prompt (``hand_exchange``) and the ``mulligan_exchange``
  action.
"""

from __future__ import annotations

import re

#: The printed sentence, as the registries normalize a line (lowercased, no
#: full stop), with its reminder text removed. Anchored at both ends: a line
#: that says this and something more is not this line.
_EXCHANGE_LINE = re.compile(
    r"^any time you could mulligan and this card is in your hand, you may "
    r"exile all the cards from your hand, then draw that many cards$"
)

_REMINDER = re.compile(r"\([^)]*\)")

#: The registry name the grammar labels the line with (``RegistryLine``).
MULLIGAN_EXCHANGE_CLAIM = "mulligan_exchanges"


def _without_reminder(text: str) -> str:
    return " ".join(_REMINDER.sub(" ", text or "").split()).strip().lower().rstrip(".")


def mulligan_exchange_line(line: str) -> bool:
    """Whether *line* is the whole "any time you could mulligan …" exchange."""
    return _EXCHANGE_LINE.match(_without_reminder(line)) is not None


def grants_mulligan_exchange(card) -> bool:
    """Whether *card*'s printed text grants the exchange (each of its lines,
    read the way every reader of a card's lines starts,
    ``line_rewrites.expand_ability_lines``)."""
    from .line_rewrites import expand_ability_lines

    text = expand_ability_lines(
        getattr(card, "oracle_text", "") or "", card_name=getattr(card, "name", None),
    )
    return any(mulligan_exchange_line(line) for line in text.splitlines())


def exchange_sources(game, seat: int) -> list[int]:
    """Hand slots of *seat*'s cards that grant the exchange — "this card is in
    your hand"."""
    return [
        index for index, card in enumerate(game.players[seat].hand)
        if grants_mulligan_exchange(card)
    ]


__all__ = [
    "MULLIGAN_EXCHANGE_CLAIM",
    "exchange_sources",
    "grants_mulligan_exchange",
    "mulligan_exchange_line",
]
