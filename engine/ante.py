"""CR 407 — Ante.

Playing for ante is an optional variation of the game (CR 407.1) in which every
player puts one random card from their deck into the ante zone before the game
begins and the winner keeps everything anted. The whole variant is opt-in: a
game is played for ante only when ``Game.playing_for_ante`` is True, which the
web layer sets from the "Playing for ante" host setting.

Two concerns live here:

* **The ante-card marker.** A handful of cards carry "Remove this card from your
  deck before playing if you're not playing for ante." Per CR 407.3 they are the
  only cards that may touch the ante zone, and they may not be in a deck or
  sideboard — nor be brought into the game from outside it — when the game isn't
  played for ante. ``is_ante_card`` recognises them from that line, so deck
  construction (``web/deck_legality.py``) and the engine share one definition
  rather than a card-name list.
* **The zone operations** — ``AnteMixin``, composed onto ``Game``: seeding the
  zone at the start of the game (407.2), anting an object mid-game subject to
  the owner-only restriction (407.4), and handing the whole zone to the winner
  when the game ends (407.2).

The zone itself is ``PlayerState.ante`` — one shared zone in paper, modeled
per-player because ownership is what every ante effect and the end-of-game
transfer key off (CR 108.3).
"""

from __future__ import annotations

import random
from typing import Any, Iterable, Mapping

from .models import CardDefinition, PlayerState

# The line printed on every card that may interact with the ante zone (CR 407.3).
# Matched case-insensitively against oracle text, which is normalized to a
# straight apostrophe in the card JSON.
ANTE_DECK_TEXT = "remove this card from your deck before playing if you're not playing for ante"


def _oracle_text_of(card: Any) -> str:
    """Oracle text of a CardDefinition, a catalog/deck payload mapping, or a
    raw string — deck construction validates plain dicts, the engine handles
    CardDefinitions, and both need the same answer."""
    if isinstance(card, str):
        return card
    if isinstance(card, Mapping):
        return str(card.get("oracle_text") or "")
    return str(getattr(card, "oracle_text", "") or "")


def is_ante_card(card: Any) -> bool:
    """Whether *card* is one of the cards removed from a deck when the game
    isn't played for ante (CR 407.3)."""
    text = _oracle_text_of(card).lower().replace("’", "'")
    return ANTE_DECK_TEXT in text


def ante_card_names(cards: Iterable[Any]) -> list[str]:
    """The names of the ante cards in *cards*, in order, without duplicates."""
    names: list[str] = []
    for card in cards:
        if not is_ante_card(card):
            continue
        if isinstance(card, Mapping):
            name = str(card.get("name") or "")
        else:
            name = str(getattr(card, "name", "") or "")
        if name and name not in names:
            names.append(name)
    return names


class AnteMixin:
    """The ante zone's game operations (CR 407). Composed onto ``Game``."""

    def place_starting_ante(self, order: list[int] | None = None) -> None:
        """CR 407.2: each player puts one random card from their deck into the
        ante zone, after the starting player is determined but before anyone
        draws. Called by ``deal_opening_hands`` when the game is played for
        ante; a player with an empty deck antes nothing (there is no card to
        put there).

        ``order`` is the turn order to process seats in, so the cards leave the
        libraries in the same order the hands are dealt.
        """
        if not self.playing_for_ante:
            return
        for index in order if order is not None else range(len(self.players)):
            player = self.players[index]
            if not player.library:
                self.log.append(f"{player.name} has no cards to ante (CR 407.2)")
                continue
            card = player.library.pop(random.randrange(len(player.library)))
            player.ante.append(card)
            self.log.append(f"{player.name} antes {card.name} (CR 407.2)")

    def ante_object(self, owner_index: int, card: CardDefinition) -> bool:
        """CR 407.4: put *card* into the ante zone as a card owned by
        ``owner_index``. Returns True when the card was anted.

        The caller is responsible for having removed the card from the zone it
        was in — this only records the arrival, which is what the ownership
        model (per-player ante lists) needs. Callers must first check
        ``can_ante(controller, owner)``: the owner is the only player who can
        ante an object.
        """
        if not (0 <= owner_index < len(self.players)):
            return False
        self.players[owner_index].ante.append(card)
        return True

    def can_ante(self, actor_index: int, owner_index: int | None) -> bool:
        """CR 407.4: only an object's owner can ante it. An object with no
        determinable owner (a token) can't be anted by anyone."""
        return owner_index is not None and actor_index == owner_index

    def cards_in_ante(self) -> list[tuple[int, CardDefinition]]:
        """Every card in the ante zone as ``(owner seat, card)``. The ante is a
        public zone (CR 400.2) and its cards "may be examined by any player at
        any time" (CR 407.2), so this is deliberately unfiltered by viewer."""
        return [
            (seat, card)
            for seat, player in enumerate(self.players)
            for card in player.ante
        ]

    def award_ante_to_winner(self, winner_index: int) -> bool:
        """CR 407.2: at the end of the game the winner becomes the owner of all
        the cards in the ante zone. Ownership is modeled by which player's ante
        list a card sits in, so the transfer moves every other player's anted
        cards into the winner's. Idempotent — the first call settles the ante
        and later ones (the web layer re-serializes a finished game on every
        poll) do nothing."""
        if not self.playing_for_ante or self.ante_awarded:
            return False
        if not (0 <= winner_index < len(self.players)):
            return False
        winner = self.players[winner_index]
        won: list[CardDefinition] = []
        for seat, player in enumerate(self.players):
            if seat == winner_index:
                continue
            won.extend(player.ante)
            player.ante = []
        winner.ante.extend(won)
        self.ante_awarded = True
        if winner.ante:
            self.log.append(
                f"{winner.name} wins the game and becomes the owner of "
                f"{len(winner.ante)} card(s) in the ante (CR 407.2)"
            )
        return True

    def _maybe_award_ante(self) -> None:
        """Settle the ante if the game has just been decided. Called wherever a
        player can become the sole survivor (state-based actions, concession)."""
        if not self.playing_for_ante or self.ante_awarded:
            return
        if len(self.players) < 2:
            return
        winner: PlayerState | None = self.get_winner()
        if winner is None:
            return
        self.award_ante_to_winner(self.players.index(winner))
