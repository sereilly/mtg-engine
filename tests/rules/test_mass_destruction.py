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
from engine.targeting import derive_cast_spec   # FixC


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


# --- FixC: a sweep names a class, not a target ---
@pytest.mark.cr("115.1a")
def test_115_1a_one_word_decides_whether_a_sweep_is_targeted(catalog):
    """"An instant or sorcery spell is targeted **if** its spell ability
    identifies something it will affect by using the phrase 'target
    [something]'" — so "all black creatures" and "target black creature" are
    the same class named two ways, and only the second is a target.

    One synthetic pair, differing by one word, because that word is the whole
    rule. The engine used to answer the same for both: a sweep's ``type_filter``
    describes the class it affects and a picker's describes the object chosen,
    and the reader could not tell them apart from the payload.
    """
    sweep = _sweeper(catalog, "Sweep D", "Destroy all black creatures.")
    aimed = _sweeper(catalog, "Aimed D", "Destroy target black creature.")

    assert derive_cast_spec(sweep, compile_card_oracle(sweep)) is None
    assert derive_cast_spec(aimed, compile_card_oracle(aimed)) == {
        "kind": "creature", "color_filter": "B",
    }


@pytest.mark.cr("115.1a")
def test_115_1a_a_sweep_is_cast_with_nothing_to_point_at(catalog):
    """The rule as the player meets it. Cleanse names no target, so it is cast
    and resolved with none — on a board holding creatures it could have been
    read as naming, and on one holding nothing at all.

    Both boards matter and the empty one most: the client raises a picker for
    any derived kind but "none" and abandons the cast when that picker has
    nothing to offer, so a spell that reported a target it never chooses was
    uncastable exactly when its controller had swept the board already.
    """
    for battlefield in ([catalog["Bog Imp"], catalog["Savannah Lions"]], []):
        p1 = PlayerState(name="P1", hand=[catalog["Cleanse"]])
        p2 = PlayerState(
            name="P2", battlefield=[Permanent(card=c) for c in battlefield]
        )
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = False
        game._sync_control()

        spec = game.cast_target_spec(0, catalog["Cleanse"])
        assert spec["kind"] == "none"
        assert spec["requires_target"] is False
        assert spec["valid_targets"] == []

        result = game.cast_from_hand(0, "Cleanse")

        assert result.supported, result.details
        # Only the black one dies; the class is the sweep's, not a picker's.
        assert [p.card.name for p in p2.battlefield] == (
            ["Savannah Lions"] if battlefield else []
        )


@pytest.mark.cr("115.1a")
def test_115_1a_wrath_of_god_and_cleanse_agree(catalog):
    """The control. Wrath of God prints the same sentence without a colour and
    answered "none" throughout — its "destroy all creatures" has an instruction
    kind of its own carrying the class in the *name*, so no filter sat in the
    payload to be misread. That the two now agree is the whole fix.
    """
    for name in ("Wrath of God", "Cleanse", "Jokulhaups", "Tivadar's Crusade"):
        card = catalog[name]
        assert derive_cast_spec(card, compile_card_oracle(card)) is None, name
# --- end FixC ---
