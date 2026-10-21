"""A stack item's ``is_triggered`` comes from its label's ``triggered_``
prefix (``web/serialization._serialize_stack_item``), so a trigger whose
instruction kind no ``TRIGGERED_LABELS`` row names reaches the client as
something other than a triggered ability.

"When this creature enters, if you cast it from your hand, exile all cards
from target opponent's hand. When this creature leaves the battlefield,
return the exiled cards to their owner's hand." (Hypnox, Torment.) Its entry
trigger compiled to ``exile_hand_pile``, which no row named, so it was
labelled ``spell_pattern`` and sent as ``is_triggered: False``. Found at
Torment's promotion rehearsal, as the effect-labels guard's second assert —
shown only once its first (Major Teroh) was answered — and the Planeshift
rehearsal's two entry triggers exactly.
"""

from __future__ import annotations

from engine import Game, PlayerState
from tests.helpers import resolve_stack
from web.serialization import _serialize_stack_item


def test_hypnox_s_entry_trigger_is_sent_as_a_triggered_ability(set_pool):
    lea, tor = set_pool("LEA"), set_pool("TOR")
    game = Game(players=[
        PlayerState("P0", library=[lea["Swamp"]] * 5, hand=[tor["Hypnox"]]),
        PlayerState(
            "P1", library=[lea["Island"]] * 5,
            hand=[lea["Lightning Bolt"], lea["Counterspell"], lea["Forest"]],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    assert game.queue_from_hand(0, "Hypnox", target_player_index=1).supported
    game.resolve_top_of_stack()

    trigger = game.stack[-1]
    assert trigger.is_ability and trigger.card.name == "Hypnox"
    wire = _serialize_stack_item(trigger, game)
    assert wire["is_triggered"] is True, trigger.ability_effect_kind

    resolve_stack(game)
    assert game.players[1].hand == []
    assert sorted(c.name for c in game.players[1].exile) == [
        "Counterspell", "Forest", "Lightning Bolt",
    ]
