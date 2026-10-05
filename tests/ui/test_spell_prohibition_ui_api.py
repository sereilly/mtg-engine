"""A seat that may not cast reads as unable to — on the board and to the AI.

"Until end of turn, target player can't cast instant or sorcery spells."
(Abeyance.) "Target player can't cast spells this turn." (Orim's Chant.) Both
are a per-turn *record* (``engine/spell_prohibitions.py``) rather than a
permanent's text, and the cast path has refused by it since Abeyance. Two
readers beside the cast path did not ask it:

* the board's castable highlight (``web/state_view._card_castable_now``), so a
  banned player's hand glowed and every click was refused;
* the AI's proposal filter (``ai_policy._can_cast_with_targets``), so a banned
  seat proposed its hand and was refused once per card.

Driven here through the record's own writer, on shipped cards, because the
running app cannot hold a card from a measured set — the untyped sentence's
own card (Orim's Chant) is tested in ``tests/sets/test_pls_instants.py``.

The last test is the cast client's half of a cost that returns a permanent
("Kicker—Return a creature you control to its owner's hand", Arctic Merfolk):
the set picker with the cost's own verb, since the one-click picker beneath it
says "sacrifice" and answers on a field the return charger does not read.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.spell_prohibitions import (ANY_SPELL, clear_turn_spell_prohibitions,
                                       forbid_casting_this_turn)
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

#: An instant, a creature spell and a land: what a typed ban tells apart, and
#: what the untyped one does not.
_HAND = ["Lightning Bolt", "Grizzly Bears", "Mountain"]


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4242,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    game.players[0].battlefield = [
        Permanent(card=_CARDS[name]) for name in ("Mountain", "Forest", "Forest")
    ]
    game.players[1].battlefield = [Permanent(card=_CARDS["Hill Giant"])]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand = [_CARDS[name] for name in _HAND]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _playable(sid) -> list[str]:
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return [_HAND[index] for index in state["players"][0]["playable_hand_indices"]]


def test_the_whole_hand_glows_with_no_prohibition():
    sid, _game = _session()
    assert _playable(sid) == _HAND


def test_a_typed_prohibition_takes_the_glow_off_that_type_alone():
    """Abeyance's sentence: instants stop glowing, the creature spell and the
    land do not — and the cast path agrees with each."""
    sid, game = _session()
    forbid_casting_this_turn(game, 0, ("instant", "sorcery"))
    assert _playable(sid) == ["Grizzly Bears", "Mountain"]

    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not refused.supported and "can't cast instant spells" in refused.details
    assert [card.name for card in game.players[0].hand] == _HAND


def test_the_untyped_prohibition_leaves_only_the_land_drop():
    """Orim's Chant's sentence: every spell, and a land is not one (CR 305.1)."""
    sid, game = _session()
    forbid_casting_this_turn(game, 0, (ANY_SPELL,))
    assert _playable(sid) == ["Mountain"]


def test_the_glow_returns_with_the_next_turn():
    sid, game = _session()
    forbid_casting_this_turn(game, 0, (ANY_SPELL,))
    clear_turn_spell_prohibitions(game)
    assert _playable(sid) == _HAND


def test_a_prohibited_seat_proposes_only_what_it_may_still_play():
    """The AI's proposal filter asks the record the cast path refuses by, so a
    banned seat is not refused once per card per decision."""
    _sid, game = _session()
    game.current_phase = "main"
    assert choose_cast_action(game, 0) is not None

    forbid_casting_this_turn(game, 0, (ANY_SPELL,))
    proposed = choose_cast_action(game, 0)
    assert proposed is None or proposed.card_name == "Mountain"

    clear_turn_spell_prohibitions(game)
    forbid_casting_this_turn(game, 0, ("creature",))
    proposed = choose_cast_action(game, 0)
    assert proposed is None or proposed.card_name != "Grizzly Bears"


def test_a_cast_cost_that_returns_a_permanent_opens_the_set_picker_with_its_verb():
    cost_prompt = app_js_function_body("startCastCostPrompt")
    assert "costSpec.return_cost" in cost_prompt
    assert cost_prompt.count("startCastPermanentSetCostPrompt(") == 1
    set_picker = app_js_function_body("startCastPermanentSetCostPrompt")
    assert "verb: permanentCostVerb(costSpec)" in set_picker
    assert 'verb: "sacrifice"' not in set_picker
