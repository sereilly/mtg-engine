"""Regression: combat keeps pointing at the creatures it meant.

Combat is recorded as **battlefield slots** — `combat_attackers` maps an
attacker index to a defending seat, `combat_blockers` maps a blocker index to
the attackers it blocks — and a slot is not a name. A creature dying in the
first-strike damage step shifts every later slot on its controller's battlefield
down by one, so an attacker recorded as index 3 silently becomes whatever index
3 is now.

`Game._renumber_combat_after_removal` runs from the single removal transition
and fixes both halves: an entry whose own creature left is dropped, and every
surviving entry shifts by the number of departing creatures ahead of it.

These tests drive the renumbering deliberately, because the AI simulation does
not reach it — the sim was byte-identical before and after the fix, which proves
the change is safe and proves nothing about whether it works. That is what these
are for.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from tests.helpers import CARDS_BY_NAME as CARDS, _game, _nosick


def _put(game: Game, seat: int, name: str) -> Permanent:
    """On the battlefield and able to act.

    `_nosick` has to run *after* the put: `_put_permanent_onto_battlefield`
    stamps `summoning_sickness_turn` itself, so clearing it beforehand is
    silently undone and every attack is refused with "cannot attack".
    """
    permanent = Permanent(card=CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, seat)
    return _nosick(permanent)


def _combat_game(board: list[tuple[int, str]]) -> tuple[Game, list[Permanent]]:
    """A game in the declare-attackers step, driven through the real turn flow.

    Not `_set_phase_and_step`: combat legality reads state that only
    `start_turn` establishes, and a hand-set phase produces a step in which
    nothing can attack.
    """
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    permanents = [_put(game, seat, name) for seat, name in board]
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    assert game.current_step == "declare_attackers"
    return game, permanents


def _kill(game: Game, permanent: Permanent) -> None:
    """Remove *permanent* through the one transition, without the rest of the
    state-based-action sweep — so these tests observe the renumbering itself
    rather than whatever else an SBA pass would do."""
    game.remove_from_battlefield(permanent)


def test_a_surviving_attacker_keeps_its_entry_when_an_earlier_one_dies():
    game, (doomed, survivor, _wall) = _combat_game(
        [(0, "Grizzly Bears"), (0, "Hill Giant"), (1, "Wall of Stone")]
    )
    assert game.declare_attackers(0, [0, 1], 1)[0]
    assert game.combat_attackers == {0: 1, 1: 1}

    _kill(game, doomed)

    assert game.battlefield_index_of(survivor) == 0
    assert game.combat_attackers == {0: 1}, (
        "the surviving attacker's entry did not follow it — combat still names "
        "the slot the dead creature vacated"
    )


def test_a_dead_attackers_entry_is_dropped_not_reassigned():
    """The other half: the entry must not survive pointing at a neighbour."""
    game, (attacker, bystander, _wall) = _combat_game(
        [(0, "Grizzly Bears"), (0, "Hill Giant"), (1, "Wall of Stone")]
    )
    assert game.declare_attackers(0, [0], 1)[0]
    assert game.combat_attackers == {0: 1}

    _kill(game, attacker)

    assert game.battlefield_index_of(bystander) == 0
    assert game.combat_attackers == {}, (
        "a dead attacker's entry was inherited by the creature that slid into "
        "its slot — a bystander is now attacking"
    )


def test_a_blocking_relation_survives_an_earlier_blocker_dying():
    game, (attacker, doomed_blocker, real_blocker) = _combat_game(
        [(0, "Hill Giant"), (1, "Grizzly Bears"), (1, "Wall of Stone")]
    )
    assert game.declare_attackers(0, [0], 1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0, 1: 0})[0]
    assert game.combat_blockers[1] == {0: [0], 1: [0]}

    _kill(game, doomed_blocker)

    assert game.battlefield_index_of(real_blocker) == 0
    assert game.combat_blockers[1] == {0: [0]}, (
        "the surviving blocker lost its block, or kept a slot that now names "
        "another creature"
    )
    assert game.battlefield_index_of(attacker) == 0


def test_a_blocker_stops_blocking_when_its_attacker_dies():
    game, (doomed_attacker, other_attacker, _blocker) = _combat_game(
        [(0, "Grizzly Bears"), (0, "Hill Giant"), (1, "Wall of Stone")]
    )
    assert game.declare_attackers(0, [0, 1], 1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    assert game.combat_blockers[1] == {0: [0]}

    _kill(game, doomed_attacker)

    assert game.battlefield_index_of(other_attacker) == 0
    assert game.combat_blockers.get(1, {}) == {}, (
        "the blocker is still recorded as blocking, and the attacker index it "
        "holds now names the creature that took the dead one's slot"
    )
    assert game.combat_attackers == {0: 1}


def test_attacker_piles_follow_their_attackers():
    """Raging River's left/right labels are keyed by attacker slot too."""
    game, (doomed, survivor, _wall) = _combat_game(
        [(0, "Grizzly Bears"), (0, "Hill Giant"), (1, "Wall of Stone")]
    )
    assert game.declare_attackers(0, [0, 1], 1)[0]
    game.combat_attacker_piles = {0: "left", 1: "right"}

    _kill(game, doomed)

    assert game.battlefield_index_of(survivor) == 0
    assert game.combat_attacker_piles == {0: "right"}, (
        "the surviving attacker's pile label did not follow it — it is now "
        "labelled with the dead creature's side"
    )


def test_removal_outside_combat_leaves_combat_state_alone():
    """The remap must not invent entries or disturb an empty combat."""
    game, (perm, _other) = _combat_game([(0, "Grizzly Bears"), (0, "Hill Giant")])

    assert game.combat_attackers == {}
    _kill(game, perm)
    assert game.combat_attackers == {}
    assert game.combat_blockers == {}
