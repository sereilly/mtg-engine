"""A cast that opens other casts (CR 601.3) is worth proposing only when the
seat could make one of them.

A rehearsal reads a cast's good off the table it leaves, and a permission "this
turn" is gone from that table by the end of the turn — so a cast whose only
trace is one (Yawgmoth's Will, Recoup, Shaman's Trance) reads as fleeting, and
a fleeting cast is held (``ai_scoring._worth_proposing``). The exception is
``Rehearsal.opened_a_cast``: the permission is gone because it is *spent*, on a
cast this rehearsal is not a rehearsal of, as a ritual's mana is.

Measured at the Judgment integration chain (the ODY zone-cast census,
``test_what_a_seat_casts_from_its_hand_it_casts_from_an_opened_zone``):
Shaman's Trance, in hand with forty mana floating, opened the three cards in the
opponent's graveyard, each costing {50}, and was proposed at
``SPELL_BASE_SCORE`` for it; the same Trance cast out of the seat's own opened
graveyard was not. Two defects, one on each side:

* **the hand's cast was over-read.** ``opened_a_cast`` counted every cast the
  permission opened, including ones the seat could not make — a card spent to
  open casts nobody can pay for bought nothing. An opened cast now counts only
  if the seat could make it there and then (``ai_rehearsal._could_make_now``):
  CR 601.3's prohibitions, its timing (CR 307.1; a land drop left for a land,
  CR 305.2) and its price, planned by the payment planner over what the seat
  has left;
* **the graveyard's cast was under-read, because the engine got it wrong.** The
  grant that opened the seat's own graveyard ("you may cast spells from your
  graveyard", Yawgmoth's Will) answered ``permission_for`` for a card in the
  *opponent's* graveyard too, and every reader then refused it for being a
  grant over the wrong pile — so the Trance's grant behind it was never reached
  and nothing the Trance opened could be cast at all, by an AI or a person
  (``cast_permissions._covers`` now holds every blanket grant outside the hand
  to its own pile; the rules test is
  ``tests/sets/test_jud_instants.py::test_w1g8_shamans_trance_beside_an_opened_own_graveyard_still_opens_theirs``).

On the census board the two now agree: the {50} cards are a cast nobody can
make, from either side. (There the opponent's cards also share their names with
the seat's own, already castable, and ``permitted_casts`` offers a name once per
zone, as the cast path finds a card by name — so the graveyard's side would read
nothing opened even with the cards affordable. A second copy of a card already
castable is not a cast this reading counts.)

Validated backwards, each half alone: without ``_could_make_now`` the four
tests that hold a cast fail (it is proposed); without the ``_covers`` change
``test_trance_out_of_an_opened_graveyard_is_weighed_as_from_hand`` fails (the
affordable board proposes nothing out of the graveyard). The tests that cast
read the same either side.
"""
from __future__ import annotations

import pytest

from engine.ai_policy import choose_cast_action
from engine.cast_permissions import grant_permission
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool(set_pool, catalog_by_name):
    """Every shipped card by name, with Judgment's (``measured``) on top."""
    return {**catalog_by_name, **set_pool("JUD")}


def _duel(pool, *, hand=(), graveyard=(), lands=(), their_graveyard=()):
    """The AI's precombat main phase, mana costs enforced; zones by name."""
    forest = pool["Forest"]

    def cards(names):
        return [pool[name] for name in names]

    me = PlayerState(
        name="AI", library=[forest] * 10, hand=cards(hand),
        graveyard=cards(graveyard),
        battlefield=[_nosick(Permanent(card=card)) for card in cards(lands)],
    )
    opp = PlayerState(
        name="Opp", library=[forest] * 10, graveyard=cards(their_graveyard),
    )
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = ME
    game._sync_control()
    return game


def _proposed(game, name: str):
    action = choose_cast_action(game, ME)
    return action if action is not None and action.card_name == name else None


# --- Shaman's Trance: the opponent's graveyard ---------------------------------

_THREE_MOUNTAINS = ["Mountain"] * 3
_AND_TWO_FORESTS = ["Mountain"] * 3 + ["Forest"] * 2


def test_trance_is_held_when_it_opens_only_a_card_the_seat_cannot_pay_for(pool):
    """Three Mountains pay for Shaman's Trance ({2}{R}) and leave nothing for
    the Grizzly Bears ({1}{G}) it would open in the opponent's graveyard."""
    game = _duel(
        pool, hand=["Shaman's Trance"], lands=_THREE_MOUNTAINS,
        their_graveyard=["Grizzly Bears"],
    )
    assert _proposed(game, "Shaman's Trance") is None


def test_trance_is_cast_when_it_opens_a_card_the_seat_can_pay_for(pool):
    """Two Forests more and the Bears it opens are a cast the seat can make."""
    game = _duel(
        pool, hand=["Shaman's Trance"], lands=_AND_TWO_FORESTS,
        their_graveyard=["Grizzly Bears"],
    )
    action = _proposed(game, "Shaman's Trance")
    assert action is not None and action.from_zone == "hand"


def test_trance_out_of_an_opened_graveyard_is_weighed_as_from_hand(pool):
    """The census's claim, both ways: the same Trance cast out of the seat's
    own graveyard under "you may cast spells from your graveyard" is held on
    the board it is held on from hand and cast on the one it is cast on."""
    for lands, wanted in ((_THREE_MOUNTAINS, False), (_AND_TWO_FORESTS, True)):
        game = _duel(
            pool, graveyard=["Shaman's Trance"], lands=lands,
            their_graveyard=["Grizzly Bears"],
        )
        grant_permission(
            game, player_index=ME, zone="graveyard", mode="play", cards=None,
            exile_instead=True, duration="end_of_turn", source_name="test",
        )
        action = _proposed(game, "Shaman's Trance")
        assert (action is not None) is wanted, lands
        if wanted:
            assert action.from_zone == "graveyard"


def test_a_land_it_opens_is_a_use_only_while_a_land_drop_is_left(pool):
    """CR 305.2: the Forest in the opponent's graveyard is a land the seat may
    play from it once Trance resolves — while it has a land drop left."""
    game = _duel(
        pool, hand=["Shaman's Trance"], lands=_THREE_MOUNTAINS,
        their_graveyard=["Forest"],
    )
    assert _proposed(game, "Shaman's Trance") is not None

    game = _duel(
        pool, hand=["Shaman's Trance"], lands=_THREE_MOUNTAINS,
        their_graveyard=["Forest"],
    )
    game.lands_played_this_turn[ME] = 1
    assert _proposed(game, "Shaman's Trance") is None


# --- Yawgmoth's Will: the seat's own graveyard ----------------------------------

def test_yawgmoths_will_is_held_when_nothing_it_opens_can_be_paid_for(pool):
    """The same rule for the shipped card it was written for: Yawgmoth's Will
    ({2}{B}) on three Swamps opens a Lightning Bolt the seat has no mana left
    to cast."""
    game = _duel(
        pool, hand=["Yawgmoth's Will"], lands=["Swamp"] * 3,
        graveyard=["Lightning Bolt"],
    )
    assert _proposed(game, "Yawgmoth's Will") is None


def test_yawgmoths_will_is_cast_when_what_it_opens_can_be_paid_for(pool):
    game = _duel(
        pool, hand=["Yawgmoth's Will"], lands=["Swamp"] * 3 + ["Mountain"],
        graveyard=["Lightning Bolt"],
    )
    assert _proposed(game, "Yawgmoth's Will") is not None
