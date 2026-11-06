"""An AI seat regenerates its blocked attacker with the mana open (SCG Phase 5,
smoke game 2).

Seen: the AI's Krosan Warchief ("{1}{G}: Regenerate target Beast"; it is a
Beast) attacked, the person blocked it with a creature that killed it, and the
AI had {1}{G} open and did nothing.

The engine's own answer was right: after the blocks the active player gets
priority (CR 509.2), and ``ai_priority.act_at_priority`` — the simulator's
answer there — rehearses the shield and takes it. The web AI seat was not asked
that: in each step of its own turn it held priority in, the web's AI step
asked ``ai_abilities.choose_activation_action``, the main-phase chooser, and
that chooser passed over every tapped permanent — an attacker is tapped.
Outside its own main phase the web's AI step now answers through
``act_at_priority`` too (``web/game_flow``, SCG Phase 5 W1), and the main-phase
chooser is asked only at sorcery speed.
"""
from __future__ import annotations

from engine.ai_priority import act_at_priority
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, client, declare_attack, resolve_stack


def _table(cards, own, other=()) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat, names in ((0, own), (1, other)):
        for name in names:
            game.players[seat].battlefield.append(_nosick(Permanent(card=cards[name])))
        game.players[seat].library = [cards["Forest"]] * 10
    game._recompute_continuous_effects()
    return game


def _cards(set_pool) -> dict:
    cards = dict(set_pool("LEA"))
    cards["Krosan Warchief"] = set_pool("SCG")["Krosan Warchief"]
    return cards


def _blocked_warchief(cards) -> Game:
    """The AI's Krosan Warchief attacking, blocked by Hill Giant (3/3), Forest
    and Mountain untapped: the declare-blockers step, damage still to come."""
    game = _table(cards, ["Krosan Warchief", "Forest", "Mountain"], ["Hill Giant"])
    game.start_turn(0)
    for _ in range(6):
        if game.current_turn_phase == "precombat_main":
            break
        game._close_current_priority_step()
    declare_attack(game, 0, blocks={0: 0})
    return game


def test_the_priority_answer_after_the_blocks_regenerates_the_warchief(set_pool):
    """The answer the web AI seat and the simulator both give in the
    declare-blockers step (``act_at_priority``): the shield, aimed at the
    Warchief; then the damage, and the Warchief is still there."""
    game = _blocked_warchief(_cards(set_pool))
    act = act_at_priority(game, 0)
    assert act is not None and act.kind == "activate" and act.supported, act
    assert act.action.permanent_name == "Krosan Warchief"
    resolve_stack(game)
    for _ in range(3):
        if game.current_step != "declare_blockers":
            break
        game.advance_combat_phase()  # into the combat damage step, which deals it
    assert any(p.card.name == "Krosan Warchief" for p in game.players[0].battlefield), game.log[-8:]
    assert "Krosan Warchief regenerated" in game.log


# --- the web AI seat, driven as the browser drives it -------------------------

_LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid: str, **body) -> int:
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body}).status_code


def _put(game, cards, seat: int, names) -> list:
    placed = []
    for name in names:
        permanent = Permanent(card=cards[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def test_the_web_ai_regenerates_its_attacker_after_a_persons_block(set_pool):
    """Human vs AI through the API: the AI's Krosan Warchief attacks (the
    Debug Menu's attack-with-everything, so the attack is certain), the person
    blocks with Hill Giant, and the client drives the rest of the AI's turn
    with ``ai_step`` / ``pass_priority``. The Warchief regenerates and lives."""
    from web.app import store

    cards = _cards(set_pool)
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_deck_cards": _LANDS, "guest_deck_cards": _LANDS, "seed": 11,
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    session.force_ai_attack_all = True
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] == 0:
            break
        assert _act(sid, action="pass_priority" if state["priority_player"] == 0 else "ai_step") == 200
    human, ai = game.players
    human.battlefield, ai.battlefield, human.hand, ai.hand = [], [], [], []
    (giant,) = _put(game, cards, 0, ["Hill Giant"])
    warchief, *_ = _put(game, cards, 1, ["Krosan Warchief", "Forest", "Mountain"])
    human.library = [cards["Island"]] * 10
    ai.library = [cards["Island"]] * 10

    for _ in range(60):
        state = _state(sid)
        if state["current_turn"] != 0:
            break
        if state["current_step"] == "declare_attackers" and state["priority_player"] is None:
            code = _act(sid, action="declare_attackers", attacker_ids=[], target_seat=1)
        else:
            code = _act(sid, action="pass_priority")
            if code != 200:
                code = _act(sid, action="next_phase")
        assert code == 200

    blocked = False
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] == 0 or state["status"] == "finished":
            break
        if state["current_step"] == "declare_blockers" and not blocked and game.combat_attackers:
            assert client.post(f"/api/sessions/{sid}/action", json={
                "seat": 0, "action": "declare_blockers", "target_seat": 0,
                "blocker_pairs_by_id": {str(giant.permanent_id): [warchief.permanent_id]},
            }).status_code == 200
            blocked = True
            continue
        assert _act(sid, action="pass_priority" if state["priority_player"] == 0 else "ai_step") == 200

    assert blocked, game.log[-20:]
    assert "Krosan Warchief regenerated" in game.log, game.log[-20:]
    assert any(p is warchief for p in game.players[1].battlefield)
