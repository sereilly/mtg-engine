"""One permanent may be chosen for more than one printed slot (W2G1).

"Each player chooses from the lands they control a land of each basic land
type, then sacrifices the rest." (Global Ruin.) "Each player chooses from among
the permanents they control an artifact, a creature, an enchantment, and a
land, then sacrifices the rest." (Cataclysm.) The ``keep_permanents`` prompt
refused every answer shorter than a maximum matching, on the reading that one
permanent fills one slot. The cards' rulings say otherwise, in as many words:

* Global Ruin (2004-10-04): "If a land counts as multiple basic land types,
  you can choose it for either or for both of those land types."
* Cataclysm (2004-10-04): "If you control a permanent with more than one type,
  you can choose that same permanent for more than one of the choices if you
  want to. This makes it possible to select an artifact creature as both your
  artifact and creature, and then select a land and thereby keep only two
  cards."
* Planar Overlay (2004-10-04): "a dual land could be chosen as two of your
  land types" — tested with the card, in ``tests/sets/test_pls_sorceries.py``,
  because there it decides how many lands a seat must *return*.

So a legal answer is a range. Each chosen permanent still answers a slot of
its own (two plain artifacts are not Cataclysm's artifact and its creature),
and no slot the seat can answer may be left out; between those, how many is
the player's. The *default* did not move for these two: where the rest is
sacrificed the seat's best play is the most, which is what the matching gave.

What must not move with it: a single printed slot with a count ("five lands",
Limited Resources) is five different lands.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _board_card(set_pool, name):
    for code in ("LEA", "ATQ", "EXO", "INV"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(name)


def _table(set_pool, code, spell, mine=(), interactive=(0,)):
    """*spell* in seat 0's hand over seat 0's board, named in board order."""
    game = Game(players=[
        PlayerState(name="W2G1-A", hand=[set_pool(code)[spell]]),
        PlayerState(name="W2G1-B"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    for player in game.players:
        player.library = [set_pool("LEA")["Grizzly Bears"]] * 20
    board = []
    for name in mine:
        perm = Permanent(card=_board_card(set_pool, name))
        game._put_permanent_onto_battlefield(0, perm, None)
        board.append(perm)
    return game, board


def _names(game, seat=0):
    return sorted(perm.card.name for perm in game.controlled_by(seat))


def _ask(game, spell):
    assert game.cast_from_hand(0, spell).supported
    game.resolve_top_of_stack()
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]


def test_w2g1_global_ruin_keeps_one_dual_land_for_both_its_types(set_pool):
    """The ruling's own case. Tropical Island named alone is the Forest and
    the Island, so the Forest and the Island are "the rest"."""
    game, (tropical, forest, island) = _table(
        set_pool, "INV", "Global Ruin",
        mine=["Tropical Island", "Forest", "Island"],
    )
    _ask(game, "Global Ruin")
    assert game.confirm_keep_permanents(0, [tropical.permanent_id])
    resolve_stack(game)
    assert _names(game) == ["Tropical Island"]
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Forest", "Global Ruin", "Island",
    ]
    assert (
        "W2G1-A kept Tropical Island and sacrificed 2 permanent(s) (Global Ruin)"
        in game.log
    )


@pytest.mark.parametrize("kept, survivors", [
    (("Forest", "Island"), ["Forest", "Island"]),
    (("Tropical Island", "Forest"), ["Forest", "Tropical Island"]),
    (("Tropical Island", "Island"), ["Island", "Tropical Island"]),
])
def test_w2g1_global_ruin_still_takes_every_longer_answer(set_pool, kept, survivors):
    """"For either": each two-land answer the old rule accepted is still one."""
    game, board = _table(
        set_pool, "INV", "Global Ruin",
        mine=["Tropical Island", "Forest", "Island"],
    )
    by_name = {perm.card.name: perm.permanent_id for perm in board}
    _ask(game, "Global Ruin")
    assert game.confirm_keep_permanents(0, [by_name[name] for name in kept])
    resolve_stack(game)
    assert _names(game) == survivors


def test_w2g1_global_ruin_refuses_an_answer_that_leaves_a_type_out(set_pool):
    """No slot the seat can answer goes unanswered: a Forest alone leaves the
    Island unchosen while the seat holds one, an Island alone the Forest, and
    all three lands are a third land for two types. Nothing moves on a refusal.
    """
    game, (tropical, forest, island) = _table(
        set_pool, "INV", "Global Ruin",
        mine=["Tropical Island", "Forest", "Island"],
    )
    _ask(game, "Global Ruin")
    for answer in (
        [], [forest.permanent_id], [island.permanent_id],
        [tropical.permanent_id, forest.permanent_id, island.permanent_id],
    ):
        assert not game.confirm_keep_permanents(0, answer), answer
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]
    assert _names(game) == ["Forest", "Island", "Tropical Island"]


def test_w2g1_global_ruin_headless_default_is_still_the_most(set_pool):
    """The seat's best play where the rest is sacrificed, and unchanged: two of
    the three lands survive a headless Global Ruin."""
    game, _board = _table(
        set_pool, "INV", "Global Ruin",
        mine=["Tropical Island", "Forest", "Island"], interactive=(),
    )
    assert game.cast_from_hand(0, "Global Ruin").supported
    resolve_stack(game)
    assert len(_names(game)) == 2


def test_w2g1_cataclysm_keeps_one_artifact_creature_as_both(set_pool):
    """The ruling's own case: "select an artifact creature as both your
    artifact and creature, and then select a land and thereby keep only two
    cards." The Grizzly Bears and the Black Lotus are the rest."""
    game, board = _table(
        set_pool, "EXO", "Cataclysm",
        mine=["Clockwork Beast", "Grizzly Bears", "Black Lotus", "Forest"],
    )
    by_name = {perm.card.name: perm.permanent_id for perm in board}
    _ask(game, "Cataclysm")
    # The artifact creature alone answers two slots and not the land.
    assert not game.confirm_keep_permanents(0, [by_name["Clockwork Beast"]])
    assert game.confirm_keep_permanents(
        0, [by_name["Clockwork Beast"], by_name["Forest"]]
    )
    resolve_stack(game)
    assert _names(game) == ["Clockwork Beast", "Forest"]


def test_w2g1_cataclysm_still_lets_the_artifact_creature_stand_for_one(set_pool):
    """The ruling beside it: "if you select a creature for your creature and
    an artifact creature for your artifact, you get to keep both of these
    creatures." The maximum, and the headless default."""
    game, board = _table(
        set_pool, "EXO", "Cataclysm",
        mine=["Clockwork Beast", "Grizzly Bears", "Forest"],
    )
    _ask(game, "Cataclysm")
    assert game.confirm_keep_permanents(0, [perm.permanent_id for perm in board])
    resolve_stack(game)
    assert _names(game) == ["Clockwork Beast", "Forest", "Grizzly Bears"]

    game, _board = _table(
        set_pool, "EXO", "Cataclysm",
        mine=["Clockwork Beast", "Grizzly Bears", "Forest"], interactive=(),
    )
    assert game.cast_from_hand(0, "Cataclysm").supported
    resolve_stack(game)
    assert _names(game) == ["Clockwork Beast", "Forest", "Grizzly Bears"]


def test_w2g1_five_lands_is_still_five_different_lands(set_pool):
    """"Each player chooses five lands they control and sacrifices the rest."
    One printed slot with a count is one choice of that many permanents, so
    nothing shorter answers it — the relaxation is between printed slots, not
    inside one."""
    game, board = _table(
        set_pool, "EXO", "Limited Resources", mine=["Forest"] * 7,
    )
    assert game.cast_from_hand(0, "Limited Resources").supported
    for _step in range(4):
        if game.pending_choices or not game.stack:
            break
        game.resolve_top_of_stack()
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]
    ids = [perm.permanent_id for perm in board]
    assert not game.confirm_keep_permanents(0, ids[:4])
    assert not game.confirm_keep_permanents(0, ids[:6])
    assert game.confirm_keep_permanents(0, ids[:5])
    resolve_stack(game)
    assert _names(game).count("Forest") == 5


def test_w2g1_the_keep_prompt_tells_the_client_the_range_and_what_fills_what(set_pool):
    """Through the real state and action endpoints. The payload carries both
    ends of the range, how many each slot needs of this seat, and which slots
    each candidate may stand for — so the modal can label the Tropical Island
    "Island / Forest" and enable the button on one land. The one-land answer is
    a 200; an answer leaving the Island out is a 400 and moves nothing."""
    from fastapi.testclient import TestClient

    from web.app import app, store

    client = TestClient(app)
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "W2G1", "host_colors": 2,
        "guest_colors": 2, "seed": 2101,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    session = store.get(session_id)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    game.players[0].hand[:] = [set_pool("INV")["Global Ruin"]]
    board = []
    for name in ("Tropical Island", "Forest", "Island", "Mishra's Factory"):
        perm = Permanent(card=_board_card(set_pool, name))
        game._put_permanent_onto_battlefield(0, perm, None)
        board.append(perm)
    tropical, forest, island, _factory = (perm.permanent_id for perm in board)
    game.start_priority_window(0)

    def act(**body):
        return client.post(
            f"/api/sessions/{session_id}/action", json={"seat": 0, **body}
        )

    def prompt():
        return client.get(
            f"/api/sessions/{session_id}/state", params={"seat": 0}
        ).json().get("keep_permanents")

    assert act(action="cast", card_name="Global Ruin").status_code == 200
    assert act(action="pass_priority").status_code == 200
    offered = prompt()
    assert (offered["keep_fewest"], offered["keep_count"]) == (1, 2)
    assert [(slot["type"], slot["need"]) for slot in offered["slots"]] == [
        ("Plains", 0), ("Island", 1), ("Swamp", 0), ("Mountain", 0), ("Forest", 1),
    ]
    assert {entry["name"]: entry["fills"] for entry in offered["candidates"]} == {
        "Tropical Island": [1, 4], "Forest": [4], "Island": [1],
        "Mishra's Factory": [],
    }

    refused = act(action="keep_permanents_confirm", target_permanent_ids=[forest])
    assert refused.status_code == 400
    assert len(list(game.controlled_by(0))) == 4

    assert act(
        action="keep_permanents_confirm", target_permanent_ids=[tropical],
    ).status_code == 200
    assert prompt() is None
    assert _names(game) == ["Tropical Island"]
    assert island not in [perm.permanent_id for perm in game.controlled_by(0)]
