"""The pay-X panel's ceiling on the wire (Darksteel W1G5).

"Whenever you gain life, you may pay {X}, where X is less than or equal to the
amount of life you gained. If you do, draw X cards." (Well of Lost Dreams.)
CR 107.3f leaves the X to the payer and the clause bounds it, so the
``pay_any_amount`` prompt carries a ``maximum`` and the server renders only the
answers the resolver will accept — the client's buttons are the ``options`` it
is sent, so it needs no change to honour the ceiling.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from web.prompt_registry import PromptContext
from web.prompts import render_prompts
from web.serialization import _serialize_card_summary


def _prompts(game, seat):
    return render_prompts(PromptContext(
        game=game, viewer_seat=seat, serialize_card=_serialize_card_summary,
        seat_type=lambda s: "human",
    ))


def _table(set_pool, lands: int):
    lea = set_pool("LEA")
    game = Game([PlayerState(name="Alice", library=[lea["Forest"]] * 5),
                 PlayerState(name="Bob", library=[lea["Forest"]] * 5)])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    for _ in range(lands):
        game._put_permanent_onto_battlefield(0, Permanent(card=lea["Forest"]), None)
    return game


def test_the_pay_x_offer_stops_at_the_printed_ceiling(set_pool):
    game = _table(set_pool, lands=3)
    game.arm_pending_choice(
        "pay_any_amount", 0, card_name="Well of Lost Dreams", pays_x=True,
        maximum=1, _results={},
    )
    offer = _prompts(game, 0)["pay_any_amount"]
    assert offer["pays_x"] is True
    assert offer["maximum"] == 1 and offer["options"] == [0, 1]
    assert offer["ceiling"] == 1


def test_the_board_still_bounds_an_offer_under_a_higher_ceiling(set_pool):
    game = _table(set_pool, lands=2)
    game.arm_pending_choice(
        "pay_any_amount", 0, card_name="Well of Lost Dreams", pays_x=True,
        maximum=6, _results={},
    )
    offer = _prompts(game, 0)["pay_any_amount"]
    assert offer["options"] == [0, 1, 2] and offer["ceiling"] == 6


def test_an_offer_with_no_printed_ceiling_carries_none(set_pool):
    game = _table(set_pool, lands=2)
    game.arm_pending_choice(
        "pay_any_amount", 0, card_name="Hollow Specter", pays_x=True, _results={},
    )
    offer = _prompts(game, 0)["pay_any_amount"]
    assert "ceiling" not in offer and offer["options"] == [0, 1, 2]
