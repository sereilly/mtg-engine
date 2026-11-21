"""A recorded "skip your next untap step" is spent by the untap step itself.

``Game.skip_next_step("untap", seat=...)`` was written by every card that
prints the words — Avizoa's "{0}: This creature gets +2/+2 until end of turn.
You skip your next untap step." (Weatherlight, shipped), Yosei's and
Shisato's (Champions of Kamigawa) — and read by nothing on any road into the
untap step: the headless turn and the simulator's (``start_turn``), and the
web's (``turn_steps``), all call ``resolve_untap_step``, which never looked.
So Avizoa's drawback never happened. Found driving Yosei, the Morning Star
(CHK W1G3). CR 614.10: the skip replaces the step with nothing; the turn still
begins (summoning sickness wears off, CR 302.6).
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState

from tests.helpers import _nosick, settle


def _avizoa_game(set_pool):
    island = set_pool("LEA")["Island"]
    avizoa = _nosick(Permanent(card=set_pool("WTH")["Avizoa"]))
    land = _nosick(Permanent(card=island))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[avizoa, land], library=[island] * 10),
        PlayerState(name="P2", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game, avizoa, land


def test_avizoa_skips_its_controllers_next_untap_step(set_pool):
    game, avizoa, land = _avizoa_game(set_pool)
    assert game.activate_permanent_ability(0, "Avizoa").supported
    settle(game)
    assert avizoa.effective_power == 4
    assert game.skip_step_counts == {(0, "untap"): 1}
    game.become_tapped(avizoa)
    game.become_tapped(land)
    game.start_next_turn()  # P2's turn
    assert game.skip_step_counts == {(0, "untap"): 1}
    game.start_next_turn()  # P1's: the untap step is skipped, the record spent
    assert game.active_player_index == 0
    assert avizoa.tapped and land.tapped
    assert game.skip_step_counts == {}
    game.start_next_turn()
    game.start_next_turn()  # the next one happens
    assert not avizoa.tapped and not land.tapped


def test_an_unspent_skip_waits_for_its_own_players_untap_step(set_pool):
    """A seated skip is that player's: the opponent's untap step in between
    does not spend it."""
    game, avizoa, land = _avizoa_game(set_pool)
    island = Permanent(card=set_pool("LEA")["Island"])
    game._put_permanent_onto_battlefield(1, island, None)
    game._sync_control()
    game.become_tapped(island)
    game.skip_next_step("untap", seat=0)
    game.start_next_turn()  # P2 untaps normally
    assert not island.tapped
    assert game.skip_step_counts == {(0, "untap"): 1}
    game.become_tapped(land)
    game.start_next_turn()  # P1's is skipped
    assert land.tapped and game.skip_step_counts == {}
