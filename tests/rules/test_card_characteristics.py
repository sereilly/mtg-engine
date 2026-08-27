"""CR 105 / 202 / 205 — an object's colours, its mana cost and its types.

Three questions the engine answers from several places, and the reason they are
tested together is that each has a *printed* answer and a *derived* one:

* **Colour** (CR 105) is a set, not a category. "Shares a colour" is a non-empty
  intersection, so a colourless permanent shares one with nothing (CR 105.1:
  there are five colours and colourless is not among them), a gold permanent
  answers to each of its colours (CR 105.2b), and a lace *replaces* the whole
  set rather than adding to it (CR 105.2a). Every one of those is asked of the
  layer-5 answer (``permanent_effective_colors``), never of ``card.colors``.
* **Mana cost** (CR 202) is the one characteristic a card carries in every zone.
  CR 202.1a makes the printed symbols what a player must actually spend, and
  CR 202.3 makes the mana value their total *regardless of colour* — so a board
  can be one short of the total, or hold the total and none of the colours, and
  both refuse.
* **Types** (CR 205) come in three axes that do not interact. A card has *every*
  card type its line names (CR 205.2a/b), so an animated land is simultaneously
  a legal "target land" and a legal "target creature"; a subtype can be replaced
  without the card type moving (CR 205.3i); and a supertype survives a type
  change and is never granted by a subtype (CR 205.4b/c — a Tundra given the
  Swamp land type is still a nonbasic land).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.layer_bridge import displayed_type_line, printed_supertypes
from engine.mana_payment import total_pips
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.search_filters import search_matches
from engine.targeting import derive_activation_spec, derive_cast_spec


def _duel(active: int = 0) -> tuple[Game, PlayerState, PlayerState]:
    """A two-seat game with costs off and seat 0 interactive (the test rig)."""
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = active
    game.interactive_seats = {0}
    return game, p1, p2


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _cast_picker(game: Game, card) -> list[str]:
    """What the UI's picker offers for *card*'s cast-time target.

    The picker rather than the resolution, because the picker is the half that
    has to agree with the rules on what a legal target *is*: a resolution that
    accepts a target nobody can click is not reachable in a real game.
    """
    spec = dict(derive_cast_spec(card, compile_card_oracle(card)) or {})
    kind = spec.pop("kind", None)
    assert kind is not None, f"{card.name} chooses no cast-time target"
    return [entry["name"] for entry in game.enumerate_targets_for_kind(0, card, kind, **spec)]


def _ability_picker(game: Game, perm: Permanent, index: int = 0) -> list[str]:
    """The same question for one activated ability (CR 601.2c's target list)."""
    spec = dict(derive_activation_spec(compile_card_oracle(perm.card).activated_abilities[index]))
    kind = spec.pop("kind")
    return [
        entry["name"]
        for entry in game.enumerate_targets_for_kind(0, perm.card, kind, **spec)
    ]


# ---------------------------------------------------------------------------
# CR 105 — colour
# ---------------------------------------------------------------------------


@pytest.mark.cr("105.1", "105.2c")
def test_a_board_of_only_colourless_permanents_has_no_colors(catalog_by_name):
    """Chromatic Orrery: "Draw a card for each color among permanents you
    control."

    CR 105.1 lists five colours and colourless is not one of them, so a board of
    an artifact and a Mox is a board of *zero* colours. Counting "colourless" as
    a sixth would draw a card here — the reading that makes an artifact board
    look mono-coloured everywhere else too.
    """
    game, p1, _p2 = _duel()
    orrery = _nosick(Permanent(card=catalog_by_name["Chromatic Orrery"]))
    p1.battlefield.append(orrery)
    p1.battlefield.append(Permanent(card=catalog_by_name["Mox Pearl"]))
    p1.library = [catalog_by_name["Forest"]] * 5

    result = game.activate_permanent_ability(0, "Chromatic Orrery", ability_index=1)
    game._settle()

    # The ability really resolved — an empty hand because the draw never
    # happened would prove nothing about colours.
    assert result.supported and result.details == "resolved"
    assert p1.hand == []


@pytest.mark.cr("105.1", "105.2")
def test_each_color_among_permanents_is_counted_once(catalog_by_name):
    """The control, and the other half of the count: the same board plus a green
    creature and a black one draws two. The Mox still contributes nothing, so
    this is a count of colours rather than of coloured permanents."""
    game, p1, _p2 = _duel()
    orrery = _nosick(Permanent(card=catalog_by_name["Chromatic Orrery"]))
    p1.battlefield.append(orrery)
    p1.battlefield.append(Permanent(card=catalog_by_name["Mox Pearl"]))
    p1.battlefield.append(Permanent(card=catalog_by_name["Grizzly Bears"]))
    p1.battlefield.append(Permanent(card=catalog_by_name["Sengir Vampire"]))
    p1.library = [catalog_by_name["Forest"]] * 5

    game.activate_permanent_ability(0, "Chromatic Orrery", ability_index=1)
    game._settle()

    assert len(p1.hand) == 2


@pytest.mark.cr("105.2b", "601.2c")
def test_a_multicolored_permanent_is_each_of_its_colors(catalog_by_name):
    """Northern Paladin destroys "target **black** permanent"; Axelrod Gunnarson
    is {4}{B}{B}{R}{R}, black *and* red.

    CR 105.2b: a multicoloured object is each of those colours, so "black" is a
    property it has and not a bucket it failed to land in. The picker has to
    agree, because a target it does not offer is one no player can choose.
    """
    game, p1, p2 = _duel()
    paladin = _nosick(Permanent(card=catalog_by_name["Northern Paladin"]))
    p1.battlefield.append(paladin)
    axelrod = Permanent(card=catalog_by_name["Axelrod Gunnarson"])
    p2.battlefield.append(axelrod)
    game._settle()

    assert axelrod.effective_colors == {"B", "R"}
    assert _ability_picker(game, paladin) == ["Axelrod Gunnarson"]


@pytest.mark.cr("105.2a", "105.2", "613.1e")
def test_a_lace_replaces_the_whole_color_set(catalog_by_name):
    """Purelace: "Target spell or permanent **becomes** white."

    "Becomes" is a replacement of the set, not an addition to it (CR 105.2a — the
    object is afterwards *monocoloured*), so a black-and-red gold creature that
    has been laced white stops answering "target black permanent" entirely. An
    implementation that added white would leave it black and the Paladin would
    still offer it.
    """
    game, p1, p2 = _duel()
    paladin = _nosick(Permanent(card=catalog_by_name["Northern Paladin"]))
    p1.battlefield.append(paladin)
    axelrod = Permanent(card=catalog_by_name["Axelrod Gunnarson"])
    p2.battlefield.append(axelrod)
    p1.hand = [catalog_by_name["Purelace"]]

    game.cast_from_hand(0, "Purelace", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert axelrod.effective_colors == {"W"}
    assert _ability_picker(game, paladin) == []


def _invoke_prejudice_board(catalog_by_name, guard: str | None):
    """Invoke Prejudice plus an optional guard, with an opponent casting a green
    Grizzly Bears into it. Returns whether the spell resolved."""
    game, p1, p2 = _duel(active=1)
    p1.battlefield.append(Permanent(card=catalog_by_name["Invoke Prejudice"]))
    if guard is not None:
        p1.battlefield.append(Permanent(card=catalog_by_name[guard]))
    p2.hand = [catalog_by_name["Grizzly Bears"]]
    game.cast_from_hand(1, "Grizzly Bears")
    game._settle()
    return game, p1, p2, [perm.card.name for perm in p2.battlefield] == ["Grizzly Bears"]


@pytest.mark.cr("105.2")
def test_a_creature_of_the_spells_color_turns_the_shared_color_trigger_off(catalog_by_name):
    """Invoke Prejudice counters a creature spell "that doesn't share a color
    with a creature you control". A green Grizzly Bears against a green guard
    shares green, so nothing is countered — the baseline the two tests below are
    measured against."""
    _game, _p1, _p2, resolved = _invoke_prejudice_board(catalog_by_name, "Grizzly Bears")

    assert resolved


@pytest.mark.cr("105.1", "105.2c")
def test_a_colorless_creature_shares_a_color_with_nothing(catalog_by_name):
    """The same board with a colourless artifact creature as the only guard.

    CR 105.2c: a colourless object has *no* colour, so the intersection with a
    green spell's colours is empty and the trigger fires. Treating colourless as
    a colour of its own would still leave the intersection empty here — treating
    it as "matches anything", which is what a truthiness test on an empty colour
    set produces, would not.
    """
    _game, _p1, p2, resolved = _invoke_prejudice_board(catalog_by_name, "Ornithopter")

    assert not resolved
    assert [card.name for card in p2.graveyard] == ["Grizzly Bears"]


@pytest.mark.cr("105.2", "613.1e")
def test_sharing_a_color_is_asked_of_the_computed_color(catalog_by_name):
    """The guard is a green Grizzly Bears that Deathlace has made black.

    Same two objects as the baseline test, opposite answer: the comparison reads
    the layer-5 colour of the board, so a guard whose colour was changed stops
    protecting the spell that used to share it.
    """
    game, p1, p2 = _duel(active=1)
    p1.battlefield.append(Permanent(card=catalog_by_name["Invoke Prejudice"]))
    guard = Permanent(card=catalog_by_name["Grizzly Bears"])
    p1.battlefield.append(guard)
    p1.hand = [catalog_by_name["Deathlace"]]
    game.cast_from_hand(0, "Deathlace", target_player_index=0, target_permanent_index=1)
    game._settle()
    assert guard.effective_colors == {"B"}

    p2.hand = [catalog_by_name["Grizzly Bears"]]
    game.cast_from_hand(1, "Grizzly Bears")
    game._settle()

    assert [card.name for card in p2.graveyard] == ["Grizzly Bears"]
    assert p2.battlefield == []


# ---------------------------------------------------------------------------
# CR 202 — mana cost and mana value
# ---------------------------------------------------------------------------


@pytest.mark.cr("202.3", "202.3a")
def test_mana_value_is_the_total_of_the_printed_symbols(catalog):
    """CR 202.3 over the whole pool: the mana value is the total amount of mana
    in the mana cost, *regardless of colour*.

    Two readers that must agree — the engine's own symbol parser
    (``Game._parse_mana_cost``, which is what a cast actually spends against) and
    the ingested ``cmc``, which every mana-value effect reads. X counts as 0 off
    the stack (CR 202.3e), and a card with no mana cost is 0 (CR 202.3a); both
    fall out of the same sum. A drift between the two would make a spell cost one
    thing and measure as another.
    """
    game, _p1, _p2 = _duel()

    mismatched = [
        card.name
        for card in catalog
        if total_pips(game._parse_mana_cost(card.mana_cost, x_value=0)) != int(card.cmc)
    ]

    assert mismatched == []
    costless = [card for card in catalog if not card.mana_cost.strip()]
    assert costless, "the pool has land cards"
    assert [card.name for card in costless if card.cmc] == []


def _cast_with_lands(catalog_by_name, land_names: list[str], spell: str):
    """Tap every land for mana, then try to cast *spell* with costs enforced."""
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    for name in land_names:
        p1.battlefield.append(Permanent(card=catalog_by_name[name]))
    for index, name in enumerate(land_names):
        assert game.tap_land_for_mana(0, name, permanent_index=index)
    p1.hand = [catalog_by_name[spell]]
    result = game.cast_from_hand(0, spell)
    game._settle()
    return result, p1


@pytest.mark.cr("202.1a", "202.3")
def test_the_total_is_not_enough_without_the_colored_symbols(catalog_by_name):
    """Sengir Vampire is {3}{B}{B}. Five Forests is five mana — the whole mana
    value — and cannot cast it.

    CR 202.1a: the mana cost is what a player must spend, symbol by symbol. An
    engine that paid against the mana value alone would cast this off any five
    lands, which is the shortcut a numeric cost invites.
    """
    result, p1 = _cast_with_lands(catalog_by_name, ["Forest"] * 5, "Sengir Vampire")

    assert not result.supported
    assert "insufficient mana" in result.details
    assert [perm.card.name for perm in p1.battlefield] == ["Forest"] * 5


@pytest.mark.cr("202.1a", "202.3")
def test_generic_symbols_take_any_color_and_the_colored_ones_do_not(catalog_by_name):
    """Three Forests and two Swamps: the {B}{B} comes off the Swamps and the {3}
    off anything (CR 202.3, "regardless of color"). The pool is emptied, so all
    five were genuinely spent."""
    result, p1 = _cast_with_lands(
        catalog_by_name, ["Forest"] * 3 + ["Swamp"] * 2, "Sengir Vampire"
    )

    assert result.supported and result.details == "resolved"
    assert "Sengir Vampire" in [perm.card.name for perm in p1.battlefield]
    assert sum(p1.mana_pool.values()) == 0


@pytest.mark.cr("202.3")
def test_the_right_colors_are_not_enough_below_the_total(catalog_by_name):
    """The mirror of the first: four Swamps pay both black pips and one of the
    three generic, and stop a mana short of the mana value."""
    result, _p1 = _cast_with_lands(catalog_by_name, ["Swamp"] * 4, "Sengir Vampire")

    assert not result.supported
    assert "insufficient mana" in result.details


@pytest.mark.cr("202.3")
def test_x_equal_to_a_permanents_mana_value_reads_the_printed_cost(catalog_by_name):
    """Great Defender: "+0/+X until end of turn, where X is its mana value."

    Sengir Vampire is a 4/4 costing {3}{B}{B}, so the bonus is 5 and not 2 (its
    coloured pips) or 3 (its generic). CR 202.3's "regardless of color" is the
    whole of the arithmetic.
    """
    game, p1, _p2 = _duel()
    vampire = Permanent(card=catalog_by_name["Sengir Vampire"])
    p1.battlefield.append(vampire)
    p1.hand = [catalog_by_name["Great Defender"]]

    game.cast_from_hand(0, "Great Defender", target_player_index=0, target_permanent_index=0)
    game._settle()

    assert (vampire.effective_power, vampire.effective_toughness) == (4, 9)


@pytest.mark.cr("202.1b", "202.3a")
def test_a_land_animated_into_a_creature_still_has_no_mana_cost(catalog_by_name):
    """Kormus Bell makes every Swamp a 1/1 creature; Great Defender then gives it
    +0/+X where X is its mana value.

    CR 202.1b: a land card has no mana cost, and CR 202.3a makes the mana value
    of an object with no mana cost 0 — becoming a creature does not invent one.
    So the pump is +0/+0 and the Swamp is still 1/1. The test above is the
    control that says Great Defender does something at all.
    """
    game, p1, _p2 = _duel()
    p1.battlefield.append(Permanent(card=catalog_by_name["Kormus Bell"]))
    swamp = Permanent(card=catalog_by_name["Swamp"])
    p1.battlefield.append(swamp)
    game._settle()
    assert swamp.is_creature

    p1.hand = [catalog_by_name["Great Defender"]]
    game.cast_from_hand(0, "Great Defender", target_player_index=0, target_permanent_index=1)
    game._settle()

    assert (swamp.effective_power, swamp.effective_toughness) == (1, 1)


@pytest.mark.cr("202.3")
def test_life_gained_equals_the_destroyed_artifacts_mana_value(catalog_by_name):
    """Divine Offering: "Destroy target artifact. You gain life equal to its mana
    value." Su-Chi costs {4} and Ornithopter costs {0} — a printed zero is a real
    mana value, not a missing one, so the second gains nothing."""
    for name, expected in (("Su-Chi", 4), ("Ornithopter", 0)):
        game, p1, p2 = _duel()
        p2.battlefield.append(Permanent(card=catalog_by_name[name]))
        p1.hand = [catalog_by_name["Divine Offering"]]
        p1.life = 20

        game.cast_from_hand(
            0, "Divine Offering", target_player_index=1, target_permanent_index=0
        )
        game._settle()

        assert p2.battlefield == [], name
        assert p1.life == 20 + expected, name


# ---------------------------------------------------------------------------
# CR 205.2 — card types
# ---------------------------------------------------------------------------


@pytest.mark.cr("205.2a", "205.2b")
def test_a_card_in_a_library_has_every_type_its_line_names(catalog_by_name):
    """"Search your library for an **artifact** card" must find Su-Chi, whose
    line is "Artifact Creature — Construct".

    CR 205.2a/b: an object with more than one card type satisfies any effect that
    applies to *any* of them. ``primary_type`` collapses that line to one word by
    the order of a list, which is why the shared search predicate asks
    ``card_has_type`` instead — a card in a library has no computed
    characteristics (CR 613.1), so the printed line is the whole of the answer.
    """
    assert search_matches(catalog_by_name["Su-Chi"], {"card_type": "artifact"})
    assert search_matches(catalog_by_name["Su-Chi"], {"card_type": "creature"})
    assert not search_matches(catalog_by_name["Grizzly Bears"], {"card_type": "artifact"})


@pytest.mark.cr("205.2b", "601.2c")
def test_an_artifact_creature_answers_target_artifact(catalog_by_name):
    """The same rule on the battlefield: Divine Offering's "target artifact"
    picker offers an Artifact Creature beside a plain artifact, and offers no
    creature that is not one."""
    game, _p1, p2 = _duel()
    for name in ("Su-Chi", "Grizzly Bears", "Icy Manipulator"):
        p2.battlefield.append(Permanent(card=catalog_by_name[name]))
    game._settle()

    assert _cast_picker(game, catalog_by_name["Divine Offering"]) == [
        "Su-Chi", "Icy Manipulator",
    ]


@pytest.mark.cr("205.2b", "613.1d")
def test_an_animated_land_is_offered_as_both_a_land_and_a_creature(catalog_by_name):
    """Kormus Bell: "All Swamps are 1/1 black creatures **that are still
    lands**."

    Two card types on one permanent, so Stone Rain's "target land" picker and
    Giant Growth's "target creature" picker both offer it and the Forest beside
    it is offered by only one. This is the CR 205.2b question asked of the
    *computed* type line (CR 613 layer 4) rather than the printed one.
    """
    game, _p1, p2 = _duel()
    p2.battlefield.append(Permanent(card=catalog_by_name["Kormus Bell"]))
    swamp = Permanent(card=catalog_by_name["Swamp"])
    p2.battlefield.append(swamp)
    p2.battlefield.append(Permanent(card=catalog_by_name["Forest"]))
    game._settle()

    assert swamp.has_type("land") and swamp.has_type("creature")
    assert _cast_picker(game, catalog_by_name["Stone Rain"]) == ["Swamp", "Forest"]
    assert _cast_picker(game, catalog_by_name["Giant Growth"]) == ["Swamp"]


@pytest.mark.cr("205.2b")
def test_destroy_target_land_destroys_the_animated_swamp(catalog_by_name):
    """And the resolution agrees with the picker: land destruction kills a Swamp
    that has become a creature, because being a creature took nothing away."""
    game, p1, p2 = _duel()
    p2.battlefield.append(Permanent(card=catalog_by_name["Kormus Bell"]))
    p2.battlefield.append(Permanent(card=catalog_by_name["Swamp"]))
    game._settle()
    p1.hand = [catalog_by_name["Stone Rain"]]

    game.cast_from_hand(0, "Stone Rain", target_player_index=1, target_permanent_index=1)
    game._settle()

    assert [perm.card.name for perm in p2.battlefield] == ["Kormus Bell"]
    assert [card.name for card in p2.graveyard] == ["Swamp"]


@pytest.mark.cr("205.2b", "202.3")
def test_an_animated_artifact_is_an_artifact_creature(catalog_by_name):
    """Xenic Poltergeist: "target noncreature artifact becomes an artifact
    creature with power and toughness each equal to its mana value."

    Both halves at once — the added card type does not displace the printed one
    (CR 205.2b), and the P/T is the printed cost's total (CR 202.3). Icy
    Manipulator costs {4}, so it is a 4/4 that is still an artifact.
    """
    game, p1, _p2 = _duel()
    poltergeist = _nosick(Permanent(card=catalog_by_name["Xenic Poltergeist"]))
    p1.battlefield.append(poltergeist)
    icy = Permanent(card=catalog_by_name["Icy Manipulator"])
    p1.battlefield.append(icy)

    game.activate_permanent_ability(
        0, "Xenic Poltergeist", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert icy.has_type("artifact") and icy.has_type("creature")
    assert (icy.effective_power, icy.effective_toughness) == (4, 4)


# ---------------------------------------------------------------------------
# CR 205.3 — subtypes
# ---------------------------------------------------------------------------


@pytest.mark.cr("205.3i", "205.3b")
def test_a_chosen_land_type_replaces_the_lands_printed_land_types(catalog_by_name):
    """Phantasmal Terrain: "Enchanted land is the chosen type."

    CR 205.3i's land types are a subtype axis, and this effect *replaces* what is
    on it — so a Forest named a Swamp stops being a Forest, and the intrinsic
    mana ability CR 305.6 gives it follows the subtype rather than the printed
    word. The card type is untouched: it is still a land.
    """
    game, p1, _p2 = _duel()
    forest = Permanent(card=catalog_by_name["Forest"])
    p1.battlefield.append(forest)
    p1.hand = [catalog_by_name["Phantasmal Terrain"]]

    game.cast_from_hand(
        0, "Phantasmal Terrain", target_player_index=0, target_permanent_index=0
    )
    game._settle()
    assert game.confirm_land_type(0, "Swamp")
    game._settle()

    assert forest.has_type("swamp")
    assert not forest.has_type("forest")
    assert forest.has_type("land")
    assert game.tap_land_for_mana(0, "Forest", permanent_index=0)
    assert p1.mana_pool["B"] == 1 and p1.mana_pool["G"] == 0


# ---------------------------------------------------------------------------
# CR 205.4 — supertypes
# ---------------------------------------------------------------------------


@pytest.mark.cr("205.4c", "205.3i")
def test_a_nonbasic_land_is_not_found_by_a_search_for_a_basic_land_card(catalog_by_name):
    """Untamed Wilds searches for "a **basic** land card". Tundra's line is
    "Land — Plains Island": two basic *land types* and no basic *supertype*.

    CR 205.4c says exactly this case — any land without the supertype is a
    nonbasic land, even if it has a basic land type. A search that read the land
    types would happily fetch a dual, which is a different card entirely.
    """
    game, p1, _p2 = _duel()
    p1.library = [
        catalog_by_name["Tundra"], catalog_by_name["Forest"], catalog_by_name["Su-Chi"]
    ]
    p1.hand = [catalog_by_name["Untamed Wilds"]]

    game.cast_from_hand(0, "Untamed Wilds")
    game._settle()

    assert game.pending_search_library is not None
    assert not game.confirm_search_library(0, 0)   # Tundra
    assert game.confirm_search_library(0, 1)       # Forest
    assert [perm.card.name for perm in p1.battlefield] == ["Forest"]


@pytest.mark.cr("205.4c", "205.4b")
def test_gaining_a_basic_land_type_does_not_make_a_land_basic(catalog_by_name):
    """The same rule from the other side: Phantasmal Terrain gives a Tundra the
    Swamp land type, and the supertype line stays empty.

    CR 205.4b — a supertype is independent of the subtype, and changing one never
    changes the other. So the Tundra taps for {B} and is still nonbasic.
    """
    game, p1, _p2 = _duel()
    tundra = Permanent(card=catalog_by_name["Tundra"])
    p1.battlefield.append(tundra)
    p1.hand = [catalog_by_name["Phantasmal Terrain"]]

    game.cast_from_hand(
        0, "Phantasmal Terrain", target_player_index=0, target_permanent_index=0
    )
    game._settle()
    assert game.confirm_land_type(0, "Swamp")
    game._settle()

    assert tundra.has_type("swamp")
    assert printed_supertypes(displayed_type_line(tundra)) == frozenset()
    assert printed_supertypes(catalog_by_name["Forest"].type_line) == frozenset({"basic"})


@pytest.mark.cr("205.4a", "205.4d", "704.5j")
def test_the_legend_rule_is_keyed_on_the_supertype(catalog_by_name):
    """CR 205.4d: a permanent with the legendary supertype is subject to the
    legend rule. Two Karakas leave one; two Forests — same card name, no
    supertype — leave both, so this is the supertype and not the name."""
    game, p1, _p2 = _duel()
    p1.battlefield.append(Permanent(card=catalog_by_name["Karakas"]))
    p1.battlefield.append(Permanent(card=catalog_by_name["Karakas"]))
    p1.battlefield.append(Permanent(card=catalog_by_name["Forest"]))
    p1.battlefield.append(Permanent(card=catalog_by_name["Forest"]))

    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == ["Karakas", "Forest", "Forest"]
    assert [card.name for card in p1.graveyard] == ["Karakas"]


@pytest.mark.cr("205.4b", "205.4d")
def test_a_type_change_does_not_take_a_supertype_away(catalog_by_name):
    """CR 205.4b's own example, in the shape the pool prints it: Xenic Poltergeist
    makes a Legendary Artifact into an artifact creature, and it stays legendary.

    Both halves are asserted because either alone would pass for the wrong
    reason: the supertype read alone would pass on a permanent nothing had
    animated, and the legend rule alone fires on two copies whatever their types
    are. Together they say the layer-4 type change left layer-independent
    supertypes alone.
    """
    game, p1, _p2 = _duel()
    poltergeist = _nosick(Permanent(card=catalog_by_name["Xenic Poltergeist"]))
    p1.battlefield.append(poltergeist)
    orrery = Permanent(card=catalog_by_name["Chromatic Orrery"])
    p1.battlefield.append(orrery)

    game.activate_permanent_ability(
        0, "Xenic Poltergeist", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert orrery.is_creature and orrery.has_type("artifact")
    assert printed_supertypes(displayed_type_line(orrery)) == frozenset({"legendary"})

    p1.battlefield.append(Permanent(card=catalog_by_name["Chromatic Orrery"]))
    game._settle()

    assert [perm.card.name for perm in p1.battlefield].count("Chromatic Orrery") == 1
    assert [card.name for card in p1.graveyard] == ["Chromatic Orrery"]
