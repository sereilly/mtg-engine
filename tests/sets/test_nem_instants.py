"""Nemesis instants.

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

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: amounts and bounded targets ---
# Dominate: a target restriction whose bound is the X the same cast announces
# (CR 601.2b announces X before CR 601.2c names the target).
from engine import Game as _W1g4Game
from engine import PlayerState as _W1g4PlayerState
from engine.models import CardDefinition as _W1g4Card
from engine.models import Permanent as _W1g4Permanent


def _w1g4_costed_creature(name, cmc):
    """A 2/2 test creature whose mana value is *cmc*."""
    line = "Creature - Test"
    return _W1g4Card(
        name=name, mana_cost="{%d}" % cmc, cmc=float(cmc), type_line=line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": line, "power": "2", "toughness": "2"},
    )


def _w1g4_instant_table(set_pool, seat1):
    """P0 holding Dominate in its main phase, costs unenforced."""
    table = _W1g4Game(players=[
        _W1g4PlayerState(name="P0", hand=[set_pool("NEM")["Dominate"]]),
        _W1g4PlayerState(name="P1", battlefield=list(seat1)),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set()
    table.start_turn(0)
    table._close_current_priority_step()
    return table


def test_w1g4_dominate_refuses_a_target_above_the_announced_x(set_pool):
    """"Gain control of target creature with mana value X or less."

    Announced at X=3, a five-drop is not a legal target and the cast is refused
    before anything is paid (CR 601.2c). Before this, the announcement was
    accepted and the resolution's scan then took a *different* creature that
    did answer the bound — one nobody named.
    """
    cheap = _W1g4Permanent(card=_w1g4_costed_creature("Two Drop", 2))
    pricey = _W1g4Permanent(card=_w1g4_costed_creature("Five Drop", 5))
    game = _w1g4_instant_table(set_pool, (cheap, pricey))

    result = game.cast_from_hand(
        0, "Dominate", target_player_index=1,
        target_permanent_ids=[pricey.permanent_id], x_value=3,
    )

    assert not result.supported
    assert game.controller_index_of(pricey) == 1
    assert game.controller_index_of(cheap) == 1
    assert [card.name for card in game.players[0].hand] == ["Dominate"]


def test_w1g4_dominate_steals_for_good_within_the_bound(set_pool):
    """X=3 at a two-drop: control changes, and with no duration printed it does
    not end at cleanup (CR 611.2a)."""
    cheap = _W1g4Permanent(card=_w1g4_costed_creature("Two Drop", 2))
    game = _w1g4_instant_table(set_pool, (cheap,))

    result = game.cast_from_hand(
        0, "Dominate", target_player_index=1,
        target_permanent_ids=[cheap.permanent_id], x_value=3,
    )

    assert result.supported, result
    assert game.controller_index_of(cheap) == 0
    game.start_turn(1)
    assert game.controller_index_of(cheap) == 0


def test_w1g4_dominate_bound_is_inclusive_and_x_is_the_announced_one(set_pool):
    """"X **or less**": a creature whose mana value equals X is legal, one above
    is not — the bound is the announced number, not the mana in the pool."""
    exactly = _W1g4Permanent(card=_w1g4_costed_creature("Three Drop", 3))
    game = _w1g4_instant_table(set_pool, (exactly,))

    low = game.cast_from_hand(
        0, "Dominate", target_player_index=1,
        target_permanent_ids=[exactly.permanent_id], x_value=2,
    )
    assert not low.supported
    exact = game.cast_from_hand(
        0, "Dominate", target_player_index=1,
        target_permanent_ids=[exactly.permanent_id], x_value=3,
    )
    assert exact.supported, exact
    assert game.controller_index_of(exactly) == 0
