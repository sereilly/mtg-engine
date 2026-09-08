"""Urza's Saga wave 1, group 3: the rules behind "it becomes a N/N creature".

Four mechanisms, none of them about a printing — which is the line
SET_PLAYBOOK.md draws between `tests/sets/` and here:

* **CR 205.1a** — an animation that prints none of CR 205.1b's retention
  clauses *replaces* the permanent's card types. That is the whole engine of
  the Hidden / Opal / Veiled cycle: the enchantment stops being an
  enchantment, which is what its own intervening-if then reads.
* **CR 205.1b** — the clauses that make it an addition instead, so the two
  readings are asserted against each other rather than one being assumed.
* **CR 603.4** — the intervening-if, checked again as the ability resolves.
* **CR 603.8** — a state trigger fires when the game state matches and does
  not fire again until the state has stopped matching.

The nouns are invented cards throughout, because the mechanism is what is
under test: a card printing any other body gets these for free.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.grammar import lower_ability, parse_line
from engine.handlers.registry import EFFECT_HANDLERS
from engine.game_types import OracleExecutionContext
from engine.models import CardDefinition, Permanent


def _g3r_card(name: str, type_line: str, text: str, **raw) -> CardDefinition:
    body = {"name": name, "type_line": type_line, **raw}
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=body,
    )


def _g3r_game() -> tuple[Game, PlayerState, PlayerState]:
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    return game, alice, bob


def _g3r_run(game: Game, permanent: Permanent, line: str) -> None:
    """Resolve *line*'s single instruction with *permanent* as its source."""
    instruction = lower_ability(parse_line(line))[0]
    context = OracleExecutionContext(
        caster=game.players[game.controller_index_of(permanent) or 0],
        target=game.players[0],
        card=permanent.card,
        source_permanent=permanent,
    )
    EFFECT_HANDLERS[instruction.kind](game, instruction, context)


@pytest.mark.cr("205.1a", "613.1d")
def test_a_body_with_no_retention_clause_replaces_the_printed_card_types():
    """"…it becomes a 2/2 Gargoyle creature." — CR 205.1a: "in most such
    cases, the new card type(s) **replaces** any existing card types."

    Both halves are asserted, because a permanent that merely *gained* the
    creature type would pass the first: it is a creature **and** it is no
    longer an enchantment. That second half is what the Opal cycle's own
    intervening-if reads, so an animation that only added would leave every one
    of those cards re-animating for ever.
    """
    game, alice, _ = _g3r_game()
    perm = Permanent(card=_g3r_card("Test Veil", "Enchantment", ""))
    game._put_permanent_onto_battlefield(0, perm, None)
    assert perm.has_type("enchantment") and not perm.is_creature

    _g3r_run(game, perm, "This permanent becomes a 2/2 Gargoyle creature.")

    assert perm.is_creature
    assert perm.has_type("gargoyle")
    assert not perm.has_type("enchantment")
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)


@pytest.mark.cr("205.1b")
def test_the_retention_clause_is_what_makes_an_animation_an_addition():
    """The same sentence with "in addition to its other types" on the end.

    CR 205.1b: "Some effects change an object's card type … but specify that
    the object retains a prior card type … In such cases, all the object's
    prior card types … are retained." Asserted beside the replacement above
    rather than on its own, because the pair is the claim: the printed clause
    is the only thing that tells the two readings apart, and a production that
    lost the words would make one of them mean the other.
    """
    game, _, _ = _g3r_game()
    perm = Permanent(card=_g3r_card("Test Form", "Enchantment", ""))
    game._put_permanent_onto_battlefield(0, perm, None)

    _g3r_run(
        game, perm,
        "This permanent becomes a 3/3 Sphinx creature in addition to its "
        "other types.",
    )

    assert perm.is_creature
    assert perm.has_type("enchantment"), "the printed clause keeps the type"


@pytest.mark.cr("205.1a", "613.7")
def test_a_later_type_replacement_beats_an_earlier_animation():
    """"{0}: This permanent becomes an enchantment." (Opal Acrolith.)

    CR 613.7 applies layer 4 in timestamp order, so the *later* replacement
    wins — and the earlier animation record is not deleted, which is what lets
    a third sentence animate the permanent again with the size its own body
    named. Three states are asserted in sequence because the middle one is the
    only place a "delete the record" implementation would still look right.
    """
    game, _, _ = _g3r_game()
    perm = Permanent(card=_g3r_card("Test Acrolith", "Enchantment", ""))
    game._put_permanent_onto_battlefield(0, perm, None)

    _g3r_run(game, perm, "This permanent becomes a 2/4 Soldier creature.")
    assert perm.is_creature and not perm.has_type("enchantment")

    _g3r_run(game, perm, "This permanent becomes an enchantment.")
    assert perm.has_type("enchantment") and not perm.is_creature
    assert not perm.has_type("soldier"), (
        "CR 205.1a: the removed card type takes the subtypes it carried"
    )

    _g3r_run(game, perm, "This permanent becomes a 2/4 Soldier creature.")
    assert perm.is_creature and not perm.has_type("enchantment")
    assert (perm.effective_power, perm.effective_toughness) == (2, 4)


@pytest.mark.cr("603.4")
def test_an_intervening_if_about_the_source_type_is_checked_at_resolution():
    """"When an opponent casts a creature spell, **if this permanent is an
    enchantment**, it becomes a 2/2 Gargoyle creature."

    CR 603.4 checks the condition twice, and the second check is at
    resolution: an ability already on the stack does nothing if the condition
    has stopped being true. Here it stops being true because an earlier
    resolution of the same ability replaced the permanent's card types, which
    is why the clause is printed at all.
    """
    from engine.handlers.control_flow import evaluate_condition

    game, _, _ = _g3r_game()
    perm = Permanent(card=_g3r_card("Test Gate", "Enchantment", ""))
    game._put_permanent_onto_battlefield(0, perm, None)
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[0],
        card=perm.card, source_permanent=perm,
    )
    gate = {"kind": "source_is_type", "card_types": ["enchantment"]}

    assert evaluate_condition(game, context, gate) is True
    _g3r_run(game, perm, "This permanent becomes a 2/2 Gargoyle creature.")
    assert evaluate_condition(game, context, gate) is False


@pytest.mark.cr("603.4", "613.1d")
def test_the_intervening_if_reads_the_layers_not_the_printed_type_line():
    """The same gate asked of a permanent whose *printed* line still says
    Enchantment.

    CR 613.1d is the layer the animation applies in, and the type line is what
    it applies **over** — so a gate that read `card.type_line` would answer
    "yes, still an enchantment" for ever and the cycle would loop. The
    permanent's printed line is asserted unchanged beside the computed answer,
    so the test fails if either reading moves.
    """
    from engine.handlers.control_flow import evaluate_condition

    game, _, _ = _g3r_game()
    perm = Permanent(card=_g3r_card("Test Line", "Enchantment", ""))
    game._put_permanent_onto_battlefield(0, perm, None)
    _g3r_run(game, perm, "This permanent becomes a 4/4 Beast creature.")

    assert perm.card.type_line == "Enchantment"
    assert perm.effective_card.type_line == "Enchantment"
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[0],
        card=perm.card, source_permanent=perm,
    )
    assert evaluate_condition(
        game, context, {"kind": "source_is_type", "card_types": ["enchantment"]}
    ) is False


@pytest.mark.cr("603.8")
def test_a_state_trigger_does_not_fire_again_while_its_condition_holds():
    """"When an opponent controls a creature with power 4 or greater, …"

    CR 603.8: the ability triggers as soon as the game state matches and
    "doesn't trigger again until the ability has resolved … Then, if … the game
    state still matches its trigger condition, the ability will trigger again."

    The failure this guards is unbounded: a sweep that re-announced on every
    state-based check would put one copy on the stack per check, for ever. So
    the assertion is on the *count* of announcements over repeated checks and
    not merely on the effect having happened once.
    """
    game, alice, bob = _g3r_game()
    watcher = Permanent(card=_g3r_card(
        "Test Watcher", "Enchantment",
        "When an opponent controls a creature with power 4 or greater, "
        "if this permanent is an enchantment, it becomes a 4/4 Beast "
        "creature.",
    ))
    game._put_permanent_onto_battlefield(0, watcher, None)
    big = Permanent(card=_g3r_card(
        "Test Ogre", "Creature - Ogre", "", power="5", toughness="5",
    ))
    game._put_permanent_onto_battlefield(1, big, None)

    game.check_state_based_actions()
    assert len(game.stack) == 1, "the state matched, so it triggered once"
    for _ in range(5):
        game.check_state_based_actions()
    assert len(game.stack) == 1, "and did not trigger again while it still matched"


@pytest.mark.cr("603.8")
def test_a_state_trigger_re_arms_once_its_condition_has_been_false():
    """The other half of CR 603.8's sentence, and the one a latch that never
    forgets would fail: after the state stops matching, a later match triggers
    the ability again.

    Asserted with the ability drained off the stack in between, so what is
    measured is the *announcement* and not a stack that happened to still hold
    the first one.
    """
    game, alice, bob = _g3r_game()
    watcher = Permanent(card=_g3r_card(
        "Test Watcher", "Enchantment",
        "When an opponent controls a creature with power 4 or greater, "
        "if this permanent is an enchantment, it becomes a 4/4 Beast "
        "creature.",
    ))
    game._put_permanent_onto_battlefield(0, watcher, None)
    big = Permanent(card=_g3r_card(
        "Test Ogre", "Creature - Ogre", "", power="5", toughness="5",
    ))
    game._put_permanent_onto_battlefield(1, big, None)

    game.check_state_based_actions()
    game.stack.clear()
    game.remove_from_battlefield(big)
    game.check_state_based_actions()
    assert not game.stack, "the state no longer matches"

    again = Permanent(card=_g3r_card(
        "Test Ogre", "Creature - Ogre", "", power="5", toughness="5",
    ))
    game._put_permanent_onto_battlefield(1, again, None)
    game.check_state_based_actions()
    assert len(game.stack) == 1, "it has been false, so it triggers again"
