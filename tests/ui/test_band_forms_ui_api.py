"""Which attackers may be declared as one band is the server's answer.

CR 702.22c gives two ways to form an attacking band: "one or more attacking
creatures with banding and up to one attacking creature without banding", and
"one or more attacking [quality] creatures with 'bands with other [quality]'
and any number of other [quality] creatures". The engine validates a declared
band against both (``Game._validate_attacking_bands``).

The browser offered its "Attack as Band" button from a count of its own: the
word "banding" on each selected card — the payload's keyword strip, else the
printed text — against the first form alone. The count was right (the strip is
layer 6's, so a granted or a lost banding read correctly); the rule was half
of CR 702.22c. Measured over the sets below, 12 of 60 answers were wrong, every
one a legal band of legendary creatures under a Cathedral of Serra that was
never offered.

``combat.band_forms`` carries the forms a band can take on this board, each as
three lists of the active player's battlefield slots, and
``selectedAttackersCanBand`` is the one reader. The census is every set of two
or more of the active player's creatures on six boards: what the client's
reader says of it (run in node over the payload the server sent) is what the
engine says of the same band declared.
"""
from __future__ import annotations

import itertools
import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body, resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_LEGENDS = ["General Jarkeld", "Sidar Jabari", "Zuberi, Golden Feather"]

#: label -> the active player's battlefield.
_BOARDS = {
    "plain banding": ["Benalish Hero", "Mesa Pegasus", "Grizzly Bears", "Hill Giant"],
    "bands with other": ["Cathedral of Serra", *_LEGENDS, "Sol'kanar the Swamp King", "Grizzly Bears"],
    "both forms": ["Cathedral of Serra", "Benalish Hero", *_LEGENDS[:2], "Grizzly Bears"],
    "banding taken away": ["Humility", "Benalish Hero", "Mesa Pegasus", "Grizzly Bears"],
    "banding granted": ["Helm of Chatzuk", "Grizzly Bears", "Hill Giant", "Craw Wurm"],
    "nobody bands": ["Grizzly Bears", "Hill Giant", "Craw Wurm"],
}


def _session(board):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = False
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for name in board:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    game._recompute_continuous_effects()
    game.stack.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _to_declare_attackers(game):
    game.current_phase = "combat"
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"


def _state(sid):
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _legacy_can_band(battlefield, selected) -> bool:
    """The reader the client had: the plain form, counted off each card's
    keyword strip with its printed text as the fallback."""
    def has_banding(card):
        if any(str(k).lower() == "banding" for k in card.get("keywords") or []):
            return True
        return str(card.get("oracle_text") or "").lower().startswith("banding")

    if len(selected) < 2:
        return False
    banders = sum(1 for slot in selected if has_banding(battlefield[slot]))
    return banders >= 1 and len(selected) - banders <= 1


@pytest.fixture(scope="module")
def census():
    """Per board: the payload, every set of two or more creature slots, and
    whether the engine accepts that set declared as one band."""
    boards = {}
    for label, board in _BOARDS.items():
        sid, game = _session(board)
        if label == "banding granted":
            helm = next(p for p in game.controlled_by(0) if p.card.name == "Helm of Chatzuk")
            bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
            granted = game.activate_permanent_ability(
                0, "Helm of Chatzuk",
                permanent_index=game.battlefield_index_of(helm),
                target_permanent_ids=[bears.permanent_id],
            )
            assert granted.supported, granted.details
            resolve_stack(game)
        _to_declare_attackers(game)
        state = _state(sid)
        controller = game.players[0]
        slots = [
            slot for slot, permanent in enumerate(game.controlled_by(0))
            if permanent.is_creature
        ]
        sets = [
            list(chosen)
            for size in range(2, len(slots) + 1)
            for chosen in itertools.combinations(slots, size)
        ]
        truth = [
            game._validate_attacking_bands([chosen], chosen, controller)[1] is None
            for chosen in sets
        ]
        boards[label] = {
            "sid": sid, "game": game, "state": state, "sets": sets, "truth": truth,
        }
    return boards


@needs_node
def test_the_client_offers_a_band_exactly_where_the_engine_accepts_one(census):
    examined = 0
    legal = 0
    for label, board in census.items():
        answers = run_app_js(
            ["getCombatState", "selectedAttackersCanBand"],
            """
            return INPUT.sets.map((chosen) => {
              combatAttackerDraft = chosen;
              return selectedAttackersCanBand(currentState);
            });
            """,
            {"state": board["state"], "sets": board["sets"]},
            prelude="let currentState = INPUT.state; let combatAttackerDraft = [];",
        )
        for chosen, said, truth in zip(board["sets"], answers, board["truth"]):
            assert said is truth, (label, chosen, board["state"]["combat"]["band_forms"])
        examined += len(answers)
        legal += sum(board["truth"])

    assert examined >= 55, examined
    assert legal >= 20, legal


def test_the_census_names_the_reader_it_replaced(census):
    """Backwards. The keyword count agrees with the engine wherever the only
    way to band is the plain form on printed banding — and is wrong on the
    board where the band is "with other": every legal band of legendary
    creatures there is one it never offered."""
    wrong = {}
    for label, board in census.items():
        battlefield = board["state"]["players"][0]["battlefield"]
        wrong[label] = sum(
            1 for chosen, truth in zip(board["sets"], board["truth"])
            if _legacy_can_band(battlefield, chosen) is not truth
        )

    assert wrong["plain banding"] == 0 and wrong["nobody bands"] == 0
    # Who has banding it had right: the keyword strip is layer 6's.
    assert wrong["banding taken away"] == 0 and wrong["banding granted"] == 0
    assert wrong["bands with other"] >= 10, wrong
    assert wrong["both forms"] >= 1, wrong


def test_the_forms_are_facts_about_this_board(census):
    forms = {label: board["state"]["combat"]["band_forms"] for label, board in census.items()}

    # Benalish Hero and Mesa Pegasus have banding; every creature is a member
    # and one without may join.
    assert forms["plain banding"] == [{"members": [0, 1, 2, 3], "needs": [0, 1], "extras": 1}]
    # Cathedral of Serra: the three white legends hold the ability, the fourth
    # legend is a member without it, and the Bears is nobody's.
    assert forms["bands with other"] == [
        {"members": [1, 2, 3, 4], "needs": [1, 2, 3], "extras": None}
    ]
    assert len(forms["both forms"]) == 2
    # "All creatures lose all abilities" (Humility): nobody has banding, so
    # there is no way to band and no form is sent.
    assert forms["banding taken away"] == []
    # Helm of Chatzuk gave the Bears banding until end of turn.
    assert forms["banding granted"] == [{"members": [1, 2, 3], "needs": [1], "extras": 1}]
    assert forms["nobody bands"] == []


def test_the_forms_ride_the_declare_attackers_step_alone():
    sid, game = _session(_BOARDS["plain banding"])

    assert _state(sid)["combat"]["band_forms"] == []
    _to_declare_attackers(game)
    assert len(_state(sid)["combat"]["band_forms"]) == 1


def test_a_band_the_client_now_offers_is_one_the_action_takes(census):
    """Three legendary creatures, none with banding: the declaration the old
    reader never let a player make."""
    board = census["bands with other"]

    response = client.post(f"/api/sessions/{board['sid']}/action", json={
        "seat": 0, "action": "declare_attackers", "attacker_indices": [1, 2, 3],
        "bands": [[1, 2, 3]], "target_seat": 1,
    })

    assert response.status_code == 200, response.text
    game = board["game"]
    assert sorted(game.combat_attackers) == [1, 2, 3]
    assert [sorted(band) for band in game.combat_bands] == [[1, 2, 3]]


def test_one_reader_and_nothing_read_off_a_card():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    reader = app_js_function_body("selectedAttackersCanBand")

    assert "band_forms" in reader
    assert "oracle_text" not in reader and "keywords" not in reader
    assert "cardHasBanding" not in source
    assert source.count("?.band_forms") == 1
