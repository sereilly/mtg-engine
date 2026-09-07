"""Exodus creatures.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: the Keepers, and a seat picked out by a comparison ---
import pytest

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g1_card(name, type_line="Creature — Bear", colors=()):
    """A creature with no text at all, so a Keeper's own restriction is the
    only thing under test."""
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1",
             "toughness": "1", "colors": list(colors)},
    )


def _g1_board(set_pool, keeper, *, mine=(), theirs=(), my_life=20,
              their_life=20, my_hand=(), their_hand=(), my_gy=(), their_gy=()):
    """*keeper* on seat 0's battlefield, ready to activate, against a seat 1
    the caller has stocked to answer (or fail) its comparison."""
    subject = Permanent(card=set_pool("EXO")[keeper])
    subject.metadata["summoning_sickness_turn"] = -99
    seat0 = PlayerState(
        name="P0", life=my_life,
        battlefield=[subject] + [Permanent(card=c) for c in mine],
        hand=list(my_hand), graveyard=list(my_gy),
        library=[_g1_card("Mine %d" % i) for i in range(5)],
    )
    seat1 = PlayerState(
        name="P1", life=their_life,
        battlefield=[Permanent(card=c) for c in theirs],
        hand=list(their_hand), graveyard=list(their_gy),
        library=[_g1_card("Theirs %d" % i) for i in range(5)],
    )
    game = Game(players=[seat0, seat1])
    game.enforce_mana_costs = False
    game._settle()
    game.start_turn(0)
    return game, seat0, seat1, subject


def _g1_activate(game, keeper):
    return game.activate_permanent_ability(
        0, keeper, permanent_index=0, target_player_index=1,
    )


@pytest.mark.parametrize("keeper", [
    "Keeper of the Beasts", "Keeper of the Dead", "Keeper of the Flame",
    "Keeper of the Light", "Keeper of the Mind",
])
def test_every_keeper_is_supported(set_pool, keeper):
    program = compile_card_oracle(set_pool("EXO")[keeper])
    assert program.supported, program.reason


def test_keeper_of_the_light_gains_life_off_an_opponent_who_is_ahead(set_pool):
    """"{W}, {T}: Choose target opponent who has more life than you do as you
    activate this ability. You gain 3 life."
    """
    game, seat0, _seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Light", my_life=20, their_life=25,
    )

    result = _g1_activate(game, "Keeper of the Light")
    assert result.supported, result.details
    resolve_stack(game)

    assert seat0.life == 23


def test_keeper_of_the_light_is_refused_with_nothing_paid_when_nobody_is_ahead(
    set_pool,
):
    """CR 602.2b/601.2c: an ability with a mandatory target it cannot fill is
    refused **before any cost is paid**, not activated into a no-op. The
    creature staying untapped is the half that would be invisible otherwise —
    an unenforced narrowing costs its controller a tap and gains 3 life anyway.
    """
    game, seat0, _seat1, keeper = _g1_board(
        set_pool, "Keeper of the Light", my_life=20, their_life=15,
    )

    result = _g1_activate(game, "Keeper of the Light")

    assert not result.supported
    assert seat0.life == 20
    assert keeper.tapped is False


def test_keeper_of_the_beasts_reads_the_board_rather_than_a_life_total(set_pool):
    """The comparison is a *counted noun phrase*, so the same clause counts
    creatures here and a life total on Keeper of the Light."""
    game, seat0, _seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Beasts",
        theirs=(_g1_card("Theirs A"), _g1_card("Theirs B")),
    )

    result = _g1_activate(game, "Keeper of the Beasts")
    assert result.supported, result.details
    resolve_stack(game)

    assert [p.card.name for p in seat0.battlefield] == [
        "Keeper of the Beasts", "Beast Token",
    ]


def test_keeper_of_the_beasts_is_refused_on_an_equal_board(set_pool):
    game, seat0, _seat1, _keeper = _g1_board(set_pool, "Keeper of the Beasts")

    result = _g1_activate(game, "Keeper of the Beasts")

    assert not result.supported
    assert len(seat0.battlefield) == 1


def test_keeper_of_the_mind_needs_the_printed_margin_of_two(set_pool):
    """"…who has **at least two** more cards in hand than you do". The
    threshold is data, so one card ahead is not enough and two is.
    """
    one_ahead = _g1_board(
        set_pool, "Keeper of the Mind",
        my_hand=[_g1_card("Mine")],
        their_hand=[_g1_card("A"), _g1_card("B")],
    )
    game, seat0, _seat1, _keeper = one_ahead
    assert not _g1_activate(game, "Keeper of the Mind").supported
    assert len(seat0.hand) == 1

    game, seat0, _seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Mind",
        my_hand=[_g1_card("Mine")],
        their_hand=[_g1_card("A"), _g1_card("B"), _g1_card("C")],
    )
    result = _g1_activate(game, "Keeper of the Mind")
    assert result.supported, result.details
    resolve_stack(game)
    assert len(seat0.hand) == 2


def test_keeper_of_the_flame_burns_the_player_the_activation_chose(set_pool):
    """"…This creature deals 2 damage to **that player**." The seat named by
    the sentence in front of it, which is the one the activation announced."""
    game, seat0, seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Flame", my_life=20, their_life=25,
    )

    result = _g1_activate(game, "Keeper of the Flame")
    assert result.supported, result.details
    resolve_stack(game)

    assert seat1.life == 23
    assert seat0.life == 20


def test_keeper_of_the_dead_destroys_out_of_the_chosen_players_board(set_pool):
    """"Destroy target nonblack creature **that player** controls."

    The seat is the one the *activation* chose, which no trigger context holds
    — so the destroy reads the record the choosing step wrote. Without it the
    sentence found no seat and destroyed nothing while the ability reported
    itself resolved.
    """
    game, seat0, seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Dead",
        mine=(_g1_card("My Own Bear"),),
        theirs=(_g1_card("Blacky", colors=["B"]), _g1_card("Whitey", colors=["W"])),
        my_gy=[_g1_card("Dead %d" % i) for i in range(3)],
    )

    result = _g1_activate(game, "Keeper of the Dead")
    assert result.supported, result.details
    resolve_stack(game)

    assert [p.card.name for p in seat1.battlefield] == ["Blacky"], (
        "the black creature is excluded and the white one is destroyed"
    )
    assert "My Own Bear" in [p.card.name for p in seat0.battlefield], (
        "'that player controls' is the chosen opponent's board, not the "
        "activator's"
    )


def test_keeper_of_the_dead_wants_two_fewer_and_not_merely_fewer(set_pool):
    game, _seat0, seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Dead",
        theirs=(_g1_card("Victim"),),
        my_gy=[_g1_card("Dead %d" % i) for i in range(3)],
        their_gy=[_g1_card("Theirs A"), _g1_card("Theirs B")],
    )

    result = _g1_activate(game, "Keeper of the Dead")

    assert not result.supported
    assert [p.card.name for p in seat1.battlefield] == ["Victim"]


def test_a_comparison_the_evaluator_cannot_count_refuses_the_line():
    """The clause carries a whole noun phrase, and the gate that admits the
    card is the same reader that counts it. A phrase no count can take has to
    refuse the sentence rather than be admitted with the comparison dropped —
    an unenforced seat narrowing is an ability that hits everybody.
    """
    line = compile_line(
        "choose target opponent who controls more creatures blocking it than "
        "you do as you activate this ability. you gain 3 life"
    )
    assert not line.instructions
    assert line.parse_error or line.lowering_error


def test_a_bare_choose_target_opponent_still_needs_its_binder():
    """The comparison is what makes a narrowed choice non-vacuous; without one
    the module's original rule stands, and a sentence that chooses a player and
    never mentions them again is refused."""
    line = compile_line("choose target opponent. you gain 3 life")
    assert not line.instructions


# --- W1G2: upkeep tolls, an intervening-if over a whole board, and a
# reveal-until ---
#
# Three creatures whose ability is a *decision* rather than an effect.
# Carnophage's toll is the printed currency the trailing-toll production could
# not read (life, where every other price was mana or an action); Zealots
# en-Dal's condition is a universal quantification, read as the count it already
# is; and Avenging Druid's offer is the whole reveal-until procedure, so
# accepting it does all of it and declining does none.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_G2C_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g2c_duel():
    """Two seats, costs off, seat 0 active — with an ending of its own so a
    mechanical union cannot splice this body onto another group's signature."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def _g2c_put(game, seat: int, card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def test_w1g2_carnophage_taps_when_the_life_is_not_paid(set_pool):
    """CR 119.4's currency as a toll's price. The consequence is the *decline*
    branch, so refusing has to tap it — an offer whose penalty went unapplied
    would be a Carnophage that untaps for free."""
    game, alice, _bob = _g2c_duel()
    game.interactive_seats = {0}
    carnophage = _g2c_put(game, 0, set_pool("EXO")["Carnophage"])

    game.resolve_upkeep(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Carnophage", accept=False)
    game._settle()

    assert carnophage.tapped
    assert alice.life == 20


def test_w1g2_carnophage_stays_untapped_for_a_life(set_pool):
    """The other branch, and the one that says the price is really charged."""
    game, alice, _bob = _g2c_duel()
    game.interactive_seats = {0}
    carnophage = _g2c_put(game, 0, set_pool("EXO")["Carnophage"])

    game.resolve_upkeep(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Carnophage", accept=True)
    game._settle()

    assert not carnophage.tapped
    assert alice.life == 19


def test_w1g2_zealots_en_dal_gains_life_on_an_all_white_board(set_pool):
    """CR 603.4's intervening-if. "All nonland permanents you control are white"
    holds when the seat controls no non-white one — the land is excluded by the
    printed word, which is why a Plains does not spoil it."""
    game, alice, _bob = _g2c_duel()
    game.interactive_seats = set()
    _g2c_put(game, 0, set_pool("EXO")["Zealots en-Dal"])
    _g2c_put(game, 0, _G2C_LEA["Plains"])

    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)

    assert alice.life == 21


def test_w1g2_zealots_en_dal_is_spoiled_by_one_green_creature(set_pool):
    """The condition is universal, so a single non-white nonland permanent
    falsifies it — and the trigger does not fire at all (CR 603.4)."""
    game, alice, _bob = _g2c_duel()
    game.interactive_seats = set()
    _g2c_put(game, 0, set_pool("EXO")["Zealots en-Dal"])
    _g2c_put(game, 0, _G2C_LEA["Llanowar Elves"])

    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)

    assert alice.life == 20


def test_w1g2_zealots_en_dal_ignores_an_opponents_green_creature(set_pool):
    """"…you control" is the seat clause, and dropping it would make the card
    unplayable against any green deck."""
    game, alice, bob = _g2c_duel()
    game.interactive_seats = set()
    _g2c_put(game, 0, set_pool("EXO")["Zealots en-Dal"])
    _g2c_put(game, 1, _G2C_LEA["Llanowar Elves"])
    assert bob is game.players[1]

    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)

    assert alice.life == 21


def test_w1g2_avenging_druid_ramps_and_bins_what_it_passed(set_pool):
    """The reveal-until run with the *battlefield* as its destination and the
    graveyard as the rest's — both read off the card, because the same sentence
    with "into your hand" is Sacred Guide and a different effect."""
    game, alice, bob = _g2c_duel()
    game.interactive_seats = set()
    druid = _g2c_put(game, 0, set_pool("EXO")["Avenging Druid"])
    alice.library.extend([
        _G2C_LEA["Giant Growth"], _G2C_LEA["Lightning Bolt"],
        _G2C_LEA["Forest"], _G2C_LEA["Mountain"],
    ])

    game._deal_damage_to_player(bob, 2, source=druid)
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert sorted(p.card.name for p in game.controlled_by(alice)) == [
        "Avenging Druid", "Forest",
    ]
    assert [c.name for c in alice.graveyard] == ["Giant Growth", "Lightning Bolt"]
    assert [c.name for c in alice.library] == ["Mountain"]


def test_w1g2_avenging_druid_declined_leaves_the_library_alone(set_pool):
    """"You **may** reveal …" is one offer over the whole procedure, so
    declining reveals nothing — the library is untouched rather than turned
    over and put back."""
    game, alice, bob = _g2c_duel()
    game.interactive_seats = {0}
    druid = _g2c_put(game, 0, set_pool("EXO")["Avenging Druid"])
    alice.library.extend([_G2C_LEA["Giant Growth"], _G2C_LEA["Forest"]])

    game._deal_damage_to_player(bob, 2, source=druid)
    game._settle()
    resolve_stack(game)
    assert game.confirm_optional_pay(0, "Avenging Druid", accept=False)
    game._settle()

    assert [c.name for c in alice.library] == ["Giant Growth", "Forest"]
    assert [p.card.name for p in game.controlled_by(alice)] == ["Avenging Druid"]


# --- W1G3: combat ---

from engine import Game, PlayerState
from engine.combat_permissions import MUST_BLOCK_ATTACKERS_UNTIL_EOT
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g3_creature(name, power, toughness, subtype="Beast", keywords=()):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=f"Creature - {subtype}",
        oracle_text="\n".join(word.capitalize() for word in keywords),
        colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": f"Creature - {subtype}",
             "power": str(power), "toughness": str(toughness)},
    )


def _g3_land(name="Forest"):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Basic Land - Forest",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("G",),
        raw={"name": name, "type_line": "Basic Land - Forest"},
    )


def _g3_ready(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g3_table(mine, theirs) -> Game:
    """A two-seat board with seat 0 active and nobody interactive."""
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _g3_into_declare_attackers(game: Game) -> Game:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def test_reckless_ogre_pumps_only_when_it_is_the_only_attacker(set_pool):
    """CR 506.5: "attacks alone" is a fact about the *declaration*.

    Both halves are the assertion. The narrowing rides the condition's payload,
    so a reading that dropped it would pump on every attack - the trigger firing
    more often than the card prints, which is the silent direction. The solo
    case is what proves the row is not simply refusing.
    """
    ogre = _g3_ready(Permanent(card=set_pool("EXO")["Reckless Ogre"]))
    program = compile_card_oracle(ogre.card)
    assert program.supported, program.reason
    assert program.triggered_abilities[0].condition.payload.get(
        "attacks_alone"
    ) == "", "the narrowing has to reach the dispatcher as payload"

    friend = _g3_ready(Permanent(card=_g3_creature("Straggler", 1, 1)))
    game = _g3_into_declare_attackers(_g3_table([ogre, friend], []))
    assert game.declare_attackers(0, [0, 1])[0]
    resolve_stack(game)
    assert ogre.effective_power == 3, (
        "two attackers were declared, so nothing attacked alone"
    )

    solo_ogre = _g3_ready(Permanent(card=set_pool("EXO")["Reckless Ogre"]))
    solo = _g3_into_declare_attackers(_g3_table([solo_ogre], []))
    assert solo.declare_attackers(0, [0])[0]
    resolve_stack(solo)
    assert solo_ogre.effective_power == 6


def test_cinder_crawler_can_only_pump_while_it_is_blocked(set_pool):
    """CR 602.5's clause, enforced rather than parsed and dropped.

    An unenforced restriction is not a dead ability - it is one that works more
    often than the card allows, so the refusal is the half worth asserting first.
    """
    crawler = _g3_ready(Permanent(card=set_pool("EXO")["Cinder Crawler"]))
    program = compile_card_oracle(crawler.card)
    assert program.supported, program.reason

    blocker = _g3_ready(Permanent(card=_g3_creature("Guard", 2, 2)))
    game = _g3_into_declare_attackers(_g3_table([crawler], [blocker]))
    refused = game.activate_permanent_ability(0, "Cinder Crawler", permanent_index=0)
    assert not refused.supported, refused.details
    assert "blocked" in refused.details, refused.details
    assert crawler.effective_power == 1

    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    allowed = game.activate_permanent_ability(0, "Cinder Crawler", permanent_index=0)
    assert allowed.supported, allowed.details
    resolve_stack(game)
    assert crawler.effective_power == 2


def test_monstrous_hound_counts_both_boards_before_attacking(set_pool):
    """"...unless you control **more lands than** defending player."

    A comparison between two boards, which is what separates it from the
    "controls a Swamp" clause beside it in `engine/combat_restrictions.py`: the
    equal-lands board is the one a dropped comparison would let through.
    """
    hound = _g3_ready(Permanent(card=set_pool("EXO")["Monstrous Hound"]))
    program = compile_card_oracle(hound.card)
    assert program.supported, program.reason

    game = _g3_table([hound, Permanent(card=_g3_land())], [])
    game.start_turn(0)
    assert game.can_attack(hound, 1), "one land against none"

    game.players[1].battlefield.append(Permanent(card=_g3_land()))
    assert not game.can_attack(hound, 1), "equal boards is not *more*"

    game.players[0].battlefield.append(Permanent(card=_g3_land()))
    assert game.can_attack(hound, 1)


def test_monstrous_hound_counts_both_boards_before_blocking(set_pool):
    """The second printed line, at the other step and against the other seat."""
    hound = _g3_ready(Permanent(card=set_pool("EXO")["Monstrous Hound"]))
    raider = _g3_ready(Permanent(card=_g3_creature("Raider", 2, 2)))
    game = _g3_table([raider, Permanent(card=_g3_land())], [hound])
    game.start_turn(0)
    assert not game._can_block_attacker(hound, raider), "no lands against one"

    game.players[1].battlefield.append(Permanent(card=_g3_land()))
    assert not game._can_block_attacker(hound, raider), "equal boards is not *more*"

    game.players[1].battlefield.append(Permanent(card=_g3_land()))
    assert game._can_block_attacker(hound, raider)


def test_pit_spawn_exiles_the_creature_it_damaged(set_pool):
    """"...deals damage to a creature, exile **that creature**."

    A `damage_dealt` event has two objects in it and the sentence names one with
    a bare pronoun. The damager here is the source, so the words can only mean
    the creature it hit - asserted against a creature big enough to survive the
    damage, which is the only board where the exile is observable at all.
    """
    spawn = _g3_ready(Permanent(card=set_pool("EXO")["Pit Spawn"]))
    program = compile_card_oracle(spawn.card)
    assert program.supported, program.reason

    survivor = _g3_ready(Permanent(card=_g3_creature("Bulwark", 0, 20)))
    game = _g3_table([spawn], [survivor])
    game._mark_damage_on_permanent(survivor, 6, source=spawn)
    resolve_stack(game)
    assert [p.card.name for p in game.players[1].battlefield] == []
    assert [c.name for c in game.players[1].exile] == ["Bulwark"]


def test_wall_of_nets_exiles_what_it_blocked_and_gives_it_back(set_pool):
    """Both printed lines, and the link between them (CR 610.3).

    The end-of-combat exile has to resolve while the block still exists: the
    ability determines what it affects when it *resolves* (CR 608.2), and
    CR 511.3 removes creatures from combat only as the step ends. The return is
    the linked twin, so nothing is remembered twice.
    """
    wall = _g3_ready(Permanent(card=set_pool("EXO")["Wall of Nets"]))
    program = compile_card_oracle(wall.card)
    assert program.supported, program.reason

    raider = _g3_ready(Permanent(card=_g3_creature("Raider", 1, 1)))
    bystander = _g3_ready(Permanent(card=_g3_creature("Bystander", 1, 1)))
    game = _g3_into_declare_attackers(_g3_table([raider, bystander], [wall]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    for _ in range(6):
        game.advance_combat_phase()
        resolve_stack(game)
        if game.current_turn_phase != "combat":
            break
    assert [c.name for c in game.players[0].exile] == ["Raider"]
    assert [p.card.name for p in game.players[0].battlefield] == ["Bystander"], (
        "the creature it never blocked is untouched"
    )

    game.remove_from_battlefield(wall)
    resolve_stack(game)
    assert [c.name for c in game.players[0].exile] == []
    assert sorted(p.card.name for p in game.players[0].battlefield) == [
        "Bystander", "Raider",
    ]


def test_crashing_boars_makes_the_defender_pick_its_own_blocker(set_pool):
    """CR 509.1c aimed at one attacker, on a creature nobody targeted.

    Three assertions, because three things could be silently dropped: the
    chooser (the *defending* player, not the boars' controller), the printed
    "untapped" narrowing, and the requirement itself.
    """
    boars = _g3_ready(Permanent(card=set_pool("EXO")["Crashing Boars"]))
    program = compile_card_oracle(boars.card)
    assert program.supported, program.reason

    guard = _g3_ready(Permanent(card=_g3_creature("Guard", 1, 1)))
    sleeper = _g3_ready(Permanent(card=_g3_creature("Sleeper", 1, 1)))
    sleeper.tapped = True
    mine = _g3_ready(Permanent(card=_g3_creature("Ally", 1, 1)))
    game = _g3_into_declare_attackers(_g3_table([boars, mine], [guard, sleeper]))
    assert game.declare_attackers(0, [0])[0]
    resolve_stack(game)

    assert guard.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) == [
        boars.permanent_id
    ]
    assert sleeper.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) is None, (
        "the printed 'untapped' is the whole of what keeps a tapped creature out"
    )
    assert mine.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) is None, (
        "the defending player chooses from their own battlefield"
    )

    game.advance_combat_phase()
    refused, why = game.declare_blockers(1, {})
    assert not refused and "must block" in why, why
    assert game.declare_blockers(1, {0: 0})[0]
