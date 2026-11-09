"""Affinity (CR 702.41) and a cost increase counted per object (CR 601.2f) —
Mirrodin's W1G3, read off invented cards.

The per-card drives are in ``tests/sets/test_mrd_*.py`` (W1G3). This file holds
the rules themselves, each on a card no set prints, because each is a reading a
second card could carry: the CR 702.41a rewrite over another [text], CR
702.41b's two instances, the support gate that refuses an affinity the rewrite
cannot read (on an instant whose other line compiles, which is the case it
exists for), and the per-each tax's two seats.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.affinity import affinity_sentence, expand_affinity_lines
from engine.cost_modifiers import cast_mana_charge
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

_REMINDER = " (This spell costs {1} less to cast for each artifact you control.)"


def _artifact(name="Test Trinket"):
    return _mk_card(name=name, mana_cost="{1}", type_line="Artifact", oracle_text="")


def _table(*permanents_by_seat, hand=()):
    game = Game(players=[
        PlayerState(name="A", hand=list(hand)), PlayerState(name="B"),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    for seat, cards in enumerate(permanents_by_seat):
        for card in cards:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    return game


@pytest.mark.cr("702.41a")
def test_affinity_means_one_less_for_each_object_its_text_names():
    """"'Affinity for [text]' means 'This spell costs {1} less to cast for each
    [text] you control.'" The keyword line becomes that sentence, its plural
    [text] counted one at a time — and the reminder text is not read: a line
    whose reminder said something else would still cost what the keyword says
    (CR 207.2a). A [text] naming a land type counts that type."""
    assert affinity_sentence("Affinity for artifacts" + _REMINDER) == (
        "This spell costs {1} less to cast for each artifact you control."
    )
    assert affinity_sentence(
        "Affinity for artifacts (This spell costs {9} less to cast.)"
    ) == "This spell costs {1} less to cast for each artifact you control."
    assert affinity_sentence("Affinity for Plains") == (
        "This spell costs {1} less to cast for each Plains you control."
    )

    golem = _mk_card(
        name="Plains Golem", mana_cost="{5}", type_line="Artifact Creature — Golem",
        oracle_text="Affinity for Plains",
    )
    assert compile_card_oracle(golem).supported
    plains = _mk_card(name="Plains", type_line="Basic Land — Plains", produced_mana=("W",))
    game = _table([plains, plains, _artifact()])
    assert cast_mana_charge(game, 0, golem).get("generic") == 3


@pytest.mark.cr("702.41b", "601.2f")
def test_each_instance_of_affinity_applies():
    """"If a spell has multiple instances of affinity, each of them applies."
    A {6} artifact printing it twice costs {2} less per artifact: with two
    artifacts it is {2}, and with three it is {0} — the cost cannot go below
    nothing (CR 601.2f) — and it is cast from an empty pool."""
    twice = _mk_card(
        name="Twice-Affine Golem", mana_cost="{6}", type_line="Artifact Creature — Golem",
        oracle_text="Affinity for artifacts\nAffinity for artifacts",
    )
    assert compile_card_oracle(twice).supported
    game = _table([_artifact(), _artifact()])
    assert cast_mana_charge(game, 0, twice).get("generic") == 2
    game = _table([_artifact(), _artifact(), _artifact()], hand=[twice])
    assert cast_mana_charge(game, 0, twice).get("generic") == 0
    cast = game.cast_from_hand(0, "Twice-Affine Golem")
    assert cast.supported, cast.details
    resolve_stack(game)
    assert any(p.card.name == "Twice-Affine Golem" for p in game.controlled_by(0))


@pytest.mark.cr("702.41a")
def test_an_affinity_the_rewrite_cannot_read_leaves_the_card_unsupported():
    """A [text] the vocabulary cannot count is left as printed, and the support
    gate names it — on an instant whose other line compiles, too, which is
    exactly how Thoughtcast reported supported with its keyword dropped before
    the rewrite existed. A grant of affinity in a sentence is not the card's
    own keyword line and is not rewritten."""
    assert affinity_sentence("Affinity for blorbs") is None
    spell = _mk_card(
        name="Blorb Insight", mana_cost="{4}{U}", type_line="Instant",
        oracle_text="Affinity for blorbs\nDraw two cards.",
    )
    program = compile_card_oracle(spell)
    assert not program.supported
    assert "unimplemented affinity: Affinity for blorbs" in program.reason
    granted = "Artifact creatures you control have affinity for artifacts."
    assert expand_affinity_lines(granted) == granted


@pytest.mark.cr("601.2f", "405.4", "109.5")
def test_a_per_each_tax_counts_the_seat_its_words_name():
    """"Each artifact spell costs {1} more to cast for each artifact **its
    controller** controls" counts the spell's controller's artifacts (CR 405.4:
    the player who cast it); "Artifact spells cost {1} less to cast for each
    artifact **you** control" counts the permanent's controller's (CR 109.5:
    "you" on an object is its controller) — so the
    same opponent's artifact spell is discounted by the permanent's board, not
    its own."""
    hum = _mk_card(
        name="Test Hum", mana_cost="{2}", type_line="Enchantment",
        oracle_text=(
            "Each artifact spell costs {1} more to cast for each artifact its "
            "controller controls."
        ),
    )
    rebate = _mk_card(
        name="Test Rebate", mana_cost="{2}", type_line="Enchantment",
        oracle_text="Artifact spells cost {1} less to cast for each artifact you control.",
    )
    assert compile_card_oracle(hum).supported and compile_card_oracle(rebate).supported
    spell = _mk_card(name="Test Widget", mana_cost="{4}", type_line="Artifact", oracle_text="")

    game = _table([hum], [_artifact(), _artifact(), _artifact()])
    assert cast_mana_charge(game, 1, spell).get("generic") == 7
    assert cast_mana_charge(game, 0, spell).get("generic") == 4

    game = _table([rebate, _artifact(), _artifact()], [_artifact()])
    assert cast_mana_charge(game, 1, spell).get("generic") == 2
    assert cast_mana_charge(game, 0, spell).get("generic") == 2
