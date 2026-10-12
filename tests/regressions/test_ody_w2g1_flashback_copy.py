"""A flashed-back spell that comes back from Ertai's Meddling is still a spell
whose flashback cost was paid.

CR 707.10: "A copy of a spell or ability copies both the characteristics of
the spell or ability and all decisions made for it, including modes, targets,
the value of X, and **additional or alternative costs**." CR 702.34a: "If the
flashback cost was paid, exile this card instead of putting it anywhere else
any time it would leave the stack."

Ertai's Meddling's ruling (Scryfall, 2011-01-22) joins the two: "If the spell
was cast using flashback, Ertai's Meddling will still exile it with delay
counters on it. When the card is returned to the stack, it still 'remembers'
the flashback cost was originally paid. It'll be exiled when it resolves or
otherwise leaves the stack."

``StackItem.flashback`` is a field, not a key of ``choices``, so the frozen
announcement (``exiled_records.StackAnnouncement``) did not carry it and the
returning object went to its owner's graveyard — where the same card could be
flashed back again. This file drives the whole sequence with the real cards.
"""
from __future__ import annotations

from functools import lru_cache

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.exiled_records import EXILE_RECORD_KEY, live_records
from engine.game_types import OracleExecutionContext
from engine.handlers.stack import put_exiled_card_onto_stack_as_copy
from engine.oracle_types import OracleInstruction
from engine.named_counters import counters_on


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


def _where(game, card) -> list[str]:
    found = []
    for seat, player in enumerate(game.players):
        for zone in ("hand", "graveyard", "exile", "library"):
            found += [f"P{seat}.{zone}"] * sum(
                1 for held in getattr(player, zone) if held is card
            )
    found += ["stack"] * sum(1 for item in game.stack if item.card is card)
    return found


def _meddled_flashback() -> tuple[Game, object]:
    """P1 flashes Firebolt back at P0; P0 answers with Ertai's Meddling for
    X = 1. Firebolt is in exile with one delay counter."""
    by_name = _pool()
    firebolt = by_name["Firebolt"]
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.players[1].graveyard.append(firebolt)
    game.players[0].hand.append(by_name["Ertai's Meddling"])

    queued = game.queue_from_hand(
        1, "Firebolt", from_zone="graveyard", target_player_index=0,
    )
    assert queued.supported, queued.details
    assert game.stack[-1].flashback
    meddled = game.cast_from_hand(
        0, "Ertai's Meddling", x_value=1, target_stack_index=len(game.stack) - 1,
    )
    assert meddled.supported, meddled.details
    assert _where(game, firebolt) == ["P1.exile"]
    (record,) = live_records(game)
    assert counters_on(record, "delay") == 1
    assert record.announcement.flashback is True
    return game, firebolt


def _next_upkeep_of_its_controller(game) -> None:
    game.active_player_index = 1
    game.resolve_upkeep(1)


def test_the_returning_copy_is_exiled_as_it_resolves():
    game, firebolt = _meddled_flashback()
    _next_upkeep_of_its_controller(game)
    game._settle()

    assert game.players[0].life == 18, "the copy kept its target and resolved"
    assert _where(game, firebolt) == ["P1.exile"], (
        "a flashed-back spell is exiled, not binned to be flashed back again"
    )
    assert not list(live_records(game)), "and no register still speaks for it"


def test_the_returning_copy_is_exiled_if_it_is_countered_instead():
    """"…or otherwise leaves the stack." """
    by_name = _pool()
    game, firebolt = _meddled_flashback()
    # The last sentence of the delayed ability, run on its own so the card is
    # on the stack with nothing resolved behind it (the headless upkeep
    # settles the stack, and the point here is the moment in between).
    (record,) = live_records(game)
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1],
        card=by_name["Ertai's Meddling"],
        trigger_context={EXILE_RECORD_KEY: record},
    )
    put_exiled_card_onto_stack_as_copy(
        game, OracleInstruction("put_exiled_card_onto_stack_as_copy", "", {}), context,
    )
    assert _where(game, firebolt) == ["stack"]
    returned = next(item for item in game.stack if item.card is firebolt)
    assert returned.flashback and not returned.is_copy

    game.players[0].hand.append(by_name["Counterspell"])
    assert game.cast_from_hand(
        0, "Counterspell", target_stack_index=game.stack.index(returned),
    ).supported
    game._settle()
    assert game.players[0].life == 20
    assert _where(game, firebolt) == ["P1.exile"]


def test_a_spell_that_was_not_flashed_back_still_goes_to_its_graveyard():
    """The control: the same sequence with Firebolt cast from a hand."""
    by_name = _pool()
    firebolt = by_name["Firebolt"]
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.players[1].hand.append(firebolt)
    game.players[0].hand.append(by_name["Ertai's Meddling"])
    assert game.queue_from_hand(1, "Firebolt", target_player_index=0).supported
    assert game.cast_from_hand(
        0, "Ertai's Meddling", x_value=1, target_stack_index=len(game.stack) - 1,
    ).supported
    (record,) = live_records(game)
    assert record.announcement.flashback is False
    _next_upkeep_of_its_controller(game)
    game._settle()
    assert game.players[0].life == 18
    assert _where(game, firebolt) == ["P1.graveyard"]
