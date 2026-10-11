"""An effect's cost is paid with whatever mana its payer may spend on it
(CR 609.4b, CR 106.6).

"You may spend white mana as though it were mana of any color. You may spend
other mana only as though it were colorless mana." (Celestial Dawn.) The cast
path has honoured that since the card arrived. A cost charged by an *effect* —
an upkeep's "unless you pay {G}{G}{G}{G}", a "you may pay {1}{B}" — is planned
by ``mana_payment.plan_payment``, which taps lands too, and it matched each
coloured pip to a land that **produces** that colour without asking what the
seat may spend the mana as. Under the Dawn every land is a Plains, so no
effect-priced coloured cost but {W} could be paid at all.

``plan_payment`` takes the payer now.
``tests/engine/test_effect_costs_under_spending_permissions.py`` is the census
over every permission in the pool; these are the shapes on shipped cards, with
the board read after each payment.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.board_payment import board_can_pay
from engine.models import Permanent
from tests.helpers import _nosick


def _table(catalog_by_name, mine):
    board = [_nosick(Permanent(card=catalog_by_name[name])) for name in mine]
    game = Game(players=[
        PlayerState(name="Payer", battlefield=board,
                    library=[catalog_by_name["Forest"]] * 6),
        PlayerState(name="Other", library=[catalog_by_name["Forest"]] * 6),
    ])
    return game, board


def test_force_of_natures_upkeep_is_paid_in_white_under_celestial_dawn(catalog_by_name):
    """"At the beginning of your upkeep, Force of Nature deals 8 damage to you
    unless you pay {G}{G}{G}{G}." Four lands that are Plains under the Dawn pay
    it — white as green — and the same four lands without the Dawn (two
    Forests, a Swamp, an Island) cannot. Before the planner asked, the Dawn's
    controller took the 8 with four untapped lands that could have paid."""
    lands = ["Forest", "Forest", "Swamp", "Island"]

    game, board = _table(catalog_by_name, ["Force of Nature", *lands, "Celestial Dawn"])
    game.start_turn(0)
    game._settle()
    assert game.players[0].life == 20
    assert [perm.card.name for perm in board if perm.tapped] == lands
    assert "Payer paid upkeep for Force of Nature" in game.log

    game, board = _table(catalog_by_name, ["Force of Nature", *lands])
    game.start_turn(0)
    game._settle()
    assert game.players[0].life == 12
    assert not any(perm.tapped for perm in board)


def test_an_optional_blue_cost_is_payable_in_white_under_celestial_dawn(catalog_by_name):
    """The repro the defect was measured on: under Celestial Dawn with two
    lands the exact planner said {U} could be paid and the effect-cost one
    said it could not. They agree now, and the plan taps one land."""
    game, board = _table(catalog_by_name, ["Celestial Dawn", "Forest", "Swamp"])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    player = game.players[0]

    assert board_can_pay(game, 0, {"U": 1})
    assert game._player_can_pay_optional(player, {"cost": {"U": 1}})
    plan = game._optional_pay_plan(player, {"cost": {"U": 1, "generic": 1}})
    assert plan is not None and len(plan.tapped) == 2 and plan.from_pool == {}
    assert game._optional_pay_plan(player, {"cost": {"U": 2, "generic": 1}}) is None


def test_floating_black_is_no_payment_for_a_black_pip_under_celestial_dawn(catalog_by_name):
    """The other direction, and the reason the pool cannot be spent ahead of
    the matching: "other mana only as though it were colorless" takes a unit's
    own colour away. A floating {B} pays generic and nothing coloured — the
    planner used to spend it on a {B} pip the cast path would have refused."""
    game, _board = _table(catalog_by_name, ["Celestial Dawn"])
    game.start_turn(0)
    game._settle()
    player = game.players[0]
    player.mana_pool["B"] = 1

    assert not board_can_pay(game, 0, {"B": 1})
    assert game._optional_pay_plan(player, {"cost": {"B": 1}}) is None
    assert game._optional_pay_plan(player, {"cost": {"generic": 1}}).from_pool == {"B": 1}

    player.mana_pool["W"] = 1
    plan = game._optional_pay_plan(player, {"cost": {"B": 1, "generic": 1}})
    assert plan is not None and plan.from_pool == {"W": 1, "B": 1}


def test_sunglasses_of_urza_pays_a_red_toll_with_a_plains(catalog_by_name):
    """"You may spend white mana as though it were red mana." A Plains pays an
    effect's {R}; it does not pay its {G}."""
    game, _board = _table(catalog_by_name, ["Sunglasses of Urza", "Plains"])
    game.start_turn(0)
    game._settle()
    player = game.players[0]

    assert game._player_can_pay_optional(player, {"cost": {"R": 1}})
    assert not game._player_can_pay_optional(player, {"cost": {"G": 1}})
