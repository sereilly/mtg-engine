"""The main-phase activation chooser and an ability that only arms a draw
replacement ("The next time you would draw a card this turn, <effect>
instead." — Onslaught's Words, Mangara's Tome).

``ai_abilities.choose_activation_action`` scores a non-land ability by its
effect's family, and an arming scored 2.5 like any other effect: every AI seat
holding a Word armed it in every main phase after its own draw step, the mana
spent on a replacement no draw that turn would meet (an ONS six-game run
armed 128 Words and spent eight). Such an ability is now gated by the
rehearsal land abilities already are — carried out on a copy through the end
of the turn, proposed only where the seat ends ahead
(``ai_valuation.waits_on_a_later_draw``).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine import ai_abilities
from engine.ai_abilities import choose_activation_action
from engine.models import Permanent


def _main_phase_with_a_word(set_pool):
    ons = set_pool("ONS")
    me = PlayerState(name="AI", library=[ons["Island"]] * 8)
    opp = PlayerState(name="Opp", library=[ons["Island"]] * 8)
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.turn = 3
    for name in ("Words of Worship", "Plains", "Plains"):
        permanent = Permanent(card=ons[name])
        permanent.metadata["summoning_sickness_turn"] = -99
        game._put_permanent_onto_battlefield(0, permanent, None)
    game._sync_control()
    return game


def test_a_word_is_not_armed_in_a_main_phase_with_no_draw_to_meet(set_pool):
    game = _main_phase_with_a_word(set_pool)

    action = choose_activation_action(game, 0)

    assert action is None or action.permanent_name != "Words of Worship"
    assert game.armed_draw_replacements == []


def test_the_gate_is_what_stops_it(set_pool, monkeypatch):
    """Backwards: with the predicate switched off the chooser proposes the
    Word again — the defect this file is about, on a tree where it exists."""
    game = _main_phase_with_a_word(set_pool)
    monkeypatch.setattr(ai_abilities, "waits_on_a_later_draw", lambda _instruction: False)

    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Words of Worship"
