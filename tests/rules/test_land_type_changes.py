"""Tests for Magic: The Gathering Comprehensive Rules Section 305.

Covers:
  305.7  — setting a land's subtype replaces its old land types
  613.1d — layer 4: type-changing effects

The engine records a land-type change as a contribution
(``engine/land_types.py``), which CR 613 layer 4 turns into a subtype
*replacement*. That part was always right. What was wrong is that seven readers
went around the layer system and asked the storage (or the printed type line)
themselves, and they did not all agree with it — or with each other.

These record the change directly rather than casting Magical Hack / Phantasmal
Terrain, so the rule is tested rather than one card's path to it.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.land_types import change_land_type
from engine.models import CardDefinition, Permanent


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

    change_land_type(mountain, "island", source="test")

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

    change_land_type(mountain, "island", source="test")

    assert game._permanent_matches_target_kind(mountain, "divided", spec, False) is False
    assert game._permanent_matches_target_kind(
        mountain, "divided", {"land_filter": "island"}, False
    ) is True


@pytest.mark.cr("305.7")
def test_305_7_mass_destruction_follows_the_current_type(catalog):
    """Tsunami destroys Islands. A Forest turned into an Island is an Island."""
    forest = Permanent(card=catalog["Forest"])
    change_land_type(forest, "island", source="test")
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

    change_land_type(forest, "island", source="test")

    assert game._can_block_attacker(blocker, attacker) is False


# ---------------------------------------------------------------------------
# 613.7 — two of these on one land, and what happens when one ends
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.7", "305.7")
def test_613_7_two_land_type_changes_resolve_in_timestamp_order(catalog):
    """**Type changes do not commute.** CR 305.7 makes each one a *replacement*,
    so what the land is is whatever the newest effect says — and the reverse
    order gives the other answer. A single stamped value could record only one
    of them, so which survived was whichever code path happened to write last.
    """
    from engine.land_types import LAND_TYPE_EFFECTS

    forest = Permanent(card=catalog["Forest"])
    _game(forest)
    change_land_type(forest, "island", source="first")
    change_land_type(forest, "swamp", source="second")
    assert forest.basic_land_types == ("swamp",)

    other = Permanent(card=catalog["Forest"])
    _game(other)
    change_land_type(other, "swamp", source="first")
    change_land_type(other, "island", source="second")
    assert other.basic_land_types == ("island",)

    # And it is the *timestamps* deciding, not the order the contributions
    # happen to sit in. Storage order is not sorted on the way out precisely so
    # that this can be asked: reversed, the answer must not move.
    other.metadata[LAND_TYPE_EFFECTS] = list(reversed(other.metadata[LAND_TYPE_EFFECTS]))
    assert other.basic_land_types == ("island",)


@pytest.mark.cr("611.3", "613.7")
def test_611_3_ending_one_change_leaves_the_other_applying(catalog):
    """Removal is dropping *one* contribution. The land goes back to what the
    remaining effects say, not to its printed type — Gaea's Liege's Forest
    ending on a land Evil Presence has made a Swamp leaves a Swamp.
    """
    from engine.land_types import end_land_type_change

    mountain = Permanent(card=catalog["Mountain"])
    _game(mountain)
    change_land_type(mountain, "swamp", source="evil presence")
    change_land_type(mountain, "forest", source="gaea's liege")
    assert mountain.basic_land_types == ("forest",)

    assert end_land_type_change(mountain, source="gaea's liege") is True

    assert mountain.basic_land_types == ("swamp",)
    assert mountain.has_type("mountain") is False


@pytest.mark.cr("613.7b")
def test_613_7b_re_recording_the_same_source_replaces_its_own_contribution(catalog):
    """One effect applies once however often it is re-resolved, and it takes the
    newer timestamp. Appending instead would leave a stale contribution that
    only ordering hid."""
    forest = Permanent(card=catalog["Forest"])
    _game(forest)
    change_land_type(forest, "island", source="aura")
    change_land_type(forest, "swamp", source="aura")

    from engine.land_types import land_type_changes

    assert [c["land_type"] for c in land_type_changes(forest)] == ["swamp"]
    assert forest.basic_land_types == ("swamp",)


@pytest.mark.cr("611.3", "305.7")
def test_611_3_gaeas_liege_leaving_restores_the_aura_type_not_the_printed_one(catalog):
    """The two real cards behind the rule above.

    Evil Presence makes a Mountain a Swamp; Gaea's Liege then makes it a Forest
    "until this creature leaves the battlefield". When the Liege dies its
    contribution is dropped and Evil Presence's is still there, so the land is a
    Swamp — not the Mountain it was printed as. The Liege used to revert by
    reading the stored type back and clearing it if it still said "forest",
    which took Evil Presence's change with it and needed an acknowledgement in
    the layer-read guard to say so.
    """
    from tests.helpers import _nosick

    mountain = Permanent(card=catalog["Mountain"])
    liege = _nosick(Permanent(card=catalog["Gaea's Liege"]))
    # Its power and toughness are the number of Forests its controller has, so
    # without one it is 0/0 and CR 704.5f sweeps it before the test starts.
    p1 = PlayerState(
        name="P1",
        hand=[catalog["Evil Presence"]],
        battlefield=[liege, Permanent(card=catalog["Forest"])],
    )
    p2 = PlayerState(name="P2", battlefield=[mountain])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Evil Presence", target_player_index=1, target_permanent_index=0)
    assert mountain.basic_land_types == ("swamp",)

    game.activate_permanent_ability(
        0, "Gaea's Liege", target_player_index=1, target_permanent_index=0
    )
    assert mountain.basic_land_types == ("forest",)

    game._permanent_to_graveyard(p1, liege)

    assert mountain.basic_land_types == ("swamp",)


# ---------------------------------------------------------------------------
# The static reading: "All <type>s are <type>s." (Conversion)
# ---------------------------------------------------------------------------
#
# Derived by engine/land_types.py from the printed sentence, so a card printed
# with the template needs no code at all. Every property below is pinned with an
# **invented** card: the rule it replaces spelled the five basics into a regex
# and matched with `.search` over the card's whole collapsed text, and a test
# naming only Conversion passes against that.

def _static_card(name: str, oracle_text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Enchantment",
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Enchantment"},
    )


@pytest.mark.cr("305.7", "613.1d")
def test_305_7_a_static_type_change_is_keyed_on_the_line_not_the_card_name(catalog):
    """An invented enchantment with Conversion's template changes the board."""
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(_static_card("Inversion", "All Islands are Swamps."))
    kinds = {instruction.kind: instruction.payload for instruction in program.instructions}

    assert program.supported
    assert kinds["static_land_type_change"] == {"from_type": "island", "to_type": "swamp"}


@pytest.mark.cr("305.7", "613.1d")
def test_305_7_a_static_type_change_applies_to_the_board(catalog):
    """End to end through the layer system, not just the payload."""
    island = Permanent(card=catalog["Island"])
    p1 = PlayerState(name="P1", battlefield=[
        Permanent(card=_static_card("Inversion", "All Islands are Swamps."))
    ])
    p2 = PlayerState(name="P2", battlefield=[island])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()

    assert island.basic_land_types == ("swamp",)


@pytest.mark.cr("305.7")
def test_305_7_an_animation_clause_is_not_read_as_a_bare_type_change():
    """"All Swamps are 1/1 black creatures that are still lands" is the *other*
    template (engine/land_animation.py). Reading it here would drop the body
    and the colour while reporting the line understood."""
    from engine.land_types import static_land_type_change_for

    assert static_land_type_change_for(
        "all swamps are 1/1 black creatures that are still lands"
    ) is None


@pytest.mark.cr("305.7")
def test_305_7_a_type_the_catalog_does_not_know_refuses():
    """The land types come from data/vocabulary, not a list of the five basics —
    so a real subtype outside them works and an invented word does not."""
    from engine.land_types import static_land_type_change_for

    assert static_land_type_change_for("all deserts are islands") is not None
    assert static_land_type_change_for("all wombats are islands") is None


# ---------------------------------------------------------------------------
# CR 305.7's losing half — "it loses all abilities generated from its rules
# text, its old land types, and any copiable effects affecting that land"
# ---------------------------------------------------------------------------
#
# Implemented ten sets after the gaining half. With Blood Moon out, Mishra's
# Factory read as a Mountain and produced {R} — and still animated itself and
# pumped; City of Brass still had its damage trigger. An ability can act three
# ways, so the rule needs three enforcement points, and each is asserted here:
# the keyword (layer 6), the activated ability (the activation gate) and the
# triggered ability (the trigger scan).


@pytest.mark.cr("305.7")
def test_305_7_a_set_land_type_removes_an_activated_ability(catalog):
    factory = Permanent(card=catalog["Mishra's Factory"])
    game, _p1, p2 = _game(factory)
    game.start_turn(1)

    assert game.activate_permanent_ability(1, "Mishra's Factory", permanent_index=0).supported

    change_land_type(factory, "mountain", source="test")
    game._recompute_continuous_effects()

    result = game.activate_permanent_ability(1, "Mishra's Factory", permanent_index=0)
    assert not result.supported
    assert "305.7" in result.details


@pytest.mark.cr("305.7")
def test_305_7_a_set_land_type_removes_a_triggered_ability(catalog):
    city = Permanent(card=catalog["City of Brass"])
    game, _p1, p2 = _game(city)
    game.start_turn(1)
    p2.life = 20

    change_land_type(city, "mountain", source="test")
    game._recompute_continuous_effects()

    p2.mana_pool = {sym: 0 for sym in ("W", "U", "B", "R", "G", "C")}
    game.tap_land_for_mana(1, "City of Brass", permanent_index=0, chosen_color="R")
    game._settle()

    assert p2.life == 20, "the damage trigger came from rules text the change removed"
    assert p2.mana_pool["R"] == 1, "and the new type's mana ability is what it gained"


@pytest.mark.cr("305.7")
def test_305_7_keeps_an_ability_granted_by_another_effect(catalog):
    """"Note that this doesn't remove any abilities that were granted to the
    land by other effects." The removal is built from the *printed* abilities
    for exactly this reason, so a grant made afterwards outlives it."""
    from engine.keywords import grant_keyword

    factory = Permanent(card=catalog["Mishra's Factory"])
    game, _p1, _p2 = _game(factory)

    change_land_type(factory, "mountain", source="test")
    grant_keyword(factory, "flying")
    game._recompute_continuous_effects()

    assert factory.has_keyword("flying")


@pytest.mark.cr("305.7")
def test_305_7_leaves_a_printed_basic_land_alone(catalog):
    """The condition is that an effect *set* the type, not that the land has a
    basic land type — a printed Mountain has lost nothing. Asserted because the
    cheap reading of this rule ("is it a basic type?") is true of both."""
    mountain = Permanent(card=catalog["Mountain"])
    city = Permanent(card=catalog["City of Brass"])
    game, _p1, p2 = _game(mountain, city)
    game.start_turn(1)
    p2.life = 20

    p2.mana_pool = {sym: 0 for sym in ("W", "U", "B", "R", "G", "C")}
    game.tap_land_for_mana(1, "City of Brass", permanent_index=1, chosen_color="R")
    game._settle()

    assert p2.life == 19, "an untouched City of Brass still has its trigger"
