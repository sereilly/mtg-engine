"""CR 608.2b for a spell whose announcement is several roles, one of them a
player.

"**Target player** gains control of **target permanent** you control."
(Donate.) "…deals 2 damage to **target creature** and 2 damage to **target
player** or planeswalker." (Lunge; Shower of Sparks.) The word is printed
twice and each instance has its own legality, so the rule has two halves here:

* an illegal target "won't be affected" while the rest of the spell still
  happens — a player who gained shroud in response is not handed the permanent
  and is not dealt the damage, and the creature still is;
* and if **every** target is illegal the spell doesn't resolve.

Neither was asked of a role that names a player. The only thing a named player
was held to at resolution was not having left the game, and the whole-object
half was declined outright because one of the targets "may be a player": with
Ivory Mask put down in response, Donate handed over the permanent and Lunge
dealt its 2 to the masked player, and with the creature gone as well Lunge
still resolved and still dealt them.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack

_BURN = (("Lunge", 2), ("Shower of Sparks", 1))


def _duel(pool, spell: str) -> Game:
    game = Game(players=[
        PlayerState("A", library=[pool["Forest"]] * 10, hand=[pool[spell]]),
        PlayerState("B", library=[pool["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    return game


def _put(game, pool, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=pool[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _mask(game, pool) -> None:
    """"You have shroud." — put down in response, under the named player."""
    _put(game, pool, 1, "Ivory Mask")


def _leave(game, permanent) -> None:
    owner = game.players[game.controller_index_of(permanent)]
    game.remove_from_battlefield(permanent)
    game._permanent_to_graveyard(owner, permanent)


def _cast_burn(game, pool, spell: str):
    giant = _put(game, pool, 1, "Hill Giant")
    assert game.queue_from_hand(
        0, spell, target_player_index=1, target_permanent_ids=[giant.permanent_id, None],
    ).supported
    return giant


@pytest.mark.cr("608.2b")
@pytest.mark.parametrize("spell,damage", _BURN)
def test_608_2b_a_player_who_gained_shroud_is_not_dealt_the_damage(
    catalog_by_name, spell, damage,
):
    game = _duel(catalog_by_name, spell)
    giant = _cast_burn(game, catalog_by_name, spell)
    _mask(game, catalog_by_name)

    resolve_stack(game)

    assert game.players[1].life == 20, "an illegal target is not affected"
    assert giant.damage_marked == damage, "and the legal one still is"
    assert f"{spell} resolved and moved to graveyard" in game.log[-1]


@pytest.mark.cr("608.2b")
@pytest.mark.parametrize("spell,damage", _BURN)
def test_608_2b_the_player_is_still_dealt_damage_when_only_the_creature_left(
    catalog_by_name, spell, damage,
):
    game = _duel(catalog_by_name, spell)
    giant = _cast_burn(game, catalog_by_name, spell)
    _leave(game, giant)

    resolve_stack(game)

    assert game.players[1].life == 20 - damage
    assert f"{spell} resolved and moved to graveyard" in game.log[-1]


@pytest.mark.cr("608.2b")
@pytest.mark.parametrize("spell,damage", _BURN)
def test_608_2b_with_every_target_illegal_the_spell_does_not_resolve(
    catalog_by_name, spell, damage,
):
    game = _duel(catalog_by_name, spell)
    giant = _cast_burn(game, catalog_by_name, spell)
    _mask(game, catalog_by_name)
    _leave(game, giant)

    resolve_stack(game)

    assert game.players[1].life == 20
    assert any("every target is illegal (608.2b)" in line for line in game.log[-3:])
    assert [card.name for card in game.players[0].graveyard] == [spell]


@pytest.mark.cr("608.2b")
@pytest.mark.parametrize("spell,damage", _BURN)
def test_608_2b_with_both_targets_legal_the_spell_does_all_of_itself(
    catalog_by_name, spell, damage,
):
    """The control: the re-check refuses nothing it should not."""
    game = _duel(catalog_by_name, spell)
    giant = _cast_burn(game, catalog_by_name, spell)

    resolve_stack(game)

    assert game.players[1].life == 20 - damage and giant.damage_marked == damage


def _cast_donate(game, pool):
    bears = _put(game, pool, 0, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Donate", target_player_index=1, target_permanent_ids=[None, bears.permanent_id],
    ).supported
    return bears


@pytest.mark.cr("608.2b")
def test_608_2b_donate_gives_nothing_to_a_player_who_gained_shroud(catalog_by_name):
    game = _duel(catalog_by_name, "Donate")
    bears = _cast_donate(game, catalog_by_name)
    _mask(game, catalog_by_name)

    resolve_stack(game)

    assert game.controller_index_of(bears) == 0
    # One of its two targets is still legal, so it resolves — and does nothing,
    # because the two halves of its sentence are one effect.
    assert "Donate resolved and moved to graveyard" in game.log[-1]


@pytest.mark.cr("608.2b")
def test_608_2b_donate_with_both_targets_illegal_does_not_resolve(catalog_by_name):
    game = _duel(catalog_by_name, "Donate")
    bears = _cast_donate(game, catalog_by_name)
    _mask(game, catalog_by_name)
    _leave(game, bears)

    resolve_stack(game)

    assert any("every target is illegal (608.2b)" in line for line in game.log[-3:])


@pytest.mark.cr("608.2b")
def test_608_2b_donate_still_gives_the_permanent_to_a_legal_player(catalog_by_name):
    """The control."""
    game = _duel(catalog_by_name, "Donate")
    bears = _cast_donate(game, catalog_by_name)

    resolve_stack(game)

    assert game.controller_index_of(bears) == 1
