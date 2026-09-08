"""A combat trigger that prints "target" chooses one — CR 603.3d / 601.2c —
and a printed "defending player" is a seat somebody has to hand over (CR 506.2).

Two independent defects met on one card and this file separates them, because
each on its own was enough to make Sidar Jabari do nothing.

**The stamp.** ``_fire_creature_attacks_triggers`` and its blocker twin thread
the permanent's own controller and slot through ``target_player_index`` /
``target_permanent_index`` so ``resolve_own_combatant`` can find it again —
Mijae Djinn removes *itself* from combat, Ydwen Efreet *itself* from the block.
``_choose_trigger_targets`` read that reference as a target the event had
already chosen and returned without announcing, so three shipped cards printing
the word "target" never got CR 603.3d's choice.

**The seat.** ``subject_matches`` refuses a printed "defending player controls"
unless a caller supplies the seat, which is the safe direction: no read of a
permanent can answer it, and by the time a trigger resolves the combat may be
over. Two resolutions never supplied it, so the narrowing rode the payload the
whole way and was then not tested — a restriction that fails *closed*, which is
the rarer half of that bug class and just as silent.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.game import Game
from engine.models import Permanent

from tests.helpers import _mk_creature_card, _nosick, resolve_stack


def _w3g5_attack(attacker_card, defenders, *, interactive=()):
    """*attacker_card* on seat 0, declared as an attacker, blockers not yet in."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    _nosick(attacker)
    blockers = []
    for card in defenders:
        perm = Permanent(card=card)
        game._put_permanent_onto_battlefield(1, perm, None)
        blockers.append(perm)
    resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, message = game.declare_attackers(0, [0])
    assert ok, message
    return game, attacker, blockers


@pytest.mark.cr("603.3d", "601.2c", "506.2")
def test_sidar_jabari_taps_the_defenders_creature_and_not_itself(set_pool):
    """"Whenever Sidar Jabari attacks, tap target creature defending player
    controls."

    Both halves are needed to see this work and neither alone is visible: the
    fire site stamped Jabari's own id, which suppressed the announcement, and
    the handler then never handed ``subject_matches`` the defending seat — so
    the ability announced nothing, matched nothing and logged "no valid
    permanent to tap" every single time.
    """
    bear = _mk_creature_card("Bear", 2, 2)
    game, jabari, blockers = _w3g5_attack(set_pool("MIR")["Sidar Jabari"], [bear])
    resolve_stack(game)

    assert blockers[0].tapped, "the defender's creature is what gets tapped"
    assert any("targets Bear" in line for line in game.log)


@pytest.mark.cr("603.3d", "601.2c")
def test_seasoned_marshal_announces_a_target_rather_than_stamping_itself(set_pool):
    """"Whenever Seasoned Marshal attacks, you may tap target creature."

    No narrowing at all, so both creatures are legal and the *choice* is the
    whole of what was missing: the fire site's stamp made the Marshal the
    target, and it resolved by tapping itself. With the announcement restored
    an interactive seat is asked, and can answer with the opponent's creature —
    an answer that had nowhere to go before.
    """
    bear = _mk_creature_card("Bear", 2, 2)
    game, marshal, blockers = _w3g5_attack(
        set_pool("USG")["Seasoned Marshal"], [bear], interactive=[0]
    )

    choice = next(
        (c for c in game.pending_choices if c.kind == "trigger_target"), None
    )
    assert choice is not None, "CR 603.3d: the controller is asked"
    offered = {target["name"] for target in choice.data["targets"]}
    assert offered == {"Seasoned Marshal", "Bear"}

    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=blockers[0].permanent_id
    )
    resolve_stack(game)
    for pending in list(game.pending_choices):
        game.resolve_pending_choice(pending.kind, pending.player_index, accept=True)
    resolve_stack(game)

    assert blockers[0].tapped
    assert not marshal.tapped or marshal.attacking, "the Marshal tapped by attacking, not by its own ability"


@pytest.mark.cr("603.3d", "601.2c")
def test_elite_javelineer_damages_the_attacker_and_not_itself(set_pool):
    """"Whenever this creature blocks, it deals 1 damage to target attacking
    creature." The blocker twin of the same stamp, and the same symptom: the
    Javelineer dealt its point of damage to the Javelineer.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    attacker = Permanent(card=_mk_creature_card("Bear", 2, 2))
    game._put_permanent_onto_battlefield(0, attacker, None)
    _nosick(attacker)
    javelineer = Permanent(card=set_pool("TMP")["Elite Javelineer"])
    game._put_permanent_onto_battlefield(1, javelineer, None)
    resolve_stack(game)

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    resolve_stack(game)

    assert attacker.damage_marked == 1
    assert javelineer.damage_marked == 0


@pytest.mark.cr("603.3d")
def test_a_trigger_about_an_object_the_event_named_keeps_its_reference(set_pool):
    """The other side of the same gate, and the reason it is not simply "ignore
    the stamp": Mindbender Spores fires from the *same* fire site and its
    printed line names no target — "put four fungus counters on **that
    creature**" is the creature it blocked, which the event chose and CR 603.3d
    has nothing left to choose. Its counters must still land on the attacker.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    attacker = Permanent(card=_mk_creature_card("Bear", 2, 2))
    game._put_permanent_onto_battlefield(0, attacker, None)
    _nosick(attacker)
    spores = Permanent(card=set_pool("MIR")["Mindbender Spores"])
    game._put_permanent_onto_battlefield(1, spores, None)
    resolve_stack(game)

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    resolve_stack(game)

    assert attacker.metadata.get("fungus_counters") == 4
    assert not spores.metadata.get("fungus_counters")


@pytest.mark.cr("506.2")
def test_jangling_automaton_untaps_the_defenders_creatures(set_pool):
    """"Whenever this creature attacks, untap all creatures defending player
    controls."

    The sweep twin of Sidar Jabari's gap, in ``_tap_or_untap_all_matching``:
    the seat was never handed over, so the matcher refused the phrase and the
    sweep matched the empty set. The log said "nothing to tap or untap", which
    reads like a board with nothing on it rather than like a bug.
    """
    bear = _mk_creature_card("Bear", 2, 2)
    ox = _mk_creature_card("Ox", 3, 3)
    game, automaton, blockers = _w3g5_attack(
        set_pool("WTH")["Jangling Automaton"], [bear, ox]
    )
    for blocker in blockers:
        game.become_tapped(blocker)
    resolve_stack(game)

    assert [blocker.tapped for blocker in blockers] == [False, False]


@pytest.mark.cr("506.2", "120.7")
def test_scalding_salamander_burns_the_defenders_board(set_pool):
    """"Whenever this creature attacks, you may have it deal 1 damage to each
    creature without flying defending player controls."

    The damage sweep's copy of the same gap. Every part of this card worked —
    the trigger fired, the offer was made, the handler ran — and the printed
    noun phrase then matched nothing, so an accepted offer swept an empty board
    and logged "found nothing to damage".
    """
    bear = _mk_creature_card("Bear", 2, 2)
    game, salamander, blockers = _w3g5_attack(
        set_pool("EXO")["Scalding Salamander"], [bear]
    )
    resolve_stack(game)
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    resolve_stack(game)

    assert blockers[0].damage_marked == 1
    assert game.damage_ledger.entries[-1].source_permanent_id == salamander.permanent_id
