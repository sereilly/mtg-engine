"""Tests for Magic: The Gathering Comprehensive Rules Section 603.

Covers:
  603.2  — "…becomes the target of a spell [or ability]", announced the moment
           the targets are chosen, and the printed narrowing that says which
           kinds of object count
  601.2c — a spell chooses its targets as it is cast, which is when the
           announcement happens ("Any abilities that trigger when those objects
           … become the target of a spell trigger at this point")
  602.2b — the same process for an activated ability

Invented card names throughout, deliberately: the condition is read from a
printed template, so a test naming Forsaken Wastes or Warden of the Woods could
pass against a table keyed by the name. Those two cards' own tests live in
``tests/sets/``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

_LEA = None


def _lea():
    global _LEA
    if _LEA is None:
        _LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
    return _LEA


def _watcher(text: str) -> CardDefinition:
    return CardDefinition(
        name="Test Watcher", mana_cost="", cmc=0.0, type_line="Enchantment",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": "Test Watcher", "type_line": "Enchantment"},
    )


_POINTER = CardDefinition(
    name="Test Pointer", mana_cost="", cmc=0.0, type_line="Artifact",
    oracle_text="{T}: Destroy target enchantment.", colors=(), color_identity=(),
    keywords=(), produced_mana=(),
    raw={"name": "Test Pointer", "type_line": "Artifact"},
)


def _board(text: str, *, by_ability: bool):
    """A watcher on seat 0, and on seat 1 whatever will point at it."""
    watcher = Permanent(card=_watcher(text))
    p1 = PlayerState(name="P1", battlefield=[watcher])
    p2 = PlayerState(name="P2")
    if by_ability:
        pointer = Permanent(card=_POINTER)
        pointer.summoning_sick = False
        p2.battlefield = [pointer]
    else:
        p2.hand = [_lea()["Disenchant"]]
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    return game, watcher


def _point_at_the_watcher(game, *, by_ability: bool, by_id: bool = False):
    ids = [game.players[0].battlefield[0].permanent_id] if by_id else None
    if by_ability:
        game.activate_permanent_ability(
            1, "Test Pointer", target_player_index=0, target_permanent_index=0,
            target_permanent_ids=ids,
        )
    else:
        game.cast_from_hand(
            1, "Disenchant", target_player_index=0, target_permanent_index=0,
            target_permanent_ids=ids,
        )
    game.resolve_stack()


_LOSE_5 = ", that spell's controller loses 5 life."


@pytest.mark.cr("603.2")
@pytest.mark.cr("601.2c")
def test_603_2_a_spell_only_trigger_ignores_an_ability():
    """"…becomes the target of **a spell**" (Forsaken Wastes' printing) is
    narrower than "…of a spell or ability", and a narrowing nothing tests is an
    ability that fires more often than the card allows — wrong in the
    controller's favour and silent."""
    for by_ability, expected in ((False, 15), (True, 20)):
        game, _ = _board(
            "Whenever this enchantment becomes the target of a spell" + _LOSE_5,
            by_ability=by_ability,
        )
        _point_at_the_watcher(game, by_ability=by_ability)
        assert game.players[1].life == expected


@pytest.mark.cr("603.2")
@pytest.mark.cr("602.2b")
def test_603_2_an_ability_only_trigger_ignores_a_spell():
    """The mirror narrowing, so the test is of the *condition* rather than of
    one card's half of it."""
    for by_ability, expected in ((True, 15), (False, 20)):
        game, _ = _board(
            "Whenever this enchantment becomes the target of an ability"
            ", that spell's controller loses 5 life.",
            by_ability=by_ability,
        )
        _point_at_the_watcher(game, by_ability=by_ability)
        assert game.players[1].life == expected


@pytest.mark.cr("603.2")
def test_603_2_the_unnarrowed_printing_still_admits_both():
    """The row every card in the shipped pool prints (Warden of the Woods,
    Skulking Ghost). Widening the pattern to carry the narrowing must not have
    narrowed the wording that carries none."""
    for by_ability in (False, True):
        game, _ = _board(
            "Whenever this enchantment becomes the target of a spell or ability"
            + _LOSE_5,
            by_ability=by_ability,
        )
        _point_at_the_watcher(game, by_ability=by_ability)
        assert game.players[1].life == 15


@pytest.mark.cr("601.2c")
def test_601_2c_the_announcement_happens_on_every_push_path():
    """The regression this test exists for.

    ``Game._stack_push_object`` stamps a target's identity through three
    exits — a graveyard target, a caller that already knows the ids, and the
    ordinary one — and the announcement used to sit at the end of the last of
    them. The middle exit is the one **the web layer always takes**: it resolves
    ``target_permanent_ids`` off the wire. So every "becomes the target"
    trigger in the pool was dead in the running app and alive in the tests.
    """
    for by_ability in (False, True):
        game, _ = _board(
            "Whenever this enchantment becomes the target of a spell or ability"
            + _LOSE_5,
            by_ability=by_ability,
        )
        _point_at_the_watcher(game, by_ability=by_ability, by_id=True)
        assert game.players[1].life == 15, (
            "a target named by id is still a target (CR 601.2c)"
        )


@pytest.mark.cr("603.2")
def test_603_2_the_targeting_seat_is_frozen_by_the_event():
    """"**That spell's controller**" is the seat the event carried, not the
    permanent's controller: pointing your own spell at your own permanent costs
    *you* the life."""
    for caster in (0, 1):
        watcher = Permanent(card=_watcher(
            "Whenever this enchantment becomes the target of a spell" + _LOSE_5
        ))
        players = [PlayerState(name="P1", battlefield=[watcher]),
                   PlayerState(name="P2")]
        players[caster].hand = [_lea()["Disenchant"]]
        game = Game(players=players)
        game.enforce_mana_costs = False
        game._recompute_continuous_effects()

        game.cast_from_hand(caster, "Disenchant", target_player_index=0,
                            target_permanent_index=0)
        game.resolve_stack()

        assert [p.life for p in game.players] == (
            [15, 20] if caster == 0 else [20, 15]
        )


@pytest.mark.cr("113.3")
def test_113_3_a_stack_item_knows_whether_it_is_an_ability():
    """CR 113.3: an ability on the stack is not a spell, and two readers care
    which — the client's stack-item label and this trigger's narrowing. One
    predicate, so a card that fires on one and not the other cannot disagree
    with the label the player is shown.

    Asked of the object rather than of a running game, because the headless
    path resolves a cast before anything can look at the stack — and this is a
    property of the object either way.
    """
    from engine.game_types import StackItem
    from engine.oracle_types import OracleInstruction
    from web.serialization import _serialize_stack_item

    def _item(**kwargs) -> StackItem:
        return StackItem(
            card=_lea()["Disenchant"], caster_index=0, target_player_index=None,
            target_permanent_index=None, x_value=None, **kwargs,
        )

    spell = _item()
    activated = _item(ability_instruction=OracleInstruction("draw_cards", "", {}))
    hooked = _item(hook_key="anything")

    assert (spell.is_ability, activated.is_ability, hooked.is_ability) == (
        False, True, True,
    )
    # The client's label is the same answer, asked through the same property.
    game, _ = _board("Whenever this enchantment becomes the target of a spell"
                     + _LOSE_5, by_ability=False)
    labels = [_serialize_stack_item(item, game)["type"]
              for item in (spell, activated, hooked)]
    assert labels == ["spell", "ability", "ability"]


@pytest.mark.cr("603.2")
def test_603_2_the_narrowing_is_payload_on_one_condition():
    """Five self-nouns times three object classes times three controller
    scopes is one condition with three payload keys, not forty-five kinds."""
    for noun in ("creature", "artifact", "enchantment", "land", "permanent"):
        card = CardDefinition(
            name="Test Narrowing", mana_cost="", cmc=0.0,
            type_line="Enchantment",
            oracle_text=(
                f"Whenever this {noun} becomes the target of a spell "
                "an opponent controls, that spell's controller loses 5 life."
            ),
            colors=(), color_identity=(), keywords=(), produced_mana=(),
            raw={"name": "Test Narrowing", "type_line": "Enchantment"},
        )
        program = compile_card_oracle(card)
        assert program.supported, (noun, program.reason)
        (trigger,) = program.triggered_abilities
        assert trigger.condition.kind == "self_becomes_target"
        assert trigger.condition.payload == {
            "targeted_by": "a spell",
            "targeting_controller": "an opponent controls",
        }
