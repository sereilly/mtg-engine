"""Regressions: "put **that many** counters" placed zero under a trigger.

Found at Mercadian Masques wave 2 while building Blood Hound ("Whenever you're
dealt damage, you may put that many +1/+1 counters on this creature"), and the
two cards below are the *shipped* pool paying for the same reading.

A bare "that much"/"that many" has three possible producers, and the counter
lowerings only ever read one of them. ``recorded_count_spec`` answers a **named**
producer ("for each card discarded this way"); the resolution **scratchpad**
answers a sentence whose own earlier step wrote a number (Tetravus's exile);
and the third — the number the **firing event** carried, frozen into the
trigger's context by the fire site (CR 603.10) — had no reader here at all.
``_events._EVENT_QUANTITIES`` is the table that names it, and a comment in that
table already said what happens without it: "reading a trigger's number out of
the scratchpad silently yields zero".

So both cards below resolved, logged themselves done, and placed **nothing**:

* **Light of Promise** (M21) grants the creature it enchants "Whenever you gain
  life, put that many +1/+1 counters on this creature". A triggered ability
  whose whole effect is one sentence has no earlier step to have written the
  scratchpad key, so the creature stayed the size it was however much life its
  controller gained.
* **Living Artifact** (LEA through 5ED) prints "Whenever you're dealt damage,
  put that many vitality counters on this Aura" — the same sentence with a
  CR 122.1 named counter. Its *whole first line* was doing nothing, and the
  second line ("remove a vitality counter: you gain 1 life") had nothing to
  spend, so the card was inert in six shipped sets.

Neither was visible to a static instrument. Both cards compiled supported, both
abilities carried real instructions, and the census has no way to ask whether an
instruction's number is the right one — only running them could see it.

The fix is one channel in three places: ``_events.trigger_quantity_key`` names
the key an event freezes its number under, the two counter lowerings emit it as
``amount_from_trigger`` when the trigger has one, and the two handlers read the
trigger's context instead of the scratchpad. A card with no such event keeps the
scratchpad read byte for byte, which is what leaves Tetravus untouched.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.damage_events import deal_damage
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import _nosick, resolve_stack


def _tm_game():
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


@pytest.mark.cr("603.10")
def test_light_of_promise_places_the_life_it_gained(catalog_by_name):
    """The granted trigger's number is the life gain the event carried."""
    game, p1, p2 = _tm_game()
    bears = _nosick(Permanent(card=catalog_by_name["Grizzly Bears"]))
    p1.battlefield.append(bears)
    aura = Permanent(card=catalog_by_name["Light of Promise"])
    p1.battlefield.append(aura)
    attach_aura(aura, bears)
    game.check_state_based_actions()
    # The ability really is on the creature: it is granted text, so the
    # compiler builds it off `effective_card` rather than off the printed one.
    assert "put that many +1/+1 counters" in bears.effective_card.oracle_text.lower()

    game._gain_life(p1, 3)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)


@pytest.mark.cr("122.1")
def test_living_artifact_accumulates_the_damage_you_were_dealt(catalog_by_name):
    """The same sentence with a named counter, on a card shipped six times."""
    game, p1, p2 = _tm_game()
    host = Permanent(card=catalog_by_name["Mox Ruby"])
    p1.battlefield.append(host)
    aura = Permanent(card=catalog_by_name["Living Artifact"])
    p1.battlefield.append(aura)
    attach_aura(aura, host)
    game.check_state_based_actions()

    deal_damage(game, {"recipient": p1, "amount": 4, "source": None})
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert counters_on(aura, "vitality") == 4


@pytest.mark.cr("608.2")
def test_tetravus_still_reads_its_own_earlier_step(catalog_by_name):
    """The scratchpad reading, unchanged.

    Tetravus's upkeep ability exiles any number of its own tokens and *then*
    puts that many counters on itself — an earlier step of the same resolution,
    which is the producer the scratchpad key was written for. Its trigger is an
    upkeep, which carries no number of its own, so the fix must leave this
    payload exactly as it was.
    """
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(catalog_by_name["Tetravus"])
    placements = [
        step
        for trigger in program.triggered_abilities
        for step in (trigger.instruction.payload.get("then") or ())
        if step.kind == "add_counter_to_self"
    ]
    assert placements, "Tetravus should still compile its counter placement"
    for step in placements:
        assert step.payload["count"] == "trigger_count"
        assert "amount_from_trigger" not in step.payload
