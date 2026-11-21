"""A one-shot "skip your next untap step" is spent by the untap step.

"You skip your next untap step." (Avizoa, Weatherlight.) CR 614.10: the skip
is a replacement — "instead of doing [the step], do nothing". The record went
into ``Game.skip_step_counts`` keyed by seat since Ivory Gargoyle, but only
the draw step and the combat phase's walk ever spent a step record: the untap
step never asked, so Avizoa's drawback (and Yosei's and Shisato's skips,
Champions of Kamigawa) was a card that did more than it printed — every
permanent untapped on schedule. The untap step now spends the seat's record
(``UntapStepMixin.resolve_untap_step``), and the phasing event does not occur
in the skipped step (CR 702.26m).
"""

from __future__ import annotations

from engine import PlayerState
from engine.models import Permanent
from tests.helpers import _game, _nosick, settle, stock_libraries


def _avizoa_table(set_pool):
    game = _game(PlayerState(name="P1", life=20), PlayerState(name="P2", life=20))
    stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    avizoa = Permanent(card=set_pool("WTH")["Avizoa"])
    game._put_permanent_onto_battlefield(0, avizoa, None)
    _nosick(avizoa)
    land = Permanent(card=set_pool("LEA")["Island"])
    game._put_permanent_onto_battlefield(0, land, None)
    game._sync_control()
    return game, avizoa, land


def test_avizoas_drawback_keeps_its_controllers_permanents_tapped(set_pool):
    game, avizoa, land = _avizoa_table(set_pool)
    result = game.activate_permanent_ability(0, "Avizoa")
    assert result.supported, result
    settle(game)
    assert game.skip_step_counts.get((0, "untap")) == 1, game.skip_step_counts
    avizoa.tapped = True
    land.tapped = True

    game.start_turn(1)
    settle(game)
    game.start_turn(0)
    settle(game)
    assert avizoa.tapped and land.tapped, game.log[-8:]
    assert "P1 skips their untap step" in game.log
    assert not game.skip_step_counts

    # Spent once: the next untap step untaps.
    game.start_turn(1)
    settle(game)
    game.start_turn(0)
    assert not avizoa.tapped and not land.tapped


def test_the_skip_is_the_controllers_alone(set_pool):
    game, _, _ = _avizoa_table(set_pool)
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bear, None)
    game._sync_control()
    assert game.activate_permanent_ability(0, "Avizoa").supported
    settle(game)
    bear.tapped = True
    game.start_turn(1)
    assert not bear.tapped
    assert game.skip_step_counts.get((0, "untap")) == 1


def test_a_skipped_untap_step_offers_no_winter_orb_selection(set_pool):
    """A step a skip takes offers nothing to choose in it: the selection the
    web layer pauses on is not raised for a step that will not happen."""
    game, avizoa, land = _avizoa_table(set_pool)
    orb = Permanent(card=set_pool("LEA")["Winter Orb"])
    game._put_permanent_onto_battlefield(1, orb, None)
    extra = Permanent(card=set_pool("LEA")["Island"])
    game._put_permanent_onto_battlefield(0, extra, None)
    game._sync_control()
    land.tapped = True
    extra.tapped = True
    assert game.get_untap_land_selection_options(0) is not None
    assert game.activate_permanent_ability(0, "Avizoa").supported
    settle(game)
    assert game.get_untap_land_selection_options(0) is None
