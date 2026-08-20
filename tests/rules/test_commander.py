"""Tests for Magic: The Gathering Comprehensive Rules 903 — Commander.

One test (or a small group) per rule sentence of CR 903, plus the rules
elsewhere in the CR that only exist because of Commander: the command zone
itself (CR 408.1, 408.3) and the two state-based actions the variant adds
(CR 704.6c, 704.6d).

CR 903.12's Brawl option has its own file, ``test_brawl.py``. Everything Brawl
inherits unchanged is tested here — 903.12a is "the normal rules for the
Commander variant with the following modifications", so testing the shared half
twice would be testing one implementation twice.

Deck construction (CR 903.5) is enforced at deck-building time rather than
during play, so ``web/deck_legality.validate_deck`` is exercised here alongside
the engine: the rule is one rule, and splitting its tests across files would
hide half of it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.commander import (
    BRAWL,
    COMMANDER,
    COMMANDER_TAX,
    LETHAL_COMMANDER_DAMAGE,
    can_be_commander,
    color_identity,
    commander_type_problem,
    deck_card_problem,
    deck_size,
    starting_life,
)
from engine.copies import become_copy
from engine.models import CardDefinition, CardFace, Permanent
from web.app import store
from web.deck_legality import validate_deck

from tests.helpers import _mk_card, _nosick, client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commander_game(
    pool,
    *,
    variant: str = COMMANDER,
    commander: str = "Gadrak, the Crown-Scourge",
    opponent_commander: str = "Azusa, Lost but Seeking",
    seats: int = 2,
    deal: bool = True,
) -> Game:
    """A Commander (or Brawl) game with a designated commander per seat.

    The library is filler — every rule under test here is about the command
    zone, the tax, or the two ways back to it, none of which reads the deck.
    """
    filler = [pool["Mountain"]] * 30
    players = [PlayerState(name=f"P{i + 1}", library=list(filler)) for i in range(seats)]
    game = Game(players=players, commander_variant=variant)
    game.designate_commander(0, pool[commander])
    for seat in range(1, seats):
        game.designate_commander(seat, pool[opponent_commander])
    if deal:
        game.deal_opening_hands(0)
    return game


def _catalog_entry(name, *, type_line="Creature — Test", mana_cost="", oracle_text="",
                   produced_mana=(), key="commander"):
    """A catalog payload entry, the shape ``validate_deck`` reads."""
    return {
        "name": name, "type_line": type_line, "mana_cost": mana_cost,
        "oracle_text": oracle_text, "produced_mana": list(produced_mana),
        "legalities": {key: "legal"},
    }


def _catalog(*entries):
    return {entry["name"].casefold(): entry for entry in entries}


def _deck(*pairs):
    return [{"name": name, "count": count} for name, count in pairs]


# ---------------------------------------------------------------------------
# 903.1 — the variant, and what an ordinary game is not
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.1")
def test_commander_is_opt_in_and_an_ordinary_game_has_none_of_it(set_pool):
    """"The Commander variant uses all the normal rules for a Magic game, with
    the following additions." A game that is not one gets no additions."""
    pool = set_pool("M21")
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.designate_commander(0, pool["Gadrak, the Crown-Scourge"])

    assert game.is_commander_game is False
    game.deal_opening_hands(0)
    assert game.players[0].life == 20            # not 903.7's 40
    assert game.players[0].command_zone == []    # not 903.6's command zone
    assert game.commander_tax(0, pool["Gadrak, the Crown-Scourge"]) == 0


@pytest.mark.cr("903.1")
def test_a_commander_game_is_one_when_the_variant_is_set(set_pool):
    game = _commander_game(set_pool("M21"))
    assert game.is_commander_game is True


# ---------------------------------------------------------------------------
# 903.2 — two-player or multiplayer
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.2")
def test_commander_supports_two_player_and_multiplayer_games(set_pool):
    """"A Commander game may be a two-player game or a multiplayer game." The
    multiplayer default is the Free-for-All variant (CR 806), which this engine
    already runs — so the variant has to seat any number, not exactly two."""
    pool = set_pool("M21")
    duel = _commander_game(pool, seats=2)
    table = _commander_game(pool, seats=4)

    assert [len(p.command_zone) for p in duel.players] == [1, 1]
    assert [len(p.command_zone) for p in table.players] == [1, 1, 1, 1]
    assert all(p.life == 40 for p in table.players)


# ---------------------------------------------------------------------------
# 903.3 — the designation
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.3")
def test_a_commander_must_be_a_legendary_creature_card(set_pool):
    pool = set_pool("M21")
    assert can_be_commander(pool["Gadrak, the Crown-Scourge"], COMMANDER)
    # A legendary artifact is not a creature card.
    assert not can_be_commander(pool["Chromatic Orrery"], COMMANDER)
    # A nonlegendary creature is not a commander however big.
    assert not can_be_commander(pool["Alpine Watchdog"], COMMANDER)


@pytest.mark.cr("903.3")
def test_commander_type_problem_names_the_fault(set_pool):
    pool = set_pool("M21")
    assert "not legendary" in commander_type_problem(pool["Alpine Watchdog"], COMMANDER)
    assert "legendary creature" in commander_type_problem(
        pool["Chromatic Orrery"], COMMANDER
    )


@pytest.mark.cr("903.3")
def test_a_vehicle_may_be_a_commander():
    """CR 903.3(b): "a Vehicle card". A Vehicle is an artifact subtype, so the
    card is legendary and named on the type line rather than being a creature."""
    vehicle = _mk_card("Test Transport", "Legendary Artifact — Vehicle")
    assert can_be_commander(vehicle, COMMANDER)


@pytest.mark.cr("903.3")
def test_the_designation_is_an_attribute_of_the_card_across_zones(set_pool):
    """"This designation is not a characteristic of the object represented by
    the card; rather, it is an attribute of the card itself. The card retains
    this designation even when it changes zones.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]

    # In the command zone.
    assert game.is_commander_card(0, gadrak)
    # In the graveyard.
    game.players[0].command_zone.clear()
    game.players[0].graveyard.append(gadrak)
    assert game.is_commander_card(0, gadrak)
    # On the battlefield.
    game.players[0].graveyard.clear()
    game.players[0].battlefield.append(Permanent(card=gadrak))
    game._sync_control()
    assert game.is_commander_card(0, gadrak)


@pytest.mark.cr("903.3")
def test_the_designation_is_per_seat_not_per_card_object(set_pool):
    """The catalog shares one ``CardDefinition`` between every deck, so the
    designation has to be the *owner's*: an opponent's copy of the same card is
    not a commander."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]

    assert game.is_commander_card(0, gadrak)
    assert not game.is_commander_card(1, gadrak)


@pytest.mark.cr("903.3")
def test_designating_the_same_commander_twice_is_refused(set_pool):
    pool = set_pool("M21")
    game = _commander_game(pool, deal=False)
    assert game.designate_commander(0, pool["Gadrak, the Crown-Scourge"]) is False
    assert len(game.commanders_of(0)) == 1


@pytest.mark.cr("903.3a")
def test_can_be_your_commander_overrides_the_type_requirement():
    """"Some cards have an ability that states the card can be your commander.
    This ability modifies the rules for deck construction." So it admits a card
    903.3's list does not."""
    planeswalker = _mk_card(
        "Test Walker", "Legendary Planeswalker — Test",
        "Test Walker can be your commander.",
    )
    assert can_be_commander(planeswalker, COMMANDER)
    # …and the same card without the line is refused in Commander.
    plain = _mk_card("Plain Walker", "Legendary Planeswalker — Test")
    assert not can_be_commander(plain, COMMANDER)


@pytest.mark.cr("903.3d")
def test_controlling_a_commander_means_a_commander_on_the_battlefield(set_pool):
    """"If an effect refers to controlling a commander, it refers to a permanent
    on the battlefield that is a commander.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)
    commander = Permanent(card=pool["Gadrak, the Crown-Scourge"])
    ordinary = Permanent(card=pool["Alpine Watchdog"])
    game.players[0].battlefield.extend([commander, ordinary])
    game._sync_control()

    assert game.is_commander_permanent(commander) is True
    assert game.is_commander_permanent(ordinary) is False


@pytest.mark.cr("903.3d")
def test_a_permanent_copying_a_commander_is_not_a_commander(set_pool):
    """CR 903.3's example: "A permanent that's copying a commander (such as a
    Body Double, for example, copying a commander in a player's graveyard) is
    not a commander." The designation rides the printed card, so the copy — a
    different card wearing the commander's characteristics — is not one."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    clone = Permanent(card=pool["Alpine Watchdog"])
    commander = Permanent(card=pool["Gadrak, the Crown-Scourge"])
    game.players[0].battlefield.extend([clone, commander])
    game._sync_control()
    become_copy(clone, commander)

    assert clone.effective_card.name == "Gadrak, the Crown-Scourge"
    assert game.is_commander_permanent(clone) is False


# ---------------------------------------------------------------------------
# 903.4 — colour identity
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.4")
def test_colour_identity_reads_the_mana_cost_and_the_rules_text(set_pool):
    """"The color or colors of any mana symbols in that card's mana cost or
    rules text.\""""
    pool = set_pool("M21")
    assert color_identity(pool["Gadrak, the Crown-Scourge"]) == frozenset("R")
    assert color_identity(pool["Radha, Heart of Keld"]) == frozenset("RG")
    # A mana symbol in the rules text alone still counts (CR 903.4's Bosh
    # example): a colourless cost with a coloured activation is that colour.
    bosh = _mk_card(
        "Test Golem", "{8}", "Legendary Artifact Creature — Golem",
        "{3}{R}, Sacrifice an artifact: This creature deals damage equal to the "
        "sacrificed artifact's mana value to any target.",
    )
    assert color_identity(bosh) == frozenset("R")


@pytest.mark.cr("903.4")
def test_a_hybrid_symbol_contributes_both_its_colours():
    """CR 903.4's Wort example: {R/G} is red *and* green, so a Wort deck's
    identity is two colours rather than none."""
    wort = _mk_card("Test Raidmother", "{4}{R/G}{R/G}", "Legendary Creature — Goblin", "")
    assert color_identity(wort) == frozenset("RG")


@pytest.mark.cr("903.4")
def test_a_basic_land_types_intrinsic_mana_is_part_of_its_identity(set_pool):
    """A dual land's printed text is nothing but reminder text, which CR 903.4c
    throws away — its identity comes from CR 305.6's intrinsic mana ability,
    which its basic land types give it."""
    pool = set_pool("3ED")
    assert color_identity(pool["Badlands"]) == frozenset("BR")
    assert color_identity(pool["Forest"]) == frozenset("G")


@pytest.mark.cr("903.4", "903.4a")
def test_the_derived_colour_identity_matches_the_pool(catalog):
    """CR 903.4a establishes colour identity before the game begins, so it is a
    property of the card and can be checked card by card.

    The engine *derives* it (a token, a test fixture and an invented card have
    no ingested field and would silently come back colourless). This holds that
    derivation to the authority for every card the engine ships — the direction
    that catches a drift, since a wrong derivation is a deck check that quietly
    passes.
    """
    mismatched = [
        (card.name, sorted(color_identity(card)), sorted(card.color_identity))
        for card in catalog
        if color_identity(card) != frozenset(card.color_identity)
    ]
    assert not mismatched, f"derived colour identity disagrees with the pool: {mismatched}"


@pytest.mark.cr("903.4c")
def test_reminder_text_is_ignored():
    """"Reminder text is ignored when determining a card's color identity.\""""
    card = _mk_card(
        "Test Reminder", "{2}", "Artifact",
        "This artifact has vigilance. (Attacking doesn't cause it to tap. {W} is "
        "not part of this.)",
    )
    assert color_identity(card) == frozenset()


@pytest.mark.cr("903.4d")
def test_the_back_face_of_a_double_faced_card_counts():
    """"The back face of a double-faced card is included when determining a
    card's color identity. This is an exception to rule 712.8a.\""""
    card = CardDefinition(
        name="Test Scholar", mana_cost="", cmc=3.0,
        type_line="Creature — Human", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw={},
        layout="transform",
        faces=(
            CardFace(name="Test Scholar", mana_cost="{2}{U}", type_line="Creature — Human"),
            CardFace(
                name="Test Brute", mana_cost="", type_line="Creature — Human",
                oracle_text="At the beginning of your upkeep, {R}: draw a card.",
            ),
        ),
    )
    assert color_identity(card) == frozenset("UR")


@pytest.mark.cr("903.4f")
def test_a_player_with_no_commander_has_an_undefined_colour_identity(set_pool):
    """"If an ability refers to the colors or number of colors in a commander's
    color identity, that quality is undefined if that player doesn't have a
    commander." The engine reports the empty set, which is what "that part of
    the ability won't do anything" means to a caller."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    assert game.commander_color_identity(0) == frozenset("R")

    game.players[1].commanders.clear()
    assert game.commander_color_identity(1) == frozenset()


# ---------------------------------------------------------------------------
# 903.5 — deck construction
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.5a")
def test_a_commander_deck_is_exactly_one_hundred_cards():
    """"Each deck must contain exactly 100 cards, including its commander. In
    other words, the minimum deck size and the maximum deck size are both 100.\""""
    assert deck_size(COMMANDER) == 100
    catalog = _catalog(
        _catalog_entry("Test Legend", type_line="Legendary Creature — Test", mana_cost="{R}"),
        _catalog_entry("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",)),
    )
    commander = _deck(("Test Legend", 1))

    short = validate_deck(_deck(("Mountain", 98)), "commander", catalog, commander=commander)
    assert any("requires at least 99" in p for p in short["problems"])

    long = validate_deck(_deck(("Mountain", 100)), "commander", catalog, commander=commander)
    assert any("at most 99" in p for p in long["problems"])

    exact = validate_deck(_deck(("Mountain", 99)), "commander", catalog, commander=commander)
    assert exact["legal"] is True, exact["problems"]


@pytest.mark.cr("903.5b")
def test_every_nonbasic_card_must_have_a_different_name():
    """"Other than basic lands, each card in a Commander deck must have a
    different English name.\""""
    catalog = _catalog(
        _catalog_entry("Test Legend", type_line="Legendary Creature — Test", mana_cost="{R}"),
        _catalog_entry("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",)),
        _catalog_entry("Test Spell", type_line="Instant", mana_cost="{R}"),
    )
    res = validate_deck(
        _deck(("Test Spell", 2), ("Mountain", 97)), "commander", catalog,
        commander=_deck(("Test Legend", 1)),
    )
    assert any("1-of limit" in p for p in res["problems"])
    # Basic lands are exempt — 97 Mountains above raised no copy problem.
    assert not any("Mountain" in p and "limit" in p for p in res["problems"])


@pytest.mark.cr("903.5c")
def test_a_cards_colour_identity_must_fit_inside_the_commanders():
    """"A card can be included in a Commander deck only if every color in its
    color identity is also found in the color identity of the deck's commander.\""""
    identity = frozenset("RG")
    inside = _catalog_entry("Test Gruul", mana_cost="{R}{G}")
    also_inside = _catalog_entry("Test Colourless", mana_cost="{2}")
    outside = _catalog_entry("Test Blue", mana_cost="{1}{U}")

    assert deck_card_problem(inside, identity, COMMANDER) is None
    assert deck_card_problem(also_inside, identity, COMMANDER) is None
    problem = deck_card_problem(outside, identity, COMMANDER)
    assert problem is not None and "903.5c" in problem


@pytest.mark.cr("903.5c")
def test_the_deck_validator_reports_an_off_colour_card():
    catalog = _catalog(
        _catalog_entry("Test Legend", type_line="Legendary Creature — Test", mana_cost="{R}"),
        _catalog_entry("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",)),
        _catalog_entry("Test Counterspell", type_line="Instant", mana_cost="{U}{U}"),
    )
    res = validate_deck(
        _deck(("Test Counterspell", 1), ("Mountain", 98)), "commander", catalog,
        commander=_deck(("Test Legend", 1)),
    )
    assert res["legal"] is False
    assert any("Test Counterspell" in p and "903.5c" in p for p in res["problems"])
    assert res["commander_identity"] == "R"


@pytest.mark.cr("903.5d")
def test_a_land_with_a_basic_land_type_is_judged_by_the_mana_it_could_produce():
    """"A card with a basic land type may be included in a Commander deck only
    if each color of mana it could produce is included in the commander's color
    identity." CR 903.5d's Wort example: Mountain and Forest yes, Island no."""
    identity = frozenset("RG")
    mountain = _catalog_entry("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",))
    island = _catalog_entry("Island", type_line="Basic Land — Island", produced_mana=("U",))

    assert deck_card_problem(mountain, identity, COMMANDER) is None
    problem = deck_card_problem(island, identity, COMMANDER)
    assert problem is not None and "903.5d" in problem


@pytest.mark.cr("903.5d")
def test_a_colourless_commander_admits_no_basic_lands_in_commander():
    """The rule has no exception in Commander — only Brawl's 903.12e does, which
    is what ``test_brawl.py`` covers."""
    forest = _catalog_entry("Forest", type_line="Basic Land — Forest", produced_mana=("G",))
    problem = deck_card_problem(forest, frozenset(), COMMANDER)
    assert problem is not None and "903.5d" in problem


@pytest.mark.cr("903.5e")
def test_commander_games_do_not_use_sideboards():
    """"Commander games do not use sideboards.\""""
    catalog = _catalog(
        _catalog_entry("Test Legend", type_line="Legendary Creature — Test", mana_cost="{R}"),
        _catalog_entry("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",)),
        _catalog_entry("Test Spell", type_line="Instant", mana_cost="{R}"),
    )
    res = validate_deck(
        _deck(("Mountain", 99)), "commander", catalog,
        sideboard=_deck(("Test Spell", 1)),
        commander=_deck(("Test Legend", 1)),
    )
    assert any("does not use a sideboard" in p for p in res["problems"])


@pytest.mark.cr("903.5")
def test_the_deck_validator_refuses_a_commander_that_cannot_be_one():
    catalog = _catalog(
        _catalog_entry("Test Bear", type_line="Creature — Bear", mana_cost="{1}{G}"),
        _catalog_entry("Forest", type_line="Basic Land — Forest", produced_mana=("G",)),
    )
    res = validate_deck(
        _deck(("Forest", 99)), "commander", catalog,
        commander=_deck(("Test Bear", 1)),
    )
    assert res["legal"] is False
    assert any("not legendary" in p for p in res["problems"])


# ---------------------------------------------------------------------------
# 903.6, 903.7, and CR 408 — starting the game
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.6", "408.3")
def test_each_commander_starts_face_up_in_the_command_zone(set_pool):
    """"At the start of the game, each player puts their commander from their
    deck face up into the command zone." CR 408.3 is the zone's own statement
    that specially designated cards start there."""
    pool = set_pool("M21")
    game = _commander_game(pool)

    assert [c.name for c in game.players[0].command_zone] == ["Gadrak, the Crown-Scourge"]
    assert [c.name for c in game.players[1].command_zone] == ["Azusa, Lost but Seeking"]


@pytest.mark.cr("903.6")
def test_the_commander_is_removed_from_the_deck_before_the_shuffle(set_pool):
    """"Then each player shuffles the remaining cards of their deck." The
    commander is out of the library first, so it can never be drawn into the
    opening hand."""
    pool = set_pool("M21")
    gadrak = pool["Gadrak, the Crown-Scourge"]
    player = PlayerState(name="A", library=[gadrak] + [pool["Mountain"]] * 30)
    game = Game(players=[player, PlayerState(name="B")], commander_variant=COMMANDER)
    game.designate_commander(0, gadrak)
    game.deal_opening_hands(0)

    assert not any(c.name == gadrak.name for c in player.library)
    assert not any(c.name == gadrak.name for c in player.hand)
    assert [c.name for c in player.command_zone] == [gadrak.name]


@pytest.mark.cr("903.7")
def test_each_player_starts_at_forty_life_and_draws_seven(set_pool):
    """"Once the starting player has been determined, each player sets their
    life total to 40 and draws a hand of seven cards.\""""
    game = _commander_game(set_pool("M21"))
    assert [p.life for p in game.players] == [40, 40]
    assert [len(p.hand) for p in game.players] == [7, 7]


@pytest.mark.cr("903.7")
def test_starting_life_is_forty_in_multiplayer_too():
    assert starting_life(COMMANDER, 2) == 40
    assert starting_life(COMMANDER, 4) == 40


@pytest.mark.cr("408.1")
def test_the_command_zone_is_not_the_battlefield_and_holds_cards_not_permanents(set_pool):
    """CR 408.1: the command zone holds objects that "are not permanents and
    cannot be destroyed". A commander sitting there is a card in a zone — it is
    on nobody's battlefield and no board wipe reaches it."""
    pool = set_pool("M21")
    game = _commander_game(pool)

    assert list(game.all_permanents()) == []
    assert len(game.players[0].command_zone) == 1


# ---------------------------------------------------------------------------
# 903.8 — casting from the command zone
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.8")
def test_a_player_may_cast_their_commander_from_the_command_zone(set_pool):
    pool = set_pool("M21")
    game = _commander_game(pool)

    result = game.cast_from_hand(0, "Gadrak, the Crown-Scourge", from_zone="command")

    assert result.supported is True
    assert [p.card.name for p in game.controlled_by(0)] == ["Gadrak, the Crown-Scourge"]
    assert game.players[0].command_zone == []


@pytest.mark.cr("903.8")
def test_only_the_owner_may_cast_a_commander_from_the_command_zone(set_pool):
    """"A player may cast a commander **they own** from the command zone.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)
    # Seat 1's commander sits in seat 1's command zone; seat 0 may not cast it.
    assert game.may_cast_from_command_zone(1, pool["Azusa, Lost but Seeking"]) is True
    assert game.may_cast_from_command_zone(0, pool["Azusa, Lost but Seeking"]) is False


@pytest.mark.cr("903.8")
def test_an_ordinary_card_in_the_command_zone_is_not_castable_from_it(set_pool):
    pool = set_pool("M21")
    game = _commander_game(pool)
    game.players[0].command_zone.append(pool["Alpine Watchdog"])

    result = game.cast_from_hand(0, "Alpine Watchdog", from_zone="command")
    assert result.supported is False
    assert "903.8" in result.details


@pytest.mark.cr("903.8")
def test_the_commander_tax_is_two_generic_per_previous_cast(set_pool):
    """"A commander cast from the command zone costs an additional {2} for each
    previous time the player casting it has cast it from the command zone that
    game.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]

    assert game.commander_tax(0, gadrak) == 0
    game.cast_from_hand(0, gadrak.name, from_zone="command")
    assert game.commander_tax(0, gadrak) == COMMANDER_TAX

    # Back to the command zone and cast again: the tax rises by {2} each time.
    game.players[0].command_zone.append(gadrak)
    game.cast_from_hand(0, gadrak.name, from_zone="command")
    assert game.commander_tax(0, gadrak) == 2 * COMMANDER_TAX


@pytest.mark.cr("903.8")
def test_the_tax_counts_only_casts_from_the_command_zone(set_pool):
    """"…cast it **from the command zone**." A commander cast from the hand
    (it was bounced there and its owner declined the command zone) does not
    raise the tax."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].hand.append(gadrak)

    game.cast_from_hand(0, gadrak.name, from_zone="hand")
    assert game.commander_tax(0, gadrak) == 0


@pytest.mark.cr("903.8")
def test_the_tax_is_charged_as_part_of_the_cost(set_pool):
    """CR 601.2f: an additional cost is part of the total cost, so a player who
    can pay the printed cost but not the tax cannot cast the commander."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    game.enforce_mana_costs = True
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].commander_casts[gadrak.name] = 1  # one previous cast → {2} more

    # {2}{R} printed + {2} tax = five mana; four is not enough.
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    refused = game.cast_from_hand(0, gadrak.name, from_zone="command")
    assert refused.supported is False
    assert "insufficient mana" in refused.details

    game.players[0].mana_pool.update({"R": 1, "C": 4})
    accepted = game.cast_from_hand(0, gadrak.name, from_zone="command")
    assert accepted.supported is True


# ---------------------------------------------------------------------------
# 903.9a / 704.6d — graveyard and exile
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.9a", "704.6d")
def test_a_commander_in_a_graveyard_goes_to_the_command_zone(set_pool):
    """"If a commander is in a graveyard or in exile and that object was put
    into that zone since the last time state-based actions were checked, its
    owner may put it into the command zone. This is a state-based action.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()
    game.players[0].graveyard.append(gadrak)

    game.check_state_based_actions()

    assert game.players[0].graveyard == []
    assert [c.name for c in game.players[0].command_zone] == [gadrak.name]


@pytest.mark.cr("903.9a")
def test_a_commander_in_exile_goes_to_the_command_zone(set_pool):
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()
    game.players[0].exile.append(gadrak)

    game.check_state_based_actions()

    assert game.players[0].exile == []
    assert [c.name for c in game.players[0].command_zone] == [gadrak.name]


@pytest.mark.cr("903.9a")
def test_a_dying_commander_reaches_the_command_zone_through_the_graveyard(set_pool):
    """The replacement in 903.9b covers hand and library only, so a commander
    that dies really does go to the graveyard first — which is what lets its
    death triggers fire — and 903.9a fetches it on the next check."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.cast_from_hand(0, gadrak.name, from_zone="command")
    permanent = next(iter(game.controlled_by(0)))

    game.remove_from_battlefield(permanent)
    game._permanent_to_graveyard(game.players[0], permanent)
    assert [c.name for c in game.players[0].graveyard] == [gadrak.name]

    game.check_state_based_actions()
    assert [c.name for c in game.players[0].command_zone] == [gadrak.name]


@pytest.mark.cr("903.9a")
def test_a_declined_return_is_not_offered_again_until_the_card_moves(set_pool):
    """"…and that object was put into that zone **since the last time
    state-based actions were checked**." A commander whose owner leaves it in
    the graveyard stays there; the offer is not repeated every check."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    game.interactive_seats = {0}
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()
    game.players[0].graveyard.append(gadrak)

    game.check_state_based_actions()
    assert len(game.pending_commander_zone_changes) == 1
    assert game.confirm_commander_zone_change(0, to_command_zone=False) is True
    assert [c.name for c in game.players[0].graveyard] == [gadrak.name]

    # Every later check finds it already offered and leaves it alone.
    game.check_state_based_actions()
    game.check_state_based_actions()
    assert game.pending_commander_zone_changes == []
    assert [c.name for c in game.players[0].graveyard] == [gadrak.name]


@pytest.mark.cr("903.9a")
def test_leaving_the_graveyard_makes_the_next_arrival_a_new_event(set_pool):
    """The "since the last check" memory is per stay, not per game: a commander
    that leaves the graveyard and dies again is asked about again."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    game.interactive_seats = {0}
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()
    game.players[0].graveyard.append(gadrak)

    game.check_state_based_actions()
    game.confirm_commander_zone_change(0, to_command_zone=False)

    # It is reanimated, then dies again.
    game.players[0].graveyard.clear()
    game.check_state_based_actions()
    game.players[0].graveyard.append(gadrak)
    game.check_state_based_actions()

    assert len(game.pending_commander_zone_changes) == 1


@pytest.mark.cr("903.9a")
def test_a_non_interactive_seat_takes_the_command_zone_without_a_prompt(set_pool):
    """AI and headless play never queue: the default is applied at once, through
    the same resolver an answered prompt runs."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    assert game.interactive_seats == set()
    game.players[0].command_zone.clear()
    game.players[0].graveyard.append(pool["Gadrak, the Crown-Scourge"])

    game.check_state_based_actions()

    assert game.pending_commander_zone_changes == []
    assert len(game.players[0].command_zone) == 1


@pytest.mark.cr("903.3", "903.9a")
def test_a_dead_copy_of_the_commander_is_not_offered_the_command_zone(set_pool):
    """CR 903.3 ties the designation to the card itself, so a token copy —
    whose card is a fresh object carrying the copied name — dying must not
    raise 903.9a's offer. Only the designated card gets the way back."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    game.interactive_seats = {0}
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.cast_from_hand(0, gadrak.name, from_zone="command")

    # A same-name look-alike (the card a token copy carries) hits the graveyard
    # while the real commander is on the battlefield.
    from engine.tokens import make_token_card
    look_alike = make_token_card(gadrak.name, None, None, "Token")
    game.players[0].graveyard.append(look_alike)

    game.check_state_based_actions()

    # No offer, and nothing reached the command zone. (The look-alike itself is
    # swept out of the graveyard by CR 111.7's own state-based action — a token
    # in any zone but the battlefield ceases to exist — which is not this rule.)
    assert game.pending_commander_zone_changes == []
    assert game.players[0].command_zone == []


@pytest.mark.cr("903.3", "903.3d")
def test_a_token_copy_of_the_commander_is_not_a_commander_permanent(set_pool):
    """903.3's example: a permanent copying the commander is not a commander;
    the designated card's permanent is, copies notwithstanding."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.cast_from_hand(0, gadrak.name, from_zone="command")
    real = next(iter(game.controlled_by(0)))

    token = game.create_token_copy(0, real)

    assert game.is_commander_permanent(real) is True
    assert game.is_commander_permanent(token) is False


# ---------------------------------------------------------------------------
# 903.9b — hand and library
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.9b")
def test_a_commander_headed_for_its_owners_hand_may_go_to_the_command_zone(set_pool):
    """"If a commander would be put into its owner's hand or library from
    anywhere, its owner may put it into the command zone instead.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()

    arrived = game.put_card_into_hand(0, gadrak)

    assert arrived is False
    assert not any(c.name == gadrak.name for c in game.players[0].hand)
    assert [c.name for c in game.players[0].command_zone] == [gadrak.name]


@pytest.mark.cr("903.9b")
def test_a_commander_headed_for_its_owners_library_may_go_to_the_command_zone(set_pool):
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()

    arrived = game.put_card_into_library(0, gadrak, "top")

    assert arrived is False
    assert not any(c.name == gadrak.name for c in game.players[0].library)
    assert [c.name for c in game.players[0].command_zone] == [gadrak.name]


@pytest.mark.cr("903.9b")
def test_a_bounced_commander_is_diverted_from_the_battlefield(set_pool):
    """"…from anywhere" — the battlefield included, which is the case the rule
    is best known for."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.cast_from_hand(0, gadrak.name, from_zone="command")
    permanent = next(iter(game.controlled_by(0)))

    game.remove_from_battlefield(permanent)
    game.put_card_into_hand(0, permanent.card)

    assert [c.name for c in game.players[0].command_zone] == [gadrak.name]


@pytest.mark.cr("903.9b")
def test_a_drawn_commander_may_be_put_into_the_command_zone(set_pool):
    """A draw puts a card into its owner's hand from their library, so a
    commander that was shuffled back in is caught by the same rule."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()
    game.players[0].library.insert(0, gadrak)

    game._draw_with_replacements(game.players[0], 1)

    assert not any(c.name == gadrak.name for c in game.players[0].hand)
    assert [c.name for c in game.players[0].command_zone] == [gadrak.name]


@pytest.mark.cr("903.9b")
def test_the_owner_may_decline_and_keep_the_card_where_it_was_headed(set_pool):
    """"…its owner **may** put it into the command zone instead." An
    interactive seat is asked, and "no" is a legal answer."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    game.interactive_seats = {0}
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()

    game.put_card_into_hand(0, gadrak)
    pending = game.pending_commander_zone_changes
    assert len(pending) == 1
    assert pending[0]["destination"] == "hand"
    assert pending[0]["rule"] == "903.9b"

    assert game.confirm_commander_zone_change(0, to_command_zone=False) is True
    assert any(c.name == gadrak.name for c in game.players[0].hand)
    assert game.players[0].command_zone == []


@pytest.mark.cr("903.9b")
def test_the_card_is_in_no_zone_while_the_choice_is_outstanding(set_pool):
    """The same shape as Library of Leng's discard (CR 614): the card has left
    where it was and its destination is undecided, so it is in neither."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    game.interactive_seats = {0}
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()

    game.put_card_into_hand(0, gadrak)

    assert not any(c.name == gadrak.name for c in game.players[0].hand)
    assert game.players[0].command_zone == []
    assert len(game.pending_commander_zone_changes) == 1


@pytest.mark.cr("903.9b", "614.5")
def test_the_replacement_may_apply_more_than_once_to_the_same_commander(set_pool):
    """"This replacement effect may apply more than once to the same event. This
    is an exception to rule 614.5." Nothing is consumed, so a commander bounced,
    declined, and bounced again is offered the command zone again."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    game.interactive_seats = {0}
    gadrak = pool["Gadrak, the Crown-Scourge"]
    game.players[0].command_zone.clear()

    game.put_card_into_hand(0, gadrak)
    game.confirm_commander_zone_change(0, to_command_zone=False)
    game.players[0].hand.remove(gadrak)

    game.put_card_into_hand(0, gadrak)
    assert len(game.pending_commander_zone_changes) == 1
    assert game.confirm_commander_zone_change(0, to_command_zone=True) is True
    assert [c.name for c in game.players[0].command_zone] == [gadrak.name]


@pytest.mark.cr("903.9b")
def test_only_the_owners_own_commander_is_diverted(set_pool):
    """"…into **its owner's** hand or library". Another player's card of the
    same name is an ordinary card and goes where it was headed."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    gadrak = pool["Gadrak, the Crown-Scourge"]

    arrived = game.put_card_into_hand(1, gadrak)

    assert arrived is True
    assert any(c.name == gadrak.name for c in game.players[1].hand)
    assert game.players[1].command_zone == [pool["Azusa, Lost but Seeking"]]


@pytest.mark.cr("903.9b")
def test_an_ordinary_card_is_never_diverted(set_pool):
    pool = set_pool("M21")
    game = _commander_game(pool)
    watchdog = pool["Alpine Watchdog"]

    assert game.put_card_into_hand(0, watchdog) is True
    assert any(c.name == watchdog.name for c in game.players[0].hand)


# ---------------------------------------------------------------------------
# 903.10a / 704.6c — commander damage
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.10a", "704.6c")
def test_twenty_one_combat_damage_from_one_commander_loses_the_game(set_pool):
    """"A player who's been dealt 21 or more combat damage by the same commander
    over the course of the game loses the game. (This is a state-based action.)\""""
    pool = set_pool("M21")
    game = _commander_game(pool)
    commander = Permanent(card=pool["Gadrak, the Crown-Scourge"])
    game.players[0].battlefield.append(commander)
    game._sync_control()

    for _ in range(4):
        game.record_commander_combat_damage(game.players[1], commander, 5)
    game.check_state_based_actions()
    assert game.commander_damage_dealt(1, 0, commander.card.name) == 20
    assert game.players[1].lost is False

    game.record_commander_combat_damage(game.players[1], commander, 1)
    game.check_state_based_actions()
    assert game.commander_damage_dealt(1, 0, commander.card.name) == LETHAL_COMMANDER_DAMAGE
    assert game.players[1].lost is True


@pytest.mark.cr("903.10a")
def test_the_tally_is_per_commander_not_per_opponent(set_pool):
    """"…by **the same** commander." Twenty damage from one and twenty from
    another is not 21 from either."""
    pool = set_pool("M21")
    game = _commander_game(pool, seats=3)
    first = Permanent(card=pool["Gadrak, the Crown-Scourge"])
    second = Permanent(card=pool["Azusa, Lost but Seeking"])
    game.players[0].battlefield.append(first)
    game.players[1].battlefield.append(second)
    game._sync_control()

    game.record_commander_combat_damage(game.players[2], first, 20)
    game.record_commander_combat_damage(game.players[2], second, 20)
    game.check_state_based_actions()

    assert game.players[2].lost is False
    assert game.commander_damage_dealt(2, 0, first.card.name) == 20
    assert game.commander_damage_dealt(2, 1, second.card.name) == 20


@pytest.mark.cr("903.10a")
def test_only_combat_damage_from_a_commander_is_tallied(set_pool):
    """The rule counts **combat** damage from a **commander**: an ordinary
    creature's combat damage and a commander's noncombat ping are both outside
    it. ``record_commander_combat_damage`` is called from the combat damage
    step alone, so the second half is what it can refuse."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    ordinary = Permanent(card=pool["Alpine Watchdog"])
    game.players[0].battlefield.append(ordinary)
    game._sync_control()

    game.record_commander_combat_damage(game.players[1], ordinary, 30)
    game.check_state_based_actions()

    assert game.players[1].lost is False
    assert game.players[1].commander_damage_taken == {}


@pytest.mark.cr("903.10a")
def test_combat_damage_from_a_commander_is_tallied_by_the_combat_damage_step(set_pool):
    """The end-to-end path: an unblocked commander attacking a player raises the
    tally in the step that deals the damage, not by a caller remembering to."""
    pool = set_pool("M21")
    # Kaervek rather than Gadrak, who "can't attack unless you control four or
    # more artifacts" (CR 506.3's restriction) and so never reaches the step.
    game = _commander_game(pool, commander="Kaervek, the Spiteful")
    kaervek = pool["Kaervek, the Spiteful"]
    commander = _nosick(Permanent(card=kaervek))
    game.players[0].battlefield.append(commander)
    game._sync_control()

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    game.declare_attackers(0, [0])
    game.advance_combat_phase()   # declare_blockers
    game.declare_blockers(1, {})
    game.advance_combat_phase()   # combat_damage
    game.resolve_combat_damage(0)

    assert game.commander_damage_dealt(1, 0, kaervek.name) == 3
    assert game.players[1].life == 37


@pytest.mark.cr("903.10a")
def test_commander_damage_is_not_tallied_outside_a_commander_game(set_pool):
    pool = set_pool("M21")
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.designate_commander(0, pool["Gadrak, the Crown-Scourge"])
    commander = Permanent(card=pool["Gadrak, the Crown-Scourge"])
    game.players[0].battlefield.append(commander)
    game._sync_control()

    game.record_commander_combat_damage(game.players[1], commander, 30)
    game.check_state_based_actions()

    assert game.players[1].lost is False


# ---------------------------------------------------------------------------
# 903.11 — cards from outside the game
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.11a")
def test_a_card_from_outside_the_game_may_not_share_a_starting_deck_name(set_pool):
    """"…that player can't bring a card into the game this way if it has the
    same name as a card that player had in their starting deck.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)

    problem = game.outside_the_game_problem(0, pool["Mountain"])
    assert problem is not None and "starting deck" in problem


@pytest.mark.cr("903.11a")
def test_a_card_from_outside_the_game_may_not_share_a_name_in_play(set_pool):
    """"…the same name as a card that the player owns in the current game.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)
    watchdog = pool["Alpine Watchdog"]
    game.players[0].graveyard.append(watchdog)

    problem = game.outside_the_game_problem(0, watchdog)
    assert problem is not None and "owns in this game" in problem


@pytest.mark.cr("903.11a")
def test_a_card_from_outside_the_game_must_fit_the_commanders_colour_identity(set_pool):
    """"…or if any color in its color identity isn't in the color identity of
    the player's commander.\""""
    pool = set_pool("M21")
    game = _commander_game(pool)  # a red commander
    blue = _mk_card("Test Import", "{1}{U}", "Instant", "Draw a card.")

    problem = game.outside_the_game_problem(0, blue)
    assert problem is not None and "colour identity" in problem


@pytest.mark.cr("903.11a")
def test_an_on_colour_card_from_outside_the_game_is_allowed(set_pool):
    pool = set_pool("M21")
    game = _commander_game(pool)
    red = _mk_card("Test Import", "{1}{R}", "Instant", "Deal 3 damage to any target.")

    assert game.outside_the_game_problem(0, red) is None


@pytest.mark.cr("903.11")
def test_the_outside_the_game_restriction_is_inert_in_an_ordinary_game(set_pool):
    """CR 903.11 is a Commander rule; an ordinary game's sideboard is bounded by
    CR 100.4 alone."""
    pool = set_pool("M21")
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    assert game.outside_the_game_problem(0, pool["Mountain"]) is None


def _sideboard_of_three(pool):
    """An off-identity card, a starting-deck name, and one legal import — the
    three CR 903.11a outcomes in one sideboard (the commander is red)."""
    blue = _mk_card("Test Import Blue", "{1}{U}", "Instant", "Draw a card.")
    red = _mk_card("Test Import Red", "{1}{R}", "Instant", "It deals 3 damage to any target.")
    return [blue, pool["Mountain"], red]


@pytest.mark.cr("903.11a")
def test_the_outside_the_game_offer_lists_only_cards_the_variant_allows(set_pool):
    """The real path: a Ring of Ma'rûf draw in a Commander game offers an
    interactive seat only the sideboard cards CR 903.11a admits."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    p1 = game.players[0]
    p1.sideboard = _sideboard_of_three(pool)
    game.outside_game_draw_replacements.add(0)
    game.interactive_seats = {0}

    game._draw_with_replacements(p1, 1)

    [choice] = game.pending_replacement_choices
    assert choice.kind == "outside_game_draw"
    assert choice.options == ("Test Import Red",)

    assert game.resolve_replacement_choice(0, 0) is True
    assert p1.hand[-1].name == "Test Import Red"
    assert [c.name for c in p1.sideboard] == ["Test Import Blue", "Mountain"]


@pytest.mark.cr("903.11a")
def test_a_default_outside_the_game_take_respects_the_bars(set_pool):
    """A non-interactive seat takes the default from the same filtered list, so
    the AI cannot import what a human would not be offered."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    p1 = game.players[0]
    p1.sideboard = _sideboard_of_three(pool)
    game.outside_game_draw_replacements.add(0)

    game._draw_with_replacements(p1, 1)

    assert p1.hand[-1].name == "Test Import Red"
    assert [c.name for c in p1.sideboard] == ["Test Import Blue", "Mountain"]


@pytest.mark.cr("903.11a", "614.1")
def test_a_fully_barred_sideboard_still_spends_the_replacement(set_pool):
    """With every sideboard card barred there is nothing to take, and CR 614.1
    spends the replacement anyway — no card arrives from anywhere."""
    pool = set_pool("M21")
    game = _commander_game(pool)
    p1 = game.players[0]
    p1.sideboard = [_mk_card("Test Import Blue", "{1}{U}", "Instant", "Draw a card.")]
    game.outside_game_draw_replacements.add(0)
    hand_before, library_before = len(p1.hand), len(p1.library)

    game._draw_with_replacements(p1, 1)

    assert 0 not in game.outside_game_draw_replacements, "the replacement was spent"
    assert len(p1.hand) == hand_before, "nothing was imported"
    assert len(p1.library) == library_before, "and nothing was drawn instead"
    assert [c.name for c in p1.sideboard] == ["Test Import Blue"]
    assert any("no cards outside the game" in line for line in game.log)


# ---------------------------------------------------------------------------
# Where Commander and Brawl part company (the Commander half; see test_brawl.py)
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.3", "903.12c")
def test_a_planeswalker_may_not_be_a_commander_in_commander(set_pool):
    """CR 903.3 lists no planeswalker; only Brawl's 903.12c adds one."""
    pool = set_pool("M21")
    garruk = pool["Garruk, Unleashed"]
    assert can_be_commander(garruk, COMMANDER) is False
    assert can_be_commander(garruk, BRAWL) is True


# ---------------------------------------------------------------------------
# The served game — CR 903 through the web layer
#
# The engine is tested above; these check that the variant actually reaches a
# game a player can sit down at. A rule implemented in the engine and not wired
# to the API is a rule nobody can use, which is the failure the ante tests
# cover the same way.
# ---------------------------------------------------------------------------

def _commander_session(variant: str = COMMANDER):
    """A two-player session led by a black and a green commander."""
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai",
        "host_name": "Host",
        "host_colors": 2,
        "guest_colors": 2,
        "seed": 9031,
        "variant": variant,
        "host_deck_cards": [{"name": "Swamp", "count": 40}],
        "host_deck_commander": [{"name": "Kaervek, the Spiteful", "count": 1}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_commander": [{"name": "Azusa, Lost but Seeking", "count": 1}],
    })
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _state(session_id: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{session_id}/state", params={"seat": seat}).json()


@pytest.mark.cr("903.6", "903.7")
def test_a_served_commander_game_starts_with_forty_life_and_a_command_zone():
    state = _state(_commander_session())

    assert state["commander_variant"] == COMMANDER
    assert [p["life"] for p in state["players"]] == [40, 40]
    assert [c["name"] for c in state["players"][0]["command_zone"]] == [
        "Kaervek, the Spiteful"
    ]
    assert [c["name"] for c in state["players"][1]["command_zone"]] == [
        "Azusa, Lost but Seeking"
    ]


@pytest.mark.cr("903.8")
def test_the_served_state_offers_the_commander_as_castable_from_its_zone():
    state = _state(_commander_session())

    offered = [e for e in state["castable_from_zones"] if e["zone"] == "command"]
    assert [e["name"] for e in offered] == ["Kaervek, the Spiteful"]
    assert offered[0]["commander_tax"] == 0


@pytest.mark.cr("903.8")
def test_casting_a_commander_from_the_command_zone_over_the_api():
    session_id = _commander_session()
    session = store.get(session_id)
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.start_priority_window(0)
    session.game.players[0].mana_pool.update({"B": 2, "C": 2})

    response = client.post(f"/api/sessions/{session_id}/action", json={
        "action": "cast", "seat": 0, "card_name": "Kaervek, the Spiteful",
        "from_zone": "command",
    })
    assert response.status_code == 200, response.text

    # The spell is on the stack (CR 601.2a) and has left the command zone; the
    # API casts, it does not resolve — that is the priority window's job.
    state = _state(session_id)
    assert [item["card"]["name"] for item in state["stack"]] == ["Kaervek, the Spiteful"]
    assert state["players"][0]["command_zone"] == []
    # …and the next cast of it is taxed (CR 903.8).
    assert session.game.commander_tax(0, session.game.commanders_of(0)[0]) == COMMANDER_TAX


@pytest.mark.cr("903.3")
def test_the_served_state_crowns_the_designated_commander_card():
    """The wire marks the designated card — in the command zone and, once cast
    and resolved, on the battlefield — so the client can badge it. Identity-
    keyed: a same-name card in another zone is not marked."""
    session_id = _commander_session()
    game = store.get(session_id).game

    state = _state(session_id)
    zone = state["players"][0]["command_zone"]
    assert [c.get("is_commander") for c in zone] == [True]

    # Cast (the session enforces costs, so fill the pool) and resolve it.
    game.players[0].mana_pool = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}
    result = game.cast_from_hand(0, "Kaervek, the Spiteful", from_zone="command")
    assert result.supported, result.details
    game.resolve_top_of_stack()
    state = _state(session_id)
    crowned = [p["name"] for p in state["players"][0]["battlefield"] if p.get("is_commander")]
    assert crowned == ["Kaervek, the Spiteful"]


@pytest.mark.cr("903.8")
def test_the_api_refuses_a_commander_that_is_not_yours():
    session_id = _commander_session()
    response = client.post(f"/api/sessions/{session_id}/action", json={
        "action": "cast", "seat": 0, "card_name": "Azusa, Lost but Seeking",
        "from_zone": "command",
    })
    assert response.status_code == 400
    assert "903.8" in response.json()["detail"]


@pytest.mark.cr("903.9a")
def test_the_served_state_prompts_its_owner_for_a_commander_in_a_graveyard():
    session_id = _commander_session()
    game = store.get(session_id).game
    game.interactive_seats = {0}
    # The *designated* card object goes to the graveyard: CR 903.3 ties the
    # designation to the card itself, so a same-name look-alike (a fixture
    # pool's separate load, a token copy) must not raise this prompt.
    game.players[0].command_zone.clear()
    game.players[0].graveyard.append(game.players[0].commanders[0])
    game.check_state_based_actions()

    prompt = _state(session_id)["commander_zone_change"]
    assert prompt["player_seat"] == 0
    assert prompt["card"]["name"] == "Kaervek, the Spiteful"
    assert prompt["destination"] == "graveyard"
    assert prompt["rule"] == "903.9a"

    response = client.post(f"/api/sessions/{session_id}/action", json={
        "action": "commander_zone_change_confirm", "seat": 0, "to_command_zone": True,
    })
    assert response.status_code == 200, response.text

    state = _state(session_id)
    assert [c["name"] for c in state["players"][0]["command_zone"]] == [
        "Kaervek, the Spiteful"
    ]
    assert state["players"][0]["graveyard"] == []


@pytest.mark.cr("903.9")
def test_the_api_refuses_a_commander_zone_answer_nobody_asked_for():
    session_id = _commander_session()
    response = client.post(f"/api/sessions/{session_id}/action", json={
        "action": "commander_zone_change_confirm", "seat": 0, "to_command_zone": True,
    })
    assert response.status_code == 400
    assert "no commander zone choice pending" in response.json()["detail"]


@pytest.mark.cr("903.1")
def test_an_ordinary_served_game_reports_no_variant():
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 9032,
    })
    state = _state(response.json()["session_id"])

    assert state["commander_variant"] is None
    assert [p["life"] for p in state["players"]] == [20, 20]
    assert state["players"][0]["command_zone"] == []
