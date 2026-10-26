"""The "share a creature type" relation (CR 205.3m), pool-wide.

Onslaught prints the relation five ways (the Crowns, Endemic Plague, Mana
Echoes, Cryptic Gateway, Graxiplon) and each has its per-card test in
``tests/sets/test_ons_*``. What is asserted here is the relation itself and the
grammar's reading of its far end, on invented cards — a second card printing
the shape needs nothing new, and a position with no far end refuses loudly
rather than reaching every creature on the table.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.handlers._filters import _card_matches_filter, permanent_matches_filter
from engine.models import CardDefinition, Permanent
from engine.object_creature_types import (creature_types, share_a_creature_type,
                                          shared_creature_type_count,
                                          shares_a_creature_type_with_each)
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _card(name, type_line, oracle_text="", power="2", toughness="2"):
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power=power, toughness=toughness)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw,
    )


def test_only_creature_types_relate_two_objects():
    """An animated Forest's "forest" and an Equipment's "equipment" are
    subtypes, not creature types: a Dryad land creature's creature types are
    {dryad}, and two Forests share nothing."""
    dryad = Permanent(card=_card("Test Dryad Arbor", "Land Creature — Forest Dryad"))
    forest = Permanent(card=_card("Test Forest", "Basic Land — Forest"))
    assert creature_types(None, dryad) == {"dryad"}
    assert creature_types(None, forest) == frozenset()
    assert not share_a_creature_type(creature_types(None, forest), creature_types(None, forest))


def test_the_relation_and_its_each_form_and_its_grouping():
    """Pairwise sharing is an intersection; "each" asks every anchor on its own
    (the Cryptic Gateway ruling's Elf Warrior for an Elf Wizard and a Human
    Warrior); a group must hold *one* type in common (Graxiplon) — a Goblin
    Warrior, a Goblin and an Elf Warrior are a group of two, not three."""
    goblin_warrior, goblin, elf_warrior = (
        {"goblin", "warrior"}, {"goblin"}, {"elf", "warrior"},
    )
    assert share_a_creature_type(goblin_warrior, elf_warrior)
    assert not share_a_creature_type(goblin, elf_warrior)
    assert not share_a_creature_type(set(), set())
    assert shares_a_creature_type_with_each(
        {"elf", "warrior"}, [{"elf", "wizard"}, {"human", "warrior"}]
    )
    assert not shares_a_creature_type_with_each(
        {"elf", "druid"}, [{"elf", "wizard"}, {"human", "warrior"}]
    )
    assert not shares_a_creature_type_with_each({"elf"}, [])
    assert shared_creature_type_count([goblin_warrior, goblin, elf_warrior]) == 2
    assert shared_creature_type_count([goblin_warrior, goblin, elf_warrior, goblin]) == 3
    assert shared_creature_type_count([set(), set(), set()]) == 0


def test_both_pure_matchers_refuse_the_relation_unresolved():
    """A filter still naming its far end matches nothing — a creature on the
    battlefield or a card in a hand — rather than everything."""
    goblin = _card("Test Goblin", "Creature — Goblin")
    for unresolved in (
        {"type_filter": "creature", "shares_creature_type_with": "event_subject"},
        {"type_filter": "creature", "shares_creature_type_with_attached_host": True},
    ):
        assert not permanent_matches_filter(Permanent(card=goblin), unresolved)
        assert not _card_matches_filter(goblin, unresolved)
    resolved = {"type_filter": "creature", "shares_creature_type_with_each": [["goblin"]]}
    assert permanent_matches_filter(Permanent(card=goblin), resolved)
    assert _card_matches_filter(goblin, resolved)
    assert not _card_matches_filter(
        goblin, {"type_filter": "creature", "shares_creature_type_with_each": [[]]}
    )


_PLAGUE_OF_KIN = (
    "Whenever a creature enters, destroy all other creatures that share a "
    "creature type with it."
)


def test_an_invented_enters_sweep_reads_it_as_the_entering_creature():
    """Spreading Plague's sentence one characteristic over, on an invented
    enchantment: a Goblin entering destroys the other Goblins (either side's)
    and spares itself — "other" is other than the creature that entered — and
    the Elf, which shares nothing."""
    plague = _card("Test Plague of Kin", "Enchantment", _PLAGUE_OF_KIN)
    program = compile_card_oracle(plague)
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.instruction.payload["shares_creature_type_with"] == "event_subject"
    assert trigger.instruction.payload["other_than_event_subject"] is True

    entering = _card("Test Goblin Raider", "Creature — Goblin Warrior")
    game = Game(players=[
        PlayerState(name="Me", hand=[entering]), PlayerState(name="Opp"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat, card in ((0, plague), (1, _card("Test Goblin", "Creature — Goblin")),
                       (1, _card("Test Elf", "Creature — Elf"))):
        game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    game.stack.clear()
    game.start_turn(0)
    game._close_current_priority_step()

    assert game.queue_from_hand(0, "Test Goblin Raider").supported
    resolve_stack(game)

    names = sorted(p.card.name for p in game.all_permanents())
    assert names == ["Test Elf", "Test Goblin Raider", "Test Plague of Kin"], game.log


def test_a_far_end_with_nothing_to_name_refuses_the_line():
    """The loud direction, in the three positions the far end can be missing
    from: "it" on a spell with no firing event, "each creature tapped this
    way" behind a cost that taps nothing but the source, and "it" in a pump's
    group whose subject is not an enchanted creature."""
    for text in (
        "Destroy all creatures that share a creature type with it.",
        "{T}: You may put a creature card from your hand that shares a creature "
        "type with each creature tapped this way onto the battlefield.",
        "Creatures that share a creature type with it get +1/+1 until end of turn.",
    ):
        program = compile_card_oracle(_card("Test Refusal", "Sorcery", text))
        assert not program.supported, (text, program)
