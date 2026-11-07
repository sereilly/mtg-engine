"""A creature is not cast into a board-wide static that kills it (kg4 aivalue).

A permanent's cast is scored by what it is (``ai_scoring._score_cast``) and
rehearsed before it is proposed only where the board sizes its body: a ``*``
toughness (``body_needs_the_board``, W1G4's Ancient Ooze). A **printed**
toughness was never asked about, so Llanowar Elves was cast with a Kaervek,
the Spiteful ("Other creatures get -1/-1") on either side of the table — a
0/0 that goes straight to the graveyard (CR 704.5f) — and a seat's own
Kaervek was cast beside the Elves it kills. The cast of a creature under a
static that lowers toughness, and of a permanent carrying one, is now
rehearsed first (``ai_scoring.arrival_needs_the_board``).

The census asks the layer system which statics kill which creature, not the
policy's reader: every supported permanent of both manifest roles is put on
each side of a board beside a 1-toughness creature of each colour, and the
sources that take it to 0 are the class. Validated backwards: with the gate
answering False (the base), every such cast is proposed.
"""

from __future__ import annotations

from unittest import mock

import pytest

from engine import ai_casts
from engine.ai_policy import choose_cast_action
from engine.ai_valuation import lowers_toughness
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick

#: One creature of toughness 1 per colour, the bodies a -1/-1 kills.
_VICTIMS = (
    "Savannah Lions", "Merfolk of the Pearl Trident", "Drudge Skeletons",
    "Raging Goblin", "Llanowar Elves",
)


@pytest.fixture(scope="module")
def pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    found: dict = {}
    for card in compilation_units(cards):
        found.setdefault(card.name, card)
    return found


def _table(pool, own, other, hand) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat, names in ((0, own), (1, other)):
        for name in names:
            game.players[seat].battlefield.append(_nosick(Permanent(card=pool[name])))
    for player in game.players:
        player.library = [pool["Island"]] * 10
    game.players[0].hand = [pool[name] for name in hand]
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return game


def _dies_there(pool, source: str, side: int, victim: str) -> bool:
    """The layer system's answer: *victim* on seat 0's battlefield beside
    *source* on *side*'s, toughness 0 or less."""
    own = [source] if side == 0 else []
    other = [source] if side == 1 else []
    game = _table(pool, [*own, victim], other, [])
    body = next(p for p in game.players[0].battlefield if p.card.name == victim)
    return body.effective_toughness <= 0


def _killing_sources(pool) -> list:
    rows = []
    for name, card in sorted(pool.items()):
        if card.primary_type in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or not program.static_lines:
            continue
        for side in (0, 1):
            for victim in _VICTIMS:
                if _dies_there(pool, name, side, victim):
                    rows.append((name, side, victim))
    return rows


def _census(pool) -> dict:
    found = {"examined": [], "cast_to_die": []}
    for source, side, victim in _killing_sources(pool):
        found["examined"].append((source, side, victim))
        own = [source] if side == 0 else []
        other = [source] if side == 1 else []
        game = _table(pool, own, other, [victim])
        action = choose_cast_action(game, 0)
        if action is not None and action.card_name == victim:
            found["cast_to_die"].append((source, side, victim))
    return found


def test_no_creature_is_cast_into_a_static_that_kills_it(pool):
    found = _census(pool)
    assert found["cast_to_die"] == [], found["cast_to_die"]
    sources = {source for source, _side, _victim in found["examined"]}
    # Floors: how much the census read (Kaervek, Ascendant Evincar, Urborg
    # Shambler, Stronghold Taskmaster on the base), on both sides.
    assert len(sources) >= 4, sorted(sources)
    assert {side for _source, side, _victim in found["examined"]} == {0, 1}
    # The policy's reader reads every source the layer system found.
    assert all(lowers_toughness(pool[source]) for source in sources), sorted(sources)


@pytest.mark.full
def test_without_the_gate_the_census_finds_every_cast(pool):
    """Backwards: ``arrival_needs_the_board`` answering False, as on 313bd09d."""
    with mock.patch.object(ai_casts, "arrival_needs_the_board", lambda game, card: False):
        found = _census(pool)
    assert len(found["cast_to_die"]) == len(found["examined"]) >= 8, found


@pytest.mark.parametrize("side", [0, 1])
def test_llanowar_elves_is_not_cast_into_kaervek(pool, side):
    own = ["Kaervek, the Spiteful"] if side == 0 else []
    other = ["Kaervek, the Spiteful"] if side == 1 else []
    game = _table(pool, own, other, ["Llanowar Elves"])
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Llanowar Elves"


def test_a_body_the_static_shrinks_but_spares_is_still_cast(pool):
    """Grizzly Bears under Kaervek is a 1/1: it stays, and is proposed."""
    game = _table(pool, [], ["Kaervek, the Spiteful"], ["Grizzly Bears"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Grizzly Bears"


def test_kaervek_is_not_cast_to_kill_more_of_its_own_than_it_is_worth(pool):
    """Its own static is a sweep of its controller's small creatures too: with
    four Llanowar Elves beside it the cast leaves the seat behind; with the
    Elves on the other side it is cast."""
    game = _table(pool, ["Llanowar Elves"] * 4, [], ["Kaervek, the Spiteful"])
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Kaervek, the Spiteful"
    game = _table(pool, [], ["Llanowar Elves"] * 4, ["Kaervek, the Spiteful"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Kaervek, the Spiteful"
    assert action.target_player_index == 0
