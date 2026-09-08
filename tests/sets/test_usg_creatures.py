"""Urza's Saga creatures.

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

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: Carrion Beetles, the picker-sweep finding that is not a hollow card ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_creature_card, resolve_stack


def _g5c_game():
    """Two seats with no mana enforcement, ending on its own three-tuple.

    The ``_g5c_`` prefix and the distinct ending are SET_PLAYBOOK.md's rule
    about a mechanical union splicing one helper's body onto another's
    signature.
    """
    p1, p2 = PlayerState(name="G5A"), PlayerState(name="G5B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_w1g5_carrion_beetles_exiles_three_cards_from_one_graveyard(set_pool):
    """{2}{B}, {T}: Exile up to three target cards from a single graveyard.

    Carrion Beetles is in ``picker_sweep`` and in **neither** of the other two
    instruments, which is the whole reading of it: the ability is implemented
    and works. What the sweep names is that its cards are chosen at *resolution*
    rather than announced (CR 601.2c) — ROADMAP.md's recorded decline for a
    graveyard target, not a card doing nothing.

    So this test is the evidence for that reading rather than a fix: the cards
    leave the pile, and they all leave the same one.
    """
    game, _p1, p2 = _g5c_game()
    beetles = Permanent(card=set_pool("USG")["Carrion Beetles"])
    game._put_permanent_onto_battlefield(0, beetles, None)
    game._sync_control()
    # CR 302.6: the {T} half of the cost needs a creature that has been under
    # its controller's control since their turn began, and the entry path is
    # what stamps the turn this reads.
    beetles.metadata.pop("summoning_sickness_turn", None)
    for i in range(4):
        p2.graveyard.append(_mk_creature_card("G5 Corpse%d" % i, 1, 1))

    assert game.activate_permanent_ability(0, "Carrion Beetles").supported
    resolve_stack(game)

    assert len(p2.exile) == 3
    assert len(p2.graveyard) == 1
    assert not game.pending_choices, "one pile with legal cards is not a decision"
