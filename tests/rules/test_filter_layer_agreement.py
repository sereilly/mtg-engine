"""Tests for Magic: The Gathering Comprehensive Rules Section 613.

Covers:
  613.1d — Layer 4: type-changing effects

The engine has one shared filter matcher (``permanent_matches_filter``) whose
whole purpose is that every consumer agrees about what a filter means. These
pin it against the layer system, which is the authority on an object's current
types.
"""

import pytest

from engine import Game, PlayerState
from engine.land_types import change_land_type
from engine.models import CardDefinition, Permanent


def _land_card(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0,
        type_line=f"Basic Land — {name}", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": f"Basic Land — {name}"},
    )

@pytest.mark.cr("613.1d")
def test_613_1d_a_filter_reads_the_layer_4_subtype_not_the_printed_line():
    """One source of truth for "is this a Swamp?".

    ``permanent_matches_filter`` is documented as the shared matcher so
    destroy-target resolution, cast validation and the legality enumerator can
    never disagree about what a filter means — but its subtype test read the
    *printed* type line while ``has_type`` computes through layer 4. A land
    turned into a Swamp (Magical Hack, Phantasmal Terrain, Evil Presence) was
    therefore a Swamp to the rules engine and an Island to every filter.

    No card in the current pool filters on a basic land subtype, so this was
    unreachable — and would have shipped as a live bug with the first card that
    did.
    """
    from engine.handlers._common import permanent_matches_filter

    player, opponent = PlayerState(name="A"), PlayerState(name="B")
    island = Permanent(card=_land_card("Island"))
    player.battlefield.append(island)
    game = Game(players=[player, opponent])
    game.enforce_mana_costs = False

    swamp_filter = {"type_filter": "land", "subtype_filter": "swamp"}
    island_filter = {"type_filter": "land", "subtype_filter": "island"}
    assert permanent_matches_filter(island, swamp_filter) is False
    assert permanent_matches_filter(island, island_filter) is True

    change_land_type(island, "swamp", source="test")

    assert island.has_type("swamp") is True
    assert island.has_type("island") is False
    # The filter must now agree with has_type in both directions.
    assert permanent_matches_filter(island, swamp_filter) is True
    assert permanent_matches_filter(island, island_filter) is False
