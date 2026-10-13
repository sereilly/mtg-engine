"""CR 401.4 over the whole pool: a look-and-pick that bottoms two or more cards
"in any order" asks an interactive seat for that order.

"Look at the top four cards of your library. Put one of them into your hand and
the rest on the bottom of your library in any order." (Impulse.) The rest were
laid down as they lay, unasked, on the stated ground that nothing can observe
the bottom of a library — which a deck that runs down to it does, one draw at a
time. Apocalypse's recruiters asked first (``Game.offer_library_bottom_order``,
``tests/engine/test_sorted_reveal_bottom.py``); this is the family that had the
same sentence and no question.

A census rather than a list of cards, so the next printing of the sentence is
held without being named: every ``look_top_pick_to_hand`` in a supported
program whose rest goes to the library's bottom in an unstated order is run
through its own handler for an interactive seat, the look is answered, and the
``reorder_library`` prompt has to be there, pointed at the bottom, over exactly
the cards that were not taken. On the tree before the wire this named Impulse,
Prophetic Bolt, Raven Familiar, See the Truth and Worldly Counsel — the list
W1G3 measured — which is the census's own backwards validation.

Abundance bottoms "in any order" through a replacement resolver rather than
this handler; ``test_abundance_asks_for_the_order_and_the_next_draw_waits`` is
its row, and says what had to be true first.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.game_types import OracleExecutionContext
from engine.handlers.registry import EFFECT_HANDLERS
from engine.oracle import compiled_units
from engine.oracle_types import OracleInstruction
from tests.helpers import _mk_card


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value
        for inner in value.payload.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _walk(inner)


def _program_instructions(program):
    yield from _walk(list(program.instructions))
    for ability in list(program.triggered_abilities) + list(program.activated_abilities):
        yield from _walk(getattr(ability, "instruction", None))
        yield from _walk(getattr(ability, "instructions", None))


@pytest.fixture(scope="module")
def bottoming_looks():
    """``{card name: (card, instruction)}`` for every look-and-pick in the pool (both
    manifest roles) whose rest goes to the bottom of the library in an order
    the card does not state."""
    from engine.card_loader import load_cards, manifest_set_paths

    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    found = {}
    for card, program in compiled_units(sorted(pool.values(), key=lambda c: c.name)):
        if not program.supported:
            continue
        for instruction in _program_instructions(program):
            if instruction.kind != "look_top_pick_to_hand":
                continue
            payload = instruction.payload
            if payload.get("rest_destination", "library_bottom") != "library_bottom":
                continue
            if payload.get("rest_order", "any") != "any":
                continue
            found.setdefault(card.name, (card, instruction))
    return found


def _look(card, instruction, *, interactive: bool):
    """Run *instruction* for seat 0 over an eight-card library and answer the
    look with its first card. Returns ``(game, looked, picks, library names
    before)``, or None when the handler armed no look at all."""
    names = [f"L{i}" for i in range(1, 9)]
    library = [_mk_card(name=name, type_line="Artifact") for name in names]
    game = Game(players=[PlayerState(name="P0", library=library), PlayerState(name="P1")])
    game.interactive_seats = {0} if interactive else set()
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[0], card=card, x_value=5,
        cast_from_zone="hand",
    )
    ok, why = EFFECT_HANDLERS[instruction.kind](game, instruction, context)
    assert ok, (card.name, why)
    choice = game.pending_choice_of("look_top_pick", 0)
    if choice is None:
        return None
    looked = int(choice.data["top_count"])
    picks = int(choice.data.get("remaining", 1))
    if not interactive:
        game.auto_resolve_pending_choices()
        return game, looked, picks, names
    while game.pending_choice_of("look_top_pick", 0) is not None:
        assert game.confirm_look_top_pick(0, 0), card.name
    return game, looked, picks, names


def test_every_look_that_bottoms_two_or_more_asks_for_their_order(bottoming_looks):
    assert len(bottoming_looks) >= 5, sorted(bottoming_looks)
    examined, unasked, wrong_pile = [], [], []
    for name, (card, instruction) in sorted(bottoming_looks.items()):
        run = _look(card, instruction, interactive=True)
        if run is None:
            continue
        game, looked, picks, names = run
        rest = looked - picks
        if rest < 2:
            # One card has one order: no prompt, and no resolution left open.
            assert game.pending_choices == [], name
            continue
        examined.append(name)
        prompt = game.pending_choice_of("reorder_library", 0)
        if prompt is None or prompt.data.get("position") != "bottom":
            unasked.append(name)
            continue
        offered = [c.name for c in game.reorder_library_pile(prompt)]
        # The first card was taken each time, so the rest are the next ones
        # looked at, as they lay — and they are the library's last cards.
        if offered != names[picks:looked] or offered != [
            c.name for c in game.players[0].library[-rest:]
        ]:
            wrong_pile.append((name, offered))
    assert len(examined) >= 5, f"only {len(examined)} examined: {examined}"
    assert not unasked, (
        f"bottomed {len(unasked)} of {len(examined)} piles without asking the "
        f"owner for an order (CR 401.4): {unasked}"
    )
    assert not wrong_pile, wrong_pile


def test_the_order_answered_is_the_order_those_cards_are_drawn_in(bottoming_looks):
    """Element 0 of the answer is the uppermost of the pile — the first of
    those cards a draw reaches — for every card in the family, checked by
    drawing the library down to them."""
    examined = 0
    for name, (card, instruction) in sorted(bottoming_looks.items()):
        run = _look(card, instruction, interactive=True)
        if run is None:
            continue
        game, looked, picks, names = run
        rest = looked - picks
        if rest < 2:
            continue
        examined += 1
        pile = names[picks:looked]
        reverse = list(range(rest - 1, -1, -1))
        assert game.confirm_reorder_library(0, reverse), name
        assert game.pending_choices == [], name
        me = game.players[0]
        untouched = len(me.library) - rest
        drawn = [me.library.pop(0).name for _ in range(len(me.library))]
        assert drawn[:untouched] == names[looked:], name
        assert drawn[untouched:] == list(reversed(pile)), name
    assert examined >= 5, examined


def test_a_seat_nobody_asks_keeps_them_as_they_lay(bottoming_looks):
    """Headless and AI seats queue nothing and consume no randomness: the rest
    go down in the order they were looked at, as they always did."""
    examined = 0
    for name, (card, instruction) in sorted(bottoming_looks.items()):
        run = _look(card, instruction, interactive=False)
        if run is None:
            continue
        game, looked, picks, names = run
        examined += 1
        assert game.pending_choices == [], name
        library = [c.name for c in game.players[0].library]
        assert library[: len(names) - looked] == names[looked:], name
        assert sorted(library[len(names) - looked:]) == sorted(
            set(names[:looked]) - {c.name for c in game.players[0].hand}
        ), name
    assert examined >= 5, examined


def _abundance_game(set_pool):
    from engine.models import Permanent

    abundance = set_pool("USG")["Abundance"]
    land = lambda n: _mk_card(name=n, type_line="Land")  # noqa: E731
    spell = lambda n: _mk_card(name=n, type_line="Artifact")  # noqa: E731
    me = PlayerState(name="P0", library=[
        land("L1"), land("L2"), spell("S1"), land("L3"), spell("S2"),
    ])
    game = Game(players=[me, PlayerState(name="P1")])
    me.battlefield.append(Permanent(card=abundance))
    return game, me


def test_abundance_asks_for_the_order_and_the_next_draw_waits(set_pool):
    """Abundance: "…put all other cards revealed this way on the bottom of
    your library in any order."

    The last look in the pool that laid its pile down unasked, and it was a
    decline with its parts measured: the one call the family above makes armed
    the order prompt beside the **next** draw's Abundance offer on a two-card
    draw, and two blocking prompts of different kinds owed by one seat each
    refuse the other's answer over the wire — a human seat was soft-locked.

    What had to be true first is that the second draw does not begin while
    the first still owes a decision (CR 121.2,
    ``Game._draw_prompt_open``). It does not: the draw behind the reveal is
    parked until the order is given, which is also what keeps "the last N
    cards" the pile *this* reveal put down rather than the next one's.
    """
    game, me = _abundance_game(set_pool)
    game.interactive_seats = {0}

    game._draw_with_replacements(me, 2)
    assert [c.kind for c in game.pending_replacement_choices] == ["reveal_until_kind_draw"]
    assert game.confirm_reveal_until_kind_draw(0, 0)

    # The first draw: S1 to hand, the two lands in front of it to the bottom
    # as revealed — and their order is asked. The second draw has not begun.
    assert [c.name for c in me.hand] == ["S1"]
    assert [c.name for c in me.library] == ["L3", "S2", "L1", "L2"]
    assert [c.kind for c in game.pending_choices] == ["reorder_library"]
    order = game.pending_choices[0]
    assert order.data["position"] == "bottom" and order.data["top_count"] == 2
    assert game.pending_replacement_choices == [], "one draw at a time"

    assert game.confirm_reorder_library(0, [1, 0])
    assert [c.name for c in me.library] == ["L3", "S2", "L2", "L1"]

    # Now the second draw, and its own offer.
    assert game.pending_choices == []
    assert [c.kind for c in game.pending_replacement_choices] == ["reveal_until_kind_draw"]
    assert game.confirm_reveal_until_kind_draw(0, 0)
    assert [c.name for c in me.hand] == ["S1", "S2"]
    # One card bottomed is no order to choose.
    assert game.pending_choices == [] and game.pending_replacement_choices == []
    assert not game.parked_draws


def test_abundance_asks_a_seat_nobody_is_asking_nothing(set_pool):
    """Headless and AI seats take "as they lay" and queue nothing, so a seeded
    run consumes no randomness and reads as it did before the question."""
    game, me = _abundance_game(set_pool)

    game._draw_with_replacements(me, 2)

    assert [c.name for c in me.hand] == ["S1", "S2"]
    assert [c.name for c in me.library] == ["L1", "L2", "L3"]
    assert game.pending_choices == [] and game.pending_replacement_choices == []
    assert not game.parked_draws
