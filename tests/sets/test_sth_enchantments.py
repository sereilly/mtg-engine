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
