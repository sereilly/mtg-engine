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


# --- W1G4: upkeep, end-step and per-player step triggers ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import CardDefinition as _W1G4CardDefinition
from engine.models import Permanent as _W1G4Permanent
from engine.named_counters import counters_on as _w1g4_counters_on


def _w1g4_bear(name: str) -> _W1G4Permanent:
    return _W1G4Permanent(card=_W1G4CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name}, power="2", toughness="2",
    ))


def test_aku_djinn_grows_every_opponents_creatures_and_none_of_yours(set_pool):
    """"At the beginning of your upkeep, put a +1/+1 counter on each creature
    each opponent controls."

    "Each opponent controls" is the distributive spelling of "your opponents
    control" and names the same seats (CR 109.5), so it is the same filter key
    rather than a third one. The controller's own board is what makes the card
    a drawback, and a dropped scope would have grown it instead.
    """
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P0"), _W1G4PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    djinn = _W1G4Permanent(card=set_pool("VIS")["Aku Djinn"])
    mine = _w1g4_bear("Mine")
    theirs = _w1g4_bear("Theirs")
    game.players[0].battlefield.extend([djinn, mine])
    game.players[1].battlefield.append(theirs)
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    game.resolve_upkeep(0, defer_priority=True)
    for _ in range(10):
        if not game.stack:
            break
        game.resolve_top_of_stack()

    assert _w1g4_counters_on(theirs, "+1/+1") == 1
    assert _w1g4_counters_on(mine, "+1/+1") == 0
    assert _w1g4_counters_on(djinn, "+1/+1") == 0
