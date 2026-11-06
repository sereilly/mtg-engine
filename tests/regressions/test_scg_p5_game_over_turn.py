"""A game that ends part-way through a turn goes no further (SCG Phase 5, W2).

Smoke game 2, turn 18: Sulfuric Vortex took the person to 0 in their upkeep;
the log read "Player 1 lost the game (704.5a)", then "Player 1 drew 1 card(s)
in draw step", and the game's last state was the precombat main phase. CR
104.1: "A game ends immediately when a player wins".

Driven through the web API as the browser drives a ``human_vs_ai`` game, one
row per step a game can end in on the server's own stepping — the upkeep (the
person's and the AI's), the draw step, the end step — each asking that after
the loss line nothing is drawn, no step begins and nothing triggers. The
engine half (every stepping entry point) is
``tests/engine/test_scg_p5_game_over_stepping.py``.
"""

from __future__ import annotations

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}
_LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


def _session(first: int):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_deck_cards": _LANDS, "guest_deck_cards": _LANDS, "seed": 11},
    ).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, first)
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 12
    return sid, session


def _put(game, seat: int, names) -> list:
    placed = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _play_until_over(sid: str, limit: int = 60) -> dict:
    """The browser's requests until the session is finished: the person
    passes with priority, declares nothing, and asks for an ``ai_step`` on
    the AI's turn."""
    state = _state(sid)
    for _ in range(limit):
        if state["status"] == "finished":
            return state
        combat = state.get("combat") or {}
        if state["priority_player"] == 0:
            body = {"action": "pass_priority"}
        elif state["current_turn"] == 1:
            body = {"action": "ai_step"}
        elif state["current_step"] == "declare_attackers" and not combat.get("attackers_locked"):
            body = {"action": "declare_attackers", "attacker_ids": [], "target_seat": 1}
        elif state.get("cleanup_discard"):
            body = {"action": "cleanup_select", "hand_index": 0}
        else:
            body = {"action": "next_phase"}
        response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})
        assert response.status_code == 200, (body, response.json())
        state = _state(sid)
    raise AssertionError(f"the game never ended: {state['log'][-12:]}")


def _after_the_loss(game) -> list[str]:
    lost = max(i for i, line in enumerate(game.log) if "lost the game" in line)
    return game.log[lost + 1:]


def _assert_nothing_after(game, step: str, phase: str) -> None:
    after = _after_the_loss(game)
    assert not any("drew" in line for line in after), after
    assert not any(
        word in line for line in after for word in ("triggered", "added to stack", "resolved")
    ), after
    assert (game.current_turn_phase, game.current_step) == (phase, step), (
        game.current_turn_phase, game.current_step, game.log[-8:],
    )


def test_the_person_lost_to_sulfuric_vortex_in_their_upkeep_draws_nothing():
    """The report: the AI's Sulfuric Vortex, the person at 2 life. The AI's
    turn ends; the person's upkeep deals the 2; their draw step never comes."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 1, ["Sulfuric Vortex"])
    game.players[0].life = 2
    game.players[1].life = 20
    _play_until_over(sid)
    assert game.players[0].lost, game.log[-10:]
    assert len(game.players[0].library) == 12, game.log[-10:]
    _assert_nothing_after(game, "upkeep", "beginning")


def test_the_ai_lost_in_its_own_upkeep_draws_nothing():
    """The same Vortex, the AI at 2: the person's turn ends, and the AI's
    upkeep is the game's last moment."""
    sid, session = _session(first=0)
    game = session.game
    _put(game, 0, ["Sulfuric Vortex"])
    game.players[1].life = 2
    _play_until_over(sid)
    assert game.players[1].lost, game.log[-10:]
    assert len(game.players[1].library) == 12, game.log[-10:]
    _assert_nothing_after(game, "upkeep", "beginning")


def test_the_person_decked_in_their_draw_step_reaches_no_main_phase():
    """An empty library: the person's draw step draws from nothing, CR
    704.5b ends the game, and the main phase is never entered."""
    sid, session = _session(first=1)
    game = session.game
    game.players[0].library = []
    _play_until_over(sid)
    assert game.players[0].lost, game.log[-10:]
    _assert_nothing_after(game, "draw", "beginning")


def test_the_ai_lost_in_its_end_step_takes_no_cleanup_and_no_next_turn():
    """Erg Raiders, tapped and so unable to attack, deals 2 to the AI at 2
    at the beginning of its end step: no cleanup step, and the person's turn
    never begins."""
    sid, session = _session(first=1)
    game = session.game
    (raiders,) = _put(game, 1, ["Erg Raiders"])
    raiders.tapped = True
    game.players[1].life = 2
    turn = game.turn
    _play_until_over(sid)
    assert game.players[1].lost, game.log[-10:]
    assert game.turn == turn and session.current_turn == 1, game.log[-10:]
    _assert_nothing_after(game, "end", "ending")
