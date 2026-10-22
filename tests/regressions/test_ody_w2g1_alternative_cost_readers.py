"""Three readers price an alternative-cost cast, and the cast path is the truth.

CR 118.9d applies every cost increase to an alternative cost, so a pitch spell
under Sphere of Resistance owes {1} beside its card and its life
(``tests/rules/test_alternative_cost_increases.py`` is the cast path's own
census). Three other readers answer "could this be cast for its alternative
cost right now?" before the cast is made:

* ``legality_cast_spec.cast_cost_offers`` — the offer's ``payable``, which the cost
  prompt greys the option by;
* ``web/state_view`` — the castable highlight, which falls back to that flag
  when the mana cost cannot be paid;
* ``ai_policy._cast_candidate`` — the AI's proposal, which takes the
  alternative cost when the mana cost cannot be planned.

All three read an alternative cost as owing no mana, which was true of the cast
path until it began charging the increases — and the day it did, each of them
would have offered a cast the engine refuses (for the AI: the same card, every
turn, which is what ``refused_casts`` counts). They ask one function now,
``Game.alternative_cost_mana``, and this file is the census that says they
agree with the cast, over every card in the pool printing an alternative cost,
on three boards:

* **free**     — no tax, every mana source tapped: all three say yes;
* **owed**     — Sphere of Resistance, every mana source tapped: all say no;
* **payable**  — Sphere of Resistance, one Forest untapped: all say yes, and
  the AI's proposal, executed through its own executor, is accepted.

A reader is held only over the cards it says yes to on the free board (a card
the AI declines for its own reasons says nothing about pricing), with a floor
on how many that is.

Validated backwards, with the cast path already charging and the three
readers as they stood: each of them said yes on the owed board for all 43
cards the census examines, and the commander test below failed on its second
line.
"""
from __future__ import annotations

from functools import lru_cache

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.ai_policy import _cast_candidate, cast_announcement, tap_planned_lands
from engine.alternative_costs import alternative_costs
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units, whole_card
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from web.app import app, store
from web.state_view import _compute_playable_hand_indices

client = TestClient(app)

_BAIT_HAND = (
    "Grizzly Bears", "Prodigal Sorcerer", "Black Knight", "Mons's Goblin Raiders",
    "White Knight", "Forest", "Island", "Swamp", "Mountain", "Plains",
)
_BAIT_BOARD = (
    "Forest", "Forest", "Island", "Island", "Swamp", "Swamp", "Mountain",
    "Mountain", "Plains", "Plains", "Grizzly Bears", "Grizzly Bears", "Sol Ring",
)
_TAX = "Sphere of Resistance"
_BOARDS = ("free", "owed", "payable")


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


def _population() -> list:
    return sorted(
        (
            unit for unit in compilation_units(_pool().values())
            if compile_card_oracle(unit).supported and alternative_costs(unit)
        ),
        key=lambda unit: unit.name,
    )


@pytest.fixture(scope="module")
def session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4243,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return store.get(sid)


def _board(session, unit, board: str) -> tuple[Game, dict]:
    """The board, with the spell at hand position 0 and seat 0 holding
    priority in its own main phase; and the announcement its picker offers."""
    by_name = _pool()
    game = Game(players=[PlayerState(name="Host"), PlayerState(name="Guest")])
    game.enforce_mana_costs = True
    for name in _BAIT_BOARD:
        for seat in (0, 1):
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    held = whole_card(unit) if unit.face_of is not None else unit
    game.players[0].hand.extend([held] + [by_name[n] for n in _BAIT_HAND] * 2)
    game.players[1].hand.extend(by_name[n] for n in _BAIT_HAND)
    for seat in (0, 1):
        game.players[seat].graveyard.extend(
            by_name[n] for n in ("Grizzly Bears", "Black Knight", "Black Knight", "Black Knight")
        )
        game.players[seat].library.extend([by_name["Forest"]] * 10)
    if board != "free":
        game._put_permanent_onto_battlefield(1, Permanent(card=by_name[_TAX]), None)
    game.turn = 3
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None

    announcement = _announce(game, unit)

    # Every mana source seat 0 has, tapped — a tapped land still pays a
    # sacrifice or a return, so the alternative cost itself is untouched. One
    # Forest is left on the payable board: enough for the {1}, and for no
    # card's mana cost under the tax (the cheapest in the population is two).
    spared = board == "payable"
    for permanent in game.controlled_by(0):
        if permanent.card.name == "Forest" and spared:
            spared = False
            continue
        if permanent.card.primary_type == "land" or permanent.card.name == "Sol Ring":
            permanent.tapped = True
    session.game = game
    session.current_turn = 0
    game.start_priority_window(0)
    return game, announcement


def _announce(game, unit) -> dict:
    spec = game.cast_target_spec(0, unit)
    if spec.get("kind") == "stack" or spec.get("also_stack"):
        game.enforce_mana_costs = False
        game.players[1].hand.append(_pool()["Giant Growth"])
        bears = next(p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears")
        game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
        game.enforce_mana_costs = True
        spec = game.cast_target_spec(0, unit)
    if spec.get("kind") == "divided":
        return {"divided_targets": [(1, None, int(spec.get("division_total") or 1))]}
    for entry in spec.get("valid_targets") or []:
        kind = entry.get("kind")
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            return {
                "target_permanent_ids": [permanent.permanent_id],
                "target_player_index": entry["seat"],
            }
        if kind == "player":
            return {"target_player_index": entry["seat"]}
        if kind == "graveyard":
            return {
                "target_player_index": entry["seat"],
                "target_permanent_index": entry["index"],
            }
        if kind == "stack":
            return {"target_stack_index": len(game.stack) - 1 - entry["stack_index"]}
    return {}


def _tap_what_is_untapped(game) -> None:
    """A human's payment: every untapped land tapped into the pool."""
    for permanent in list(game.controlled_by(0)):
        if permanent.card.primary_type == "land" and not permanent.tapped:
            game.tap_land_for_mana(
                0, permanent.card.name, "G", permanent_id=permanent.permanent_id,
            )


def _truth(session, unit, board: str) -> bool:
    """Whether the cast path accepts the alternative-cost cast on *board*,
    after tapping everything the board leaves untapped."""
    try:
        game, announcement = _board(session, unit, board)
    except Exception:  # noqa: BLE001 - a board that cannot announce the card
        return False
    _tap_what_is_untapped(game)
    return game.queue_from_hand(
        0, unit.name, alternative_cost=True, **announcement,
    ).supported


def _offer_says(session, unit, board: str) -> bool:
    game, _announcement = _board(session, unit, board)
    return any(
        offer.get("kind") == "alternative" and offer.get("payable")
        for offer in game.cast_cost_offers(0, unit, spell_hand_index=0)
    )


def _highlight_says(session, unit, board: str) -> bool:
    _board(session, unit, board)
    return 0 in _compute_playable_hand_indices(session, 0)


def _ai_says(session, unit, board: str) -> tuple[bool, bool]:
    """``(proposed for its alternative cost, and the engine accepted it)``."""
    game, _announcement = _board(session, unit, board)
    action = _cast_candidate(game, 0, unit, 0)
    if action is None or not action.alternative_cost:
        return False, False
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, unit.name, **cast_announcement(action))
    return True, bool(result.supported)


@pytest.fixture(scope="module")
def castable(session) -> list:
    """The cards the cast path casts for their alternative cost on the free
    board — and, as the census's own sanity, refuses on the owed board and
    accepts on the payable one."""
    found = [unit for unit in _population() if _truth(session, unit, "free")]
    assert len(found) >= 43, [unit.name for unit in found]
    assert not [u.name for u in found if _truth(session, u, "owed")]
    assert not [u.name for u in found if not _truth(session, u, "payable")]
    return found


def test_the_offer_is_payable_exactly_when_the_cast_is(session, castable):
    wrong = {
        board: [
            unit.name for unit in castable
            if _offer_says(session, unit, board) != (board != "owed")
        ]
        for board in _BOARDS
    }
    assert not any(wrong.values()), wrong


def test_the_highlight_glows_exactly_when_the_cast_can_be_made(session, castable):
    examined = [u for u in castable if _highlight_says(session, u, "free")]
    over = [u.name for u in examined if _highlight_says(session, u, "owed")]
    under = [u.name for u in examined if not _highlight_says(session, u, "payable")]
    assert not over, f"glows over an alternative cost whose tax nothing pays: {over}"
    assert not under, f"dark over an alternative cost the board can pay: {under}"
    # Measured: all 43.
    assert len(examined) >= 40, [u.name for u in examined]


def test_the_ai_proposes_an_alternative_cost_only_where_it_can_pay_the_tax(
    session, castable,
):
    examined = [u for u in castable if _ai_says(session, u, "free") == (True, True)]
    proposed_unpayable = [
        u.name for u in examined if _ai_says(session, u, "owed")[0]
    ]
    refused, silent = [], []
    for unit in examined:
        proposed, accepted = _ai_says(session, unit, "payable")
        if not proposed:
            silent.append(unit.name)
        elif not accepted:
            refused.append(unit.name)
    assert not proposed_unpayable, (
        f"proposed for an alternative cost with the tax unpayable: "
        f"{proposed_unpayable}"
    )
    assert not refused, f"proposed, tapped for, and refused: {refused}"
    assert not silent, f"payable and not proposed: {silent}"
    # Measured: all 43 (a policy that grows a reason to hold one back may
    # lower this; one that proposes none has stopped being examined).
    assert len(examined) >= 35, [u.name for u in examined]


# ---------------------------------------------------------------------------
# CR 903.8: the commander tax is a cost increase like any other
# ---------------------------------------------------------------------------

def test_the_commander_tax_is_owed_beside_a_granted_alternative_cost():
    """Dream Halls lets a spell be cast for a discard rather than its mana
    cost, the command zone included — and CR 118.9d keeps CR 903.8's {2} in
    force on top of the discard, for the highlight and for the cast alike."""
    by_name = _pool()
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 9031, "variant": "commander",
        "host_deck_cards": [{"name": "Swamp", "count": 40}],
        "host_deck_commander": [{"name": "Kaervek, the Spiteful", "count": 1}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_commander": [{"name": "Azusa, Lost but Seeking", "count": 1}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    game.start_priority_window(0)
    game._put_permanent_onto_battlefield(0, Permanent(card=by_name["Dream Halls"]), None)
    game.players[0].hand.append(by_name["Black Knight"])

    def glowing() -> list:
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        return state["players"][0]["playable_command_indices"]

    # Never cast before: the discard is the whole price.
    assert glowing() == [0]
    # One previous cast: {2} more, which an empty pool and no land cannot pay.
    game.players[0].commander_casts["Kaervek, the Spiteful"] = 1
    assert glowing() == []
    refused = game.queue_from_hand(
        0, "Kaervek, the Spiteful", from_zone="command", alternative_cost=True,
    )
    assert not refused.supported and "{2}" in refused.details, refused.details
    assert "CR 118.9d" in refused.details
    game.players[0].mana_pool["C"] = 2
    assert glowing() == [0]
    cast = game.queue_from_hand(
        0, "Kaervek, the Spiteful", from_zone="command", alternative_cost=True,
    )
    assert cast.supported, cast.details
    assert not any(game.players[0].mana_pool.values())
