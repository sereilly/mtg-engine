"""Regression: a spell held on the stack for a prompt was also in the graveyard.

The round that made a resolution wait for its prompts (CR 608.2, CR 117.3b —
``tests/regressions/test_resolution_holds_priority.py``) kept the stack object
on the stack, but a *spell's* card had already gone to the graveyard by then:
``finish`` binned it at the end of the instructions, and the object was pushed
back afterwards. For a suspending prompt (a search, a scry) ``run_resumable``
holds ``finish`` back, so those were right. For every other holding prompt —
Mind Rot's discard, Power Sink's payment, Balance's removals — the card sat in
two zones at once, and the log read "resolved and moved to graveyard" with the
decision still on screen.

CR 608.2n: the card goes to the graveyard as the *last* step of resolution.
The step is now handed to the held object and run when its last prompt is
answered; the same release restores the priority CR 117.3b gives the active
player, after the CR 704.3 check.
"""

from __future__ import annotations

from engine import Game
from engine.models import PlayerState


def _duel(pool, caster_hand, target_hand=(), *, interactive=(0, 1)):
    p1 = PlayerState(name="P1", hand=[pool[n] for n in caster_hand])
    p2 = PlayerState(name="P2", hand=[pool[n] for n in target_hand])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"
    return game, p1, p2


def _cast_and_pass(game, caster, name, **cast):
    assert game._cast_onto_stack(caster, name, **cast).supported
    game.priority_player_index = 0
    game.pass_priority(0)
    return game.pass_priority(1)


class TestMindRot:
    def test_the_card_is_on_the_stack_only_while_the_discard_is_owed(self, set_pool):
        pool = set_pool("M21")
        game, p1, p2 = _duel(pool, ["Mind Rot"], ["Opt", "Storm Caller", "Forest"])

        result = _cast_and_pass(game, 0, "Mind Rot", target_player_index=1)

        assert result == "awaiting_choice"
        assert [(item.card.name, item.resolution_held) for item in game.stack] == [("Mind Rot", True)]
        assert p1.graveyard == []
        assert [c.kind for c in game.pending_choices] == ["discard"]
        assert not any("moved to graveyard" in line for line in game.log)
        assert any("Mind Rot is resolving, awaiting a choice" in line for line in game.log)

    def test_answering_bins_the_card_and_hands_priority_back(self, set_pool):
        pool = set_pool("M21")
        game, p1, p2 = _duel(pool, ["Mind Rot"], ["Opt", "Storm Caller", "Forest"])
        _cast_and_pass(game, 0, "Mind Rot", target_player_index=1)
        assert game.priority_player_index == 1  # the seat that owes the answer

        assert game.resolve_pending_choice("discard", 1, hand_indices=[0, 1], to_library=False)

        assert game.stack == []
        assert [c.name for c in p1.graveyard] == ["Mind Rot"]
        assert [c.name for c in p2.hand] == ["Forest"]
        # The graveyard is the last step, and the log says so in that order.
        binned = game.log.index("Mind Rot resolved and moved to graveyard")
        assert binned > game.log.index("P2 discarded Opt")
        assert game.log.index("Mind Rot finished resolving") > binned
        # CR 117.3b, now that the resolution is over.
        assert game.priority_player_index == game.active_player_index == 0
        assert game.priority_pass_count == 0

    def test_a_non_interactive_targets_default_releases_it_the_same_way(self, set_pool):
        """An AI seat's discard stays queued until the drain takes its default
        (the web layer's ``_auto_resolve_ai_pending``), so the spell is held
        for exactly as long as a human's would be — and the default answer goes
        through the same release, bin included."""
        pool = set_pool("M21")
        game, p1, p2 = _duel(
            pool, ["Mind Rot"], ["Opt", "Storm Caller", "Forest"], interactive=(0,)
        )

        result = _cast_and_pass(game, 0, "Mind Rot", target_player_index=1)
        assert result == "awaiting_choice"
        assert p1.graveyard == []

        game.auto_resolve_pending_choices(only_player_index=1)

        assert game.stack == []
        assert [c.name for c in p1.graveyard] == ["Mind Rot"]
        assert len(p2.hand) == 1
        assert game.pending_choices == []
        assert game.priority_player_index == 0


class TestPowerSink:
    def test_the_counterspell_waits_for_the_payment_before_it_is_binned(self, set_pool):
        pool = set_pool("LEA")
        game, p1, p2 = _duel(pool, ["Power Sink"], ["Grizzly Bears"])
        assert game._cast_onto_stack(1, "Grizzly Bears").supported
        assert game._cast_onto_stack(0, "Power Sink", target_stack_index=0, x_value=2).supported
        game.priority_player_index = 0
        game.pass_priority(0)
        result = game.pass_priority(1)

        assert result == "awaiting_choice"
        assert [c.kind for c in game.pending_choices] == ["mana_payment"]
        assert [item.card.name for item in game.stack] == ["Grizzly Bears", "Power Sink"]
        assert game.stack[-1].resolution_held is True
        assert p1.graveyard == []

        assert game.resolve_pending_choice("mana_payment", 1, pay=False)

        # Declined: the Bears are countered, the Sink is binned, nothing is held.
        assert [c.name for c in p1.graveyard] == ["Power Sink"]
        assert [c.name for c in p2.graveyard] == ["Grizzly Bears"]
        assert game.stack == []
        assert game.priority_player_index == 0


class TestBalance:
    def test_each_players_removals_are_answered_before_the_card_leaves_the_stack(self, set_pool):
        pool = set_pool("LEA")
        game, p1, p2 = _duel(pool, ["Balance"], ["Grizzly Bears", "Llanowar Elves"])

        result = _cast_and_pass(game, 0, "Balance", target_player_index=1)

        assert result == "awaiting_choice"
        assert [c.kind for c in game.pending_choices] == ["balance"]
        assert [item.card.name for item in game.stack] == ["Balance"]
        assert p1.graveyard == []

        assert game.confirm_balance(1, land_indices=[], creature_indices=[], hand_indices=[0, 1])

        assert game.stack == []
        assert [c.name for c in p1.graveyard] == ["Balance"]
        assert p2.hand == []
        assert game.priority_player_index == 0
