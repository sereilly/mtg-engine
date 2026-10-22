"""Apocalypse lands.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

import pytest as _w1g9_pytest

from engine import Game as _w1g9_Game
from engine import PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from tests.helpers import resolve_stack as _w1g9_resolve_stack

#: The five pain lands and the two colours each prints, in printed order. A
#: list of tuples, so the parametrized ids collect in one order on every
#: xdist worker.
_W1G9_PAINLANDS = [
    ("Battlefield Forge", "RW"),
    ("Caves of Koilos", "WB"),
    ("Llanowar Wastes", "BG"),
    ("Shivan Reef", "UR"),
    ("Yavimaya Coast", "GU"),
]


def _w1g9_land_game(set_pool, name, *, hand=(), interactive=True):
    """*name* alone on seat 0's battlefield in its main phase.

    Interactive on both seats by default, deliberately: for a non-interactive
    table ``activate_permanent_ability`` settles the stack itself, so an
    ability that wrongly went onto the stack would resolve anyway and read as
    "resolved" — the harness would report the defect as its own fix.
    """
    lea = set_pool("LEA")
    land = _w1g9_Permanent(card=set_pool("APC")[name])
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P1", battlefield=[land], hand=list(hand),
            library=[lea["Island"]] * 5,
        ),
        _w1g9_PlayerState(name="P2", library=[lea["Island"]] * 5),
    ])
    game.interactive_seats = {0, 1} if interactive else set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game, land


def _w1g9_pool(game, seat=0):
    return {symbol: n for symbol, n in game.players[seat].mana_pool.items() if n}


@_w1g9_pytest.mark.parametrize("name, colors", _W1G9_PAINLANDS)
def test_w1g9_a_painlands_colorless_mana_is_free(set_pool, name, colors):
    """"{T}: Add {C}." The first ability, and the one that hurts nobody."""
    game, land = _w1g9_land_game(set_pool, name)

    assert game.tap_land_for_mana(0, name, "C", permanent_id=land.permanent_id)

    assert _w1g9_pool(game) == {"C": 1}
    assert game.players[0].life == 20
    assert land.tapped and not game.stack


@_w1g9_pytest.mark.parametrize("name, colors", _W1G9_PAINLANDS)
def test_w1g9_a_painlands_colored_mana_costs_a_point_of_damage(set_pool, name, colors):
    """"{T}: Add {R} or {W}. This land deals 1 damage to you." Either printed
    colour, one damage each time, counted as damage taken this turn."""
    for color in colors:
        game, land = _w1g9_land_game(set_pool, name)

        assert game.tap_land_for_mana(
            0, name, color, permanent_id=land.permanent_id, ability_index=1,
        )

        assert _w1g9_pool(game) == {color: 1}, (name, color)
        assert game.players[0].life == 19
        assert game.players[0].damage_taken_this_turn == 1
        assert f"{name} dealt 1 damage to P1" in game.log
        assert land.tapped and not game.stack


@_w1g9_pytest.mark.parametrize("name, colors", _W1G9_PAINLANDS)
def test_w1g9_a_painlands_colored_ability_never_uses_the_stack(set_pool, name, colors):
    """CR 605.3b, through the door the web wire uses. "Add mana. ⟨rider⟩"
    lowers to a sequence, and it is still a mana ability: queued with both
    seats interactive it resolves where it stands — the mana is in the pool and
    the damage is dealt with nothing for anybody to respond to (the card's own
    ruling: "It doesn't use the stack and can't be responded to")."""
    from engine.mana_payment import is_mana_ability

    game, land = _w1g9_land_game(set_pool, name)
    assert [is_mana_ability(a) for a in game.usable_abilities_of(land)] == [True, True]

    queued = game.queue_permanent_ability(
        0, name, permanent_index=0, ability_index=1, mana_color=colors[1],
    )

    assert queued.supported, queued.details
    assert not game.stack
    assert _w1g9_pool(game) == {colors[1]: 1}
    assert game.players[0].life == 19


def test_w1g9_a_painlands_damage_is_damage_and_a_shield_prevents_it(set_pool):
    """The rider is *damage dealt by the land*, not life loss: a prevention
    shield on its controller absorbs it (CR 615), and the mana is made all the
    same."""
    game, land = _w1g9_land_game(
        set_pool, "Shivan Reef", hand=[set_pool("LEA")["Healing Salve"]],
        interactive=False,
    )
    game.enforce_mana_costs = False
    salve = game.cast_from_hand(0, "Healing Salve", target_player_index=0, mode_index=1)
    assert salve.supported, salve.details
    _w1g9_resolve_stack(game)
    assert game.players[0].damage_prevention_pool == 3

    assert game.tap_land_for_mana(
        0, "Shivan Reef", "U", permanent_id=land.permanent_id, ability_index=1,
    )

    assert _w1g9_pool(game) == {"U": 1}
    assert game.players[0].life == 20
    assert game.players[0].damage_prevention_pool == 2
    assert "Shivan Reef dealt 0 damage to P1" in game.log


def test_w1g9_the_highlight_and_the_ai_both_reach_a_painlands_color(set_pool):
    """The two readers that tap lands through their own doors. The castable
    highlight (`board_can_pay`) counts the land for either printed colour and
    for no third, and for one pip at a time; the AI's planner taps it by the
    ability that makes the colour, pays for a Lightning Bolt with it, and takes
    the point of damage — where a generic cost is paid with the painless {C}."""
    from engine.ai_policy import choose_cast_action
    from engine.ai_payment import tap_planned_lands
    from engine.board_payment import board_can_pay

    lea = set_pool("LEA")
    game, land = _w1g9_land_game(
        set_pool, "Shivan Reef", hand=[lea["Lightning Bolt"]], interactive=False,
    )
    game.enforce_mana_costs = True

    assert board_can_pay(game, 0, {"R": 1})
    assert board_can_pay(game, 0, {"U": 1})
    assert not board_can_pay(game, 0, {"G": 1})
    assert not board_can_pay(game, 0, {"R": 1, "U": 1}), "one land, one mana"

    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Lightning Bolt"
    assert action.land_tap_colors == ("R",)
    tap_planned_lands(game, 0, action)
    cast = game.cast_from_hand(
        0, action.card_name, target_player_index=action.target_player_index,
        target_permanent_ids=action.target_permanent_ids,
    )
    _w1g9_resolve_stack(game)

    assert cast.supported, cast.details
    assert game.players[0].life == 19, "the coloured ability's damage was dealt"
    assert game.players[1].life == 17

    game, land = _w1g9_land_game(
        set_pool, "Llanowar Wastes", hand=[lea["Sol Ring"]], interactive=False,
    )
    game.enforce_mana_costs = True
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Sol Ring"
    tap_planned_lands(game, 0, action)
    assert game.cast_from_hand(0, "Sol Ring").supported
    assert game.players[0].life == 20, "a generic {1} was paid with the painful colour"

# ==== end W1G9 ========================================================

# ==== W2G1 ============================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ========================================================

# ==== W2G2 ============================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ========================================================

# ==== W2G3 ============================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ========================================================

# ==== W2G4 ============================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ========================================================

# ==== W2G5 ============================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ========================================================
