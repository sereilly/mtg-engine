"""The combat gambles kg4 left unpriced (``ai_combat_triggers``), each driven
through the AI's own combat (``run_ai_combat_phase``) and read off the board.

* Ebonblade Reaper's "you lose half your life, rounded up" — at one life the
  attack is the game;
* Loafing Giant's milled land — its damage prevented as often as its
  controller's library holds lands;
* tolls behind a ``may`` — Rotting Giant's "sacrifice it unless you exile a
  card from your graveyard", Hasran Ogress's "3 damage to you unless you pay
  {2}" — priced where they cannot be paid;
* a defender reading an armed lost-flip redirect — Goblin Psychopath's five
  are its controller's, blocked or not;
* Goblin Cadets' "blocks or becomes blocked, target opponent gains control of
  it" — an attack into a blocker and a block are a creature handed over.
"""
from __future__ import annotations

from functools import lru_cache

import pytest

from engine import Game, PlayerState
from engine.ai_combat import run_ai_combat_phase
from engine.ai_combat_triggers import (combat_gamble, expected_attack_damage,
                                       turned_on_its_controller)
from engine.ai_declarations import choose_attackers, choose_combat_blockers
from engine.card_loader import load_catalog
from engine.models import Permanent

from tests.helpers import settle


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _combat(mine, theirs=(), *, my_life=20, their_life=20, library=None, graveyard=(),
            mana=False):
    """A two-seat table in seat 0's declare-attackers step."""
    catalog = _catalog()
    me = PlayerState(
        name="AI", life=my_life, graveyard=[catalog[n] for n in graveyard],
        library=[catalog[n] for n in (library or ["Mountain"] * 10)],
    )
    them = PlayerState(name="Them", life=their_life, library=[catalog["Mountain"]] * 10)
    game = Game(players=[me, them])
    game.enforce_mana_costs = mana
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=catalog[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
    game.start_turn(0)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.current_step == "declare_attackers"
    return game, me, them


def _named(game, seat, name):
    return next(p for p in game.controlled_by(game.players[seat]) if p.card.name == name)


def _fight(game):
    run_ai_combat_phase(game, 0)
    settle(game)


def test_ebonblade_reaper_attacks_an_open_board_but_never_at_one_life():
    """At twenty each against an empty board the Reaper's half-a-life is
    paid for by the opponent's (one damage, then half of nineteen): it
    attacks. At one life the half it rounds up is the last point: it stays
    home. Validated backwards: on 59f133e63 it attacked at one life and its
    controller lost the game to its own trigger."""
    game, me, them = _combat(["Ebonblade Reaper"])
    assert combat_gamble(game, _named(game, 0, "Ebonblade Reaper"), blocking=False).life == 10
    _fight(game)
    assert (me.life, them.life) == (10, 9)
    game, me, them = _combat(["Ebonblade Reaper"], my_life=1)
    assert choose_attackers(game, 0) == []
    _fight(game)
    assert (me.life, them.life) == (1, 20) and not me.lost


@pytest.mark.parametrize("library, expected", [
    (["Forest"] * 10, 0.0), (["Grizzly Bears"] * 10, 4.0),
    (["Forest", "Grizzly Bears"] * 5, 2.0),
])
def test_loafing_giants_damage_is_forecast_by_the_lands_in_its_library(library, expected):
    """"Mill a card. If a land card was milled this way, prevent all combat
    damage this creature would deal this turn": the damage expected is its
    power times the share of its controller's library that is not land —
    a count of the library, never its order (CR 400.2)."""
    game, _me, _them = _combat(["Loafing Giant"], library=library)
    assert expected_attack_damage(game, _named(game, 0, "Loafing Giant")) == pytest.approx(expected)


def test_loafing_giant_over_a_library_of_lands_deals_what_was_forecast():
    """Driven: the forecast and the engine agree — over a library of lands
    the mill finds one and the Giant's four never arrive."""
    game, me, them = _combat(["Loafing Giant"], library=["Forest"] * 10)
    giant = _named(game, 0, "Loafing Giant")
    assert expected_attack_damage(game, giant) == 0.0
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(giant)], defending_player_index=1)
    assert ok, why
    _fight(game)
    assert them.life == 20 and any(c.name == "Forest" for c in me.graveyard)


def test_rotting_giant_attacks_only_with_a_card_to_exile():
    """With an empty graveyard the toll cannot be paid: the Giant is
    sacrificed as its trigger resolves and deals nothing — it stays home.
    With a card there it attacks and pays. Validated backwards: on 59f133e63
    it attacked from an empty graveyard and was sacrificed for nothing."""
    game, me, them = _combat(["Rotting Giant"])
    assert choose_attackers(game, 0) == []
    _fight(game)
    assert them.life == 20 and any(p.card.name == "Rotting Giant" for p in game.controlled_by(me))
    game, me, them = _combat(["Rotting Giant"], graveyard=["Forest"])
    _fight(game)
    assert them.life == 17 and [c.name for c in me.exile] == ["Forest"]
    assert any(p.card.name == "Rotting Giant" for p in game.controlled_by(me))


def test_hasran_ogress_attacks_only_where_its_toll_is_paid_or_worth_it():
    """With no mana for the {2} its own 3 damage is the price of its 3: at
    twenty each it stays home. With two Mountains it attacks and pays.
    Validated backwards: on 59f133e63 it attacked with no mana and took 3."""
    game, me, them = _combat(["Hasran Ogress"], mana=True)
    assert choose_attackers(game, 0) == []
    _fight(game)
    assert (me.life, them.life) == (20, 20)
    game, me, them = _combat(["Hasran Ogress", "Mountain", "Mountain"], mana=True)
    _fight(game)
    assert (me.life, them.life) == (20, 17)


def test_goblin_cadets_does_not_attack_into_a_blocker_and_is_taken_by_one():
    """Into an empty board the Cadets attack for two. Into a Grizzly Bears
    the block hands them to the defender: they stay home. And declared into
    a Crimson Kobolds anyway, the defender blocks with the 0/1 and takes
    them. Validated backwards: on 59f133e63 the 0/1 stayed back, reading the
    block as a chump."""
    game, _me, them = _combat(["Goblin Cadets"])
    _fight(game)
    assert them.life == 18
    game, _me, _them = _combat(["Goblin Cadets"], ["Grizzly Bears"])
    assert choose_attackers(game, 0) == []
    game, me, them = _combat(["Goblin Cadets"], ["Crimson Kobolds"])
    cadets = _named(game, 0, "Goblin Cadets")
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(cadets)], defending_player_index=1)
    assert ok, why
    _fight(game)
    assert game.controller_index_of(cadets) == 1
    assert any(p.card.name == "Crimson Kobolds" for p in game.controlled_by(them))


def test_goblin_cadets_do_not_block_a_bear_for_the_attacker():
    """Blocking, the Cadets change sides before damage and the Bears, still
    blocked, deal nothing: two life saved for a creature handed to the
    attacker. At twenty life the AI does not make that block. Validated
    backwards: on 59f133e63 it read the block as a trade and made it."""
    game, me, them = _combat(["Grizzly Bears"], ["Goblin Cadets"])
    bears = _named(game, 0, "Grizzly Bears")
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(bears)], defending_player_index=1)
    assert ok, why
    settle(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert choose_combat_blockers(game, 1) == {}


def test_a_defender_does_not_spend_its_block_on_a_psychopath_whose_flip_was_lost(monkeypatch):
    """Goblin Psychopath and a Hill Giant attack a seat at three life with
    one Llanowar Elves. The flip is lost: the Psychopath's five are its own
    controller's, blocked or not (the armed redirect). The defender chumps
    the Giant and lives; read as five coming, the Elves "prevented" more on
    the Psychopath and the Giant's three were the game."""
    import engine.handlers.control_flow as control_flow

    monkeypatch.setattr(control_flow, "flip_coin", lambda *args, **kwargs: False)
    game, me, them = _combat(["Goblin Psychopath", "Hill Giant"], ["Llanowar Elves"], their_life=3)
    psychopath, giant = _named(game, 0, "Goblin Psychopath"), _named(game, 0, "Hill Giant")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(psychopath), game.battlefield_index_of(giant)],
        defending_player_index=1,
    )
    assert ok, why
    settle(game)
    assert turned_on_its_controller(game, psychopath)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    blocks = choose_combat_blockers(game, 1)
    assert blocks == {game.battlefield_index_of(_named(game, 1, "Llanowar Elves")):
                      game.battlefield_index_of(giant)}
    _fight(game)
    assert not them.lost and them.life == 3
    assert me.life == 15
