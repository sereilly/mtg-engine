"""The castable highlight asks a card's own "Cast this spell only …" clause
through the table the cast path refuses with (CR 601.3).

``web/state_view._card_castable_now`` spelled three of
``cast_restrictions.CAST_RESTRICTIONS``' phrases as literals with step tests of
its own and asked nothing else, so every other row glowed a card whose click
the cast path then refused. Measured backwards before the fix, over the
shipped pool on an ordinary own-main-phase board: 34 cards print a clause about
their own cast, 29 of them are refused by it there, and **15 glowed** —
Siren's Call, Reset, Teleport, Festival, Melee, Blizzard, Suffocation,
Aleatory, Lure of Prey, Skyshroud Condor, Necrologia, Angelic Favor, Chaotic
Strike, Spinal Embrace and Surprise Deployment. Found by SCG W1G3 beside Rock
Jockey's "You can't cast Rock Jockey if …", which is asked by all three
readers as a ``cast_prohibitions`` row.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_restrictions import cast_timing_claims_line, check_cast_timing
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack
from web.app import app, store
from web.state_view import _compute_playable_hand_indices

client = TestClient(app)

_POOL: dict = {}
for _card in load_cards(manifest_set_paths()):
    _POOL.setdefault(_card.name, _card)


def _session():
    sid = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4243,
    }).json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return store.get(sid)


def _board(session, card):
    """Seat 0's own precombat main phase, mana for anything, a creature and an
    artifact across the table to aim at, *card* alone in hand."""
    library = [_POOL["Grizzly Bears"]] * 10
    game = Game(players=[
        PlayerState(name="A", library=list(library)),
        PlayerState(name="B", library=list(library)),
    ])
    game.enforce_mana_costs = True
    game.turn = 3
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.players[0].battlefield = [Permanent(card=_POOL["Forest"]) for _ in range(2)]
    game.players[1].battlefield = [
        Permanent(card=_POOL["Grizzly Bears"]), Permanent(card=_POOL["Ornithopter"]),
    ]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    game.players[0].hand = [card]
    game.players[0].mana_pool.update({"W": 9, "U": 9, "B": 9, "R": 9, "G": 9})
    game.start_priority_window(0)
    session.game = game
    session.current_turn = 0
    return game


def test_no_card_glows_that_its_own_cast_clause_refuses():
    session = _session()
    candidates = [
        card for card in _POOL.values()
        if card.primary_type != "land"
        and any(
            cast_timing_claims_line(line, card.name)
            for line in (card.oracle_text or "").splitlines()
        )
        and compile_card_oracle(card).supported
    ]
    refused = 0
    glowing = []
    for card in candidates:
        game = _board(session, card)
        denial = check_cast_timing(game, 0, (card.oracle_text or "").lower())
        if denial is None:
            continue
        refused += 1
        if 0 in _compute_playable_hand_indices(session, 0):
            glowing.append(f"{card.name}: {denial}")
        # …and the click the glow would invite is refused in those words.
        result = game.cast_from_hand(0, card.name)
        assert not result.supported and result.details == denial, card.name
    assert not glowing, glowing
    # The floors, measured: 34 candidates, 29 refused on this board.
    assert len(candidates) >= 30, len(candidates)
    assert refused >= 25, refused


def test_a_clause_that_holds_still_glows():
    """The other direction, on the card that printed the first such clause on a
    creature: Skyshroud Condor ("Cast this spell only if you've cast another
    spell this turn") is dark on an empty turn and glows after a spell."""
    session = _session()
    condor = _POOL["Skyshroud Condor"]
    game = _board(session, condor)
    assert 0 not in _compute_playable_hand_indices(session, 0)
    game.players[0].hand.insert(0, _POOL["Llanowar Elves"])
    assert game.cast_from_hand(0, "Llanowar Elves").supported
    resolve_stack(game)
    game.start_priority_window(0)
    hand = game.players[0].hand
    assert [card.name for card in hand] == ["Skyshroud Condor"]
    assert 0 in _compute_playable_hand_indices(session, 0)
