"""Ice Age (ICE) enchantment cards — wave 2.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.


The file passed the 2,600-line guard and tests/sets/README.md's next axis
after the printed type is a round boundary. The cut is the wave boundary:
the serial rounds and the first parallel wave are in
``test_ice_enchantments_early_rounds.py``; the second wave is here.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick

# --- W2G2: mana-production replacements and land-type changes ---
def _lands_board(set_pool, permanent_name=None, lands=("Forest", "Plains", "Island", "Mountain", "Swamp"), opponents=False):
    """A seat with one basic of each type, and optionally a permanent printing a
    mana-production replacement — on either battlefield.

    The lands are LEA basics on purpose: their whole printed text is CR 305.6
    reminder text, so they compile to no mana ability and fall through the tap
    seam's ``produced_mana`` branch. ``_dual_board`` below covers the other one.
    """
    perms = [Permanent(card=set_pool("LEA")[name]) for name in lands]
    p1 = PlayerState(name="P1", battlefield=list(perms))
    p2 = PlayerState(name="P2")
    if permanent_name is not None:
        source = Permanent(card=set_pool("ICE")[permanent_name])
        (p2 if opponents else p1).battlefield.append(source)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, perms


def _tap_every_land(game, player, lands=("Forest", "Plains", "Island", "Mountain", "Swamp")):
    player.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}
    for index, name in enumerate(lands):
        assert game.tap_land_for_mana(0, name, permanent_index=index), name
    return {symbol: count for symbol, count in player.mana_pool.items() if count}


def test_ritual_of_subdual_makes_every_land_produce_colorless(set_pool):
    """"If a land is tapped for mana, it produces colorless mana instead of any
    other type."

    CR 106.12b: a replacement effect over the mana production event, so the
    only way to see it is to tap the lands and read the pool. The compiler
    would have been happy with a claimed line that changed nothing.
    """
    game, p1, _p2, _lands = _lands_board(set_pool, "Ritual of Subdual")

    assert _tap_every_land(game, p1) == {"C": 5}


def test_ritual_of_subdual_is_gone_when_the_enchantment_is(set_pool):
    """Nothing is stamped on the lands, so the static stops applying the moment
    its source leaves — the half a recorded swap would have got wrong."""
    game, p1, _p2, _lands = _lands_board(set_pool, "Ritual of Subdual")
    game.remove_from_battlefield(p1.battlefield[-1])

    assert _tap_every_land(game, p1) == {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1}


def test_ritual_of_subdual_covers_an_opponents_lands_too(set_pool):
    """"**A land**" names no seat, so the enchantment reaches every
    battlefield — the same reading Worms of the Earth's "Lands can't enter the
    battlefield" gets, and the reason this is not a per-seat record."""
    game, p1, _p2, _lands = _lands_board(set_pool, "Ritual of Subdual", opponents=True)

    assert _tap_every_land(game, p1) == {"C": 5}


def test_infernal_darkness_makes_every_land_produce_black(set_pool):
    """The same sentence with the symbol as payload: a card printing another
    colour needs no code."""
    game, p1, _p2, _lands = _lands_board(set_pool, "Infernal Darkness")

    assert _tap_every_land(game, p1) == {"B": 5}


def test_reality_twist_substitutes_by_land_type(set_pool):
    """"If tapped for mana, Plains produce {R}, Swamps produce {G}, Mountains
    produce {W}, and Forests produce {B} instead of any other type."

    Four clauses, and the Island the card does not name still makes {U} — which
    is what separates this from the untyped spelling above.
    """
    game, p1, _p2, _lands = _lands_board(set_pool, "Reality Twist")

    assert _tap_every_land(game, p1) == {"R": 1, "G": 1, "W": 1, "B": 1, "U": 1}


def test_reality_twist_reads_the_type_through_layer_4(set_pool):
    """A land made a Swamp by an effect is one of the Swamps the clause names.

    ``has_type``, not the printed type line: the substitution is keyed to what
    the land *is* when it is tapped, so an Evil Presence Forest produces {G}
    and not {B}.
    """
    from engine.land_types import change_land_type

    game, p1, _p2, lands = _lands_board(set_pool, "Reality Twist", lands=("Forest",))
    change_land_type(lands[0], "swamp", source="a test", label="test")

    p1.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}
    assert game.tap_land_for_mana(0, "Forest", permanent_index=0)

    assert p1.mana_pool["G"] == 1, "a Swamp, so the Swamp clause"
    assert p1.mana_pool["B"] == 0, "not the Forest clause it no longer answers"


def test_ritual_of_subdual_covers_a_land_whose_mana_ability_compiles(set_pool):
    """A dual land runs its own compiled ability and writes into the pool
    itself, so the substitution cannot be a swap on ``produced_mana``.

    The tap seam snapshots the pool and moves whatever came out, which is the
    one place both production branches meet.
    """
    game, p1, _p2, _lands = _lands_board(
        set_pool, "Ritual of Subdual", lands=("Tundra",)
    )

    p1.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}
    assert game.tap_land_for_mana(0, "Tundra", permanent_index=0, chosen_color="U")

    assert p1.mana_pool["C"] == 1
    assert p1.mana_pool["U"] == 0, "the blue is replaced, not added to"


def test_ritual_of_subdual_line_is_claimed_by_the_replacement_registry(set_pool):
    """The interceptor is what implements the line, so the claim asks it — the
    card would otherwise carry a printed sentence nothing accounts for."""
    from engine.grammar.registries import registry_for_line

    for name in ("Ritual of Subdual", "Infernal Darkness", "Reality Twist"):
        card = set_pool("ICE")[name]
        line = [
            text for text in card.oracle_text.split("\n")
            if text.lower().startswith("if ")
        ][0]
        assert registry_for_line(line) == "replacements", name

def _blizzard_game(set_pool, lands):
    """Blizzard in hand over a board of *lands*, named out of ICE or LEA."""
    ice, lea = set_pool("ICE"), set_pool("LEA")
    perms = [Permanent(card=ice.get(name) or lea[name]) for name in lands]
    p1 = PlayerState(name="P1", battlefield=perms, hand=[ice["Blizzard"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1


def test_blizzard_refuses_a_board_with_no_snow_land(set_pool):
    """"Cast this spell only if you control a snow land." (CR 601.3.)

    A printed restriction is only done when something enforces it: the line was
    read and dropped, so the spell cast off any board at all.
    """
    game, p1 = _blizzard_game(set_pool, ["Forest"])

    result = game.cast_from_hand(0, "Blizzard")

    assert not result.supported
    assert "snow land" in result.details
    assert [card.name for card in p1.hand] == ["Blizzard"], "nothing was spent"


def test_blizzard_casts_over_a_snow_land(set_pool):
    game, _p1 = _blizzard_game(set_pool, ["Snow-Covered Forest"])

    assert game.cast_from_hand(0, "Blizzard").supported


def test_blizzard_wants_a_snow_land_and_not_merely_something_snow(set_pool):
    """The noun phrase is read by the grammar's own noun parser, so "snow"
    qualifies the *land* — a snow permanent that is not one does not answer."""
    game, _p1 = _blizzard_game(set_pool, ["Forest"])
    assert not game.cast_from_hand(0, "Blizzard").supported


def test_blizzard_reads_snow_through_the_layers(set_pool):
    """"All lands are no longer snow." (Melting.) The condition asks
    ``subject_matches``, which resolves the supertype through layer 4 — so a
    board Melting has thawed stops answering."""
    game, p1 = _blizzard_game(set_pool, ["Snow-Covered Forest"])
    p1.battlefield.append(Permanent(card=set_pool("ICE")["Melting"]))
    game._refresh_dynamic_creatures()

    result = game.cast_from_hand(0, "Blizzard")

    assert not result.supported, result.details

def _terrain_game(set_pool, opponent_lands, interactive=False):
    """Illusionary Terrain in hand over an opponent's *opponent_lands*."""
    ice, lea = set_pool("ICE"), set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[ice["Illusionary Terrain"]])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=lea[name]) for name in opponent_lands],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game.start_turn(0)
    return game, p1, p2


def test_illusionary_terrain_changes_the_chosen_basic_type(set_pool):
    """"As this enchantment enters, choose two basic land types." / "Basic
    lands of the first chosen type are the second chosen type."

    CR 614.1c's entry choice feeding a CR 613 layer-4 static: the sentence
    names no land type at all, so the derivation reads the ordered pair off the
    permanent. Proved by tapping the land, because a type change nothing
    produces mana from is one only the metadata can see.
    """
    game, p1, p2 = _terrain_game(set_pool, ["Forest", "Forest"])

    assert game.cast_from_hand(0, "Illusionary Terrain").supported
    game._settle()

    terrain = p1.battlefield[-1]
    assert terrain.metadata["chosen_land_types"] == ("forest", "plains"), (
        "the default is the hoser's choice: the type the opponents hold most "
        "of becomes the one they hold least"
    )
    forest = p2.battlefield[0]
    assert forest.basic_land_types == ("plains",)

    p2.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}
    assert game.tap_land_for_mana(1, "Forest", permanent_index=0)
    assert p2.mana_pool["W"] == 1
    assert p2.mana_pool["G"] == 0


def test_illusionary_terrain_leaves_a_nonbasic_alone(set_pool):
    """"**Basic** lands of the first chosen type" — a Taiga is a Forest and is
    not basic, so the static does not reach it. Asked of ``has_supertype``,
    which computes the word rather than reading the printed line."""
    game, _p1, p2 = _terrain_game(set_pool, ["Forest", "Taiga"])
    assert game.cast_from_hand(0, "Illusionary Terrain").supported
    game._settle()

    assert p2.battlefield[0].basic_land_types == ("plains",)
    assert p2.battlefield[1].basic_land_types == ("mountain", "forest")


def test_illusionary_terrain_asks_its_controller_and_takes_the_answer(set_pool):
    """The default is stamped before the prompt so a headless seat never
    blocks; an interactive controller's answer overwrites it, and the static
    recomputes from the new pair."""
    game, p1, p2 = _terrain_game(set_pool, ["Forest"], interactive=True)
    assert game.cast_from_hand(0, "Illusionary Terrain").supported
    game._settle()
    assert game.pending_enter_choice["needs_land_types"]

    assert game.confirm_enter_choice(0, land_types=["forest", "island"])

    assert p1.battlefield[-1].metadata["chosen_land_types"] == ("forest", "island")
    assert p2.battlefield[0].basic_land_types == ("island",)


def test_illusionary_terrain_refuses_a_pair_that_is_not_two_types(set_pool):
    """An answer naming one type twice is refused rather than repaired:
    quietly keeping the default would tell the player they had chosen
    something they had not."""
    game, _p1, _p2 = _terrain_game(set_pool, ["Forest"], interactive=True)
    assert game.cast_from_hand(0, "Illusionary Terrain").supported
    game._settle()

    assert not game.confirm_enter_choice(0, land_types=["forest", "forest"])
    assert not game.confirm_enter_choice(0, land_types=["forest", "wastes"])


def test_illusionary_terrain_reverts_when_it_leaves(set_pool):
    """A derived static, recomputed from the board — so the land is a Forest
    again the moment the enchantment is gone (CR 611.3a/b)."""
    game, p1, p2 = _terrain_game(set_pool, ["Forest"])
    assert game.cast_from_hand(0, "Illusionary Terrain").supported
    game._settle()
    assert p2.battlefield[0].basic_land_types == ("plains",)

    game.remove_from_battlefield(p1.battlefield[-1])
    game._refresh_dynamic_creatures()

    assert p2.battlefield[0].basic_land_types == ("forest",)

def _snowfall_board(set_pool, land_name):
    ice, lea = set_pool("ICE"), set_pool("LEA")
    land = Permanent(card=ice.get(land_name) or lea[land_name])
    p1 = PlayerState(
        name="P1", battlefield=[land, Permanent(card=ice["Snowfall"])]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    p1.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}
    p1.restricted_mana = {}
    return game, p1, land


def _pools(player):
    pool = {symbol: count for symbol, count in player.mana_pool.items() if count}
    restricted = {
        key: {symbol: count for symbol, count in bucket.items() if count}
        for key, bucket in player.restricted_mana.items()
        if any(bucket.values())
    }
    return pool, restricted


def test_snowfall_adds_restricted_mana_for_an_island(set_pool):
    """"Whenever an Island is tapped for mana, its controller may add an
    additional {U}. … Spend this mana only to pay cumulative upkeep costs."

    The whole ability failed to parse, so the card reported supported on its
    cumulative upkeep alone and made **no mana at all**. Two things were
    wrong at once: the trigger table read "whenever **a** … is tapped for
    mana" and the card prints "an Island", and the offer's three sentences
    had no production that read them together.
    """
    game, p1, _land = _snowfall_board(set_pool, "Island")

    assert game.tap_land_for_mana(0, "Island", permanent_index=0)

    pool, restricted = _pools(p1)
    assert pool == {"U": 1}, "the Island's own mana, unrestricted"
    assert restricted == {"cumulative_upkeep": {"U": 1}}


def test_snowfall_doubles_the_offer_for_a_snow_island(set_pool):
    """"If that Island is snow, its controller may add an additional {U}{U}
    **instead**." The alternative replaces the base production rather than
    adding to it — parsed apart, the two sentences would make three."""
    game, p1, _land = _snowfall_board(set_pool, "Snow-Covered Island")

    assert game.tap_land_for_mana(0, "Snow-Covered Island", permanent_index=0)

    pool, restricted = _pools(p1)
    assert pool == {"U": 1}
    assert restricted == {"cumulative_upkeep": {"U": 2}}, "instead, not as well"


def test_snowfall_ignores_a_land_that_is_not_an_island(set_pool):
    game, p1, _land = _snowfall_board(set_pool, "Forest")

    assert game.tap_land_for_mana(0, "Forest", permanent_index=0)

    assert _pools(p1) == ({"G": 1}, {})


def test_snowfall_mana_pays_a_cumulative_upkeep_and_nothing_else(set_pool):
    """A printed restriction is only done when something enforces it. The
    bucket is ``engine/restricted_mana.py``'s, so the three payment paths
    already ask what it may pay for."""
    from engine.restricted_mana import (CAST, CUMULATIVE_UPKEEP, PaymentPurpose,
                                        spendable_restricted_mana)

    game, p1, _land = _snowfall_board(set_pool, "Island")
    assert game.tap_land_for_mana(0, "Island", permanent_index=0)

    upkeep = PaymentPurpose(kind=CUMULATIVE_UPKEEP)
    assert spendable_restricted_mana(p1, upkeep) == {"U": 1}
    casting = PaymentPurpose(kind=CAST, card=set_pool("LEA")["Ancestral Recall"])
    assert spendable_restricted_mana(p1, casting) == {}
# --- end W2G2 ---


# --- W2G1: pay-or-consequence tolls ---
def test_cold_snap_damages_each_player_for_their_own_snow_lands(set_pool):
    """"At the beginning of each player's upkeep, this enchantment deals damage
    to that player equal to the number of snow lands they control."

    Recipient and counted board are the *same* frozen seat (CR 603.10), which
    is what separates this from Typhoon's per-seat loop: one number, taken on
    the player whose upkeep it is.
    """
    pool = set_pool("ICE")
    snap = Permanent(card=pool["Cold Snap"])
    p0 = PlayerState(name="P0", battlefield=[snap], life=20)
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=pool["Snow-Covered Plains"]),
            Permanent(card=pool["Snow-Covered Island"]),
        ],
        life=20,
    )
    game = Game(players=[p0, p1])
    game.active_player_index = 1

    game.resolve_upkeep(1)
    game._settle()

    assert p1.life == 18, "two snow lands, two damage"
    assert p0.life == 20, "it is not their upkeep"


def test_cold_snap_counts_only_snow_lands(set_pool):
    """A plain land is not a snow land, so it is not counted."""
    pool = set_pool("ICE")
    snap = Permanent(card=pool["Cold Snap"])
    p0 = PlayerState(
        name="P0",
        battlefield=[snap, Permanent(card=pool["Snow-Covered Swamp"])],
        life=20,
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Ice Floe"])], life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 1

    game.resolve_upkeep(1)
    game._settle()

    assert p1.life == 20, "Ice Floe is a land, but not a snow one"
    assert p0.life == 20


def test_a_permanents_second_upkeep_trigger_survives_the_first(set_pool):
    """CR 603.3: *every* ability that triggered goes on the stack.

    Cold Snap prints cumulative upkeep first and "each player's upkeep" second.
    The upkeep loop broke out of a permanent's ability list the moment it saw a
    "your upkeep" condition on somebody else's turn, so the second ability was
    never reached - the enchantment dealt nobody damage on any turn but its
    controller's while reporting itself supported. Maddening Wind prints the
    same pair and lost its damage the same way.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    wind = Permanent(card=pool["Maddening Wind"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[wind], life=20)
    p1 = PlayerState(name="P1", battlefield=[bears], life=20)
    game = Game(players=[p0, p1])
    attach_aura(wind, bears)
    game.active_player_index = 1

    game.resolve_upkeep(1)
    game._settle()

    assert p1.life == 18, "the Aura's second trigger fires on the host's upkeep"


def test_icy_prison_offers_the_toll_to_every_seat(set_pool):
    """"At the beginning of your upkeep, sacrifice this enchantment unless any
    player pays {3}."

    "Any player" is the whole table, the controller included - one offer the
    first acceptance ends (CR 601.2b), not one prompt per seat.
    """
    pool = set_pool("ICE")
    prison = Permanent(card=pool["Icy Prison"])
    p0 = PlayerState(name="P0", battlefield=[prison], life=20)
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 0

    game.resolve_upkeep(0)
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert not game.is_on_battlefield(prison), "nobody paid, so it is sacrificed"


def test_icy_prison_asks_the_next_seat_when_one_declines(set_pool):
    """The chain, not a batch: the controller is asked first (CR 101.4), and a
    decline moves the offer on rather than sacrificing the enchantment. Any one
    payment keeps it, and nobody after the payer is asked (CR 601.2b)."""
    pool = set_pool("ICE")
    prison = Permanent(card=pool["Icy Prison"])
    lands = [Permanent(card=pool["Snow-Covered Island"]) for _ in range(3)]
    p0 = PlayerState(name="P0", battlefield=[prison], life=20)
    p1 = PlayerState(name="P1", battlefield=lands, life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 0

    game.resolve_upkeep(0)
    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert [c.player_index for c in owed] == [0], "the controller is asked first"

    assert game.confirm_optional_pay(0, accept=False)
    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert [c.player_index for c in owed] == [1], "and the offer moves on"

    assert game.confirm_optional_pay(1, accept=True)
    game._settle()

    assert game.is_on_battlefield(prison), "an opponent bought it off"
    assert all(land.tapped for land in lands), "the {3} came off the board"


def test_earthlink_makes_the_dead_creatures_controller_sacrifice_a_land(set_pool):
    """"Whenever a creature dies, that creature's controller sacrifices a land
    of their choice."

    The seat is the one that controlled the creature that died - frozen by the
    fire site, because a graveyard card cannot say whose battlefield it left.
    """
    pool = set_pool("ICE")
    link = Permanent(card=pool["Earthlink"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[link], life=20)
    p1 = PlayerState(
        name="P1",
        battlefield=[bears, Permanent(card=pool["Snow-Covered Forest"])],
        life=20,
    )
    game = Game(players=[p0, p1])

    game._destroy_target_permanent(p1, target_permanent_index=p1.battlefield.index(bears))
    game._settle()

    assert [c.name for c in p1.graveyard] == ["Balduvian Bears", "Snow-Covered Forest"]
    assert p0.battlefield == [link], "the Earthlink controller gives up nothing"


def test_mystic_remora_lets_the_caster_buy_off_the_draw(set_pool):
    """"Whenever an opponent casts a noncreature spell, you may draw a card
    unless that player pays {4}."

    The decision belongs to the caster, not to Remora's controller: the offer
    is theirs and the draw is the branch they decline into.
    """
    pool = set_pool("ICE")
    remora = Permanent(card=pool["Mystic Remora"])
    p0 = PlayerState(
        name="P0", battlefield=[remora], life=20,
        library=[pool["Balduvian Bears"], pool["Brown Ouphe"]],
    )
    p1 = PlayerState(name="P1", hand=[pool["Icy Prison"]], life=20)
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Icy Prison")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert len(p0.hand) == 1, "the toll went unpaid, so the card is drawn"


def test_mystic_remora_ignores_a_creature_spell(set_pool):
    """"a **noncreature** spell" - the narrowing the opponent-scoped cast head
    could not read at all until this round, which stranded the whole line."""
    pool = set_pool("ICE")
    remora = Permanent(card=pool["Mystic Remora"])
    p0 = PlayerState(
        name="P0", battlefield=[remora], life=20,
        library=[pool["Balduvian Bears"]],
    )
    p1 = PlayerState(name="P1", hand=[pool["Balduvian Bears"]], life=20)
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Balduvian Bears")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert p0.hand == []


def test_freyalise_charm_draws_when_the_controller_pays(set_pool):
    """"Whenever an opponent casts a black spell, you may pay {G}{G}. If you do,
    you draw a card."

    The colour narrowing was tested in one of the two cast dispatchers, so the
    opponent-scoped spelling had no colour test at all.
    """
    pool = set_pool("ICE")
    charm = Permanent(card=pool["Freyalise's Charm"])
    p0 = PlayerState(
        name="P0", battlefield=[charm], life=20, mana_pool={"G": 2},
        library=[pool["Balduvian Bears"]],
    )
    p1 = PlayerState(name="P1", hand=[pool["Dark Ritual"]], life=20)
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Dark Ritual")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert len(p0.hand) == 1
    assert p0.mana_pool.get("G", 0) == 0


def test_freyalise_charm_ignores_a_spell_of_another_colour(set_pool):
    pool = set_pool("ICE")
    charm = Permanent(card=pool["Freyalise's Charm"])
    p0 = PlayerState(
        name="P0", battlefield=[charm], life=20, mana_pool={"G": 2},
        library=[pool["Balduvian Bears"]],
    )
    p1 = PlayerState(name="P1", hand=[pool["Icy Prison"]], life=20)   # blue
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Icy Prison")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert p0.hand == []
    assert p0.mana_pool.get("G", 0) == 2, "nothing was offered, so nothing was paid"


def test_icy_prison_gives_the_exiled_creature_back_when_it_leaves(set_pool):
    """"When this enchantment leaves the battlefield, return the exiled card to
    the battlefield under its owner's control."

    CR 610.3's linked pair, printed as two abilities: "the exiled card" is the
    one *this* permanent's other ability exiled, which is the pile
    ``engine/linked_exile.py`` already records — the same one Safe Haven drains
    with its own wording of the sentence.
    """
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", hand=[pool["Icy Prison"]], life=20)
    p1 = PlayerState(name="P1", battlefield=[bears], life=20)
    game = Game(players=[p0, p1])

    result = game.cast_from_hand(
        0, "Icy Prison", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()
    assert [c.name for c in p1.exile] == ["Balduvian Bears"]

    prison = p0.battlefield[0]
    game.active_player_index = 0
    game.resolve_upkeep(0)
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert not game.is_on_battlefield(prison), "nobody paid the {3}"
    assert p1.exile == []
    assert [p.card.name for p in p1.battlefield] == ["Balduvian Bears"], (
        "back under its owner's control, not the Prison controller's"
    )


def test_mudslide_untaps_only_what_the_player_pays_for(set_pool):
    """"At the beginning of each player's upkeep, that player may choose any
    number of tapped creatures without flying they control and pay {2} for each
    creature chosen this way. If the player does, untap those creatures."

    A toll whose *number of payments* the payer picks, so the price is not
    known until the picking is done — which is why it is one production and not
    a ``May`` around an untap. Magnetic Mountain prints the same template with
    a colour where this one has a keyword, and was a card hook until it did.
    """
    pool = set_pool("ICE")
    slide = Permanent(card=pool["Mudslide"])
    one = Permanent(card=pool["Balduvian Bears"], tapped=True)
    two = Permanent(card=pool["Balduvian Bears"], tapped=True)
    lands = [Permanent(card=pool["Snow-Covered Forest"]) for _ in range(4)]
    p0 = PlayerState(name="P0", battlefield=[slide], life=20)
    p1 = PlayerState(name="P1", battlefield=[one, two, *lands], life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 1

    game.resolve_upkeep(1)
    owed = [c for c in game.pending_choices if c.kind == "untap_up_to"]
    assert [c.player_index for c in owed] == [1], "the chooser is the upkeep player"
    assert owed[0].data["amount"] == 2, "any number, capped at what is there"

    assert game.confirm_untap_up_to(1, [game.permanent_id_of(one)])

    assert one.tapped is False
    assert two.tapped is True, "unchosen, so unpaid for and still tapped"
    assert sum(1 for land in lands if land.tapped) == 2, "{2}, once"


def test_mudslide_does_not_offer_a_flyer_or_an_opponents_creature(set_pool):
    """"tapped creatures **without flying** **they control**" — a keyword
    (layer 6) and a seat, neither of which the pure matcher can test. Handed to
    it, both keys would be silently ignored, and the offer would be a strictly
    larger set than the card names.
    """
    pool = set_pool("ICE")
    slide = Permanent(card=pool["Mudslide"])
    flyer = Permanent(card=pool["Silver Erne"], tapped=True)
    ground = Permanent(card=pool["Balduvian Bears"], tapped=True)
    theirs = Permanent(card=pool["Balduvian Bears"], tapped=True)
    p0 = PlayerState(name="P0", battlefield=[slide, theirs], life=20)
    p1 = PlayerState(name="P1", battlefield=[flyer, ground], life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 1

    game.resolve_upkeep(1)
    owed = [c for c in game.pending_choices if c.kind == "untap_up_to"]

    assert owed[0].data["amount"] == 1, "only the grounded creature they control"
    assert not game.confirm_untap_up_to(1, [game.permanent_id_of(flyer)])
    assert not game.confirm_untap_up_to(1, [game.permanent_id_of(theirs)])


def test_leshracs_sigil_looks_at_the_casters_hand_and_takes_a_card(set_pool):
    """"Whenever an opponent casts a green spell, you may pay {B}{B}. If you do,
    look at that player's hand and choose a card from it. The player discards
    that card."

    Duress's template with the hand looked at instead of revealed, and with the
    seat named by the *firing event* rather than by a target — so the frozen
    key is what says whose hand, not whatever the resolution was carrying.
    """
    pool = set_pool("ICE")
    sigil = Permanent(card=pool["Leshrac's Sigil"])
    p0 = PlayerState(name="P0", battlefield=[sigil], life=20, mana_pool={"B": 2})
    p1 = PlayerState(
        name="P1", life=20,
        hand=[pool["Balduvian Bears"], pool["Icy Prison"]],
    )
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Balduvian Bears")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    owed = [c for c in game.pending_choices if c.kind == "revealed_hand_pick"]
    assert len(owed) == 1
    assert owed[0].player_index == 0, "the Sigil's controller chooses"
    assert owed[0].data["victim_index"] == 1, "out of the caster's hand"

    game.auto_resolve_pending_choices()
    game._settle()
    assert [c.name for c in p1.graveyard] == ["Icy Prison"]


def _oath_board(set_pool, hand: list[str]):
    """Oath of Lim-Dûl out, three bears beside it, and *hand* in hand."""
    pool = set_pool("ICE")
    oath = Permanent(card=pool["Oath of Lim-Dûl"])
    bears = [Permanent(card=pool["Balduvian Bears"]) for _ in range(3)]
    p0 = PlayerState(
        name="P0", battlefield=[oath, *bears], life=20,
        hand=[pool[name] for name in hand],
    )
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p0, p1])
    # Seed the sweep's record of the life totals: a starting life total is not
    # a loss, and the sweep announces only a *drop* from what it last saw.
    game.check_state_based_actions()
    return game, p0, oath


def _settle_prompts(game) -> None:
    for _ in range(3):
        game._settle()
        game.auto_resolve_pending_optional_pays()
        game.auto_resolve_pending_choices()
        game._settle()


def test_oath_of_lim_dul_sacrifices_once_per_life_lost(set_pool):
    """"Whenever you lose life, for each 1 life you lost, sacrifice a permanent
    other than this enchantment unless you discard a card."

    Two damage is two losses' worth of repetitions, and the enchantment itself
    is never one of the permanents given up.
    """
    game, p0, oath = _oath_board(set_pool, hand=[])

    game._deal_damage_to_player(p0, 2, source=None)
    _settle_prompts(game)

    assert [c.name for c in p0.graveyard] == ["Balduvian Bears"] * 2
    assert game.is_on_battlefield(oath), "'other than this enchantment'"


def test_oath_of_lim_dul_takes_a_discard_instead(set_pool):
    """The toll, in its cost-is-not-mana spelling: a card in hand buys the
    permanent back."""
    game, p0, _oath = _oath_board(set_pool, hand=["Icy Prison"])

    game._deal_damage_to_player(p0, 1, source=None)
    _settle_prompts(game)

    assert [c.name for c in p0.graveyard] == ["Icy Prison"]
    assert len(p0.battlefield) == 4, "nothing was sacrificed"


def test_oath_of_lim_dul_is_announced_by_a_life_total_that_dropped(set_pool):
    """The condition has no single call site — damage, a cost, a "lose N life"
    effect all take life — so it is announced by the state-based sweep off the
    one thing every route writes. Paying life is a life loss (CR 118.8), and
    the sweep sees it exactly as it sees damage.
    """
    game, p0, _oath = _oath_board(set_pool, hand=[])

    p0.life -= 1
    _settle_prompts(game)

    assert [c.name for c in p0.graveyard] == ["Balduvian Bears"]


def test_oath_of_lim_dul_stays_silent_on_an_opponents_loss(set_pool):
    """"Whenever **you** lose life" — the seat-scoped reading the life *gain*
    trigger beside it already takes."""
    game, p0, _oath = _oath_board(set_pool, hand=[])
    opponent = game.players[1]

    game._deal_damage_to_player(opponent, 3, source=None)
    _settle_prompts(game)

    assert p0.graveyard == []
    assert len(p0.battlefield) == 4


def test_lim_duls_hex_asks_every_player_in_turn(set_pool):
    """"At the beginning of your upkeep, for each player, this enchantment
    deals 1 damage to that player unless they pay {B} or {3}."

    Three pieces at once: a loop over *seats* (the printed "for each player"),
    a "that player" that means a different seat each time round, and CR 118.8's
    alternative cost in its mana spelling.
    """
    pool = set_pool("ICE")
    hex_enchantment = Permanent(card=pool["Lim-Dûl's Hex"])
    swamp = Permanent(card=pool["Snow-Covered Swamp"])
    forests = [Permanent(card=pool["Snow-Covered Forest"]) for _ in range(3)]
    p0 = PlayerState(name="P0", battlefield=[hex_enchantment, swamp], life=20)
    p1 = PlayerState(name="P1", battlefield=forests, life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 0

    game.resolve_upkeep(0)
    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert [c.player_index for c in owed] == [0, 1], "one offer per seat"
    assert owed[0].data["cost"] == {"B": 1}
    assert owed[0].data["cost_alternatives"] == [{"generic": 3}]

    assert game.confirm_optional_pay(0, accept=True)
    assert game.confirm_optional_pay(1, accept=True)
    game._settle()

    assert (p0.life, p1.life) == (20, 20)
    assert swamp.tapped, "the {B} half"
    assert all(forest.tapped for forest in forests), "the {3} half"


def test_lim_duls_hex_damages_a_player_who_cannot_pay_either_cost(set_pool):
    """An offer nobody can afford is never made, and its decline branch is the
    damage — so a board with neither a Swamp nor three lands takes the 1."""
    pool = set_pool("ICE")
    hex_enchantment = Permanent(card=pool["Lim-Dûl's Hex"])
    p0 = PlayerState(name="P0", battlefield=[hex_enchantment], life=20)
    p1 = PlayerState(
        name="P1", life=20,
        battlefield=[Permanent(card=pool["Snow-Covered Forest"])],
    )
    game = Game(players=[p0, p1])
    game.active_player_index = 0

    game.resolve_upkeep(0)
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert (p0.life, p1.life) == (19, 19)


def test_seizures_offers_the_toll_to_the_creatures_controller(set_pool):
    """"Whenever enchanted creature becomes tapped, this Aura deals 3 damage to
    that creature's controller unless that player pays {3}."

    The seat is "that **creature's** controller", which the tap announcement
    freezes under its own key — where an upkeep or a cast freezes "that
    player". The lowering named the second key without asking which event it
    was under, so the handler found no seat and this Aura did nothing at all,
    on every tap, since it was printed.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    seizures = Permanent(card=pool["Seizures"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[seizures], life=20)
    p1 = PlayerState(name="P1", battlefield=[bears], life=20)
    game = Game(players=[p0, p1])
    attach_aura(seizures, bears)

    game.become_tapped(bears)
    game._settle()

    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert [c.player_index for c in owed] == [1], "the creature's controller"
    assert owed[0].data["cost"] == {"generic": 3}

    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert (p0.life, p1.life) == (20, 17), "unpaid, so the damage lands"
# --- end W2G1 ---


# --- W2G4: Auras and attachments ---


def test_cloak_of_confusion_lets_its_controller_trade_damage_for_a_discard(set_pool):
    """Ice Age's Cloak of Confusion: "Whenever enchanted creature attacks and
    isn't blocked, you may have it assign no combat damage this turn. If you do,
    defending player discards a card at random."

    The Aura's trigger, not the creature's — CR 113.7a — so it fires from the
    attacker's attachments rather than from its own compiled program.
    """
    program = compile_card_oracle(set_pool("ICE")["Cloak of Confusion"])
    assert program.supported, program.reason
    trigger = next(
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "attacks_unblocked"
    )
    # The noun the attached channel tests the host against (CR 613 layer 4: an
    # Equipment on an unanimated artifact is not a creature).
    assert trigger.condition.payload.get("combatant_attached") == "creature"
    assert trigger.instruction.kind == "may"
    (action,) = trigger.instruction.payload["action"]
    # The pronoun names the enchanted creature, never the Aura — an Aura
    # assigns no combat damage in any case, so a mark on the source is the
    # card doing nothing at all.
    assert action.kind == "assign_no_combat_damage_until_eot"
    assert action.payload == {"subject": "attached"}
    # "If you do" — the discard happens only behind the offer, and its seat is
    # the one the fire site froze rather than one anybody targeted.
    (rider,) = trigger.instruction.payload["then"]
    assert rider.kind == "discard_x_target_cards"
    assert rider.payload == {"amount": 1, "who": "defending_player"}


def _cloak_board(set_pool):
    """P1's bear wearing Cloak of Confusion, with a card in P2's hand."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])  # a vanilla 2/2, no text
    cloak = Permanent(card=pool["Cloak of Confusion"])
    p1 = PlayerState(name="P1", battlefield=[bear, cloak], life=20)
    p2 = PlayerState(name="P2", life=20, hand=[pool["Balduvian Bears"]])
    game = Game(players=[p1, p2])
    attach_aura(cloak, bear)
    game._settle()
    _nosick(bear)
    return game, bear, cloak


def _attack_unblocked(game):
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    game._fire_unblocked_attack_triggers()


def test_cloak_of_confusion_fires_from_the_aura_and_takes_a_card_at_random(set_pool):
    """The whole effect in a real game: the trigger is announced off the
    attacker's attachments, the offer marks the *creature*, and the seat the
    combat froze loses a card.
    """
    game, bear, cloak = _cloak_board(set_pool)
    _attack_unblocked(game)

    item = game.stack[-1]
    assert item.source_permanent is cloak
    assert item.trigger_context["trigger_defending_player_index"] == 1
    game.resolve_top_of_stack()
    # The offer is a decision the controller owes (CR 117.3b) — accepted here,
    # which is the half of the card the discard is behind.
    game.confirm_optional_pay(0, "Cloak of Confusion", accept=True)

    assert bear.metadata.get("assigns_no_combat_damage_until_eot") is True
    assert cloak.metadata.get("assigns_no_combat_damage_until_eot") is None
    assert game.players[1].hand == []
    assert len(game.players[1].graveyard) == 1


def test_cloak_of_confusion_stops_being_a_trigger_once_it_is_detached(set_pool):
    """CR 611.3b — removal is the absence of a contribution. The Aura's trigger
    is found by scanning the attacker's attachments, so detaching it is the
    whole of taking the ability away.
    """
    from engine.auras import detach_aura

    game, bear, cloak = _cloak_board(set_pool)
    detach_aura(cloak, bear)
    game._settle()
    _attack_unblocked(game)

    assert game.stack == []
    assert bear.metadata.get("assigns_no_combat_damage_until_eot") is None


def test_a_cloaked_attacker_assigns_no_combat_damage(set_pool):
    """The mark is read by ``combat_assignment``, so the defending player takes
    nothing — the half of the card that pays for the discard."""
    from engine.combat_assignment import combat_damage_assigned_by

    game, bear, _ = _cloak_board(set_pool)
    assert combat_damage_assigned_by(bear) == 2
    _attack_unblocked(game)
    game.resolve_top_of_stack()
    game.confirm_optional_pay(0, "Cloak of Confusion", accept=True)

    assert combat_damage_assigned_by(bear) == 0


def _aggression_board(set_pool):
    """P1's Aggression on P2's bear — the way the card is printed to be used.

    The trigger's seat is the *enchanted* creature's controller, not the Aura's,
    so putting the two on opposite sides is what the scoping is about.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    aggression = Permanent(card=pool["Aggression"])
    p1 = PlayerState(name="P1", battlefield=[aggression], life=20)
    p2 = PlayerState(name="P2", battlefield=[bear], life=20)
    game = Game(players=[p1, p2])
    attach_aura(aggression, bear)
    game._settle()
    _nosick(bear)
    return game, bear, aggression


def test_aggression_grants_first_strike_and_trample(set_pool):
    game, bear, _ = _aggression_board(set_pool)

    assert bear.has_keyword("first strike")
    assert bear.has_keyword("trample")


def test_aggression_destroys_a_creature_that_sat_out_its_controllers_end_step(set_pool):
    game, bear, _ = _aggression_board(set_pool)

    game.active_player_index = 1
    game.resolve_end_step(1)
    while game.stack:
        game.resolve_top_of_stack()

    assert bear not in list(game.controlled_by(game.players[1]))
    assert [card.name for card in game.players[1].graveyard] == ["Balduvian Bears"]


def test_aggression_spares_a_creature_that_attacked(set_pool):
    """CR 603.4's gate read off the *enchanted* creature. Asked of the Aura it
    would always answer "didn't attack" — an Aura never does — and the card
    would destroy its host every turn."""
    game, bear, _ = _aggression_board(set_pool)

    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [0], defending_player_index=0)[0]
    game.resolve_end_step(1)
    while game.stack:
        game.resolve_top_of_stack()

    assert bear in list(game.controlled_by(game.players[1]))


def test_aggression_fires_on_the_hosts_controllers_end_step_and_no_other(set_pool):
    """The seat is whoever controls the enchanted creature (CR 109.5 does not
    reach it — the clause names the *host's* controller), so the Aura's own
    controller's end step must leave the creature alone."""
    game, bear, _ = _aggression_board(set_pool)

    game.active_player_index = 0
    game.resolve_end_step(0)
    while game.stack:
        game.resolve_top_of_stack()

    assert bear in list(game.controlled_by(game.players[1]))


def test_a_detached_aggression_destroys_nothing(set_pool):
    from engine.auras import detach_aura

    game, bear, aggression = _aggression_board(set_pool)
    detach_aura(aggression, bear)
    game._settle()

    game.active_player_index = 1
    game.resolve_end_step(1)
    while game.stack:
        game.resolve_top_of_stack()

    assert bear in list(game.controlled_by(game.players[1]))
    assert not bear.has_keyword("first strike")


def _snow_devil_board(set_pool, *, snow_land: bool):
    """P1's Snow Devil on P1's bear, with or without a snow land under P1."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    devil = Permanent(card=pool["Snow Devil"])
    mine = [bear, devil]
    if snow_land:
        mine.append(Permanent(card=pool["Snow-Covered Forest"]))
    p1 = PlayerState(name="P1", battlefield=mine, life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pool["Balduvian Bears"])], life=20)
    game = Game(players=[p1, p2])
    attach_aura(devil, bear)
    game._settle()
    _nosick(bear)
    for perm in game.controlled_by(game.players[1]):
        _nosick(perm)
    return game, bear, devil


def _block_with(game, blocker):
    """Put *blocker* (P1's) in front of P2's attacker."""
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [0], defending_player_index=0)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    game.declare_blockers(0, {game.battlefield_index_of(blocker): [0]})
    game._settle()


def test_snow_devil_always_grants_flying(set_pool):
    game, bear, _ = _snow_devil_board(set_pool, snow_land=True)

    assert bear.has_keyword("flying")


def test_snow_devil_grants_first_strike_only_while_blocking(set_pool):
    """Both halves of the condition are asked, and a conjunct dropped would be
    a permanent first-striker. Not blocking: no first strike."""
    game, bear, _ = _snow_devil_board(set_pool, snow_land=True)
    assert not bear.has_keyword("first strike")

    _block_with(game, bear)

    assert bear.blocking_attacker_index is not None
    assert bear.has_keyword("first strike")


def test_snow_devil_grants_nothing_without_a_snow_land(set_pool):
    """The board half, with the combat half satisfied — so a test that only
    blocked would pass on a card that had dropped this conjunct."""
    game, bear, _ = _snow_devil_board(set_pool, snow_land=False)
    _block_with(game, bear)

    assert bear.blocking_attacker_index is not None
    assert not bear.has_keyword("first strike")


def test_snow_devil_asks_the_condition_on_every_recompute(set_pool):
    """CR 611.3a. Removing the snow land takes first strike away mid-combat
    with nothing to undo."""
    game, bear, _ = _snow_devil_board(set_pool, snow_land=True)
    _block_with(game, bear)
    assert bear.has_keyword("first strike")

    land = next(
        perm for perm in game.controlled_by(game.players[0])
        if perm.card.name == "Snow-Covered Forest"
    )
    game.remove_from_battlefield(land)
    game._settle()

    assert not bear.has_keyword("first strike")


def test_a_detached_snow_devil_grants_neither_keyword(set_pool):
    from engine.auras import detach_aura

    game, bear, devil = _snow_devil_board(set_pool, snow_land=True)
    _block_with(game, bear)
    detach_aura(devil, bear)
    game._settle()

    assert not bear.has_keyword("flying")
    assert not bear.has_keyword("first strike")


def test_snow_devils_snow_land_is_counted_on_the_auras_controllers_board(set_pool):
    """CR 109.5: "you" is the Aura's controller, so an Aura put on an
    opponent's creature still reads its own controller's lands."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    devil = Permanent(card=pool["Snow Devil"])
    p1 = PlayerState(
        name="P1",
        battlefield=[devil, Permanent(card=pool["Snow-Covered Forest"])],
        life=20,
    )
    p2 = PlayerState(name="P2", battlefield=[bear], life=20)
    game = Game(players=[p1, p2])
    attach_aura(devil, bear)
    game._settle()
    _nosick(bear)

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    attacker = next(iter(game.controlled_by(game.players[0])))
    # P1 has no creature to attack with, so the block is staged directly: what
    # is under test is which board the snow land is counted on.
    bear.blocking_attacker_index = 0
    game._settle()

    assert bear.has_keyword("first strike")


def _caribou_board(set_pool):
    """A Plains wearing Caribou Range, with {W}{W} in P1's pool."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    plains = Permanent(card=pool["Snow-Covered Plains"])
    aura = Permanent(card=pool["Caribou Range"])
    p1 = PlayerState(name="P1", battlefield=[plains, aura], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(aura, plains)
    game._settle()
    return game, plains, aura


def test_caribou_range_grants_its_land_the_token_maker(set_pool):
    """The quoted ability reaches the host through ``effective_card``, so the
    compiler builds it for the land as though the land had printed it."""
    game, plains, aura = _caribou_board(set_pool)

    program = compile_card_oracle(plains.effective_card)
    (granted,) = [
        ability for ability in program.activated_abilities
        if ability.instruction is not None
        and ability.instruction.kind == "create_token"
    ]
    assert granted.supported
    assert granted.cost.mana["W"] == 2
    assert granted.cost.requires_tap

    from engine.auras import detach_aura

    detach_aura(aura, plains)
    game._settle()
    assert not compile_card_oracle(plains.effective_card).activated_abilities


def test_caribou_range_sacrifices_a_caribou_token_for_a_life(set_pool):
    """The Aura's own ability, whose cost names a token by creature type — the
    narrowing that has to survive to the charger, or the cost eats anything."""
    game, plains, aura = _caribou_board(set_pool)
    (ability,) = compile_card_oracle(aura.card).activated_abilities

    assert ability.cost.sacrifice_filter == {
        "type_filter": "creature",
        "subtype_filter": "caribou",
        "token_only": True,
    }
    assert ability.instruction.kind == "target_gains_life"
    assert ability.instruction.payload == {"amount": 1, "recipient": "caster"}


def test_the_caribou_sacrifice_spares_a_printed_caribou(set_pool):
    """"A Caribou **token**" is not "a Caribou": the word is a fact about the
    object (CR 111.1), and dropped it would let the cost eat a real creature."""
    from engine.handlers._common import permanent_matches_filter
    from engine.tokens import make_token_card

    aura = Permanent(card=set_pool("ICE")["Caribou Range"])
    (ability,) = compile_card_oracle(aura.card).activated_abilities
    described = ability.cost.sacrifice_filter

    caribou = make_token_card(
        "Caribou", 0, 1, "Creature — Caribou", colors=("W",)
    )
    made = Permanent(card=caribou, metadata={"is_token": True})
    printed = Permanent(card=caribou)  # the same characteristics, not a token

    assert permanent_matches_filter(made, described)
    assert not permanent_matches_filter(printed, described)


def _breath_board(set_pool):
    """Breath of Dreams out, with one green creature and one that is not."""
    pool = set_pool("ICE")
    breath = Permanent(card=pool["Breath of Dreams"])
    green = Permanent(card=pool["Balduvian Bears"])   # green, vanilla
    blue = Permanent(card=pool["Phantasmal Mount"])   # blue
    p1 = PlayerState(name="P1", battlefield=[breath, green, blue], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game._settle()
    return game, breath, green, blue


def test_breath_of_dreams_gives_green_creatures_a_cumulative_upkeep(set_pool):
    """"Green creatures have "Cumulative upkeep {1}."" — the ability reaches
    the creature through ``effective_card``, so the upkeep step builds the
    trigger without knowing this enchantment exists."""
    game, _, green, blue = _breath_board(set_pool)

    (trigger,) = [
        trig for trig in compile_card_oracle(green.effective_card).triggered_abilities
        if trig.instruction is not None
        and trig.instruction.kind == "cumulative_upkeep"
    ]
    assert trigger.condition.kind == "upkeep_self"
    assert trigger.instruction.payload["mana"] == {"generic": 1}
    assert not [
        trig for trig in compile_card_oracle(blue.effective_card).triggered_abilities
        if trig.instruction is not None
        and trig.instruction.kind == "cumulative_upkeep"
    ]


def test_breath_of_dreams_sacrifices_an_unpaid_green_creature(set_pool):
    """The whole mechanism end to end: the granted ability is a real CR 702.24
    upkeep, so declining it sacrifices the creature."""
    game, breath, green, blue = _breath_board(set_pool)

    game.active_player_index = 0
    game.resolve_upkeep(
        0,
        human_choices={"Balduvian Bears": False, "Breath of Dreams": False},
    )
    game._settle()

    board = list(game.controlled_by(game.players[0]))
    assert green not in board
    assert blue in board


def test_breath_of_dreams_stops_granting_when_it_leaves(set_pool):
    """CR 611.3b again: the grant is derived from the source recorded on the
    creature, so removing the enchantment takes the upkeep away with nothing to
    undo."""
    game, breath, green, _ = _breath_board(set_pool)
    assert "cumulative upkeep" in green.effective_card.oracle_text.lower()

    game.remove_from_battlefield(breath)
    game._settle()

    assert "cumulative upkeep" not in (green.effective_card.oracle_text or "").lower()


def _snowblind_board(set_pool, *, mine: int, theirs: int):
    """P1's bear under P1's Snowblind, with snow lands on both sides."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])  # a vanilla 2/2
    snowblind = Permanent(card=pool["Snowblind"])
    p1 = PlayerState(
        name="P1",
        battlefield=[bear, snowblind]
        + [Permanent(card=pool["Snow-Covered Forest"]) for _ in range(mine)],
        life=20,
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=pool["Snow-Covered Island"]) for _ in range(theirs)],
        life=20,
    )
    game = Game(players=[p1, p2])
    attach_aura(snowblind, bear)
    game._settle()
    return game, bear, snowblind


def test_snowblind_counts_its_controllers_snow_lands_out_of_combat(set_pool):
    game, bear, _ = _snowblind_board(set_pool, mine=1, theirs=3)

    # X = 1, Y = min(X, toughness - 1) = 1.
    assert (bear.effective_power, bear.effective_toughness) == (1, 1)


def test_snowblind_clamps_the_toughness_but_not_the_power(set_pool):
    """"Y is equal to X or to enchanted creature's toughness minus 1, whichever
    is smaller" — the clamp is what stops the Aura killing what it enchants, and
    it applies to Y alone."""
    game, bear, _ = _snowblind_board(set_pool, mine=3, theirs=0)

    assert (bear.effective_power, bear.effective_toughness) == (-1, 1)


def test_snowblind_counts_the_defending_players_snow_lands_while_attacking(set_pool):
    """CR 506.2. The condition is read at every recompute, so the same board
    gives two different answers depending on whether the creature is in
    combat — which is the whole card."""
    game, bear, _ = _snowblind_board(set_pool, mine=0, theirs=3)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    bear.attacking = True
    bear.defending_player_index = 1
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (-1, 1)


def test_a_detached_snowblind_takes_its_penalty_with_it(set_pool):
    from engine.auras import detach_aura

    game, bear, snowblind = _snowblind_board(set_pool, mine=2, theirs=0)
    assert bear.effective_power == 0

    detach_aura(snowblind, bear)
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_snowblind_ignores_a_nonsnow_land(set_pool):
    """The noun phrase is read by the grammar's own parser and refused if the
    matcher cannot test it, so "snow" is a narrowing rather than decoration —
    dropped, the card would count every land on the board."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    snowblind = Permanent(card=pool["Snowblind"])
    p1 = PlayerState(
        name="P1",
        battlefield=[bear, snowblind] + [Permanent(card=pool["Forest"]) for _ in range(3)],
        life=20,
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(snowblind, bear)
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_aggression_cannot_be_put_on_a_wall(set_pool, catalog_by_name):
    """"Enchant **non-Wall** creature" (CR 702.5). The negation is a prefix on
    a noun the enchant table already knows, and without it the whole phrase
    missed the table and the permissive fallback said yes — so the restriction
    the card prints was enforced by nothing at all.
    """
    from engine.auras import enchant_card_refusal

    pool = set_pool("ICE")
    wall = Permanent(card=catalog_by_name["Wall of Stone"])
    bear = Permanent(card=pool["Balduvian Bears"])
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[wall, bear], life=20),
            PlayerState(name="P2", life=20),
        ]
    )
    game._settle()

    assert enchant_card_refusal(game, pool["Aggression"], 0, wall) is not None
    assert enchant_card_refusal(game, pool["Aggression"], 0, bear) is None


# --- end W2G4 ---


# --- W3G4: coin flips, ante, noted mana ---
def test_iceberg_enters_with_the_announced_x_in_ice_counters(set_pool):
    """"This enchantment enters with **X ice** counters on it."

    Round 18 made the counter *kind* data for the X form (Balduvian Hydra) and
    the *number* data for the named form (Rasputin), and the crossing case fell
    between the two: the named reader matched Iceberg's shape and then refused
    "x" as a number word. The card compiled supported, entered with an empty
    counter store, and could never pay for its own second ability — which is
    the whole card.
    """
    from engine.named_counters import counters_on

    pool = set_pool("ICE")
    p0 = PlayerState(name="P0", hand=[pool["Iceberg"]], life=20)
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"

    game.cast_from_hand(0, "Iceberg", x_value=3)
    game._settle()

    berg = p0.battlefield[0]
    assert counters_on(berg, "ice") == 3

    # And the counters are spendable: "Remove an ice counter from this
    # enchantment: Add {C}" is the ability the entry state exists to feed.
    berg.metadata["summoning_sickness_turn"] = -99
    game.activate_permanent_ability(0, "Iceberg", permanent_index=0, ability_index=1)
    game._settle()

    assert counters_on(berg, "ice") == 2
    assert p0.mana_pool["C"] == 1


def test_iceberg_cast_for_no_x_enters_with_nothing(set_pool):
    """X is the value announced on casting (CR 601.2b), not a printed number, so
    an Iceberg cast for zero really does arrive empty. Asserted because the loop
    that places the counters has to read a *missing* X the same way — a default
    of one would be a card nobody printed."""
    from engine.named_counters import counters_on

    pool = set_pool("ICE")
    p0 = PlayerState(name="P0", hand=[pool["Iceberg"]], life=20)
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"

    game.cast_from_hand(0, "Iceberg", x_value=0)
    game._settle()

    assert counters_on(p0.battlefield[0], "ice") == 0


def test_the_x_named_counter_reader_declines_the_printed_number_form(set_pool):
    """The two readers are separate on purpose and must stay disjoint: a printed
    count is read off the line and X is read off the cast, at different times.
    A reader that answered both would place one counter where Rasputin prints
    seven, or seven where Iceberg's X was three."""
    from engine.enter_effects import (
        enters_with_named_counter, enters_with_x_named_counters,
    )

    assert enters_with_x_named_counters(
        "this enchantment enters with x ice counters on it"
    ) == "ice"
    assert enters_with_named_counter(
        "this enchantment enters with x ice counters on it"
    ) is None
    assert enters_with_x_named_counters(
        "this creature enters with seven dream counters on it"
    ) is None
    # A P/T counter is the other X reader's, not this one's.
    assert enters_with_x_named_counters(
        "this creature enters with x +1/+1 counters on it"
    ) is None
# --- end W3G4 ---
