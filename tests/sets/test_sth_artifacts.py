"""Stronghold artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""



# --- W1G2: combat restrictions and requirements ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2a_creature(name, power, toughness):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _g2a_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g2a_game(mine, theirs, hand=()) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine), hand=list(hand)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def test_bullwhip_damages_a_creature_and_then_compels_it(set_pool):
    """"{2}, {T}: This artifact deals 1 damage to target creature. That
    creature attacks this turn if able."

    Both sentences of one ability, and the second names no target of its own:
    CR 601.2c fixed one creature when the ability was activated, so "that
    creature" is the object the damage step in front of it hit. A requirement
    that asked for a second target would make the picker ask twice; one that
    dropped the pronoun would compel nobody.
    """
    bullwhip = set_pool("STH")["Bullwhip"]
    program = compile_card_oracle(bullwhip)
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "deal_damage", "force_bound_to_attack_until_eot",
    ]

    whip = _g2a_nosick(Permanent(card=bullwhip))
    victim = _g2a_nosick(Permanent(card=_g2a_creature("Raider", 2, 3)))
    bystander = _g2a_nosick(Permanent(card=_g2a_creature("Rider", 2, 3)))
    game = _g2a_game([whip], [victim, bystander])

    result = game.activate_permanent_ability(
        0, "Bullwhip", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result
    resolve_stack(game)

    assert victim.damage_marked == 1
    assert victim.metadata.get("must_attack_until_eot")
    assert not bystander.metadata.get("must_attack_until_eot"), (
        "the pronoun names the creature the damage step hit, not the board"
    )


def test_ensnaring_bridge_reads_the_hand_at_every_declaration(set_pool):
    """"Creatures with power greater than the number of cards in your hand
    can't attack."

    The bound is the size of a hidden zone and "your" is the Bridge's
    controller (CR 109.5), so the same board answers differently as its
    controller's hand empties and fills. Strictly greater: a creature exactly at
    the count still attacks.
    """
    bridge = Permanent(card=set_pool("STH")["Ensnaring Bridge"])
    program = compile_card_oracle(bridge.card)
    assert program.supported, program.reason

    big = _g2a_nosick(Permanent(card=_g2a_creature("Ogre", 3, 3)))
    small = _g2a_nosick(Permanent(card=_g2a_creature("Scout", 1, 1)))
    filler = _g2a_creature("Spare", 1, 1)
    game = _g2a_game([big, small, bridge], [])

    game.players[0].hand[:] = [filler] * 3
    assert game.can_attack(big, 1), (
        "power 3 against a hand of 3 is not *greater* than it"
    )
    game.players[0].hand[:] = [filler] * 2
    assert not game.can_attack(big, 1), "3 is greater than 2"
    assert game.can_attack(small, 1), (
        "the same board, one power down: the restriction names a threshold, "
        "not a creature"
    )

    game.players[0].hand.clear()
    assert not game.can_attack(small, 1), (
        "an empty hand grounds every creature with power 1 or more"
    )


def test_ensnaring_bridge_counts_its_own_controller_s_hand(set_pool):
    """"Your" is the seat whose ability the sentence is, not the creature's.

    A restriction printed on one permanent that reaches every seat's creatures
    is the Moat shape; what this adds is that the *number* comes from the
    Bridge's controller. Reading the attacker's controller's hand instead would
    make the card asymmetrical in the direction nobody printed.
    """
    bridge = Permanent(card=set_pool("STH")["Ensnaring Bridge"])
    theirs = _g2a_nosick(Permanent(card=_g2a_creature("Ogre", 3, 3)))
    filler = _g2a_creature("Spare", 1, 1)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bridge]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    game._close_current_priority_step()
    game.players[0].hand.clear()
    game.players[1].hand[:] = [filler] * 5

    assert not game.can_attack(theirs, 0), (
        "the empty hand that matters is the Bridge controller's, and the "
        "attacker's own five cards do not lift the restriction"
    )
