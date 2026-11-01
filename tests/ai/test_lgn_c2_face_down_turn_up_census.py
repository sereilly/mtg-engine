"""Casting a card face down leaves its own turn-up payable: a census over
boards x morph costs, for both planners that choose which sources pay a cast.

Onslaught's Phase 5 recorded four Plains, three Mountains and Exalted Angel
cast face down for {3}: the auto-tap planned three Plains and the Angel's morph
cost {2}{W}{W} could not be paid. Round kg2 built the payer's wants
(``mana_wants.mana_wants``) and the preference that spares them
(``mana_payment._sparing_choice``), and its census measured a {3} beside a
*second* card wanting {2}{W}{W} — the neighbouring board. On this one the
card being cast **is** the want, and the cast's own seam threw it away:

* the AI's face-down cast was planned under ``_paying_for(card)``, and the
  wants leave the card being paid for out of the hand — so the Angel wanted
  nothing at all;
* the web's auto-tap was planned under the engine's purpose, whose card is the
  face-down 2/2 (CR 702.37c), which is no card in the hand — so the Angel was
  counted at its printed {4}{W}{W}, which no {3} could leave payable either.

A face-down spell's turn-up is a want of the card being cast: the morph cost
is paid later, as a special action (CR 702.37e), from what the {3} left. Both
planners now plan a face-down cast as the 2/2 the cast path casts, and the
wants read the card it hides as leaving the hand and bringing its turn-up.

**The census.** For each board of kg2's census and each distinct morph cost in
the pool (one card each), where the board can pay {3} and the morph cost
together: the card goes into the hand alone, the {3} is planned the way each
planner plans it, and the rest of the board is asked for the morph cost. A
**strand** is a row where it cannot although some set of sources would have
paid the {3} and left it payable. ``test_the_census_names_the_turn_up_left_out``
runs it backwards — the turn-up not read — and must find strands on both
planners, the entry's board among them. Measured on the tree before the fix
(a501c6c5): the AI planner stranded 25 of 81 rows, the auto-tap 21 of 81,
the entry's Angel on both; after it, none.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

import pytest

from engine import mana_wants as wants_module
from engine.ai_cast_gates import _alternative_cost_tap_plan
from engine.ai_payment import _PaymentPlanner, _paying_for
from engine.face_down import morph_cost
from engine.mana_payment import mana_cost_label, mana_cost_x_as_zero
from engine.oracle import compile_card_oracle
from tests.ai.test_kg2_payment_colour_census import (
    BOARDS, _CARDS, _board, _cost, _sources_leave, _together,
)
from web.payment_plan import planned_taps, unpaid_costs

#: The entry's row: Exalted Angel cast face down on four Plains and three
#: Mountains (its morph cost, {2}{W}{W}).
ENTRY_ROW = ("four Plains, three Mountains", "{2}{W}{W}")


def _morph_cards() -> dict[str, object]:
    """``{morph cost printed: card}`` — one supported card per distinct mana
    morph cost, X read as 0 (CR 107.3d's least). Exalted Angel stands for
    {2}{W}{W}, the entry's cost."""
    found: dict[str, object] = {"{2}{W}{W}": _CARDS["Exalted Angel"]}
    for name in sorted(_CARDS):
        card = _CARDS[name]
        printed = morph_cost(card)
        if printed is None:
            continue
        cost = mana_cost_x_as_zero(printed)
        if not cost or not compile_card_oracle(card).supported:
            continue
        found.setdefault(mana_cost_label(cost), card)
    return found


def _in_main_phase(game):
    """*game* in seat 0's precombat main phase with priority, as the web's
    auto-tap finds a person's table."""
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return game


def _ai_plan(game, card):
    """The AI candidate's morph branch (`ai_casts._cast_candidate`): the
    printed alternative cost planned under the cast's own `_paying_for`."""
    with _paying_for(card):
        return _alternative_cost_tap_plan(game, 0, card)


def _web_plan(game, card):
    """The auto-tap (`web/payment_plan.pay_from_board`): the engine asked
    what the face-down cast is short of, and the plan drawn for it."""
    _result, asked = unpaid_costs(
        game, lambda table: table.cast_from_hand(0, card.name, alternative_cost=True),
    )
    assert asked, card.name
    required, purpose = asked[0]
    assert required.get("generic") == 3 and sum(required.values()) == 3, required
    return planned_taps(game, 0, required, purpose)


PLANNERS = {"ai": _ai_plan, "web": _web_plan}


def _census(planner_name: str) -> dict:
    plan = PLANNERS[planner_name]
    morphs = _morph_cards()
    found = {"examined": 0, "strands": [], "boards": set(), "rows": set()}
    for label, names in BOARDS.items():
        if not all(_CARDS[name].primary_type == "land" for name in names) and (
            label not in ("a Llanowar Elves",)
        ):
            continue
        for printed, card in morphs.items():
            game = _in_main_phase(_board(names, hand=[card]))
            turn_up = _cost(printed)
            empty = _PaymentPlanner(game, game.players[0])
            if empty.plan(_together({"generic": 3}, turn_up)) is None:
                continue
            planned = plan(game, card)
            assert planned is not None, (label, printed)
            slots = set(planned[0])
            left = [source for source in empty.sources if source.slot not in slots]
            found["examined"] += 1
            found["boards"].add(label)
            found["rows"].add((label, printed))
            if empty._plan_with(left, turn_up) is not None:
                continue
            if _sources_leave(names, {"generic": 3}, turn_up):
                found["strands"].append((
                    label, printed, card.name,
                    [game.permanent_at(0, slot).card.name for slot in planned[0]],
                ))
    return found


@contextmanager
def _turn_up_left_out():
    """The tree before the fix, as both planners saw it: nothing the card
    being cast brings is a want."""
    with mock.patch.object(wants_module, "wants_brought_by", lambda paying_for: ()):
        yield


@pytest.fixture(scope="module", params=sorted(PLANNERS))
def census(request):
    return request.param, _census(request.param)


def test_a_face_down_cast_leaves_its_own_turn_up_payable(census):
    name, found = census
    assert found["strands"] == [], (name, found["strands"][:10])


def test_the_census_examined_enough(census):
    name, found = census
    assert ENTRY_ROW in found["rows"], name
    assert len(found["boards"]) >= 8, (name, found["boards"])
    assert found["examined"] >= 75, (name, found["examined"])


def test_the_census_names_the_turn_up_left_out():
    """Backwards: with the turn-up not read, both planners strand the card
    being cast — the entry's Angel among them."""
    with _turn_up_left_out():
        for name in PLANNERS:
            found = _census(name)
            assert len(found["strands"]) >= 15, (name, len(found["strands"]))
            assert ENTRY_ROW in {strand[:2] for strand in found["strands"]}, name
