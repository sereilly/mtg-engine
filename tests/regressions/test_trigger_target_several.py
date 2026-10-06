"""A triggered ability that prints several targets chooses several (PLS W2G6).

CR 603.3d routes a triggered ability's targets through CR 601.2c, which
chooses **every** target the ability prints. The ``trigger_target`` prompt
recorded one: the printed count reached the target spec (``max_targets``) and
stopped there, so "put a +1/+1 counter on each of **up to two** other target
creatures you control" (Basri's Acolyte) asked for a creature, took it, and the
second counter was nobody's to place. A cast that named both at once — this
engine names an entry trigger's targets as the permanent is cast — was the only
road to the card as printed; a reanimated Acolyte, an attack trigger (Cho-Arrim
Bruiser's "you may tap up to two target creatures") and a trigger the cast did
not announce for (Nightscape Battlemage) all got one.

The census is derived from the compiled program and carries a floor, so a
derivation that drifts to an empty population fails rather than passes.
Validated backwards: on the tree before the fix every prompt it arms carries no
``max_targets`` and every two-target answer is refused.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import KICKED, KICKED_WITH, kicker_costs
from engine.faces import compilation_units
from engine.game_types import StackItem
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_instruction_spec
from tests.helpers import _nosick, resolve_stack

#: Basri's Acolyte, Cho-Arrim Bruiser, Nightscape Battlemage (October 2026).
_MIN_SEVERAL_TARGET_TRIGGERS = 3

_BYSTANDERS = ("Grizzly Bears", "Savannah Lions", "Hill Giant")


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def _w2g6_several_target_triggers(pool) -> list:
    """``(card, trigger, printed count)`` for every supported triggered ability
    whose target description prints more than one target."""
    rows = []
    for card in pool.values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trigger in program.triggered_abilities:
            if not trigger.supported or trigger.instruction is None:
                continue
            spec = derive_instruction_spec([trigger.instruction])
            count = (spec or {}).get("max_targets")
            if isinstance(count, int) and count > 1:
                rows.append((card, trigger, count))
    return sorted(rows, key=lambda row: row[0].name)


def _w2g6_table(pool, *, humans=(0,)) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("A", library=[forest] * 10),
        PlayerState("B", library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(humans)
    return game


def _w2g6_put(game, pool, seat, name) -> Permanent:
    permanent = Permanent(card=pool[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def test_w2g6_every_several_target_trigger_is_asked_for_all_of_them(pool):
    """Each such ability, put on the stack with nothing announced and a human
    controlling it: the prompt says how many it may name, and an answer naming
    that many is the announcement the stack object then carries."""
    rows = _w2g6_several_target_triggers(pool)
    assert len(rows) >= _MIN_SEVERAL_TARGET_TRIGGERS, [row[0].name for row in rows]
    assert {"Basri's Acolyte", "Cho-Arrim Bruiser", "Nightscape Battlemage"} <= {
        card.name for card, _, _ in rows
    }

    for card, trigger, printed in rows:
        game = _w2g6_table(pool)
        for seat in (0, 1):
            for name in _BYSTANDERS:
                _w2g6_put(game, pool, seat, name)
        source = Permanent(card=card)
        # Whatever kicker the card prints was paid, so an "if it was kicked
        # with…" trigger is one this reaches (CR 702.33f).
        source.metadata[KICKED] = True
        source.metadata[KICKED_WITH] = tuple(kicker_costs(card.oracle_text or ""))
        game.players[0].battlefield.append(source)
        game._sync_control()
        item = StackItem(
            card=card, caster_index=0, target_player_index=None,
            target_permanent_index=None, x_value=None,
            ability_instruction=trigger.instruction,
            ability_effect_kind=trigger.effect_kind, source_permanent=source,
            ability_text=trigger.source_line,
        )
        assert game._stack_push(item) is item, card.name

        (asked,) = game.pending_choices
        assert asked.kind == "trigger_target", card.name
        offered = [t["permanent_id"] for t in asked.data["targets"]]
        assert len(offered) >= printed, (card.name, len(offered))
        assert asked.data.get("max_targets") == printed, card.name

        assert not game.confirm_trigger_target(
            0, permanent_ids=offered[: printed + 1]
        ), f"{card.name}: more than it prints"
        assert not game.confirm_trigger_target(
            0, permanent_ids=[offered[0], offered[0]]
        ), f"{card.name}: one object twice"
        assert not game.confirm_trigger_target(
            0, permanent_ids=[offered[0], 999_999]
        ), f"{card.name}: something never offered"
        assert not game.confirm_trigger_target(0, permanent_ids=[]), card.name
        assert game.pending_choices == [asked], "a refused answer leaves it owed"

        assert game.confirm_trigger_target(0, permanent_ids=offered[:printed]), card.name
        assert item.target_permanent_id == offered[:printed]
        assert game.pending_choices == []


def test_w2g6_basris_acolyte_put_onto_the_battlefield_counters_two(pool):
    """"Put a +1/+1 counter on each of up to two other target creatures you
    control." Put onto the battlefield (nothing was cast, so nothing was
    announced), its controller is asked for both and both get the counter."""
    game = _w2g6_table(pool)
    bears = _w2g6_put(game, pool, 0, "Grizzly Bears")
    giant = _w2g6_put(game, pool, 0, "Hill Giant")
    lions = _w2g6_put(game, pool, 0, "Savannah Lions")
    _w2g6_put(game, pool, 0, "Basri's Acolyte")

    (asked,) = game.pending_choices
    assert asked.data["max_targets"] == 2
    assert game.confirm_trigger_target(
        0, permanent_ids=[bears.permanent_id, lions.permanent_id]
    )
    resolve_stack(game)

    counters = [p.metadata.get("plus_counters", 0) for p in (bears, giant, lions)]
    assert counters == [1, 0, 1]

    # One is still a legal answer: "up to" two.
    game = _w2g6_table(pool)
    bears = _w2g6_put(game, pool, 0, "Grizzly Bears")
    giant = _w2g6_put(game, pool, 0, "Hill Giant")
    _w2g6_put(game, pool, 0, "Basri's Acolyte")
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)
    resolve_stack(game)
    assert [p.metadata.get("plus_counters", 0) for p in (bears, giant)] == [0, 1]


def test_w2g6_a_seat_nobody_asks_takes_both_of_basris_counters(pool):
    """The stated default: as many as the ability prints, on the side the
    effect wants. It took one, so an AI's reanimated Acolyte was half a card."""
    game = _w2g6_table(pool, humans=())
    bears = _w2g6_put(game, pool, 0, "Grizzly Bears")
    giant = _w2g6_put(game, pool, 0, "Hill Giant")
    theirs = _w2g6_put(game, pool, 1, "Savannah Lions")
    _w2g6_put(game, pool, 0, "Basri's Acolyte")
    resolve_stack(game)

    assert [p.metadata.get("plus_counters", 0) for p in (bears, giant)] == [1, 1]
    assert theirs.metadata.get("plus_counters", 0) == 0


def test_w2g6_cho_arrim_bruiser_taps_two_when_it_attacks(pool):
    """"Whenever this creature attacks, you may tap up to two target
    creatures." An attack trigger has no cast to have named its targets, so
    the prompt is the only place the second one can come from."""
    game = _w2g6_table(pool)
    game.start_turn(0)
    game._close_current_priority_step()
    bruiser = _nosick(_w2g6_put(game, pool, 0, "Cho-Arrim Bruiser"))
    wall = _w2g6_put(game, pool, 1, "Grizzly Bears")
    giant = _w2g6_put(game, pool, 1, "Hill Giant")
    lions = _w2g6_put(game, pool, 1, "Savannah Lions")
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert game.declare_attackers(0, [game.battlefield_index_of(bruiser)])[0]
    asked = next(c for c in game.pending_choices if c.kind == "trigger_target")
    assert asked.data["max_targets"] == 2
    assert game.confirm_trigger_target(
        0, permanent_ids=[wall.permanent_id, giant.permanent_id]
    )
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert (wall.tapped, giant.tapped, lions.tapped) == (True, True, False)


def test_w2g6_nightscape_battlemage_bounces_two_it_was_not_cast_at(pool):
    """Kicked with {2}{U} and cast naming nothing, the Battlemage's "return up
    to two target nonblack creatures to their owners' hands" chooses as it
    goes on the stack — both of them."""
    game = _w2g6_table(pool)
    game.players[0].hand.append(pool["Nightscape Battlemage"])
    bears = _w2g6_put(game, pool, 1, "Grizzly Bears")
    giant = _w2g6_put(game, pool, 1, "Hill Giant")
    knight = _w2g6_put(game, pool, 1, "Black Knight")

    assert game.queue_from_hand(
        0, "Nightscape Battlemage", optional_cost_payments={"{2}{U}": 1}
    ).supported
    assert game.resolve_top_of_stack()
    (asked,) = game.pending_choices
    assert asked.data["max_targets"] == 2
    assert knight.permanent_id not in {
        t["permanent_id"] for t in asked.data["targets"]
    }, "nonblack"
    assert game.confirm_trigger_target(
        0, permanent_ids=[bears.permanent_id, giant.permanent_id]
    )
    resolve_stack(game)

    assert sorted(card.name for card in game.players[1].hand) == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert [p.card.name for p in game.controlled_by(1)] == ["Black Knight"]


def test_w2g6_a_bruiser_nobody_asks_taps_the_defenders_creatures_not_itself(pool):
    """The same trigger for an AI or headless seat. It used to keep the
    reference to itself that the declare-attackers fire site stamps — "up to
    two target creatures" was not read as naming a target — so the Bruiser
    "tapped" the Bruiser and nothing else, every attack."""
    game = _w2g6_table(pool, humans=())
    game.start_turn(0)
    game._close_current_priority_step()
    bruiser = _nosick(_w2g6_put(game, pool, 0, "Cho-Arrim Bruiser"))
    mine = _w2g6_put(game, pool, 0, "Savannah Lions")
    bears = _w2g6_put(game, pool, 1, "Grizzly Bears")
    giant = _w2g6_put(game, pool, 1, "Hill Giant")
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert game.declare_attackers(0, [game.battlefield_index_of(bruiser)])[0]
    (trigger,) = game.stack
    assert trigger.target_permanent_id == [bears.permanent_id, giant.permanent_id]
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert (bears.tapped, giant.tapped, mine.tapped) == (True, True, False)
    assert "Cho-Arrim Bruiser tapped Cho-Arrim Bruiser" not in game.log
