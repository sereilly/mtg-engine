"""Prophecy creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: prevention and odd ones ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_blocked_by(set_pool, defender_name, attacker_names, blocks):
    """Seat 1 attacks seat 0 with *attacker_names* (LEA); seat 0's
    *defender_name* (PCY) blocks per *blocks* ({blocker slot: attacker slot});
    stopped in the declare-blockers step. W1G5's own."""
    lea = set_pool("LEA")
    defender = _W1G5Permanent(card=set_pool("PCY")[defender_name])
    attackers = [_W1G5Permanent(card=lea[n]) for n in attacker_names]
    me = _W1G5PlayerState(name="W1G5-A", battlefield=[defender])
    them = _W1G5PlayerState(name="W1G5-B", battlefield=list(attackers))
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    for perm in (defender, *attackers):
        perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, list(range(len(attackers))))[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, dict(blocks))[0]
    assert game.current_step == "declare_blockers"
    return game, me, them, defender, attackers


def _w1g5_finish_the_combat(game):
    for _ in range(6):
        if game.current_turn_phase == "postcombat_main":
            return
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)


def test_w1g5_shield_dancer_turns_the_attackers_damage_on_itself(set_pool):
    """"{2}{W}: The next time target attacking creature would deal combat damage
    to this creature this turn, that creature deals that damage to itself
    instead."

    Hill Giant attacks into the blocking Dancer; with the ability on the Giant,
    its 3 combat damage is dealt to the Giant (CR 614.9 — by the Giant, in
    full) and the Dancer's 1 lands too, so the Giant dies and the 1/3 Dancer is
    untouched. The picker offers attacking creatures only.
    """
    game, _me, them, dancer, (giant,) = _w1g5_blocked_by(
        set_pool, "Shield Dancer", ["Hill Giant"], {0: 0},
    )
    spec = game.activation_target_spec(0, 0, 0)
    assert [t["name"] for t in spec["valid_targets"]] == ["Hill Giant"]
    assert game.activate_permanent_ability(
        0, "Shield Dancer", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    _w1g5_finish_the_combat(game)

    assert [c.name for c in them.graveyard] == ["Hill Giant"]
    assert game.is_on_battlefield(dancer) and dancer.damage_marked == 0


def test_w1g5_shield_dancer_moves_one_instance_from_that_creature_only(set_pool):
    """"The next time" is one instance, and only the announced creature's: a
    second attacker blocked by nothing deals its damage to the player as usual,
    and the record does not reach it."""
    game, me, them, dancer, (giant, bears) = _w1g5_blocked_by(
        set_pool, "Shield Dancer", ["Hill Giant", "Grizzly Bears"], {0: 0},
    )
    assert game.activate_permanent_ability(
        0, "Shield Dancer", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    _w1g5_finish_the_combat(game)
    assert me.life == 18, "the unblocked Bears still connect"
    assert [c.name for c in them.graveyard] == ["Hill Giant"]


def _w1g5_glitter_table(set_pool, name, bolts):
    """*name* (PCY) on seat 0; seat 1 to act in its main phase holding *bolts*
    Lightning Bolts. W1G5's own."""
    lea = set_pool("LEA")
    cat = _W1G5Permanent(card=set_pool("PCY")[name])
    me = _W1G5PlayerState(name="W1G5-A", battlefield=[cat])
    them = _W1G5PlayerState(name="W1G5-B", hand=[lea["Lightning Bolt"]] * bolts)
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game._settle()
    game.active_player_index = 1
    game.current_turn_phase = "precombat_main"
    return game, me, them, cat


def _w1g5_bolt(game, cat):
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[cat.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)


def test_w1g5_glittering_lion_shield_comes_off_when_anyone_pays(set_pool):
    """"Prevent all damage that would be dealt to this creature. / {3}: Until
    end of turn, this creature loses "Prevent all damage that would be dealt to
    this creature." Any player may activate this ability."

    The opponent's first Bolt is prevented whole. The opponent then activates
    it (CR 602.1b: the text says which players may) and pays the {3} from
    **their own** pool (CR 602.1a), the Lion loses the line (CR 613.1f) and the
    second Bolt kills it.
    """
    game, me, them, lion = _w1g5_glitter_table(set_pool, "Glittering Lion", 2)
    _w1g5_bolt(game, lion)
    assert game.is_on_battlefield(lion) and lion.damage_marked == 0

    game.enforce_mana_costs = True
    them.mana_pool["R"] = 3
    assert game.activate_permanent_ability(
        1, "Glittering Lion", ability_index=0, source_controller_index=0,
    ).supported
    assert them.mana_pool["R"] == 0, "the activator pays"
    _w1g5_resolve_stack(game)
    game.enforce_mana_costs = False

    _w1g5_bolt(game, lion)
    assert not game.is_on_battlefield(lion)
    assert [c.name for c in me.graveyard] == ["Glittering Lion"]


def test_w1g5_glittering_lynx_gets_its_shield_back_at_cleanup(set_pool):
    """"Until end of turn" is the removal's whole lifetime: after the cleanup
    step (CR 514.2) the Lynx says the line again and the next Bolt is
    prevented. The activated ability itself is never what is lost."""
    game, _me, _them, lynx = _w1g5_glitter_table(set_pool, "Glittering Lynx", 1)
    assert game.activate_permanent_ability(
        1, "Glittering Lynx", ability_index=0, source_controller_index=0,
    ).supported
    _w1g5_resolve_stack(game)
    shield = "prevent all damage that would be dealt to this creature."
    assert shield not in lynx.effective_card.oracle_text.lower().splitlines()

    game.resolve_cleanup_step(1)
    assert shield in lynx.effective_card.oracle_text.lower().splitlines()
    game.start_turn(1)
    game._close_current_priority_step()
    game.active_player_index = 1
    game.current_turn_phase = "precombat_main"
    _w1g5_bolt(game, lynx)
    assert game.is_on_battlefield(lynx) and lynx.damage_marked == 0
# end of the W1G5 creatures block
