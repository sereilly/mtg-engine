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


# --- W1G3: combat triggers, delayed effects and retargeting ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w1g3_rebound_game(set_pool, spell, spell_set="LEA"):
    """Rebound in seat 0's hand, *spell* in seat 1's, a creature on seat 0's board."""
    perm = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game = Game(players=[
        PlayerState(
            name="P1", hand=[set_pool("STH")["Rebound"]],
            battlefield=[perm], life=20,
        ),
        PlayerState(name="P2", hand=[set_pool(spell_set)[spell]], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    return game, perm


def _w1g3_rebound_spec(set_pool):
    card = set_pool("STH")["Rebound"]
    return derive_cast_spec(card, compile_card_oracle(card))


def test_rebound_is_supported_and_bounds_both_ends(set_pool):
    """"Change the target of target spell that targets only a player. The new
    target must be a player."

    Both printed restrictions land on the payload: the clause is CR 115.9a's
    count plus the shape of the one target — the same node Meddle builds from a
    condition and Reflecting Mirror from a noun phrase plus an "if".
    """
    card = set_pool("STH")["Rebound"]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_new_spell_target", "change_target_spell_target",
    ]
    assert steps[0].payload["current_target_type"] == "player"
    assert steps[0].payload["new_target"] == "player"
    assert _w1g3_rebound_spec(set_pool)["stack_single_target_type"] == "player"


def test_rebound_re_aims_a_spell_at_the_other_player(set_pool):
    """CR 115.7a: everything else the spell announced stays, and only the face
    it points at moves — so the Lava Burst's caster takes its own damage."""
    game, _perm = _w1g3_rebound_game(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.queue_from_hand(0, "Rebound", target_stack_index=0)
    game.resolve_stack()

    assert game.players[0].life == 20, game.log
    assert game.players[1].life == 17, game.log


def test_rebound_is_not_offered_a_spell_aimed_at_a_creature(set_pool):
    """The clause is a restriction, not decoration: a production that consumed
    "that targets only a player" and dropped it would let Rebound re-aim a
    Terror, which is a strictly larger card than the one printed."""
    game, perm = _w1g3_rebound_game(set_pool, "Terror", spell_set="LEA")
    game.queue_from_hand(1, "Terror", target_permanent_ids=[perm.permanent_id])

    offered = game._enumerate_targets(
        0, set_pool("STH")["Rebound"], _w1g3_rebound_spec(set_pool), for_cast=True
    )
    assert offered == [], game.log


def test_rebound_is_offered_a_spell_aimed_at_a_player(set_pool):
    """The other side of the same gate, so the test above is not passing for
    the wrong reason."""
    game, _perm = _w1g3_rebound_game(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)

    offered = game._enumerate_targets(
        0, set_pool("STH")["Rebound"], _w1g3_rebound_spec(set_pool), for_cast=True
    )
    assert [entry["name"] for entry in offered] == ["Lightning Bolt"], game.log


# --- W1G1: damage prevention, redirection and damage-event triggers ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def _w1g1_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g1_bear(name="Bear", power=2, toughness=2):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


def _w1g1_temper(set_pool, x_value):
    """Temper cast for *x_value* over a 2/2, with the shield armed."""
    game = _w1g1_duel()
    p1, _ = game.players
    bear = _nosick(Permanent(card=_w1g1_bear("Shielded Bear")))
    p1.battlefield.append(bear)
    p1.hand.append(set_pool("STH")["Temper"])
    result = game.cast_from_hand(
        0, "Temper", target_player_index=0, target_permanent_index=0,
        x_value=x_value,
    )
    assert result.supported
    return game, bear


def test_temper_puts_a_counter_on_as_each_point_is_prevented(set_pool):
    """"Prevent the next X damage that would be dealt to target creature this
    turn. For each 1 damage prevented this way, put a +1/+1 counter on that
    creature."

    CR 615.5: "the prevention takes place at the time the original event would
    have happened; the rest of the effect takes place immediately afterward."
    So the counters arrive **inside the damage event**, which is the assertion
    that matters — a reading that placed them when the spell resolved would put
    down zero for ever, and would report exactly the same "supported".

    Three numbers, because each is a different way to get it wrong: no damage
    marked (the points really were prevented), two counters (one per point, not
    one per event), and the shield spent down to nothing.
    """
    game, bear = _w1g1_temper(set_pool, 2)
    printed = bear.effective_power

    assert bear.effective_power == printed, "nothing is placed at resolution"

    game._mark_damage_on_permanent(bear, 2)

    assert bear.damage_marked == 0
    assert bear.effective_power == printed + 2
    assert bear.damage_prevention_pool == 0


def test_temper_only_pays_for_the_damage_its_shield_actually_absorbed(set_pool):
    """The pool is X points wide and the counters count points, not events
    (CR 615.7). An event larger than the pool leaves its remainder marked and
    buys exactly as many counters as the shield had left — a rider that read
    the *event* would grow the creature by the whole Fireball.
    """
    game, bear = _w1g1_temper(set_pool, 1)
    printed_toughness = bear.effective_toughness

    game._mark_damage_on_permanent(bear, 3)

    assert bear.damage_marked == 2, "only one point was in the pool"
    assert bear.effective_toughness == printed_toughness + 1
