"""CR 201.2a and CR 708.2a: what "the same name" means, and that a face-down
permanent has none (Darksteel W1G4).

CR 201.2a: "Two or more objects have the same name if they have at least one
name in common … An object with no name doesn't have the same name as any
other object, including another object with no name." CR 708.2a: a face-down
permanent is "a 2/2 face-down creature with no text, no name, no subtypes, and
no mana cost." The engine's face-down object carries a display label
(``face_down.FACE_DOWN_NAME``) that every face-down permanent shares, and every
"same name" reader compared ``effective_card.name`` — so two face-down
creatures had "the same name": Eye of Singularity destroyed both, Winnow
destroyed one, Chrome Replicator made a Construct off them. The readers now
ask ``face_down.permanent_name``, which is None for a face-down permanent.

Echoing Courage's own ruling (2018-03-16) states the face-down half: "A
face-down creature has no name, so it can't share a name with anything. This
includes other creatures with no name."
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.face_down import face_down_card
from engine.models import Permanent
from tests.helpers import settle


def _card(set_pool, name):
    for code in ("DST", "LEA", "VIS", "INV", "M21"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _table(set_pool, hand=()) -> Game:
    forest = set_pool("LEA")["Forest"]
    game = Game(players=[
        PlayerState("P1", hand=[_card(set_pool, n) for n in hand], library=[forest] * 20),
        PlayerState("P2", library=[forest] * 20),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game


def _put(game: Game, seat: int, card, *, face_down: bool = False) -> Permanent:
    permanent = Permanent(card=face_down_card(card) if face_down else card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _board(game: Game) -> list[str]:
    return sorted(p.card.name for p in game.all_permanents())


@pytest.mark.cr("201.2a", "708.2a")
def test_echoing_courage_on_a_face_down_creature_pumps_it_alone(set_pool):
    """The ruling's case: the target gets +2/+2 and the other face-down
    creature, with no name to share, gets nothing."""
    game = _table(set_pool, ["Echoing Courage"])
    bears = _card(set_pool, "Grizzly Bears")
    target = _put(game, 0, bears, face_down=True)
    other = _put(game, 0, bears, face_down=True)
    assert game.cast_from_hand(
        0, "Echoing Courage", target_permanent_ids=[target.permanent_id],
    ).supported
    settle(game)
    assert (target.effective_power, target.effective_toughness) == (4, 4)
    assert (other.effective_power, other.effective_toughness) == (2, 2)


@pytest.mark.cr("201.2a", "708.2a")
def test_echoing_truth_on_a_face_down_creature_returns_it_alone(set_pool):
    """Two face-down Grizzly Bears are not namesakes: Echoing Truth returns the
    one it targeted (revealed as it leaves, CR 708.9) and leaves the other."""
    game = _table(set_pool, ["Echoing Truth"])
    bears = _card(set_pool, "Grizzly Bears")
    target = _put(game, 1, bears, face_down=True)
    other = _put(game, 1, bears, face_down=True)
    assert game.cast_from_hand(
        0, "Echoing Truth", target_permanent_ids=[target.permanent_id],
    ).supported
    settle(game)
    assert not game.is_on_battlefield(target)
    assert game.is_on_battlefield(other)
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]


@pytest.mark.cr("201.2a", "708.2a")
def test_eye_of_singularity_spares_face_down_creatures(set_pool):
    """"When this enchantment enters, destroy each permanent with the same name
    as another permanent, except for basic lands." The two Grizzly Bears die;
    the two face-down creatures have no name and stay."""
    game = _table(set_pool, ["Eye of Singularity"])
    bears = _card(set_pool, "Grizzly Bears")
    _put(game, 0, bears)
    _put(game, 1, bears)
    _put(game, 0, bears, face_down=True)
    _put(game, 1, bears, face_down=True)
    assert game.cast_from_hand(0, "Eye of Singularity").supported
    settle(game)
    assert _board(game) == [
        "Eye of Singularity", "Face-down creature", "Face-down creature",
    ]


@pytest.mark.cr("201.2a", "708.2a")
def test_winnow_does_not_see_a_namesake_for_a_face_down_target(set_pool):
    """"Destroy target nonland permanent if another permanent with the same
    name is on the battlefield." Another face-down creature is not one, so the
    face-down target survives (the card is still drawn); a Grizzly Bears
    beside another Bears is destroyed."""
    game = _table(set_pool, ["Winnow", "Winnow"])
    bears = _card(set_pool, "Grizzly Bears")
    hidden = _put(game, 1, bears, face_down=True)
    _put(game, 1, bears, face_down=True)
    named = _put(game, 1, bears)
    _put(game, 0, bears)
    assert game.cast_from_hand(0, "Winnow", target_permanent_ids=[hidden.permanent_id]).supported
    settle(game)
    assert game.is_on_battlefield(hidden)
    assert game.cast_from_hand(0, "Winnow", target_permanent_ids=[named.permanent_id]).supported
    settle(game)
    assert not game.is_on_battlefield(named)


@pytest.mark.cr("201.2a", "708.2a")
def test_chrome_replicator_counts_no_face_down_pair(set_pool):
    """"…if you control two or more nonland, nontoken permanents with the same
    name as one another, create a 4/4 colorless Construct artifact creature
    token." Two face-down creatures are not such a pair; two Bears are."""
    game = _table(set_pool, ["Chrome Replicator"])
    bears = _card(set_pool, "Grizzly Bears")
    _put(game, 0, bears, face_down=True)
    _put(game, 0, bears, face_down=True)
    assert game.cast_from_hand(0, "Chrome Replicator").supported
    settle(game)
    assert "Construct Token" not in _board(game)

    game = _table(set_pool, ["Chrome Replicator"])
    _put(game, 0, bears)
    _put(game, 0, bears)
    game.cast_from_hand(0, "Chrome Replicator")
    settle(game)
    assert "Construct Token" in _board(game)
