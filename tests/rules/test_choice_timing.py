"""CR 608.2d vs CR 700.2 — *when* a choice between alternatives is made.

Two rules, two moments:

* **CR 700.2** — "A spell or ability is modal if it has two or more options in
  a **bulleted list** preceded by instructions for a player to choose a number
  of those options, such as 'Choose one —'." Only such an ability chooses as it
  is put on the stack (CR 700.2a for an activated ability, 700.2b for a
  triggered one).
* **CR 608.2d** — "If an effect of a spell or ability offers any choices other
  than choices already made as part of … putting the spell or ability on the
  stack, the player announces these **while applying the effect**."

"Target creature loses first strike **or** swampwalk" (Urborg) is the second
kind: no bullets, so not modal, so the choice is made at resolution. The engine
lowered both kinds onto one ``choose_one`` instruction and the push path asked
every top-level one at activation — nine shipped abilities, seven activated and
two upkeep triggers. The observable difference is the opponent's response: a
player who chose at activation cannot answer it with the other alternative.
``modal_triggers.MODAL_HEAD_KEY`` is the mark only a bulleted head carries.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import _nosick, resolve_stack


def _w2g5_sponge_versus_bears(set_pool):
    """Walking Sponge for seat 0; Grizzly Bears and a Jump for seat 1. Both
    seats interactive, so each spell and ability waits on the stack for its
    turn and every choice is asked rather than defaulted."""
    sponge = _nosick(Permanent(card=set_pool("ULG")["Walking Sponge"]))
    bears = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[sponge]),
        PlayerState(name="P1", battlefield=[bears], hand=[set_pool("LEA")["Jump"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    return game, sponge, bears  # _w2g5_sponge_versus_bears


@pytest.mark.cr("608.2d", "700.2")
def test_an_or_choice_is_not_asked_when_the_ability_is_activated(set_pool):
    """"{T}: Target creature loses **your choice of** flying, first strike, or
    trample until end of turn." The target is announced (CR 602.2b) and the
    ability goes on the stack with the choice still open."""
    game, _, _ = _w2g5_sponge_versus_bears(set_pool)

    result = game.queue_permanent_ability(
        0, "Walking Sponge", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    assert [item.card.name for item in game.stack] == ["Walking Sponge"]
    assert game.pending_choices == [], "nothing is chosen at activation"


@pytest.mark.cr("608.2d")
def test_the_choice_answers_a_response_made_after_activation(set_pool):
    """The point of the rule. Seat 1 responds by giving its Bears flying; the
    Sponge's controller, asked only now, takes flying away — the alternative
    that did not exist when the ability was activated."""
    game, _, bears = _w2g5_sponge_versus_bears(set_pool)
    assert game.queue_permanent_ability(
        0, "Walking Sponge", target_player_index=1, target_permanent_index=0
    ).supported
    assert game.queue_from_hand(
        1, "Jump", target_player_index=1, target_permanent_index=0
    ).supported

    # Both passes go through the priority path's resolution, which keeps an
    # object that stops to ask on the stack until it is answered (CR 608.2).
    game.resolve_top_of_stack(pause_for_choices=True)  # Jump
    assert game._has_keyword(bears, "flying")
    game.resolve_top_of_stack(pause_for_choices=True)  # the Sponge, which now asks

    (prompt,) = game.pending_choices
    assert (prompt.kind, prompt.player_index) == ("mode_choice", 0)
    assert prompt.data["labels"] == ["flying", "first strike", "trample"]
    assert [item.card.name for item in game.stack] == ["Walking Sponge"], (
        "the ability is still resolving while the choice is owed (CR 608.2)"
    )
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=0)
    resolve_stack(game)

    assert not game._has_keyword(bears, "flying")
    assert game.stack == []


@pytest.mark.cr("608.2d", "602.2b")
def test_the_target_announced_at_activation_is_the_one_the_choice_acts_on(set_pool):
    """"Put a +0/+1 counter **or** a +1/+0 counter on target creature." (Dwarven
    Armorer.) The target was chosen at activation and the kind of counter at
    resolution — two decisions at two moments, and the second must not re-ask
    the first."""
    armorer = _nosick(Permanent(card=set_pool("FEM")["Dwarven Armorer"]))
    bears = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[armorer], hand=[set_pool("LEA")["Forest"]]),
        PlayerState(name="P1", battlefield=[bears]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    assert game.queue_permanent_ability(
        0, "Dwarven Armorer", target_player_index=1, target_permanent_index=0
    ).supported
    assert game.pending_choices == []

    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    resolve_stack(game)

    assert (bears.effective_power, bears.effective_toughness) == (3, 2)
    assert (armorer.effective_power, armorer.effective_toughness) == (0, 2), (
        "the counter went to the target, not the Armorer"
    )


@pytest.mark.cr("608.2d", "603.3")
def test_an_upkeep_trigger_that_says_choose_chooses_as_it_resolves(set_pool):
    """"At the beginning of your upkeep, choose flying, first strike, trample,
    or rampage 3. Gabriel Angelfire gains that ability until your next
    upkeep." "Choose" is an instruction of the effect, not a bulleted head, so
    the trigger goes on the stack with nothing chosen (CR 603.3) and asks as it
    resolves."""
    gabriel = Permanent(card=set_pool("LEG")["Gabriel Angelfire"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[gabriel]), PlayerState(name="P1"),
    ])
    game.interactive_seats = {0}

    game.start_turn(0)

    # The trigger went on the stack with nothing asked and has *resolved* up to
    # the choice: it is held there, resolving, while the answer is owed
    # (CR 608.2, CR 117.3b). Asked at the push instead, it would be waiting to
    # finish being put on the stack and would not have begun to resolve.
    (item,) = game.stack
    assert item.card.name == "Gabriel Angelfire" and item.resolution_held
    assert "Gabriel Angelfire ability is resolving, awaiting a choice" in game.log
    (prompt,) = game.pending_choices
    assert prompt.data["labels"] == ["flying", "first strike", "trample", "rampage 3"]
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=2)
    resolve_stack(game)
    assert game._has_keyword(gabriel, "trample")
    assert not game._has_keyword(gabriel, "flying")


@pytest.mark.cr("700.2b")
def test_a_bulleted_trigger_still_chooses_as_it_goes_on_the_stack(set_pool):
    """The control. Elder Gargaroth's "choose one —" is modal, and CR 700.2b
    still has its mode chosen as the ability is put on the stack — the mark
    that moved the nine abilities above is on this head and only on heads
    like it."""
    gargaroth = _nosick(Permanent(card=set_pool("M21")["Elder Gargaroth"]))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[gargaroth]), PlayerState(name="P1"),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    game.interactive_seats = {0}

    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg

    prompts = [c for c in game.pending_choices if c.kind == "mode_choice"]
    assert len(prompts) == 1
    assert prompts[0].data.get("_trigger_item") is not None, (
        "armed at the push, on the stack object"
    )
