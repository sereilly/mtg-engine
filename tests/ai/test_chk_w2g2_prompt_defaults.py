"""What a seat nobody asks answers for Mindblaze's number (CHK W1G7, W2G2).

"Name a nonland card and choose a number greater than 0. Target player reveals
their library. If that library contains exactly the chosen number of cards with
the chosen name, Mindblaze deals 8 damage to that player." The number took the
default every chosen number takes, the mana value that names the most of the
other players' permanents (Void's question) — "exactly three copies" of a card
a forty-card deck holds once. It is now the count it is held against
(``ai_prompt_readers.named_library_count_guess``): one in another player's
library, a hidden zone (CR 400.2), and the real count in the chooser's own.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle


def _w2g2_mindblaze(set_pool, *, their_library, their_graveyard, their_board=()) -> Game:
    chk, lea = set_pool("CHK"), set_pool("LEA")
    cards = {**lea, **chk}
    game = Game(players=[
        PlayerState("A", hand=[chk["Mindblaze"]], library=[chk["Mountain"]] * 5),
        PlayerState(
            "B", library=[cards[name] for name in their_library],
            graveyard=[cards[name] for name in their_graveyard],
            battlefield=[Permanent(card=cards[name]) for name in their_board],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    game.turn = 3
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    result = game.cast_from_hand(0, "Mindblaze", target_player_index=1)
    assert result.supported, result.details
    settle(game)
    return game


def test_mindblaze_names_one_copy_in_another_players_library(set_pool):
    """The Bears in their graveyard is the name (W1G7's evidence), one more in
    their library, and three Hill Giants (mana value 4) on their board that
    the mana-value default would have counted instead: eight damage."""
    game = _w2g2_mindblaze(
        set_pool,
        their_library=["Grizzly Bears"] + ["Forest"] * 6,
        their_graveyard=["Grizzly Bears"],
        their_board=["Hill Giant", "Hill Giant", "Hill Giant"],
    )
    assert game.players[1].life == 12, game.log[-12:]
