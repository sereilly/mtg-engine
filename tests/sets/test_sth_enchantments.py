"""Stronghold enchantments.

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


def _g2e_creature(name, power, toughness, subtype="Test", keywords=()):
    text = "\n".join(word.capitalize() for word in keywords)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=f"Creature - {subtype}",
        oracle_text=text, colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": f"Creature - {subtype}",
             "power": str(power), "toughness": str(toughness)},
    )


def _g2e_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g2e_combat(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def test_rolling_stones_lifts_defender_for_walls_and_nothing_else(set_pool):
    """"Wall creatures can attack as though they didn't have defender."

    CR 609.4: the permission applies to the stated effect only, so the Wall
    still *has* defender for everything that counts them - and the noun phrase
    is payload, so the non-Wall defender beside it is untouched. Both halves are
    the assertion; a reading that removed the keyword or that ignored the noun
    would pass one of them and fail the other.
    """
    stones = Permanent(card=set_pool("STH")["Rolling Stones"])
    program = compile_card_oracle(stones.card)
    assert program.supported, program.reason

    wall = _g2e_nosick(Permanent(
        card=_g2e_creature("Stone Wall", 0, 4, "Wall", ("defender",))
    ))
    keeper = _g2e_nosick(Permanent(
        card=_g2e_creature("Gate Keeper", 0, 4, "Soldier", ("defender",))
    ))
    game = _g2e_combat([wall, keeper], [])
    assert not game.can_attack(wall, 1)
    assert not game.can_attack(keeper, 1)

    game.players[0].battlefield.append(stones)
    assert game.can_attack(wall, 1)
    assert not game.can_attack(keeper, 1), (
        "the sentence names Walls; a dropped noun phrase would free every "
        "creature with defender"
    )
    assert game._has_keyword(wall, "defender"), (
        "CR 609.4: the permission is not a keyword removal"
    )


def test_invasion_plans_compels_every_block_and_moves_the_choice(set_pool):
    """Both printed lines, because a card is supported when *any* of them is.

    "All creatures block each combat if able" is CR 509.1c over a described set,
    found by a board scan because the sentence is printed on an enchantment
    nobody is blocking with. "The attacking player chooses how each creature
    blocks each combat" is CR 509.1a's chooser, substituted by a static rather
    than by Melee's one-shot - so the seat is derived at the declaration and
    stops being derived when the enchantment leaves.
    """
    plans = Permanent(card=set_pool("STH")["Invasion Plans"])
    program = compile_card_oracle(plans.card)
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == [
        "creatures_must_block", "attacker_chooses_blocks",
    ]

    attacker = _g2e_nosick(Permanent(card=_g2e_creature("Raider", 2, 2)))
    blocker = _g2e_nosick(Permanent(card=_g2e_creature("Guard", 2, 2)))
    game = _g2e_combat([attacker, plans], [blocker])
    assert game.block_chooser_index(1) == 0, (
        "the attacking player is the active player (CR 506.2)"
    )
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    # The defender may no longer submit their own declaration: CR 509.1a's
    # choices are seat 0's while the enchantment is out.
    refused, whose = game.declare_blockers(1, {0: 0})
    assert not refused and "P1 chooses" in whose, whose

    ok, message = game.declare_blockers(1, {}, acting_index=0)
    assert not ok and "blocks each combat if able" in message, message
    assert game.declare_blockers(1, {0: 0}, acting_index=0)[0]


def test_invasion_plans_stops_choosing_when_it_leaves(set_pool):
    """The substitution is derived, not stored.

    Melee writes a seat onto the game and the combat reset clears it; this is a
    static, so the only thing that ends it is the enchantment leaving - and a
    board scan is what makes that automatic rather than something a zone-change
    path has to remember.
    """
    plans = Permanent(card=set_pool("STH")["Invasion Plans"])
    attacker = _g2e_nosick(Permanent(card=_g2e_creature("Raider", 2, 2)))
    blocker = _g2e_nosick(Permanent(card=_g2e_creature("Guard", 2, 2)))
    game = _g2e_combat([attacker, plans], [blocker])
    assert game.block_chooser_index(1) == 0

    game.remove_from_battlefield(plans)
    assert game.block_chooser_index(1) == 1, (
        "with the enchantment gone the defending player chooses again"
    )


# --- W1G3: combat triggers, delayed effects and retargeting ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g3_creature(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_block(attackers, defenders, *, blocks, watchers=()):
    """Seat 0 attacks with *attackers*; seat 1 blocks per *blocks*.

    *watchers* are permanents put on seat 0's battlefield before combat — the
    board-wide enchantments these tests are about, which are in no combat at all.

    ``blocks`` is keyed by position in *attackers* / *defenders*; the watchers
    sitting in front of the attackers on the battlefield are offset here so no
    test has to count them.
    """
    game = Game(players=[
        PlayerState(name="P1", battlefield=[*watchers, *attackers]),
        PlayerState(name="P2", battlefield=list(defenders)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in (*watchers, *attackers, *defenders):
        perm.summoning_sick = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(
        0, [len(watchers) + i for i in range(len(attackers))]
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {b: a + len(watchers) for b, a in blocks.items()}
    )[0]
    game.resolve_stack()
    return game


def test_heat_of_battle_burns_each_blocking_creatures_controller(set_pool):
    """"Whenever a creature blocks, this enchantment deals 1 damage to that
    creature's controller."

    A board-wide watcher on a third permanent: it is neither combatant, so the
    seat is the one the declare-blockers announcement froze rather than anything
    read off the source. Two blockers, two triggers, two damage.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attackers = [Permanent(card=_w1g3_creature(f"Bear {i}", 2, 2)) for i in range(2)]
    blockers = [Permanent(card=_w1g3_creature(f"Wall {i}", 0, 4)) for i in range(2)]
    game = _w1g3_block(attackers, blockers, blocks={0: 0, 1: 1}, watchers=[heat])

    assert game.players[1].life == 18, game.log
    assert game.players[0].life == 20, game.log


def test_heat_of_battle_fires_once_per_blocker_not_once_per_attacker(set_pool):
    """CR 509.3c: a condition with no partner phrase fires once for the creature
    the event is about, however many creatures are on the other side.

    One blocker against one attacker is one trigger — the per-pair announcement
    the narrowed spellings answer to would be the same number here, so the test
    that separates them is the multi-block one below.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    blocker = Permanent(card=_w1g3_creature("Wall", 0, 4))
    game = _w1g3_block([attacker], [blocker], blocks={0: 0}, watchers=[heat])

    assert game.players[1].life == 19, game.log


def test_heat_of_battle_fires_once_for_each_of_two_creatures_blocking_one(set_pool):
    """CR 509.3d against CR 509.3c, on the one board that tells them apart.

    Two creatures block a single attacker. "Whenever a creature blocks" is about
    each *blocker*, so it fires twice; the per-pair announcement the narrowed
    spellings (No Quarter) answer to would fire twice here as well — what would
    fire twice *wrongly* is the becomes-blocked side, which is one creature
    becoming blocked and is announced once. Both readings share one fire site,
    so this is the board that would show the pair announcement leaking into the
    bare condition.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    blockers = [Permanent(card=_w1g3_creature(f"Wall {i}", 0, 4)) for i in range(2)]
    game = _w1g3_block([attacker], blockers, blocks={0: 0, 1: 0}, watchers=[heat])

    assert game.players[1].life == 18, game.log


def test_heat_of_battle_says_nothing_about_an_unblocked_attack(set_pool):
    """The condition is about blocking, not about combat: an attack nobody
    blocks announces no firing at all."""
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    game = _w1g3_block([attacker], [], blocks={}, watchers=[heat])

    assert game.players[1].life == 20, game.log
