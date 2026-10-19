"""A cast made before the turn's combat is worth what it does to the fight.

The policy rehearses a cast on a copy of the game and runs the copy to the
end of the turn with **nothing declared on the way** — so what a precombat
cast does *to the combat that follows it* was not in the price:

* a **Fog** in its caster's own main phase "changed" a turn flag, harmed
  nobody by that reading, and was cast — stopping the caster's own attack;
* a **pump** was a quarter of the body it lent whether the creature then
  attacked for three more or stayed home, and was cast in the first main
  phase it could be;
* **Hatred** was the life it cost, and was held with lethal on the table.

A cast whose good is this turn's only — everything it changed gone by the end
of the turn (``Rehearsal.fleeting``), or more of its good than is left — is
now read a second time with the turn's combat fought on both copies
(``ai_policy._weighed_through_the_fight``), and one that has left nothing
even then is not proposed (``_worth_proposing``).

Every test makes the cast and **plays the turn's combat for real**
(``ai_combat.run_ai_combat_phase``), and asserts on the table afterwards.
The pool-wide half is ``test_ai_combat_trick_census.py``: every instant and
sorcery whose good is this turn's, on seven boards built for no card, cast
where the fight it changes is and held where it changes nothing — and
``test_ai_idle_cast_census.py``, on whose three boards no proposal moves
nothing that outlasts the turn.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_combat import run_ai_combat_phase
from engine.ai_policy import (SPELL_BASE_SCORE, cast_announcement,
                              choose_cast_action,
                              choose_combat_instant_cast_action)
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from tests.helpers import _mk_creature_card, declare_attack, resolve_stack

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


def _table(pool, hand, mine=(), theirs=(), *, life=(20, 20), arrived=()) -> Game:
    """Seat 0's precombat main phase. *arrived* names the creatures that came
    under their controller's control this turn (CR 302.6)."""
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[pool[name] for name in hand],
                    library=[forest] * 20, life=life[0]),
        PlayerState(name="Opp", hand=[], library=[forest] * 20, life=life[1]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat, cards in ((ME, mine), (OPP, theirs)):
        for card in cards:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, seat)
            permanent.metadata["summoning_sickness_turn"] = (
                game.turn if card.name in arrived else -99
            )
    return game


def _cast_and_fight(game, action) -> None:
    """Make the cast, resolve it, and play the turn's combat."""
    result = game.cast_from_hand(ME, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    run_ai_combat_phase(game, ME)


def _names(game, seat) -> list:
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


BEAR = _mk_creature_card("My Bear", 2, 2)
OGRE = _mk_creature_card("My Ogre", 3, 3)


# --- Fog ----------------------------------------------------------------------


def test_fog_is_not_cast_in_its_casters_own_main_phase(pool):
    """With an attacker ready, the Fog stops the caster's own two damage;
    with nobody anywhere, it stops nothing. Cast, both times: it "changed" a
    turn flag and left its caster no worse off by a reading with no combat
    in it."""
    with_an_attacker = _table(pool, ["Fog"], mine=[BEAR])
    assert choose_cast_action(with_an_attacker, ME) is None
    # ...and the attack it would have stopped is made.
    run_ai_combat_phase(with_an_attacker, ME)
    assert with_an_attacker.players[OPP].life == 18

    assert choose_cast_action(_table(pool, ["Fog"]), ME) is None


def test_fog_is_cast_under_an_attack(pool):
    """The moment it is for: four damage coming and nothing in front of it."""
    game = _table(pool, ["Fog"], theirs=[_mk_creature_card("Their Giant", 4, 4)])
    declare_attack(game, OPP)

    action = choose_combat_instant_cast_action(game, ME)

    assert action is not None and action.card_name == "Fog"
    result = game.queue_from_hand(ME, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    for _ in range(6):
        if game.current_turn_phase != "combat":
            break
        game.advance_combat_phase()
    assert game.players[ME].life == 20


# --- A pump -------------------------------------------------------------------


def test_a_pump_is_cast_on_the_attacker_it_puts_three_more_damage_through_with(pool):
    game = _table(pool, ["Giant Growth"], mine=[BEAR])
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Giant Growth"
    _cast_and_fight(game, action)
    assert game.players[OPP].life == 15


def test_a_pump_is_held_for_a_creature_that_cannot_fight(pool):
    """The Bear came in this turn: +3/+3 until end of turn on a creature that
    is not attacking is nothing by the end of the turn. It was cast, for a
    quarter of the body it lent."""
    game = _table(pool, ["Giant Growth"], mine=[BEAR], arrived=("My Bear",))
    assert choose_cast_action(game, ME) is None


def test_a_pump_is_held_once_the_fight_is_over(pool):
    game = _table(pool, ["Giant Growth"], mine=[BEAR])
    game._set_phase_and_step("postcombat_main", "postcombat_main")
    assert choose_cast_action(game, ME) is None


def test_a_pump_wins_the_fight_it_is_cast_before(pool):
    """A 2/2 into a 0/4: with +3/+3 the attack is made and the Wall that
    blocks it dies."""
    game = _table(
        pool, ["Giant Growth"], mine=[BEAR], theirs=[_mk_creature_card("Their Wall", 0, 4)],
    )
    action = choose_cast_action(game, ME)
    assert action is not None
    _cast_and_fight(game, action)
    assert _names(game, OPP) == [] and _names(game, ME) == ["My Bear"]


# --- Evasion, and a blocker tapped ----------------------------------------------


def test_flying_is_cast_where_something_stands_in_the_way(pool):
    """Jump, "target creature gains flying until end of turn": two damage
    over a 0/4 that would have stopped it — and held where nothing would
    have."""
    game = _table(pool, ["Jump"], mine=[BEAR], theirs=[_mk_creature_card("Their Wall", 0, 4)])
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Jump"
    _cast_and_fight(game, action)
    assert game.players[OPP].life == 18

    assert choose_cast_action(_table(pool, ["Jump"], mine=[BEAR]), ME) is None


def test_a_creature_tapped_after_the_fight_is_not_a_cast(pool):
    """Twiddle at the opposing creature once the turn's combat is over: it
    untaps in its controller's untap step (CR 502.3) before it could have
    done anything tapped or untapped. It was cast there, for a quarter of
    the body it took for the rest of the turn — the end of the turn, which
    is where a rehearsal stops reading (``ai_valuation.
    untap_for_the_next_turn``)."""
    game = _table(pool, ["Twiddle"], mine=[BEAR], theirs=[_mk_creature_card("Their Rival", 2, 2)])
    game._set_phase_and_step("postcombat_main", "postcombat_main")
    assert choose_cast_action(game, ME) is None


def test_a_combat_a_cast_adds_is_a_fight_it_is_weighed_through(pool):
    """Relentless Assault after the Bear has attacked: "untap all creatures
    that attacked this turn. After this main phase, there is an additional
    combat phase" (CR 500.8). Nothing it does is left at the end of the turn
    but what the second attack did, so a reading that fought only the turn's
    first combat — from its precombat main phase — held it."""
    game = _table(pool, ["Relentless Assault"], mine=[BEAR])
    run_ai_combat_phase(game, ME)
    assert game.current_turn_phase == "postcombat_main"
    assert game.players[OPP].life == 18
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Relentless Assault"
    # Priced at the second attack's two damage: proposed before for the
    # turn's plan left unspent on a copy run straight to its cleanup.
    assert action.score - SPELL_BASE_SCORE == pytest.approx(2.0)
    result = game.cast_from_hand(ME, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    assert game.enter_next_turn_phase() == "combat"
    run_ai_combat_phase(game, ME)
    assert game.players[OPP].life == 16


def test_the_lone_blocker_is_tapped_before_the_attack(pool):
    """Twiddle at the creature in the way: a tap is over with the opposing
    untap step, and what it is worth is the attack it lets through."""
    wall = _mk_creature_card("Their Wall", 0, 4)
    game = _table(pool, ["Twiddle"], mine=[OGRE], theirs=[wall])
    action = choose_cast_action(game, ME)
    assert action is not None
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is wall
    _cast_and_fight(game, action)
    assert game.players[OPP].life == 17


# --- Hatred ---------------------------------------------------------------------


def test_hatred_is_cast_for_the_game(pool):
    """"As an additional cost, pay X life. Target creature gets +X/+0 until
    end of turn." An unblocked 2/2, an opponent at twelve: ten life is the
    game. It was held — the life is lasting and the power is not."""
    game = _table(pool, ["Hatred"], mine=[BEAR], life=(20, 12))
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Hatred"
    _cast_and_fight(game, action)
    assert game.players[OPP].life <= 0


def test_hatred_is_held_with_nobody_to_carry_it(pool):
    game = _table(pool, ["Hatred"], mine=[BEAR], life=(20, 12), arrived=("My Bear",))
    assert choose_cast_action(game, ME) is None


def test_hatred_pays_the_life_the_fight_needs(pool):
    """A 2/2 into a 0/4 Wall: two life is a dead Wall. The X was the largest
    the life reserve allowed — ten life for a Wall worth less than that —
    and measured as the loss it was, so Hatred was held; each size is now
    weighed (``ai_policy._cast_candidate_sized``)."""
    wall = _mk_creature_card("Their Wall", 0, 4, "Defender")
    game = _table(pool, ["Hatred"], mine=[BEAR], theirs=[wall])
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Hatred"
    assert action.x_value is not None and action.x_value < 10
    _cast_and_fight(game, action)
    assert _names(game, OPP) == [] and _names(game, ME) == ["My Bear"]
    assert game.players[ME].life == 20 - action.x_value >= 15


# --- A shield, and damage nothing dies of ---------------------------------------


def test_a_shield_for_any_target_goes_on_the_creature_about_to_trade(pool):
    """Healing Salve's second bullet, "prevent the next 3 damage that would
    be dealt to any target this turn", with a 2/2 about to trade with a 2/2:
    on the attacker it is the trade won. Its target was chosen with no
    combat in the reading — the caster's seat, where it is nothing — and
    the cast was then held, or made on the caster for three life."""
    rival = _mk_creature_card("Their Rival", 2, 2)
    game = _table(pool, ["Healing Salve"], mine=[BEAR], theirs=[rival])
    action = choose_cast_action(game, ME)
    assert action is not None and action.mode_index == 1
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is BEAR
    _cast_and_fight(game, action)
    assert _names(game, OPP) == [] and _names(game, ME) == ["My Bear"]


def test_damage_a_creature_survives_is_not_a_cast(pool):
    """Strafe, "3 damage to target nonred creature", at a 4/4 it does not
    kill: by the end of the turn the damage is gone (CR 514.2) and it was a
    cast only for the turn's record of who dealt what. At a 2/2 it kills."""
    giant = _mk_creature_card("Their Giant", 4, 4)
    assert choose_cast_action(_table(pool, ["Strafe"], theirs=[giant]), ME) is None

    game = _table(pool, ["Strafe"], theirs=[_mk_creature_card("Their Bear", 2, 2)])
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Strafe"
    result = game.cast_from_hand(ME, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    assert _names(game, OPP) == []


# --- What comes back to the hand, and what is not a trick -------------------------


def test_a_spell_bought_back_for_nothing_is_not_a_card_to_the_good(pool):
    """Seething Anger, "Buyback {3}. Target creature gets +3/+0 until end of
    turn": on a creature that cannot attack the pump is nothing and the card
    is back in hand — which measured as a card gained, every main phase."""
    idle = _table(pool, ["Seething Anger"], mine=[OGRE], arrived=("My Ogre",))
    assert choose_cast_action(idle, ME) is None

    game = _table(pool, ["Seething Anger"], mine=[OGRE])
    action = choose_cast_action(game, ME)
    assert action is not None
    _cast_and_fight(game, action)
    assert game.players[OPP].life == 14


def test_a_ritual_and_a_removal_spell_are_cast_as_they_were(pool):
    """Mana is gone by the end of the turn because it is spent; a creature
    destroyed is still destroyed. Neither is asked about the fight."""
    ritual = _table(pool, ["Dark Ritual"])
    action = choose_cast_action(ritual, ME)
    assert action is not None and action.card_name == "Dark Ritual"

    game = _table(pool, ["Terror"], mine=[BEAR], theirs=[_mk_creature_card("Their Ogre", 3, 3)])
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Terror"
    _cast_and_fight(game, action)
    assert _names(game, OPP) == []
