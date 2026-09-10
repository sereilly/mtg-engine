"""Mercadian Masques enchantments, Auras included.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: combat-event triggers and the defending player ---

import dataclasses

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_creature_card, resolve_stack


def _g2e_colored(name, power, toughness, color):
    """A vanilla creature of one colour — the trigger under test narrows by
    colour, so the colour has to be on the card rather than only in its raw
    payload."""
    return dataclasses.replace(
        _mk_creature_card(name, power, toughness),
        colors=(color,), color_identity=(color,),
    )


def _g2e_board(set_pool, enchantment, *, attackers, blockers=(), owner=1):
    """*enchantment* on seat *owner*'s battlefield, with seat 0 attacking.

    Both cards in this block hang off a **board-wide** combat event — the
    watcher is neither combatant — so the enchantment sits on the defending
    seat's side and the creatures that matter are somebody else's. A compiled
    program cannot show which half of the combat the effect landed on; only a
    driven declaration can.
    """
    attacking = [Permanent(card=c) for c in attackers]
    blocking = [Permanent(card=c) for c in blockers]
    seats = [
        PlayerState(name="P1", battlefield=list(attacking), life=20),
        PlayerState(name="P2", battlefield=list(blocking), life=20),
    ]
    seats[owner].battlefield.append(
        Permanent(card=set_pool("MMQ")[enchantment])
    )
    game = Game(players=seats)
    game._settle()
    for perm in attacking + blocking:
        perm.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, list(range(len(attacking))), defending_player_index=1
    )[0]
    resolve_stack(game)
    return game, attacking, blocking


def test_briar_patch_shrinks_only_the_creature_that_attacked_its_controller(
    set_pool,
):
    """"Whenever a creature attacks you, it gets -1/-0 until end of turn."

    "It" names the creature the announcement was about, not the enchantment and
    not a target — and the printed "attacks **you**" is the whole narrowing, so
    the enchantment has to be on the *defending* seat for anything to happen at
    all. Two attackers, so the once-per-attacker reading (CR 508.1) is asserted
    as well: each loses one power, never one of them losing two.
    """
    game, attackers, _ = _g2e_board(
        set_pool, "Briar Patch",
        attackers=[_mk_creature_card("Bear", 2, 2), _mk_creature_card("Ox", 3, 3)],
    )

    assert [a.effective_power for a in attackers] == [1, 2]
    assert [a.effective_toughness for a in attackers] == [2, 3]


def test_briar_patch_ignores_a_combat_it_is_not_the_defender_of(set_pool):
    """The same enchantment on the *attacking* seat's battlefield does nothing.

    CR 506.2's "you" is the enchantment's controller, and the creature attacking
    is that controller's own. A version that dropped the printed "attacks you"
    would shrink its own team every combat, which is the direction this asserts
    against — the narrowing has to survive both the trigger's filter and the
    re-check at resolution.
    """
    game, attackers, _ = _g2e_board(
        set_pool, "Briar Patch",
        attackers=[_mk_creature_card("Bear", 2, 2)], owner=0,
    )

    assert attackers[0].effective_power == 2


def test_righteous_indignation_pumps_the_blocker_not_what_it_blocked(set_pool):
    """"Whenever a creature blocks a black or red creature, the blocking
    creature gets +1/+1 until end of turn."

    The role word is the whole test. Under a *blocks* event the announcement's
    subject is the blocker and its partner is the attacker, so a lowering that
    read the partner table would have pumped the creature being blocked — the
    opponent's, and the opposite of what the card says.
    """
    red = _g2e_colored("Red Ogre", 3, 3, "R")
    green = _g2e_colored("Green Bear", 2, 2, "G")
    game, attackers, blockers = _g2e_board(
        set_pool, "Righteous Indignation",
        attackers=[red, green],
        blockers=[_mk_creature_card("Guard", 1, 1), _mk_creature_card("Watch", 1, 1)],
    )
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: 0, 1: 1})[0]
    resolve_stack(game)

    assert blockers[0].effective_power == 2, "blocked the red creature"
    assert blockers[1].effective_power == 1, "blocked the green one, no trigger"
    assert [a.effective_power for a in attackers] == [3, 2], "not the attackers"
