"""Tests for Magic: The Gathering Comprehensive Rules Section 701.

Covers:
  701.7a — destroy: move a permanent to its owner's graveyard
  701.19 — regenerate replaces destruction, unless the effect forbids it

"Destroy all <types>" was four handlers with identical bodies differing only in
which types qualify and whether regeneration may replace the destruction. That
shape costs a fifth handler for every new noun a card names — "destroy all
artifacts" (Shatterstorm) was exactly that fifth. The types and the
regeneration flag are parameters now.

Types are asked of the layer system, so a Copy Artifact copy counts as both of
its types and an animated land counts as a creature.
"""

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle


@pytest.fixture(scope="module")
def catalog():
    return {c.name: c for c in load_catalog()}


def _sweeper(catalog, name, text):
    return dataclasses.replace(
        catalog["Shatter"], name=name, mana_cost="{2}{R}{R}", cmc=4.0, oracle_text=text
    )


@pytest.mark.cr("701.7a")
def test_701_7a_destroy_all_artifacts_sweeps_both_battlefields(catalog):
    """Shatterstorm's text. It had no handler at all, so the card compiled to a
    bare pattern marker and would have resolved as a no-op."""
    card = _sweeper(catalog, "Shatterstorm", "Destroy all artifacts. They can't be regenerated.")
    program = compile_card_oracle(card)
    assert program.supported
    assert any(i.kind == "destroy_all_artifacts" for i in program.instructions)

    mine = [Permanent(card=catalog["Sol Ring"]), Permanent(card=catalog["Black Lotus"])]
    theirs = [Permanent(card=catalog["Jayemdae Tome"]), Permanent(card=catalog["Grizzly Bears"])]
    p1 = PlayerState(name="P1", hand=[card], battlefield=mine)
    p2 = PlayerState(name="P2", battlefield=theirs)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Shatterstorm")

    assert p1.battlefield == []
    assert [p.card.name for p in p2.battlefield] == ["Grizzly Bears"]


@pytest.mark.cr("701.19")
def test_701_19_they_cant_be_regenerated_is_payload_not_a_separate_kind(catalog):
    """The rider is data on the instruction, so the same sweep serves both the
    regeneratable and non-regeneratable printings of a template."""
    plain = compile_card_oracle(_sweeper(catalog, "Sweep A", "Destroy all artifacts."))
    rider = compile_card_oracle(
        _sweeper(catalog, "Sweep B", "Destroy all artifacts. They can't be regenerated.")
    )
    got_plain = next(i for i in plain.instructions if i.kind == "destroy_all_artifacts")
    got_rider = next(i for i in rider.instructions if i.kind == "destroy_all_artifacts")

    assert not got_plain.payload.get("bypass_regeneration")
    assert got_rider.payload.get("bypass_regeneration") is True


@pytest.mark.cr("701.7a")
def test_701_7a_an_animated_land_is_swept_by_destroy_all_creatures(catalog):
    """The sweep asks is_creature (CR 613 layer 4), not the printed type line,
    so Kormus Bell's Swamps die to a creature sweep."""
    swamp = Permanent(card=catalog["Swamp"])
    bell = Permanent(card=catalog["Kormus Bell"])
    card = _sweeper(catalog, "Sweep C", "Destroy all creatures.")
    p1 = PlayerState(name="P1", hand=[card], battlefield=[swamp, bell])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert swamp.is_creature is True

    game.cast_from_hand(0, "Sweep C")

    assert not any(p is swamp for p in p1.battlefield)
    assert any(p is bell for p in p1.battlefield)   # the Bell is not a creature


@pytest.mark.cr("701.7a")
def test_701_7a_every_sweep_kind_is_registered(catalog):
    """Each kind in the table must have a handler: the consolidation registers
    one function under several kinds, and a kind added to the table without the
    registration loop seeing it would be a silent no-op."""
    from engine.handlers import EFFECT_HANDLERS
    from engine.handlers.destruction import _SWEEP_TYPES

    for kind in _SWEEP_TYPES:
        assert kind in EFFECT_HANDLERS, kind
