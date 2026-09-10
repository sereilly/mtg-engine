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


# --- W1G4: upkeep, end-step and enters-the-battlefield triggers ---
#
# Four enchantments, two of them Auras whose trigger names a seat the Aura's
# own controller is not. Both Auras were refused on a back-reference the
# lowering could not resolve rather than on anything the parser could not read.

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from tests.helpers import _nosick, resolve_stack


def _g4e_card(name, type_line, power=None, toughness=None):
    """A filler card; a P/T pair makes it a creature the layers can read."""
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name},
        power=power, toughness=toughness,
    )


def _g4e_duel(set_pool):
    """Two seats with cost enforcement off, and MMQ's pool keyed by name."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, set_pool("MMQ")


def _g4e_drain(game):
    """Resolve the stack and then answer the offers a trigger left behind."""
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()
    return game.log


def test_ley_line_asks_the_seat_whose_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, **that player** may put a
    +1/+1 counter on target creature **of their choice**."

    Both halves name the same seat and neither is the enchantment's controller:
    the offer is made to the seat the upkeep froze, and the pick is armed on
    that same seat.
    """
    game, p1, p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Ley Line"]))
    mine = _nosick(Permanent(card=_g4e_card("Mine", "Creature - Bear", "2", "2")))
    p1.battlefield.append(mine)
    game._sync_control()

    game.active_player_index = 1
    game.resolve_upkeep(1)
    game._settle()
    resolve_stack(game)
    offers = [
        (choice.kind, choice.player_index) for choice in game.pending_choices
    ]
    assert offers == [("optional_pay", 1)]
    game.auto_resolve_pending_choices()
    game._settle()

    assert mine.effective_power == 3


def test_ley_line_places_nothing_on_a_creatureless_board(set_pool):
    """The pick has no candidate, so the offer buys nothing - and the ability
    still resolves rather than raising."""
    game, p1, _p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Ley Line"]))
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4e_drain(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Ley Line"]


def test_insubordination_burns_a_controller_who_stayed_home(set_pool):
    """"At the beginning of the end step of enchanted creature's controller,
    this Aura deals 2 damage to **that player** unless **that creature**
    attacked this turn."

    Two back-references in one sentence, and they name different objects: the
    seat is the one the end step froze, the creature is the Aura's host.
    """
    game, p1, p2, by_name = _g4e_duel(set_pool)
    victim = _nosick(Permanent(card=_g4e_card("Victim", "Creature - Bear", "2", "2")))
    p2.battlefield.append(victim)
    aura = Permanent(card=by_name["Insubordination"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, victim)

    game.active_player_index = 1
    game.resolve_end_step(1)
    _g4e_drain(game)

    assert (p1.life, p2.life) == (20, 18)


def test_insubordination_spares_a_creature_that_attacked(set_pool):
    """The "unless" is an ordinary condition on the effect, not CR 603.4's
    intervening if - so the ability triggers either way and does nothing here.

    Read against the Aura instead of its host the clause would be false on
    every end step (an enchantment never attacks) and the damage would land
    whatever the creature did.
    """
    game, p1, p2, by_name = _g4e_duel(set_pool)
    victim = _nosick(Permanent(card=_g4e_card("Victim", "Creature - Bear", "2", "2")))
    p2.battlefield.append(victim)
    aura = Permanent(card=by_name["Insubordination"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, victim)
    victim.metadata["attacked_this_turn"] = True

    game.active_player_index = 1
    game.resolve_end_step(1)
    _g4e_drain(game)

    assert (p1.life, p2.life) == (20, 20)


def test_insubordination_is_silent_on_its_own_controllers_end_step(set_pool):
    """The condition names the *host's* controller, which is not the seat
    holding the Aura - the card is printed to go on an opponent's creature."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    victim = _nosick(Permanent(card=_g4e_card("Victim", "Creature - Bear", "2", "2")))
    p2.battlefield.append(victim)
    aura = Permanent(card=by_name["Insubordination"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, victim)

    game.active_player_index = 0
    game.resolve_end_step(0)
    _g4e_drain(game)

    assert (p1.life, p2.life) == (20, 20)


def test_unnatural_hunger_deals_the_hosts_power(set_pool):
    """"...deals damage equal to **that creature's power**" - a live read of
    the attached permanent (CR 613 makes power computed), not a number any fire
    site had to freeze."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    host = _nosick(Permanent(card=_g4e_card("Host", "Creature - Bear", "4", "4")))
    p2.battlefield.append(host)
    aura = Permanent(card=by_name["Unnatural Hunger"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, host)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4e_drain(game)

    assert p2.life == 16
    assert [perm.card.name for perm in p2.battlefield] == ["Host"]


def test_unnatural_hungers_another_means_another_than_the_host(set_pool):
    """"...unless they sacrifice **another** creature of their choice." The
    antecedent is the enchanted creature, not the ability's source: an Aura is
    not a creature, so excluding the source rules out nothing and the host
    would be offered as its own way out of the damage."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    host = _nosick(Permanent(card=_g4e_card("Host", "Creature - Bear", "4", "4")))
    p2.battlefield.append(host)
    spare = _nosick(Permanent(card=_g4e_card("Spare", "Creature - Bear", "1", "1")))
    p2.battlefield.append(spare)
    aura = Permanent(card=by_name["Unnatural Hunger"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, host)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4e_drain(game)

    assert p2.life == 20
    assert [perm.card.name for perm in p2.battlefield] == ["Host"]


def test_game_preserve_puts_every_revealed_creature_under_its_owner(set_pool):
    """"...put those cards onto the battlefield **under their owners'
    control**." CR 110.2a: an effect that puts an object onto the battlefield puts
    it under the instructed player's control *unless the effect states
    otherwise*, and this sentence is that statement - which is why the reveal
    records ``{seat: card}`` rather than a flat list."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Game Preserve"]))
    p1.library = [_g4e_card("A1", "Creature - Bear", "2", "2"),
                  _g4e_card("A2", "Creature - Bear", "2", "2")]
    p2.library = [_g4e_card("B1", "Creature - Bear", "2", "2"),
                  _g4e_card("B2", "Creature - Bear", "2", "2")]
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4e_drain(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Game Preserve", "A1"]
    assert [perm.card.name for perm in p2.battlefield] == ["B1"]
    assert [card.name for card in p1.library] == ["A2"]
    assert [card.name for card in p2.library] == ["B2"]


def test_one_noncreature_card_stops_game_preserve_entirely(set_pool):
    """"**all** cards revealed this way" - a universal over every seat's
    reveal, so one land on top of one library keeps everything where it is.
    CR 701.20a moved nothing, so the cards stay on top of their libraries."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Game Preserve"]))
    p1.library = [_g4e_card("A1", "Creature - Bear", "2", "2")]
    p2.library = [_g4e_card("Ritual", "Sorcery")]
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4e_drain(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Game Preserve"]
    assert [card.name for card in p1.library] == ["A1"]
    assert [card.name for card in p2.library] == ["Ritual"]


def test_foster_digs_to_the_first_creature_card(set_pool):
    """"...reveal cards from the top of your library until you reveal a
    creature card. Put that card into your hand and **the rest** into your
    graveyard." A fourth printed spelling of "all other cards revealed this
    way", and the whole of what stood between this card and the production."""
    game, p1, _p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Foster"]))
    victim = _nosick(Permanent(card=_g4e_card("Victim", "Creature - Bear", "2", "2")))
    p1.battlefield.append(victim)
    p1.library = [
        _g4e_card("S3", "Sorcery"),
        _g4e_card("Target", "Creature - Bear", "2", "2"),
        _g4e_card("S2", "Sorcery"),
    ]
    p1.mana_pool["G"] = 3
    game._sync_control()
    game.sacrifice_permanent(victim)
    _g4e_drain(game)

    assert [card.name for card in p1.hand] == ["Target"]
    assert [card.name for card in p1.graveyard] == ["Victim", "S3"]
    assert [card.name for card in p1.library] == ["S2"]
