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


def test_brood_of_cockroaches_returns_itself_at_the_next_end_step(set_pool):
    """"When this creature is put into your graveyard from the battlefield, at
    the beginning of the next end step, you lose 1 life and return this card to
    your hand."

    CR 700.4 makes the long spelling of the trigger *dies* — the whole of what
    was missing, since the delayed ability behind it already compiled. Two copies
    of the card sit in the graveyard so the return has to take exactly one: a
    hand and a graveyard both hold the same immutable definition per copy, which
    is the identity bug `engine/phases/upkeep_step.py` records about a graveyard.
    """
    brood = set_pool("VIS")["Brood of Cockroaches"]
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P0", graveyard=[brood]),
        _W1G4PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    perm = _W1G4Permanent(card=brood)
    game.players[0].battlefield.append(perm)
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    game._destroy_swept_permanents(game.players[0], lambda c: c is perm)
    for _ in range(10):
        if not game.stack:
            break
        game.resolve_top_of_stack()

    assert len(game.players[0].graveyard) == 2
    assert len(game.delayed_triggers) == 1
    assert game.players[0].life == 20, "the delayed half waits for the end step"

    game.resolve_end_step(0)
    for _ in range(10):
        if not game.stack:
            break
        game.resolve_top_of_stack()

    assert game.players[0].life == 19
    assert [c.name for c in game.players[0].hand] == ["Brood of Cockroaches"]
    assert len(game.players[0].graveyard) == 1, "exactly one copy left the yard"


def test_kookus_only_bites_while_its_keeper_is_absent(set_pool):
    """"At the beginning of your upkeep, if you don't control a creature named
    Keeper of Kookus, this creature deals 3 damage to you and attacks this turn
    if able."

    Three things at once, and the printed name is the interesting one: it is a
    noun phrase parsed as data (`named`), not a name the engine branches on.
    CR 603.4's intervening-if is checked before the ability is put on the stack,
    so with the Keeper out nothing triggers at all.
    """
    pool = set_pool("VIS")
    keeper = _W1G4CardDefinition(
        name="Keeper of Kookus", mana_cost="", cmc=0.0,
        type_line="Creature - Human Nomad", oracle_text="", colors=(),
        color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Keeper of Kookus"}, power="2", toughness="2",
    )

    def _upkeep(with_keeper: bool):
        game = _W1G4Game(players=[
            _W1G4PlayerState(name="P0"), _W1G4PlayerState(name="P1"),
        ])
        game.enforce_mana_costs = False
        kookus = _W1G4Permanent(card=pool["Kookus"])
        game.players[0].battlefield.append(kookus)
        if with_keeper:
            game.players[0].battlefield.append(_W1G4Permanent(card=keeper))
        game.begin_turn_bookkeeping(0)
        game.active_player_index = 0
        game.resolve_upkeep(0, defer_priority=True)
        triggered = bool(game.stack)
        for _ in range(10):
            if not game.stack:
                break
            game.resolve_top_of_stack()
        return game, kookus, triggered

    game, kookus, triggered = _upkeep(with_keeper=False)
    assert triggered
    assert game.players[0].life == 17
    assert kookus.metadata.get("must_attack_until_eot") is True

    game, kookus, triggered = _upkeep(with_keeper=True)
    assert not triggered, "CR 603.4: a gated trigger whose condition is false does not trigger"
    assert game.players[0].life == 20
    assert kookus.metadata.get("must_attack_until_eot") is None
