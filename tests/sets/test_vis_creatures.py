"""Visions creatures.

Opened at the set's ingest with the yield of Phase 1's suite run — see
SET_PLAYBOOK.md, "treat what fires as yield, not noise".
"""

from engine.oracle import compile_card_oracle


def test_kyscu_drake_charges_both_halves_of_its_conjoined_sacrifice(set_pool):
    """"Sacrifice this creature **and a creature named Spitting Drake**".

    Two objects under one printed verb, joined by a bare "and" with no comma —
    the shape every reader in the charger declined. The Oxford-list regex needs
    a comma before its "and", the single-object delimiter is switched off once
    "sacrifice this ..." has set ``sacrifice_self``, and the "any number of"
    reader wants a set. So the Drake's own sacrifice was charged and the second
    creature was not: an ability activated for less than the card prints, which
    is the failure that neither crashes nor goes missing.
    """
    drake = set_pool("VIS")["Kyscu Drake"]
    program = compile_card_oracle(drake)

    tutor = [
        ability
        for ability in program.activated_abilities
        if ability.cost.sacrifice_self
    ]
    assert len(tutor) == 1, "the tutor ability is the one that sacrifices itself"
    cost = tutor[0].cost

    # The source in its flag and the chosen permanent in the filter — the same
    # encoding the Oxford-list path already gives the same two facts.
    assert cost.sacrifice_self is True
    assert cost.sacrifice_filter == {
        "type_filter": "creature",
        "named": "spitting drake",
    }


# --- W1G2: land animation with a colour ---

from engine import Game, PlayerState
from engine.models import Permanent


def _w1g2_druid_board(set_pool):
    druid = Permanent(card=set_pool("VIS")["Quirion Druid"])
    forest = Permanent(card=set_pool("LEA")["Forest"])
    druid.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[druid, forest]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    return game, forest


def test_quirion_druid_animates_a_land_indefinitely(set_pool):
    """"{G}, {T}: Target land becomes a 2/2 green creature that's still a land.
    (This effect lasts indefinitely.)"

    The indefinite animation already existed (Mishra's Groundbreaker); what this
    card added was the **colour word** inside the creature body, which the
    production stopped at.
    """
    game, forest = _w1g2_druid_board(set_pool)
    assert not forest.is_creature

    result = game.activate_permanent_ability(
        0, "Quirion Druid", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert forest.is_creature
    assert (forest.effective_power, forest.effective_toughness) == (2, 2)
    assert forest.has_type("land"), "that's still a land"


def test_quirion_druid_makes_the_land_green(set_pool):
    """CR 613 layer 5, the half of the sentence the animation record cannot
    carry. A colourless land animated without its colour is a permanent Circle
    of Protection: Green does not stop — a word consumed and dropped."""
    game, forest = _w1g2_druid_board(set_pool)
    game.activate_permanent_ability(
        0, "Quirion Druid", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()

    assert forest.effective_colors == {"G"}


def test_quirion_druid_s_animation_survives_the_turn(set_pool):
    """CR 611.2a: no stated duration, so it lasts as long as the game does. The
    printed reminder says so and the lexer drops it, which is why the *absence*
    of "until end of turn" is what the production reads."""
    game, forest = _w1g2_druid_board(set_pool)
    game.activate_permanent_ability(
        0, "Quirion Druid", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()

    game.start_turn(1)
    game.start_turn(0)

    assert forest.is_creature
    assert forest.effective_colors == {"G"}
