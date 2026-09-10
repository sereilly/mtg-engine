"""CR 601.2c / 602.2b: what an announcement made by object identity says.

CR 115.1c has an activated ability's targets chosen *as it is activated*, and
CR 602.2b sends that choice through CR 601.2c — "the player announces their
choice of an appropriate object … The chosen objects each become a target".
The rule is about an **object**, not about a battlefield and a slot: CR 400.7
makes a permanent one object for one stay on the battlefield, and naming it is
the whole announcement.

The engine's spelling of "that object" is ``Permanent.permanent_id``, so an
announcement carrying ids and nothing else is complete by the rule. These tests
say what "complete" has to mean downstream: the permanent named is the permanent
affected, whichever seat it belongs to, and the one that was not named is not.

Written on Icy Manipulator because its printed line ("Tap target artifact,
creature, or land") is the flattest in the pool — the effect is observable in one
boolean, so nothing between the announcement and the answer can absorb a wrong
target and still look right.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent

from ..helpers import _mk_card, _nosick


def _creature(name: str) -> Permanent:
    return _nosick(
        Permanent(card=_mk_card(name=name, type_line="Creature - Human", power=1, toughness=1))
    )


def _board(cards, *, mine: int = 1, theirs: int = 1):
    """Icy Manipulator plus *mine* creatures for its controller and *theirs* for
    the opponent, all identical.

    Identical on purpose: a resolver that ignored the announcement and scanned
    would be choosing between permanents nothing else distinguishes, so the
    assertion below can only be satisfied by the announcement itself.
    """
    manipulator = _nosick(Permanent(card=cards["Icy Manipulator"]))
    ours = [_creature(f"Ours {i}") for i in range(mine)]
    yours = [_creature(f"Theirs {i}") for i in range(theirs)]
    p1 = PlayerState(name="P1", battlefield=[manipulator] + ours, life=20)
    p2 = PlayerState(name="P2", battlefield=list(yours), life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, manipulator, ours, yours


@pytest.mark.cr("115.1c", "602.2b", "601.2c")
def test_an_activation_aimed_at_its_own_side_taps_the_permanent_it_named(cards):
    """"{1}, {T}: Tap target artifact, creature, or land."

    CR 115.1c chooses the target as the ability is activated and CR 601.2c makes
    the named object *the* target. A seat is no part of that announcement — the
    id already knows which battlefield it is on — so naming one and nothing else
    has to be enough.

    It was not. The engine defaulted the unsaid seat to the opponent's before the
    ability reached the stack, and the resolver scoped its id lookup to that
    seat, so the choice was discarded and a scan beneath it tapped whatever it
    met first. Nothing crashed; the ability logged that it resolved.
    """
    game, _manipulator, ours, theirs = _board(cards)

    result = game.activate_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[ours[0].permanent_id]
    )
    game._settle()

    assert result.supported, result.details
    assert ours[0].tapped, game.log
    assert not theirs[0].tapped, game.log


@pytest.mark.cr("601.2c")
def test_only_the_announced_permanent_is_affected(cards):
    """"The chosen objects and/or players each become a target of that spell."

    The other half of the same sentence, and the half a scan can satisfy by
    accident: with one eligible permanent per seat, a resolver that took the
    first thing it found on the *right* board would still pass the test above.
    Three identical creatures on the activator's own side leave it nowhere to
    hide — only the one that was named may be tapped.
    """
    game, _manipulator, ours, _theirs = _board(cards, mine=3)

    game.activate_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[ours[2].permanent_id]
    )
    game._settle()

    assert [p.tapped for p in ours] == [False, False, True], game.log


@pytest.mark.cr("400.7")
def test_the_announcement_survives_the_battlefield_renumbering_under_it(cards):
    """"An object that moves from one zone to another becomes a new object."

    Which is why the announcement is an id and not a slot. The distractor sits
    *before* the named creature and leaves while the ability is on the stack, so
    every later slot shifts down by one and the index the activator would have
    given now names its neighbour. The id still names the creature that was
    chosen, on the activator's own battlefield — the seat and the identity
    settled by the same announcement.
    """
    game, _manipulator, ours, _theirs = _board(cards, mine=2)
    distractor, named = ours

    game.activate_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[named.permanent_id]
    )
    game.remove_from_battlefield(distractor)
    game._settle()

    assert named.tapped, game.log


@pytest.mark.cr("608.2b")
def test_an_announced_target_that_has_left_is_not_replaced_by_a_scan(cards):
    """"A target that's no longer in the zone it was in when it was targeted is
    illegal … If all its targets … are now illegal, the spell or ability doesn't
    resolve."

    The guard on the other side of the fix. Settling the seat from the ids makes
    the resolver's id lookup succeed far more often, and the temptation is to
    read that as "the id is now trusted". It is not: an id recorded and no longer
    resolving is CR 608.2b, and the answer is nothing at all. With the seat now
    correct, a resolver that fell back here would find the survivor standing
    beside the departed creature and tap that instead — the same silent
    wrongness in a new place.
    """
    game, _manipulator, ours, _theirs = _board(cards, mine=2)
    named, survivor = ours

    game.activate_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[named.permanent_id]
    )
    game.remove_from_battlefield(named)
    game._settle()

    assert not survivor.tapped, game.log
