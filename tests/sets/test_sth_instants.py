"""Stronghold instants.

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


def _g2i_creature(name, power, toughness):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _g2i_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g2i_game(mine, theirs, hand=()) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine), hand=list(hand)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_change_of_heart_marks_one_creature_and_not_the_board(set_pool):
    """"Target creature can't attack this turn."

    A *targeted* restriction, which is the whole reason it is not the blanket
    one printed with the same words: routed through that kind it would ground
    every creature the noun phrase describes, and "target creature" describes
    all of them. The bystander is the assertion.
    """
    heart = set_pool("STH")["Change of Heart"]
    program = compile_card_oracle(heart)
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == [
        "target_cant_attack_until_eot"
    ]

    marked = _g2i_nosick(Permanent(card=_g2i_creature("Raider", 2, 2)))
    bystander = _g2i_nosick(Permanent(card=_g2i_creature("Rider", 2, 2)))
    game = _g2i_game([marked, bystander], [], hand=[heart])
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.can_attack(marked, 1)

    result = game.cast_from_hand(
        0, "Change of Heart", target_player_index=0, target_permanent_index=0,
    )
    assert result.supported, result
    resolve_stack(game)

    assert not game.can_attack(marked, 1)
    assert game.can_attack(bystander, 1), (
        "the spell named one creature; a blanket reading would ground both"
    )


def test_change_of_heart_s_mark_is_swept_with_the_turn(set_pool):
    """"This turn" is the cleanup sweep and nothing else.

    A mark no ``_EOT_METADATA_KEYS`` entry names would ground the creature for
    the rest of the game while the card reported supported - the failure Blaze
    of Glory's pair records in ``engine/combat_permissions.py``.
    """
    from engine.combat_permissions import CANT_ATTACK_UNTIL_EOT

    marked = _g2i_nosick(Permanent(card=_g2i_creature("Raider", 2, 2)))
    game = _g2i_game([], [marked])
    marked.metadata[CANT_ATTACK_UNTIL_EOT] = True
    game.start_turn(0)
    game.resolve_cleanup_step(0)

    assert CANT_ATTACK_UNTIL_EOT not in marked.metadata


def test_provoke_untaps_a_creature_and_makes_it_block(set_pool):
    """"Untap target creature you don't control. That creature blocks this turn
    if able."

    Both sentences, and the second one is why: the card reported *supported* on
    its "Draw a card" line alone, with the untap and the requirement dropped
    together. CR 509.1c's weakest requirement - block **something** - so the
    declaration that leaves the provoked creature at home is the illegal one.
    """
    provoke = set_pool("STH")["Provoke"]
    program = compile_card_oracle(provoke)
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "untap_target_permanent", "force_bound_to_block_until_eot",
    ]

    attacker = _g2i_nosick(Permanent(card=_g2i_creature("Raider", 2, 2)))
    provoked = _g2i_nosick(Permanent(card=_g2i_creature("Guard", 2, 2)))
    provoked.tapped = True
    game = _g2i_game([attacker], [provoked], hand=[provoke])
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.cast_from_hand(
        0, "Provoke", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result
    resolve_stack(game)
    assert not provoked.tapped, "the first sentence untaps it"

    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    ok, message = game.declare_blockers(1, {})
    assert not ok and "blocks each combat if able" in message, message
    assert game.declare_blockers(1, {0: 0})[0]
