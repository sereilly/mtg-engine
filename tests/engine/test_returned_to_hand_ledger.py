""""A permanent was put into your hand from the battlefield this turn" has one
writer, and it is the seam every such move goes through.

Barrin, Tolarian Archmage reads ``Game.permanents_to_hand_this_turn``. The
ledger was bumped **by hand at two call sites** — the bounce helper and the
single targeted bounce — while nine places move a permanent into a hand
through ``Game.put_card_into_hand(..., from_battlefield=…)``, which is where
the "permanent returned to hand" event has always been announced. So a bounce
spell counted and nothing else did: a land Storm Cauldron sent home, an
artifact Hurkyl's Recall swept up, a creature returned as a cost, a Firestorm
Phoenix that would have died, a Rakalite at the end step.

And the two hand-written bumps had one case backwards. "If a token is returned
to your hand, it's put there before it ceases to exist" (Barrin's ruling,
2020-06-23, fetched from Scryfall) — they skipped it, because the seam reports
that no *card* arrived.

The write is in the seam now, at the line that announces the move. This file
is the census — every way in, and whether the ledger saw it — and the guard
that there is still one writer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.game_types import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.tokens import make_token_card
from tests.helpers import resolve_stack

ENGINE = Path(__file__).resolve().parents[2] / "engine"
LEDGER = "permanents_to_hand_this_turn"


def _functions(tree):
    """``(function name, node)`` for every function in *tree*, innermost last."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node


def _ledger_writes(tree):
    """Function names that assign to the ledger or to one of its keys."""
    writers = set()
    for name, function in _functions(tree):
        for node in ast.walk(function):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript):
                    target = target.value
                if isinstance(target, ast.Attribute) and target.attr == LEDGER:
                    writers.add(name)
    return writers


def test_the_ledger_has_one_writer_and_one_reset():
    """An AST scan of ``engine/``. A third function writing the ledger is a
    call site keeping its own count again, which is how this went wrong."""
    found = {}
    for path in sorted(ENGINE.rglob("*.py")):
        writers = _ledger_writes(ast.parse(path.read_text(encoding="utf-8")))
        if writers:
            found[path.relative_to(ENGINE).as_posix()] = sorted(writers)

    assert found == {
        # The seam: where a permanent arriving in a hand is announced.
        "mixins/helpers.py": ["_announce_permanent_returned_to_hand"],
        # The turn's reset.
        "mixins/turn_management.py": ["begin_turn_bookkeeping"],
    }, found


def test_every_way_back_to_a_hand_goes_through_the_counting_seam():
    """The census of ways in: every call under ``engine/`` that hands the hand
    seam the permanent the card is leaving the battlefield *as*. Each of them
    is counted by construction now; two were, before.

    The floor is what makes it a census: a scan that stopped finding the calls
    would report every way covered over none.
    """
    ways = []
    for path in sorted(ENGINE.rglob("*.py")):
        for name, function in _functions(ast.parse(path.read_text(encoding="utf-8"))):
            for node in ast.walk(function):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "put_card_into_hand"
                ):
                    continue
                leaving = next(
                    (k.value for k in node.keywords if k.arg == "from_battlefield"),
                    None,
                )
                if leaving is None or (
                    isinstance(leaving, ast.Constant) and leaving.value is None
                ):
                    continue
                ways.append(f"{path.relative_to(ENGINE).as_posix()}::{name}")

    # Nine on the tree this was written against.
    assert len(ways) >= 9, ways
    for sighting in (
        "handlers/_common.py::return_permanent_to_owners_hand",
        "handlers/returns.py::return_all_owned_artifacts_to_hand",
        "mixins/turn_management.py::_return_tapped_land_to_hand",
        "replacements.py::_return_to_hand_instead_of_dying",
    ):
        assert sighting in ways, (sighting, ways)


# -- the ways that were not counted, driven --------------------------------------


def _card(name: str, type_line: str, text: str = "", **raw) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, **raw},
    )


def _duel(**hands):
    game = Game(players=[
        PlayerState(name="P1", hand=list(hands.get("p1", ()))),
        PlayerState(name="P2", hand=list(hands.get("p2", ()))),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _put(game, seat, card) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def test_a_land_storm_cauldron_sends_home_is_counted(set_pool):
    """"Whenever a land is tapped for mana, return it to its owner's hand.\""""
    game = _duel()
    _put(game, 1, set_pool("ALL")["Storm Cauldron"])
    forest = _put(game, 0, set_pool("LEA")["Forest"])

    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    resolve_stack(game)

    assert [c.name for c in game.players[0].hand] == ["Forest"]
    assert game.permanents_to_hand_this_turn == {0: 1}


def test_artifacts_hurkyls_recall_sweeps_up_are_counted_for_their_owner(set_pool):
    """"Return all artifacts target player owns to their hand." Two of them,
    so two — and to the owner's seat, whoever cast it."""
    lea = set_pool("LEA")
    game = _duel(p2=[set_pool("ATQ")["Hurkyl's Recall"]])
    _put(game, 0, lea["Mox Pearl"])
    _put(game, 0, lea["Sol Ring"])

    assert game.cast_from_hand(1, "Hurkyl's Recall", target_player_index=0).supported
    resolve_stack(game)

    assert sorted(c.name for c in game.players[0].hand) == ["Mox Pearl", "Sol Ring"]
    assert game.permanents_to_hand_this_turn == {0: 2}


def test_a_permanent_returned_as_a_cost_is_counted(set_pool):
    """"{0}: Return this creature to its owner's hand." (Blinking Spirit) and a
    cost that returns *other* permanents: "{U}{U}, Return two Islands you
    control to their owner's hand: …" (Flooded Shoreline)."""
    game = _duel()
    _put(game, 0, set_pool("ICE")["Blinking Spirit"])
    assert game.activate_permanent_ability(0, "Blinking Spirit").supported
    resolve_stack(game)
    assert game.permanents_to_hand_this_turn == {0: 1}

    lea = set_pool("LEA")
    game = _duel()
    _put(game, 0, set_pool("VIS")["Flooded Shoreline"])
    _put(game, 0, lea["Island"])
    _put(game, 0, lea["Island"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    assert game.activate_permanent_ability(
        0, "Flooded Shoreline", target_permanent_ids=[bears.permanent_id],
    ).supported
    resolve_stack(game)

    assert [c.name for c in game.players[0].hand] == ["Island", "Island"]
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert game.permanents_to_hand_this_turn == {0: 2, 1: 1}


def test_a_phoenix_that_would_have_died_is_counted(set_pool):
    """"If this creature would die, return it to its owner's hand instead." A
    replaced death is a permanent put into a hand from the battlefield."""
    game = _duel()
    phoenix = _put(game, 0, set_pool("LEG")["Firestorm Phoenix"])

    game._permanent_to_graveyard(game.players[0], phoenix)
    game.remove_from_battlefield(phoenix)

    assert [c.name for c in game.players[0].hand] == ["Firestorm Phoenix"]
    assert game.players[0].graveyard == []
    assert game.permanents_to_hand_this_turn == {0: 1}


def test_a_bounced_token_is_counted_though_no_card_arrives(set_pool):
    """Barrin's ruling: the token is put into the hand before it ceases to
    exist. The hand-written bumps skipped it, because the seam's answer to
    "did a card arrive?" is no."""
    game = _duel(p2=[set_pool("LEA")["Unsummon"]])
    token = Permanent(card=make_token_card("Bear", 2, 2, "Creature — Bear"))
    token.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(0, token, None)

    assert game.cast_from_hand(
        1, "Unsummon", target_permanent_ids=[token.permanent_id]
    ).supported
    resolve_stack(game)

    assert not game.is_on_battlefield(token)
    assert game.players[0].hand == []
    assert game.permanents_to_hand_this_turn == {0: 1}


def test_a_card_reaching_a_hand_from_anywhere_else_is_not_counted(set_pool):
    """The control: a draw and a return from a graveyard put a card into a hand
    and nothing came from the battlefield."""
    lea = set_pool("LEA")
    game = _duel()
    game.players[0].library = [lea["Forest"]] * 2
    game._draw_with_replacements(game.players[0], 1)
    game.put_card_into_hand(game.players[0], lea["Grizzly Bears"])

    assert len(game.players[0].hand) == 2
    assert game.permanents_to_hand_this_turn == {}


# -- an invented card: Barrin's condition on something that is not Barrin --------


@pytest.mark.parametrize("returned", [True, False])
def test_an_invented_card_reads_the_ledger_for_a_return_no_bounce_spell_made(
    set_pool, returned,
):
    """"At the beginning of your end step, if a permanent was put into your
    hand from the battlefield this turn, you gain 3 life." — fed by a land
    Storm Cauldron returned, a way in that the ledger never saw."""
    warden = _card(
        "Tide Warden", "Creature — Merfolk",
        "At the beginning of your end step, if a permanent was put into your "
        "hand from the battlefield this turn, you gain 3 life.",
        power="1", toughness="3",
    )
    assert compile_card_oracle(warden).supported
    game = _duel()
    game.players[0].library = [set_pool("LEA")["Swamp"]] * 4
    game.players[1].library = [set_pool("LEA")["Swamp"]] * 4
    game.start_turn(0)
    _put(game, 0, warden)
    _put(game, 0, set_pool("ALL")["Storm Cauldron"])
    forest = _put(game, 0, set_pool("LEA")["Forest"])
    if returned:
        assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
        resolve_stack(game)
        game.clear_mana_pools()

    game.resolve_end_step(0)
    resolve_stack(game)

    assert game.players[0].life == (23 if returned else 20), game.log
