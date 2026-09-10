"""Urza's Destiny enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: player-directed effects, and a cost reduction nothing implemented ---
from unittest.mock import patch

import pytest

from engine import Game, PlayerState
from engine.control import BASE_CONTROLLER
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g5_festival_game(pool, opponents: int = 1) -> tuple[Game, Permanent]:
    """A board with Goblin Festival out and *opponents* seats facing it.

    Libraries are stocked because the first untap step draws, and a seat that
    draws from an empty one loses before the ability is ever activated.
    """
    stock = [pool["Goblin Berserker"]] * 5
    seats = [PlayerState(name="P1", life=20, library=list(stock))]
    seats += [
        PlayerState(name=f"P{n + 2}", life=20, library=list(stock))
        for n in range(opponents)
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    festival = Permanent(card=pool["Goblin Festival"])
    festival.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(festival)
    game._sync_control()
    game.start_turn(0)
    return game, game.players[0].battlefield[0]


def test_goblin_festival_keeps_itself_when_the_flip_is_won(set_pool):
    """"{2}: This enchantment deals 1 damage to any target. Flip a coin. If you
    lose the flip, choose one of your opponents. That player gains control of
    this enchantment."

    Every piece but one was already here — the flip, the "if you lose the flip"
    conditional (twenty cards print it) and the hand-over that reads a chosen
    seat (Rainbow Vale's "An opponent gains control of this land" compiles to
    the very same two instructions). What was missing was the *two-sentence*
    spelling of the pick, and the record's visibility across an ``if_then``.

    The won half is the one that would fail silently: a hand-over reading no
    record must give the enchantment to nobody, where falling back to the
    controller — or to whoever a resolution was carrying — is a card that
    changes hands on every activation.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Goblin Festival"])
    assert program.supported, program.reason

    game, festival = _g5_festival_game(pool)
    with patch("engine.handlers.control_flow.flip_coin", return_value=True):
        assert game.activate_permanent_ability(
            0, "Goblin Festival", target_player_index=1
        ).supported
        resolve_stack(game)

    assert game.players[1].life == 19, game.log
    assert game.controller_index_of(festival) == 0, game.log


def test_goblin_festival_hands_itself_over_when_the_flip_is_lost(set_pool):
    """The losing half: the damage still happens and the enchantment moves.

    Both in one game, because the sentence order is the whole card — a reading
    that folded the hand-over into the conditional's branch would be right here
    and would still have to be right about the won case above.
    """
    pool = set_pool("UDS")
    game, festival = _g5_festival_game(pool)
    with patch("engine.handlers.control_flow.flip_coin", return_value=False):
        assert game.activate_permanent_ability(
            0, "Goblin Festival", target_player_index=1
        ).supported
        resolve_stack(game)

    assert game.players[1].life == 19, game.log
    assert game.controller_index_of(festival) == 1, game.log
    # CR 613 layer 2 is a contribution, not a move of the card: the seat it
    # entered under is untouched, which is what an ended effect reverts to.
    assert festival.metadata[BASE_CONTROLLER] == 0


def test_goblin_festival_asks_which_opponent_at_three_seats(set_pool):
    """At two seats the pick has one answer; at three it is a prompt.

    Which is what makes the pick its own instruction rather than a word the
    hand-over resolves: a handler that has to stop and ask cannot also finish
    the sentence. The resolution suspends with the gift still owed, and the
    answer is what runs it — so the enchantment is still its controller's until
    an opponent is named.
    """
    pool = set_pool("UDS")
    game, festival = _g5_festival_game(pool, opponents=2)
    game.interactive_seats = {0}
    with patch("engine.handlers.control_flow.flip_coin", return_value=False):
        assert game.activate_permanent_ability(
            0, "Goblin Festival", target_player_index=1
        ).supported
        resolve_stack(game)

    assert [c.kind for c in game.pending_choices] == ["player_choice"]
    assert game.controller_index_of(festival) == 0, game.log

    assert game.confirm_player_choice(0, 2)
    assert game.controller_index_of(festival) == 2, game.log
