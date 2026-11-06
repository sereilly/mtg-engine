"""A damage redirect is bought against damage coming, never in an idle main
phase (SCG Phase 5).

Seen: the AI activated Zealous Inquisitor ("{1}{W}: The next 1 damage that
would be dealt to this creature this turn is dealt to target creature
instead") in its own precombat main phase, aimed at the person's Ancient Ooze,
and then declared no attack: nothing was coming at the Inquisitor that turn.

The main-phase chooser rehearses a shield before proposing it
(``ai_valuation.shields_only``, LGN Phase 5), and a redirect was not one: CR
614.9's redirects are categorised ``damage``, so the flat score rated it 2.5.
``DAMAGE_REPLACEMENT_KINDS`` makes it one. In front of a burn spell aimed at
the Inquisitor the same redirect is still taken.
"""
from __future__ import annotations

from engine.ai_abilities import choose_activation_action
from engine.ai_policy import activate_chosen_ability, choose_instant_speed_activation
from engine.game import Game
from engine.mixins._constants import phases_after
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack


def _table(cards, own, other=()) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat, names in ((0, own), (1, other)):
        for name in names:
            game.players[seat].battlefield.append(_nosick(Permanent(card=cards[name])))
        game.players[seat].library = [cards["Plains"]] * 10
    game._recompute_continuous_effects()
    return game


def _main_phase(game: Game, phase: str = "precombat_main") -> Game:
    game.start_turn(0)
    for _ in range(6):
        if game.current_turn_phase == "precombat_main":
            break
        game._close_current_priority_step()
    if phase == "postcombat_main":
        game.current_turn_phase = game.current_step = phase
        game.turn_phases_remaining = phases_after(phase)
    return game


def _cards(set_pool) -> dict:
    cards = dict(set_pool("LEA"))
    cards["Zealous Inquisitor"] = set_pool("SCG")["Zealous Inquisitor"]
    return cards


def test_zealous_inquisitor_is_not_activated_with_nothing_coming(set_pool):
    """Main phase 2, and main phase 1 against a creature too big to attack
    into (the Phase 5 board: the AI then attacked with nothing)."""
    cards = _cards(set_pool)
    game = _main_phase(
        _table(cards, ["Zealous Inquisitor", "Plains", "Plains"], ["Grizzly Bears"]),
        "postcombat_main",
    )
    assert choose_activation_action(game, 0) is None
    game = _main_phase(_table(cards, ["Zealous Inquisitor", "Plains", "Plains"], ["Craw Wurm"]))
    assert choose_activation_action(game, 0) is None


def test_zealous_inquisitor_redirects_a_burn_spell_aimed_at_it(set_pool):
    """The opponent's Shock at the Inquisitor (a 2/2): in response the AI
    redirects 1 of the 2 onto the opponent's Grizzly Bears, and the
    Inquisitor lives. The same rehearsal that now turns the redirect down
    when idle takes it here; against a Lightning Bolt it does not, since the
    Inquisitor dies to the rest either way (that is a weighing, and right)."""
    cards = _cards(set_pool)
    cards["Shock"] = set_pool("6ED")["Shock"]
    game = _table(cards, ["Zealous Inquisitor", "Plains", "Plains"], ["Grizzly Bears", "Mountain"])
    game.players[1].hand = [cards["Shock"]]
    _main_phase(game)
    inquisitor = game.players[0].battlefield[0]
    assert inquisitor.card.name == "Zealous Inquisitor"
    game.players[1].mana_pool["R"] = 1  # the Mountain, tapped for the Shock
    result = game.queue_from_hand(1, "Shock", target_player_index=0, target_permanent_index=0)
    assert result.supported, result.details
    action = choose_instant_speed_activation(game, 0)
    assert action is not None and action.permanent_name == "Zealous Inquisitor", action
    assert action.target_player_index == 1
    assert activate_chosen_ability(game, 0, action).supported
    resolve_stack(game)
    assert any(p is inquisitor for p in game.players[0].battlefield), game.log[-10:]
    bears = next(p for p in game.players[1].battlefield if p.card.name == "Grizzly Bears")
    assert bears.damage_marked == 1, game.log[-10:]
