"""The recipient-keyed "the next time damage would be dealt to …" is one
**simultaneous dealing** wide — not one resolution.

Glarecaster: "{5}{W}: The next time damage would be dealt to this creature
and/or you this turn, that damage is dealt to any target instead." Its ruling
(2004-10-04): "If both you and this card would be dealt damage at the same
time, or if either you or this card would be dealt damage from multiple
sources at the same time, the redirection will apply to both chunks of
damage." *At the same time* is a dealing (``engine/simultaneous_damage.py``):
a sweep, a split sentence, a combat damage step. Two printed sentences are two
events (CR 608.2c), and Mana Clash's flips are as many ("Each point of damage
is dealt separately, so if you are damaged twice by this spell, each time is
considered a separate time this source deals damage", its ruling, 2004-10-04).

Until kg5 the template's moment was the resolving stack object
(``damage_redirects.damage_moment``), so Illuminate kicked with {2}{R} moved
its second sentence's damage to Glarecaster's controller too, and every one of
Mana Clash's flips moved. The moment is now the dealing for every "next time"
(``damage_redirects.dealing_moment``), and the combat damage step's dealing
closes its occasions as it finishes like any other — ``COMBAT_DEALING`` and
``end_simultaneous_redirects`` are gone.

Validated backwards: on the base (``59f133e6``) the Illuminate and Mana Clash
boards fail; the sweep board (one dealing, both chunks move) passes on both.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from tests.helpers import settle

_SEATS = [pytest.param(set(), id="nobody-asked"), pytest.param({0, 1}, id="interactive")]
_RECIPIENT_KEYED = re.compile(r"\bthe next time damage would be dealt to\b", re.I)
#: Each recipient-keyed card and where its "time" is driven.
_DRIVEN = {
    "Glarecaster": "this module: Illuminate, Mana Clash, Hurricane",
    # One recipient: no resolution in the pool deals damage to one creature in
    # two dealings, so its time meets a second chunk only in combat — two
    # blockers, one combat damage step.
    "Mirrorwood Treefolk": "tests/regressions/test_next_time_is_a_time.py::"
                           "test_mirrorwood_treefolk_moves_both_blockers_then_the_time_is_over",
}


@pytest.mark.cr("614.9", "608.2c")
def test_every_recipient_keyed_next_time_is_driven():
    found = set()
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        if _RECIPIENT_KEYED.search(card.oracle_text or ""):
            found.add(card.name)
    assert len(found) >= 2, found
    assert found == set(_DRIVEN), found


def _table(catalog_by_name, interactive, *, hand0=()):
    game = Game(players=[
        PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20,
                    hand=[catalog_by_name[name] for name in hand0]),
        PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.current_turn_phase = "main1"
    glare = Permanent(card=catalog_by_name["Glarecaster"])
    game._put_permanent_onto_battlefield(1, glare, None)
    glare.metadata["summoning_sickness_turn"] = -99
    # Bob arms it, its "any target" Alice.
    game.active_player_index = 1
    armed = game.activate_permanent_ability(1, "Glarecaster", target_player_index=0)
    assert armed.supported, armed.details
    settle(game)
    game.active_player_index = 0
    return game, glare


def _lives(game):
    return [player.life for player in game.players]


@pytest.mark.cr("614.9", "608.2c")
@pytest.mark.parametrize("interactive", _SEATS)
def test_illuminate_kicked_moves_only_its_first_sentence(catalog_by_name, interactive):
    """Illuminate, X=2, kicked with {2}{R}, at Glarecaster: "Illuminate deals X
    damage to target creature. If this spell was kicked with its {2}{R}
    kicker, it deals X damage to that creature's controller." The first
    sentence's 2 go to Alice instead; the second sentence is another event,
    after the time is over, and Bob is dealt his 2."""
    game, glare = _table(catalog_by_name, interactive, hand0=["Illuminate"])
    cast = game.cast_from_hand(
        0, "Illuminate", x_value=2, target_permanent_ids=[glare.permanent_id],
        optional_cost_payments={"{2}{R}": 1},
    )
    assert cast.supported, cast.details
    settle(game)
    assert glare.damage_marked == 0, game.log
    assert _lives(game) == [18, 18], game.log
    assert sum("is dealt to Alice instead (Glarecaster)" in line for line in game.log) == 1, game.log


@pytest.mark.cr("614.9", "705.1")
@pytest.mark.parametrize("interactive", _SEATS)
def test_mana_clash_moves_only_its_first_point(catalog_by_name, monkeypatch, interactive):
    """Mana Clash at Bob: tails for him twice, then heads for both. Each point
    is dealt separately — the first moves to Alice, the second is Bob's."""
    from engine.handlers import damage as damage_handlers

    flips = iter([True, False, True, False, True, True])
    monkeypatch.setattr(damage_handlers, "flip_coin", lambda win_probability=0.5: next(flips))
    game, _glare = _table(catalog_by_name, interactive, hand0=["Mana Clash"])
    cast = game.cast_from_hand(0, "Mana Clash", target_player_index=1)
    assert cast.supported, cast.details
    settle(game)
    assert _lives(game) == [19, 19], game.log
    assert sum("is dealt to Alice instead (Glarecaster)" in line for line in game.log) == 1, game.log


@pytest.mark.cr("614.9", "608.2f")
@pytest.mark.parametrize("interactive", _SEATS)
def test_a_sweep_at_glarecaster_and_its_controller_moves_both_chunks(catalog_by_name, interactive):
    """Hurricane, X=1: "deals X damage to each creature with flying and each
    player" — one dealing, so the flying Glarecaster's chunk and Bob's are one
    time and both go to Alice (and Alice's own chunk is hers)."""
    game, glare = _table(catalog_by_name, interactive, hand0=["Hurricane"])
    cast = game.cast_from_hand(0, "Hurricane", x_value=1)
    assert cast.supported, cast.details
    settle(game)
    assert glare.damage_marked == 0, game.log
    assert _lives(game) == [17, 20], game.log
