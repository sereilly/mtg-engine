"""The simulator's printed-card expectation counts permanents by the types
CR 613's layer 4 gives them (CR 205.2b), not by their printed lines.

Found by kg5's ``aicast``: ``run_ai_simulation([LEA, ATQ], games=2, seed=70,
max_turns=14, required_cards=[Balance, Mishra's Factory, Living Lands, Soul
Net])`` reported, in game 2 at turn 7,

    Unsummon did not remove one target creature

on a game whose own log read "Forest returned to its owner's hand
(Unsummon)". Living Lands makes every Forest a 1/1 creature that is still a
land (CR 613.1d), and the check counted ``card_has_type(perm.card,
"creature")`` — the printed line — on clones detached from the game, which no
layer reaches: the Forest was in neither count, so the defender's printed
creatures read as unchanged. The engine was right; the instrument was wrong.
The snapshot now records each permanent's layer-4 types while it is still on
the table (``simulation_checks._clone_player``), and the counts read those.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.simulation_checks import _assert_expected, _snap
from tests.helpers import _game, _nosick, settle

_CARDS = {card.name: card for card in load_catalog()}
_MISSED = "Unsummon did not remove one target creature"


def _board(defender_names, *, caster_names=()):
    caster = PlayerState(name="Caster", hand=[_CARDS["Unsummon"]])
    defender = PlayerState(name="Defender")
    game = _game(caster, defender)
    placed = {}
    for seat, names in ((0, caster_names), (1, defender_names)):
        for name in names:
            permanent = _nosick(Permanent(card=_CARDS[name]))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[name] = permanent
    game._sync_control()
    return game, placed


def test_an_unsummon_that_bounces_an_animated_forest_is_not_an_issue():
    """aicast's board, one cast: a Forest Living Lands animates, returned to
    its owner's hand beside a printed creature that stays. One creature left
    the defender's battlefield, and the check says so — on the base it
    counted the Bears alone, before and after, and reported the cast."""
    game, placed = _board(["Forest", "Grizzly Bears"], caster_names=["Living Lands"])
    forest = placed["Forest"]
    assert forest.is_creature, "Living Lands should make the Forest a creature (layer 4)"
    before = _snap(game)
    result = game.cast_from_hand(
        0, "Unsummon", target_player_index=1,
        target_permanent_ids=[forest.permanent_id],
    )
    assert result.supported, result.details
    settle(game)
    after = _snap(game)
    assert [card.name for card in game.players[1].hand] == ["Forest"], game.log[-6:]
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Grizzly Bears"]
    assert _assert_expected(_CARDS["Unsummon"], before, after, 0, 1) is None


def test_the_check_still_fires_when_no_creature_left():
    """Reading layer 4 does not neuter the expectation: snapshots in which
    nothing left are still an issue, the animated Forest counted as the
    creature it was."""
    game, _placed = _board(["Forest"], caster_names=["Living Lands"])
    snap = _snap(game)
    assert _assert_expected(_CARDS["Unsummon"], snap, snap, 0, 1) == _MISSED


@pytest.mark.parametrize("animated", [True, False])
def test_the_snapshot_reads_each_permanent_through_layer_four(animated):
    """A clone belongs to no game, so what it is counted as is what the table
    said when it was taken: with Living Lands the defender's Forest is a
    creature in the snapshot, and an unchanged board is a missed bounce;
    without it the defender has no creature and the check has nothing to
    say."""
    game, _placed = _board(
        ["Forest"], caster_names=["Living Lands"] if animated else [],
    )
    snap = _snap(game)
    assert _assert_expected(_CARDS["Unsummon"], snap, snap, 0, 1) == (
        _MISSED if animated else None
    )


def test_the_disenchant_count_reads_the_same_snapshot():
    """Disenchant's twin, on the same reading: an artifact creature counts as
    the artifact it is, and one destroyed is the one expected."""
    caster = PlayerState(name="Caster", hand=[_CARDS["Disenchant"]])
    defender = PlayerState(name="Defender")
    game = _game(caster, defender)
    ornithopter = _nosick(Permanent(card=_CARDS["Ornithopter"]))
    game._put_permanent_onto_battlefield(1, ornithopter, None)
    game._sync_control()
    before = _snap(game)
    result = game.cast_from_hand(
        0, "Disenchant", target_player_index=1,
        target_permanent_ids=[ornithopter.permanent_id],
    )
    assert result.supported, result.details
    settle(game)
    after = _snap(game)
    assert not list(game.controlled_by(1)), game.log[-6:]
    assert _assert_expected(_CARDS["Disenchant"], before, after, 0, 1) is None
    assert _assert_expected(_CARDS["Disenchant"], before, before, 0, 1) is not None
