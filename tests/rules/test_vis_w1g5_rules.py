"""Rules tests earned by Visions wave 1, group 5.

Each of these is about a Comprehensive Rule rather than about a card, which is
what puts it here instead of in ``tests/sets/`` — the cards that provoked them
are named in the docstrings and have their own per-card tests beside their set.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent


def _pool(code):
    return {
        card.name: card
        for card in load_cards(manifest_set_path(code, include_measured=True))
    }


def _game(*battlefields, **kwargs):
    players = [
        PlayerState(name=f"P{index + 1}", battlefield=list(pile), **kwargs)
        for index, pile in enumerate(battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    for player in players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


@pytest.mark.cr("608.2b", "608.2c")
def test_a_targets_legality_is_checked_once_not_once_per_instruction():
    """CR 608.2b checks a target's legality **before** the resolution runs, and
    608.2c then follows the instructions in the order written. One printed
    instance of the word "target" is one check however many steps the sentence
    lowers to.

    Phantasmal Mount is the card that proves it: "target creature you control
    **with toughness 2 or less** gets +1/+1 **and** gains flying until end of
    turn" is one noun phrase and two lowered steps. The pump runs first and
    takes a 2/2 to toughness 3; a grant that re-asked the printed bound at its
    own step would find nothing and the card's only ability would fly nobody.

    The two grant handlers disagreed about this for a different reason —
    ``grant_target_flying_until_eot`` read no filter at all, so its fallback
    scan could land on any creature — and closing that hole is what made the
    ordering question answerable rather than latent.
    """
    ice, lea = _pool("ICE"), _pool("LEA")
    mount = Permanent(card=ice["Phantasmal Mount"])
    rider = Permanent(card=lea["Grizzly Bears"])
    game = _game([mount, rider], [])

    result = game.activate_permanent_ability(
        0, "Phantasmal Mount",
        target_player_index=0,
        permanent_index=game.battlefield_index_of(mount),
        target_permanent_index=game.battlefield_index_of(rider),
    )
    assert result.supported
    game.resolve_stack()

    assert (rider.effective_power, rider.effective_toughness) == (3, 3)
    assert rider.has_keyword("flying")


@pytest.mark.cr("608.2b")
def test_a_keyword_grant_obeys_the_printed_noun_phrase_it_scans_under():
    """The other half of the same fix. With nothing announced, the fallback
    scan is all a grant has — and reading no filter at all is how "target
    creature **you control**" reached an opponent's creature.

    Whalebone Glider is one of the five shipped cards that had the hole
    ("target creature **with power 3 or less**"); Chariot of the Sun, Goblin
    Kites, Krovikan Elementalist and Phantasmal Mount are the others, between
    them printing a seat bound and two characteristic bounds.
    """
    ice, lea = _pool("ICE"), _pool("LEA")
    glider = Permanent(card=ice["Whalebone Glider"])
    theirs = Permanent(card=lea["Shivan Dragon"])
    game = _game([glider], [theirs])

    game.activate_permanent_ability(
        0, "Whalebone Glider",
        permanent_index=game.battlefield_index_of(glider),
    )
    game.resolve_stack()

    # A 5/5 is outside "power 3 or less", so the scan found nobody rather than
    # granting to whatever it reached first. (The Dragon prints flying itself,
    # so what is read is the *grant* record, not the keyword.)
    from engine.keywords import ability_effects
    assert not [
        entry for entry in ability_effects(theirs)
        if entry["keyword"] == "flying" and entry["grant"]
    ]


@pytest.mark.cr("701.23a", "701.23d")
def test_a_search_for_any_number_of_cards_is_bounded_by_the_zone():
    """CR 701.23a: a search looks at every card in the zone. "Any number of"
    prints no ceiling at all, so the only bound is how many cards the phrase
    admits — which is a fact about this library at this moment, not about the
    card, and is therefore resolved at the handler rather than baked into a
    payload.

    Goblin Recruiter is the card. CR 701.23b keeps finding fewer legal, which is
    why ``up_to`` rides with the count.
    """
    vis, mir, lea = _pool("VIS"), _pool("MIR"), _pool("LEA")
    goblins = [mir["Goblin Elite Infantry"], mir["Goblin Tinkerer"]]
    game = Game(players=[
        PlayerState(
            name="P1", hand=[vis["Goblin Recruiter"]],
            library=[lea["Island"], goblins[0], goblins[1], lea["Mountain"]],
        ),
        PlayerState(name="P2", library=[lea["Island"]] * 4),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    game.cast_from_hand(0, "Goblin Recruiter")
    game.resolve_stack()

    assert game.pending_search_library["count"] == len(goblins)

    # CR 701.23b: finding fewer than the ceiling is a legal answer, and finding
    # none ends the search.
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 1}]
    )
    assert game.players[0].library[0].name == goblins[0].name


@pytest.mark.cr("400.7", "122.1")
def test_a_counter_placed_after_a_return_lands_on_the_new_object():
    """CR 400.7: a permanent that leaves the battlefield and comes back is a
    **new object**. So "return it to the battlefield … and put a death counter
    on it" cannot place the counter on the object that died — that one is gone,
    and CR 122.1's marker would sit on nothing.

    Bogardan Phoenix is the card, and the failure is silent in the worst
    direction: the log said the counter was placed, the store read zero, and the
    Phoenix returned every time it died.
    """
    from engine.named_counters import counters_on

    vis, lea = _pool("VIS"), _pool("LEA")
    phoenix = Permanent(card=vis["Bogardan Phoenix"])
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[phoenix],
            hand=[lea["Lightning Bolt"]], library=[lea["Island"]] * 4,
        ),
        PlayerState(name="P2", library=[lea["Island"]] * 4),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()

    game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(phoenix),
    )
    game.resolve_stack()
    game._settle()
    game.resolve_stack()

    returned = list(game.controlled_by(game.players[0]))
    assert len(returned) == 1
    assert returned[0] is not phoenix, "CR 400.7: a new object"
    assert counters_on(returned[0], "death") == 1
    assert counters_on(phoenix, "death") == 0


@pytest.mark.cr("603.10", "122.3")
def test_a_dying_permanents_named_counters_are_last_known_information():
    """CR 603.10: a leaves-the-battlefield trigger reads the game state
    immediately before the event. A card in a graveyard carries no counters at
    all, so "if it had a **death** counter on it" is answerable only from what
    the fire site froze.

    CR 122.3's counters — those with no rules meaning of their own — live one
    metadata key per word rather than in the single P/T channel, so freezing
    them is a map and not the bool the +1/+1 clause reads. Two records, two
    keys: a reader written for one must fail by name rather than receive the
    other.

    Asserted through the *engine*, not by reading the dict: the two death fire
    sites are two loops over one event, and information only one of them
    records is a condition that answers differently depending on which loop
    announced it.
    """
    from engine.named_counters import add_counters

    vis, lea = _pool("VIS"), _pool("LEA")
    phoenix = Permanent(card=vis["Bogardan Phoenix"])
    add_counters(phoenix, "death", 1)
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[phoenix],
            hand=[lea["Lightning Bolt"]], library=[lea["Island"]] * 4,
        ),
        PlayerState(name="P2", library=[lea["Island"]] * 4),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()

    game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(phoenix),
    )
    game.resolve_stack()
    game._settle()
    game.resolve_stack()

    # It had one when it died, so it is exiled rather than returned — and the
    # exile comes out of the graveyard, which is where CR 603.3 had already put
    # the card by the time the trigger resolved.
    assert list(game.controlled_by(game.players[0])) == []
    assert [c.name for c in game.players[0].exile] == ["Bogardan Phoenix"]
    assert "Bogardan Phoenix" not in [c.name for c in game.players[0].graveyard]
