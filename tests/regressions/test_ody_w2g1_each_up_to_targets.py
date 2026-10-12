"""Two leftovers of "…to each of **up to** three targets" (Shower of Coals).

**A cast naming nobody.** CR 115.6: "A spell or ability that requires targets
may allow zero targets to be chosen. Such a spell or ability is still said to
require targets, but that spell or ability is targeted only if one or more
targets have been chosen for it." The division gate refused it ("a divided
spell must have at least one target") — CR 601.2d's floor, which is about a
spell that *divides*, and this one hands every target the whole amount. And
letting it through the gate was only half: with no list on the stack object
the damage handler fell through to its single-target path, whose default is
the opposing player's face, so a spell that targeted nothing dealt 2 to a
player. The announcement is written down as the empty list it is and the
resolution reads it (``divided_damage.announced_no_targets``).

**The number an entry carried.** Each entry of an ``EACH`` list was stamped at
the cast with "the whole amount" — for this card the replacing arm's 4, on a
board where it would deal 2. ``divide`` never read it for ``EACH`` (the amount
is the resolving instruction's, CR 608.2h), so the stamp said nothing true and
was asked nothing: it is no longer written. And the picker's
``division_total`` — what the AI and a client are told each target takes — is
the arm the board selects now (``legality._size_conditional_division``).

``oracle_diff`` is blind to all of it; the census below is over every card in
either manifest role whose spell divides, with a floor.
"""
from __future__ import annotations

from functools import lru_cache

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.divided_damage import (
    EACH, FIXED, announced_no_targets, divided_description, divided_entry,
    divided_entry_id,
)
from engine.faces import compilation_units, whole_card
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import chosen_targets
from engine.targeting import derive_cast_spec
from web.app import app, store

client = TestClient(app)


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


def _board(name: str, graveyard: int = 0) -> tuple[Game, Permanent, Permanent]:
    by_name = _pool()
    game = Game(players=[
        PlayerState(name="P1", library=[by_name["Forest"]] * 10),
        PlayerState(name="P2", library=[by_name["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    bears = Permanent(card=by_name["Grizzly Bears"])
    giant = Permanent(card=by_name["Hill Giant"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    game.players[0].hand.append(by_name[name])
    game.players[0].graveyard.extend([by_name["Forest"]] * graveyard)
    return game, bears, giant


def _untouched(game, bears, giant) -> bool:
    return (
        [player.life for player in game.players] == [20, 20]
        and game.is_on_battlefield(bears) and game.is_on_battlefield(giant)
    )


# ---------------------------------------------------------------------------
# Naming nobody
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("graveyard", [0, 7])
@pytest.mark.parametrize("announcement", [
    {},                                                  # nothing said at all
    {"divided_targets": []},                             # an explicit empty list
    {"divided_targets": [], "target_player_index": 1},   # …beside the seat a wire cast carries
])
def test_each_of_up_to_three_targets_may_name_nobody(graveyard, announcement):
    game, bears, giant = _board("Shower of Coals", graveyard)

    queued = game.queue_from_hand(0, "Shower of Coals", **announcement)
    assert queued.supported, queued.details
    item = game.stack[-1]
    # A spell that chose no target has none: no seat, no list, nothing for a
    # "becomes the target" reader to find.
    assert item.target_player_index is None
    assert item.choices["divided_targets"] == []
    assert chosen_targets(game, item) == ()
    assert announced_no_targets(
        item.choices["divided_targets"],
        divided_description(compile_card_oracle(item.card).instructions)[1],
    )

    assert game.resolve_top_of_stack()
    game._settle()
    assert _untouched(game, bears, giant), game.log[-4:]
    assert any("was cast with no targets" in line for line in game.log)
    assert [card.name for card in game.players[0].graveyard][-1] == "Shower of Coals"


@pytest.mark.parametrize("graveyard, each", [(0, 2), (7, 4)])
def test_a_seat_named_the_older_way_is_still_one_target(graveyard, each):
    """``target_player_index`` alone is the single-target announcement every
    scripted caller makes, and stays one: the face takes the whole amount."""
    game, bears, giant = _board("Shower of Coals", graveyard)
    assert game.cast_from_hand(0, "Shower of Coals", target_player_index=1).supported
    assert game.players[1].life == 20 - each
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(giant)


def test_the_cast_route_forwards_an_empty_list_as_nobody():
    """Over the wire every cast carries a default seat, so "nobody" has to be
    said: ``divided_targets: []``. An absent field is the older announcement."""
    by_name = _pool()

    def session():
        created = client.post("/api/sessions", json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4242,
        }).json()
        sid = created["session_id"]
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
        live = store.get(sid)
        game = live.game
        game.enforce_mana_costs = False
        game.players[0].battlefield, game.players[1].battlefield = [], []
        game.players[0].hand = [by_name["Shower of Coals"]]
        game.players[0].graveyard = []
        game.players[0].life = game.players[1].life = 20
        live.current_turn = 0
        game.active_player_index = 0
        game.current_phase = "main"
        game.current_turn_phase, game.current_step = "precombat_main", None
        game.start_priority_window(0)
        return sid, game

    sid, game = session()
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Shower of Coals",
        "divided_targets": [],
    })
    assert response.status_code == 200, response.text
    assert game.stack[-1].choices["divided_targets"] == []
    assert game.stack[-1].target_player_index is None

    sid, game = session()
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Shower of Coals",
    })
    assert response.status_code == 200, response.text
    assert game.stack[-1].target_player_index == 1


def test_only_an_each_list_with_a_ceiling_may_name_nobody():
    """The census: every divided spell in the pool, cast naming nobody. The
    one that may is the one that prints "each of up to N targets"; a spell
    that *divides* needs one or more (CR 601.2d), and one that prints its
    count needs that many (CR 601.2c)."""
    by_name = _pool()
    examined, may, wrong = 0, [], []
    for unit in sorted(compilation_units(by_name.values()), key=lambda u: u.name):
        program = compile_card_oracle(unit)
        if not program.supported or unit.primary_type not in ("instant", "sorcery"):
            continue
        found = divided_description(program.instructions)
        if found is None:
            continue
        examined += 1
        described = found[1]
        expected = described.get("division") == EACH and "max_targets" in described
        game, bears, giant = _board("Forest")
        game.players[0].hand = [whole_card(unit)]
        game.players[0].graveyard.extend([by_name["Grizzly Bears"]] * 3)
        try:
            result = game.cast_from_hand(0, unit.name, divided_targets=[], x_value=2)
        except Exception as error:  # noqa: BLE001
            wrong.append(f"{unit.name}: {error}")
            continue
        if result.supported:
            may.append(unit.name)
        if bool(result.supported) != expected:
            wrong.append(f"{unit.name}: {result.details}")
        elif result.supported and not _untouched(game, bears, giant):
            wrong.append(f"{unit.name}: named nobody and something was hit")
    assert not wrong, wrong
    assert may == ["Shower of Coals"], may
    # Measured: 27 divided instants and sorceries across both roles.
    assert examined >= 25, examined


# ---------------------------------------------------------------------------
# What an entry carries
# ---------------------------------------------------------------------------

def test_an_each_entry_carries_its_target_and_no_share():
    """The id rides the entry (CR 400.7); the amount does not — the card
    supplies it as the spell resolves."""
    for graveyard in (0, 7):
        game, bears, giant = _board("Shower of Coals", graveyard)
        assert game.queue_from_hand(
            0, "Shower of Coals", divided_targets=[(1, None), (1, 0), (1, 1)],
        ).supported
        entries = game.stack[-1].choices["divided_targets"]
        assert [divided_entry(entry) for entry in entries] == [
            (1, None, None), (1, 0, None), (1, 1, None),
        ]
        assert [divided_entry_id(entry) for entry in entries] == [
            None, bears.permanent_id, giant.permanent_id,
        ]
        assert game.resolve_top_of_stack()
        game._settle()
        each = 4 if graveyard >= 7 else 2
        assert game.players[1].life == 20 - each
        assert not game.is_on_battlefield(bears)
        assert game.is_on_battlefield(giant) is (each < 3)


def test_a_printed_share_still_rides_its_target():
    """``FIXED`` is the division whose stamp *is* the printed share: Cone of
    Flame's 1, 2 and 3 are written onto the announcement as before."""
    game, bears, giant = _board("Cone of Flame")
    assert game.queue_from_hand(
        0, "Cone of Flame", divided_targets=[(1, 0), (1, 1), (1, None)],
    ).supported
    described = divided_description(
        compile_card_oracle(_pool()["Cone of Flame"]).instructions
    )[1]
    assert described["division"] == FIXED
    assert [
        divided_entry(entry)[2] for entry in game.stack[-1].choices["divided_targets"]
    ] == [1, 2, 3]


def test_firestorm_still_deals_x_to_each_of_x_targets():
    """The other ``EACH`` card in the pool, whose entries were stamped X: it
    resolves as it did with nothing stamped."""
    by_name = _pool()
    game, bears, giant = _board("Firestorm")
    game.players[0].hand.extend([by_name["Forest"]] * 2)
    assert game.cast_from_hand(
        0, "Firestorm", x_value=2, divided_targets=[(1, 0), (1, None)],
    ).supported
    assert game.players[1].life == 18
    assert not game.is_on_battlefield(bears) and game.is_on_battlefield(giant)


# ---------------------------------------------------------------------------
# What the picker says each target takes
# ---------------------------------------------------------------------------

def test_the_spec_sizes_a_conditional_division_by_the_board_as_it_stands():
    card = _pool()["Shower of Coals"]
    # The card alone cannot say: the replacing arm's amount, as it always was.
    assert derive_cast_spec(card, compile_card_oracle(card))["division_total"] == 4
    for graveyard, each in ((0, 2), (6, 2), (7, 4), (9, 4)):
        game, _bears, _giant = _board("Shower of Coals", graveyard)
        spec = game.cast_target_spec(0, card)
        assert (spec["division"], spec["max_targets"]) == ("each", 3)
        assert spec["division_total"] == each, graveyard
    # The opponent's graveyard is not "your graveyard".
    game, _bears, _giant = _board("Shower of Coals", 0)
    game.players[1].graveyard.extend([_pool()["Forest"]] * 9)
    assert game.cast_target_spec(0, card)["division_total"] == 2
