"""Per-card tests for Fallen Empires' enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations

# --- G4: costs from the board and the graveyard ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g4_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g4_game(battlefield, *, graveyard=(), their_graveyard=()):
    p1 = PlayerState(
        name="P1", battlefield=list(battlefield), graveyard=list(graveyard)
    )
    p2 = PlayerState(name="P2", graveyard=list(their_graveyard))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2


def test_goblin_warrens_eats_two_goblins_for_three_tokens(set_pool):
    """"{2}{R}, **Sacrifice two Goblins**: Create three 1/1 red Goblin creature
    tokens."

    A *counted* sacrifice cost. Both Goblins are gone before the ability is on
    the stack (CR 601.2h), and the three tokens arrive after — so the board this
    leaves is two Goblins poorer and three tokens richer, never five creatures.
    """
    pool = set_pool("FEM")
    warrens = Permanent(card=pool["Goblin Warrens"])
    goblins = [
        _g4_nosick(Permanent(card=pool["Goblin Chirurgeon"])) for _ in range(2)
    ]
    game, p1, _p2 = _g4_game([warrens, *goblins])

    result = game.activate_permanent_ability(0, "Goblin Warrens", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert sorted(perm.card.name for perm in p1.battlefield) == [
        "Goblin Token", "Goblin Token", "Goblin Token", "Goblin Warrens",
    ]
    assert [card.name for card in p1.graveyard] == [
        "Goblin Chirurgeon", "Goblin Chirurgeon",
    ]


def test_goblin_warrens_cannot_be_activated_with_one_goblin(set_pool):
    """The control the count exists for. One Goblin is no more a payment of a
    two-Goblin cost than none is (CR 601.2h), so the ability is not activated at
    all (CR 602.2b) — and the lone Goblin is still on the battlefield.

    Without this, a cost that matched a *singular* pattern would have eaten one
    Goblin and made three tokens for it, which is the card at half price."""
    pool = set_pool("FEM")
    warrens = Permanent(card=pool["Goblin Warrens"])
    goblin = _g4_nosick(Permanent(card=pool["Goblin Chirurgeon"]))
    game, p1, _p2 = _g4_game([warrens, goblin])

    result = game.activate_permanent_ability(0, "Goblin Warrens", permanent_index=0)
    game._settle()

    assert not result.supported
    assert [perm.card.name for perm in p1.battlefield] == [
        "Goblin Warrens", "Goblin Chirurgeon",
    ]
    assert p1.graveyard == []


def test_goblin_warrens_will_not_eat_a_creature_that_is_not_a_goblin(set_pool):
    """The noun phrase is a narrowing, not decoration: two Merfolk pay nothing.

    A charger reading "sacrifice two creatures" would have taken them — which is
    the dropped-rider bug with the card still reporting supported."""
    pool = set_pool("FEM")
    warrens = Permanent(card=pool["Goblin Warrens"])
    merfolk = [
        _g4_nosick(Permanent(card=pool["River Merfolk"])) for _ in range(2)
    ]
    game, p1, _p2 = _g4_game([warrens, *merfolk])

    result = game.activate_permanent_ability(0, "Goblin Warrens", permanent_index=0)
    game._settle()

    assert not result.supported
    assert p1.graveyard == []
    assert len(p1.battlefield) == 3


def test_night_soil_exiles_two_creature_cards_for_a_saproling(set_pool):
    """"{1}, **Exile two creature cards from a single graveyard**: Create a 1/1
    green Saproling creature token."

    The cost is paid at activation (CR 602.2b), so the cards are in exile before
    the token is made. Either player's pile may pay it — the phrase names "a"
    graveyard, not "your" one."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    soil = Permanent(card=pool["Night Soil"])
    game, p1, _p2 = _g4_game(
        [soil], graveyard=[lea["Grizzly Bears"], lea["Hurloon Minotaur"]]
    )

    result = game.activate_permanent_ability(0, "Night Soil", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert p1.graveyard == []
    assert sorted(card.name for card in p1.exile) == [
        "Grizzly Bears", "Hurloon Minotaur",
    ]
    assert sorted(perm.card.name for perm in p1.battlefield) == [
        "Night Soil", "Saproling Token",
    ]


def test_night_soil_reaches_an_opponents_graveyard(set_pool):
    """"…from **a** single graveyard" — anybody's. Read as "your graveyard" the
    card would be dead against an empty pile of one's own, which is the ordinary
    way it is played."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    soil = Permanent(card=pool["Night Soil"])
    game, p1, p2 = _g4_game(
        [soil], their_graveyard=[lea["Grizzly Bears"], lea["Hurloon Minotaur"]]
    )

    result = game.activate_permanent_ability(0, "Night Soil", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert p2.graveyard == []
    assert len(p1.exile) == 2
    assert any(perm.card.name == "Saproling Token" for perm in p1.battlefield)


def test_night_soil_will_not_take_one_card_from_each_graveyard(set_pool):
    """"…from **a single** graveyard" is the rider that gets parsed and dropped,
    and dropped it makes the cost strictly cheaper: two piles holding one
    creature card each would pay a cost the card says they cannot.

    Nothing is exiled and no token is made — the ability is not activated at all
    (CR 602.2b)."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    soil = Permanent(card=pool["Night Soil"])
    game, p1, p2 = _g4_game(
        [soil],
        graveyard=[lea["Grizzly Bears"]],
        their_graveyard=[lea["Hurloon Minotaur"]],
    )

    result = game.activate_permanent_ability(0, "Night Soil", permanent_index=0)
    game._settle()

    assert not result.supported
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]
    assert [card.name for card in p2.graveyard] == ["Hurloon Minotaur"]
    assert p1.exile == []
    assert [perm.card.name for perm in p1.battlefield] == ["Night Soil"]


def test_night_soil_will_not_exile_land_cards(set_pool):
    """"…two **creature** cards". A pile of lands pays nothing, which is what
    tells the narrowing from decoration."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    soil = Permanent(card=pool["Night Soil"])
    game, p1, _p2 = _g4_game([soil], graveyard=[lea["Forest"], lea["Forest"]])

    result = game.activate_permanent_ability(0, "Night Soil", permanent_index=0)
    game._settle()

    assert not result.supported
    assert len(p1.graveyard) == 2
    assert p1.exile == []
