"""Regression: a chosen target survives the battlefield renumbering under it.

`player.battlefield` is a list, so a permanent leaving shifts every later slot
down by one. Anything holding an index across that shift addresses a *different*
permanent — and a spell on the stack is exactly that: it waits for priority, for
responses, and for everything above it to resolve, any of which can remove a
permanent.

The engine's answer is `Permanent.permanent_id`, stamped at `Game._stack_push`
when the target is chosen (CR 601.2c) and read back through
`Game.chosen_permanent`. These tests drive the renumbering deliberately and
assert the *right* permanent is hit.

They are written to fail on the old code: each has a distractor permanent in a
lower slot that dies while the spell is on the stack, so the index the caster
chose now names its neighbour. An index-only engine hits the neighbour and
reports success, which is the silent-wrongness this repo's first standing
invariant forbids — not a crash, not an error, just the wrong creature dying.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from tests.helpers import CARDS_BY_NAME as CARDS, _game


def _put(game: Game, seat: int, name: str) -> Permanent:
    """Put a permanent onto the battlefield through the engine, so it is
    stamped with an id the way a real entry would be."""
    permanent = Permanent(card=CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, seat)
    return permanent


def _kill(game: Game, permanent: Permanent) -> None:
    """Remove *permanent* the way a game does — lethal damage, then CR 704.5g.

    Not ``_permanent_to_graveyard``: that records the arrival in the graveyard
    and leaves the battlefield list to its caller, so using it here would leave
    the slots un-renumbered and the test would pass without ever exercising the
    thing it is about.
    """
    permanent.damage_marked = 99
    game.check_state_based_actions()


def test_damage_hits_the_creature_it_targeted_after_an_earlier_one_dies():
    """Lightning Bolt at slot 1; slot 0 dies first, so slot 1 becomes slot 0.

    Craw Wurm (6/4) rather than a 3-toughness creature on purpose: the bolt has
    to leave its damage *marked* and visible. A creature the bolt kills would
    make the assertion unreadable — a dead target proves nothing about which
    target was chosen.
    """
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    doomed = _put(game, 1, "Grizzly Bears")
    intended = _put(game, 1, "Craw Wurm")
    assert game.battlefield_index_of(intended) == 1

    game.players[0].hand.append(CARDS["Lightning Bolt"])
    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=1)

    # The distractor leaves while the spell is on the stack; Hill Giant slides
    # into slot 0, so the recorded index now names the wrong creature.
    _kill(game, doomed)
    assert game.battlefield_index_of(intended) == 0

    game.resolve_stack()

    assert intended.damage_marked == 3, (
        "the bolt did not hit the creature it targeted — it followed the index "
        "into the slot vacated by the creature that died"
    )


def test_an_aura_attaches_to_the_creature_it_targeted():
    """The longest gap in the engine between choosing a target and using it."""
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    doomed = _put(game, 1, "Grizzly Bears")
    intended = _put(game, 1, "Hill Giant")

    game.players[0].hand.append(CARDS["Weakness"])
    game.queue_from_hand(0, "Weakness", target_player_index=1, target_permanent_index=1)

    _kill(game, doomed)
    game.resolve_stack()

    aura = next(
        perm for perm in game.all_permanents() if perm.card.name == "Weakness"
    )
    attached = aura.metadata.get("attached_to")
    assert attached is intended, (
        f"Weakness attached to {getattr(attached, 'card', None)} rather than the "
        "creature it targeted — the Aura followed a stale index"
    )


def test_the_id_is_what_makes_it_work_not_the_index():
    """Pin the mechanism, so a future change that drops the id but happens to
    keep these passing (because the index still lines up) is still caught."""
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    first = _put(game, 1, "Grizzly Bears")
    second = _put(game, 1, "Hill Giant")

    assert first.permanent_id != second.permanent_id
    assert game.permanent_by_id(second.permanent_id) is second

    _kill(game, first)

    # `second` has slid into slot 0, so index 1 is empty: the index the caster
    # chose has no answer at all now, while the id still names `second`.
    assert game.permanent_by_id(second.permanent_id) is second
    assert game.chosen_permanent(1, 1, second.permanent_id) is second
    assert game.chosen_permanent(1, 1, None) is None, (
        "slot 1 is empty now — the index alone has no answer, which is the "
        "whole reason the id is recorded"
    )
