"""Prophecy enchantments.

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


# --- W1G1: rhystic ---
from engine import Game, PlayerState
from engine.damage_events import deal_damage
from engine.models import Permanent


def _w1g1_circle_duel(set_pool, *, opponent_lands: int):
    """Seat 0 (active) holds Rhystic Circle and four Islands; seat 1 holds a
    Hill Giant and *opponent_lands* Islands."""
    island = set_pool("LEA")["Island"]
    circle = Permanent(card=set_pool("PCY")["Rhystic Circle"])
    giant = Permanent(card=set_pool("LEA")["Hill Giant"])
    game = Game(players=[
        PlayerState(
            name="P0", life=20,
            battlefield=[circle] + [Permanent(card=island) for _ in range(4)],
        ),
        PlayerState(
            name="P1", life=20,
            battlefield=[giant] + [Permanent(card=island) for _ in range(opponent_lands)],
        ),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, giant


def _w1g1_giant_hits(game, giant) -> int:
    """What a 3-damage hit from the Giant to seat 0 deals after the shields."""
    return deal_damage(
        game, {"recipient": game.players[0], "amount": 3, "source": giant, "combat": True},
    ).dealt


def test_rhystic_circle_shields_its_controller_when_no_one_pays(set_pool):
    """"{1}: Any player may pay {1}. If no one does, the next time a source of
    your choice would deal damage to you this turn, prevent that damage." The
    controller is asked first and does not pay to stop its own shield; the
    opponent has no mana; so the shield is armed against the chosen source."""
    game, giant = _w1g1_circle_duel(set_pool, opponent_lands=0)

    assert game.activate_permanent_ability(
        0, "Rhystic Circle", target_permanent_ids=[giant.permanent_id],
    ).supported
    game.auto_resolve_pending_choices()
    game._settle()

    assert "P0 declined to pay for Rhystic Circle" in game.log
    assert _w1g1_giant_hits(game, giant) == 0


def test_rhystic_circle_is_bought_off_by_an_opponent_paying_one(set_pool):
    """One Island is enough: the opponent pays {1} and the damage comes
    through. The payment is the whole of what the opponent can do — it is one
    "unless", so once paid nobody else is asked (CR 118.12a)."""
    game, giant = _w1g1_circle_duel(set_pool, opponent_lands=1)

    assert game.activate_permanent_ability(
        0, "Rhystic Circle", target_permanent_ids=[giant.permanent_id],
    ).supported
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g1_giant_hits(game, giant) == 3
    assert [perm.tapped for perm in game.controlled_by(game.players[1])] == [False, True]


def test_rhystic_circle_lets_its_controller_answer_first(set_pool):
    """Asked interactively: the active player — the Circle's controller — is
    asked first; declining moves the offer on, and a decline there arms the
    shield."""
    game, giant = _w1g1_circle_duel(set_pool, opponent_lands=3)

    assert game.activate_permanent_ability(
        0, "Rhystic Circle", target_permanent_ids=[giant.permanent_id],
    ).supported
    owed = [c.player_index for c in game.pending_choices if c.kind == "optional_pay"]
    assert owed == [0]
    assert game.confirm_optional_pay(0, accept=False)
    assert game.confirm_optional_pay(1, accept=False)
    game._settle()

    assert _w1g1_giant_hits(game, giant) == 0
