"""A spell with no target is not countered for an illegal one (CR 608.2b).

"As an additional cost to cast this spell, sacrifice a creature. Draw two
cards." (Village Rites.) The spell targets nothing, so ``derive_cast_spec``
answers with the picker for its *cost* — and ``illegal_targets_refusal`` asked
"does this spell target?" as ``spec is None``. A cost picker is not None, so an
id stamped on the stack item's target channel was judged as a target.

The AI put one there: ``_choose_single_object_target`` read the same cost
picker as "a one-object-target spell" and named the creature it meant to pay
with. That creature is in the graveyard by the time the spell is on the stack
(a cost is paid at CR 601.2h), so every such cast paid in full and was then
"removed from the stack: every target is illegal" — a spell countered by the
rules for a target it never printed. Found by reading a simulated game's log
(Diabolic Intent, three casts of twelve); the census below read 15 of 15 on the
tree before the fix.

Two ends, both asserted pool-wide: the gate leaves a cost-only spell alone, and
the policy does not name a payment as a target.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import _choose_single_object_target
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, spec_is_a_cost
from tests.helpers import resolve_stack

# Each card whose text compiles (`faces.compilation_units`): a split card's
# half is a spell of its own, cast by its own name, and the whole card compiles
# to no instructions at all — so a census over the raw catalog would pass over
# a half that pays a cost without ever asking about it.
_POOL = {card.name: card for card in compilation_units(load_catalog())}

#: What the rig puts on the caster's battlefield: something for every head
#: noun a printed cost in the pool names (a creature, each basic land, an
#: artifact, a Goblin, a Wall).
_RIG = (
    "Grizzly Bears", "Forest", "Swamp", "Mountain", "Island", "Plains",
    "Sol Ring", "Goblin Balloon Brigade", "Wall of Wood",
)

#: How many spells the sweep must reach. Fourteen at Planeshift's wave 1; a
#: floor rather than the number, so a new one is covered without an edit and a
#: census that silently reads no cards fails instead of passing.
_FLOOR = 12


def _cost_only_spells() -> list[str]:
    """Every shipped instant or sorcery whose whole cast spec is a picker for
    a permanent its **cost** takes — the spell itself targets nothing."""
    found = []
    for name, card in sorted(_POOL.items()):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(card, program)
        if spec is None or not spec_is_a_cost(spec):
            continue
        if spec.get("sacrifice_cost") or spec.get("exile_cost") or spec.get("return_cost"):
            found.append(name)
    return found


def _table(name: str):
    forest = _POOL["Forest"]
    game = Game(players=[
        # A half is cast by its own name out of the card that prints it
        # (CR 709.3a), so the hand holds the whole card.
        PlayerState(
            "Caster", library=[forest] * 10,
            hand=[_POOL[name].face_of or _POOL[name]],
        ),
        PlayerState("Bystander", library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    for rigged in _RIG:
        game._put_permanent_onto_battlefield(0, Permanent(card=_POOL[rigged]), None)
    return game


def test_the_sweep_reaches_the_spells_it_is_about():
    names = _cost_only_spells()
    assert len(names) >= _FLOOR, names
    # The three the defect was first read off, by name: a census that stopped
    # naming them has stopped looking at this shape.
    assert {"Village Rites", "Natural Order", "Harrow"} <= set(names)


@pytest.mark.parametrize("name", _cost_only_spells())
def test_a_cost_only_spell_resolves_with_its_payer_named_on_the_target_channel(name):
    """The announcement the AI made: the permanent that pays, named as the
    cost *and* on the target channel. The cost is paid, and the spell then
    resolves — it has no target to have lost."""
    card = _POOL[name]
    game = _table(name)
    payers = [
        entry for entry in game.cast_target_spec(0, card).get("valid_targets") or ()
        if entry.get("kind") == "permanent"
    ]
    assert payers, f"the rig holds nothing that pays for {name}"
    payer = game.permanent_at(payers[0]["seat"], payers[0]["index"])

    result = game.cast_from_hand(
        0, name, target_player_index=0,
        target_permanent_index=payers[0]["index"],
        target_permanent_ids=[payer.permanent_id],
        cost_permanent_index=payers[0]["index"],
        cost_permanent_ids=[payer.permanent_id],
        x_value=1 if "{X}" in (card.mana_cost or "") else None,
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert not game.is_on_battlefield(payer), "the cost was paid"
    assert not any("every target is illegal" in line for line in game.log), [
        line for line in game.log if name in line
    ]


@pytest.mark.parametrize("name", _cost_only_spells())
def test_the_policy_names_no_target_for_a_spell_that_has_none(name):
    """A payment is not a target (CR 601.2b vs 601.2c): the single-object
    chooser answers None for a spec that is a cost picker, where it used to
    answer the first of the caster's own permanents that could pay."""
    game = _table(name)
    assert _choose_single_object_target(game, 0, _POOL[name], 1) is None
