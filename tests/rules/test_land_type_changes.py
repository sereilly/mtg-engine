"""Tests for Magic: The Gathering Comprehensive Rules Section 305.

Covers:
  305.7  — setting a land's subtype replaces its old land types
  613.1d — layer 4: type-changing effects

The engine records a land-type change as ``land_type_override`` metadata, which
CR 613 layer 4 turns into a subtype *replacement*. That part was right. What was
wrong is that seven readers went around the layer system and asked the raw
metadata (or the printed type line) themselves, and they did not all agree with
it — or with each other.

These use an override rather than casting Magical Hack / Phantasmal Terrain so
the rule is tested rather than one card's path to it.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent


@pytest.fixture(scope="module")
def catalog():
    return {c.name: c for c in load_catalog()}


def _game(*battlefield, hand=()):
    p1 = PlayerState(name="P1", hand=list(hand))
    p2 = PlayerState(name="P2", battlefield=list(battlefield))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


@pytest.mark.cr("305.7")
def test_305_7_a_changed_land_loses_its_printed_type(catalog):
    mountain = Permanent(card=catalog["Mountain"])
    _game(mountain)
    assert mountain.has_type("mountain") is True

    mountain.metadata["land_type_override"] = "island"

    assert mountain.has_type("island") is True
    assert mountain.has_type("mountain") is False


@pytest.mark.cr("305.7")
def test_305_7_targeting_respects_the_replacement(catalog):
    """A Mountain turned into an Island is not a legal "target Mountain". The
    legality check matched *printed type OR override*, so it was both at once."""
    mountain = Permanent(card=catalog["Mountain"])
    game, _, _ = _game(mountain)
    spec = {"land_filter": "mountain"}

    assert game._permanent_matches_target_kind(mountain, "divided", spec, False) is True

    mountain.metadata["land_type_override"] = "island"

    assert game._permanent_matches_target_kind(mountain, "divided", spec, False) is False
    assert game._permanent_matches_target_kind(
        mountain, "divided", {"land_filter": "island"}, False
    ) is True


@pytest.mark.cr("305.7")
def test_305_7_mass_destruction_follows_the_current_type(catalog):
    """Tsunami destroys Islands. A Forest turned into an Island is an Island."""
    forest = Permanent(card=catalog["Forest"])
    forest.metadata["land_type_override"] = "island"
    plain_forest = Permanent(card=catalog["Forest"])
    game, p1, p2 = _game(forest, plain_forest, hand=[catalog["Tsunami"]])

    game.cast_from_hand(0, "Tsunami")

    survivors = [p for p in p2.battlefield]
    assert len(survivors) == 1
    assert survivors[0] is plain_forest


@pytest.mark.cr("305.7")
def test_305_7_flashfires_destroys_plains_at_all():
    """Regression: the handler stripped a trailing "s" from the named type, so
    "Plains" became "plain" — a subtype no land has. The old substring match hid
    it, because "plain" is a substring of "plains"."""
    from engine.static_bonuses import singular_land_type

    assert singular_land_type("plains") == "plains"
    assert singular_land_type("islands") == "island"
    assert singular_land_type("mountains") == "mountain"
    assert singular_land_type("forests") == "forest"
    assert singular_land_type("swamps") == "swamp"


@pytest.mark.cr("305.7")
def test_305_7_flashfires_destroys_plains_in_play(catalog):
    plains = Permanent(card=catalog["Plains"])
    forest = Permanent(card=catalog["Forest"])
    game, p1, p2 = _game(plains, forest, hand=[catalog["Flashfires"]])

    game.cast_from_hand(0, "Flashfires")

    assert [p.card.name for p in p2.battlefield] == ["Forest"]


@pytest.mark.cr("702.14b")
def test_702_14b_landwalk_reads_the_current_land_type(catalog):
    """Islandwalk is beaten by the defender controlling an Island — including
    a Forest that has been turned into one."""
    from tests.helpers import _nosick

    # Fishliver Oil grants islandwalk; the Aura is what makes this a real board
    # rather than a stamped flag.
    attacker = _nosick(Permanent(card=catalog["Grizzly Bears"]))
    blocker = _nosick(Permanent(card=catalog["Grizzly Bears"]))
    forest = Permanent(card=catalog["Forest"])
    p1 = PlayerState(
        name="P1", hand=[catalog["Fishliver Oil"]], battlefield=[attacker]
    )
    p2 = PlayerState(name="P2", battlefield=[blocker, forest])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Fishliver Oil", target_player_index=0, target_permanent_index=0)
    assert game._has_keyword(attacker, "islandwalk") is True

    # A Forest is no obstacle to islandwalk.
    assert game._can_block_attacker(blocker, attacker) is True

    forest.metadata["land_type_override"] = "island"

    assert game._can_block_attacker(blocker, attacker) is False
