"""A contest of top cards, repeated among the tied players (Timesifter).

"At the beginning of each upkeep, each player exiles the top card of their
library. The player who exiled the card with the greatest mana value takes an
extra turn after this one. If two or more players' cards are tied for greatest,
the tied players repeat this process until the tie is broken."

One handler runs the whole paragraph, because each round's field is the last
round's leaders and nothing but the loop knows it. The rulings (2004-12-01)
settle the three questions the words leave open:

- "Each time there's a tie for the highest cost, only the players involved in
  the tie continue";
- "If a player fails to exile a card, they can't take the extra turn" — a seat
  whose library is empty leaves the contest that round;
- "A land card has a mana value of 0" — mana value is the card's own
  (CR 202.3), which the record of the card in the library already holds.

The loop ends: every round takes a card from every contender's library, so a
tie that never breaks runs the tied libraries out, and a round in which nobody
exiled anything names nobody.

Every exile goes through ``Game.put_card_into_exile`` (the one exile arrival),
and the prize is CR 500.7's extra turn through ``Game.add_extra_turn``, the
seam ``grant_extra_turn`` uses. Nothing here draws randomness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _mana_value(card) -> int:
    """CR 202.3's mana value of a card as it sat in a library."""
    return int(getattr(card, "cmc", 0) or 0)


@effect_handler("contest_top_cards")
def contest_top_cards(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext,
) -> tuple[bool, str]:
    move = str(instruction.payload.get("move") or "")
    prize = str(instruction.payload.get("prize") or "")
    if move != "exile" or prize != "extra_turn":
        return False, f"no top-card contest moves by {move!r} for {prize!r}"
    name = context.card.name if context.card is not None else "The contest"
    # CR 101.4: everyone at once, in APNAP order; a seat that has left the game
    # is not in it (CR 800.4a).
    contenders = list(game.apnap_seats())
    winner: int | None = None
    while contenders:
        exiled: dict[int, int] = {}
        for seat in contenders:
            player = game.players[seat]
            if not player.library:
                game.log.append(f"{name}: {player.name} has no card to exile")
                continue
            card = game.put_card_into_exile(player, player.library.pop(0))
            exiled[seat] = _mana_value(card)
            game.log.append(
                f"{name}: {player.name} exiled {card.name} "
                f"(mana value {exiled[seat]})"
            )
        if not exiled:
            break
        best = max(exiled.values())
        leaders = [seat for seat in contenders if exiled.get(seat) == best]
        if len(leaders) == 1:
            winner = leaders[0]
            break
        game.log.append(
            f"{name}: "
            + ", ".join(game.players[seat].name for seat in leaders)
            + f" tied at mana value {best} and repeat the process"
        )
        contenders = leaders
    if winner is None:
        game.log.append(f"{name}: nobody exiled the card with the greatest mana value")
        return True, "resolved"
    game.add_extra_turn(winner)
    game.log.append(f"{game.players[winner].name} gained an extra turn")
    return True, "resolved"


__all__ = ["contest_top_cards"]
