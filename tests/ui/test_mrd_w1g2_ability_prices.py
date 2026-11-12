"""The wire carries what an activation will charge where it is not the printed
cost (``ability_prices``, ``web/offers.ability_price``).

"Equip costs you pay cost {1} less." (Auriok Steelshaper.) The engine charges
Leonin Scimitar's "Equip {1}" {0} (CR 601.2f via 602.2b) and the client had
only the printed line to show: nothing on the wire said the click was free.
Indexed like ``ability_index`` and present only when some ability's price
moved, so every other permanent's payload is unchanged.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from web.player_view import _serialize_player

_MRD = {card.name: card for card in load_cards(manifest_set_path("MRD", include_measured=True))}


def _put(game, seat, name):
    permanent = Permanent(card=_MRD[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _entry(payload, name):
    return next(entry for entry in payload["battlefield"] if entry["name"] == name)


def test_steelshapers_discount_is_on_the_wire_and_only_its_controllers():
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    _put(game, 0, "Leonin Scimitar")
    _put(game, 0, "Vulshok Battlegear")
    _put(game, 1, "Leonin Scimitar")
    mine = _serialize_player(game.players[0], 0, 0, game)
    assert "ability_prices" not in _entry(mine, "Leonin Scimitar"), "printed price, no key"

    _put(game, 0, "Auriok Steelshaper")
    mine = _serialize_player(game.players[0], 0, 0, game)
    assert _entry(mine, "Leonin Scimitar")["ability_prices"] == ["{0}"]
    assert _entry(mine, "Vulshok Battlegear")["ability_prices"] == ["{2}"]
    theirs = _serialize_player(game.players[1], 1, 1, game)
    assert "ability_prices" not in _entry(theirs, "Leonin Scimitar")
