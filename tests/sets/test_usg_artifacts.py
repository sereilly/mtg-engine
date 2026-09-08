"""Urza's Saga artifacts.

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


# --- W1G3: Chimeric Staff — an X/X body with a duration ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g3a_staff(set_pool):
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    staff = Permanent(card=set_pool("USG")["Chimeric Staff"])
    game._put_permanent_onto_battlefield(0, staff, None)
    staff.metadata["summoning_sickness_turn"] = -99
    return game, staff


def test_chimeric_staff_is_the_size_the_activation_paid_for(set_pool):
    """"{X}: This artifact becomes an X/X Construct artifact creature until end
    of turn."

    The only card in the group whose body prints a *variable* size, and the
    only one with a duration. Two activations at different X are asserted
    rather than one, because a body that resolved X to zero or to a constant
    would look right at whichever number the test happened to pick.
    """
    game, staff = _g3a_staff(set_pool)
    assert not staff.is_creature

    game.activate_permanent_ability(0, "Chimeric Staff", x_value=4)
    resolve_stack(game)

    assert staff.is_creature
    assert staff.has_type("artifact"), "CR 205.1b: it is still an artifact"
    assert staff.has_type("construct")
    assert (staff.effective_power, staff.effective_toughness) == (4, 4)

    game.activate_permanent_ability(0, "Chimeric Staff", x_value=1)
    resolve_stack(game)
    assert (staff.effective_power, staff.effective_toughness) == (1, 1)


def test_chimeric_staff_stops_being_a_creature_at_cleanup(set_pool):
    """The duration, which every other card in this group lacks.

    "Until end of turn" is the difference between the Staff and the Veiled
    cycle, and it is the half a record written on the wrong key would lose:
    the animation would last for ever and the artifact would keep attacking
    on turns its controller never paid for.
    """
    game, staff = _g3a_staff(set_pool)
    game.activate_permanent_ability(0, "Chimeric Staff", x_value=3)
    resolve_stack(game)
    assert staff.is_creature

    game.resolve_cleanup_step(0)

    assert not staff.is_creature
    assert staff.has_type("artifact")
