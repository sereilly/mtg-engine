"""Which cards pay "exile X cards from your graveyard" is the caster's choice.

    "As an additional cost to cast this spell, exile X creature cards from
    your graveyard."  (Haunting Misery, Weatherlight)
    "As an additional cost to cast this spell, exile X cards from your
    graveyard."  (Skeletal Scrying, Odyssey)

CR 601.2b: the caster announces how a cost is paid, and which cards leave a
graveyard is part of that — it decides what threshold, flashback and a
reanimation spell have left. The charger took the top X of the pile for every
seat (``candidates[-1]``): there was no parameter to say otherwise.

The cast path takes ``cost_graveyard_indices`` now — the channel
``activate_permanent_ability`` has taken the same choice on since Psychatog —
and holds a named set to the cost (CR 601.2h: "Partial payments are not
allowed"): every slot a card the cost could take, none twice, exactly X of
them, or the spell is not cast. A cast naming no set takes the top of the pile
as before, which is the headless convention.

A graveyard holds one immutable ``CardDefinition`` per copy, so two copies of a
card there are the same Python object: cards are named by slot and exactly one
leaves per slot.

The second half is the spell cast **from** that graveyard (CR 601.2a: it is on
the stack before a cost is paid). The CR 601.2h gate counted the spell itself
among the cards it could exile, so Skeletal Scrying cast out of a graveyard of
four for X = 4 was admitted and then found three.

The population is the whole pool's — both cards — and the last test says so.
"""
from __future__ import annotations

from functools import lru_cache

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import additional_costs
from engine.cast_permissions import grant_permission
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from web.app import app, store

client = TestClient(app)

_CARDS = ("Haunting Misery", "Skeletal Scrying")
#: Slots:       0                1         2               3                4           5
_PILE = ("Grizzly Bears", "Forest", "Black Knight", "Grizzly Bears", "Mind Rot", "Black Knight")
#: What a cast naming no set gives up for X = 2: the top of the pile down,
#: least valuable first (``ai_valuation.graveyard_price_order``, Torment's
#: W2G3) — the Forest before any spell for Skeletal Scrying, which takes any
#: card; for Haunting Misery's four two-mana creature cards the top two.
#: It was the top two whatever they were (the Mind Rot and a Black Knight).
_UNNAMED_PAYMENT = {
    "Haunting Misery": ["Black Knight", "Grizzly Bears"],
    "Skeletal Scrying": ["Forest", "Black Knight"],
}
#: The slots each card's cost may take.
_PAYABLE = {
    "Haunting Misery": (0, 2, 3, 5),         # creature cards
    "Skeletal Scrying": (0, 1, 2, 3, 4, 5),  # any card
}


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


def _board(name: str) -> Game:
    by_name = _pool()
    game = Game(players=[
        PlayerState(name="P1", library=[by_name["Forest"]] * 12),
        PlayerState(name="P2", library=[by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.players[0].hand.append(by_name[name])
    game.players[0].graveyard.extend(by_name[n] for n in _PILE)
    return game


def _cast(game, name: str, x: int, slots, **kwargs):
    return game.cast_from_hand(
        0, name, x_value=x, target_player_index=1,
        cost_graveyard_indices=slots, **kwargs,
    )


def _pile(game) -> list[str]:
    return [card.name for card in game.players[0].graveyard]


def _exiled(game) -> list[str]:
    return [card.name for card in game.players[0].exile]


def _left_behind(name: str, removed) -> list[str]:
    """The pile after *removed* slots leave and the spell itself arrives."""
    return [n for slot, n in enumerate(_PILE) if slot not in removed] + [name]


@pytest.mark.parametrize("name", _CARDS)
def test_the_named_graveyard_cards_are_the_ones_exiled(name):
    payable = _PAYABLE[name]
    # Two named, from both ends and out of order: exiled in the order named.
    game = _board(name)
    named = [payable[-1], payable[0]]
    result = _cast(game, name, 2, named)
    assert result.supported, result.details
    assert _exiled(game) == [_PILE[slot] for slot in named]
    assert _pile(game) == _left_behind(name, named)

    # Both copies of one card (slots 0 and 3 hold the same object): exactly
    # those two leave, and exactly one each.
    game = _board(name)
    result = _cast(game, name, 2, [0, 3])
    assert result.supported, result.details
    assert _exiled(game) == ["Grizzly Bears", "Grizzly Bears"]
    assert _pile(game) == _left_behind(name, [0, 3])

    # One copy of the two: the other stays where it was.
    game = _board(name)
    result = _cast(game, name, 1, [0])
    assert result.supported, result.details
    assert _exiled(game) == ["Grizzly Bears"]
    assert _pile(game) == _left_behind(name, [0])


@pytest.mark.parametrize("name", _CARDS)
def test_a_cast_that_names_no_set_takes_the_top_of_the_pile(name):
    game = _board(name)
    result = _cast(game, name, 2, None)
    assert result.supported, result.details
    assert _exiled(game) == _UNNAMED_PAYMENT[name]
    # X = 0 exiles nothing, named or not.
    for slots in (None, []):
        game = _board(name)
        assert _cast(game, name, 0, slots).supported
        assert _exiled(game) == [] and _pile(game) == _left_behind(name, [])


@pytest.mark.parametrize("name", _CARDS)
@pytest.mark.parametrize("why, x, slots", [
    ("short", 2, [0]),
    ("empty for a cost that takes two", 2, []),
    ("long", 2, [0, 2, 3]),
    ("one slot twice", 2, [0, 0]),
    ("past the end of the pile", 1, [6]),
    ("negative", 1, [-1]),
])
def test_a_named_set_that_is_not_the_payment_refuses_the_cast(name, why, x, slots):
    game = _board(name)
    result = _cast(game, name, x, slots)
    assert not result.supported, why
    assert "CR 601.2h" in result.details, result.details
    # CR 601.2e: nothing moved, nothing was spent.
    assert _pile(game) == list(_PILE) and _exiled(game) == []
    assert [card.name for card in game.players[0].hand] == [name]


def test_a_card_the_cost_cannot_take_refuses_the_cast():
    """Haunting Misery exiles *creature* cards: the Forest at slot 1 and the
    Mind Rot at slot 4 pay nothing."""
    for slot in (1, 4):
        game = _board("Haunting Misery")
        result = _cast(game, "Haunting Misery", 1, [slot])
        assert not result.supported and "CR 601.2h" in result.details
        assert _pile(game) == list(_PILE)
    # …and Skeletal Scrying, which prints no type, takes either.
    for slot in (1, 4):
        game = _board("Skeletal Scrying")
        assert _cast(game, "Skeletal Scrying", 1, [slot]).supported
        assert _exiled(game) == [_PILE[slot]]


# ---------------------------------------------------------------------------
# Cast from the graveyard that pays (CR 601.2a)
# ---------------------------------------------------------------------------

def _graveyard_cast_board() -> tuple[Game, object]:
    by_name = _pool()
    scrying = by_name["Skeletal Scrying"]
    game = Game(players=[
        PlayerState(name="P1", library=[by_name["Forest"]] * 12),
        PlayerState(name="P2", library=[by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    # Slots:                        0                1        2         3
    game.players[0].graveyard.extend(
        [by_name["Grizzly Bears"], by_name["Forest"], scrying, by_name["Mind Rot"]]
    )
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast", cards=[scrying],
        duration="end_of_turn", source_name="Test Grant",
    )
    return game, scrying


def test_a_spell_cast_from_the_graveyard_is_not_one_of_the_cards_it_exiles():
    # Three other cards: an X of four cannot be paid…
    game, _scrying = _graveyard_cast_board()
    refused = game.cast_from_hand(0, "Skeletal Scrying", x_value=4, from_zone="graveyard")
    assert not refused.supported and "CR 601.2h" in refused.details, refused.details
    assert len(game.players[0].graveyard) == 4 and not game.players[0].exile

    # …and an X of three takes exactly the other three.
    game, _scrying = _graveyard_cast_board()
    cast = game.cast_from_hand(0, "Skeletal Scrying", x_value=3, from_zone="graveyard")
    assert cast.supported, cast.details
    assert sorted(_exiled(game)) == ["Forest", "Grizzly Bears", "Mind Rot"]
    assert _pile(game) == ["Skeletal Scrying"]


def test_slots_named_for_a_graveyard_cast_are_read_as_the_caster_saw_them():
    # The spell's own slot pays nothing.
    game, _scrying = _graveyard_cast_board()
    refused = game.cast_from_hand(
        0, "Skeletal Scrying", x_value=1, from_zone="graveyard",
        cost_graveyard_indices=[2],
    )
    assert not refused.supported and "CR 601.2h" in refused.details, refused.details

    # Slot 3 is the Mind Rot *above* the spell: by the time the cost is
    # collected the spell has left and it sits at slot 2. It is the Mind Rot
    # that goes, not whatever slid into the number.
    game, _scrying = _graveyard_cast_board()
    cast = game.cast_from_hand(
        0, "Skeletal Scrying", x_value=2, from_zone="graveyard",
        cost_graveyard_indices=[3, 0],
    )
    assert cast.supported, cast.details
    assert _exiled(game) == ["Mind Rot", "Grizzly Bears"]
    assert _pile(game) == ["Forest", "Skeletal Scrying"]


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

def _session(name: str):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4242,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    by_name = _pool()
    game.enforce_mana_costs = False
    game.players[0].battlefield, game.players[1].battlefield = [], []
    game.players[0].hand = [by_name[name]]
    game.players[0].graveyard = [by_name[n] for n in _PILE]
    game.players[0].exile = []
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


@pytest.mark.parametrize("name", _CARDS)
def test_the_cast_route_forwards_the_graveyard_set(name):
    payable = _PAYABLE[name]
    sid, game = _session(name)
    named = [payable[0], payable[2]]
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": name, "x_value": 2,
        "target_seat": 1, "cost_graveyard_indices": named,
    })
    assert response.status_code == 200, response.text
    assert _exiled(game) == [_PILE[slot] for slot in named]

    # A set that is not the payment is a 400 naming the rule, nothing spent.
    sid, game = _session(name)
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": name, "x_value": 2,
        "target_seat": 1, "cost_graveyard_indices": [payable[0]],
    })
    assert response.status_code == 400, response.text
    assert "CR 601.2h" in response.json()["detail"]
    assert _pile(game) == list(_PILE) and _exiled(game) == []

    # A client that does not know the field casts as it always did.
    sid, game = _session(name)
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": name, "x_value": 2, "target_seat": 1,
    })
    assert response.status_code == 200, response.text
    assert _exiled(game) == _UNNAMED_PAYMENT[name]


def test_these_are_the_pools_graveyard_exile_cast_costs():
    """The floor: the two cards above are every card in either manifest role
    that charges a graveyard exile to be cast — a third arrives here first."""
    found = sorted(
        unit.name for unit in compilation_units(_pool().values())
        if compile_card_oracle(unit).supported
        and any(cost.exile_graveyard_filter is not None for cost in additional_costs(unit))
    )
    assert found == sorted(_CARDS), found


@pytest.mark.parametrize("name", _CARDS)
def test_with_the_gate_off_the_payment_still_takes_only_what_the_cost_names(
    name, monkeypatch,
):
    """The second sweep, the other way: the payment now trusts a list the gate
    checked, so the gate is taken away and the payment is handed what the
    gate would have refused — a slot twice, a slot past the end, one too many,
    one too few and (for Haunting Misery) a card that is not a creature. It
    must exile exactly X cards, every one of them a card the cost could take."""
    payable = _PAYABLE[name]
    monkeypatch.setattr(
        Game, "_named_graveyard_cost_refusal", lambda self, *args, **kwargs: None,
    )
    for slots in ([0, 0], [0, 99], [0, 2, 3], [0], [1, 4], []):
        game = _board(name)
        result = _cast(game, name, 2, slots)
        assert result.supported, (slots, result.details)
        exiled = _exiled(game)
        assert len(exiled) == 2, (slots, exiled)
        assert sorted(exiled + _pile(game)) == sorted(list(_PILE) + [name]), slots
        if name == "Haunting Misery":
            assert set(exiled) <= {"Grizzly Bears", "Black Knight"}, (slots, exiled)
        # A named slot the cost could take is among what went.
        for slot in dict.fromkeys(slots):
            if slot in payable and list(dict.fromkeys(slots)).index(slot) < 2:
                assert _PILE[slot] in exiled, (slots, exiled)
