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


# --- W1G4: counters, computed characteristics and the Licids ----------------

from engine import Game as _G4Game, PlayerState as _G4Player
from engine.models import Permanent as _G4Perm
from engine.named_counters import counters_on as _g4_counters_on
from engine.named_counters import remove_counters as _g4_remove_counters
from engine.oracle import compile_card_oracle as _g4_compile

from tests.helpers import resolve_stack as _g4_resolve


def _g4_perm(card, *, tapped=False):
    """A permanent already on the battlefield, past its summoning sickness."""
    permanent = _G4Perm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    return permanent


def _g4_duel(mine=(), theirs=(), hand=(), pool=None):
    """A two-seat board with P0 to act, costs off, layers already computed."""
    p0 = _G4Player(name="G4-P0", battlefield=list(mine), life=20,
                   hand=list(hand), mana_pool=dict(pool or {}))
    p1 = _G4Player(name="G4-P1", battlefield=list(theirs), life=20)
    game = _G4Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.priority_player_index = 0
    game._sync_control()
    game._refresh_dynamic_creatures()
    # A closing line no other group's helper writes, so a mechanical union
    # cannot splice this body onto another signature (W1G4).
    return game, p0, p1


def test_w1g4_spike_cannibal_eats_every_creatures_plus_one_counters(set_pool):
    """"When this creature enters, move all +1/+1 counters from all creatures
    onto it."

    The counter move read from the far end: the *destination* is the ability's
    own source and the sources are a described set. CR 122.5 makes it one
    action, which is why it is one instruction rather than a counter sweep
    composed with a placement -- the number placed is exactly the number the
    board gave up, and an empty board places nothing.

    Every creature, not only the caster's: the printed phrase names no
    controller, so an opponent's counters travel too.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    mine, theirs = _g4_perm(lea["Grizzly Bears"]), _g4_perm(lea["Grizzly Bears"])
    game, _p0, _p1 = _g4_duel(mine=[mine], theirs=[theirs],
                              hand=[exo["Spike Cannibal"]])
    game.place_pt_counters(mine, "+1/+1", 2)
    game.place_pt_counters(theirs, "+1/+1", 3)
    game._refresh_dynamic_creatures()

    assert game.cast_from_hand(0, "Spike Cannibal").supported
    _g4_resolve(game)
    game.check_state_based_actions()

    cannibal = next(p for p in game.controlled_by(0)
                    if p.card.name == "Spike Cannibal")
    # One counter from its own entry line plus the five it took.
    assert _g4_counters_on(cannibal, "+1/+1") == 6
    assert (cannibal.effective_power, cannibal.effective_toughness) == (6, 6)
    assert _g4_counters_on(mine, "+1/+1") == 0
    assert _g4_counters_on(theirs, "+1/+1") == 0


def test_w1g4_spike_cannibal_on_an_empty_board_keeps_its_own_counter(set_pool):
    """A permanent is skipped as a source of its own move (CR 122.5 -- moving a
    counter onto the object it came off does nothing).

    Taking the Spike's entry counter off and putting the same number back would
    read the same on the board and would write the "a counter was removed"
    record along the way, which nothing about this card asks for.
    """
    exo = set_pool("EXO")
    game, _p0, _p1 = _g4_duel(hand=[exo["Spike Cannibal"]])

    assert game.cast_from_hand(0, "Spike Cannibal").supported
    _g4_resolve(game)
    game.check_state_based_actions()

    cannibal = next(p for p in game.controlled_by(0)
                    if p.card.name == "Spike Cannibal")
    assert _g4_counters_on(cannibal, "+1/+1") == 1
    assert any("no +1/+1 counters to move" in line for line in game.log)


def test_w1g4_spike_rogue_pays_a_counter_off_another_creature(set_pool):
    """"{2}, Remove a +1/+1 counter from **a creature you control**: Put a
    +1/+1 counter on this creature."

    The counter-removal cost aimed somewhere other than the source -- the
    mirror of Wandering Mage's placing cost, on the same `cost_permanent_ids`
    channel. The named creature pays; the Spike grows.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    bear = _g4_perm(lea["Grizzly Bears"])
    game, _p0, _p1 = _g4_duel(mine=[bear], hand=[exo["Spike Rogue"]],
                              pool={"generic": 9, "G": 4})
    game.place_pt_counters(bear, "+1/+1", 2)
    game._refresh_dynamic_creatures()
    assert game.cast_from_hand(0, "Spike Rogue").supported
    _g4_resolve(game)
    game.check_state_based_actions()
    rogue = next(p for p in game.controlled_by(0) if p.card.name == "Spike Rogue")
    assert _g4_counters_on(rogue, "+1/+1") == 2

    result = game.activate_permanent_ability(
        0, "Spike Rogue", ability_index=1,
        cost_permanent_ids=[bear.permanent_id],
    )
    assert result.supported, result.details
    _g4_resolve(game)

    assert _g4_counters_on(bear, "+1/+1") == 1
    assert _g4_counters_on(rogue, "+1/+1") == 3


def test_w1g4_spike_rogue_refuses_when_nothing_holds_a_counter(set_pool):
    """CR 601.2h: an activation whose cost cannot be paid is no activation.

    The candidate list is not "a creature you control" but "a creature you
    control **with a +1/+1 counter on it**" -- a list that ignored the counters
    would take the mana and then find nothing to remove.
    """
    exo = set_pool("EXO")
    game, _p0, _p1 = _g4_duel(hand=[exo["Spike Rogue"]],
                              pool={"generic": 9, "G": 4})
    assert game.cast_from_hand(0, "Spike Rogue").supported
    _g4_resolve(game)
    game.check_state_based_actions()
    rogue = next(p for p in game.controlled_by(0) if p.card.name == "Spike Rogue")
    _g4_remove_counters(rogue, "+1/+1", _g4_counters_on(rogue, "+1/+1"))
    game._refresh_dynamic_creatures()

    result = game.activate_permanent_ability(0, "Spike Rogue", ability_index=1)

    assert not result.supported
    assert "+1/+1 counter to remove" in result.details


def test_w1g4_spike_rogues_own_counter_cost_stays_a_self_cost(set_pool):
    """The first ability still reads its own source.

    The chosen-subject reading is tried **before** the plain one in
    ``engine/oracle.py``, because the plain regex's "from " matches anything at
    all. This is the other side of that order: "from this creature" opens with
    no article, so the chosen reader cannot claim it and Scavenging Ghoul's
    shape is untouched.
    """
    rogue = set_pool("EXO")["Spike Rogue"]
    program = _g4_compile(rogue)

    self_cost, chosen_cost = (a.cost for a in program.activated_abilities)
    assert self_cost.remove_counter == "+1/+1"
    assert self_cost.remove_counter_filter is None
    assert chosen_cost.remove_counter_filter == {"type_filter": "creature"}


def test_w1g4_skyshroud_war_beast_counts_the_chosen_players_nonbasics(set_pool):
    """"...power and toughness are each equal to the number of **nonbasic**
    lands the chosen player controls." (CR 604.3.)

    Pallimud's row with a fifth capture: a supertype the counted object must
    *not* have (CR 205.4a). Asked through ``has_supertype``, so it is CR 613
    layer 4 rather than the printed line -- a land made basic stops counting.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    theirs = [_g4_perm(lea["Badlands"]), _g4_perm(lea["Tundra"]),
              _g4_perm(lea["Forest"])]
    game, _p0, _p1 = _g4_duel(theirs=theirs, hand=[exo["Skyshroud War Beast"]])

    assert game.cast_from_hand(
        0, "Skyshroud War Beast", target_player_index=1
    ).supported
    _g4_resolve(game)
    game.check_state_based_actions()

    beast = next(p for p in game.controlled_by(0)
                 if p.card.name == "Skyshroud War Beast")
    assert beast.metadata.get("chosen_player_index") == 1
    # Two nonbasics; the Forest is a basic land and is not counted.
    assert (beast.effective_power, beast.effective_toughness) == (2, 2)


# --- W1G4 (cont.): the two Exodus Licids ------------------------------------

from engine.auras import attach_aura as _g4_attach
from engine.special_actions import (
    take_permanent_special_action as _g4_special_action,
)


def _g4_licid_attached(set_pool, name, pool):
    """*name* activated onto an opponent's Grizzly Bears, stack drained."""
    exo, lea = set_pool("EXO"), set_pool("LEA")
    licid, bear = _g4_perm(exo[name]), _g4_perm(lea["Grizzly Bears"])
    game, p0, p1 = _g4_duel(mine=[licid], theirs=[bear], pool=pool)
    game.activate_permanent_ability(
        0, name, ability_index=0,
        target_permanent_index=0, target_player_index=1,
    )
    _g4_resolve(game)
    game.check_state_based_actions()
    game.priority_player_index = 0
    return game, licid, bear, p0, p1


def test_w1g4_dominating_licid_takes_control_of_what_it_enchants(set_pool):
    """"You control enchanted creature."

    CR 613 layer 2 derived from the **attachment** rather than performed when
    an Aura spell resolves — which is what a Licid forces: it becomes an Aura
    through an activated ability and attaches through
    ``attach_source_to_target``, so no Aura spell ever resolves and the
    resolution-time reading reached it not at all.
    """
    game, licid, bear, _p0, _p1 = _g4_licid_attached(
        set_pool, "Dominating Licid", {"U": 6, "generic": 6}
    )

    assert licid.metadata.get("attached_to") is bear
    assert not licid.is_creature and licid.has_type("aura")
    assert game.controller_index_of(bear) == 0


def test_w1g4_dominating_licid_gives_the_creature_back_when_it_stops(set_pool):
    """"You may pay {U} to end this effect." (CR 116.2d's special action.)

    The other half of a derived contribution: the sweep records it while the
    attachment holds and drops it the moment it does not, so the creature goes
    home with nothing to undo and no detach site to keep in step.
    """
    game, licid, bear, _p0, _p1 = _g4_licid_attached(
        set_pool, "Dominating Licid", {"U": 6, "generic": 6}
    )
    assert game.controller_index_of(bear) == 0

    assert _g4_special_action(game, 0, licid, "end_own_continuous_effect") is None
    game.check_state_based_actions()

    assert game.controller_index_of(bear) == 1
    assert licid.is_creature


def test_w1g4_transmogrifying_licid_adds_a_card_type_to_its_host(set_pool):
    """"Enchanted creature gets +1/+1 and is an **artifact** in addition to its
    other types."

    Dub's rider one level up CR 205's hierarchy: a card type (CR 205.2) rather
    than a creature subtype (CR 205.3), which is why it is a separate reader —
    handing "artifact" to the subtype field would make the permanent an
    artifact *subtype* nothing on any board is.

    Both halves, in their own layers: the P/T at 7c (read by the unanchored
    ``_STATIC_PT_GRANT`` search, untouched) and the type at 4.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    licid, bear = _g4_perm(exo["Transmogrifying Licid"]), _g4_perm(lea["Grizzly Bears"])
    game, _p0, _p1 = _g4_duel(mine=[licid, bear], pool={"generic": 6})
    assert not bear.has_type("artifact")

    game.activate_permanent_ability(
        0, "Transmogrifying Licid", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    _g4_resolve(game)
    game.check_state_based_actions()

    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    assert bear.has_type("artifact")
    assert bear.is_creature, "in addition to its other types, never replacing"

    game.priority_player_index = 0
    assert _g4_special_action(game, 0, licid, "end_own_continuous_effect") is None
    game.check_state_based_actions()
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert not bear.has_type("artifact")


def test_w1g4_a_control_aura_that_changes_hands_takes_the_creature_with_it(set_pool):
    """CR 109.5: the ability's controller is the **attachment's** controller.

    The derived sweep re-reads it on every pass, so a Control Magic somebody
    steals hands the creature to the thief as well. The resolution-time reading
    this replaced froze the seat that cast the Aura and could not.
    """
    lea = set_pool("LEA")
    magic, bear = _g4_perm(lea["Control Magic"]), _g4_perm(lea["Grizzly Bears"])
    game, _p0, _p1 = _g4_duel(mine=[magic], theirs=[bear])
    _g4_attach(magic, bear)
    game.check_state_based_actions()
    assert game.controller_index_of(bear) == 0

    thief = _g4_perm(lea["Grizzly Bears"])
    game.players[1].battlefield.append(thief)
    game._sync_control()
    game.take_control(magic, 1, source=thief)
    game.check_state_based_actions()

    assert game.controller_index_of(bear) == 1


# --- W2G3: what a step records, and the rate the sentence behind it spends ---
from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _g3w2_seats():
    """Two seats with costs off, seat 0 active.

    Its own ending — three names in the returned tuple — so a mechanical union
    cannot splice this body onto another group's helper signature.
    """
    game = Game(players=[PlayerState(name="Kaya"), PlayerState(name="Oleg")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def _g3w2_enter(game, seat, card, hand=()):
    """Put *card* onto *seat*'s battlefield and fire its enters trigger."""
    game.players[seat].hand = list(hand)
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    game._apply_self_enters_battlefield_triggers(seat, perm, None, None)
    game._settle()
    return perm


def _g3w2_owed_discard(game):
    """The discard prompt this resolution armed, or None if it armed none."""
    owed = [choice for choice in game.pending_choices if choice.kind == "discard"]
    return owed[0] if owed else None


def test_mind_maggots_pays_two_counters_for_every_card_discarded(set_pool):
    """"Discard any number of creature cards. For each card discarded this way,
    put two +1/+1 counters on this creature."

    The rate is the point: one discard buys two counters, so a lowering that
    dropped the printed "two" would place half what the card says, and one that
    dropped the *record* would place none at all. Two discards, four counters,
    a 2/2 becoming a 6/6.
    """
    pool = set_pool("EXO")
    game, kaya, _oleg = _g3w2_seats()
    game.interactive_seats = {0}
    hand = [pool["Standing Troops"], pool["Rabid Wolverines"], pool["City of Traitors"]]
    maggots = _g3w2_enter(game, 0, pool["Mind Maggots"], hand)

    assert game.confirm_discard(0, [0, 1])
    game._settle()

    assert len(kaya.graveyard) == 2
    assert maggots.effective_power == 6
    assert maggots.effective_toughness == 6


def test_mind_maggots_offers_a_ceiling_rather_than_demanding_a_count(set_pool):
    """"**Any number**" includes none, so the prompt is a ceiling and answering
    it with nothing is a legal answer.

    Read as an amount instead, the trigger would force the whole hand out — a
    cost strictly larger than the card asks for, in the silent direction.
    """
    pool = set_pool("EXO")
    game, kaya, _oleg = _g3w2_seats()
    game.interactive_seats = {0}
    hand = [pool["Standing Troops"], pool["Rabid Wolverines"]]
    maggots = _g3w2_enter(game, 0, pool["Mind Maggots"], hand)

    owed = _g3w2_owed_discard(game)
    assert owed is not None and owed.data.get("up_to") is True
    assert owed.data["count"] == 2, "the ceiling is what the phrase names"

    assert game.confirm_discard(0, [])
    game._settle()

    assert len(kaya.hand) == 2
    assert maggots.effective_power == 2, "declining places no counters"


def test_mind_maggots_only_offers_the_creature_cards_the_phrase_names(set_pool):
    """"Any number of **creature** cards": the ceiling is bounded by what the
    printed noun phrase admits, not by the size of the hand. A dropped narrowing
    would let the trigger pitch a land for counters.
    """
    pool = set_pool("EXO")
    game, _kaya, _oleg = _g3w2_seats()
    game.interactive_seats = {0}
    hand = [pool["Standing Troops"], pool["Rabid Wolverines"], pool["City of Traitors"]]
    _g3w2_enter(game, 0, pool["Mind Maggots"], hand)

    owed = _g3w2_owed_discard(game)
    assert owed is not None and owed.data["count"] == 2, "the land is no candidate"
    assert owed.data["filter"] == {"type_filter": "creature"}


def test_mind_maggots_with_no_creature_card_arms_no_prompt(set_pool):
    """An empty candidate list is answered by not asking. A prompt armed over
    nothing would hold the trigger on the stack with no legal answer to it."""
    pool = set_pool("EXO")
    game, _kaya, _oleg = _g3w2_seats()
    game.interactive_seats = {0}
    maggots = _g3w2_enter(
        game, 0, pool["Mind Maggots"], [pool["City of Traitors"]]
    )

    assert _g3w2_owed_discard(game) is None
    assert maggots.effective_power == 2


def test_a_recorded_count_names_the_record_it_reads():
    """The latent defect this round found in shipped code, as a probe.

    Every ``ThatMuch`` reaching the counter placement left as ``trigger_count``
    whatever record the words named — a key no discard writes — so the trailing
    spelling would have placed **zero** counters while compiling clean. Only
    Tetravus reached the branch and its record really is that key, which is what
    kept it latent rather than live. The named record now travels.
    """
    trailing = compile_line(
        "discard a creature card. Put a +1/+1 counter on this creature "
        "for each card discarded this way"
    )
    assert trailing.lowering_error is None
    placed = trailing.instructions[-1]
    assert placed.payload["x_from_count"] == {"back_reference": "discarded_count"}


def test_a_bare_that_many_keeps_the_key_its_own_producer_writes():
    """Tetravus' "put **that many** +1/+1 counters on this creature" names no
    record at all, so it keeps ``trigger_count`` — the key its exile step really
    writes. Routing it through the named channel would have refused a shipped
    card for want of a producer nothing declares."""
    tetravus = compile_line(
        "you may exile any number of tokens created with this creature. "
        "If you do, put that many +1/+1 counters on this creature"
    )
    assert tetravus.lowering_error is None
    assert "trigger_count" in repr(tetravus.instructions)


def test_a_rate_with_no_earlier_step_refuses_by_name():
    """"For each card discarded this way" with nothing in front of it names no
    record. ``count_from_payload`` would answer 0, which is a card that reports
    supported and places no counters — so it refuses instead, naming the key it
    could not find."""
    orphan = compile_line(
        "For each card discarded this way, put two +1/+1 counters on this creature"
    )
    assert orphan.parse_error is None, "the clause parses; the record is what is missing"
    assert "no producer in this effect" in (orphan.lowering_error or "")


def test_the_two_printed_word_orders_of_a_rate_agree():
    """Mind Maggots prints the clause in front and Sacred Boon behind it. One
    reader mints the arithmetic for both, so the two spellings cannot come to
    mean two numbers — which is why the fronted form is a production rather than
    a second table."""
    fronted = compile_line(
        "discard a creature card. For each card discarded this way, "
        "put two +1/+1 counters on this creature"
    )
    trailing = compile_line(
        "discard a creature card. Put two +1/+1 counters on this creature "
        "for each card discarded this way"
    )
    assert fronted.lowering_error is None and trailing.lowering_error is None
    assert fronted.instructions[-1].payload == trailing.instructions[-1].payload
    assert fronted.instructions[-1].payload["x_from_count"]["multiplier"] == 2


def test_a_leading_rate_over_an_effect_that_cannot_carry_one_refuses():
    """The refusal that makes the distribution safe. A rate silently dropped is
    a card that does its effect once where it should do it per recorded unit, so
    a statement with nowhere to carry the number raises rather than losing it."""
    nowhere = compile_line(
        "discard a creature card. For each card discarded this way, "
        "destroy target creature"
    )
    assert nowhere.parse_error is not None
    assert "leading rate" in nowhere.parse_error


def test_mind_maggots_reports_supported_with_both_sentences_behind_it(set_pool):
    """A card is supported when *any* of its lines is, so the step list is what
    says the second sentence landed rather than being read and dropped."""
    program = compile_card_oracle(set_pool("EXO")["Mind Maggots"])
    assert program.supported
    steps = program.triggered_abilities[0].instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "discard_controller_cards", "add_counter_to_self",
    ]


def test_kor_chant_lowers_once_the_cast_can_announce_its_source(set_pool):
    """W2G3's decline, closed in W3 — kept here as the record of what it was.

    The sentence parsed all along; what refused was the **announcement**.
    CR 609.7a's chosen source reaches a resolution on
    ``choices["chosen_source"]``, only the activation path wrote that key, and
    this card's two target slots were already spoken for — so lowering it onto
    the "no source recorded, answers to any source" fallback would have moved
    every point of damage dealt all turn.

    The casting path takes the three announcement fields now, so the line
    lowers. The card's own behaviour is tested where its printed type says
    (``tests/sets/test_exo_instants.py``); what this asserts is the shape of the
    lowering: the blanket record carries **no** ``uses``, which is exactly the
    fact that made the fallback unsafe for it and safe for every other printing
    of the phrase.
    """
    program = compile_card_oracle(set_pool("EXO")["Kor Chant"])
    assert program.supported

    line = compile_line(
        "All damage that would be dealt this turn to target creature you "
        "control by a source of your choice is dealt to another target "
        "creature instead"
    )
    assert line.parse_error is None
    assert line.lowering_error is None
    instruction, = line.instructions
    assert (
        instruction.kind
        == "redirect_chosen_source_damage_between_targets_until_eot"
    )
    assert "uses" not in instruction.payload

    # …and the same sentence printed as "the next time" would be bounded, which
    # is the branch that keeps the blanket reading from being an assumption.
    bounded = compile_line(
        "The next time a source of your choice would deal damage to target "
        "creature you control this turn, that damage is dealt to another "
        "target creature instead"
    )
    assert bounded.parse_error is None and bounded.lowering_error is None
    assert bounded.instructions[0].payload.get("uses") == 1


# --- W2G5: a comparison that stops holding while the ability is on the stack ---
#
# "…who has more life than you do **as you activate this ability**" is a
# restriction on which seats may be chosen (CR 601.2c), and the picker enforces
# it. CR 608.2b asks the same question again as the object resolves, and until
# now nothing did — so a Keeper activated against a player who was ahead paid
# out anyway once that player fell behind in response. The ability is not a
# spell, so the engine's general 608.2b gate deliberately does not reach it;
# `legality.stale_comparison_refusal` covers exactly this printed clause and
# says so.

from engine import Game as _G5Game, PlayerState as _G5PlayerState
from engine.models import CardDefinition as _G5Card, Permanent as _G5Permanent
from tests.helpers import resolve_stack as _g5_resolve_stack


def _g5_body(name, colors=()):
    return _G5Card(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Bear",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear", "power": "1",
             "toughness": "1", "colors": list(colors)},
    )


def _g5_keeper_on_the_stack(set_pool, keeper, *, lives=(20, 25), theirs=(),
                            my_gy=(), their_gy=(), hands=((), ())):
    """Activate *keeper* at seat 1 and leave the ability **on the stack**.

    ``queue_permanent_ability`` rather than ``activate_permanent_ability``:
    the latter settles the stack before returning, which is a game in which
    nothing can ever happen in response — and "in response" is the whole
    question here.
    """
    subject = _G5Permanent(card=set_pool("EXO")[keeper])
    subject.metadata["summoning_sickness_turn"] = -99
    players = [
        _G5PlayerState(
            name="P0", life=lives[0], battlefield=[subject],
            graveyard=list(my_gy), hand=list(hands[0]),
            library=[_g5_body("Mine %d" % i) for i in range(5)],
        ),
        _G5PlayerState(
            name="P1", life=lives[1],
            battlefield=[_G5Permanent(card=c) for c in theirs],
            graveyard=list(their_gy), hand=list(hands[1]),
            library=[_g5_body("Theirs %d" % i) for i in range(5)],
        ),
    ]
    game = _G5Game(players=players)
    game.enforce_mana_costs = False
    game._settle()
    game.start_turn(0)
    queued = game.queue_permanent_ability(
        0, keeper, permanent_index=0, target_player_index=1,
    )
    assert queued.supported, queued.details
    assert len(game.stack) == 1, game.log
    return game, players[0], players[1]


def test_w2g5_keeper_of_the_light_is_countered_when_the_lead_disappears(set_pool):
    """CR 608.2b: an object whose every target has become illegal does not
    resolve. The opponent was ahead when the ability was activated and is not
    when it would resolve, so there is no legal target left and no life is
    gained — where before the check the 3 life arrived regardless.
    """
    game, seat0, seat1 = _g5_keeper_on_the_stack(
        set_pool, "Keeper of the Light", lives=(20, 25),
    )

    seat1.life = 15
    _g5_resolve_stack(game)

    assert seat0.life == 20, "the ability was countered, so nothing was gained"
    assert game.stack == []
    assert any("608.2b" in line for line in game.log), game.log


def test_w2g5_keeper_of_the_light_still_pays_out_when_the_lead_holds(set_pool):
    """The other direction, because a gate that refuses everything also passes
    the test above. The lead narrows and still holds, so the ability resolves.
    """
    game, seat0, seat1 = _g5_keeper_on_the_stack(
        set_pool, "Keeper of the Light", lives=(20, 25),
    )

    seat1.life = 21
    _g5_resolve_stack(game)

    assert seat0.life == 23
    assert not any("608.2b" in line for line in game.log), game.log


def test_w2g5_keeper_of_the_mind_is_countered_when_the_hands_even_up(set_pool):
    """The same clause counted off a hand instead of a life total, so the
    re-check is reading the printed noun phrase rather than one hard-wired
    quantity: "at least two more cards in hand than you do", margin two.
    """
    game, seat0, seat1 = _g5_keeper_on_the_stack(
        set_pool, "Keeper of the Mind",
        hands=((), [_g5_body("Theirs %d" % i) for i in range(3)]),
    )
    before = len(seat0.hand)

    del seat1.hand[1:]
    _g5_resolve_stack(game)

    assert len(seat0.hand) == before, "no card was drawn"
    assert any("608.2b" in line for line in game.log), game.log


def test_w2g5_keeper_of_the_dead_prints_two_targets_and_is_left_alone(set_pool):
    """CR 608.2b is **all-or-nothing**, and this is the card that bounds the
    gate: "Choose target opponent … Destroy target nonblack creature that
    player controls" prints the word twice, so one target going illegal is not
    every target going illegal and the ability still resolves.

    The creature is destroyed and the ability is not countered. That is the
    honest answer for a gate that only claims the one-target case — and it is
    also why the gate counts the printed quantifiers rather than assuming the
    seat is the whole announcement.
    """
    game, _seat0, seat1 = _g5_keeper_on_the_stack(
        set_pool, "Keeper of the Dead",
        theirs=(_g5_body("Victim"),),
        my_gy=[_g5_body("Dead %d" % i) for i in range(3)],
    )

    # In response the opponent's graveyard fills and the margin is gone.
    seat1.graveyard.extend(_g5_body("Theirs %d" % i) for i in range(3))
    _g5_resolve_stack(game)

    assert [p.card.name for p in seat1.battlefield] == []
    assert not any("608.2b" in line for line in game.log), game.log


def _g5_keeper_of_the_dead_table(set_pool, boards, my_gy):
    """Keeper of the Dead on seat 0 at a table of ``len(boards)`` seats.

    Not the two-seat helper above: the question here is *which opponent* the
    picker offers, and at two seats there is only ever one answer.
    """
    keeper = _G5Permanent(card=set_pool("EXO")["Keeper of the Dead"])
    keeper.metadata["summoning_sickness_turn"] = -99
    players = []
    for seat, board in enumerate(boards):
        players.append(_G5PlayerState(
            name="P%d" % seat,
            battlefield=([keeper] if seat == 0 else [])
            + [_G5Permanent(card=c) for c in board],
            graveyard=list(my_gy) if seat == 0 else [],
            library=[_g5_body("L%d-%d" % (seat, i)) for i in range(5)],
        ))
    game = _G5Game(players=players)
    game.enforce_mana_costs = False
    game._settle()
    game.start_turn(0)
    return game, keeper


def _g5_offered_seats(game):
    spec = game.activation_target_spec(0, 0, 0)
    return sorted(
        entry["seat"] for entry in spec["valid_targets"]
        if entry.get("kind") == "player"
    )


def test_w2g5_keeper_of_the_dead_needs_the_second_slot_fillable_too(set_pool):
    """CR 602.2b/601.2c: **every** target is chosen as the ability is
    activated, so an opponent with no nonblack creature is not a legal
    announcement — and the cost is never paid.

    Before this the derivation answered with the first description it found,
    the second slot was narrowed by nothing, and the ability tapped the Keeper
    to resolve into "no valid target permanent found".
    """
    game, keeper = _g5_keeper_of_the_dead_table(
        set_pool, [[], []], [_g5_body("Dead %d" % i) for i in range(3)],
    )

    result = game.queue_permanent_ability(
        0, "Keeper of the Dead", permanent_index=0, target_player_index=1,
    )

    assert not result.supported
    assert not keeper.tapped, "refused before any cost was paid"
    assert game.stack == []


def test_w2g5_keeper_of_the_dead_reads_the_printed_colour_on_that_slot(set_pool):
    """"…target **nonblack** creature that player controls". The slot is
    enumerated with its own filter, so an opponent whose only creature is black
    cannot be named either — a check that asked "any creature?" would pass this
    and the ability would still resolve into nothing.
    """
    game, keeper = _g5_keeper_of_the_dead_table(
        set_pool, [[], [_g5_body("Blacky", ["B"])]],
        [_g5_body("Dead %d" % i) for i in range(3)],
    )

    result = game.queue_permanent_ability(
        0, "Keeper of the Dead", permanent_index=0, target_player_index=1,
    )

    assert not result.supported
    assert not keeper.tapped


def test_w2g5_the_keeper_picker_offers_exactly_the_seats_the_gate_admits(set_pool):
    """The invariant this narrowing had to be built around, not merely beside:
    ``activation_target_refusal`` is asked over the very list
    ``activation_target_spec`` hands the browser, so a seat one of them accepts
    is a seat the other accepts.

    Three seats and the two failure directions in one board — seat 1 answers
    the graveyard comparison and has nothing that can be destroyed, seat 2
    answers it and does. A narrowing added to the gate alone would leave the
    browser offering P1 and the server refusing the click.
    """
    boards = [[], [], [_g5_body("Reachable", ["W"])]]
    graveyard = [_g5_body("Dead %d" % i) for i in range(3)]
    game, _keeper = _g5_keeper_of_the_dead_table(set_pool, boards, graveyard)

    assert _g5_offered_seats(game) == [2]

    for seat, admitted in ((1, False), (2, True)):
        fresh, _fresh_keeper = _g5_keeper_of_the_dead_table(
            set_pool, [[], [], [_g5_body("Reachable", ["W"])]], graveyard,
        )
        result = fresh.queue_permanent_ability(
            0, "Keeper of the Dead", permanent_index=0, target_player_index=seat,
        )
        assert result.supported is admitted, (seat, result.details)


# --- W2G2: a choice somebody else makes ---

from unittest.mock import patch as _w2g2_patch

import pytest as _w2g2_pytest

from engine import Game as _W2G2Game, PlayerState as _W2G2PlayerState
from engine.grammar import compile_line as _w2g2_compile_line
from engine.models import CardDefinition as _W2G2CardDefinition
from engine.models import Permanent as _W2G2Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile_card
from engine.targeting import derive_activation_spec as _w2g2_activation_spec


def _w2g2_bear(name, power=2, toughness=2):
    return _W2G2CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={}, power=str(power), toughness=str(toughness),
    )


def _w2g2_assassin_board(set_pool, *, opponent_creature=True):
    """Mogg Assassin untapped on seat 0, one creature each side.

    Both seats interactive: the whole ability is two seats making two choices,
    and a headless seat takes the registry default for the second one — which
    would let a test pass without ever proving the opponent was the seat asked.
    """
    p1, p2 = _W2G2PlayerState(name="P1"), _W2G2PlayerState(name="P2")
    game = _W2G2Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    assassin = _W2G2Permanent(card=set_pool("EXO")["Mogg Assassin"])
    game._put_permanent_onto_battlefield(0, assassin, None)
    assassin.metadata["summoning_sickness_turn"] = -99
    mine = _W2G2Permanent(card=_w2g2_bear("Mine"))
    game._put_permanent_onto_battlefield(0, mine, None)
    theirs = None
    if opponent_creature:
        theirs = _W2G2Permanent(card=_w2g2_bear("Theirs", 3, 3))
        game._put_permanent_onto_battlefield(1, theirs, None)
    game.log.clear()
    return game, assassin, mine, theirs


def test_w2g2_mogg_assassin_compiles_to_two_choices_and_two_records(set_pool):
    """The shape, pinned because every part of this card is a payload key.

    Its two picks are made by two seats at two different moments, and this
    engine spells that difference as two instruction kinds: the ability's
    controller announces at activation (CR 602.2b), and any other seat is asked
    at resolution. The destroys behind them read the record each of those steps
    wrote, so a program that lost one key would resolve and destroy nothing.
    """
    program = _w2g2_compile_card(set_pool("EXO")["Mogg Assassin"])
    assert program.supported
    (ability,) = program.activated_abilities
    steps = ability.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_target_permanent", "choose_permanent", "flip_coin",
        "if_then", "if_then",
    ]
    assert steps[0].payload["targets"]["filter"] == {
        "type_filter": "creature", "controller": "opponent",
    }
    assert steps[1].payload["chooser"] == "chosen_player"
    won, lost = steps[3], steps[4]
    assert won.payload["condition"] == {"kind": "coin_flip", "won": True}
    assert lost.payload["condition"] == {"kind": "coin_flip", "won": False}
    assert won.payload["then"][0].payload["permanents_from"] == (
        "chosen_target_permanents"
    )
    assert lost.payload["then"][0].payload["permanents_from"] == "attach_host"


def test_w2g2_mogg_assassin_announces_only_an_opponents_creature(set_pool):
    """"You choose **target creature an opponent controls**" — the picker's
    narrowing, which a resolution-time prompt could not have carried."""
    program = _w2g2_compile_card(set_pool("EXO")["Mogg Assassin"])
    (ability,) = program.activated_abilities
    assert _w2g2_activation_spec(ability) == {
        "kind": "creature", "opponent_only": True,
    }


def test_w2g2_mogg_assassin_refuses_with_the_tap_unpaid(set_pool):
    """CR 602.2b/601.2c: targets are chosen as the ability is activated, so an
    ability with no legal target is never activated at all.

    Mogg Assassin taps as its cost, and this is the whole reason the first
    choice is an announcement rather than a prompt: refused at resolution the
    creature would be tapped for nothing, every turn, for as long as the
    opponent's board is empty.
    """
    game, assassin, _mine, _theirs = _w2g2_assassin_board(
        set_pool, opponent_creature=False
    )

    result = game.activate_permanent_ability(0, "Mogg Assassin")

    assert not result.supported
    assert assassin.tapped is False
    assert not game.pending_choices


def test_w2g2_mogg_assassin_asks_the_opponent_for_the_second_creature(set_pool):
    """"…**and that opponent** chooses target creature."

    "That opponent" is the controller of what the *first* clause announced —
    there is no firing event to have frozen a seat, so the pronoun is answered
    from the record that clause wrote. And the second noun phrase carries no
    controller at all, so every creature on the table is a candidate, the
    Assassin itself included.
    """
    game, assassin, mine, theirs = _w2g2_assassin_board(set_pool)

    game.activate_permanent_ability(
        0, "Mogg Assassin", target_permanent_ids=[theirs.permanent_id]
    )

    (choice,) = [c for c in game.pending_choices if c.kind == "permanent_choice"]
    assert choice.player_index == 1
    assert sorted(p.card.name for p in choice.data["_candidates"]) == [
        "Mine", "Mogg Assassin", "Theirs",
    ]


@_w2g2_pytest.mark.parametrize(
    "roll, destroyed, survivor",
    [
        # The flipper is the ability's controller, so a win destroys what *they*
        # announced and a loss destroys what the opponent chose. Reading the two
        # records the other way round is a card that plays exactly backwards,
        # with nothing to fail.
        (0.0, "Theirs", "Mine"),
        (0.99, "Mine", "Theirs"),
    ],
)
def test_w2g2_mogg_assassin_destroys_the_flip_winners_pick(
    set_pool, roll, destroyed, survivor
):
    """The Rock Hydra test for this card: a game, driven to the end.

    Both choices are made, the coin is rigged, and the board afterwards says
    which record the destroy read. Nothing in this repo can see the alternative
    — the card compiles, claims every sentence, carries no hollow line, and a
    destroy reading an unwritten record simply destroys nothing.
    """
    game, assassin, mine, theirs = _w2g2_assassin_board(set_pool)

    with _w2g2_patch("engine.handlers._common.random.random", return_value=roll):
        game.activate_permanent_ability(
            0, "Mogg Assassin", target_permanent_ids=[theirs.permanent_id]
        )
        answered = game.resolve_pending_choice(
            "permanent_choice", 1, permanent_id=mine.permanent_id
        )
        game._settle()

    assert answered
    alive = {p.card.name for p in game.all_permanents()}
    assert destroyed not in alive
    assert survivor in alive
    assert "Mogg Assassin" in alive


def test_w2g2_a_chosen_back_reference_refuses_with_nothing_recorded():
    """The refusal that keeps "the creature you chose" honest.

    Both phrases are read wherever a bound noun phrase is, so a card printing
    one without an earlier step that chose is refused by name — a destroy
    reading an empty record is a card that compiles, resolves and does nothing,
    which is the one failure no instrument here can see.
    """
    for line in (
        "Destroy the creature you chose.",
        "Destroy the creature your opponent chose.",
    ):
        compiled = _w2g2_compile_line(line)
        assert compiled.parsed, line
        assert compiled.lowering_error is not None, line
        assert "with no producer in this effect" in compiled.lowering_error, line


def test_w2g2_a_bare_definite_noun_phrase_keeps_its_old_reading():
    """The positive control for the parse above.

    "Destroy the creature" is the definite back-reference this engine has always
    read as the ability's own source, and the new clause is read only as a whole
    — so a production that swallowed the article would silently re-point every
    card printing it.
    """
    compiled = _w2g2_compile_line("Destroy the creature.")
    assert compiled.usable
    assert [i.kind for i in compiled.instructions] == ["destroy_self"]
