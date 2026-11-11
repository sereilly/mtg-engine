"""CR 500.2 — a step ends "when the stack is empty **and all players pass in
succession**. Simply having the stack become empty doesn't cause such a phase
or step to end."

To pass, a player has to get priority, and CR 117.5 says what happens first:
state-based actions are performed, "then triggered abilities are put on the
stack". So an ability the *last* resolution of a step made trigger belongs to
that step.

The step's window drained its stack and stopped there. Whatever that last
resolution set off was announced by the next thing to check state — the draw
step — and resolved after it. Phase 5 watched Bomb Squad do it: "Hill Giant
each got 1 fuse counter(s)", then "drew 1 card(s) in draw step", and only then
the destruction and the 4 damage.

A state trigger (CR 603.8) is the shape that shows it, because a state has no
fire site: the sweep announces it. Ten in the pool reach the stack, and every
one of them made true by an upkeep effect waited for the draw — on the web's
path, the headless one and the simulator's. The census below runs all three,
and is validated backwards with the window's check switched off.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.handlers.registry import EFFECT_HANDLERS
from engine.mixins.phase_steps import PhaseStepsMixin
from engine.named_counters import add_counters, counters_on
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction

from .test_state_trigger_latch import STATE_KINDS, _make_the_state_true, _put

#: The three ways the engine runs a step nobody holds priority through.
PATHS = ("headless", "interactive", "driver")

#: A floor, because a sweep that reaches nothing passes. Ten on the day.
_MIN_STACKED = 10


@pytest.fixture(scope="module")
def pool():
    cards = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards


def _table(pool, path: str, life: int = 20) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("P0", library=[forest] * 10, life=life),
        PlayerState("P1", library=[forest] * 10, life=life),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    if path == "interactive":
        game.interactive_seats = {0, 1}
    elif path == "driver":
        game.prompt_driver = lambda table: table.auto_resolve_pending_choices()
    return game


# -- Bomb Squad, as Phase 5 played it -----------------------------------------

@pytest.mark.cr("500.2", "117.5", "603.8")
@pytest.mark.parametrize("path", PATHS)
def test_500_2_the_fuse_goes_off_in_the_upkeep_it_was_lit_in(pool, path):
    """"At the beginning of your upkeep, put a fuse counter on each creature
    with a fuse counter on it. Whenever a creature has four or more fuse
    counters on it, remove all fuse counters from it and destroy it. That
    creature deals 4 damage to its controller." """
    game = _table(pool, path)
    me, you = game.players
    _put(game, 0, pool["Bomb Squad"])
    giant = _put(game, 1, pool["Hill Giant"])
    add_counters(giant, "fuse", 3)
    game._settle()
    hand = len(me.hand)

    game.resolve_upkeep(0)

    # The step is over, and so is everything it set off: nothing waits on the
    # stack for the draw step to find.
    assert not game.stack, [item.ability_text for item in game.stack]
    assert not game.is_on_battlefield(giant), game.log[-6:]
    assert [card.name for card in you.graveyard] == ["Hill Giant"]
    assert you.life == 16
    assert len(me.hand) == hand, "the upkeep is not the draw step"
    assert counters_on(giant, "fuse") == 0


# -- Every state trigger that reaches the stack -------------------------------

def _state_triggers(pool):
    for card in faces.compilation_units(list(pool.values())):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trig in program.triggered_abilities:
            if trig.condition.kind in STATE_KINDS and trig.instruction is not None:
                yield card, trig


def _left_waiting_when_the_upkeep_ended(
    pool, card, trig, path, asked: "set | None" = None,
) -> "bool | None":
    """Run an upkeep whose last trigger makes *trig*'s state true as it
    resolves. True when the step ended with the state trigger still waiting —
    on the stack, or not announced at all; None when this trigger is not one
    that reaches the stack this way.

    *asked*, when given, collects ``(card name, path)`` for every row whose
    upkeep armed a decision of the card's own — a "may", a target — beside
    the census's order prompt: the backwards check's "another road"."""
    # The state must not already hold as the card arrives: Transcendence's
    # "when you have 20 or more life, you lose the game" at the table's 20
    # resolved during the setup, the game was over (CR 104.1) and no upkeep
    # followed it to make anything true. Seated with less, rather than set
    # after, so no life was lost ("whenever you lose life", its third line).
    game = _table(
        pool, path,
        life=int(trig.condition.payload["life_count"]) - 1
        if trig.condition.kind == "life_at_least" else 20,
    )
    for seat in (0, 1):
        _put(game, seat, pool["Forest"])
        _put(game, seat, pool["Grizzly Bears"])
    permanent = _put(game, 0, card)
    game._settle()
    if game.stack:
        return None

    made = []

    def make_true(table, instruction, context):
        _make_the_state_true(table, permanent, trig, pool)
        made.append(True)
        return True, "resolved"

    EFFECT_HANDLERS["census_make_state_true"] = make_true
    enqueue = game._enqueue_triggered_batch

    def with_one_more(events):
        game._enqueue_triggered_batch = enqueue
        return enqueue(list(events) + [{
            "controller_index": 0,
            "source_permanent": permanent,
            "instruction": OracleInstruction("census_make_state_true", None, {}),
            "effect_kind": "triggered_census",
            "ability_text": "census",
            "trigger_context": {"event_subject_player": 0},
        }])

    game._enqueue_triggered_batch = with_one_more
    arm = game.arm_pending_choice

    def arm_and_note(kind, *args, **kwargs):
        if asked is not None and kind != "order_triggers":
            asked.add((card.name, path))
        return arm(kind, *args, **kwargs)

    game.arm_pending_choice = arm_and_note
    try:
        game.resolve_upkeep(0)
        # The census's own trigger and the card's go on the stack together,
        # so an interactive seat is asked their order first (CR 603.3b; round
        # 4) and nothing resolves until it answers. Answered as a seat nobody
        # asks would — the order pushed — and the step's window run on, which
        # is what the web layer's resume does (`_resume_paused_beginning_phase`).
        for owed in game.pending_choices_of("order_triggers"):
            game.auto_resolve_choice(owed)
            game._resolve_priority_window()
    finally:
        EFFECT_HANDLERS.pop("census_make_state_true", None)
        game.arm_pending_choice = arm
    assert made, card.name
    if game.is_game_over():
        # CR 104.1: "A game ends immediately when a player wins". Darksteel
        # Reactor's "you win the game", announced and resolved inside the
        # upkeep it was made true in, ends the game with its own upkeep
        # trigger still on the stack — an object that will never resolve,
        # not one waiting for a draw step that will never come. Only the
        # state trigger's own instance left there would be late.
        return any(
            item.source_permanent is permanent
            and item.ability_text == trig.source_line
            for item in game.stack
        )
    if game.stack and game.pending_choices:
        return False  # held on a decision it armed: still its own step's
    if game.stack:
        return True
    game.check_state_based_actions()
    return bool(game.stack)


def _census(pool, asked: "set | None" = None) -> tuple[list[str], int]:
    waiting, stacked = [], set()
    for card, trig in _state_triggers(pool):
        for path in PATHS:
            left = _left_waiting_when_the_upkeep_ended(
                pool, card, trig, path, asked,
            )
            if left is None:
                continue
            if left:
                waiting.append(f"{card.name} [{path}]")
    # Which of them reach the stack at all, asked with the check switched off
    # by the caller — see the backwards test.
    return waiting, len({name.split(" [")[0] for name in waiting})


@pytest.mark.cr("500.2", "117.5")
def test_no_state_trigger_an_upkeep_effect_made_true_waits_for_the_draw_step(pool):
    waiting, _cards = _census(pool)

    assert waiting == [], waiting


@pytest.mark.cr("500.2", "603.8")
def test_the_census_names_all_ten_with_the_windows_check_switched_off(
    pool, monkeypatch,
):
    """Backwards: a window that closes on an empty stack is the tree before
    the fix, and on it every state trigger that reaches the stack is left
    waiting on every path. This is also the census's floor — what it would
    find if there were something to find."""
    monkeypatch.setattr(
        PhaseStepsMixin, "_window_may_close", lambda self, *, waits: True,
    )
    # Round 4 added a second check, between resolutions, which catches the
    # same late triggers first. The tree before both is the one with both off.
    monkeypatch.setattr(
        PhaseStepsMixin, "_check_between_resolutions", lambda self: None,
    )

    asked: set = set()
    waiting, cards = _census(pool, asked)

    assert cards >= _MIN_STACKED, waiting
    # On every path, bar the rows a path reaches by another road: a decision
    # of the card's own in the same upkeep — Darksteel Reactor's "you may put
    # a charge counter" — holds the step open on an interactive seat, and an
    # answer a driver settles runs the state check itself, which announces the
    # state trigger inside the step. Those rows are named rather than
    # allowed for by a count; one row more may still reach it unasked.
    every = {entry.split(" [")[0] for entry in waiting}
    for path in PATHS:
        named = {
            entry.split(" [")[0] for entry in waiting
            if entry.endswith(f"[{path}]")
        }
        unexplained = {
            name for name in every - named if (name, path) not in asked
        }
        assert len(unexplained) <= 1, (path, sorted(unexplained), waiting)
    assert {f"Bomb Squad [{path}]" for path in PATHS} <= set(waiting)
