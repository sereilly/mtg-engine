"""Planeshift sorceries.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: lands and mana ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_cast_spec as _w1g5_derive_cast_spec
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_implode_table(set_pool, *, mine=(), theirs=(), library=()):
    """Seat 0's main phase holding Implode, costs enforced. Names resolve in
    Planeshift, then Alpha."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[pls["Implode"]],
        library=[card(name) for name in library],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    return game  # _w1g5_implode_table


def test_w1g5_implode_destroys_a_land_and_draws(set_pool):
    """"Destroy target land. Draw a card." Supported on arrival and never run.
    The picker asks for a land; five Mountains pay {4}{R}; a creature is not a
    legal target and nothing is spent on the refusal; the Lair is destroyed,
    the caster draws, and the mana is gone."""
    implode = set_pool("PLS")["Implode"]
    assert _w1g5_derive_cast_spec(implode, _w1g5_compile(implode)) == {"kind": "land"}

    game = _w1g5_implode_table(
        set_pool, mine=["Mountain"] * 5,
        theirs=["Crosis's Catacombs", "Grizzly Bears"], library=["Swamp"],
    )
    (lair,) = [p for p in game.controlled_by(1) if p.card.name == "Crosis's Catacombs"]
    (bears,) = [p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears"]

    def aimed_at(target):
        return game.cast_from_hand(
            0, "Implode", target_player_index=1,
            target_permanent_ids=[target.permanent_id],
        )

    assert not aimed_at(lair).supported, "nothing has paid for it"
    for mountain in list(game.controlled_by(0)):
        game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert not aimed_at(bears).supported
    assert sum(game.players[0].mana_pool.values()) == 5, "a refusal spends nothing"

    assert aimed_at(lair).supported
    _w1g5_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == ["Crosis's Catacombs"]
    assert [card.name for card in game.players[0].hand] == ["Swamp"]
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g5_implode_needs_a_land_to_name_and_fizzles_without_it(set_pool):
    """CR 601.2c: with no land on the battlefield there is no target to
    announce and the spell cannot be cast. CR 608.2b: when its one target has
    left by resolution it is removed from the stack and its second sentence
    is not performed — no card is drawn for destroying nothing."""
    empty = _w1g5_implode_table(set_pool, theirs=["Grizzly Bears"])
    empty.enforce_mana_costs = False
    assert not empty.cast_from_hand(0, "Implode").supported
    assert [card.name for card in empty.players[0].hand] == ["Implode"]

    game = _w1g5_implode_table(set_pool, theirs=["Forest"], library=["Swamp"])
    game.enforce_mana_costs = False
    (forest,) = list(game.controlled_by(1))
    assert game.queue_from_hand(
        0, "Implode", target_player_index=1,
        target_permanent_ids=[forest.permanent_id],
    ).supported
    game.remove_from_battlefield(forest)
    _w1g5_resolve_stack(game)

    assert game.players[0].hand == []
    assert [card.name for card in game.players[0].graveyard] == ["Implode"]
