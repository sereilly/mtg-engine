"""A card off the battlefield is asked its creature types with its own seat.

"Creatures you control are the chosen type. **The same is true for creature
spells you control and creature cards you own that aren't on the
battlefield.**" (Conspiracy.) The second sentence is CR 613 layer 4 over
objects with no permanent to ask — a card in a hand, a library, a graveyard,
a spell on the stack — and it is a property of a *seat*: whose card it is
(CR 108.3) or whose spell (CR 109.5) decides what it is. "Affected spells,
cards, and creatures lose all of their other creature types." (The card's
ruling, 2013-09-20; CR 205.1a.)

The type twin of round kg's Celestial Dawn fix
(``tests/engine/test_kg_colour_off_battlefield_reads.py``): every card
matcher already took ``game=``/``owner=``, and the colour half asked them.
The creature-type half did not everywhere — the graveyard matcher read the
printed line, a library search asked the chooser's seat rather than the
zone's owner's, and four readers outside the matchers read the printed card.
Each board below is one the pool-wide census found playing differently from
the same board with the cards printed as the chosen type
(``test_kg3_types_conspiracy_census.py``), driven through the real entry
points.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.object_creature_types import card_creature_types
from engine.search_filters import card_has_type, search_matches
from tests.helpers import _nosick, resolve_stack


@pytest.fixture(scope="module")
def pool(set_pool):
    found = {}
    for code, names in (
        ("4ED", ("Forest", "Grizzly Bears", "Plains")),
        ("7ED", ("Giant Cockroach",)),
        ("MMQ", ("Conspiracy", "Strongarm Thug")),
        ("NEM", ("Lin Sivvi, Defiant Hero",)),
        ("M21", ("Rin and Seri, Inseparable",)),
        ("UDS", ("Urza's Incubator",)),
        ("ONS", ("Aphetto Dredging",)),
    ):
        for name in names:
            found[name] = set_pool(code)[name]
    return found


def _conspiracy(pool, chosen):
    source = Permanent(card=pool["Conspiracy"])
    source.metadata["chosen_creature_type"] = chosen
    return source


def _duel(pool, mine=(), theirs=(), *, hand=(), graveyard=(), their_graveyard=()):
    library = [pool["Forest"]] * 10
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(mine), hand=list(hand),
                    graveyard=list(graveyard), library=list(library)),
        PlayerState(name="P1", battlefield=list(theirs),
                    graveyard=list(their_graveyard), library=list(library)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    game._sync_control()
    for player in game.players:
        for permanent in player.battlefield:
            _nosick(permanent)
    game._recompute_continuous_effects()
    return game


# ---------------------------------------------------------------------------
# The graveyard matcher (``graveyard_card_matches``' ``graveyard_subtypes``)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("conspiracy_seat,returned", [(0, True), (1, False)])
def test_strongarm_thug_returns_a_card_its_owners_conspiracy_made_a_mercenary(
    pool, conspiracy_seat, returned,
):
    """"…return target Mercenary card from your graveyard to your hand."
    Under its owner's Conspiracy naming Mercenary the Giant Cockroach in that
    graveyard is a Mercenary card; under the *opponent's* it is an Insect,
    because whose card it is decides (CR 108.3)."""
    source = _conspiracy(pool, "Mercenary")
    game = _duel(
        pool,
        mine=[source] if conspiracy_seat == 0 else [],
        theirs=[source] if conspiracy_seat == 1 else [],
        hand=[pool["Strongarm Thug"]], graveyard=[pool["Giant Cockroach"]],
    )

    result = game.cast_from_hand(0, "Strongarm Thug")
    assert result.supported, result
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    in_hand = [card.name for card in game.players[0].hand]
    assert ("Giant Cockroach" in in_hand) is returned, game.log[-6:]


def test_lin_sivvi_puts_back_a_card_its_owners_conspiracy_made_a_rebel(pool):
    """"{3}: Put target Rebel card from your graveyard on the bottom of your
    library." The ability had no legal target (CR 602.2b) while the matcher
    read the printed Insect."""
    lin = Permanent(card=pool["Lin Sivvi, Defiant Hero"])
    game = _duel(pool, mine=[lin, _conspiracy(pool, "Rebel")],
                 graveyard=[pool["Giant Cockroach"]])

    result = game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=1,
    )
    assert result.supported, result
    resolve_stack(game)

    assert game.players[0].library[-1].name == "Giant Cockroach"
    assert not game.players[0].graveyard


# ---------------------------------------------------------------------------
# Readers outside the matchers
# ---------------------------------------------------------------------------


def test_rin_and_seri_sees_a_spell_its_casters_conspiracy_made_a_dog(pool):
    """"Whenever you cast a Dog spell, create a 1/1 green Cat creature token."
    "…creature spells you control" (Conspiracy naming Dog) make the Bear spell
    a Dog spell and nothing else, so the Cat trigger fires and the Dog one does
    not — a Bear is not a Cat either."""
    rin = Permanent(card=pool["Rin and Seri, Inseparable"])
    game = _duel(pool, mine=[rin, _conspiracy(pool, "Dog")],
                 hand=[pool["Grizzly Bears"]])

    result = game.cast_from_hand(0, "Grizzly Bears")
    assert result.supported, result
    resolve_stack(game)

    tokens = sorted(
        p.card.name for p in game.controlled_by(0) if p.metadata.get("is_token")
    )
    assert tokens == ["Cat Token"], game.log[-6:]


def test_urzas_incubator_discounts_a_spell_its_casters_conspiracy_retyped(pool):
    """"Creature spells of the chosen type cost {2} less to cast." The
    Incubator and the Conspiracy both name Goblin; the Giant Cockroach spell is
    a Goblin spell, so it costs {1}{B} — paid here from exactly that."""
    incubator = Permanent(card=pool["Urza's Incubator"])
    incubator.metadata["chosen_creature_type"] = "Goblin"
    game = _duel(pool, mine=[incubator, _conspiracy(pool, "Goblin")],
                 hand=[pool["Giant Cockroach"]])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"B": 2})

    result = game.cast_from_hand(0, "Giant Cockroach")

    assert result.supported, (result, game.log[-4:])
    assert any("costs less to cast (Urza's Incubator)" in line for line in game.log)
    assert any(p.card.name == "Giant Cockroach" for p in game.controlled_by(0))


def test_aphetto_dredging_names_the_type_its_casters_conspiracy_made_the_pile(pool):
    """"Return up to three target creature cards of the creature type of your
    choice …" — the picker's default is the type most of the caster's
    graveyard shares, and under its owner's Conspiracy naming Goblin every
    creature card in it is a Goblin and nothing else. The printed count named
    a type no card in the pile was (CR 205.1a), and offered nothing."""
    game = _duel(pool, mine=[_conspiracy(pool, "Goblin")],
                 hand=[pool["Aphetto Dredging"]],
                 graveyard=[pool["Giant Cockroach"], pool["Grizzly Bears"]])
    card = game.players[0].hand[0]

    spec = game.cast_target_spec(0, card)
    assert spec["default_creature_type"] == spec["chosen_creature_type"] == "goblin"
    assert sorted(t["name"] for t in spec["valid_targets"]) == [
        "Giant Cockroach", "Grizzly Bears",
    ]

    result = game.cast_from_hand(
        0, "Aphetto Dredging", chosen_creature_type="goblin",
        target_player_index=0, target_permanent_index=[0, 1],
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert sorted(card.name for card in game.players[0].hand) == [
        "Giant Cockroach", "Grizzly Bears",
    ]


# ---------------------------------------------------------------------------
# The seams themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("conspiracy_seat,found", [(1, True), (0, False)])
def test_a_search_of_another_seats_zone_asks_that_seats_conspiracy(
    pool, conspiracy_seat, found,
):
    """``search_matches`` is told the chooser and the zone's seat
    (``zone_seat``); "cards **you own**" is the zone's owner (CR 108.3). The
    override was asked of the chooser, so a search of seat 1's library applied
    seat 0's Conspiracy to seat 1's cards and ignored seat 1's own."""
    source = _conspiracy(pool, "Goblin")
    game = _duel(
        pool,
        mine=[source] if conspiracy_seat == 0 else [],
        theirs=[source] if conspiracy_seat == 1 else [],
    )
    armed = {"card_type": "any", "restrictions": {"subtypes": ["goblin"]},
             "zone_seat": 1}

    assert search_matches(
        pool["Grizzly Bears"], armed, game=game, owner=0,
    ) is found


def test_the_one_reader_replaces_creature_types_and_nothing_else(pool):
    """CR 205.1a: the chosen type replaces the card's **creature** types (the
    Bear is not a Bear) and leaves a subtype of another of its types; a
    noncreature card is not retyped (CR 205.3d). ``card_has_type`` asks the
    same reader for a creature-type word when it is told the seat."""
    from engine.models import CardDefinition

    game = _duel(pool, mine=[_conspiracy(pool, "Goblin")])
    bears = pool["Grizzly Bears"]
    assert card_creature_types(game, bears, 0) == frozenset({"goblin"})
    assert card_creature_types(game, bears, 1) == frozenset({"bear"})
    assert card_has_type(bears, "goblin", game=game, owner=0)
    assert not card_has_type(bears, "bear", game=game, owner=0)
    assert card_has_type(bears, "bear")  # no seat: the printed answer
    assert card_has_type(bears, "creature", game=game, owner=0)
    land_creature = CardDefinition(
        name="Test Arbor", mana_cost="", cmc=0.0,
        type_line="Land Creature — Forest Dryad", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw={},
    )
    assert card_creature_types(game, land_creature, 0) == frozenset({"forest", "goblin"})
    assert card_creature_types(game, pool["Plains"], 0) == frozenset({"plains"})
