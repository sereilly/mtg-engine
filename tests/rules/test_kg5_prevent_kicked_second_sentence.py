"""Kicked Magma Burst is **two instances** of damage from the spell, not one.

"Kicker—Sacrifice two lands. / Magma Burst deals 3 damage to any target. If
this spell was kicked, it deals 3 damage to another target." Two printed
sentences, followed in the order written (CR 608.2c): two events, as
Illuminate's two sentences are (``test_kg4_615_next_instance``'s
``test_two_damage_sentences_of_one_spell_are_two_instances``). Its rulings
(2004-10-04) say only that the second target is chosen if the kicker is paid
and is a different one — nothing makes the two damages simultaneous.

The lowering reads the pair as one divided instruction over two targets
(``grammar/lowering/damage.kicked_second_damage_target``), and the handler
dealt a divided instruction as one dealing (``deal_at_once``) — so CR 615.8's
"next instance of damage from that source", which is the whole dealing (the
project owner's ruling, 2026-11-07), took both: a Pilgrim of Justice naming
the spell stopped all 6. The kicked arm is now marked
``oracle_types.SEPARATE_DEALINGS`` and each target is dealt its own event, in
the order announced. Validated backwards: on the base (``59f133e6``) the
board fails (Bob takes nothing).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle

_SEATS = [pytest.param(set(), id="nobody-asked"), pytest.param({0, 1}, id="interactive")]


@pytest.mark.cr("615.8", "608.2c")
@pytest.mark.parametrize("interactive", _SEATS)
def test_pilgrim_of_justice_stops_only_kicked_magma_burst_s_first_sentence(
    catalog_by_name, interactive,
):
    """Alice's kicked Magma Burst at Bob's Craw Wurm and then at Bob; Bob's
    Pilgrim of Justice ("The next time a red source of your choice would deal
    damage this turn, prevent that damage") names it on the stack. The first
    sentence's 3 to the Wurm is prevented; the second sentence is the next
    instance, and Bob is dealt 3."""
    game = Game(players=[
        PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20,
                    hand=[catalog_by_name["Magma Burst"]]),
        PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main1"

    def put(seat, name):
        permanent = Permanent(card=catalog_by_name[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        return permanent

    lands = [put(0, "Mountain"), put(0, "Mountain")]
    put(1, "Pilgrim of Justice")
    wurm = put(1, "Craw Wurm")
    wurm_slot = next(i for i, p in enumerate(game.controlled_by(1)) if p is wurm)
    queued = game.queue_from_hand(
        0, "Magma Burst", optional_cost_payments={"sacrifice two lands": 1},
        divided_targets=[(1, wurm_slot), (1, None)],
        cost_permanent_ids=[land.permanent_id for land in lands],
    )
    assert queued.supported, queued.details
    armed = game.activate_permanent_ability(1, "Pilgrim of Justice", target_stack_index=0)
    assert armed.supported, armed.details
    settle(game)

    assert wurm.damage_marked == 0 and game.is_on_battlefield(wurm), game.log
    assert game.players[1].life == 17, game.log
