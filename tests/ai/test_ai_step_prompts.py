"""A simulated step answers its own prompts before the next step begins.

The sixth omission of the "the simulator plays a whole turn" class, and the
first that was not a missing phase. ``run_ai_simulation`` ran every step in
order and answered what each one *asked* whenever its own loop next drained the
queue — which for an upkeep trigger was after the draw step, and for a combat
trigger after combat. Nothing failed: the run completed, the interaction count
was non-zero, the issue list was empty and every log line was present.

What holds it now is ``Game.prompt_driver`` — the engine asks the simulator for
its answers between one stack object and the next, inside the priority window
of the step that armed them — and ``SimulationReport.steps_left_owing``, which
the simulated game counts for itself at the line every step change goes through.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.ai_simulator import _resolve_pending_choices, run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.resumption import resume_after_answer, run_resumable
from tests.helpers import resolve_stack


def _w2g6_path(code: str):
    """The set's card file, whichever manifest role it is in today."""
    return manifest_set_path(code, include_measured=True)


def _w2g6_sanctuary_run():
    """Three Invasion games with Elfhame Sanctuary pinned into both decks —
    W1G7's reproduction: "At the beginning of your upkeep, you may search your
    library for a basic land card … If you do, you skip your draw step this
    turn."
    """
    return run_ai_simulation(
        _w2g6_path("INV"), games=3, seed=4242, max_turns=20,
        required_cards=["Elfhame Sanctuary"],
    )


def _w2g6_armed_and_spent(report) -> tuple[int, int]:
    armed = sum("will skip their draw step this turn" in line for line in report.log_lines)
    spent = sum("skipped draw step" in line for line in report.log_lines)
    return armed, spent


def test_w2g6_an_upkeep_triggers_answer_is_taken_before_the_draw_step():
    """CR 503.1 / CR 608.2: the upkeep trigger resolves — the whole of it,
    the "you may" included — before the draw step begins. Every skip the
    Sanctuary arms is the skip of *that turn's* draw step, so every one armed
    is spent; on the base tree 14 were armed in these three games and none
    was, because the search was answered after the card had been drawn."""
    report = _w2g6_sanctuary_run()
    armed, spent = _w2g6_armed_and_spent(report)

    assert armed >= 10, f"the Sanctuary was offered only {armed} time(s); the run proves nothing"
    assert spent == armed, (
        f"{armed} draw-step skips were armed in an upkeep and {spent} were spent: "
        "an upkeep trigger's answer is being taken after the draw step again"
    )
    assert report.steps_left_owing == Counter()
    # While Invasion is `measured` a deck can hold a card nothing supports yet,
    # and proposing one is reported; anything else would be the reordering.
    other = [
        issue.message for issue in report.issues
        if not issue.message.startswith("Unsupported card cast in simulation")
    ]
    assert not other, other


def test_w2g6_the_owing_count_names_the_defect_on_a_tree_that_has_it(monkeypatch):
    """The instrument, validated backwards. With the engine's seam taken out
    the simulator is the loop it was — it drains the queue only where its own
    walk stands — and the count has to say so, naming the step, the prompt and
    the card. A census that reads zero on the broken tree is not a census."""
    monkeypatch.setattr(Game, "drive_owed_prompts", lambda self: False)
    report = _w2g6_sanctuary_run()
    armed, spent = _w2g6_armed_and_spent(report)

    assert armed > 0 and spent == 0
    assert report.steps_left_owing["upkeep -> draw: optional_pay (Elfhame Sanctuary)"] == armed
    assert report.steps_left_owing["draw -> precombat_main: optional_pay (Elfhame Sanctuary)"] == armed


@pytest.mark.slow
@pytest.mark.parametrize("code", ["LEA", "TMP", "M21", "INV"])
def test_w2g6_no_simulated_step_ends_owing_anything(code):
    """Zero, over a counted number of step changes, in a base set, the set whose
    Mirri's Guile showed the upkeep half, the set whose Jeskai Elder showed the
    combat half, and the set this was found in.

    Asserted on the count rather than on any card's behaviour for the reason
    the combat and ending-phase guards are: the defect is an *ordering*, every
    line of which is present, and only a number that must stay at zero catches
    the next step somebody walks by hand.
    """
    report = run_ai_simulation(_w2g6_path(code), games=4, seed=1337, max_turns=14)

    assert report.step_changes >= 600, (
        f"only {report.step_changes} step changes were examined in four games"
    )
    assert report.steps_left_owing == Counter(), dict(report.steps_left_owing)


def test_w2g6_the_simulator_answers_a_prompt_kind_it_does_not_name():
    """``_SIMULATED_CHOICES`` fixes the *order* of the kinds whose defaults
    consume randomness; it was also the whole of what the simulator answered.
    Phantasmal Terrain's "As this Aura enters, choose a basic land type" is a
    ``land_type_choice`` — it holds priority, does not suspend, and so was on
    no list: the Aura sat on a land for the rest of every game with its choice
    owed and the land unchanged."""
    report = run_ai_simulation(
        _w2g6_path("LEA"), games=2, seed=11, max_turns=14,
        required_cards=["Phantasmal Terrain"],
    )
    cast = sum(
        "cast Phantasmal Terrain -> resolved" in line for line in report.log_lines
    )
    chosen = sum(
        "Phantasmal Terrain: enchanted land becomes" in line for line in report.log_lines
    )

    assert cast >= 1, "no seat cast Phantasmal Terrain; pick a seed that does"
    assert chosen == cast, (
        f"Phantasmal Terrain resolved {cast} time(s) and its land type was "
        f"chosen {chosen} time(s)"
    )
    assert report.steps_left_owing == Counter()


def test_w2g6_every_prompt_kind_has_a_default_the_simulator_can_take():
    """What makes "then everything else that is queued" safe to say: the drain
    is generic over the registry, so a kind with no default would be a prompt a
    simulated seat owes forever."""
    from engine.pending_choices import CHOICE_SPECS

    assert len(CHOICE_SPECS) >= 80
    without = sorted(kind for kind, spec in CHOICE_SPECS.items() if spec.default is None)
    assert not without, f"prompt kind(s) with no non-interactive default: {without}"


# --- the seam itself --------------------------------------------------------


def _w2g6_sanctuary_table(all_cards_by_name, **game_kwargs) -> Game:
    library = [all_cards_by_name[name] for name in (
        "Shivan Dragon", "Forest", "Serra Angel", "Island", "Grizzly Bears",
    )]
    game = Game(
        players=[
            PlayerState(
                name="Sanctuary",
                battlefield=[Permanent(card=all_cards_by_name["Elfhame Sanctuary"])],
                library=library,
            ),
            PlayerState(name="Other", library=[all_cards_by_name["Forest"]] * 5),
        ],
        **game_kwargs,
    )
    game._sync_control()
    game.turn = 4
    return game


@pytest.fixture(scope="module")
def _w2g6_cards(catalog_by_name, set_pool):
    return {**catalog_by_name, **set_pool("INV")}


def test_w2g6_a_driven_table_resolves_the_upkeep_before_it_draws(_w2g6_cards):
    """`Game.start_turn`, the engine's own walk of the beginning phase, at a
    table with a ``prompt_driver``: the Sanctuary's offer is answered inside
    the upkeep step's priority window, so the draw step it names is skipped."""
    game = _w2g6_sanctuary_table(_w2g6_cards, prompt_driver=_resolve_pending_choices)
    game.start_turn(0)
    player = game.players[0]

    assert [card.name for card in player.hand] in (["Forest"], ["Island"])
    assert len(player.library) == 4, "the turn's card was drawn as well as the land searched for"
    assert "Sanctuary skipped draw step" in game.log
    assert game.pending_choices == [] and game.stack == []
    assert game.skip_step_counts == {}


def test_w2g6_a_bare_headless_game_still_leaves_its_prompts_for_the_caller(_w2g6_cards):
    """The driver is opt-in, and this is what it is opting out of: a headless
    ``Game`` with nobody to ask queues the prompt and returns, so a caller —
    forty tests among them — can read what was asked before answering it. That
    contract is why the simulator needed a seam rather than a different
    default."""
    game = _w2g6_sanctuary_table(_w2g6_cards)
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)

    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    assert game.stack == []
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert game.pending_choices == []
    assert len(game.players[0].hand) == 1


def test_w2g6_answering_inside_a_running_loop_leaves_that_loop_alone():
    """engine/resumption.py: an answer unwinds the loops that are *waiting*,
    and a loop whose step is still executing is not.

    The combat damage step's last step drains a priority window; a trigger
    resolving there stops to ask; a driven table answers at once, from inside
    the outer loop's own step. Unwinding the whole stack re-ran the outer
    loop's remainder underneath it — its second step twice, then a pop from an
    empty stack (Volrath's Dungeon, EXO, the first simulated game to reach it).
    """
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    ran: list[str] = []

    def step(item: str) -> None:
        ran.append(item)
        if item == "outer-1":
            # An inner loop stopped to ask and returned, leaving the rest of
            # itself; its answer arrives while this step is still running.
            game.resume_stack.append(lambda: ran.append("inner-rest"))
            resume_after_answer(game)

    run_resumable(game, ["outer-1", "outer-2"], step)

    assert ran == ["outer-1", "inner-rest", "outer-2"]
    assert game.resume_stack == []


def test_w2g6_a_drain_does_not_answer_a_choice_twice(_w2g6_cards):
    """`auto_resolve_pending_choices` walks a snapshot of the queue, and at a
    driven table an answer can drain the rest of that queue from inside itself
    (it resolves something, and the engine asks the driver again). The choice
    the inner drain took must not be taken a second time by the outer one."""
    game = _w2g6_sanctuary_table(_w2g6_cards)
    answers: list[int] = []
    first = game.arm_pending_choice("optional_pay", 0, card_name="first", cost={})
    second = game.arm_pending_choice("optional_pay", 0, card_name="second", cost={})

    def take(choice):
        answers.append(id(choice))
        game.discard_pending_choice(choice)
        if choice is first:
            # The nested drain: everything else that is queued, now.
            for other in list(game.pending_choices):
                take(other)

    game.take_choice_default = take
    game.auto_resolve_pending_choices(kinds=("optional_pay",))

    assert answers == [id(first), id(second)]


# --- whose turn comes next is the engine's answer -----------------------------


def _w2g6_turn_takers(report) -> list[tuple[str, str]]:
    """``(game, seat)`` for every turn of the run, in order — read off the untap
    step's own log line, which every turn writes exactly once."""
    import re

    takers = []
    for line in report.log_lines:
        found = re.match(r"\s+AI-([AB])-(\d+) untapped \d+ permanent", line)
        if found:
            takers.append((found.group(2), found.group(1)))
    return takers


def test_w2g6_a_simulated_seat_takes_the_extra_turn_it_cast():
    """CR 500.7. The seventh omission of the class, found by counting rather
    than by a failure: the loop read ``for active in (0, 1)``, so Time Walk
    queued its turn and the loop walked past it. Four games with it pinned —
    five resolved, five still on `extra_turn_queue` at the end, none taken.
    Whose turn is next is `Game.start_next_turn`'s answer now."""
    report = run_ai_simulation(
        _w2g6_path("LEA"), games=4, seed=5, max_turns=14, required_cards=["Time Walk"],
    )
    resolved = sum("cast Time Walk -> resolved" in line for line in report.log_lines)
    takers = _w2g6_turn_takers(report)
    twice_running = sum(1 for first, second in zip(takers, takers[1:]) if first == second)

    assert resolved >= 3, f"Time Walk resolved only {resolved} time(s); pick a seed that casts it"
    # One per Time Walk, less any still queued when its game ended.
    assert resolved - 4 <= report.extra_turns_taken <= resolved
    assert report.extra_turns_taken >= 1
    assert twice_running == report.extra_turns_taken
    assert not report.issues, [issue.message for issue in report.issues]


def test_w2g6_a_simulated_seat_skips_the_turn_a_card_takes_from_it():
    """CR 500.11's other direction, through the same call: Meditate's "You
    skip your next turn" is a record `_compute_next_active_player` spends, and
    a loop that named the seats itself never asked. A skipped turn is the
    *other* seat taking two in a row, with no extra turn to explain it."""
    report = run_ai_simulation(
        _w2g6_path("TMP"), games=4, seed=5, max_turns=14, required_cards=["Meditate"],
    )
    resolved = sum("cast Meditate -> resolved" in line for line in report.log_lines)
    takers = _w2g6_turn_takers(report)
    twice_running = sum(1 for first, second in zip(takers, takers[1:]) if first == second)

    assert resolved >= 2, f"Meditate resolved only {resolved} time(s)"
    assert report.extra_turns_taken == 0
    assert 1 <= twice_running <= resolved


def test_w2g6_an_ordinary_game_still_alternates_its_two_seats():
    """…and nothing else moved: with no card that adds or skips a turn, the
    engine's rotation is the alternation the loop used to spell out, seat A
    first. (The five default seeded runs — LEA, DRK, TMP, M21, INV — are
    byte-identical across the change.)"""
    report = run_ai_simulation(_w2g6_path("DRK"), games=2, seed=1337, max_turns=8)
    takers = _w2g6_turn_takers(report)

    assert len(takers) >= 20
    for game in {game for game, _seat in takers}:
        seats = [seat for taker_game, seat in takers if taker_game == game]
        assert seats[0] == "A"
        assert all(first != second for first, second in zip(seats, seats[1:])), seats
    assert report.extra_turns_taken == 0
