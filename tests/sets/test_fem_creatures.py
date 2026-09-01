"""Per-card tests for Fallen Empires' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations

# --- G4: costs from the board and the graveyard ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g4_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g4_game(battlefield, *, hand=(), their_battlefield=(), enforce=False):
    p1 = PlayerState(name="P1", battlefield=list(battlefield), hand=list(hand))
    p2 = PlayerState(name="P2", battlefield=list(their_battlefield))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = enforce
    game.start_turn(0)
    return game, p1, p2


# Derelor — a cost tax printed as a coloured pip


def test_derelor_taxes_your_black_spells_a_black_pip(set_pool):
    """"Black spells you cast cost {B} more to cast."

    The tax is a **coloured** pip, not a generic one, which is the whole
    difference: {B} may not be paid with a Forest. So a caster holding exactly
    the printed cost cannot cast, and one holding a second black mana can.
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    ritual = lea["Dark Ritual"]

    def cast_with(**mana):
        game, p1, _p2 = _g4_game(
            [Permanent(card=pool["Derelor"])], hand=[ritual], enforce=True
        )
        p1.mana_pool.update(mana)
        return game.cast_from_hand(0, "Dark Ritual")

    assert not cast_with(B=1).supported, "one {B} no longer pays {B} plus {B}"
    assert not cast_with(B=1, G=1).supported, "a Forest cannot pay a {B} tax"
    assert cast_with(B=2).supported


def test_derelor_taxes_only_its_own_controllers_black_spells(set_pool):
    """"…**you cast**" is CR 109.5's seat: the opponent's black spell is
    untaxed, and so is a nonblack spell of the controller's own.
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")

    game, p1, _p2 = _g4_game(
        [], their_battlefield=[Permanent(card=pool["Derelor"])], enforce=True
    )
    p1.hand = [lea["Dark Ritual"]]
    p1.mana_pool["B"] = 1
    assert game.cast_from_hand(0, "Dark Ritual").supported, (
        "the taxing permanent is the opponent's, and it taxes only its own "
        "controller's spells"
    )

    game, p1, _p2 = _g4_game(
        [Permanent(card=pool["Derelor"])], hand=[lea["Giant Growth"]], enforce=True
    )
    p1.mana_pool["G"] = 1
    assert game.cast_from_hand(0, "Giant Growth").supported, "green is not black"


# Thelonite Druid — an activated, one-turn land animation scoped to "you control"


def _g4_druid_board(set_pool):
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    druid = _g4_nosick(Permanent(card=pool["Thelonite Druid"]))
    forest = Permanent(card=lea["Forest"])
    mountain = Permanent(card=lea["Mountain"])
    fodder = _g4_nosick(Permanent(card=lea["Grizzly Bears"]))
    theirs = Permanent(card=lea["Forest"])
    game, p1, p2 = _g4_game(
        [druid, forest, mountain, fodder], their_battlefield=[theirs]
    )
    return game, p1, p2, druid, forest, mountain, theirs, fodder


def test_thelonite_druid_animates_only_the_forests_you_control(set_pool):
    """"{1}{G}, {T}, Sacrifice a creature: **Forests you control** become 2/3
    creatures until end of turn. They're still lands."

    Three narrowings in one sentence and each one is load-bearing: the Mountain
    is not a Forest, the opponent's Forest is not one *you control*, and the
    animated lands are still lands (CR 613 layer 4 adds a type, it does not
    replace one).
    """
    (game, p1, _p2, druid, forest, mountain, theirs, fodder) = _g4_druid_board(
        set_pool
    )

    result = game.activate_permanent_ability(
        0, "Thelonite Druid", permanent_index=0,
        cost_permanent_ids=[fodder.permanent_id],
    )
    game._settle()

    assert result.supported, result.details
    assert (
        forest.is_creature, forest.effective_power, forest.effective_toughness
    ) == (True, 2, 3)
    assert forest.has_type("land"), "they are still lands"
    assert not mountain.is_creature
    assert not theirs.is_creature
    assert druid.tapped
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]


def test_thelonite_druids_forests_stop_being_creatures_at_cleanup(set_pool):
    """"…**until end of turn**". The record is what makes them creatures, and
    the cleanup sweep is what ends it — a duration nothing lifts is a permanent
    animation.
    """
    (game, _p1, _p2, _druid, forest, _mtn, _theirs, fodder) = _g4_druid_board(
        set_pool
    )
    game.activate_permanent_ability(
        0, "Thelonite Druid", permanent_index=0,
        cost_permanent_ids=[fodder.permanent_id],
    )
    game._settle()
    assert forest.is_creature

    game.resolve_cleanup_step(0)

    assert not forest.is_creature
    assert (forest.effective_power, forest.effective_toughness) == (0, 0)


def test_thelonite_druid_pays_with_itself_when_it_is_the_only_creature(set_pool):
    """The sacrifice is a real cost, and "a creature" includes the source
    (CR 601.2b names no exclusion) — so a lone Druid eats itself, and the
    ability still resolves from the graveyard (CR 603.6).

    That is also the cheapest proof the cost is charged at all: something leaves
    the battlefield every time this is activated.
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    druid = _g4_nosick(Permanent(card=pool["Thelonite Druid"]))
    forest = Permanent(card=lea["Forest"])
    game, p1, _p2 = _g4_game([druid, forest])

    result = game.activate_permanent_ability(0, "Thelonite Druid", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert [card.name for card in p1.graveyard] == ["Thelonite Druid"]
    assert [perm.card.name for perm in p1.battlefield] == ["Forest"]
    assert forest.is_creature


def test_thelonite_druid_spends_nothing_when_it_cannot_pay_the_tap(set_pool):
    """"{1}{G}, **{T}**, Sacrifice a creature: …". CR 302.6 makes a
    summoning-sick creature unable to pay a tap symbol, and CR 601.2h then makes
    the whole cost unpayable — so the ability is not activated and the creature
    that would have paid the sacrifice is still there.

    The order matters as much as the refusal: a cost half-charged is a creature
    eaten for nothing.
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    druid = Permanent(card=pool["Thelonite Druid"])
    fodder = _g4_nosick(Permanent(card=lea["Grizzly Bears"]))
    forest = Permanent(card=lea["Forest"])
    game, p1, _p2 = _g4_game([druid, fodder, forest])
    druid.metadata["summoning_sickness_turn"] = game.turn  # it arrived this turn

    result = game.activate_permanent_ability(
        0, "Thelonite Druid", permanent_index=0,
        cost_permanent_ids=[fodder.permanent_id],
    )
    game._settle()

    assert not result.supported
    assert p1.graveyard == []
    assert not druid.tapped
    assert not forest.is_creature


# Vodalian War Machine — a record of what was tapped to pay for its abilities


def _g4_war_machine(set_pool, merfolk=2, extra=()):
    pool = set_pool("FEM")
    machine = _g4_nosick(Permanent(card=pool["Vodalian War Machine"]))
    school = [
        _g4_nosick(Permanent(card=pool["River Merfolk"])) for _ in range(merfolk)
    ]
    others = [_g4_nosick(Permanent(card=pool[name])) for name in extra]
    game, p1, p2 = _g4_game([machine, *school, *others])
    return game, p1, p2, machine, school, others


def test_vodalian_war_machine_taps_a_merfolk_to_pump(set_pool):
    """"**Tap an untapped Merfolk you control**: This creature gets +2/+1 until
    end of turn."

    The cost taps *another* permanent, and it was charged as nothing at all: the
    count reader knew "a" and not "an", so the ability pumped for free and could
    be pumped forever.
    """
    game, _p1, _p2, machine, school, _others = _g4_war_machine(set_pool)

    result = game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=1,
        cost_permanent_ids=[school[0].permanent_id],
    )
    game._settle()

    assert result.supported, result.details
    assert (machine.effective_power, machine.effective_toughness) == (2, 5)
    assert school[0].tapped
    assert not school[1].tapped


def test_vodalian_war_machine_cannot_pump_with_no_untapped_merfolk(set_pool):
    """The control on the cost: an ability whose payment does not exist is
    refused (CR 602.2b), not activated for nothing.
    """
    game, _p1, _p2, machine, school, _others = _g4_war_machine(set_pool, merfolk=1)
    game.become_tapped(school[0])

    result = game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=1,
    )

    assert not result.supported
    assert (machine.effective_power, machine.effective_toughness) == (0, 4)


def test_vodalian_war_machine_may_attack_after_tapping_a_merfolk(set_pool):
    """Defender, and the ability that lifts it for a turn — checked from both
    sides, because an unenforced defender would make the second half prove
    nothing.
    """
    game, _p1, _p2, _machine, school, _others = _g4_war_machine(set_pool, merfolk=1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    allowed, _why = game.declare_attackers(0, [0])
    assert not allowed, "Defender: it cannot attack on its own"

    game, _p1, _p2, _machine, school, _others = _g4_war_machine(set_pool, merfolk=1)
    assert game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=0,
        cost_permanent_ids=[school[0].permanent_id],
    ).supported
    game._settle()
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert game.declare_attackers(0, [0])[0]


def test_vodalian_war_machine_destroys_only_the_merfolk_that_paid(set_pool):
    """"When this creature dies, destroy all Merfolk **tapped this turn to pay
    for its abilities**."

    Narrower than "tapped this turn", and nothing about a tapped permanent says
    which it is — so the payment path writes the record and the sweep reads it.
    A Merfolk tapped for anything else survives.
    """
    game, p1, _p2, machine, school, others = _g4_war_machine(
        set_pool, merfolk=2, extra=["Vodalian Soldiers"],
    )
    bystander = others[0]

    game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=1,
        cost_permanent_ids=[school[0].permanent_id],
    )
    game._settle()
    game.become_tapped(bystander)  # tapped, but not to pay for anything

    game.sacrifice_permanent(machine)
    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == [
        "River Merfolk", "Vodalian Soldiers",
    ], "the untapped Merfolk and the bystander both survive"
    assert [card.name for card in p1.graveyard] == [
        "Vodalian War Machine", "River Merfolk",
    ]


def test_vodalian_war_machines_record_does_not_outlive_the_turn(set_pool):
    """"…tapped **this turn**". The record is swept at cleanup, so a Merfolk
    that paid on an earlier turn is not destroyed — without the sweep the phrase
    would mean "ever".
    """
    game, p1, _p2, machine, school, _others = _g4_war_machine(set_pool, merfolk=1)

    game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=1,
        cost_permanent_ids=[school[0].permanent_id],
    )
    game._settle()
    game.resolve_cleanup_step(0)

    game.sacrifice_permanent(machine)
    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == ["River Merfolk"]
