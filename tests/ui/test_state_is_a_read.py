"""Guard: `_serialize_state` reads the game; `build_state` is what settles it.

The two used to be one function, and the one they were was the reading one. Ante
transfer (CR 407.2) and an AI's Raging River lock ran inside `_serialize_state`,
so building the JSON payload moved cards between players and locked combat
state — `GET /state` was not a read, and nothing in the name said so.

Splitting them is only worth something if the split is held. The obvious way to
undo it is not deleting `build_state` — it is someone adding "just one more"
settle to the serializer, exactly the way the first two got there. So these
tests drive the serializer against a game that has settling *pending* and assert
it comes back untouched, then assert `build_state` over the same state does the
settling. A test that only checked the payload would pass either way.

The settling itself is not deletable — see `game_flow.settle_before_observation`
for why both are lazy settlements the human's next action is gated on — so
"never mutates on observation" is the wrong invariant and is not what is
asserted here. "The function named for reading does not mutate" is.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from tests.helpers import LEA_PATH
from web.app import app, store
from web.state_view import _serialize_state, build_state

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(LEA_PATH)}


def _raging_river_session_with_ai_defender():
    """A game whose AI defender owes a left/right division, unsettled.

    human_vs_ai so seat 1 is the AI, which is the seat
    `_ai_resolve_raging_river` acts for.
    """
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 7777,
        },
    ).json()
    session = store.get(created["session_id"])
    game = session.game
    game.players[0].battlefield = [
        Permanent(card=_CARDS["Raging River"]),
        Permanent(card=_CARDS["Grizzly Bears"]),
    ]
    game.players[0].battlefield[1].metadata["summoning_sickness_turn"] = -99
    game.players[1].battlefield = [
        Permanent(card=_CARDS["Hill Giant"]),
        Permanent(card=_CARDS["Hurloon Minotaur"]),
    ]
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 1
    game.declare_attackers(0, [1], 1)
    game.resolve_stack()  # the attack trigger resolves; piles seeded, unlocked
    return session, game


def test_serializing_does_not_lock_an_ai_raging_river_division():
    session, game = _raging_river_session_with_ai_defender()
    assert game.combat_left_right_active
    assert not game.combat_left_right_defender_locked, "setup should leave it pending"

    _serialize_state(session, viewer_seat=0)

    assert not game.combat_left_right_defender_locked, (
        "_serialize_state locked the AI's Raging River division — building the "
        "payload must not settle combat state"
    )


def test_build_state_does_lock_it():
    """The other half: the settling still happens, just somewhere it can be seen."""
    session, game = _raging_river_session_with_ai_defender()
    assert not game.combat_left_right_defender_locked

    build_state(session, viewer_seat=0)

    assert game.combat_left_right_defender_locked, (
        "build_state must settle the AI's division — the human's prompt "
        "sequencing is gated on it, so skipping it deadlocks the game"
    )


def _ante_session_decided_only_in_the_web_layer():
    """A game the *web layer* sees as won, with the ante still unsettled.

    Seat 1 is dropped to 0 life without running state-based actions, which is
    the divergence the web layer's own ante call exists for: `_player_has_lost`
    falls back to the 0-or-less-life rule (the Lich-aware reading), while the
    engine's `_maybe_award_ante` only fires from an SBA or a concession and has
    not run. Conceding instead would let the engine settle the ante first and
    leave nothing for this test to observe.
    """
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4242,
            "playing_for_ante": True,
        },
    ).json()
    session = store.get(created["session_id"])
    game = session.game
    assert game.playing_for_ante, "session did not start an ante game"
    assert not game.ante_awarded
    anted = [len(player.ante) for player in game.players]
    assert sum(anted) > 0, f"no cards were anted: {anted}"

    game.players[1].life = 0
    return session, game, anted


def test_serializing_a_decided_game_does_not_move_the_ante():
    """CR 407.2 ante transfer is a real change of ownership, not a rendering step."""
    session, game, anted = _ante_session_decided_only_in_the_web_layer()

    _serialize_state(session, viewer_seat=0)

    assert not game.ante_awarded, (
        "_serialize_state settled the ante — reading the state moved cards "
        "between players"
    )
    assert [len(player.ante) for player in game.players] == anted


def test_build_state_settles_the_ante():
    """The other half, and the reason the call cannot simply be deleted: the
    engine does not make this reading, so nothing else would settle it."""
    session, game, anted = _ante_session_decided_only_in_the_web_layer()

    build_state(session, viewer_seat=0)

    assert game.ante_awarded, (
        "build_state must settle the ante once the web layer's own (Lich-aware) "
        "reading of who has lost decides the game"
    )
    assert len(game.players[0].ante) == sum(anted), "the winner takes the whole ante"
    assert game.players[1].ante == []


def test_status_flips_on_build_not_on_serialize():
    """`session.status` is the same transition seen on the session rather than
    the game, and it moved with the rest of the settle step."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 909,
        },
    ).json()
    session = store.get(created["session_id"])
    session.game.concede(1)

    _serialize_state(session, viewer_seat=0)
    assert session.status != "finished", (
        "_serialize_state flipped the session to finished — a read decided the "
        "game's bookkeeping"
    )

    build_state(session, viewer_seat=0)
    assert session.status == "finished"


def test_the_payload_is_unchanged_by_the_split():
    """Behaviour, not just structure: a settled game serializes identically
    through either entry point, so the split moved *when* rather than *what*."""
    session, _game = _raging_river_session_with_ai_defender()
    settled = build_state(session, viewer_seat=0)
    again = _serialize_state(session, viewer_seat=0)
    assert again == settled, (
        "once nothing is pending, the two must agree — a difference means the "
        "serializer depends on the settle step for something other than state"
    )
