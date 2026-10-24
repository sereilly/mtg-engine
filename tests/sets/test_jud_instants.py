"""Judgment instants.

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

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# Grip of Amnesia: "Counter target spell unless its controller exiles all
# cards from their graveyard. / Draw a card." The punisher offer Molten
# Influence makes (the *spell's* controller asked, ``stack_target_controller``)
# with the whole-graveyard sweep for its price.

import pytest as _w1g5_pytest  # noqa: E402

from engine.oracle import compile_card_oracle as _w1g5_compile  # noqa: E402
from engine.targeting import derive_cast_spec as _w1g5_cast_spec  # noqa: E402
from tests.sets import jud_w1g5_helpers as _w1g5  # noqa: E402


def _w1g5_grip(set_pool, *, bolt_caster=1, graveyard=3, interactive=(0, 1)):
    """*bolt_caster*'s Lightning Bolt at the other seat, with seat 0's Grip of
    Amnesia aimed at it; the Bolt's controller holds *graveyard* cards."""
    hands = [["Grip of Amnesia"], []]
    hands[bolt_caster].append("Lightning Bolt")
    game = _w1g5.table(set_pool, hands=hands, interactive=interactive)
    game.players[bolt_caster].graveyard.extend(
        [_w1g5.card(set_pool, "Grizzly Bears")] * graveyard
    )
    game.start_turn(0)
    bolt = game.queue_from_hand(
        bolt_caster, "Lightning Bolt", target_player_index=1 - bolt_caster,
    )
    assert bolt.supported, bolt.details
    grip = game.queue_from_hand(0, "Grip of Amnesia", target_stack_index=0)
    assert grip.supported, grip.details
    return game


@_w1g5_pytest.mark.parametrize("bolt_caster", [1, 0])
def test_w1g5_grip_exiled_graveyard_lets_the_spell_resolve(set_pool, bolt_caster):
    """The spell's controller is asked — the opponent, or Grip's own caster
    aiming at their own spell — and paying exiles their graveyard."""
    game = _w1g5_grip(set_pool, bolt_caster=bolt_caster)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g5.owed(game) == [bolt_caster]
    assert game.confirm_optional_pay(bolt_caster, accept=True)
    _w1g5.settle(game)

    payer = game.players[bolt_caster]
    assert [found.name for found in payer.exile] == ["Grizzly Bears"] * 3
    # What is left is what arrived after the exile: the Bolt, and Grip itself
    # when its caster was the one who paid.
    assert "Grizzly Bears" not in _w1g5.pile(game, bolt_caster)
    assert game.players[1 - bolt_caster].life == 17, "the Bolt resolved"


def test_w1g5_grip_declined_counters_the_spell_and_keeps_the_graveyard(set_pool):
    game = _w1g5_grip(set_pool)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=False)
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 20]
    assert game.players[1].exile == []
    assert _w1g5.pile(game, 1).count("Grizzly Bears") == 3
    assert "Lightning Bolt was countered by Grip of Amnesia and moved to graveyard" in game.log


def test_w1g5_grip_is_offered_to_an_empty_graveyard(set_pool):
    """"You can choose to exile all cards from your graveyard even if it has
    no cards in it." (Grip of Amnesia ruling, 2004-10-04.) The offer is made,
    and taking it saves the spell for nothing."""
    game = _w1g5_grip(set_pool, graveyard=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g5.owed(game) == [1]
    assert game.confirm_optional_pay(1, accept=True)
    _w1g5.settle(game)

    assert game.players[0].life == 17


def test_w1g5_grip_draws_a_card_whichever_way_it_goes(set_pool):
    for accept in (True, False):
        game = _w1g5_grip(set_pool)
        game.resolve_top_of_stack(pause_for_choices=True)
        game.confirm_optional_pay(1, accept=accept)
        _w1g5.settle(game)
        assert len(game.players[0].hand) == 1, accept


def test_w1g5_grip_answered_headless_before_the_spell_resolves(set_pool):
    """A seat nobody asks answers where the offer stands, because the spell
    it is about is the next object to resolve — the Molten Influence rule."""
    game = _w1g5_grip(set_pool, interactive=())
    _w1g5.settle(game)

    assert game.stack == []
    countered = "Lightning Bolt was countered by Grip of Amnesia and moved to graveyard" in game.log
    assert countered == (game.players[0].life == 20)
    assert countered != (len(game.players[1].exile) == 3)


def test_w1g5_grip_announces_a_spell_and_nothing_else(set_pool):
    """The picker offers the one target the line prints; the graveyard is the
    payer's, never a player Grip chose."""
    grip = _w1g5.card(set_pool, "Grip of Amnesia")
    assert _w1g5_cast_spec(grip, _w1g5_compile(grip)) == {"kind": "stack"}
    game = _w1g5.table(set_pool, hands=(["Grip of Amnesia"], []))
    game.start_turn(0)
    assert not game.cast_from_hand(0, "Grip of Amnesia").supported, "an empty stack"

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
