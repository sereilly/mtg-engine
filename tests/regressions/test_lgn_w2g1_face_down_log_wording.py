"""Two log lines that named the wrong thing (SET_PLAYBOOK, "Face-down
leftovers on the wire").

* **A face-down cast's {3} is not a morph cost.** CR 702.37a: "Morph [cost]"
  means "You may cast this card as a 2/2 face-down creature … by paying {3}
  rather than paying its mana cost" and "As long as this permanent is face
  down, you may turn it face up … by paying [cost]" — the morph cost is the
  second, the price of turning it up (CR 702.37e). The log said "Face-down
  creature cast for its morph cost (…{3})", the one thing the morph cost is
  not.
* **A land is played, never cast** (CR 305.1). A land Future Sight lets its
  controller play off the top of their library came through the zone-cast path
  and was logged "Forest cast from Alice's library".
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.cast_permissions import grant_permission
from engine.models import Permanent

_ONS = {card.name: card for card in load_cards(manifest_set_path("ONS", include_measured=True))}


def _table():
    game = Game([PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase = game.current_step = "precombat_main"
    game.enforce_mana_costs = False
    return game


def test_a_face_down_cast_is_logged_as_cast_face_down_not_for_a_morph_cost():
    game = _table()
    game.players[0].hand = [_ONS["Exalted Angel"]]
    start = len(game.log)

    result = game.cast_from_hand(0, "Exalted Angel", alternative_cost=True)

    assert result.supported, result.details
    written = game.log[start:]
    assert "Face-down creature cast face down for {3}" in written, written
    assert not any("morph cost" in line for line in written), written
    # The hidden card is not named by the public log (CR 708.5).
    assert not any("Exalted Angel" in line for line in written), written


def test_the_morph_cost_is_still_what_turning_it_face_up_is_logged_as():
    """The other half stays as it was: turning the permanent up is paying its
    morph cost (CR 702.37e), and the log says so."""
    game = _table()
    game.players[0].hand = [_ONS["Exalted Angel"]]
    assert game.cast_from_hand(0, "Exalted Angel", alternative_cost=True).supported
    game.resolve_top_of_stack()
    face_down = next(iter(game.controlled_by(0)))
    from engine.face_down import turn_face_up

    turn_face_up(game, face_down, how="for its morph cost {2}{W}{W}")

    assert any("morph cost {2}{W}{W}" in line for line in game.log[-3:]), game.log[-3:]


def test_a_land_played_from_the_top_of_a_library_is_logged_as_played():
    game = _table()
    forest = _ONS["Forest"]
    game.players[0].library = [forest, _ONS["Island"]]
    game._put_permanent_onto_battlefield(0, Permanent(card=_ONS["Future Sight"]), None)
    game._sync_control()
    grant_permission(
        game, player_index=0, zone="library", mode="play", cards=[forest],
        position="top", free=False, duration="end_of_turn",
        source_name="Future Sight",
    )
    start = len(game.log)

    result = game.cast_from_hand(0, "Forest", from_zone="library")

    assert result.supported, result.details
    written = game.log[start:]
    assert "Forest played from Alice's library" in written, written
    assert not any("cast from" in line for line in written), written
    assert any(p.card.name == "Forest" for p in game.controlled_by(0))
