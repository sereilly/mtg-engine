"""Web-API test for the planeswalker loyalty-ability picker.

Clicking a planeswalker used to activate whichever loyalty ability was printed
first — the client's ability menu only recognised a ``{cost}:`` line, so a
walker's ``+1:`` / ``-2:`` / ``-6:`` lines produced no options at all and the
activate action went out with no ``ability_index``. The engine then fell back to
"the first ability this permanent can pay for", which is the plus ability on
every walker in the pool: its minus abilities were unreachable from the board.

The client now parses loyalty lines into the same menu and greys an option it
can't pay for. Both halves need state only the server has, so this covers the
fields the payload carries and the requests the menu issues.
"""
from __future__ import annotations

import pytest

from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine import load_cards
from tests.helpers import client
from web.app import store

_M21 = {c.name: c for c in load_cards(manifest_set_path("M21"))}


def _new_hvh_session() -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4242,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _walker_session(name: str = "Basri Ket"):
    """A session whose seat 0 controls *name* in its own precombat main phase."""
    sid = _new_hvh_session()
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    walker = Permanent(card=_M21[name])
    # CR 306.5c: loyalty on the battlefield *is* the loyalty counters, set on
    # entry. A hand-built board sets it the way one sets damage_marked.
    walker.metadata["loyalty_counters"] = int(_M21[name].loyalty)
    game.players[0].battlefield = [walker]
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return sid, game, walker


def _my_walker(sid: str) -> dict:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return state["players"][0]["battlefield"][0]


def _activate(sid: str, name: str, ability_index: int, **extra):
    body = {
        "seat": 0,
        "action": "activate",
        "permanent_name": name,
        "permanent_index": 0,
        "ability_index": ability_index,
    }
    body.update(extra)
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_payload_carries_the_three_things_the_menu_gates_on():
    """Loyalty on the card, the once-per-turn flag, and the timing widener."""
    sid, _game, _walker = _walker_session()
    payload = _my_walker(sid)

    assert payload["is_planeswalker"] is True
    # Loyalty rides in the generic counters map, so the menu can show "has N".
    assert payload["counters"]["loyalty"] == 3
    assert payload["loyalty_ability_used_this_turn"] is False
    # Basri Ket does not widen its own window; Teferi does (below).
    assert payload["loyalty_any_time"] is False


def test_each_loyalty_ability_is_addressable_by_its_index():
    """The menu's whole point: index 1 activates the -2, not the +1."""
    sid, game, walker = _walker_session()
    # -2: the delayed attack trigger. Loyalty 3 - 2 = 1.
    response = _activate(sid, "Basri Ket", 1)
    assert response.status_code == 200, response.text
    assert walker.metadata["loyalty_counters"] == 1


def test_the_plus_ability_still_raises_loyalty():
    sid, game, walker = _walker_session()
    response = _activate(sid, "Basri Ket", 0, target_permanent_index=None)
    assert response.status_code == 200, response.text
    assert walker.metadata["loyalty_counters"] == 4


def test_the_used_this_turn_flag_flips_after_one_activation():
    """The flag the menu greys every button on (CR 606.3)."""
    sid, game, _walker = _walker_session()
    assert _activate(sid, "Basri Ket", 0).status_code == 200
    assert _my_walker(sid)["loyalty_ability_used_this_turn"] is True
    # The first ability has resolved off the stack, so the second attempt meets
    # the once-per-turn half of 606.3 rather than the stack-empty half.
    game.stack.clear()
    second = _activate(sid, "Basri Ket", 1)
    assert second.status_code == 400
    assert "already been activated this turn" in second.json()["detail"]


def test_an_unaffordable_minus_ability_is_refused_by_the_engine():
    """What the greyed-out button corresponds to: CR 606.6, cost > loyalty."""
    sid, _game, _walker = _walker_session()
    # -6 with 3 loyalty on the card.
    response = _activate(sid, "Basri Ket", 2)
    assert response.status_code == 400
    assert "does not have enough loyalty counters" in response.json()["detail"]


def test_teferi_reports_the_static_that_widens_the_timing_window():
    """The field that decides whether the menu greys everything off-turn."""
    sid, _game, _walker = _walker_session("Teferi, Master of Time")
    assert _my_walker(sid)["loyalty_any_time"] is True


def test_a_walker_carries_one_target_spec_per_loyalty_ability():
    """The menu swaps in ability_target_specs[i] before prompting for targets."""
    sid, _game, _walker = _walker_session()
    payload = _my_walker(sid)
    specs = payload.get("ability_target_specs")
    assert isinstance(specs, list) and len(specs) == 3


def test_a_non_planeswalker_is_not_reported_as_one():
    """The is_planeswalker flag is what stops the client reading a creature's
    'Choose one -' bullets or a '2: ...' line as a loyalty cost."""
    sid = _new_hvh_session()
    session = store.get(sid)
    session.game.enforce_mana_costs = False
    session.game.players[0].battlefield = [Permanent(card=_M21["Garruk's Warsteed"])]
    payload = _my_walker(sid)
    assert payload["is_planeswalker"] is False
    assert payload["loyalty_any_time"] is False
    assert payload["loyalty_ability_used_this_turn"] is False


@pytest.mark.parametrize("index,expected", [(0, 9), (2, None)])
def test_ugin_plus_two_and_its_unaffordable_minus_ten(index, expected):
    """Ugin enters at 7: +2 is payable, -10 is not."""
    sid, _game, walker = _walker_session("Ugin, the Spirit Dragon")
    response = _activate(sid, "Ugin, the Spirit Dragon", index)
    if expected is None:
        assert response.status_code == 400
        assert "does not have enough loyalty counters" in response.json()["detail"]
    else:
        assert response.status_code == 200, response.text
        assert walker.metadata["loyalty_counters"] == expected
