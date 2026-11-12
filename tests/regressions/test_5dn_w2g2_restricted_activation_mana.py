"""An activation paid out of a restricted mana bucket notes what it spent.

"{1}, {T}: Put a charge counter on this artifact. Note the type of mana spent
to pay this activation cost." (Jeweled Amulet.) The activation path measured
``choices["mana_spent_for_cost"]`` as the difference the payment made to
``mana_pool`` alone, so mana held under a CR 106.6 restriction that admits an
activation — "Spend this mana only to activate abilities of artifacts" (Soldevi
Machinist), "…cast artifact spells or activate abilities of artifacts"
(Vedalken Engineer), "This mana can't be spent to cast spells" (Thran Turbine)
— paid the cost and was noted as nothing: the Amulet logged "noted no mana" and
its second ability added none. Measured now over the pool and every bucket
(``sunburst.pool_units``, the cast side's measurement).

The census (Fifth Dawn wave 2, W2G2): three abilities read the record — Jeweled
Amulet and Ice Cauldron (``note_mana_spent``, artifacts, so all three buckets
can pay them) and Protective Sphere (an enchantment: only Thran Turbine's
colourless mana reaches it, and colourless prevents nothing either way).

Validated backwards: on the tree before the fix every row notes ``{}`` and the
second ability adds nothing.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.noted_mana import noted_mana
from engine.restricted_mana import mana_bucket
from tests.helpers import settle


@pytest.mark.parametrize("key, symbol", [
    ("artifact_or_artifact_ability", "U"),   # Vedalken Engineer
    ("artifact_ability", "C"),               # Soldevi Machinist
    ("not_cast", "C"),                       # Thran Turbine
])
def test_jeweled_amulet_notes_restricted_mana_that_paid_it(set_pool, key, symbol):
    amulet = Permanent(card=set_pool("ICE")["Jeweled Amulet"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[amulet]),
        PlayerState(name="P1"),
    ])
    game.active_player_index = 0
    game.enforce_mana_costs = True
    game._sync_control()
    amulet.metadata["summoning_sickness_turn"] = -99
    mana_bucket(game.players[0], key)[symbol] = 1

    charged = game.activate_permanent_ability(0, "Jeweled Amulet", ability_index=0)
    settle(game)
    assert charged.supported, charged.details
    assert counters_on(amulet, "charge") == 1
    assert game.players[0].restricted_mana[key][symbol] == 0, "the bucket paid"
    assert noted_mana(amulet) == {symbol: 1}

    amulet.tapped = False
    spent = game.activate_permanent_ability(0, "Jeweled Amulet", ability_index=1)
    settle(game)
    assert spent.supported, spent.details
    assert game.players[0].mana_pool[symbol] == 1
