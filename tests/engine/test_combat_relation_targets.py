"""“…target creature **blocking or blocked by this creature**” is a narrowing
every targeted verb carries, not one card's sentence.

The relation used to have no payload form: ``ObjectFilter.in_combat_with_source``
was listed among the fields ``to_payload`` never emits, so every lowering but
the four written for it (Abu Ja'far's sweep, Sentinel's rewrite, Lesser
Werewolf's counter, Spitting Slug's grant) refused the phrase by name. Cromat
prints it on a plain "destroy target" and was unsupported for that reason
alone.

It is an emitted, testable key now, on ``blocking_source``'s footing —
``subject_matches`` takes the source the relation is to and answers it off
``creatures_in_combat_with`` — and the pure matcher **refuses** it rather than
ignoring it, so a handler that asks only the pure half matches nothing instead
of matching the board.

What that bought is checked here by behaviour, on invented cards so that no
pool card's other text is in the way: for each verb the picker offers exactly
the creature in the fight, a look-alike standing beside it is refused at
announcement with nothing on the stack, and the named creature is acted on.
The blocker and the bystander are the same printed card on purpose — nothing
about either creature tells them apart, so a dropped relation shows up as the
bystander being reachable, which is the only way to see it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

#: (instruction kind, the printed ability). A tuple of tuples, so the
#: parametrized ids collect in one order on every xdist worker.
_VERBS = (
    ("add_counter_to_target",
     "{1}: Put a -1/-1 counter on target creature blocking or blocked by this creature."),
    ("bounce_target_creature",
     "{1}: Return target creature blocking or blocked by this creature to its owner's hand."),
    ("deal_damage",
     "{1}: This creature deals 2 damage to target creature blocking or blocked by this creature."),
    ("destroy_target_permanent",
     "{1}: Destroy target creature blocking or blocked by this creature."),
    ("exile_target_permanent",
     "{1}: Exile target creature blocking or blocked by this creature."),
    ("grant_target_keyword_until_eot",
     "{1}: Target creature blocking or blocked by this creature gains first strike until end of turn."),
    ("prevent_damage_by_target_until_eot",
     "{1}: Prevent all combat damage that would be dealt by target creature blocking or blocked by this creature this turn."),
    ("pump_target_creature_until_eot",
     "{1}: Target creature blocking or blocked by this creature gets -2/-2 until end of turn."),
    ("tap_target_permanent",
     "{1}: Tap target creature blocking or blocked by this creature."),
    ("untap_target_permanent",
     "{1}: Untap target creature blocking or blocked by this creature."),
)


def _creature(name: str, power: int, toughness: int, text: str = "") -> CardDefinition:
    type_line = "Creature - Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _ready(card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _blocked(text: str):
    """A creature printing *text*, attacking and blocked by the first of two
    identical 3/6s."""
    source = _ready(_creature("Relation Probe", 3, 3, text))
    blocker = _ready(_creature("Look-alike", 3, 6))
    bystander = _ready(_creature("Look-alike", 3, 6))
    filler = _creature("Filler", 1, 1)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[source], library=[filler, filler]),
        PlayerState(name="P2", battlefield=[blocker, bystander], library=[filler, filler]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    return game, source, blocker, bystander


@pytest.mark.parametrize("kind, text", _VERBS, ids=[kind for kind, _ in _VERBS])
def test_the_combat_relation_narrows_the_picker_and_the_announcement(kind, text):
    program = compile_card_oracle(_creature("Relation Probe", 3, 3, text))
    assert program.supported, text
    (ability,) = program.activated_abilities
    assert ability.instruction.kind == kind

    game, source, blocker, bystander = _blocked(text)

    offered = game.activation_target_spec(0, 0, 0)["valid_targets"]
    assert [(t["seat"], t["index"]) for t in offered] == [(1, 0)], (
        "the picker offers the creature in the fight and nothing else"
    )

    refused = game.activate_permanent_ability(
        0, "Relation Probe", permanent_index=0,
        target_permanent_ids=[bystander.permanent_id],
    )
    assert not refused.supported, "the look-alike is not blocking this creature"
    assert not game.stack

    log_before = len(game.log)
    named = game.activate_permanent_ability(
        0, "Relation Probe", permanent_index=0,
        target_permanent_ids=[blocker.permanent_id],
    )
    assert named.supported, named.details
    acted = [line for line in game.log[log_before:] if "Look-alike" in line]
    assert acted, f"{kind} resolved without acting on the creature it named"
    assert game.is_on_battlefield(bystander)
    assert bystander.damage_marked == 0 and not bystander.tapped


def test_no_block_is_no_legal_target_for_any_of_them():
    """Outside a block the phrase names nobody, so none of these abilities can
    be activated at all (CR 602.2b through CR 601.2c) — with a creature named
    or without one."""
    for _kind, text in _VERBS:
        source = _ready(_creature("Relation Probe", 3, 3, text))
        other = _ready(_creature("Look-alike", 3, 6))
        game = Game(players=[
            PlayerState(name="P1", battlefield=[source]),
            PlayerState(name="P2", battlefield=[other]),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = set()
        game.start_turn(0)
        game._close_current_priority_step()

        assert game.activation_target_spec(0, 0, 0)["valid_targets"] == [], text
        assert not game.activate_permanent_ability(
            0, "Relation Probe", permanent_index=0,
            target_permanent_ids=[other.permanent_id],
        ).supported, text
        assert not game.activate_permanent_ability(
            0, "Relation Probe", permanent_index=0,
        ).supported, text
        assert not game.stack


def test_the_sweeps_written_before_this_keep_their_own_kinds():
    """The four older users of the relation each strip the field and carry it
    themselves, so making the key emitted moved none of them — the same
    sentences still lower to the kinds their handlers were written for."""
    from engine.grammar import compile_line

    sweep = compile_line(
        "At end of combat, destroy all creatures blocking or blocked by this creature.",
        card_name="Test",
    )
    assert [i.kind for i in sweep.instructions] == [
        "destroy_creatures_in_combat_with_source"
    ]
    rewrite = compile_line(
        "{0}: Change this creature's base toughness to 1 plus the power of "
        "target creature blocking or blocked by this creature.",
        card_name="Test",
    )
    (instruction,) = rewrite.instructions
    assert instruction.kind == "set_source_base_pt_from_target"
    assert instruction.payload["in_combat_with_source"] is True
    assert "in_combat_with_source" not in (
        instruction.payload["targets"]["filter"]
    ), "the rewrite still carries the relation on its own root"
