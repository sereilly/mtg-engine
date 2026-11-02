"""Every "can the effect payer pay this?" plans each land as what one tap of
it adds — the reading the payment itself makes.

kg3/leftovers made the effect payer's *payment* (``Game._pay_planned_cost``)
plan each land as its units (``board_payment.plan_over_land_units``, named by
``mana_payment.payment_units_in_force``), so Ancient Tomb is {C}{C} of one
source there. Every read of the same question *outside* the payment — the
counter-unless prompt's ``payable`` and its default, the upkeep price's
affordability, the attack and block tolls' gates and plans, an optional pay,
a pay-any-amount ceiling, a special action's price — still planned over
``Game.payment_lands`` one mana per land, so a cost only the Tomb's second
{C} covers read unpayable there and was declined, sacrificed or refused.

They now ask one seam, ``Game.effect_payment_plan``, which plans under the
units planner. This census is static: no ``plan_payment`` call in ``engine/``
or ``web/`` plans over ``payment_lands`` except that seam — or inside a plan
handed to ``_pay_planned_cost``, which already names the units. Measured on
90bef6d1: 13 calls (one per function). The boards below are the reads driven.
"""

from __future__ import annotations

import ast
from pathlib import Path

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import add_counters
from tests.helpers import resolve_stack

_ROOT = Path(__file__).resolve().parents[2]
_POOL = {card.name: card for card in load_catalog()}
_SEAM = "effect_payment_plan"


def _plans_over_payment_lands() -> list[str]:
    found: list[str] = []
    examined = 0
    for folder in ("engine", "web"):
        for path in sorted((_ROOT / folder).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "plan_payment(" not in source:
                continue
            tree = ast.parse(source)
            parents: dict = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[child] = node
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "plan_payment"):
                    continue
                examined += 1
                function = node
                inside_payment = False
                while function in parents:
                    function = parents[function]
                    if (
                        isinstance(function, ast.Call)
                        and getattr(function.func, "attr", None) == "_pay_planned_cost"
                    ):
                        inside_payment = True
                    if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        break
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if function.name == _SEAM or inside_payment:
                    continue
                lands = node.args[1] if len(node.args) > 1 else None
                text = ast.get_source_segment(source, lands) if lands is not None else ""
                if isinstance(lands, ast.Name):
                    # A local assigned from the board's payment lands.
                    text += "".join(
                        ast.get_source_segment(source, assign.value) or ""
                        for assign in ast.walk(function)
                        if isinstance(assign, ast.Assign)
                        and any(getattr(t, "id", None) == lands.id for t in assign.targets)
                    )
                if "payment_lands(" in (text or ""):
                    found.append(f"{path.relative_to(_ROOT).as_posix()}:{node.lineno} {function.name}")
    # Measured after the fix: 9 calls, the seam's own among them.
    assert examined >= 8, examined
    return found


def test_no_affordability_read_plans_one_mana_per_land():
    assert _plans_over_payment_lands() == []


# ---------------------------------------------------------------------------
# The reads, driven: a cost only the Tomb's second {C} covers
# ---------------------------------------------------------------------------


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _game(*boards, interactive=()) -> Game:
    island = _POOL["Island"]
    game = Game(players=[
        PlayerState(f"P{seat}", library=[island] * 10, battlefield=[_permanent(n) for n in names])
        for seat, names in enumerate(boards)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._sync_control()
    return game


def test_mana_leak_s_three_is_payable_off_a_tomb_and_a_plains():
    game = _game(("Ancient Tomb", "Plains"), ("Island",), interactive=(0,))
    game.active_player_index = 0
    game.players[0].hand.append(_POOL["Grizzly Bears"])
    game.players[1].hand.append(_POOL["Mana Leak"])
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.queue_from_hand(1, "Mana Leak", target_stack_index=0).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    choice = game.pending_choice_of("mana_payment", 0)
    assert choice is not None, game.log[-4:]
    assert game.mana_payment_is_payable(choice), "{C}{C} and {W} cover {3}"
    assert game.resolve_pending_choice("mana_payment", 0, pay=True)
    resolve_stack(game)

    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0)), game.log[-6:]
    assert game.players[0].life == 18, "the Tomb's damage"


def test_a_seat_nobody_asks_pays_the_upkeep_only_the_tomb_covers():
    """Mystic Remora's cumulative upkeep at its second age counter: {2}, and
    an Ancient Tomb alone. Backwards on 90bef6d1 the seat could not afford it
    and sacrificed the Remora."""
    game = _game(("Ancient Tomb", "Mystic Remora"), ("Island",))
    remora = next(p for p in game.controlled_by(0) if p.card.name == "Mystic Remora")
    add_counters(remora, "age", 1)
    game.active_player_index = 0

    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)

    assert game.is_on_battlefield(remora), game.log[-6:]
    assert game.players[0].life == 18, "paid with the Tomb's {C}{C}"
