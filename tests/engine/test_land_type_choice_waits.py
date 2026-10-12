"""Census: nothing behind "the basic land type of your choice" happens before
the type is named (CR 608.2c, CR 608.2d).

"Target land becomes the basic land type of your choice until end of turn. /
Draw a card." (Shimmering Mirage.) CR 608.2c has a spell's instructions
followed in the order written, and the first one is not finished until its
controller has chosen. For a human seat the prompt was armed, the draw behind
it ran, and only then did the game wait — so the card was in hand while the
type was still being chosen, and a player could name the type having seen it.

``land_type_choice`` is a ``suspends`` kind now: arming it stops the loop its
effect was a step of (``engine/resumption.py``) and answering resumes it. That
is the arrangement ``scry`` has had since Opt, which is the same card shape one
keyword over.

The census drives **every** card in both manifest roles whose compiled program
arms the prompt — a spell or an ability, read off the ``choose_land_type``
payload rather than a list of names — as an interactive seat, and compares the
game the moment the prompt is owed with the game before anything resolved: the
zones, the life totals and the delayed triggers must not have moved. One card
printed a step that showed (Shimmering Mirage's draw) and one a step that did
not (Jinx's delayed draw was *created* early, which nothing could see); the
other five print the choice alone.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.helpers import _nosick


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


def _chooses(instructions) -> bool:
    return any((step.payload or {}).get("choose_land_type") for step in _walk(instructions))


def choosers(pool) -> list[tuple]:
    """``(card, "spell" | ability index, steps behind the choice)`` for every
    supported card whose resolution arms the land type prompt."""
    found = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if card.primary_type in ("instant", "sorcery"):
            steps = list(program.instructions)
            if _chooses(steps):
                at = next(i for i, step in enumerate(steps) if _chooses([step]))
                found.append((card, "spell", len(steps) - at - 1))
            continue
        for index, ability in enumerate(program.activated_abilities):
            if ability.instruction is not None and _chooses([ability.instruction]):
                found.append((card, index, 0))
    return found


def _snapshot(game) -> tuple:
    """Everything a later step of one of these cards could move."""
    return (
        tuple(len(player.hand) for player in game.players),
        tuple(len(player.library) for player in game.players),
        tuple(player.life for player in game.players),
        len(getattr(game, "delayed_triggers", ()) or ()),
    )


def _drive(by_name, card, where) -> dict:
    """Announce *card*'s choice as an interactive seat, on the path a seat is
    on (``_settle``, which holds a resolution that stops to ask), and report
    what had moved by the time the prompt was owed and after it was answered."""
    forest = _nosick(Permanent(card=by_name["Forest"]))
    board = [forest]
    hand = []
    if where == "spell":
        hand.append(card)
    else:
        board.append(_nosick(Permanent(card=card)))
    game = Game(players=[
        PlayerState(name="Chooser", hand=hand, battlefield=board,
                    library=[by_name["Swamp"]] * 6),
        PlayerState(name="Other", library=[by_name["Swamp"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    game._settle()
    before = _snapshot(game)
    if where == "spell":
        result = game.cast_from_hand(0, card.name, target_permanent_ids=[forest.permanent_id])
        # The spell itself left the hand; that is the cast, not a later step.
        before = (
            tuple(n - (1 if seat == 0 else 0) for seat, n in enumerate(before[0])),
            *before[1:],
        )
    else:
        result = game.activate_permanent_ability(
            0, card.name, ability_index=where, target_permanent_ids=[forest.permanent_id],
        )
    owed = game.pending_choice_of("land_type_choice", 0)
    report = {
        "announced": bool(result.supported),
        "asked": owed is not None,
        "moved_before_the_answer": _snapshot(game) != before,
        "held": bool(game.stack) and game.waiting_prompt() is not None,
    }
    if owed is not None:
        offered = game.land_type_choice_options(owed)
        answer = "swamp" if "swamp" in offered else offered[0]
        report["answered"] = game.confirm_land_type(0, answer)
        report["became"] = forest.has_type(answer)
        report["moved_after_the_answer"] = _snapshot(game) != before
        report["released"] = not game.stack and game.waiting_prompt() is None
    return report


def run_census(pool, by_name) -> dict:
    """``{label: report}`` over every chooser, with how many steps each prints
    behind its choice."""
    result = {}
    for card, where, behind in choosers(pool):
        label = card.name if where == "spell" else f"{card.name}#{where}"
        result[label] = {**_drive(by_name, card, where), "steps_behind": behind}
    return result


def test_nothing_behind_a_land_type_choice_happens_before_it_is_named(pool, by_name):
    """Every chooser: the prompt is asked, the game waits with the object on
    the stack, nothing behind the choice has happened yet, and the answer both
    changes the land and lets the rest run.

    The floors: seven cards arm this prompt from a resolution today, two of
    them with a step behind the choice. Before the kind suspended, Shimmering
    Mirage had drawn its card and Jinx had created its delayed draw by the
    time the prompt was owed.
    """
    census = run_census(pool, by_name)

    assert len(census) >= 7, sorted(census)
    with_a_step_behind = {label for label, saw in census.items() if saw["steps_behind"]}
    assert len(with_a_step_behind) >= 2, with_a_step_behind
    for label, saw in census.items():
        assert saw["announced"] and saw["asked"], (label, saw)
        assert saw["held"], (label, saw)
        assert not saw["moved_before_the_answer"], (label, saw)
        assert saw["answered"] and saw["became"] and saw["released"], (label, saw)
    # …and the steps behind did run, once the type was named.
    for label in with_a_step_behind:
        assert census[label]["moved_after_the_answer"], (label, census[label])
