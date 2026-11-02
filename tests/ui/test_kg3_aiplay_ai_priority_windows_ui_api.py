"""The web AI seat answers priority with the simulator's own windows and
choosers (kg3 `aiplay`, part 5).

``web/game_flow._ai_respond_to_priority`` cast instants and nothing else, and
the AI's own upkeep was resolved straight through, so the six "Activate only
during your upkeep" graveyard abilities were the simulator's and never a web
AI's. Both now go through ``engine.ai_priority`` — ``instant_speed_window`` and
``act_at_priority``, the one answer the simulator's priority driver gives —
and the AI's upkeep stops for it when the seat holds a graveyard ability.

Driven as the browser drives a ``human_vs_ai`` game: the human's requests
(``pass_priority``, ``declare_attackers``, ``end_turn``) and ``ai_step`` while
the AI has priority on its own turn, reading the state each seat is served.
"""

from __future__ import annotations

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}
LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_deck_cards": LANDS, "guest_deck_cards": LANDS, "seed": 11},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.game.enforce_mana_costs = True
    return sid, session


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat={seat}").json()


def _act(sid: str, **body):
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})
    return response.status_code, response.json()


def _put(game, seat: int, names) -> list:
    placed = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def _play_ai_turn(sid: str) -> None:
    """The AI's turn, driven the way the client does: the human passes when
    it holds priority, and asks for an ``ai_step`` otherwise."""
    for _ in range(60):
        state = _state(sid)
        if state["current_turn"] == 0:
            return
        if state["priority_player"] == 0:
            code, _ = _act(sid, action="pass_priority")
        else:
            code, _ = _act(sid, action="ai_step")
        assert code == 200
    raise AssertionError("the AI's turn never ended")


def _finish_own_turn(sid: str) -> None:
    """The human's turn ended the way the client ends it: passing, the
    declare-attackers step answered with no attack, the cleanup discard."""
    for _ in range(40):
        state = _state(sid)
        if state["current_turn"] != 0:
            return
        if state.get("cleanup_discard"):
            code, _ = _act(sid, action="cleanup_select", hand_index=0)
        elif state["current_step"] == "declare_attackers" and state["priority_player"] is None:
            code, _ = _act(sid, action="declare_attackers", attacker_ids=[], target_seat=1)
        else:
            code, _ = _act(sid, action="pass_priority")
            if code != 200:
                code, _ = _act(sid, action="next_phase")
        assert code == 200
    raise AssertionError("the human's turn never ended")


def _to_the_humans_turn(sid: str) -> None:
    """The session opens on whichever seat the coin chose; play the AI's
    turn out first where that is the AI."""
    if _state(sid)["current_turn"] == 1:
        _play_ai_turn(sid)
    assert _state(sid)["current_turn"] == 0


def test_the_web_ai_returns_hammer_of_bogardan_in_its_upkeep():
    """Hammer of Bogardan in the AI's graveyard and five Mountains: "{2}{R}{R}{R}:
    Return this card from your graveyard to your hand. Activate only during
    your upkeep." The human ends the turn; in the AI's upkeep the ability goes
    on the stack, the human is handed priority over it, and the Hammer comes
    back."""
    sid, session = _session()
    game = session.game
    _to_the_humans_turn(sid)
    ai = game.players[1]
    ai.battlefield = []
    _put(game, 1, ["Mountain"] * 5)
    ai.graveyard = [_CARDS["Hammer of Bogardan"]]
    ai.library = [_CARDS["Island"]] * 10
    ai.hand = []

    _finish_own_turn(sid)
    _play_ai_turn(sid)

    assert "Hammer of Bogardan ability added to stack from the graveyard" in game.log, game.log[-20:]
    hand = [card.name for card in ai.hand]
    assert "Hammer of Bogardan" in hand or any(
        "Hammer of Bogardan" in line and "cast" in line.lower() for line in game.log
    ), (hand, game.log[-20:])
    assert all(card.name != "Hammer of Bogardan" for card in ai.graveyard)


def test_the_web_ai_flashes_in_a_blocker_before_the_blocks():
    """The human attacks with Grizzly Bears; the AI holds Benalish Knight
    (flash, first strike, 2/2) and three Plains. Handed priority in the
    declare-attackers step — the simulator's ``declare_attackers`` window —
    it casts the Knight, which blocks and kills the Bears."""
    sid, session = _session()
    game = session.game
    _to_the_humans_turn(sid)
    human, ai = game.players
    human.battlefield = []
    ai.battlefield = []
    (bears,) = _put(game, 0, ["Grizzly Bears"])
    _put(game, 1, ["Plains"] * 3)
    ai.hand = [_CARDS["Benalish Knight"]]

    for _ in range(10):
        state = _state(sid)
        if state["current_step"] == "declare_attackers":
            break
        code, _ = _act(sid, action="next_phase")
        assert code == 200
    assert _state(sid)["current_step"] == "declare_attackers"
    code, body = _act(
        sid, action="declare_attackers",
        attacker_ids=[bears.permanent_id], target_seat=1,
    )
    assert code == 200, body
    for _ in range(12):
        if not game.is_on_battlefield(bears) or game.current_turn_phase != "combat":
            break
        code, _ = _act(sid, action="pass_priority")
        if code != 200:
            code, _ = _act(sid, action="next_phase")
        assert code == 200

    assert any("Benalish Knight" in line for line in game.log), game.log[-20:]
    assert any(p.card.name == "Benalish Knight" for p in game.controlled_by(1))
    assert not game.is_on_battlefield(bears), game.log[-20:]
    assert human.life == 20 and ai.life == 20


def test_the_web_ai_regenerates_in_front_of_a_burn_spell():
    """An ability at instant speed, which the web AI seat never activated:
    the human's Lightning Bolt at the AI's Drudge Skeletons ("{B}:
    Regenerate this creature"), the AI holding a Swamp. Handed priority over
    the Bolt — the ``response`` window — it raises the shield, and the
    Skeletons survive the Bolt, tapped."""
    sid, session = _session()
    game = session.game
    _to_the_humans_turn(sid)
    human, ai = game.players
    human.battlefield = []
    ai.battlefield = []
    _put(game, 0, ["Mountain"])
    (skeletons,) = _put(game, 1, ["Drudge Skeletons"])
    _put(game, 1, ["Swamp"])
    human.hand = [_CARDS["Lightning Bolt"]]
    assert _state(sid)["current_step"] == "precombat_main"

    code, body = _act(
        sid, action="cast", card_name="Lightning Bolt", target_player_index=1,
        target_permanent_id=skeletons.permanent_id, auto_tap=True,
    )
    assert code == 200, body
    for _ in range(6):
        if not game.stack:
            break
        code, _ = _act(sid, action="pass_priority")
        assert code == 200

    assert any("Drudge Skeletons" in line and "activate" in line.lower() or
               "regenerat" in line.lower() for line in game.log), game.log[-15:]
    survivor = next((p for p in game.controlled_by(1) if p.card.name == "Drudge Skeletons"), None)
    assert survivor is not None, game.log[-15:]
    assert survivor.tapped
