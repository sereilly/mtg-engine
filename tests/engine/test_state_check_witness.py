"""The state-based checks the engine skips because the previous one already
saw the table, and the witness that says when (``engine/state_check_witness.py``).

A check runs to a fixed point, so a second check on the table the first one
left finds nothing. Two such seconds are skipped:

* **the window's closing check** (CR 117.5) straight after a resolution's own
  check or an answer's, with nothing done since
  (``PhaseStepsMixin._resolve_window_answering_prompts``);
* **a rehearsal's settle check** after a window that closed on a check, with
  nothing left to answer and nothing on the stack
  (``ai_rehearsal._settle_scratch``).

Each is held three ways here. The skip happens: the checking mode counts it
and the closing check is never asked. The check is still made where it would
act: after a resolution whose own check was not made, and after an answer
the settle takes that deals lethal damage. And **backwards**, with the skip
made to ignore what it must not, the board shows the creature the check
would have destroyed, and ``fast_paths.CHECKING``, which makes every skipped
check anyway, raises. So the instrument the seeded games are run under can
see a wrong skip.
"""

import pytest

from engine import Game, PlayerState, ai_rehearsal, fast_paths, state_check_witness
from engine.mixins.phase_steps import PhaseStepsMixin
from engine.models import Permanent
from engine.pending_choices import PendingChoice


def _table(set_pool, *, driver: bool) -> Game:
    """Seat 0's precombat main phase. *driver*: the simulator's kind of table,
    whose prompts a driver answers inside the window, so the window is
    ``_resolve_window_answering_prompts``. Without one it is a bare headless
    table, a web game's scratch copy, whose prompts are left for the caller."""
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState("P1", library=[island] * 20),
        PlayerState("P2", library=[island] * 20),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.turn = 3
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(0)
    if driver:
        game.prompt_driver = lambda table: table.auto_resolve_pending_choices()
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _bolt_at_the_bears(set_pool, *, driver: bool):
    """Lightning Bolt on the stack at an opponent's Grizzly Bears."""
    lea = set_pool("LEA")
    game = _table(set_pool, driver=driver)
    bears = _put(game, 1, lea["Grizzly Bears"])
    game.players[0].hand = [lea["Lightning Bolt"]]
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]
    return game, bears


def _an_answer_owed_that_deals_the_bears_lethal_damage(set_pool, monkeypatch):
    """A headless table, as a web game's scratch copy is, with nothing on the
    stack. The opponent's Grizzly Bears are on the battlefield, and a prompt
    is queued whose default answer marks 2 damage on them and checks nothing.

    A suspending answer resumes its resolution and checks state itself
    (``_settle_resumed_resolution``), so Mind Bomb's lethal damage, dealt once
    its discards are answered, is checked either way. A non-suspending
    answer's default is applied and closed with no check
    (``_apply_choice_default``). Which answer does what is the registry's;
    this one is written to the shape of the second, so the settle's own check
    is the one that matters."""
    game = _table(set_pool, driver=False)
    bears = _put(game, 1, set_pool("LEA")["Grizzly Bears"])
    game.pending_choices.append(PendingChoice(kind="untap_up_to", player_index=0))

    def lethal_default(self, choice):
        bears.damage_marked += 2

    monkeypatch.setattr(Game, "take_choice_default", lethal_default)
    return game, bears


@pytest.fixture
def checking(monkeypatch):
    monkeypatch.setattr(fast_paths, "CHECKING", True)
    monkeypatch.setattr(fast_paths, "CHECKED", {})
    return fast_paths.CHECKED


def _spy_window_close(monkeypatch) -> list:
    asked = []
    original = PhaseStepsMixin._window_may_close

    def spied(self, *, waits):
        asked.append(waits)
        return original(self, waits=waits)

    monkeypatch.setattr(PhaseStepsMixin, "_window_may_close", spied)
    return asked


def _a_resolution_taken_for_a_check(monkeypatch) -> None:
    """The defect the witness exists to rule out: a skip keyed on "an object
    resolved" rather than on "its check was made". Every resolution marks
    the watch as if its check had been made."""
    original = Game.resolve_next_object

    def marking(self, *, pause_for_choices):
        resolved = original(self, pause_for_choices=pause_for_choices)
        state_check_witness.saw(self)
        return resolved

    monkeypatch.setattr(Game, "resolve_next_object", marking)


# --- The window's closing check ----------------------------------------------------


def test_the_window_closes_on_the_resolutions_own_check(set_pool, monkeypatch, checking):
    """The Bolt resolves and its check puts the Bears in the graveyard. With
    the stack empty and nothing answered, the window's closing check would
    look at the table that check left. It is not asked. The checking mode
    makes it anyway and counts it, and it moved nothing."""
    game, bears = _bolt_at_the_bears(set_pool, driver=True)
    asked = _spy_window_close(monkeypatch)

    assert game._resolve_priority_window() is True

    assert not game.is_on_battlefield(bears)
    assert game.stack == []
    assert asked == []
    assert checking.get("window_close_after_a_check") == 1


def test_a_resolution_whose_check_was_not_made_leaves_the_window_its_own(
    set_pool, monkeypatch, checking,
):
    """With the check between resolutions switched off (a census's tree before,
    ``tests/rules/test_step_ends_after_what_triggered.py``), the Bolt resolves
    and nothing checks. The window's closing check is the one that finds the
    Bears: it is asked, and nothing is skipped."""
    monkeypatch.setattr(PhaseStepsMixin, "_check_between_resolutions", lambda self: None)
    game, bears = _bolt_at_the_bears(set_pool, driver=True)
    asked = _spy_window_close(monkeypatch)

    game._resolve_priority_window()

    assert not game.is_on_battlefield(bears)
    assert asked == [False]
    assert "window_close_after_a_check" not in checking


def test_backwards_a_resolution_taken_for_a_check_leaves_the_bears_and_is_caught(
    set_pool, monkeypatch,
):
    """Backwards: the same board with a witness that takes a resolution for a
    check. The window skips its closing check and the Bears live through it
    with 3 damage marked. Under the checking mode the skipped check is made
    and acts, and that raises."""
    monkeypatch.setattr(PhaseStepsMixin, "_check_between_resolutions", lambda self: None)
    _a_resolution_taken_for_a_check(monkeypatch)

    game, bears = _bolt_at_the_bears(set_pool, driver=True)
    game._resolve_priority_window()
    assert game.is_on_battlefield(bears) and bears.damage_marked == 3

    monkeypatch.setattr(fast_paths, "CHECKING", True)
    monkeypatch.setattr(fast_paths, "CHECKED", {})
    game, bears = _bolt_at_the_bears(set_pool, driver=True)
    with pytest.raises(RuntimeError, match="window_close_after_a_check"):
        game._resolve_priority_window()


# --- The rehearsal's settle ----------------------------------------------------------


def test_a_settle_after_a_window_that_closed_on_a_check_makes_none(set_pool, checking):
    """A headless table, as a web game's scratch copy is. The window resolves
    the Bolt and closes on its own check. Nothing is owed and the stack is
    empty, so the settle's check is skipped, and the checking mode finds it
    would have moved nothing."""
    game, bears = _bolt_at_the_bears(set_pool, driver=False)

    ai_rehearsal._settle_scratch(game)

    assert not game.is_on_battlefield(bears)
    assert checking.get("settle_after_a_closing_check") == 1


def test_a_settle_whose_answer_deals_lethal_damage_still_checks(
    set_pool, monkeypatch, checking,
):
    """The window has nothing to resolve and closes on its own check, so it
    reports the table checked. The settle then answers the queued prompt,
    which deals the Bears lethal damage. The settle's check is made, and the
    Bears are in the graveyard (CR 704.5g) before anything reads the copy."""
    game, bears = _an_answer_owed_that_deals_the_bears_lethal_damage(set_pool, monkeypatch)

    ai_rehearsal._settle_scratch(game)

    assert not game.is_on_battlefield(bears)
    assert game.pending_choices == []
    assert "settle_after_a_closing_check" not in checking


def test_backwards_a_settle_that_ignores_the_answer_reads_dead_bears_as_alive(
    set_pool, monkeypatch,
):
    """Backwards: a settle that skips on the window's mark alone, whatever it
    answered afterwards. The Bears are still on the battlefield with lethal
    damage marked when the copy is read. Under the checking mode the skipped
    check acts, and that raises."""
    monkeypatch.setattr(
        ai_rehearsal, "_settle_needs_a_check",
        lambda game, closed_on_a_check, owed: not closed_on_a_check or bool(game.stack),
    )
    game, bears = _an_answer_owed_that_deals_the_bears_lethal_damage(set_pool, monkeypatch)
    ai_rehearsal._settle_scratch(game)
    assert game.is_on_battlefield(bears) and bears.damage_marked == 2

    monkeypatch.setattr(fast_paths, "CHECKING", True)
    monkeypatch.setattr(fast_paths, "CHECKED", {})
    game, bears = _an_answer_owed_that_deals_the_bears_lethal_damage(set_pool, monkeypatch)
    with pytest.raises(RuntimeError, match="settle_after_a_closing_check"):
        ai_rehearsal._settle_scratch(game)


def test_a_window_on_an_ended_game_answers_none_so_the_settle_checks(set_pool):
    """CR 104.1: once the game is over the window does nothing
    (``game_over_guard``) and says nothing about the table. The settle reads
    that as "not closed on a check"."""
    game, _bears = _bolt_at_the_bears(set_pool, driver=False)
    game.players[1].life = 0
    game.check_state_based_actions()
    assert game.is_game_over()

    assert game._resolve_priority_window() is None
    assert ai_rehearsal._settle_needs_a_check(game, None, False)


# --- The witness itself ---------------------------------------------------------------


class _Table:
    """Anything with an identity will do: the witness compares with ``is``."""


def test_a_watch_starts_unmarked_and_only_a_check_of_its_own_table_marks_it():
    table, other = _Table(), _Table()
    with state_check_witness.watching(table) as witness:
        assert witness.checked is False
        state_check_witness.saw(other)
        assert witness.checked is False
        state_check_witness.saw(table)
        assert witness.checked is True
        state_check_witness.changed(table)
        assert witness.checked is False
    # Outside every watch a check marks nothing and raises nothing.
    state_check_witness.saw(table)
    state_check_witness.changed(table)


def test_a_watch_inside_another_leaves_the_outer_one_as_it_was():
    """A rehearsal's copy is watched inside the real table's priority offer,
    and a window run inside a resolution is watched inside the window that
    called it. Neither one's checks mark the outer watch. A change to a table
    unmarks every watch of it."""
    table, copy = _Table(), _Table()
    with state_check_witness.watching(table) as outer:
        state_check_witness.saw(table)
        with state_check_witness.watching(copy) as inner:
            state_check_witness.saw(table)  # not the innermost watch's table
            state_check_witness.saw(copy)
            assert inner.checked is True
        assert outer.checked is True

        outer.checked = False
        with state_check_witness.watching(table) as nested:
            state_check_witness.saw(table)
            assert nested.checked is True
        assert outer.checked is False, "a nested watch of the same table leaked its mark"

        state_check_witness.saw(table)
        with state_check_witness.watching(copy):
            state_check_witness.changed(table)
        assert outer.checked is False
