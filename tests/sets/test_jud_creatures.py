"""Judgment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
#
# The Nightmares: an entry exile linked to leaving (CR 607.2a, 610.3). Each
# card is cast through the real path and its leaving half driven by Swords to
# Plowshares; each is also killed with its entry trigger on the stack, where
# the leave trigger resolves first and returns nothing and the entry trigger
# then exiles for good (the Worldgorger Dragon / Wormfang Drake rulings,
# 2022-12-08).

import pytest as _w1g4_pytest

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.linked_exile import linked_entries as _w1g4_linked_entries
from engine.models import Permanent as _W1G4Permanent
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(set_pool, name):
    for code in ("JUD", "LEA", "ODY", "TOR"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g4_game(set_pool, *, hand=(), opp_hand=(), interactive=()):
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    p0 = _W1G4PlayerState(
        name="P0", hand=[card(n) for n in hand], library=[card("Island")] * 5,
    )
    p1 = _W1G4PlayerState(
        name="P1", hand=[card(n) for n in opp_hand], library=[card("Forest")] * 5,
    )
    game = _W1G4Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g4_put(game, set_pool, seat, name):
    permanent = _W1G4Permanent(card=_w1g4_card(set_pool, name))
    permanent.metadata["summoning_sickness_turn"] = -5
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g4_resolve_stack(game)
    return permanent


def _w1g4_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g4_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def _w1g4_drain(game):
    for _ in range(6):
        _w1g4_resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _w1g4_swords(game, set_pool, victim):
    """Exile *victim* with Swords to Plowshares, dealt into seat 0's hand here
    so a test's hand is only the cards it is about."""
    game.players[0].hand.append(set_pool("LEA")["Swords to Plowshares"])
    result = game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=game.controller_index_of(victim),
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log[-5:]
    _w1g4_drain(game)


# --- Wormfang Newt / Turtle: "exile a land you control" --------------------


@_w1g4_pytest.mark.parametrize("name", ["Wormfang Newt", "Wormfang Turtle"])
def test_w1g4_a_land_nightmare_exiles_a_land_and_gives_it_back_untapped(set_pool, name):
    game = _w1g4_game(set_pool, hand=[name])
    plains = _w1g4_put(game, set_pool, 0, "Plains")
    _w1g4_put(game, set_pool, 0, "Island")
    _w1g4_put(game, set_pool, 1, "Forest")
    plains.tapped = True
    game.cast_from_hand(0, name)
    _w1g4_drain(game)

    # One of *its controller's* lands, chosen as the trigger resolved: the
    # opponent's Forest is never a candidate.
    p0 = game.players[0]
    assert [c.name for c in p0.exile] == ["Plains"], game.log[-6:]
    assert _w1g4_names(game, 0) == sorted(["Island", name])
    assert _w1g4_names(game, 1) == ["Forest"]
    nightmare = _w1g4_named(game, 0, name)
    assert [e["card"].name for e in _w1g4_linked_entries(nightmare)] == ["Plains"]

    _w1g4_swords(game, set_pool, nightmare)

    # "Return the exiled card to the battlefield under its owner's control" —
    # a new object (CR 400.7): untapped, and not the permanent that left.
    returned = _w1g4_named(game, 0, "Plains")
    assert returned is not plains and not returned.tapped
    assert [c.name for c in p0.exile] == [name]


def test_w1g4_wormfang_newt_asks_its_controller_which_land(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"], interactive=(0,))
    plains = _w1g4_put(game, set_pool, 0, "Plains")
    island = _w1g4_put(game, set_pool, 0, "Island")
    _w1g4_put(game, set_pool, 1, "Forest")
    game.queue_from_hand(0, "Wormfang Newt")
    game.resolve_top_of_stack()  # the creature spell
    game.resolve_top_of_stack()  # its entry trigger, which stops to ask

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "permanent_choice"
    assert choice.player_index == 0
    # Only lands its controller controls: not the Newt, not the Forest.
    assert {p.card.name for p in game.live_permanent_choices(choice)} == {
        "Plains", "Island",
    }
    assert game.confirm_permanent_choice(0, island.permanent_id)
    _w1g4_drain(game)

    assert [c.name for c in game.players[0].exile] == ["Island"]
    assert game.is_on_battlefield(plains)


def test_w1g4_wormfang_newt_with_no_land_exiles_nothing(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"])
    _w1g4_put(game, set_pool, 1, "Forest")
    game.cast_from_hand(0, "Wormfang Newt")
    _w1g4_drain(game)

    assert game.players[0].exile == [] and game.players[1].exile == []
    assert _w1g4_names(game, 1) == ["Forest"]
    assert "Wormfang Newt: there is no permanent it could choose" in game.log


def test_w1g4_wormfang_newt_killed_in_response_exiles_its_land_for_good(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"])
    _w1g4_put(game, set_pool, 0, "Plains")
    game.queue_from_hand(0, "Wormfang Newt")
    game.resolve_top_of_stack()
    newt = _w1g4_named(game, 0, "Wormfang Newt")
    assert game.stack, "the entry trigger is a stack object (CR 603.3)"

    _w1g4_swords(game, set_pool, newt)

    # The leave trigger resolved first and found nothing; the entry trigger
    # then exiled the Plains, and nothing is left that will return it.
    assert sorted(c.name for c in game.players[0].exile) == ["Plains", "Wormfang Newt"]
    assert _w1g4_names(game, 0) == []


# --- Wormfang Drake: "sacrifice it unless you exile a creature you control
# other than this creature" -------------------------------------------------


def test_w1g4_wormfang_drake_exiles_a_creature_and_returns_it_when_it_leaves(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"])
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.cast_from_hand(0, "Wormfang Drake")
    _w1g4_drain(game)

    # A seat nobody asks pays the toll: the Bears go, the Drake stays.
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"], game.log[-6:]
    drake = _w1g4_named(game, 0, "Wormfang Drake")
    assert [e["card"].name for e in _w1g4_linked_entries(drake)] == ["Grizzly Bears"]

    _w1g4_swords(game, set_pool, drake)

    returned = _w1g4_named(game, 0, "Grizzly Bears")
    assert returned is not bears
    assert [c.name for c in game.players[0].exile] == ["Wormfang Drake"]


def test_w1g4_wormfang_drake_alone_is_sacrificed_without_an_offer(set_pool):
    # "If you don't control any other creatures as the enters-the-battlefield
    # ability resolves, you must sacrifice Wormfang Drake." (2022-12-08.) An
    # interactive seat, so an offer — had one been made — would be left owed.
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"], interactive=(0,))
    _w1g4_put(game, set_pool, 1, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()

    assert not game.pending_choices
    assert [c.name for c in game.players[0].graveyard] == ["Wormfang Drake"]
    # The opponent's creature was never a price the Drake's controller pays.
    assert _w1g4_names(game, 1) == ["Grizzly Bears"]


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_wormfang_drake_offers_its_controller_the_price(set_pool, accept):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"], interactive=(0,))
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()
    assert game.waiting_prompt().kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=accept)
    if accept:
        # Which creature is the next question, and only the Bears answer it:
        # "other than this creature".
        choice = game.waiting_prompt()
        assert choice.kind == "permanent_choice"
        assert [p.card.name for p in game.live_permanent_choices(choice)] == [
            "Grizzly Bears",
        ]
        assert game.confirm_permanent_choice(0, bears.permanent_id)
    _w1g4_drain(game)

    if accept:
        assert _w1g4_names(game, 0) == ["Wormfang Drake"]
        assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    else:
        assert _w1g4_names(game, 0) == ["Grizzly Bears"]
        assert [c.name for c in game.players[0].graveyard] == ["Wormfang Drake"]


def test_w1g4_wormfang_drake_killed_in_response_exiles_the_price_for_good(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"])
    _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    drake = _w1g4_named(game, 0, "Wormfang Drake")
    assert game.stack

    _w1g4_swords(game, set_pool, drake)

    # "If you exile a creature you control, it will be exiled indefinitely.
    # Wormfang Drake won't return it." (2022-12-08.)
    assert sorted(c.name for c in game.players[0].exile) == [
        "Grizzly Bears", "Wormfang Drake",
    ]
    assert _w1g4_names(game, 0) == []

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
