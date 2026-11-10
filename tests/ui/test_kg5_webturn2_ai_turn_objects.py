"""On an AI's turn at a person's table, every object on the stack goes round
the table before it resolves (CR 117.4) — whichever step it is in.

The web's AI-turn walk (``game_flow._advance_ai_turn``) left each step
through the engine's window, which resolved what the step had put on the
stack with the person never asked; only the AI's declarations' triggers went
round (``_ai_declares_attackers``, the blocks' round). Measured on the round's
base: the AI's upkeep (Copper Tablet), draw step (Mana Vault), beginning of
combat (Battering Ram), combat damage (Hypnotic Specter), end of combat (Time
Elemental) and end step (Ball Lightning) objects all resolved unasked; and on
the person's own turn the combat damage step's (Hypnotic Specter) did too —
the engine's damage step drained its window wherever no rail flag held it.

Now the walk stops at a step it arrives at with objects on the stack and the
AI answers and passes (``_ai_answers_over_the_stack``); the AI's upkeep and
draw step at a person's table run with its priority open and stop for their
objects (``turn_steps._stops_for_the_steps_objects``); and the damage step
stays, with the active player's priority, when the damage set something off
at a table with a person (``CombatPhaseMixin._leave_combat_step``).
"""

from __future__ import annotations

import unittest.mock as mock

import pytest

from engine.ai_rehearsal import rehearsing
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent
from tests.helpers import client, seat_plays_first

_CARDS = {card.name: card for card in load_catalog()}

_EVERY_STEP = [
    "upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers",
    "declare_blockers", "combat_damage", "end_of_combat", "postcombat_main", "end",
]


def _put(game, seat: int, name: str, *, tapped: bool = False) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    return permanent


def _act(sid: str, seat: int, **body) -> dict:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": seat, **body})
    assert response.status_code == 200, (body, response.json())
    return response.json()


def _table(first: int):
    created = client.post("/api/sessions", json={"mode": "human_vs_ai", "seed": 5}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, first)
    for player in session.game.players:
        player.battlefield = []
        player.graveyard = []
        player.hand = []
        player.library = [_CARDS["Plains"]] * 20
    return sid, session


class _Resolutions:
    """Every object resolved off *game*'s stack while *seat* is the active
    player, with its step — and every object on the stack each time the
    person passes priority (the client's ``pass_priority``)."""

    def __init__(self, monkeypatch, game, seat: int):
        self.resolved: list[tuple] = []
        self.passed_over: list = []
        real = Game.resolve_top_of_stack

        def watching(game_, pause_for_choices=False):
            if game_ is game and game_.stack and not rehearsing() and game_.active_player_index == seat:
                top = game_.stack[-1]
                self.resolved.append((top, game_.current_step, top.card.name))
            return real(game_, pause_for_choices=pause_for_choices)

        monkeypatch.setattr(Game, "resolve_top_of_stack", watching)

    def unasked(self) -> list[tuple]:
        return [
            (step, name) for item, step, name in self.resolved
            if not any(item is other for other in self.passed_over)
        ]

    def steps(self) -> set[str]:
        return {step for _item, step, _name in self.resolved}


@pytest.mark.cr("117.4", "503.1", "504.2", "507.2", "510.3", "511.2", "513.1")
@pytest.mark.parametrize("stops", [[], _EVERY_STEP], ids=["unflagged", "every step flagged"])
def test_every_object_of_the_ais_turn_goes_round_before_it_resolves(monkeypatch, stops):
    """The AI's turn, the person holding Lightning Bolt and a Mountain and
    passing whenever handed priority. The AI's board puts an object on the
    stack in each step: Copper Tablet (upkeep), a tapped Mana Vault (draw),
    Battering Ram (beginning of combat), Time Elemental attacking (its
    attack trigger, and its end-of-combat sacrifice), Hypnotic Specter
    (combat damage), Dragon Whelp pumped four times (its end-step sacrifice)
    and Ball Lightning (end step). Each resolved only after the person had
    passed priority with it on the stack."""
    sid, session = _table(0)
    game = session.game
    _put(game, 0, "Mountain")
    game.players[0].hand = [_CARDS["Lightning Bolt"], _CARDS["Plains"], _CARDS["Plains"]]
    for name in ("Copper Tablet", "Battering Ram", "Hypnotic Specter", "Time Elemental"):
        _put(game, 1, name)
    _put(game, 1, "Mana Vault", tapped=True)
    session.force_ai_attack_all = True
    watch = _Resolutions(monkeypatch, game, seat=1)

    _act(sid, 0, action="end_turn", stop_steps=stops)
    # Ball Lightning and the Whelp arrive once the person's own end step has
    # passed (Ball Lightning's trigger fires at every end step).
    _put(game, 1, "Ball Lightning")
    whelp = _put(game, 1, "Dragon Whelp")
    pumped = False
    for _ in range(160):
        state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
        if state["current_turn"] != 1:
            break
        if not pumped and game.current_step == "precombat_main" and not game.stack:
            # The AI's own four activations, made for it through the engine
            # (its chooser has no use for them): the delayed sacrifice.
            # The pumps settle as they are made — the test's own hand, not
            # the AI's turn — so they are not counted.
            game.players[1].mana_pool["R"] = 4
            before = len(watch.resolved)
            for _ in range(4):
                assert game.activate_permanent_ability(1, "Dragon Whelp").supported
            del watch.resolved[before:]
            pumped = True
        combat = state.get("combat") or {}
        if state["current_step"] == "declare_blockers" and not combat.get("blockers_locked"):
            _act(sid, 0, action="declare_blockers", blocker_pairs_by_id={}, stop_steps=stops)
        elif state["priority_player"] == 0:
            watch.passed_over.extend(game.stack)
            _act(sid, 0, action="pass_priority", stop_steps=stops)
        else:
            _act(sid, 0, action="ai_step", stop_steps=stops)
    else:
        raise AssertionError(f"the AI's turn never ended: {game.log[-15:]}")

    assert pumped and not game.is_on_battlefield(whelp), game.log[-20:]
    names = {(step, name) for _item, step, name in watch.resolved}
    assert {
        ("upkeep", "Copper Tablet"), ("draw", "Mana Vault"),
        ("beginning_of_combat", "Battering Ram"), ("declare_attackers", "Time Elemental"),
        ("combat_damage", "Hypnotic Specter"), ("end_of_combat", "Time Elemental"),
        ("end", "Ball Lightning"), ("end", "Dragon Whelp"),
    } <= names, sorted(names)
    assert not watch.unasked(), watch.unasked()


@pytest.mark.cr("117.4", "510.3")
def test_the_persons_own_combat_damage_trigger_goes_round():
    """The person's own turn: their Hypnotic Specter deals combat damage to
    the AI, whose discard trigger the person — the active player — receives
    priority over (CR 510.3) before it resolves; their pass hands it to the
    AI. The damage step drained it in the engine's window."""
    sid, session = _table(0)
    game = session.game
    specter = _put(game, 0, "Hypnotic Specter")
    game.players[1].hand = [_CARDS["Plains"], _CARDS["Plains"]]
    held_over: list = []
    resolved: list = []
    real = Game.resolve_top_of_stack

    def watching(game_, pause_for_choices=False):
        if game_ is game and game_.stack and not rehearsing():
            resolved.append((game_.stack[-1], game_.current_step))
        return real(game_, pause_for_choices=pause_for_choices)

    with mock.patch.object(Game, "resolve_top_of_stack", watching):
        for _ in range(40):
            state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
            combat = state.get("combat") or {}
            if state["current_step"] == "end_of_combat" or state["current_turn"] != 0:
                break
            if state["current_step"] == "declare_attackers" and not combat.get("attackers_locked"):
                _act(sid, 0, action="declare_attackers",
                     attacker_ids=[specter.permanent_id], target_seat=1)
            elif state["priority_player"] == 0:
                if state["current_step"] == "combat_damage":
                    held_over.extend(game.stack)
                _act(sid, 0, action="pass_priority")
            else:
                _act(sid, 0, action="next_phase")
    in_damage = [item for item, step in resolved if step == "combat_damage"]
    assert len(in_damage) == 1 and in_damage[0].card.name == "Hypnotic Specter", resolved
    assert any(item is in_damage[0] for item in held_over), game.log[-12:]
    assert len(game.players[1].hand) == 1
