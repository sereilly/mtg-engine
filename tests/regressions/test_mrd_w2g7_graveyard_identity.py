"""Two copies of one card in one graveyard are two objects (CR 400.7).

A deck repeats one immutable ``CardDefinition`` per copy, so until Mirrodin's
wave 2 an old Grizzly Bears and one that died this turn were **one object at
two positions** of a graveyard, and every record about a card there answered
for whichever copy came first. ``Game.put_card_into_graveyard`` now makes a
copy arriving as an object some graveyard holds a new, equal one, and returns
the object the pile holds (``tests/engine/test_graveyard_arrival_identity.py``
guards the invariant). These are the boards each reader was wrong on, every
one driven through the engine's own entry points:

* **No Rest for the Wicked** (USG, shipped) returned the old Bears after Raise
  Dead took back the one that died — "put there from the battlefield this
  turn" was a count of entries over one object.
* **Enduring Renewal** (ICE) returned "it" by identity and took the old copy,
  leaving the one that died in the pile for that record to name.
* **Recoup** (ODY) granted flashback to an object, which covered both copies.
* **Planar Void** (USG) dying in a sweep beside an older copy now lands as a
  new object, which its "another" must still know is itself.
* Two roads reached a graveyard around the seam through a computed zone name:
  **Gravegouger**'s return of its exiled cards (and Knowledge Vault's,
  Gustha's Scepter's, Duplicity's) and **Vexing Arcanix**'s miss (and Petra
  Sphinx's) — Planar Void never heard of those cards.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_weighed_cast import permitted_casts
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack


@pytest.fixture
def pool(set_pool):
    merged: dict = {}
    for code in ("LEA", "ICE", "USG", "ODY", "TOR", "MRD"):
        merged.update(set_pool(code))
    return merged


def _table(pool, *, hand=(), mine=(), graveyard=(), library=None):
    game = Game(players=[
        PlayerState(
            "A", hand=[pool[n] for n in hand],
            library=[pool[n] for n in (library or ["Forest"] * 12)],
        ),
        PlayerState("B", library=[pool["Island"]] * 12),
    ])
    game.enforce_mana_costs = False
    placed = []
    for name in mine:
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        _nosick(permanent)
        placed.append(permanent)
    game.start_turn(0)
    game._settle()
    # Through the seam, as a card that died on an earlier turn got there.
    for name in graveyard:
        game.put_card_into_graveyard(0, pool[name])
    return game, placed


def _names(cards):
    return [card.name for card in cards]


def _bolt_then_raise_the_newest(game, bears):
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    resolve_stack(game)
    game._settle()
    pile = game.players[0].graveyard
    newest = max(i for i, card in enumerate(pile) if card.name == "Grizzly Bears")
    assert pile[newest] is not pile[0], "the copy that died is its own object"
    assert game.queue_from_hand(
        0, "Raise Dead", target_permanent_index=newest, target_player_index=0,
    ).supported
    resolve_stack(game)
    assert _names(game.players[0].graveyard) == [
        "Grizzly Bears", "Lightning Bolt", "Raise Dead",
    ]


def test_no_rest_for_the_wicked_leaves_the_old_bears_when_the_new_one_was_raised(pool):
    game, (bears, _) = _table(
        pool, hand=["Lightning Bolt", "Raise Dead"],
        mine=["Grizzly Bears", "No Rest for the Wicked"],
        graveyard=["Grizzly Bears"],
    )
    _bolt_then_raise_the_newest(game, bears)
    assert game.activate_permanent_ability(0, "No Rest for the Wicked").supported
    resolve_stack(game)
    # The raised Bears only: the one left in the pile was put there before
    # this turn, so No Rest has nothing to return.
    assert _names(game.players[0].hand) == ["Grizzly Bears"]
    assert _names(game.players[0].graveyard) == [
        "Grizzly Bears", "Lightning Bolt", "Raise Dead", "No Rest for the Wicked",
    ]


def test_enduring_renewal_returns_the_copy_that_died(pool):
    # "Whenever a creature is put into your graveyard from the battlefield,
    # return it to your hand." "It" is the card that just arrived; with an old
    # copy beneath it the identity found the old one, and the copy that died
    # stayed for "put there from the battlefield this turn" to name.
    game, (_, bears) = _table(
        pool, hand=["Lightning Bolt", "Second Sunrise"],
        mine=["Enduring Renewal", "Grizzly Bears"], graveyard=["Grizzly Bears"],
    )
    old = game.players[0].graveyard[0]
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    resolve_stack(game)
    game._settle()
    resolve_stack(game)
    assert game.players[0].graveyard[0] is old
    assert _names(game.players[0].graveyard) == ["Grizzly Bears", "Lightning Bolt"]
    assert "Grizzly Bears" in _names(game.players[0].hand)
    # Nothing in the pile died this turn, so Second Sunrise returns nothing.
    assert game.queue_from_hand(0, "Second Sunrise").supported
    resolve_stack(game)
    game._settle()
    assert _names(p.card for p in game.controlled_by(0)) == ["Enduring Renewal"]
    assert "Second Sunrise: no cards to return" in game.log


def test_recoup_gives_flashback_to_the_copy_it_targets(pool):
    game, _ = _table(pool, hand=["Recoup"], graveyard=["Stone Rain", "Stone Rain"])
    pile = game.players[0].graveyard
    assert pile[0] is not pile[1]
    assert game.queue_from_hand(
        0, "Recoup", target_permanent_index=1, target_player_index=0,
    ).supported
    resolve_stack(game)
    granted = [p.spell for p in permitted_casts(game, 0) if p.spell.name == "Stone Rain"]
    assert len(granted) == 1 and granted[0] is pile[1]


def test_a_dying_planar_void_beside_an_older_copy_does_not_exile_itself(pool):
    # A sweep puts the Void into the graveyard while it is still a watcher, as
    # a new object (an older Void lies in the pile). "Another card" is every
    # card but its own, and its own is the permanent it was.
    game, _ = _table(
        pool, hand=["Tranquility"], mine=["Planar Void"], graveyard=["Planar Void"],
    )
    assert game.queue_from_hand(0, "Tranquility").supported
    resolve_stack(game)
    game._settle()
    resolve_stack(game)
    assert _names(game.players[0].graveyard) == [
        "Planar Void", "Planar Void", "Tranquility",
    ]
    assert game.players[0].exile == []


def test_gravegougers_return_reaches_the_graveyard_through_its_one_arrival(pool):
    # "When this creature leaves the battlefield, return the exiled cards to
    # their owner's graveyard." Planar Void sees them land.
    game, _ = _table(pool, hand=["Gravegouger", "Lightning Bolt"], mine=["Planar Void"])
    game.put_card_into_graveyard(1, pool["Grizzly Bears"])
    game.put_card_into_graveyard(1, pool["Hill Giant"])
    assert game.queue_from_hand(0, "Gravegouger").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert sorted(_names(game.players[1].exile)) == ["Grizzly Bears", "Hill Giant"]
    gouger = next(p for p in game.controlled_by(0) if p.card.name == "Gravegouger")
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[gouger.permanent_id],
    ).supported
    resolve_stack(game)
    game._settle()
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    game._settle()
    assert "Grizzly Bears, Hill Giant go to their owner's graveyard" in game.log
    assert "Planar Void exiled Grizzly Bears from B's graveyard" in game.log
    assert "Planar Void exiled Hill Giant from B's graveyard" in game.log
    assert game.players[1].graveyard == []


def test_vexing_arcanix_miss_reaches_the_graveyard_through_its_one_arrival(pool):
    # "Otherwise, they put it into their graveyard and this artifact deals 2
    # damage to them." The seat names its commonest card (Forest) and reveals
    # an Island.
    game, _ = _table(
        pool, mine=["Vexing Arcanix", "Planar Void"],
        library=["Island"] + ["Forest"] * 11,
    )
    assert game.activate_permanent_ability(
        0, "Vexing Arcanix", target_player_index=0,
    ).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert game.players[0].life == 18
    assert "Planar Void exiled Island from A's graveyard" in game.log
    assert _names(game.players[0].exile) == ["Island"]
