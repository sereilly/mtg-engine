"""Judgment's four triggers that no label row named, sent as triggered abilities.

A stack item's ``is_triggered`` comes from its label's ``triggered_`` prefix
(``web/serialization._serialize_stack_item``), so a trigger whose instruction
kind no ``TRIGGERED_LABELS`` row (nor a ``TRIGGERED_LABELS_BY_CONDITION`` pair)
names reaches the client as ``spell_pattern`` — something other than a
triggered ability. Found at Judgment's promotion rehearsal, by
``test_no_grammar_read_ability_falls_back_to_the_category_default`` once the
set shipped; Torment's Hypnox exactly (``test_hypnox_trigger_wire_ui_api.py``).

Each trigger is fired through its real seam — a cast, an exile, combat damage,
the beginning of combat — read off the wire while it waits on the stack, and
resolved to what it prints.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import declare_attack, resolve_stack
from web.serialization import _serialize_stack_item


def _table(set_pool, *, hand=(), libraries=None):
    lea = set_pool("LEA")
    libraries = libraries or ([lea["Island"]] * 5, [lea["Forest"]] * 5)
    game = Game(players=[
        PlayerState("P0", library=list(libraries[0]), hand=list(hand)),
        PlayerState("P1", library=list(libraries[1])),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _put(game, card, seat):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _waiting_trigger(game, name):
    trigger = game.stack[-1]
    assert trigger.is_ability and trigger.card.name == name, [
        (item.card.name, item.is_ability) for item in game.stack
    ]
    wire = _serialize_stack_item(trigger, game)
    assert wire["is_triggered"] is True, trigger.ability_effect_kind
    return trigger


def test_wormfang_manta_s_skip_and_extra_turn_are_sent_as_triggered(set_pool):
    """"When this creature enters, you skip your next turn." and "When this
    creature leaves the battlefield, you take an extra turn after this one."
    (``skip_next_turn`` and ``grant_extra_turn``, each ``triggered_turn``.)"""
    lea, jud = set_pool("LEA"), set_pool("JUD")
    game = _table(set_pool, hand=[jud["Wormfang Manta"], lea["Swords to Plowshares"]])
    game.start_turn(0)

    assert game.queue_from_hand(0, "Wormfang Manta").supported
    game.resolve_top_of_stack()
    _waiting_trigger(game, "Wormfang Manta")
    resolve_stack(game)
    assert game.skip_turn_counts.get(0) == 1

    manta = next(p for p in game.controlled_by(0) if p.card.name == "Wormfang Manta")
    assert game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[manta.permanent_id],
    ).supported
    game.resolve_top_of_stack()
    _waiting_trigger(game, "Wormfang Manta")
    resolve_stack(game)
    assert game.extra_turns.get(0) == 1


def test_scalpelexis_s_repeated_exile_is_sent_as_triggered(set_pool):
    """"Whenever this creature deals combat damage to a player, that player
    exiles the top four cards of their library. If two or more of those cards
    have the same name, repeat this process." (``repeat_process_while``,
    ``triggered_repeated``.) Two Islands in the first four repeat it once."""
    lea, jud = set_pool("LEA"), set_pool("JUD")
    names = ("Island", "Island", "Forest", "Mountain", "Plains", "Swamp",
             "Lightning Bolt", "Hill Giant", "Grizzly Bears")
    game = _table(set_pool, libraries=(
        [lea["Island"]] * 5, [lea[name] for name in names],
    ))
    game.start_turn(0)
    _put(game, jud["Scalpelexis"], 0)
    declare_attack(game, 0)
    # The damage pass alone: stepping the combat phase would also give the
    # step's priority window, which resolves the trigger before it is read.
    game.current_step = "combat_damage"
    assert game.resolve_combat_damage(0)[0]

    assert game.players[1].life == 19
    _waiting_trigger(game, "Scalpelexis")
    resolve_stack(game)
    assert [card.name for card in game.players[1].exile] == list(names[:8])
    assert [card.name for card in game.players[1].library] == ["Grizzly Bears"]


def test_web_of_inertia_s_offer_is_sent_as_triggered(set_pool):
    """"At the beginning of combat on each opponent's turn, that player may
    exile a card from their graveyard. If the player doesn't, creatures they
    control can't attack you this turn." (``may`` under
    ``combat_opponent_turn``, ``triggered_combat``.) With an empty graveyard
    there is nothing to pay with, and the Hill Giant stays home."""
    lea, jud = set_pool("LEA"), set_pool("JUD")
    game = _table(set_pool)
    _put(game, jud["Web of Inertia"], 0)
    giant = _put(game, lea["Hill Giant"], 1)
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_step == "beginning_of_combat"

    _waiting_trigger(game, "Web of Inertia")
    resolve_stack(game)
    assert not game.can_attack(giant, 0)
