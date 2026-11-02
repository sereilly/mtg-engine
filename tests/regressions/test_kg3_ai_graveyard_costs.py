"""The graveyard's activation door charges a counted sacrifice and a discard.

Coffin Puppets ("Sacrifice two lands: Return this card from your graveyard to
the battlefield. Activate only during your upkeep and only if you control a
Swamp.") and Undead Gladiator ("{1}{B}, Discard a card: Return this card from
your graveyard to your hand. Activate only during your upkeep.") are supported
cards, and ``Game._activate_from_graveyard`` refused both for every seat — a
person's click included: its cost deny list held "only a one-permanent
sacrifice" and "a discard cost". Found by the kg3 round's census of every
graveyard ability in the pool, building the AI's graveyard activations.

The door now charges both the way the battlefield door does: the payer's named
permanents (``cost_permanent_ids``) or hand positions (``cost_hand_index``)
first, the deterministic pick for the rest, a named payment that cannot pay
refused (CR 601.2h), and the whole cost checked before any of it is spent.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack
from web.app import app, store

_CARDS = {card.name: card for card in load_catalog()}
client = TestClient(app)


def _upkeep(graveyard, *, lands=(), hand=(), step="upkeep"):
    game = Game(players=[
        PlayerState(
            name="P0", graveyard=[_CARDS[graveyard]],
            hand=[_CARDS[name] for name in hand], library=[_CARDS["Swamp"]] * 5,
        ),
        PlayerState(name="P1", library=[_CARDS["Swamp"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    for name in lands:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        _nosick(permanent)
    game.current_turn_phase = "beginning" if step == "upkeep" else step
    game.current_step = step
    return game


def _land(game, name):
    return next(p for p in game.controlled_by(0) if p.card.name == name)


def _board(game):
    return sorted(p.card.name for p in game.controlled_by(0))


def test_coffin_puppets_sacrifices_the_two_lands_named():
    game = _upkeep("Coffin Puppets", lands=("Swamp", "Forest", "Plains"))
    named = [_land(game, "Forest").permanent_id, _land(game, "Plains").permanent_id]

    result = game.activate_from_graveyard(0, "Coffin Puppets", cost_permanent_ids=named)

    assert result.supported, result.details
    # Paid as the ability is activated; the card leaves the graveyard only
    # when the ability resolves (CR 608.2).
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Coffin Puppets", "Forest", "Plains",
    ]
    resolve_stack(game)
    assert _board(game) == ["Coffin Puppets", "Swamp"]
    assert sorted(card.name for card in game.players[0].graveyard) == ["Forest", "Plains"]


def test_coffin_puppets_named_nothing_pays_with_the_default_pick():
    game = _upkeep("Coffin Puppets", lands=("Swamp", "Swamp", "Swamp"))

    assert game.activate_from_graveyard(0, "Coffin Puppets").supported
    resolve_stack(game)

    assert _board(game) == ["Coffin Puppets", "Swamp"]
    assert [card.name for card in game.players[0].graveyard] == ["Swamp", "Swamp"]


def test_one_land_is_not_two_and_nothing_is_spent():
    game = _upkeep("Coffin Puppets", lands=("Swamp",))

    result = game.activate_from_graveyard(0, "Coffin Puppets")

    assert not result.supported
    assert "not enough lands" in result.details
    assert _board(game) == ["Swamp"]
    assert [card.name for card in game.players[0].graveyard] == ["Coffin Puppets"]


def test_a_named_permanent_that_cannot_pay_is_refused_not_substituted():
    """CR 601.2h: a land the payer named that is not the payer's to give is
    an announcement that cannot be paid."""
    game = _upkeep("Coffin Puppets", lands=("Swamp", "Swamp", "Forest"))
    stranger = Permanent(card=_CARDS["Forest"])
    game._put_permanent_onto_battlefield(1, stranger, None)

    result = game.activate_from_graveyard(
        0, "Coffin Puppets",
        cost_permanent_ids=[stranger.permanent_id, _land(game, "Forest").permanent_id],
    )

    assert not result.supported
    assert _board(game) == ["Forest", "Swamp", "Swamp"]


def test_the_printed_restrictions_still_bind():
    """"Activate only during your upkeep and only if you control a Swamp":
    both conjuncts, before anything is paid."""
    no_swamp = _upkeep("Coffin Puppets", lands=("Forest", "Forest"))
    main_phase = _upkeep("Coffin Puppets", lands=("Swamp", "Swamp"), step="precombat_main")

    for game in (no_swamp, main_phase):
        assert not game.activate_from_graveyard(0, "Coffin Puppets").supported
        assert len(list(game.controlled_by(0))) == 2


def test_undead_gladiator_discards_the_card_named():
    game = _upkeep("Undead Gladiator", hand=("Hill Giant", "Island", "Shock"))

    result = game.activate_from_graveyard(0, "Undead Gladiator", cost_hand_index=1)

    assert result.supported, result.details
    assert "P0 discarded Island to activate Undead Gladiator" in game.log
    resolve_stack(game)
    assert sorted(card.name for card in game.players[0].hand) == [
        "Hill Giant", "Shock", "Undead Gladiator",
    ]
    assert [card.name for card in game.players[0].graveyard] == ["Island"]


def test_undead_gladiator_named_nothing_discards_the_first_card():
    game = _upkeep("Undead Gladiator", hand=("Hill Giant", "Island"))

    assert game.activate_from_graveyard(0, "Undead Gladiator").supported
    resolve_stack(game)

    assert [card.name for card in game.players[0].graveyard] == ["Hill Giant"]


def test_undead_gladiator_with_an_empty_hand_is_refused():
    game = _upkeep("Undead Gladiator")

    result = game.activate_from_graveyard(0, "Undead Gladiator")

    assert not result.supported and "not enough cards in hand" in result.details
    assert [card.name for card in game.players[0].graveyard] == ["Undead Gladiator"]


def test_the_route_forwards_the_discard_a_person_names():
    """``activate_graveyard`` carries ``cost_hand_index`` to the door, as
    every activation's discard is named."""
    game = _upkeep("Undead Gladiator", hand=("Hill Giant", "Island"))
    game.interactive_seats = {0, 1}
    game.start_priority_window(0)
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "H", "guest_name": "G",
        "host_colors": 2, "guest_colors": 2, "seed": 2600,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "G"})
    session = store.get(sid)
    session.pregame_phase = None
    session.current_turn = 0
    session.joined_seats = {0, 1}
    session.game = game

    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate_graveyard", "graveyard_index": 0,
        "ability_index": 0, "cost_hand_index": 1,
    })

    assert answered.status_code == 200, answered.text
    assert "P0 discarded Island to activate Undead Gladiator" in game.log
