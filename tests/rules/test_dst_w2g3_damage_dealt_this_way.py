""""A creature **dealt damage this way** can't be regenerated this turn."

Incinerate's rider (and Flamebreak's plural, "Creatures dealt damage this way
…") is about the creatures the damage was *dealt* to, and prevented damage is
damage that "will not be dealt" (CR 615.1a). So a creature whose share was
all prevented was not dealt damage this way and may still be regenerated
(CR 701.19a). Disintegrate's "If it's a creature, it can't be regenerated
this turn" is a different sentence about the *target*: its 2004-10-04 ruling
says "The 'can't regenerate' is an effect of Disintegrate and not an effect
of the damage. It works even if the damage is prevented or redirected."

The engine read both as one payload key that the single-target handler
stamped before dealing, so Test of Faith followed by Incinerate left a
creature that could not regenerate after taking no damage (W1G6's measured
item). Every test drives the real cast and activation entry points and reads
the board after ``settle``.
"""

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import settle


def _table(set_pool, hand):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[island] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.players[0].hand.extend(hand)
    return game


def _skeletons(game, set_pool):
    permanent = Permanent(card=set_pool("LEA")["Drudge Skeletons"])
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._settle()
    return permanent


def _cast(game, name, target, **kwargs):
    result = game.cast_from_hand(
        0, name, target_permanent_ids=[target.permanent_id], **kwargs
    )
    assert result.supported, result.details
    settle(game)


def _regenerate_then_destroy(game, skeletons):
    """"{B}: Regenerate this creature." then Finishing Blow ("Destroy target
    creature or planeswalker."), a destruction a regeneration shield replaces
    unless the creature can't be regenerated (CR 701.19a, 701.19c)."""
    shield = game.activate_permanent_ability(0, "Drudge Skeletons")
    assert shield.supported, shield.details
    settle(game)
    _cast(game, "Finishing Blow", skeletons)


@pytest.mark.cr("615.1a", "701.19a", "701.19c")
@pytest.mark.parametrize("second_incinerate", [False, True])
def test_a_creature_whose_damage_was_prevented_was_not_dealt_damage_this_way(
    set_pool, second_incinerate,
):
    """Test of Faith prevents all three of Incinerate's damage (and makes the
    Skeletons a 4/4 with three counters). Nothing was dealt, so the
    regeneration shield replaces Finishing Blow's destruction and the
    Skeletons survive, tapped. A second Incinerate *is* dealt to the 4/4 —
    three damage marked, the creature alive — and after that the same shield
    does nothing and the Skeletons die."""
    incinerates = [set_pool("ICE")["Incinerate"]] * (2 if second_incinerate else 1)
    game = _table(set_pool, [
        set_pool("DST")["Test of Faith"], *incinerates,
        set_pool("M21")["Finishing Blow"],
    ])
    skeletons = _skeletons(game, set_pool)

    _cast(game, "Test of Faith", skeletons)
    _cast(game, "Incinerate", skeletons)
    assert skeletons.damage_marked == 0
    assert counters_on(skeletons, "+1/+1") == 3
    if second_incinerate:
        _cast(game, "Incinerate", skeletons)
        assert game.is_on_battlefield(skeletons)
        assert skeletons.damage_marked == 3

    _regenerate_then_destroy(game, skeletons)

    graveyard = [card.name for card in game.players[0].graveyard]
    if second_incinerate:
        assert not game.is_on_battlefield(skeletons)
        assert "Drudge Skeletons" in graveyard
    else:
        assert game.is_on_battlefield(skeletons)
        assert skeletons.tapped
        assert "Drudge Skeletons" not in graveyard


@pytest.mark.cr("615.1a", "701.19c")
def test_disintegrates_ban_is_the_spells_and_survives_prevention(set_pool):
    """The other reading, held apart: Disintegrate's ban is on the target
    whatever the damage did (its 2004-10-04 ruling), so the same prevented
    board ends with the Skeletons exiled by its other rider ("if it would die
    this turn, exile it instead") rather than regenerated."""
    game = _table(set_pool, [
        set_pool("DST")["Test of Faith"], set_pool("LEA")["Disintegrate"],
        set_pool("M21")["Finishing Blow"],
    ])
    skeletons = _skeletons(game, set_pool)

    _cast(game, "Test of Faith", skeletons)
    _cast(game, "Disintegrate", skeletons, x_value=3)
    assert skeletons.damage_marked == 0
    assert counters_on(skeletons, "+1/+1") == 3

    _regenerate_then_destroy(game, skeletons)

    assert not game.is_on_battlefield(skeletons)
    assert "Drudge Skeletons" in [card.name for card in game.players[0].exile]
    assert "Drudge Skeletons" not in [card.name for card in game.players[0].graveyard]
