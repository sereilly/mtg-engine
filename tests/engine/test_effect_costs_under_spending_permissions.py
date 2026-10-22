"""Census: a cost an *effect* charges is payable with whatever mana the payer
may spend on it (CR 609.4b, CR 106.6).

There are two questions about paying and two functions for them
(``engine/mana_payment.py``): casting spends the **pool**, and an effect that
says "you may pay {1}{B}" also taps **lands**, because it gives its player no
priority window to tap them in. The first has honoured "you may spend white
mana as though it were mana of any color" since Celestial Dawn; the second
matched each coloured pip to a land that *produces that colour* and never asked
what the seat may spend that mana as. So under Celestial Dawn — every land a
Plains — no effect-priced coloured cost but {W} could be paid at all, and under
False Dawn, which turns every land's mana white for the turn, the same.

``plan_payment`` takes the payer now and asks ``mana_payment.pips_payable_by``,
the one reading of a seat's permissions the castable highlight already used.

The census holds the effect-cost planner (``Game._optional_pay_plan``) to the
exact one (``board_payment.board_can_pay``, itself held to tapping every
combination by ``test_castable_highlight_asks_the_planner``) under **every**
spending permission in both manifest roles, over every board of up to two
basic lands and one floating mana, against every cost of one or two symbols —
and under no permission at all, where the two had better agree already, which
is what says the comparison is a fair one.
"""

from __future__ import annotations

import itertools

import pytest

from engine import Game, PlayerState
from engine.board_payment import board_can_pay
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.mana_spending import spending_permission_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.helpers import _nosick, resolve_stack

_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")
_SYMBOLS = ("W", "U", "B", "R", "G", "C", "generic")

#: Every board asked: no land, one basic, or two.
_LANDS = [()] + [(name,) for name in _BASICS] + list(
    itertools.combinations_with_replacement(_BASICS, 2)
)
#: …with nothing floating, or one mana of a colour the permissions treat
#: differently: white (the mana Celestial Dawn frees), black (a colour it
#: confines to generic) and colourless.
_FLOATING = (None, "W", "B", "C")
#: Every cost asked: one symbol or two.
_COSTS = [
    {symbol: 1} for symbol in _SYMBOLS
] + [
    ({first: 2} if first == second else {first: 1, second: 1})
    for first, second in itertools.combinations_with_replacement(_SYMBOLS, 2)
]


def _pool() -> list:
    return list(compilation_units(load_cards(manifest_set_paths(include_measured=True))))


@pytest.fixture(scope="module")
def pool():
    return _pool()


@pytest.fixture(scope="module")
def by_name(pool):
    names: dict = {}
    for card in pool:
        names.setdefault(card.name, card)
    return names


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)


def permission_sources(pool) -> list[tuple]:
    """``(card, how)`` for every supported card that changes what its
    controller may spend mana as: a static line ``mana_spending`` reads (put on
    the battlefield) or a spell that grants one for the turn (cast)."""
    found = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if spending_permission_line(card.oracle_text or "") is not None:
            found.append((card, "static"))
        elif any(
            step.kind == "grant_mana_spending_until_eot"
            for instruction in program.instructions for step in _walk(instruction)
        ):
            found.append((card, "cast"))
    return found


def _table(by_name, lands, source=None, how=None) -> Game:
    """Seat 0 at its main phase with *lands* untapped and *source* in force."""
    board = [_nosick(Permanent(card=by_name[name])) for name in lands]
    if how == "static":
        board.append(_nosick(Permanent(card=source)))
    game = Game(players=[
        PlayerState(name="Payer", battlefield=board, library=[by_name["Forest"]] * 6,
                    hand=[source] if how == "cast" else []),
        PlayerState(name="Other", library=[by_name["Forest"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    if how == "cast":
        assert game.queue_from_hand(0, source.name).supported
        resolve_stack(game)
    game._recompute_continuous_effects()
    return game


def disagreements(by_name, source=None, how=None) -> dict:
    """Every (board, cost) on which the effect-cost planner and the exact one
    part, split by direction, with how many were asked."""
    refused, overpaid, asked, payable = [], [], 0, 0
    for lands in _LANDS:
        game = _table(by_name, lands, source, how)
        player = game.players[0]
        for floating in _FLOATING:
            player.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}
            if floating is not None:
                player.mana_pool[floating] = 1
            for cost in _COSTS:
                asked += 1
                truth = board_can_pay(game, 0, cost)
                planned = game._optional_pay_plan(player, {"cost": dict(cost)}) is not None
                payable += truth
                if truth and not planned:
                    refused.append((lands, floating, cost))
                elif planned and not truth:
                    overpaid.append((lands, floating, cost))
    return {"asked": asked, "payable": payable, "refused": refused, "overpaid": overpaid}


def run_census(pool, by_name) -> dict:
    """``{name: disagreements}`` for no permission (``"(none)"``) and for each
    permission source in the pool."""
    result = {"(none)": disagreements(by_name)}
    for card, how in permission_sources(pool):
        result[card.name] = disagreements(by_name, card, how)
    return result


def test_an_effect_cost_is_payable_with_what_the_seat_may_spend(pool, by_name):
    """Under every spending permission, the effect-cost planner and the exact
    one agree on every board and cost asked.

    Before the planner was given the payer it refused, of the costs a board
    could really pay: 1,559 of 2,054 under Celestial Dawn, 115 of 747 under
    Sunglasses of Urza, 1,582 of 2,214 under Chromatic Orrery and 1,579 of
    2,080 under False Dawn — and none of 632 without a permission, which is the
    control. It also *planned* six payments the Dawn forbids: a floating {B}
    for a {B} pip, where "other mana only as though it were colorless" makes
    black mana no payment for black.
    """
    census = run_census(pool, by_name)

    assert len(census) >= 5, sorted(census)
    for name, found in census.items():
        assert found["asked"] == len(_LANDS) * len(_FLOATING) * len(_COSTS), name
        assert found["payable"] >= 500, (name, found["payable"])
        assert found["refused"] == [], (name, len(found["refused"]), found["refused"][:5])
        assert found["overpaid"] == [], (name, len(found["overpaid"]), found["overpaid"][:5])


# ---------------------------------------------------------------------------
# The seam: a planner that is not told who is paying cannot ask what they may
# spend, and it answers anyway.
# ---------------------------------------------------------------------------

#: Callers that plan a payment without naming the payer, each with the reason
#: that is right for it. Anything else calling ``plan_payment`` without
#: ``payer=`` fails the guard below.
_PAYERLESS_PLANNERS = {
    # The castable highlight reads the permissions itself, a unit at a time
    # (``_pays``), and hands the matching sources that already say what they
    # pay — its pool argument is empty and its "lands" are those units.
    "engine/board_payment.py",
    # The AI's planner (``ai_payment._PaymentPlanner``) is the same matching
    # over the same units: each says what it pays for this seat
    # (``_unit_pays``, the permissions asked a unit at a time), so the payer
    # is already in what the matching is handed.
    "engine/ai_payment.py",
    # "Pay any amount of mana": a generic cost, which every unit pays whatever
    # the seat may spend it as.
    "web/prompts.py",
}


def test_every_payment_planner_names_its_payer():
    """A new ``plan_payment`` call site that forgets ``payer=`` plans as though
    its seat held no permission — it under-reports under four cards and
    nothing fails. This reads every call in ``engine/`` and ``web/``."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    calls, missing = 0, []
    for folder in ("engine", "web"):
        for path in sorted((root / folder).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", None))
                    == "plan_payment"
                ):
                    continue
                calls += 1
                named = any(keyword.arg == "payer" for keyword in node.keywords)
                if not named and relative not in _PAYERLESS_PLANNERS:
                    missing.append(f"{relative}:{node.lineno}")
    assert calls >= 17, calls
    assert missing == [], missing
