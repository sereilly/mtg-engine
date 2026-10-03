"""Prophecy sorceries.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_creature_card(name):
    return _w1g6_mk_card(name, "Creature — Beast")


def _w1g6_elephants(game, seat):
    return [p for p in game.controlled_by(seat) if p.card.name == "Elephant Token"]


def test_w1g6_elephant_resurgence_sizes_each_token_by_its_controllers_graveyard(set_pool):
    """"Each player creates a green Elephant creature token. Those creatures
    have "This token's power and toughness are each equal to the number of
    creature cards in its controller's graveyard."" Each token counts its own
    controller's pile, and keeps counting it."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P0", hand=[set_pool("PCY")["Elephant Resurgence"]],
            graveyard=[_w1g6_creature_card("Elk"), _w1g6_creature_card("Ox")],
        ),
        _W1G6PlayerState(
            name="P1",
            graveyard=[_w1g6_creature_card("Yak"), _w1g6_mk_card("Forest", "Basic Land — Forest")],
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()

    assert game.cast_from_hand(0, "Elephant Resurgence").supported
    _w1g6_resolve(game)

    (mine,), (theirs,) = _w1g6_elephants(game, 0), _w1g6_elephants(game, 1)
    assert mine.metadata.get("is_token") and theirs.metadata.get("is_token")
    assert "G" in mine.effective_colors
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (1, 1)

    # A creature of P1's dies: P1's token grows, P0's does not.
    gnu = _W1G6Permanent(card=_w1g6_creature_card("Gnu"))
    game._put_permanent_onto_battlefield(1, gnu, None)
    game.sacrifice_permanent(gnu)
    game._refresh_dynamic_creatures()
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)
    assert mine.effective_power == 2
