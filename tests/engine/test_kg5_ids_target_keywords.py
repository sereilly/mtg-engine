"""Each zone its own target keyword at the API (``engine/target_keywords``).

kg5 / ``ids``. Every cast, activation and AI action announced its target on
``target_permanent_index``: one slot whose zone the card's spec decided — a
battlefield slot on the named seat, a graveyard slot, or (Darkpact) an ante
slot. A permanent is named by id now (``target_permanent_ids``), a card in a
graveyard by its place in the pile (``target_graveyard_indices``), a card in
the ante by its place there (``target_ante_index``), and the slot the gates
behind the boundary read is derived from them once, as the announcement is
made. These drive each keyword through the real entry points and read the
board; the refusals hold a keyword to the zone it names.

Beside it, the Known-gaps entry this round drained: a cast naming its lone
graveyard target **by role** (``target_role_refs``) was handed the bare-cast
default (``names_an_object`` was asked without the role refs), so Raise Dead
returned the first creature card in the pile rather than the one named.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle


@pytest.fixture(scope="module")
def pool(catalog_by_name):
    return catalog_by_name


def _game(pool, *, hand=(), mine=(), theirs=(), graveyard=(), their_graveyard=()):
    p0 = PlayerState(
        name="P0", hand=[pool[name] for name in hand],
        battlefield=[Permanent(card=pool[name]) for name in mine],
        graveyard=[pool[name] for name in graveyard],
        library=[pool["Swamp"]] * 5,
    )
    p1 = PlayerState(
        name="P1", battlefield=[Permanent(card=pool[name]) for name in theirs],
        graveyard=[pool[name] for name in their_graveyard],
        library=[pool["Swamp"]] * 5,
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    for permanent in [*p0.battlefield, *p1.battlefield]:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    return game, p0, p1


GRAVEYARD = ["Grizzly Bears", "Hill Giant", "Shivan Dragon"]


def test_a_lone_graveyard_role_returns_the_card_it_names(pool):
    """The Known-gaps board: Raise Dead announced one role at a time, naming
    the third creature card in the pile. It returns that card, not the first
    one the bare-cast default would have written over the announcement."""
    game, p0, _p1 = _game(pool, hand=["Raise Dead"], graveyard=GRAVEYARD)

    result = game.cast_from_hand(
        0, "Raise Dead",
        target_role_refs=[{"graveyard_seat": 0, "graveyard_index": 2}],
    )

    assert result.supported, result.details
    assert [c.name for c in p0.hand] == ["Shivan Dragon"]
    assert [c.name for c in p0.graveyard] == ["Grizzly Bears", "Hill Giant", "Raise Dead"]
    assert "Returned Shivan Dragon from graveyard to hand" in game.log


def test_a_graveyard_card_is_named_by_its_place_in_the_pile(pool):
    game, p0, _p1 = _game(pool, hand=["Raise Dead"], graveyard=GRAVEYARD)

    result = game.cast_from_hand(0, "Raise Dead", target_graveyard_indices=[1])

    assert result.supported, result.details
    assert [c.name for c in p0.hand] == ["Hill Giant"]


def test_a_graveyard_keyword_names_the_named_seats_pile(pool):
    """"Exile target card from a graveyard" (Coffin Purge): the slot counts
    into the seat named beside it."""
    game, p0, p1 = _game(
        pool, hand=["Coffin Purge"], graveyard=["Grizzly Bears"],
        their_graveyard=["Hill Giant", "Shivan Dragon"],
    )

    result = game.cast_from_hand(
        0, "Coffin Purge", target_player_index=1, target_graveyard_indices=[1],
    )

    assert result.supported, result.details
    assert [c.name for c in p1.graveyard] == ["Hill Giant"]
    assert [c.name for c in p1.exile] == ["Shivan Dragon"]
    assert [c.name for c in p0.graveyard][:1] == ["Grizzly Bears"]


def test_a_permanent_named_by_id_alone_is_found_on_its_own_board(pool):
    """Swords to Plowshares named by id at the caster's own creature, no seat
    beside it: the id names the board, and the slot the gates read is derived
    from it there — never counted into the opposing seat's battlefield."""
    game, p0, p1 = _game(
        pool, hand=["Swords to Plowshares"], mine=["Hill Giant"],
        theirs=["Grizzly Bears"],
    )
    giant = p0.battlefield[0]

    result = game.cast_from_hand(
        0, "Swords to Plowshares", target_permanent_ids=[giant.permanent_id],
    )

    assert result.supported, result.details
    assert [p.card.name for p in p0.battlefield] == []
    assert [p.card.name for p in p1.battlefield] == ["Grizzly Bears"]
    assert p0.life == 23


@pytest.mark.cr("601.2c")
def test_one_id_is_one_target_for_a_spell_that_prints_two(pool):
    """Captain's Maneuver prints two targets ("target creature … another
    target creature"), so one is an illegal announcement (CR 601.2c, 601.2e).
    By one slot it was refused; by one id it was cast: the divided-target
    gate counted the id and the slot the entry point derives from that same
    id, two targets for one. Found by the round's full gate
    (``test_cast_announcements_w2g7``'s id-against-slot sweep)."""
    game, p0, _p1 = _game(pool, hand=["Captain's Maneuver"], mine=["Hill Giant"])
    giant = p0.battlefield[0]

    by_id = game.queue_from_hand(
        0, "Captain's Maneuver", x_value=1, target_permanent_ids=[giant.permanent_id],
    )

    game, _p0, _p1 = _game(pool, hand=["Captain's Maneuver"], mine=["Hill Giant"])
    by_slot = game.queue_from_hand(
        0, "Captain's Maneuver", x_value=1, target_player_index=0, target_permanent_index=0,
    )
    assert not by_slot.supported
    assert not by_id.supported, by_id.details
    assert by_id.details == by_slot.details
    assert "exactly 2 targets (1 named" in by_id.details


def test_an_activation_names_a_graveyard_card_by_its_place(pool):
    """Grave Robbers: "{B}, {T}: Exile target artifact card from a graveyard.
    You gain 2 life." The activation door takes the same keyword."""
    game, p0, p1 = _game(
        pool, mine=["Grave Robbers"], their_graveyard=["Ornithopter", "Sol Ring"],
    )

    result = game.activate_permanent_ability(
        0, "Grave Robbers", target_player_index=1, target_graveyard_indices=[1],
    )

    assert result.supported, result.details
    assert [c.name for c in p1.graveyard] == ["Ornithopter"]
    assert [c.name for c in p1.exile] == ["Sol Ring"]
    assert p0.life == 22


def test_a_mode_names_its_graveyard_cards_by_their_places(pool):
    """Ebony Charm's second mode, "Exile up to three target cards from a
    single graveyard", chosen as a mode with its own keyword."""
    game, _p0, p1 = _game(
        pool, hand=["Ebony Charm"],
        their_graveyard=["Grizzly Bears", "Hill Giant", "Shivan Dragon"],
    )

    result = game.cast_from_hand(
        0, "Ebony Charm",
        mode_choices=[{
            "index": 1, "target_player_index": 1,
            "target_graveyard_indices": [0, 2],
        }],
    )
    settle(game)

    assert result.supported, result.details
    assert [c.name for c in p1.graveyard] == ["Hill Giant"]
    assert sorted(c.name for c in p1.exile) == ["Grizzly Bears", "Shivan Dragon"]


def test_darkpact_names_its_ante_card_by_its_place(pool):
    """"You own target card in the ante. Exchange that card with the top card
    of your library." The second ante card named comes back to hand."""
    p0 = PlayerState(
        name="P0", hand=[pool["Darkpact"]], library=[pool["Swamp"]],
        ante=[pool["Black Lotus"], pool["Mox Pearl"]],
    )
    game = Game(players=[p0, PlayerState(name="P1")])

    result = game.cast_from_hand(0, "Darkpact", target_ante_index=1)

    assert result.supported, result.details
    assert [c.name for c in p0.ante] == ["Black Lotus", "Swamp"]
    assert any(c.name == "Mox Pearl" for c in p0.hand)


@pytest.mark.parametrize("announcement, refusal", [
    ({"target_graveyard_indices": [0]}, "targets no card in a graveyard"),
    ({"target_ante_index": 0}, "targets no card in the ante"),
    (
        {"target_graveyard_indices": [0], "target_permanent_index": 0},
        "name it twice",
    ),
])
def test_a_keyword_is_held_to_the_zone_it_names(pool, announcement, refusal):
    game, p0, p1 = _game(
        pool, hand=["Terror"], theirs=["Grizzly Bears"], graveyard=GRAVEYARD,
    )

    result = game.cast_from_hand(0, "Terror", **announcement)

    assert not result.supported
    assert refusal in result.details
    assert [c.name for c in p0.hand] == ["Terror"]
    assert [p.card.name for p in p1.battlefield] == ["Grizzly Bears"]


def test_a_graveyard_card_has_no_permanent_id(pool):
    """Raise Dead handed a permanent's id is refused rather than read as a
    slot of the pile."""
    game, p0, _p1 = _game(
        pool, hand=["Raise Dead"], mine=["Hill Giant"], graveyard=GRAVEYARD,
    )

    result = game.cast_from_hand(
        0, "Raise Dead", target_permanent_ids=[p0.battlefield[0].permanent_id],
    )

    assert not result.supported
    assert "has no permanent id" in result.details
    assert [c.name for c in p0.graveyard] == GRAVEYARD


def test_a_graveyard_target_names_no_permanent_in_the_same_numbered_slot(pool):
    """Grave Robbers aimed at the opposing pile's second card. The activation
    path stamped an id off the slot as though it were a battlefield slot, so
    the permanent second on that player's battlefield rode the stack object as
    a target too — and Skulking Ghost, which is sacrificed when it "becomes
    the target of a spell or ability", died to an ability that never named
    it. Through the old keyword (the tests' adapter) and the new one alike."""
    for announcement in ({"target_permanent_index": 1}, {"target_graveyard_indices": [1]}):
        game, p0, p1 = _game(
            pool, mine=["Grave Robbers"], theirs=["Hill Giant", "Skulking Ghost"],
            their_graveyard=["Ornithopter", "Sol Ring"],
        )

        result = game.activate_permanent_ability(
            0, "Grave Robbers", target_player_index=1, **announcement,
        )

        assert result.supported, result.details
        assert [p.card.name for p in p1.battlefield] == ["Hill Giant", "Skulking Ghost"]
        assert [c.name for c in p1.exile] == ["Sol Ring"]
