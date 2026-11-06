"""The ability menu greys an ability by the server's answer alone.

``ability_denials`` (one entry per usable ability of each of the viewer's
permanents) has carried the engine's CR 602.5 prohibitions since they were
written. Beside it the client kept its own copies of three more engine answers
and asked them when the server's list was silent:

* ``activationTimingDisabledReason`` read six "Activate only …" windows off
  the ability's text (upkeep, your turn, sorcery speed, the end of combat
  step, combat, an opponent's turn before attackers);
* ``abilityLineDisabledReason`` read Library of Alexandria's "exactly seven
  cards in hand" off the text and Jandor's Ring's "discard the last card you
  drew this turn" off a player flag;
* ``loyaltyAbilityDisabledReason`` re-derived CR 606.3 and 606.6 from two
  permanent flags and the counters.

The copies are deleted, and the wire's list is now the activation path's own
refusals before anything is chosen (``web/serialization._ability_denial``):
the loyalty window (``Game.loyalty_activation_refusal``, extracted from the
path), the prohibition table, and a non-mana cost the board cannot pay
(``Game.unpayable_activation_cost``). The census below is the deletion's
proof, run backwards: on two boards, every ability in the pool the deleted
readers denied is denied by the wire — in the engine's words — and the
activate route refuses it.
"""
from __future__ import annotations

import shutil

import pytest

from engine import faces
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import app_js_function_body, client, run_app_js
from web.app import store

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)

#: The deleted client readers, each phrase with the boards it denied on:
#: "A" is the other seat's turn, "B" the viewer's own — both in the precombat
#: main phase with an empty stack, the viewer holding no card and having
#: drawn none this turn.
_DELETED_READERS = {
    "activate only during your upkeep": {"A", "B"},
    "only during your turn": {"A"},
    "activate only as a sorcery": {"A"},
    "activate only during the end of combat step": {"A", "B"},
    "activate only during combat": {"A", "B"},
    "activate only during an opponent's turn, before attackers are declared": {"B"},
    "activate only if you have exactly seven cards in hand": {"A", "B"},
    "discard the last card you drew this turn": {"A", "B"},
}


def _phrase_of(line: str):
    lowered = (line or "").lower()
    for phrase in _DELETED_READERS:
        if phrase in lowered and not (
            phrase == "activate only during combat" and "end of combat" in lowered
        ):
            return phrase
    return None


def _subjects():
    """Every permanent card in the pool with an ability one of the deleted
    readers judged, and every planeswalker (the loyalty reader)."""
    found = []
    for unit in faces.compilation_units(_CATALOG):
        if unit is not _CARDS.get(unit.name) or unit.primary_type in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(unit)
        if any(_phrase_of(ability.source_line) for ability in program.activated_abilities) or any(
            ability.cost.is_loyalty for ability in program.activated_abilities
        ):
            found.append(unit)
    return found


def _board(subjects, *, turn):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4406,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
        player.hand = []
    for card in subjects:
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    game._recompute_continuous_effects()
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = turn
    game.active_player_index = turn
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _served(sid, game):
    payload = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    rows = []
    for slot, permanent in enumerate(game.controlled_by(0)):
        entry = payload["players"][0]["battlefield"][slot]
        usable = game.usable_abilities_of(permanent, card=permanent.effective_card)
        denials = entry.get("ability_denials") or [None] * len(usable)
        assert len(denials) == len(usable), entry["name"]
        for index, ability in enumerate(usable):
            rows.append({
                "name": entry["name"], "id": entry["id"], "index": index,
                "phrase": _phrase_of(ability.source_line),
                "loyalty": bool(ability.cost.is_loyalty), "denial": denials[index],
                "card": entry,
            })
    return rows


def _boards(subjects):
    boards = {}
    for label, turn in (("A", 1), ("B", 0)):
        sid, game = _board(subjects, turn=turn)
        boards[label] = (sid, game, _served(sid, game))
    return boards


#: One card for each deleted reader, and a planeswalker: the quick pass's
#: board. The whole pool's is ``census`` (``full``: two boards of ~90
#: permanents take ~15 s to serve).
_SMALL = (
    "Rock Hydra", "Disrupting Scepter", "Illusionary Mask", "Desert", "Jade Statue",
    "Nettling Imp", "Library of Alexandria", "Jandor's Ring", "Basri Ket",
)


@pytest.fixture(scope="module")
def small():
    return _boards([_CARDS[name] for name in _SMALL])


@pytest.fixture(scope="module")
def census():
    return _boards(_subjects())


def _judge(boards):
    """Every ability a deleted reader denied on these boards: the wire denies
    it too. Returns how many were judged."""
    judged = 0
    for label, (_sid, _game, rows) in boards.items():
        for row in rows:
            if row["phrase"] is not None and label in _DELETED_READERS[row["phrase"]]:
                judged += 1
                assert row["denial"], (label, row["name"], row["phrase"])
            # The other seat's turn shuts every loyalty ability (CR 606.3) —
            # unless the permanent widens its own window (Teferi, Master of
            # Time: the deleted reader's `loyalty_any_time`).
            if row["loyalty"] and label == "A" and not row["card"].get("loyalty_any_time"):
                judged += 1
                assert row["denial"] and "CR 606.3" in row["denial"], row["name"]
    return judged


def _refusals(boards):
    """Every denied ability, activated anyway, is refused — in the wire's own
    sentence, unless the announcement refused it first for a target the
    board does not have (CR 601.2c comes before the window). Returns how many
    were sent."""
    checked = 0
    for _label, (sid, _game, rows) in boards.items():
        for row in rows:
            if not row["denial"]:
                continue
            refused = client.post(f"/api/sessions/{sid}/action", json={
                "seat": 0, "action": "activate", "permanent_name": row["name"],
                "permanent_id": row["id"], "ability_index": row["index"], "target_seat": 1,
            })
            assert refused.status_code == 400, (row["name"], row["index"], refused.text)
            detail = refused.json()["detail"]
            assert detail == row["denial"] or "target" in detail, (row["name"], detail)
            checked += 1
    return checked


def test_one_of_each_the_deleted_readers_denied_the_wire_denies(small):
    assert _judge(small) >= 12
    assert _refusals(small) >= 12


@pytest.mark.full
def test_every_ability_the_deleted_readers_denied_the_wire_denies(census):
    # A sweep that judged nothing would pass as one that found nothing: every
    # phrase and the loyalty reader are represented in the pool.
    phrases = {row["phrase"] for _s, _g, rows in census.values() for row in rows}
    assert set(_DELETED_READERS) <= phrases
    assert _judge(census) >= 100


@pytest.mark.full
def test_the_route_refuses_what_the_wire_denies(census):
    assert _refusals(census) >= 100


def test_the_loyalty_window_is_per_ability_on_the_planeswalker_s_own_turn(small):
    sid, game, rows = small["B"]
    walkers = [row for row in rows if row["loyalty"]]
    assert walkers
    # On its controller's turn, main phase, empty stack: only a minus cost
    # bigger than the loyalty on it is denied (CR 606.6).
    for row in walkers:
        assert row["denial"] is None or "CR 606.6" in row["denial"], row
    # Once one of its loyalty abilities has been activated this turn, every
    # one is denied (CR 606.3).
    walker = next(p for p in game.controlled_by(0) if p.permanent_id == walkers[0]["id"])
    walker.metadata["loyalty_ability_used_turn"] = game.turn
    after = [row for row in _served(sid, game) if row["id"] == walker.permanent_id and row["loyalty"]]
    assert after and all("already been activated this turn" in row["denial"] for row in after)
    walker.metadata.pop("loyalty_ability_used_turn")


def test_jandors_ring_and_the_library_answer_the_board_not_the_text(small):
    sid, game, rows = small["B"]
    ring = next(row for row in rows if row["name"] == "Jandor's Ring")
    library = next(row for row in rows if row["name"] == "Library of Alexandria" and row["phrase"])
    assert "no card drawn this turn" in ring["denial"]
    assert "seven" in library["denial"]
    # Seven cards in hand, one of them drawn this turn: both open up.
    game.players[0].library = [_CARDS["Forest"]] * 3 + game.players[0].library
    game.players[0].hand = [_CARDS["Mountain"]] * 6
    game._draw_with_replacements(game.players[0], 1)
    assert len(game.players[0].hand) == 7
    after = {(row["name"], row["index"]): row["denial"] for row in _served(sid, game)}
    assert after[("Jandor's Ring", ring["index"])] is None
    assert after[("Library of Alexandria", library["index"])] is None
    game.players[0].hand = []


@needs_node
def test_the_menu_greys_exactly_the_wire_s_denials(small):
    _sid, _game, rows = small["A"]
    sample = [row for row in rows if row["phrase"] or row["loyalty"]]
    answers = run_app_js(
        ["abilityOptionDisabledReason", "abilityProhibitionOf"],
        "return INPUT.map((row) => abilityOptionDisabledReason("
        "{ index: row.index, line: 'Activate only during your upkeep.' }, row.card));",
        [{"index": row["index"], "card": row["card"]} for row in sample],
    )
    assert answers == [row["denial"] for row in sample]


def test_the_client_reads_no_ability_text_for_a_denial():
    menu = app_js_function_body("abilityOptionDisabledReason")
    assert "abilityProhibitionOf(card, opt?.index)" in menu
    assert ".line" not in menu and "oracle_text" not in menu
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    for deleted in (
        "function activationTimingDisabledReason", "function abilityLineDisabledReason",
        "function loyaltyAbilityDisabledReason", "has_last_drawn_card",
    ):
        assert deleted not in source, deleted
