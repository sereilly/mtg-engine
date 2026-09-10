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


# --- W1G3: prevention shields and damage redirection ---
from engine import Game as _G3Game
from engine import PlayerState as _G3PlayerState
from engine.auras import attach_aura as _g3_attach
from engine.models import CardDefinition as _G3Card
from engine.models import Permanent as _G3Permanent
from tests.helpers import _damage_dealt as _g3_dealt


def _g3_creature(name, power=2, toughness=2):
    """A vanilla creature to hang a shield on or point one at."""
    line = "Creature - Test"
    return _G3Card(
        name=name, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _g3_board(seat0=(), seat1=()):
    """A two-seat game with the permanents already on the battlefield."""
    made = _G3Game(players=[
        _G3PlayerState(name="P0", battlefield=list(seat0)),
        _G3PlayerState(name="P1", battlefield=list(seat1)),
    ])
    made.enforce_mana_costs = False
    made.interactive_seats = set()
    return made


def test_inviolability_shields_its_host_from_damage_of_every_kind(set_pool):
    """"Prevent all damage that would be dealt to enchanted creature."

    The Aura form of CR 615.1's shield **without** the word "combat" —
    Prismatic Ward's subject and Gaseous Form's direction, one word narrower
    than either. Both widths are asserted because the word is payload: a reader
    that kept the old "combat damage" anchoring would prevent the attack and let
    a burn spell through, and the card reads identically either way.
    """
    host = _G3Permanent(card=_g3_creature("Host"))
    aura = _G3Permanent(card=set_pool("MMQ")["Inviolability"])
    bystander = _G3Permanent(card=_g3_creature("Bystander"))
    victim = _G3Permanent(card=_g3_creature("Victim", 5, 5))
    game = _g3_board((host, aura, bystander), (victim,))
    _g3_attach(aura, host)

    assert _g3_dealt(game, host, 3, source=victim, combat=True) == 0
    assert _g3_dealt(game, host, 3, source=victim) == 0, "not just combat damage"
    assert _g3_dealt(game, bystander, 3, source=victim) == 3, "only the host"
    assert _g3_dealt(game, aura, 3, source=victim) == 3, (
        "an Aura is a permanent too, and this one does not enchant itself"
    )
    assert _g3_dealt(game, victim, 3, source=host, combat=True) == 3, (
        "'dealt to' is one end of the event; the host still hits back"
    )


def test_muzzle_silences_its_host_without_protecting_it(set_pool):
    """"Prevent all damage that would be dealt **by** enchanted creature."

    The other direction, and the pair is what makes the direction load-bearing:
    a reader folding the two together would make either card's creature both
    unkillable and harmless.
    """
    host = _G3Permanent(card=_g3_creature("Muzzled", 4, 4))
    aura = _G3Permanent(card=set_pool("MMQ")["Muzzle"])
    victim = _G3Permanent(card=_g3_creature("Victim", 5, 5))
    game = _g3_board((host, aura), (victim,))
    _g3_attach(aura, host)

    assert _g3_dealt(game, victim, 4, source=host, combat=True) == 0
    assert _g3_dealt(game, victim, 4, source=host) == 0, "an ability's damage too"
    assert _g3_dealt(game, game.players[1], 4, source=host, combat=True) == 0, (
        "a player is a recipient like any other (CR 615.1)"
    )
    assert _g3_dealt(game, host, 4, source=victim, combat=True) == 4, (
        "the muzzled creature is still perfectly able to be dealt damage"
    )


def test_the_printed_combat_word_still_narrows_the_attached_shield(
    catalog_by_name,
):
    """Demonic Torment against Muzzle: one printed word apart, and it is read.

    The regression this pins is the direction the widening could have gone
    wrong in — dropping the word rather than carrying it would have made
    Demonic Torment stop the enchanted creature's ping abilities as well, which
    no reader outside a game can see.
    """
    host = _G3Permanent(card=_g3_creature("Tormented", 4, 4))
    aura = _G3Permanent(card=catalog_by_name["Demonic Torment"])
    victim = _G3Permanent(card=_g3_creature("Victim", 5, 5))
    game = _g3_board((host, aura), (victim,))
    _g3_attach(aura, host)

    assert _g3_dealt(game, victim, 4, source=host, combat=True) == 0
    assert _g3_dealt(game, victim, 4, source=host) == 4, "combat damage only"


def test_both_halves_apply_when_both_auras_are_attached(set_pool):
    """Inviolability *and* Muzzle on one creature.

    Every static shield the pool had before this set was already two-way (Fog
    Bank, Gaseous Form), so the reader could stop at the first line it found
    and never be wrong. Mercadian Masques prints the two halves as separate
    Auras, and a creature carrying both is an ordinary board on which
    first-match silently drops one of them.
    """
    host = _G3Permanent(card=_g3_creature("Wrapped", 4, 4))
    to_shield = _G3Permanent(card=set_pool("MMQ")["Inviolability"])
    by_shield = _G3Permanent(card=set_pool("MMQ")["Muzzle"])
    victim = _G3Permanent(card=_g3_creature("Victim", 5, 5))
    game = _g3_board((host, to_shield, by_shield), (victim,))
    _g3_attach(to_shield, host)
    _g3_attach(by_shield, host)

    assert _g3_dealt(game, host, 4, source=victim) == 0, "Inviolability's half"
    assert _g3_dealt(game, victim, 4, source=host) == 0, "Muzzle's half"


def test_statecraft_covers_both_ends_of_a_combat_damage_event(set_pool):
    """"Prevent all combat damage that would be dealt to and dealt by creatures
    you control."

    Two shields in one printed sentence over a set the sentence describes rather
    than fixes, so both ends are asserted and so is each narrowing the sentence
    carries: the printed "combat", and the printed "you control". The source
    half is the one a *player* can be on the other end of, which is why an event
    with a `PlayerState` recipient is checked here.
    """
    enchantment = _G3Permanent(card=set_pool("MMQ")["Statecraft"])
    mine = _G3Permanent(card=_g3_creature("Mine", 3, 3))
    theirs = _G3Permanent(card=_g3_creature("Theirs", 3, 3))
    game = _g3_board((enchantment, mine), (theirs,))

    assert _g3_dealt(game, mine, 3, source=theirs, combat=True) == 0, "dealt to"
    assert _g3_dealt(game, theirs, 3, source=mine, combat=True) == 0, "dealt by"
    assert _g3_dealt(game, game.players[1], 3, source=mine, combat=True) == 0, (
        "the source half covers an event headed for a player"
    )
    assert _g3_dealt(game, mine, 3, source=theirs) == 3, "the printed 'combat'"
    assert _g3_dealt(game, theirs, 3, source=mine) == 3, "in both directions"
    assert _g3_dealt(game, game.players[0], 3, source=theirs, combat=True) == 3, (
        "the printed 'you control': their creature's damage is untouched"
    )


def test_statecraft_reads_the_board_at_the_damage_event(set_pool):
    """The set is re-matched when the damage would be dealt, not when the
    enchantment entered (CR 611.2c fixes a set only where the effect says so,
    and "creatures you control" does not).

    A creature that changed hands is the case that separates the two readings,
    and the board looks identical either way.
    """
    from engine.control import change_control

    enchantment = _G3Permanent(card=set_pool("MMQ")["Statecraft"])
    borrowed = _G3Permanent(card=_g3_creature("Borrowed", 3, 3))
    attacker = _G3Permanent(card=_g3_creature("Attacker", 3, 3))
    game = _g3_board((enchantment,), (borrowed, attacker))

    assert _g3_dealt(game, borrowed, 3, source=attacker, combat=True) == 3, (
        "no creature of the enchantment's controller is in the event"
    )

    change_control(borrowed, 0, source=enchantment)
    game._sync_control()

    assert _g3_dealt(game, borrowed, 3, source=attacker, combat=True) == 0
# --- end W1G3 ---


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
