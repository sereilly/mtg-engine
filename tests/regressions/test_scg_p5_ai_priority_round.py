"""An AI seat's object on the stack gives the person at the table priority
before it resolves (SCG Phase 5, W1).

The verification agent watched Pemmin's Aura's activations, Gilded Light's
and Eternal Dragon's cycling resolve on the AI's turn with no pass by the
person, and in smoke game 1's turn 11 the AI cycle Shoreline Ranger in its
declare blockers step **before the person had declared a blocker** — a moment
nobody holds priority (CR 117.3a, 509.1) — the ability resolving after the
blocks. CR 117.3c gives the seat that acted priority again; CR 117.4 resolves
the object only once every player has passed in succession.

``web/game_flow._ai_step``'s cast went through ``queue_from_hand`` and the
priority exchange; its four activation doors called the engine and settled at
once (or left the object for the step's window to drain), and it asked only
whether another seat held priority, not whether the AI did. The defender's
combat trick in the declare blockers step was a settling ``cast_from_hand``
by a seat without priority, and the AI's attack and block triggers were
drained by the step's window.

**The census is every web site where an AI seat puts an object on the stack**,
driven through the API as the browser drives a ``human_vs_ai`` game: the
person passes when the served state gives them priority, declares no blocks
when the blocks are theirs to declare, and otherwise asks for an ``ai_step``.
Each row asks one question: was the AI's object on the stack in a state that
gave the person priority, before it resolved? On the base, six of the eleven
rows were red (the four activation doors, the face-up trigger, the attack
trigger); the defender's trick and the AI's block trigger were red too.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_catalog
from engine.face_down import face_down_card
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
    session.game.enforce_mana_costs = True
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 12
    return sid, session


def _put(game, seat: int, names, *, face_down: bool = False) -> list:
    placed = []
    for name in names:
        card = _CARDS[name]
        permanent = Permanent(card=face_down_card(card) if face_down else card)
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid: str, **body) -> dict:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})
    assert response.status_code == 200, response.json()
    return response.json()


def _drive(sid: str, label: str, *, until, limit: int = 80) -> dict:
    """Play as the browser plays until *until(game)*; report whether the
    object named *label* was ever on the stack in a state that gave seat 0
    (the person) priority, and every state it was seen on the stack in."""
    session = store.get(sid)
    game = session.game
    seen = {"with_priority": False, "states": []}
    for _ in range(limit):
        if until(game):
            break
        state = _state(sid)
        labels = [item["label"] for item in state["stack"]]
        if any(label in entry for entry in labels):
            seen["states"].append((state["current_step"], state["priority_player"], labels))
            if state["priority_player"] == 0:
                seen["with_priority"] = True
        combat = state.get("combat") or {}
        if state["priority_player"] == 0:
            _act(sid, action="pass_priority")
        elif (
            state["current_step"] == "declare_blockers"
            and combat.get("attackers")
            and not combat.get("blockers_locked")
            and combat.get("defending_player_index") == 0
        ):
            _act(sid, action="declare_blockers", blocker_pairs_by_id=[])
        elif state["current_turn"] == 1:
            _act(sid, action="ai_step")
        elif state["current_step"] == "declare_attackers" and not combat.get("attackers_locked"):
            _act(sid, action="declare_attackers", attacker_ids=[], target_seat=1)
        elif state.get("cleanup_discard"):
            _act(sid, action="cleanup_select", hand_index=0)
        else:
            _act(sid, action="next_phase")
    else:
        raise AssertionError(f"never reached the end; log: {game.log[-15:]}")
    return seen


def _assert_round(seen: dict, game) -> None:
    assert seen["states"], f"the object never showed on the stack; log: {game.log[-15:]}"
    assert seen["with_priority"], (
        f"the AI's object was never on the stack with the person holding priority: "
        f"{seen['states']}; log: {game.log[-15:]}"
    )


# ---------------------------------------------------------------------------
# The AI's own turn: each door of `_ai_step`.
# ---------------------------------------------------------------------------


def test_an_ability_of_the_ais_permanent_waits_for_the_persons_pass():
    """Prodigal Sorcerer's ping on the AI's main phase (the battlefield door)."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 1, ["Prodigal Sorcerer"])
    seen = _drive(sid, "Prodigal Sorcerer", until=lambda g: g.players[0].life < 20)
    _assert_round(seen, game)


def test_a_cycled_card_waits_for_the_persons_pass():
    """Shoreline Ranger islandcycled over two Islands (the hand door)."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 1, ["Island", "Island"])
    game.players[1].hand = [_CARDS["Shoreline Ranger"]]
    game.players[1].library = [_CARDS["Island"]] * 6
    seen = _drive(
        sid, "Shoreline Ranger",
        until=lambda g: any(c.name == "Shoreline Ranger" for c in g.players[1].graveyard)
        and not g.stack,
    )
    _assert_round(seen, game)


def test_a_graveyard_ability_waits_for_the_persons_pass():
    """Gangrenous Goliath returned by tapping three Clerics (the graveyard door)."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 1, ["Daru Healer"] * 3)
    game.players[1].graveyard = [_CARDS["Gangrenous Goliath"]]
    seen = _drive(
        sid, "Gangrenous Goliath",
        until=lambda g: any(c.name == "Gangrenous Goliath" for c in g.players[1].hand),
    )
    _assert_round(seen, game)


def test_an_ability_of_the_persons_permanent_the_ai_activates_waits_for_the_pass():
    """The person's Volrath's Dungeon, destroyed by the AI for 5 life on the
    AI's turn ("Any player may activate this ability but only during their
    turn", the foreign door)."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 0, ["Volrath's Dungeon"])
    seen = _drive(
        sid, "Volrath's Dungeon",
        until=lambda g: any(c.name == "Volrath's Dungeon" for c in g.players[0].graveyard),
    )
    _assert_round(seen, game)


def test_a_face_up_trigger_waits_for_the_persons_pass():
    """Skinthinner turned face up (a special action, CR 116.2b) over five
    Swamps: its "destroy target nonblack creature" is a trigger, and the
    person is asked over it."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 1, ["Swamp"] * 5)
    _put(game, 1, ["Skinthinner"], face_down=True)
    _put(game, 0, ["Grizzly Bears"])
    seen = _drive(
        sid, "Skinthinner",
        until=lambda g: any(c.name == "Grizzly Bears" for c in g.players[0].graveyard),
    )
    _assert_round(seen, game)


def test_an_attack_trigger_of_the_ai_waits_for_the_persons_pass():
    """Charging Paladin attacks: "it gets +0/+3" is a trigger of the AI's own
    declaration (CR 508.2 gives the active player priority after it)."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 1, ["Charging Paladin"])
    seen = _drive(sid, "Charging Paladin", until=lambda g: g.players[0].life < 20)
    _assert_round(seen, game)


def test_nothing_is_activated_before_the_person_declares_blockers():
    """Smoke game 1, turn 11: the AI attacks into a person who can block and
    holds Shoreline Ranger over two untapped Islands. While the blocks are the
    person's to declare, nobody holds priority (CR 117.3a, 509.1): an
    ``ai_step`` — the browser sends one whenever the AI's turn shows nobody
    holding priority — puts nothing on the stack."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 1, ["Grizzly Bears", "Island", "Island"])
    _put(game, 0, ["Grizzly Bears"])
    game.players[1].library = [_CARDS["Island"]] * 6
    for _ in range(40):
        state = _state(sid)
        combat = state.get("combat") or {}
        if (
            state["current_step"] == "declare_blockers"
            and combat.get("attackers")
            and not combat.get("blockers_locked")
        ):
            break
        if state["priority_player"] == 0:
            _act(sid, action="pass_priority")
        else:
            _act(sid, action="ai_step")
    else:
        pytest.skip("the AI did not attack")
    assert state["priority_player"] is None
    # The Ranger reaches the AI's hand only now, so nothing the AI did in an
    # earlier step can have spent it.
    game.players[1].hand = [_CARDS["Shoreline Ranger"]]
    mark = len(game.log)
    for _ in range(3):
        _act(sid, action="ai_step")
        assert game.stack == [], [item.card.name for item in game.stack]
    assert [card.name for card in game.players[1].hand] == ["Shoreline Ranger"], game.log[mark:]
    assert not any("added to stack" in line for line in game.log[mark:]), game.log[mark:]


# ---------------------------------------------------------------------------
# The AI's answer to priority, and the person's turn.
# ---------------------------------------------------------------------------


def test_the_ais_upkeep_graveyard_ability_waits_for_the_persons_pass():
    """Hammer of Bogardan in the AI's graveyard, five Mountains: its upkeep
    window (`_ai_answer_priority`)."""
    sid, session = _session(first=0)
    game = session.game
    _put(game, 1, ["Mountain"] * 5)
    game.players[1].graveyard = [_CARDS["Hammer of Bogardan"]]
    seen = _drive(
        sid, "Hammer of Bogardan",
        until=lambda g: any(c.name == "Hammer of Bogardan" for c in g.players[1].hand),
    )
    _assert_round(seen, game)


def test_the_ais_response_to_a_spell_waits_for_the_persons_pass():
    """The person bolts the AI's Grizzly Bears; the AI answers with Giant
    Growth (`_ai_respond_to_priority`)."""
    sid, session = _session(first=0)
    game = session.game
    (bears,) = _put(game, 1, ["Grizzly Bears"])
    _put(game, 1, ["Forest"])
    _put(game, 0, ["Mountain"])
    game.players[1].hand = [_CARDS["Giant Growth"]]
    game.players[0].hand = [_CARDS["Lightning Bolt"]]
    _act(
        sid, action="cast", card_name="Lightning Bolt", target_player_index=1,
        target_permanent_id=bears.permanent_id, auto_tap=True,
    )
    seen = _drive(
        sid, "Giant Growth",
        until=lambda g: any(c.name == "Giant Growth" for c in g.players[1].graveyard) and not g.stack,
    )
    _assert_round(seen, game)


def test_the_defenders_trick_waits_for_the_attackers_priority():
    """The person attacks with Grizzly Bears; the AI blocks with its own and
    holds Giant Growth over a Forest. CR 509.2: the active player — the
    person — receives priority after the blocks; the trick is cast when the
    AI is handed priority, and the person is asked over it."""
    sid, session = _session(first=0)
    game = session.game
    (attacker,) = _put(game, 0, ["Grizzly Bears"])
    _put(game, 1, ["Grizzly Bears", "Forest"])
    game.players[1].hand = [_CARDS["Giant Growth"]]
    state = _state(sid)
    for _ in range(10):
        if state["current_step"] == "declare_attackers":
            break
        _act(sid, action="next_phase")
        state = _state(sid)
    _act(sid, action="declare_attackers", attacker_ids=[attacker.permanent_id], target_seat=1)
    seen = _drive(
        sid, "Giant Growth",
        until=lambda g: any(c.name == "Giant Growth" for c in g.players[1].graveyard) and not g.stack
        or g.current_turn_phase == "postcombat_main",
    )
    if not seen["states"] and all(c.name != "Giant Growth" for c in game.players[1].graveyard):
        pytest.skip("the AI chose not to cast its trick")
    _assert_round(seen, game)


def test_the_ais_block_trigger_waits_for_the_attackers_priority():
    """The person attacks with Grizzly Bears into the AI's Root Spider
    ("Whenever this creature blocks, it gets +1/+0 and gains first strike").
    The AI blocks; its trigger is on the stack when the person — the active
    player, CR 509.2 — receives priority, and resolves only after the pass."""
    sid, session = _session(first=0)
    game = session.game
    (attacker,) = _put(game, 0, ["Grizzly Bears"])
    _put(game, 1, ["Root Spider"])
    state = _state(sid)
    for _ in range(10):
        if state["current_step"] == "declare_attackers":
            break
        _act(sid, action="next_phase")
        state = _state(sid)
    _act(sid, action="declare_attackers", attacker_ids=[attacker.permanent_id], target_seat=1)
    seen = _drive(
        sid, "Root Spider",
        until=lambda g: g.current_turn_phase == "postcombat_main" or g.current_step == "end",
    )
    if not seen["states"] and not any("declared 1 blocker" in line for line in game.log):
        pytest.skip("the AI did not block")
    _assert_round(seen, game)


def test_the_active_ais_trick_after_the_persons_blocks_waits_for_the_pass():
    """The AI attacks with Grizzly Bears (the Debug Menu's attack-everything,
    so the attack is certain) into the person's Grizzly Bears, holding Giant
    Growth over a Forest. The person blocks; CR 509.2 gives the AI — the active
    player — priority, and it answers as every AI seat handed priority does
    (`ai_priority.act_at_priority`): the trick goes on the stack and the person
    is asked over it. The AI step asked the main phase's choosers here, which
    cast nothing in combat."""
    sid, session = _session(first=1)
    game = session.game
    session.force_ai_attack_all = True
    (attacker,) = _put(game, 1, ["Grizzly Bears"])
    _put(game, 1, ["Forest"])
    (blocker,) = _put(game, 0, ["Grizzly Bears"])
    blocked = False
    seen = {"with_priority": False, "states": []}
    for _ in range(60):
        state = _state(sid)
        if state["current_turn"] == 0 or state["status"] == "finished":
            break
        labels = [item["label"] for item in state["stack"]]
        if any("Giant Growth" in entry for entry in labels):
            seen["states"].append((state["current_step"], state["priority_player"], labels))
            seen["with_priority"] |= state["priority_player"] == 0
        combat = state.get("combat") or {}
        if (
            state["current_step"] == "declare_blockers" and not blocked
            and combat.get("attackers") and not combat.get("blockers_locked")
        ):
            # The trick reaches the AI's hand only now, so its main phase
            # cannot have spent it.
            game.players[1].hand = [_CARDS["Giant Growth"]]
            _act(sid, action="declare_blockers", target_seat=0, blocker_pairs_by_id={
                str(blocker.permanent_id): [attacker.permanent_id],
            })
            blocked = True
        elif state["priority_player"] == 0:
            _act(sid, action="pass_priority")
        else:
            _act(sid, action="ai_step")
    assert blocked, game.log[-15:]
    assert any(card.name == "Giant Growth" for card in game.players[1].graveyard), game.log[-15:]
    _assert_round(seen, game)
    # In the fight it is for, not afterwards in the second main phase.
    assert seen["states"][0][0] == "declare_blockers", seen["states"]
