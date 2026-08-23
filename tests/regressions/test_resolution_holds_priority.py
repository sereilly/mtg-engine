"""Regression: a resolution that stops to ask reported itself resolved.

Reported in-game against Sanctum of All. "At the beginning of your upkeep, you
may search your library and/or graveyard for a Shrine card…" went on the stack,
both players passed, and the log said *"Sanctum of All ability resolved"* while
the "you may" prompt was still on screen unanswered. Saying yes then took the
ability off the stack and armed the search — so the search was answered with
nothing resolving, and the object the decision belonged to was gone.

Underneath was a general shape, not a card. ``resolve_top_of_stack`` held an
object on the stack for exactly three prompts named by hand — the optional pay,
Power Sink's payment, Word of Command's card — and ``pass_priority`` named the
same three again when deciding who got the priority window. Every other prompt
armed mid-resolution fell through: the object popped, CR 117.3b's "after a
spell or ability resolves" was applied to a resolution that had not finished,
and only the action gate (which refuses by *seat*, not by whose turn it is) kept
the board from being played around. A prompt armed by *answering* another one
fell through even for the three, which is the Sanctum path exactly.

The link is a property of the queue now: a prompt armed while something is
resolving records that object, and the object leaves the stack when the last of
them is answered. These tests are written to fail on the old engine — the first
on the log line and on the stack going empty a decision early, the rest on the
generalization to prompts nobody had named.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState


def _upkeep_with(pool, name, *, library=(), interactive=True):
    """A game at *name*'s controller's upkeep, its trigger on the stack."""
    source = Permanent(card=pool[name])
    p1 = PlayerState(name="P1", battlefield=[source], library=[*library])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game.active_player_index = 0
    game.resolve_upkeep(0, defer_priority=True)
    return game, source


def _both_pass(game):
    game.pass_priority(0)
    return game.pass_priority(1)


# ---------------------------------------------------------------------------
# The reported card
# ---------------------------------------------------------------------------

class TestSanctumOfAll:
    def test_the_ability_waits_on_stack_for_the_optional_prompt(self, set_pool):
        pool = set_pool("M21")
        game, _ = _upkeep_with(
            pool, "Sanctum of All", library=[pool["Sanctum of Tranquil Light"]]
        )

        result = _both_pass(game)

        assert result == "awaiting_choice"
        assert [item.card.name for item in game.stack] == ["Sanctum of All"]
        assert [c.kind for c in game.pending_choices] == ["optional_pay"]
        # The log is the half the player saw. "Resolved" is a claim about a
        # resolution that is over, and this one has not searched anything yet.
        assert "Sanctum of All ability resolved" not in game.log
        assert any("awaiting a choice" in line for line in game.log)

    def test_saying_yes_hands_over_to_the_search_without_resolving(self, set_pool):
        pool = set_pool("M21")
        game, _ = _upkeep_with(pool, "Sanctum of All", library=[pool["Sanctum of Tranquil Light"]])
        _both_pass(game)

        assert game.confirm_optional_pay(0, accept=True)

        # The ability is one step further into the same resolution, not done.
        assert [item.card.name for item in game.stack] == ["Sanctum of All"]
        assert [c.kind for c in game.pending_choices] == ["search_library"]
        assert "Sanctum of All finished resolving" not in game.log

    def test_the_ability_leaves_only_when_the_last_decision_is_made(self, set_pool):
        pool = set_pool("M21")
        game, _ = _upkeep_with(pool, "Sanctum of All", library=[pool["Sanctum of Tranquil Light"]])
        _both_pass(game)
        game.confirm_optional_pay(0, accept=True)

        assert game.confirm_search_library(0, 0, zone="library")

        assert game.stack == []
        assert game.pending_choices == []
        assert "Sanctum of Tranquil Light" in [p.card.name for p in game.players[0].battlefield]
        assert "Sanctum of All finished resolving" in game.log

    def test_declining_finishes_the_resolution_at_once(self, set_pool):
        pool = set_pool("M21")
        game, _ = _upkeep_with(pool, "Sanctum of All", library=[pool["Sanctum of Tranquil Light"]])
        _both_pass(game)

        assert game.confirm_optional_pay(0, accept=False)

        # Nothing else was asked, so the ability is genuinely finished.
        assert game.stack == []
        assert game.pending_choices == []
        assert "Sanctum of All finished resolving" in game.log

    def test_a_non_interactive_seat_still_resolves_it_in_one_pass(self, set_pool):
        """The headless/AI path is unchanged: no prompt is held for a seat that
        answers with its default, and the deterministic run is the same run."""
        pool = set_pool("M21")
        game, _ = _upkeep_with(
            pool, "Sanctum of All", library=[pool["Sanctum of Tranquil Light"]], interactive=False
        )
        game.resolve_stack()
        game.auto_resolve_pending_choices()

        assert game.stack == []
        assert game.pending_choices == []


# ---------------------------------------------------------------------------
# The generalization: a prompt nobody named holds the resolution too
# ---------------------------------------------------------------------------

class TestAnyPromptHoldsTheResolution:
    def test_a_spell_whose_search_is_armed_directly_waits_too(self, set_pool):
        """Sanctum of All reaches its search through a "you may", which was one
        of the three kinds held by name. Demonic Tutor arms the same prompt
        straight from its instruction, and so used to leave the stack with the
        search unanswered — "Search your library for a card" reported as done
        before a card had been looked for."""
        pool = set_pool("LEA")
        p1 = PlayerState(
            name="P1", hand=[pool["Demonic Tutor"]], library=[pool["Black Lotus"]]
        )
        game = Game(players=[p1, PlayerState(name="P2")])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game.active_player_index = 0
        assert game.queue_from_hand(0, "Demonic Tutor").supported
        game.start_priority_window(0)

        result = _both_pass(game)

        assert result == "awaiting_choice"
        assert [item.card.name for item in game.stack] == ["Demonic Tutor"]
        assert [c.kind for c in game.pending_choices] == ["search_library"]
        # And the seat that owes the decision holds the window, rather than the
        # active player CR 117.3b would have handed it to had this resolved.
        assert game.priority_player_index == game.pending_choices[0].player_index

        assert game.confirm_search_library(0, 0, zone="library")
        assert game.stack == []
        assert [c.name for c in p1.hand] == ["Black Lotus"]

    def test_the_held_object_is_never_resolved_twice(self, set_pool):
        """The backstop. A held object has already run its instructions, so a
        further priority pass may only take it off the stack — re-resolving it
        would search, discard or destroy a second time."""
        pool = set_pool("M21")
        game, _ = _upkeep_with(pool, "Sanctum of All", library=[pool["Sanctum of Tranquil Light"]])
        _both_pass(game)
        held = game.stack[-1]
        assert held.resolution_held

        # Drop the prompt without going through an answer path at all.
        game.pending_choices.clear()
        assert game.resolve_top_of_stack(pause_for_choices=True) is True

        assert game.stack == []
        assert game.log.count("Sanctum of All ability is resolving, awaiting a choice") == 1
