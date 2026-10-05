"""Invasion creatures.

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
from engine.land_types import change_land_type as _w1g3_change_land_type
from engine.models import Permanent as _W1G3Permanent


def _w1g3_board(set_pool, mine=(), theirs=()):
    """A duel with each seat's permanents named in board order. Lands come from
    Alpha — Invasion prints no dual land with two basic land types, and the
    whole question here is which *types* a board holds."""
    w1g3_inv, w1g3_lea = set_pool("INV"), set_pool("LEA")
    w1g3_game = _W1G3Game(
        players=[_W1G3PlayerState(name="W1G3-A"), _W1G3PlayerState(name="W1G3-B")]
    )
    w1g3_game.enforce_mana_costs = False
    w1g3_game.active_player_index = 0
    w1g3_rows = []
    for w1g3_seat, w1g3_names in enumerate((mine, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_source = w1g3_inv if w1g3_name in w1g3_inv else w1g3_lea
            w1g3_perm = _W1G3Permanent(card=w1g3_source[w1g3_name])
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_board (creatures)


def _w1g3_pt(perm):
    return perm.effective_power, perm.effective_toughness  # _w1g3_pt


def test_w1g3_wayfaring_giant_counts_types_not_lands(set_pool):
    """"Domain — This creature gets +1/+1 for each basic land type among lands
    you control." Three Plains are one type; a printed 1/3 with one type is
    2/4, not 4/6."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant", "Plains", "Plains", "Plains"]
    )
    assert _w1g3_pt(mine[0]) == (2, 4)


def test_w1g3_wayfaring_giant_reads_a_dual_land_as_two_types(set_pool):
    """A Tropical Island is a Forest *and* an Island (CR 305.6), so one land
    is worth two — and the Forest beside it adds nothing new."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant", "Tropical Island"]
    )
    giant = mine[0]
    assert _w1g3_pt(giant) == (3, 5)

    forest = _W1G3Permanent(card=set_pool("LEA")["Forest"])
    game._put_permanent_onto_battlefield(0, forest, None)
    assert _w1g3_pt(giant) == (3, 5), "a second Forest is not a second type"

    swamp = _W1G3Permanent(card=set_pool("LEA")["Swamp"])
    game._put_permanent_onto_battlefield(0, swamp, None)
    assert _w1g3_pt(giant) == (4, 6), "the bonus follows the board (layer 7c)"

    game.remove_from_battlefield(swamp)
    game._settle()
    assert _w1g3_pt(giant) == (3, 5), "and shrinks when the type leaves"


def test_w1g3_wayfaring_giant_ignores_the_opponents_lands_and_caps_at_five(set_pool):
    """"Lands **you** control": the opponent's five types are worth nothing,
    and your own five are the most there are."""
    five = ["Plains", "Island", "Swamp", "Mountain", "Forest"]
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant"], theirs=five
    )
    assert _w1g3_pt(mine[0]) == (1, 3)

    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant", *five, "Tropical Island", "Badlands"]
    )
    assert _w1g3_pt(mine[0]) == (6, 8)


def test_w1g3_wayfaring_giant_counts_the_type_a_land_has_now(set_pool):
    """CR 305.7 / CR 613 layer 4: a land's basic land types are computed. A
    Forest an effect has made a Swamp is a Swamp for domain — so with a Swamp
    already beside it the count *drops* to one, which the printed type line
    would never say."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant", "Forest", "Swamp"]
    )
    giant, forest = mine[0], mine[1]
    assert _w1g3_pt(giant) == (3, 5)

    _w1g3_change_land_type(forest, "swamp", source="w1g3-test")
    game._settle()
    assert forest.basic_land_types == ("swamp",)
    assert _w1g3_pt(giant) == (2, 4)


def test_w1g3_kavu_scout_gets_power_only(set_pool):
    """"Domain — This creature gets **+1/+0** for each basic land type among
    lands you control." A printed 0/2: the toughness never moves."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Kavu Scout", "Mountain", "Forest", "Tropical Island"]
    )
    scout = mine[0]
    assert _w1g3_pt(scout) == (3, 2)

    game, mine, _theirs = _w1g3_board(set_pool, mine=["Kavu Scout"])
    assert _w1g3_pt(mine[0]) == (0, 2), "no lands, no domain"


def test_w1g3_kavu_scout_attacks_for_its_domain(set_pool):
    """Driven through a real combat: the damage dealt is the computed power."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Kavu Scout", "Mountain", "Island", "Swamp", "Plains"]
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.current_step = "declare_blockers"
    game.declare_blockers(1, {})
    game.current_step = "combat_damage"
    game.resolve_combat_damage(0)
    assert game.players[1].life == 16, game.log[-8:]
