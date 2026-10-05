"""Invasion artifacts.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: domain ---
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_activation_spec as _w1g3_activation_spec
from engine.targeting import derive_cast_spec as _w1g3_cast_spec
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_armory(set_pool, mine=(), theirs=()):
    """Power Armor on seat 0's battlefield beside *mine*, facing *theirs*; both
    named in board order and drawn from Alpha. Returns the Armor too."""
    w1g3_lea = set_pool("LEA")
    w1g3_game = _W1G3Game(
        players=[_W1G3PlayerState(name="W1G3-A"), _W1G3PlayerState(name="W1G3-B")]
    )
    w1g3_game.enforce_mana_costs = False
    w1g3_game.active_player_index = 0
    w1g3_armor = _W1G3Permanent(card=set_pool("INV")["Power Armor"])
    w1g3_game._put_permanent_onto_battlefield(0, w1g3_armor, None)
    w1g3_rows = []
    for w1g3_seat, w1g3_names in enumerate((mine, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_perm = _W1G3Permanent(card=w1g3_lea[w1g3_name])
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    return w1g3_game, w1g3_armor, w1g3_rows[0], w1g3_rows[1]  # _w1g3_armory


def test_w1g3_power_armor_picks_a_creature_on_activation_not_on_cast(set_pool):
    """"Domain — {3}, {T}: Target creature gets +1/+1 until end of turn for
    each basic land type among lands you control." The ability word in front of
    the cost changes nothing (CR 207.2c): the *ability* targets a creature and
    casting the artifact chooses nothing."""
    card = set_pool("INV")["Power Armor"]
    program = _w1g3_compile(card)
    [ability] = program.activated_abilities
    assert _w1g3_activation_spec(ability)["kind"] == "creature"
    cast = _w1g3_cast_spec(card, program)
    assert cast is None or cast.get("kind") == "none"


def test_w1g3_power_armor_pumps_by_the_activators_domain(set_pool):
    """Aimed across the table: the count is the activator's (CR 109.5), so an
    opponent's creature grows by the *activator's* four types."""
    game, armor, _mine, theirs = _w1g3_armory(
        set_pool,
        mine=["Plains", "Island", "Swamp", "Tropical Island"],
        theirs=["Grizzly Bears", "Mountain"],
    )
    bears = theirs[0]
    result = game.activate_permanent_ability(
        0, "Power Armor", target_permanent_ids=[bears.permanent_id]
    )
    assert result.supported, result.details
    _w1g3_resolve(game)
    assert armor.tapped
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)
    assert "Power Armor gives Grizzly Bears +4/+4 until end of turn" in game.log


def test_w1g3_power_armor_bonus_is_locked_in_and_ends_with_the_turn(set_pool):
    """CR 608.2h: counted once, as the ability resolves. A land that arrives
    afterwards adds nothing, one that leaves takes nothing away, and the whole
    boost is gone at cleanup."""
    game, _armor, mine, _theirs = _w1g3_armory(
        set_pool, mine=["Grizzly Bears", "Forest", "Island"],
    )
    bears, forest = mine[0], mine[1]
    assert game.queue_permanent_ability(
        0, "Power Armor", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert len(game.stack) == 1
    # In response, a third type arrives: it is on the battlefield when the
    # ability resolves, so it counts.
    game._put_permanent_onto_battlefield(
        0, _W1G3Permanent(card=set_pool("LEA")["Swamp"]), None
    )
    _w1g3_resolve(game)
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    game._put_permanent_onto_battlefield(
        0, _W1G3Permanent(card=set_pool("LEA")["Mountain"]), None
    )
    game.remove_from_battlefield(forest)
    game._settle()
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    game.resolve_cleanup_step(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g3_power_armor_costs_three_and_a_tap(set_pool):
    """The cost is paid or nothing happens: no mana is a refusal with the
    Armor untapped, and a tapped Armor cannot be used twice."""
    game, armor, mine, _theirs = _w1g3_armory(set_pool, mine=["Grizzly Bears", "Plains"])
    bears = mine[0]
    game.enforce_mana_costs = True
    refused = game.activate_permanent_ability(
        0, "Power Armor", target_permanent_ids=[bears.permanent_id]
    )
    assert not refused.supported and not armor.tapped

    game.players[0].mana_pool["C"] = 3
    assert game.activate_permanent_ability(
        0, "Power Armor", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g3_resolve(game)
    assert armor.tapped and game.players[0].mana_pool["C"] == 0
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)

    game.players[0].mana_pool["C"] = 3
    again = game.activate_permanent_ability(
        0, "Power Armor", target_permanent_ids=[bears.permanent_id]
    )
    assert not again.supported and game.players[0].mana_pool["C"] == 3


def test_w1g3_power_armor_needs_a_creature_to_target(set_pool):
    """CR 602.2b: with no creature on the battlefield the ability cannot be
    activated, and nothing is paid."""
    game, armor, _mine, _theirs = _w1g3_armory(set_pool, mine=["Plains"])
    result = game.activate_permanent_ability(0, "Power Armor")
    assert not result.supported
    assert not armor.tapped
