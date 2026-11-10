"""An ``ai_vs_ai`` web AI casts every spell it wants in a main phase, as the
simulator's main phase does (``ai_simulator._play_casts``).

``game_flow._ai_step``'s cast door, at a table of AI seats alone, cast once
(a settling ``cast_from_hand``) and went on to the activation doors and out
of the phase: an AI holding two Grizzly Bears and four Forests cast the
second Bears in its second main phase, every main phase of every game. At a
table with a person each cast pauses for the priority round and the next
``ai_step`` comes back to the door, so only the AI-only table was short.
The door is a loop there now, bounded as the simulator's is.
"""

from __future__ import annotations

import pytest

from engine.ai_policy import choose_cast_action
from engine.ai_rehearsal import rehearsing
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent
from tests.helpers import client, seat_plays_first

_CARDS = {card.name: card for card in load_catalog()}


def _ai_step(sid: str) -> None:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "ai_step"})
    assert response.status_code == 200, response.json()


@pytest.mark.cr("505.6", "117.3c")
def test_an_ai_only_tables_ai_casts_both_spells_before_combat():
    """Seat 0 of an ``ai_vs_ai`` table: four Forests, two Grizzly Bears in
    hand. One ``ai_step`` from its precombat main phase casts both Bears
    before the combat phase begins."""
    created = client.post("/api/sessions", json={"mode": "ai_vs_ai", "seed": 5}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 0)
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.graveyard = []
        player.hand = []
        player.library = [_CARDS["Plains"]] * 20
    for _ in range(4):
        game._put_permanent_onto_battlefield(0, Permanent(card=_CARDS["Forest"]), None)
    game.players[0].hand = [_CARDS["Grizzly Bears"], _CARDS["Grizzly Bears"]]
    assert game.current_step == "precombat_main"
    start = len(game.log)

    _ai_step(sid)

    lines = game.log[start:]
    casts = [i for i, line in enumerate(lines) if line == "Grizzly Bears added to stack"]
    combat = next(i for i, line in enumerate(lines) if "attack" in line.lower() or "combat" in line.lower())
    assert len(casts) == 2, lines
    assert max(casts) < combat, lines
    assert sum(p.card.name == "Grizzly Bears" for p in game.players[0].battlefield) == 2


def _person_or_ai_step(sid: str) -> None:
    """One request of a person who ends their own turns, passes whenever
    handed priority and declares no blocks — or, on the AI's turn with
    nobody else to act, its ``ai_step``."""
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    combat = state.get("combat") or {}
    if state["current_step"] == "declare_blockers" and not combat.get("blockers_locked"):
        body = {"action": "declare_blockers", "blocker_pairs_by_id": {}}
    elif state["current_turn"] == 0 and state.get("cleanup_discard"):
        body = {"action": "cleanup_select", "hand_index": 0}
    elif state["priority_player"] == 0:
        own_turn = state["current_turn"] == 0 and not state["stack"]
        body = {"action": "end_turn" if own_turn else "pass_priority"}
    elif state["current_turn"] == 0:
        body = {"action": "next_phase"}
    else:
        body = {"action": "ai_step"}
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})
    assert response.status_code == 200, (body, response.json())


@pytest.mark.cr("505.6")
@pytest.mark.parametrize("mode, seed", [("ai_vs_ai", 3), ("ai_vs_ai", 17), ("human_vs_ai", 17)])
def test_census_an_ai_leaves_its_main_phase_only_when_it_would_cast_nothing(monkeypatch, mode, seed):
    """Census over seeded web games — ``ai_vs_ai`` stepped by ``ai_step``
    alone, and a person's table (the person ending their turns and passing):
    each time an AI's main phase is closed
    (``Game._close_current_priority_step``), the cast chooser is asked what
    it would cast there — it must be nothing. The floor: main phases closed
    and examined, and a precombat main phase closed with spells cast in it.
    The AI-only rows fail on the tree before; the person's table held
    already, but for an AI's own resolved search (the Eladamri's Call
    board below)."""
    created = client.post("/api/sessions", json={"mode": mode, "seed": seed}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 0)
    game = session.game
    ai_seats = {s for s in range(len(game.players)) if session.seat_types.get(s, session.seat_types.get(str(s))) == "ai"}
    left_with_a_cast: list[tuple] = []
    examined = []
    real = Game._close_current_priority_step

    def watching(self, *args, **kwargs):
        if (
            self is game
            and not rehearsing()
            and self.current_step in ("precombat_main", "postcombat_main")
            and not self.stack
            and self.active_player_index in ai_seats
        ):
            seat = self.active_player_index
            spells = len(self.players[seat].spells_cast_this_turn)
            examined.append((self.turn, self.current_step, spells))
            would = choose_cast_action(self, seat)
            if would is not None:
                left_with_a_cast.append((self.turn, self.current_step, would))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Game, "_close_current_priority_step", watching)
    act = _ai_step if mode == "ai_vs_ai" else _person_or_ai_step
    for _ in range(300):
        if game.is_game_over() or game.turn > 14:
            break
        act(sid)

    assert len(examined) >= 10, examined
    assert not left_with_a_cast, left_with_a_cast
    # What the door's loop exercised: a precombat main phase closed with two
    # spells cast in it at the AI-only table; one at the person's, whose
    # web game is not the same game from one process to the next (the
    # second spell there is the Eladamri's Call board's, below).
    most = 2 if mode == "ai_vs_ai" else 1
    assert any(step == "precombat_main" and spells >= most for _t, step, spells in examined), examined


@pytest.mark.cr("117.3b", "608.2")
def test_the_ai_casts_what_its_own_resolved_search_fetched_in_the_same_main_phase():
    """A person's table, the AI's precombat main phase: Eladamri's Call
    (search for a creature card, put it into your hand) with three lands,
    Benalish Hero the creature in its library. The person passes over the
    Call; it resolves, the AI answers its search — and the resolution over,
    the active player receives priority (CR 117.3b), so the AI casts the Hero
    before combat. The round passed the AI's priority on as its search was
    answered, the person's pass over an empty stack ended the main phase, and
    the Hero waited for the second one."""
    created = client.post("/api/sessions", json={"mode": "human_vs_ai", "seed": 5}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 1)
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.graveyard = []
        player.hand = []
        player.library = [_CARDS["Plains"]] * 20
    for name in ("Plains", "Plains", "Forest"):
        game._put_permanent_onto_battlefield(1, Permanent(card=_CARDS[name]), None)
    game.players[1].hand = [_CARDS["Eladamri's Call"]]
    game.players[1].library = [_CARDS["Benalish Hero"]] + [_CARDS["Plains"]] * 19
    assert (game.active_player_index, game.current_step) == (1, "precombat_main")
    start = len(game.log)

    for _ in range(12):
        state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
        if state["current_step"] != "precombat_main" or state["current_turn"] != 1:
            break
        action = "pass_priority" if state["priority_player"] == 0 else "ai_step"
        response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": action})
        assert response.status_code == 200, response.json()

    lines = game.log[start:]
    assert "Eladamri's Call added to stack" in lines, lines
    assert "Benalish Hero added to stack" in lines, lines
    hero = lines.index("Benalish Hero added to stack")
    left = next(
        (i for i, line in enumerate(lines) if "attacker" in line or "combat" in line.lower()),
        len(lines),
    )
    assert hero < left, lines


@pytest.mark.cr("505.6", "117.3a")
def test_the_ai_casts_in_the_main_phase_its_held_upkeep_leads_into():
    """A person's table, the AI's turn: the AI holds a graveyard ability
    (Necrosavant, "Activate only during your upkeep"), so its upkeep stops
    with its priority open (``turn_steps._resolve_upkeep_step``); its
    ``ai_step`` there answers and leaves the upkeep, the draw step and into
    the precombat main phase — where it casts its Grizzly Bears, before
    combat. The step's ``_advance_ai_turn`` walked out of the main phase it
    had just begun, so the Bears waited for the second one."""
    created = client.post("/api/sessions", json={"mode": "human_vs_ai", "seed": 5}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 0)
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.graveyard = []
        player.hand = []
        player.library = [_CARDS["Plains"]] * 20
    for _ in range(2):
        game._put_permanent_onto_battlefield(1, Permanent(card=_CARDS["Forest"]), None)
    game.players[1].hand = [_CARDS["Grizzly Bears"]]
    game.players[1].graveyard = [_CARDS["Necrosavant"]]
    start = len(game.log)

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert response.status_code == 200, response.json()
    assert (game.active_player_index, game.current_step) == (1, "upkeep")
    for _ in range(40):
        state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
        if state["current_turn"] != 1:
            break
        action = "pass_priority" if state["priority_player"] == 0 else "ai_step"
        response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": action})
        assert response.status_code == 200, response.json()

    lines = game.log[start:]
    assert "Grizzly Bears added to stack" in lines, lines
    declared = next(i for i, line in enumerate(lines) if "declared" in line and "attacker" in line)
    assert lines.index("Grizzly Bears added to stack") < declared, lines
