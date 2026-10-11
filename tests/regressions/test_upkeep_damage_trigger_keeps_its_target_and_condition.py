"""An upkeep damage trigger that prints a **target** or an **intervening "if"**
goes on the stack as itself.

The upkeep step keeps a small registry of pay-or-consequence handlers, and two
of its rows — ``(upkeep_self, deal_damage)`` and ``(upkeep_each, deal_damage)``
— read a number off the instruction and queued a bare damage event at the
player whose upkeep it was. That is the whole of Juzám Djinn. It is not the
whole of a card that prints more:

* **a target.** Scalding Tongs and Thumbscrews ("…deals 1 damage to target
  opponent or planeswalker") dealt their damage to their *own controller*, and
  Spiteful Bully ("…deals 3 damage to target creature you control") dealt its
  three to its controller's face.
* **an intervening "if".** CR 603.4 checks it as the ability triggers *and
  again as it resolves*. The queued event carried no condition, so the second
  check was never made: Misers' Cage, Paupers' Cage, Kezzerdrix, Rivalry,
  Sarcomancy and Urborg Stalker all dealt their damage after the condition had
  been answered in response.

Found driving Apocalypse's Mask of Intolerance, which is the tenth card of the
second kind. Both are declined by the registry now and resolve through the
ordinary trigger path, where CR 603.3d chooses the target and the gate is
re-asked.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack

_SETS = ("TMP", "NEM", "MIR", "ULG", "WTH", "LEA")


def _find(set_pool, name):
    for code in _SETS:
        found = set_pool(code).get(name)
        if found is not None:
            return found
    raise KeyError(name)


def _table(set_pool, mine=(), theirs=(), hand=0, their_hand=0, interactive=False):
    forest = _find(set_pool, "Forest")
    game = Game(players=[
        PlayerState(name="A", hand=[forest] * hand),
        PlayerState(name="B", hand=[forest] * their_hand),
    ])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats.add(0)
    rows = []
    for seat, names in enumerate((mine, theirs)):
        row = []
        for name in names:
            permanent = Permanent(card=_find(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(permanent)
        rows.append(row)
    resolve_stack(game)  # an entry trigger (Sarcomancy's Zombie) is not the subject
    return game, rows[0], rows[1]


def _upkeep(game, seat=0, **answers):
    game.active_player_index = seat
    game.resolve_upkeep(seat, defer_priority=True, **answers)
    return [item.card.name for item in game.stack]


# ---------------------------------------------------------------------------
# A printed target
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name, hand", [("Scalding Tongs", 3), ("Thumbscrews", 5)])
def test_the_damage_goes_to_the_opponent_the_trigger_targets(set_pool, name, hand):
    """"…this artifact deals 1 damage to **target opponent or planeswalker**."
    The opponent, chosen as the trigger goes on the stack — it used to be the
    artifact's own controller who took it."""
    game, _mine, _theirs = _table(set_pool, mine=[name], hand=hand, interactive=True)

    assert _upkeep(game) == [name]
    (prompt,) = game.pending_choices
    assert prompt.kind == "trigger_target"
    assert [(entry["kind"], entry["seat"]) for entry in prompt.data["targets"]] == [
        ("player", 1),
    ]
    assert game.confirm_trigger_target(0, seat=1)
    resolve_stack(game)

    assert [player.life for player in game.players] == [20, 19]


@pytest.mark.parametrize("name, hand", [("Scalding Tongs", 4), ("Thumbscrews", 4)])
def test_the_hand_size_condition_still_decides_whether_it_triggers(set_pool, name, hand):
    game, _mine, _theirs = _table(set_pool, mine=[name], hand=hand)

    assert _upkeep(game) == []
    assert [player.life for player in game.players] == [20, 20]


def test_spiteful_bully_hits_a_creature_its_controller_controls(set_pool):
    """"…deals 3 damage to **target creature you control**." A creature, and
    one of its controller's: the upkeep prompt offers those and no other, the
    answer is the creature damaged, and no player loses life."""
    game, mine, theirs = _table(
        set_pool, mine=["Spiteful Bully", "Craw Wurm"], theirs=["Hill Giant"],
    )
    bully, wurm = mine

    (prompt,) = game.get_upkeep_target_triggers(0)
    assert prompt["mandatory"] and [t["name"] for t in prompt["valid_targets"]] == [
        "Spiteful Bully", "Craw Wurm",
    ]
    assert _upkeep(
        game, trigger_targets={bully.permanent_id: (0, game.battlefield_index_of(wurm))},
    ) == ["Spiteful Bully"]
    resolve_stack(game)

    assert wurm.damage_marked == 3
    assert bully.damage_marked == 0 and theirs[0].damage_marked == 0
    assert [player.life for player in game.players] == [20, 20]


def test_spiteful_bully_alone_is_its_own_only_target(set_pool):
    """With no other creature of its controller's, the mandatory trigger has
    one legal target — the Bully (CR 603.3d) — and three damage kills a 3/3."""
    game, mine, _theirs = _table(set_pool, mine=["Spiteful Bully"], theirs=["Hill Giant"])

    assert _upkeep(game) == ["Spiteful Bully"]
    resolve_stack(game)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(mine[0])
    assert [player.life for player in game.players] == [20, 20]


# ---------------------------------------------------------------------------
# An intervening "if", asked again on resolution (CR 603.4)
# ---------------------------------------------------------------------------


def test_misers_cage_does_nothing_once_the_hand_is_small_enough(set_pool):
    """"…if that player has five or more cards in hand, … deals 2 damage to
    that player." On the stack over five cards; the player is down to four by
    the time it resolves."""
    game, _mine, _theirs = _table(set_pool, mine=["Misers' Cage"], their_hand=5)
    assert _upkeep(game, seat=1) == ["Misers' Cage"]
    resolve_stack(game)
    assert [player.life for player in game.players] == [20, 18]

    game, _mine, _theirs = _table(set_pool, mine=["Misers' Cage"], their_hand=5)
    assert _upkeep(game, seat=1) == ["Misers' Cage"]
    game.players[1].hand.pop()
    resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]
    assert "Misers' Cage ability did nothing: its condition is no longer true" in game.log


def test_paupers_cage_does_nothing_once_the_hand_has_grown(set_pool):
    game, _mine, _theirs = _table(set_pool, mine=["Paupers' Cage"], their_hand=2)
    assert _upkeep(game, seat=1) == ["Paupers' Cage"]
    game.players[1].hand.append(_find(set_pool, "Forest"))
    resolve_stack(game)

    assert [player.life for player in game.players] == [20, 20]


def test_kezzerdrix_does_nothing_once_an_opponent_has_a_creature(set_pool):
    """"…if your opponents control no creatures, this creature deals 4 damage
    to you." A creature arrives across the table in response."""
    game, _mine, _theirs = _table(set_pool, mine=["Kezzerdrix"])
    assert _upkeep(game) == ["Kezzerdrix"]
    resolve_stack(game)
    assert [player.life for player in game.players] == [16, 20]

    game, _mine, _theirs = _table(set_pool, mine=["Kezzerdrix"])
    assert _upkeep(game) == ["Kezzerdrix"]
    game._put_permanent_onto_battlefield(
        1, Permanent(card=_find(set_pool, "Hill Giant")), None
    )
    resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]


def test_urborg_stalker_does_nothing_once_the_nonblack_permanent_is_gone(set_pool):
    """"…if that player controls a nonblack, nonland permanent, this creature
    deals 1 damage to that player." The opponent's Hill Giant is the condition
    on their upkeep, and it leaves in response."""
    game, _mine, theirs = _table(set_pool, mine=["Urborg Stalker"], theirs=["Hill Giant"])
    assert _upkeep(game, seat=1) == ["Urborg Stalker"]
    resolve_stack(game)
    assert [player.life for player in game.players] == [20, 19]

    game, _mine, theirs = _table(set_pool, mine=["Urborg Stalker"], theirs=["Hill Giant"])
    assert _upkeep(game, seat=1) == ["Urborg Stalker"]
    game.remove_from_battlefield(theirs[0])
    resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]


def test_sarcomancy_does_nothing_once_a_zombie_is_back(set_pool):
    """"…if there are no Zombies on the battlefield, this enchantment deals 1
    damage to you." The token is gone at the trigger; a Zombie is on the
    battlefield again when it resolves."""
    game, _mine, _theirs = _table(set_pool, mine=["Sarcomancy"])
    for token in [p for p in game.controlled_by(0) if p.card.name != "Sarcomancy"]:
        game.remove_from_battlefield(token)
    assert _upkeep(game) == ["Sarcomancy"]
    resolve_stack(game)
    assert [player.life for player in game.players] == [19, 20]

    game, _mine, _theirs = _table(set_pool, mine=["Sarcomancy"])
    for token in [p for p in game.controlled_by(0) if p.card.name != "Sarcomancy"]:
        game.remove_from_battlefield(token)
    assert _upkeep(game) == ["Sarcomancy"]
    game._put_permanent_onto_battlefield(
        1, Permanent(card=_find(set_pool, "Scathe Zombies")), None
    )
    resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]


def test_a_plain_upkeep_damage_row_is_untouched(set_pool):
    """The rows themselves stand: a trigger that prints neither a target nor
    a condition is still the registry's — Copper Tablet deals its 1 to each
    player on that player's upkeep, as it did."""
    game, _mine, _theirs = _table(set_pool, mine=["Copper Tablet"])

    assert _upkeep(game) == ["Copper Tablet"]
    resolve_stack(game)
    assert _upkeep(game, seat=1) == ["Copper Tablet"]
    resolve_stack(game)

    assert [player.life for player in game.players] == [19, 19]
