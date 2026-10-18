"""Regression: "create **that many** tokens" made zero under a damage trigger.

Found at Odyssey wave 1 while driving Druid's Call ("Whenever enchanted
creature is dealt damage, its controller creates that many 1/1 green Squirrel
creature tokens"), a card that arrived compiling supported — and the shipped
pool was paying for the same reading: **Saber Ants** (Urza's Saga, "Whenever
this creature is dealt damage, you may create that many 1/1 green Insect
creature tokens") resolved, logged itself done and made **no** Insects.

It is ``test_that_many_reads_the_trigger.py``'s defect one effect family over.
A bare "that many" under a trigger names the number the firing event carried,
frozen into the trigger's context by the fire site (CR 603.10), and
``_events.trigger_quantity_key`` is the one table of which event freezes what.
The counter placements have read it since Light of Promise; the token maker
still read ``trigger_count`` out of the resolution scratchpad, a key only a
delayed attack trigger (Basri Ket) and Tetravus' own exile step write. No
static instrument could see it: both cards compiled, both triggers carried a
real ``create_token`` instruction, and the census cannot ask whether an
instruction's number is the right one.

The fix is that channel in two places: ``lowering/tokens._stamp_token_count``
emits ``amount_from_trigger`` when the trigger's event has a row, and the
``create_token`` handler reads the trigger's context when the key is there. An
event with no row keeps the scratchpad read byte for byte.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compiled_units
from tests.helpers import resolve_stack


def _game(catalog_by_name):
    forest = catalog_by_name["Forest"]
    game = Game(players=[
        PlayerState("A", library=[forest] * 10),
        PlayerState("B", library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    return game


def _bolt(game, catalog_by_name, seat, permanent):
    game.players[seat].hand.append(catalog_by_name["Lightning Bolt"])
    result = game.cast_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[permanent.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    game.check_state_based_actions()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _tokens(game, seat):
    return [p for p in game.controlled_by(seat) if p.metadata.get("is_token")]


def test_saber_ants_makes_an_insect_for_each_damage_it_was_dealt(catalog_by_name):
    """Dealt 3 by a Lightning Bolt, a Saber Ants with enough toughness to
    survive it makes three 1/1 green Insects for its controller."""
    game = _game(catalog_by_name)
    ants = Permanent(card=catalog_by_name["Saber Ants"])
    game._put_permanent_onto_battlefield(0, ants, None)
    ants.metadata["plus_counters"] = 5
    game.check_state_based_actions()

    _bolt(game, catalog_by_name, 1, ants)

    insects = _tokens(game, 0)
    assert len(insects) == 3
    assert all(
        token.has_type("insect")
        and (token.effective_power, token.effective_toughness) == (1, 1)
        and token.effective_colors == {"G"}
        for token in insects
    )
    assert not _tokens(game, 1)


def test_saber_ants_still_makes_its_insects_when_the_damage_kills_it(catalog_by_name):
    """The number was frozen by the fire site, so the Ants dying to the very
    damage that triggered it changes nothing: a 2/3 dealt 3 makes three."""
    game = _game(catalog_by_name)
    ants = Permanent(card=catalog_by_name["Saber Ants"])
    game._put_permanent_onto_battlefield(0, ants, None)

    _bolt(game, catalog_by_name, 1, ants)

    assert not game.is_on_battlefield(ants)
    assert len(_tokens(game, 0)) == 3


def test_every_that_many_token_trigger_names_a_number_something_writes():
    """Pool-wide, both manifest roles: a ``create_token`` whose count is the
    bare "that many" sits either under an event with a frozen quantity — and
    then says which (``amount_from_trigger``) — or under one of the two
    producers of the scratchpad key. A third shape is a token maker that
    resolves and makes nothing."""
    #: The triggers whose own resolution writes ``trigger_count`` before the
    #: token step reads it: Tetravus' upkeep (its exile step). Basri Ket's
    #: delayed attack trigger is not a printed trigger of the card at all.
    scratchpad_producers = {"upkeep_self"}
    examined = 0
    subjects: dict[str, str] = {}
    orphans: dict[str, str] = {}
    pool: dict[str, object] = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    # ``compiled_units``: a split card's text is on its halves (CR 709.4c).
    for card, program in compiled_units(pool.values()):
        if not program.supported:
            continue
        for trigger in program.triggered_abilities:
            if trigger.instruction is None:
                continue
            examined += 1
            pending = [trigger.instruction]
            while pending:
                instruction = pending.pop()
                for value in instruction.payload.values():
                    if isinstance(value, (list, tuple)):
                        pending.extend(
                            item for item in value
                            if hasattr(item, "kind") and hasattr(item, "payload")
                        )
                if (
                    instruction.kind != "create_token"
                    or instruction.payload.get("count") != "trigger_count"
                ):
                    continue
                subjects[card.name] = trigger.condition.kind
                if (
                    instruction.payload.get("amount_from_trigger") is None
                    and trigger.condition.kind not in scratchpad_producers
                ):
                    orphans[card.name] = trigger.condition.kind
    # Floors, so a walk that stops finding triggers cannot pass over nothing.
    assert examined >= 1500, examined
    assert {"Saber Ants", "Tetravus"} <= set(subjects), subjects
    assert not orphans, orphans
