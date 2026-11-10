"""A holder made before its card reached the graveyard names the card that got there.

Since Mirrodin's wave 2 the graveyard's one arrival lands a copy colliding
with an object some graveyard already holds as a new, equal object (CR 400.7,
``Game.put_card_into_graveyard``; ``test_mrd_w2g7_graveyard_identity.py``).
Every reader handed the landed object is exact. These are the readers made
**before** the arrival, about the permanent's own card — and an identity search
for that card finds the older copy:

* an activated ability whose cost sacrificed its own source — Tempest Efreet's
  "exchange ownership of the revealed card and Tempest Efreet" handed the
  opponent back their own Efreet from the first exchange
  (``test_legends_creatures_round_30_onward``'s second-Efreet test, red on
  the merge gate);
* the creatures Sword of the Ages' cost ate, two copies of one card among them;
* a trigger whose source a state-based action binned before it resolved —
  Puppet Master's "return this card to its owner's hand", with an older Puppet
  Master already in the graveyard.

The death records the landed object on the permanent
(``graveyard_order.CARD_IN_GRAVEYARD``), and an ability's execution context
reads "this card" through ``graveyard_order.graveyard_object_of``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.graveyard_order import CARD_IN_GRAVEYARD
from engine.models import Permanent


def test_sword_of_the_ages_exiles_both_copies_its_cost_ate(set_pool):
    lea, leg = set_pool("LEA"), set_pool("LEG")
    sword = Permanent(card=leg["Sword of the Ages"])
    bears = [Permanent(card=lea["Grizzly Bears"]) for _ in range(2)]
    for permanent in (sword, *bears):
        permanent.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sword, *bears]), PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(
        0, "Sword of the Ages", target_player_index=1,
        cost_permanent_ids=[bear.permanent_id for bear in bears],
    )
    game._settle()

    assert result.supported
    assert game.players[1].life == 16, "2 + 2 total power"
    # The second Bears landed as its own object, which the death recorded.
    assert CARD_IN_GRAVEYARD in bears[1].metadata
    assert sorted(c.name for c in game.players[0].exile) == [
        "Grizzly Bears", "Grizzly Bears", "Sword of the Ages",
    ]
    assert game.players[0].graveyard == []


def test_puppet_master_buys_back_the_copy_that_was_on_the_battlefield(set_pool):
    leg, lea = set_pool("LEG"), set_pool("LEA")
    host = Permanent(card=lea["Grizzly Bears"])
    aura = Permanent(card=leg["Puppet Master"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[aura]),
        PlayerState(name="P2", battlefield=[host]),
    ])
    attach_aura(aura, host)
    # An older Puppet Master already in P1's graveyard.
    older = game.put_card_into_graveyard(0, leg["Puppet Master"])
    game.players[0].mana_pool["U"] = 3

    game._destroy_target_permanent(game.players[1], described={"type_filter": "creature"})
    game.check_state_based_actions()
    game.resolve_stack()
    pile = game.players[0].graveyard
    assert [c.name for c in pile] == ["Puppet Master", "Puppet Master"]
    assert pile[0] is older and pile[1] is not older

    assert game.confirm_optional_pay(0, "Puppet Master", accept=True)

    assert [c.name for c in game.players[0].hand] == ["Puppet Master"]
    assert game.players[0].graveyard == [older]
    assert game.players[0].graveyard[0] is older
