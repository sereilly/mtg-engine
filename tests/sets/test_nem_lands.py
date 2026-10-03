"""Nemesis lands.

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


# --- W1G5: library, hand and graveyard ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_generator(set_pool, *, interactive=True):
    """Terrain Generator on seat 0 with a basic Forest, a nonbasic land and a
    creature in hand. W1G5's own."""
    nem, lea = set_pool("NEM"), set_pool("LEA")
    me = _W1G5PlayerState(
        name="W1G5-A", hand=[nem["Rath's Edge"], nem["Mogg Toady"], lea["Forest"]]
    )
    game = _W1G5Game(players=[me, _W1G5PlayerState(name="W1G5-B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    if interactive:
        game.interactive_seats = {0}
    generator = _W1G5Permanent(card=nem["Terrain Generator"])
    game._put_permanent_onto_battlefield(0, generator, None)
    return game, generator, me


def test_w1g5_terrain_generator_puts_a_basic_land_in_tapped(set_pool):
    """"{2}, {T}: You may put a basic land card from your hand onto the
    battlefield tapped."

    Three printed words, three assertions: only the *basic* land is offered
    (Rath's Edge is a land and is refused), it arrives *tapped* (CR 110.5b —
    the entry state is the effect's to say), and it was *put*, not played, so
    the turn's land drop is untouched.
    """
    game, generator, me = _w1g5_generator(set_pool)

    assert game.activate_permanent_ability(0, "Terrain Generator", ability_index=1).supported
    assert generator.tapped
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, True, None)
    pick = game.pending_choice_of("put_from_hand_choice", 0)
    assert game.live_put_from_hand_choices(pick) == [2]
    assert not game.confirm_put_from_hand_choice(0, 0), "Rath's Edge is not basic"
    assert game.confirm_put_from_hand_choice(0, 2)
    _w1g5_resolve_stack(game)

    (forest,) = [p for p in game.controlled_by(0) if p.card.name == "Forest"]
    assert forest.tapped, "it enters tapped"
    assert [c.name for c in me.hand] == ["Rath's Edge", "Mogg Toady"]
    assert int(game.lands_played_this_turn.get(0, 0) or 0) == 0, (
        "a land put onto the battlefield is not a land played"
    )


def test_w1g5_terrain_generator_headless_takes_the_basic(set_pool):
    """The non-interactive seat's default answers the same offer the same way:
    the first eligible card, which is the Forest and never the nonbasic."""
    game, _, me = _w1g5_generator(set_pool, interactive=False)
    game.activate_permanent_ability(0, "Terrain Generator", ability_index=1)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    names = {p.card.name: p.tapped for p in game.controlled_by(0)}
    assert names.get("Forest") is True
    assert "Rath's Edge" not in names
