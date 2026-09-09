"""Urza's Legacy instants.

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

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: a quantity the sentence that spends it produced ---
#
# Last-Ditch Effort — "Sacrifice any number of creatures. Last-Ditch Effort
# deals that much damage to any target." "Any number" prints no count, so the
# number the damage reads exists nowhere until the seat has answered — and by
# then the creatures are cards in a graveyard (CR 400.7).

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack as _g1i_resolve


def _g1i_board(set_pool, creatures=3, *, interactive=()):
    """Seat 0 holding Last-Ditch Effort behind *creatures* bodies.

    ``_g1i_`` prefixed and ending on ``return game, game.players[0], game.players[1]``
    — SET_PLAYBOOK.md's note about a union splicing one helper onto another.
    """
    bear = set_pool("LEA")["Grizzly Bears"]
    seat0 = PlayerState(
        name="G1I-A",
        hand=[set_pool("ULG")["Last-Ditch Effort"]],
        battlefield=[Permanent(card=bear) for _ in range(creatures)],
    )
    seat1 = PlayerState(name="G1I-B")
    game = Game(players=[seat0, seat1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, game.players[0], game.players[1]


def test_g1_last_ditch_effort_deals_one_per_creature_given_up(set_pool):
    """"That much" names the sacrifice in front of it, and what it counts is
    what the seat actually gave up rather than what it was offered — two of the
    three go, and two damage lands."""
    game, mine, theirs = _g1i_board(set_pool, interactive=(0,))

    game.cast_from_hand(0, "Last-Ditch Effort", target_player_index=1)
    offer = game.pending_sacrifice_state()
    assert offer["up_to"] is True and offer["count"] == 3, (
        '"any number" is a ceiling the whole board answers, not an amount'
    )
    assert game.confirm_sacrifice(0, [0, 1])
    _g1i_resolve(game)

    assert len(list(game.controlled_by(0))) == 1, "two went"
    assert theirs.life == 18


def test_g1_last_ditch_effort_gives_up_the_whole_board(set_pool):
    """The control on the count: three creatures is three damage, so nothing
    about the number is the printed one — the card prints none."""
    game, mine, theirs = _g1i_board(set_pool, interactive=(0,))

    game.cast_from_hand(0, "Last-Ditch Effort", target_player_index=1)
    assert game.confirm_sacrifice(0, [0, 1, 2])
    _g1i_resolve(game)

    assert list(game.controlled_by(0)) == []
    assert theirs.life == 17


def test_g1_last_ditch_effort_declined_by_a_headless_seat_deals_none(set_pool):
    """"Any number" includes none, which is the stated ``up_to`` policy — a
    seat merely offered the chance gives up nothing, and the count behind it is
    zero rather than the board's size."""
    game, mine, theirs = _g1i_board(set_pool)

    game.cast_from_hand(0, "Last-Ditch Effort", target_player_index=1)
    _g1i_resolve(game)

    assert len(list(game.controlled_by(0))) == 3, "nothing was given up"
    assert theirs.life == 20


def test_g1_last_ditch_effort_over_an_empty_board_deals_none(set_pool):
    """Nothing to offer, nothing asked, and a count off a record nothing wrote
    is zero rather than a number the card never named."""
    game, mine, theirs = _g1i_board(set_pool, creatures=0, interactive=(0,))

    game.cast_from_hand(0, "Last-Ditch Effort", target_player_index=1)
    _g1i_resolve(game)

    assert game.pending_sacrifice_state() is None
    assert theirs.life == 20
