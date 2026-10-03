"""The AI's land-tapping planner asks the engine what each land makes.

``_plan_land_taps`` used to read each land as one printed symbol
(``produced_mana[0]``) and every executor tapped with the seam's default colour
"G". Measured at NEM: a Forest under Deep Water's swap makes {U}, a Forest
carrying Overlaid Terrain's granted "{T}: Add two mana of any one color" makes
two of any colour, and a dual land can make its second colour — the planner saw
none of it, so the seat held castable spells all game. It now reads
``Game._land_payment_colors`` (the hook the optional-pay planner and the
client's colour prompt read), counts a granted ability's amount, and carries
the colour it planned to the tap (``land_tap_colors`` / ``planned_tap_color``).
"""
from __future__ import annotations

from engine.ai_policy import choose_cast_action, planned_tap_color
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack


def _duel(set_pool, hand, mine):
    lea = set_pool("LEA")
    me = PlayerState(
        name="AI", hand=list(hand), library=[lea["Island"]] * 10,
        battlefield=[_nosick(Permanent(card=card)) for card in mine],
    )
    them = PlayerState(name="Opp", library=[lea["Island"]] * 10)
    game = Game(players=[me, them])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game._settle()
    return game


def _execute(game, action):
    """Tap and cast exactly as the simulator's executor does."""
    for position, slot in enumerate(action.land_tap_indices):
        land = game.permanent_at(0, slot)
        assert game.tap_land_for_mana(
            0, land.card.name, chosen_color=planned_tap_color(action, position),
            permanent_index=slot,
        )
    return game.cast_from_hand(
        0, action.card_name, target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
    )


def test_a_seat_wide_swap_is_planned_through(set_pool):
    lea = set_pool("LEA")
    game = _duel(
        set_pool, [lea["Prodigal Sorcerer"]],
        [set_pool("DRK")["Deep Water"], lea["Forest"], lea["Forest"], lea["Forest"]],
    )
    game.players[0].mana_pool["U"] = 1
    assert game.activate_permanent_ability(0, "Deep Water", permanent_index=0).supported
    resolve_stack(game)

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Prodigal Sorcerer"
    assert action.land_tap_colors == ("U", "U", "U")
    assert _execute(game, action).supported


def test_a_granted_two_mana_ability_is_planned_at_its_amount(set_pool):
    """Two Forests under Overlaid Terrain make four mana between them; read as
    one apiece, a three-drop was out of reach."""
    lea = set_pool("LEA")
    game = _duel(
        set_pool, [lea["Prodigal Sorcerer"]],
        [set_pool("NEM")["Overlaid Terrain"], lea["Forest"], lea["Forest"]],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Prodigal Sorcerer"
    assert len(action.land_tap_indices) == 2 and action.land_tap_colors[0] == "U"
    assert _execute(game, action).supported
    assert any(p.card.name == "Prodigal Sorcerer" for p in game.controlled_by(0))


def test_a_dual_land_is_asked_for_the_colour_the_plan_counted(set_pool):
    lea = set_pool("LEA")
    game = _duel(set_pool, [lea["Grizzly Bears"]], [lea["Taiga"], lea["Mountain"]])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Grizzly Bears"
    by_land = {
        game.permanent_at(0, slot).card.name: planned_tap_color(action, position)
        for position, slot in enumerate(action.land_tap_indices)
    }
    assert by_land == {"Taiga": "G", "Mountain": "R"}
    assert _execute(game, action).supported


def test_a_board_of_basics_is_planned_exactly_as_before(set_pool):
    """The greedy order is unchanged for single-colour lands: the coloured pip
    first, from the first land that makes it, then the generic in board order."""
    lea = set_pool("LEA")
    game = _duel(
        set_pool, [lea["Prodigal Sorcerer"]],
        [lea["Forest"], lea["Island"], lea["Swamp"], lea["Island"]],
    )

    action = choose_cast_action(game, 0)

    assert action.land_tap_indices == (1, 0, 2)
    assert action.land_tap_colors == ("U", "G", "B")
