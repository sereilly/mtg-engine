"""A table whose prompts a driver answers holds the resolving object for the
answer, as the web does (CR 608.2: an object stays on the stack until it has
finished resolving; CR 704.3 names no moment inside a resolution).

The simulator's ``prompt_driver`` was asked between one object and the next,
but the object that armed the prompt had already resolved straight through:
popped off the stack, a state-based check made, the abilities its destructions
triggered announced — and only then the answer. Measured at the base of round
``kg3`` over eight seeded Legions and Onslaught games (outside rehearsals): 41
resolutions armed a prompt that holds priority, all 41 held nothing, a
state-based check was made with each one owed, and one of those checks acted
before the answer. Now the table holds for the driver
(``Game.holds_for_answers``), the driver answers at the top of the loop with
the object on the stack, and the answer releases it (``_release_stack_item``):
41 of 41 held, no check made while one was owed.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.mixins.stack.choices.queue import PendingChoicesMixin
from engine.models import Permanent

_CARDS = {card.name: card for card in load_catalog()}


def card(name: str):
    return _CARDS[name]


def names(cards) -> list[str]:
    return [c.name for c in cards]


def driven(*, hands, boards=((), ())):
    """A headless two-seat game whose prompts a recording driver answers with
    each kind's default, the way the simulator's does."""
    seen: list[dict] = []

    def driver(game: Game) -> None:
        seen.append({
            "stack": [(item.card.name, item.resolution_held) for item in game.stack],
            "owed": [choice.kind for choice in game.pending_choices],
            "log": list(game.log),
        })
        game.auto_resolve_pending_choices()

    players = []
    for seat in range(2):
        battlefield = []
        for name in boards[seat]:
            permanent = Permanent(card=card(name))
            permanent.metadata["summoning_sickness_turn"] = -99
            battlefield.append(permanent)
        players.append(PlayerState(
            name=f"P{seat}",
            hand=[card(n) for n in hands[seat]],
            library=[card("Island")] * 8,
            battlefield=battlefield,
        ))
    game = Game(players=players, prompt_driver=driver)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, seen


def test_the_driver_answers_with_the_spell_still_on_the_stack():
    game, seen = driven(hands=(("Mind Rot",), ("Grizzly Bears", "Shock", "Forest")))
    game.cast_from_hand(0, "Mind Rot", target_player_index=1)

    assert seen, "the driver was never asked"
    first = seen[0]
    assert first["owed"] == ["discard"]
    assert first["stack"] == [("Mind Rot", True)]
    assert not any("Mind Rot finished resolving" in line for line in first["log"])
    # The answer released it: once, at the end, with the discard made — one
    # closing line, which says where the card went as well.
    assert not game.stack and not game.pending_choices
    assert sum("Mind Rot finished resolving" in line for line in game.log) == 1
    assert game.log.count("Mind Rot finished resolving and moved to graveyard") == 1
    assert len(game.players[1].hand) == 1
    assert "Mind Rot" in names(game.players[0].graveyard)


def test_power_sinks_payment_reaches_the_driver_and_takes_the_same_default():
    """Power Sink's "counter it unless its controller pays {X}" used to be
    answered from inside ``resolve_top_of_stack`` (``_auto_resolve_mana_payment``)
    on any table that was not interactive. Held, it reaches the driver like
    any prompt, whose default is that same answer: no way to pay, countered."""
    game, seen = driven(hands=(("Power Sink",), ("Lightning Bolt",)), boards=((), ()))
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.cast_from_hand(0, "Power Sink", target_stack_index=0, x_value=3)

    asked = [entry for entry in seen if "mana_payment" in entry["owed"]]
    assert asked, "the payment never reached the driver"
    assert asked[0]["stack"][-1] == ("Power Sink", True)
    assert "Lightning Bolt" in names(game.players[1].graveyard)
    assert game.players[0].life == 20
    assert not game.stack


def test_backwards_with_the_old_derivation_the_driver_finds_the_stack_empty(monkeypatch):
    monkeypatch.setattr(
        PendingChoicesMixin, "holds_for_answers", lambda self: bool(self.interactive_seats)
    )
    game, seen = driven(hands=(("Mind Rot",), ("Grizzly Bears", "Shock", "Forest")))
    game.cast_from_hand(0, "Mind Rot", target_player_index=1)

    assert seen and seen[0]["owed"] == ["discard"]
    assert seen[0]["stack"] == []


@pytest.mark.full
def test_a_seeded_run_holds_for_its_driver_and_raises_no_rehearsal():
    """Over a seeded Legions batch: at least one object was held on the stack
    when the driver was asked (the subject exercised, a floor of one), no
    state-based check was made while a resolution waited on its answer, and
    no rehearsal raised — the rehearsal copies carry the driver
    (``ai_scratch_copy.scratch_copy``), so they hold too."""
    from engine import ai_rehearsal, ai_simulator
    from engine.card_loader import manifest_set_paths

    held_when_asked = []
    checked_while_waiting = []
    original_drive = PendingChoicesMixin.drive_owed_prompts
    original_check = Game.check_state_based_actions

    def drive(self):
        if self.prompt_driver is not None and not ai_rehearsal.rehearsing():
            if self.pending_choices and any(item.resolution_held for item in self.stack):
                held_when_asked.append(self.turn)
        return original_drive(self)

    def check(self):
        if (
            self.prompt_driver is not None
            and not ai_rehearsal.rehearsing()
            and self.resolution_waiting()
        ):
            checked_while_waiting.append(self.turn)
        return original_check(self)

    paths = {path.stem.split("_")[0]: path for path in manifest_set_paths()}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PendingChoicesMixin, "drive_owed_prompts", drive)
        patch.setattr(Game, "check_state_based_actions", check)
        report = ai_simulator.run_ai_simulation(str(paths["LGN"]), games=4, seed=7)

    assert report.interaction_count > 0
    assert held_when_asked, "no object was held for the driver in the whole batch"
    assert checked_while_waiting == []
    assert not report.rehearsals_raised, report.rehearsals_raised
