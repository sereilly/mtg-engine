"""Tempest sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W2G2: damage sized by a creature's own power (CR 119.3) ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from tests.helpers import _mk_creature_card, _nosick


def _w2g2_spell_board(spell, p0_creatures, p1_creatures):
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p0.hand.append(spell)
    for card in p0_creatures:
        p0.battlefield.append(_nosick(Permanent(card=card)))
    for card in p1_creatures:
        p1.battlefield.append(_nosick(Permanent(card=card)))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    return game, p0, p1


def test_w2g2_repentance_makes_a_creature_kill_itself(set_pool):
    """``Target creature deals damage to itself equal to its power.``

    CR 119.3: the damage is dealt **by the creature**, so the source is the
    permanent and not the sorcery — which is what makes a bite different from
    the generic damage instruction and why it is its own kind.
    """
    game, p0, p1 = _w2g2_spell_board(
        set_pool("TMP")["Repentance"], [_mk_creature_card("Ogre", 4, 4)], []
    )
    assert game.cast_from_hand(
        0, "Repentance",
        target_player_index=0,
        target_permanent_ids=[p0.battlefield[0].permanent_id],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert list(game.controlled_by(0)) == [], game.log
    assert any("deals 4 damage to itself" in line for line in game.log), game.log


def test_w2g2_repentance_on_a_zero_power_creature_deals_nothing(set_pool):
    """CR 120.8: damage of 0 is not dealt at all, so nothing is marked and the
    Wall survives — the direction a handler that skipped the check would get
    right by accident and the log would get wrong."""
    game, p0, p1 = _w2g2_spell_board(
        set_pool("TMP")["Repentance"], [_mk_creature_card("Wall", 0, 4)], []
    )
    assert game.cast_from_hand(
        0, "Repentance",
        target_player_index=0,
        target_permanent_ids=[p0.battlefield[0].permanent_id],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert [p.card.name for p in p0.battlefield] == ["Wall"]


def test_w2g2_deadshot_taps_one_target_and_bites_with_it(set_pool):
    """``Tap target creature. It deals damage equal to its power to another
    target creature.`` — the slot-per-clause gap the engine stated in its own
    refusal. Two announced targets (CR 601.2c), the tap on slot 0 and the bite
    from slot 0 to slot 1."""
    deadshot = set_pool("TMP")["Deadshot"]
    program = compile_card_oracle(deadshot)
    assert program.supported
    assert derive_cast_spec(deadshot, program) == {"kind": "creature", "max_targets": 2}

    game, p0, p1 = _w2g2_spell_board(
        deadshot, [_mk_creature_card("Ogre", 4, 4)], [_mk_creature_card("Squire", 1, 2)]
    )
    assert game.cast_from_hand(
        0, "Deadshot",
        target_player_index=0,
        target_permanent_ids=[
            p0.battlefield[0].permanent_id, p1.battlefield[0].permanent_id
        ],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert p0.battlefield[0].tapped, game.log
    assert list(game.controlled_by(1)) == [], game.log


def test_w2g2_deadshots_biter_need_not_be_yours(set_pool):
    """``target_bites_target`` had "you control" spelled into the handler —
    Garruk, Savage Herald's word, not the kind's. Deadshot names anybody's
    creature as the biter, so the slot is tested against its own printed noun
    phrase instead."""
    game, p0, p1 = _w2g2_spell_board(
        set_pool("TMP")["Deadshot"],
        [],
        [_mk_creature_card("Ogre", 4, 4), _mk_creature_card("Squire", 1, 2)],
    )
    assert game.cast_from_hand(
        0, "Deadshot",
        target_player_index=1,
        target_permanent_ids=[
            p1.battlefield[0].permanent_id, p1.battlefield[1].permanent_id
        ],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert [p.card.name for p in p1.battlefield] == ["Ogre"], game.log
    assert p1.battlefield[0].tapped
