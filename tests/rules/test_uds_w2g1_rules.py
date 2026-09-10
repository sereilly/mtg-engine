"""Rules tests earned by Urza's Destiny wave 2, group 1 — a **player** as one
role of a several-target announcement.

Donate ("Target player gains control of target permanent you control") is the
pool's first spell whose targets are of two different *kinds* and one of them is
a seat. Everything about a several-role announcement already existed — the
ordered roles description, the depth-first walk the picker and the announcement
gate share, the CR 601.2c distinctness that falls out of it — and all of it
assumed a role's object was on a battlefield or in a graveyard.

Three CR subjects, one per thing the seat had to learn:

* **CR 601.2c** — every target of a spell is announced as it is cast, and the
  announcement is legal or the spell is not cast. A roles walk answers *every*
  role; a player is now one of the answers it can give.
* **CR 115.3** — the same target cannot answer one instance of the word
  "target" twice. A seat and a permanent are never the same object, so the rule
  is silent between these two roles and must stay silent: a keying scheme that
  collided them would refuse a legal Donate.
* **CR 611.2a** / **CR 613.1b** — what the spell then does. A control change is
  a layer-2 contribution with no stated duration, so it lasts until the end of
  the game, and ``base_controller_index`` is never rewritten by it.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_cards, manifest_set_paths
from engine.control import end_control_change
from engine.models import Permanent, PlayerState

from tests.helpers import resolve_stack


def _w2g1r_catalog():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _w2g1r_duel(*, seats=2, mine="Grizzly Bears", theirs=None):
    """Seat 0 holding Donate with one permanent out, and *seats* players.

    Three seats where the test asks about them, because "which player gains
    control?" is a question a duel answers by accident — the one opponent is
    the only answer a wrong implementation could give.
    """
    pool = _w2g1r_catalog()
    players = [
        PlayerState(
            name="P0", life=20, hand=[pool["Donate"]],
            battlefield=[Permanent(card=pool[mine])],
        )
    ]
    for index in range(1, seats):
        players.append(
            PlayerState(
                name=f"P{index}", life=20,
                battlefield=(
                    [Permanent(card=pool[theirs])] if theirs else []
                ),
            )
        )
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    return pool, game


@pytest.mark.cr("601.2c", "115.3")
def test_a_roles_announcement_can_name_a_player_for_one_of_its_slots():
    """CR 601.2c announces an object *or player* for each target the spell
    requires, and Donate requires one of each.

    The walk is the assertion rather than the cast: ``valid_targets`` is role
    0's list with each entry carrying under ``next`` what role 1 would then
    allow, and role 0's list being three seats is the whole of what "a player
    can be a role" means. CR 115.3 is silent between the two — a seat is not a
    permanent — so every seat keeps its full permanent list rather than losing
    one to a distinctness check that had collided them.
    """
    pool, game = _w2g1r_duel(seats=3)
    spec = game.cast_target_spec(0, pool["Donate"])

    assert spec["kind"] == "roles"
    assert [role["kind"] for role in spec["roles"]] == ["player", "permanent"]
    assert [entry["seat"] for entry in spec["valid_targets"]] == [0, 1, 2]
    assert all(entry["kind"] == "player" for entry in spec["valid_targets"])
    for entry in spec["valid_targets"]:
        assert [step["name"] for step in entry["next"]] == ["Grizzly Bears"]


@pytest.mark.cr("601.2c")
def test_the_permanent_role_is_narrowed_by_its_own_printed_phrase():
    """"…target permanent **you control**." The second role carries its own
    narrowing, and a walk that offered one shared list would hand the caster an
    opponent's permanent to give away.

    Measured against a board where the opponent has one, which is the only board
    that can tell the two readings apart.
    """
    pool, game = _w2g1r_duel(theirs="Hill Giant")
    spec = game.cast_target_spec(0, pool["Donate"])

    offered = {
        (step["seat"], step["name"])
        for entry in spec["valid_targets"] for step in entry["next"]
    }
    assert offered == {(0, "Grizzly Bears")}


@pytest.mark.cr("601.2c")
def test_a_caster_with_no_permanent_has_no_legal_announcement():
    """CR 601.2c fills every role or the spell is not cast. With nothing to
    give, role 1 is empty for every seat — and the walk drops a role 0 choice
    that leaves a later role with nothing, so the whole list is empty rather
    than being a set of first clicks that dead-end."""
    pool = _w2g1r_catalog()
    game = Game(players=[
        PlayerState(name="P0", life=20, hand=[pool["Donate"]]),
        PlayerState(name="P1", life=20,
                    battlefield=[Permanent(card=pool["Hill Giant"])]),
    ])
    game.enforce_mana_costs = False
    game._sync_control()

    assert game.cast_target_spec(0, pool["Donate"])["valid_targets"] == []


@pytest.mark.cr("611.2a", "613.1b")
def test_the_named_seat_gains_control_for_as_long_as_the_game_lasts():
    """CR 613.1b's layer-2 contribution with CR 611.2a's duration: the spell
    states none, so it lasts until the end of the game.

    Three seats, so "the seat the announcement named" and "the seat that is not
    the caster" are different answers. The named seat is the *second* opponent.
    """
    pool, game = _w2g1r_duel(seats=3)
    (bears,) = game.players[0].battlefield
    permanent_id = game.permanent_id_of(bears)

    result = game.cast_from_hand(
        0, "Donate", target_player_index=2,
        target_permanent_ids=[None, permanent_id],
    )
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert game.controller_index_of(bears) == 2
    assert [p.card.name for p in game.players[2].battlefield] == ["Grizzly Bears"]
    assert game.players[0].battlefield == []
    # Nothing about the turn ends it: cleanup drops only the contributions
    # stamped until-end-of-turn (CR 611.2a).
    game.resolve_cleanup_step(0)
    assert game.controller_index_of(bears) == 2


@pytest.mark.cr("613.1b")
def test_the_gift_leaves_ownership_where_it_was():
    """A control change is a contribution and not a move (CR 613.1b), so ending
    it hands the permanent back — which is the observable form of
    ``base_controller_index`` never being rewritten. CR 108.3's owner is read
    off that same seat.
    """
    pool, game = _w2g1r_duel()
    (bears,) = game.players[0].battlefield
    donate = pool["Donate"]

    game.cast_from_hand(
        0, "Donate", target_player_index=1,
        target_permanent_ids=[None, game.permanent_id_of(bears)],
    )
    resolve_stack(game)
    assert game.controller_index_of(bears) == 1

    end_control_change(bears, source=donate)
    game._sync_control()
    assert game.controller_index_of(bears) == 0
