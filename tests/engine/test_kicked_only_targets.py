"""A target printed only in a kicked half (CR 702.33g), for the two shapes that
print "**another** target" there.

"If part of a spell's ability has its effect only if that spell was kicked, and
that part of the ability includes any targets, the spell's controller chooses
those targets only if that spell was kicked." Planeshift prints it three times
— Falling Timber, Rushing River, Magma Burst — and its own tests drive those
cards. These are the same sentences on **invented** cards with a *mana* kicker,
which is the check `engine/card_hooks.py`'s entry bar asks for: give a card
nobody named the same printed text and see whether it works. Nothing here is
keyed on a name, a set or on the cost being a sacrifice.

Two lowerings, told apart by what the slot can be:

* **an object** ("another target creature", "another target nonland
  permanent") is an ordered-roles announcement, and `targeting._as_kicked`
  drops the role no surviving step spends;
* **"any target"** may be a seat or an object, which a role cannot say, so the
  pair is rewritten to the sentence it means — the amount to each of two
  targets if kicked (`lowering/damage.kicked_second_damage_target`).
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.grammar import compile_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import (_as_kicked, derive_cast_spec,
                              instructions_as_announced, spec_roles)
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}
_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _spell(name: str, text: str, *, type_line: str = "Instant") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "layout": "normal"},
    )


_TWO_SHATTERS = _spell(
    "Invented Twin Shatter",
    "Kicker {2}\n"
    "Destroy target artifact. If this spell was kicked, destroy another "
    "target artifact.",
)
_TWO_BOLTS = _spell(
    "Invented Twin Bolt",
    "Kicker {2}\n"
    "Invented Twin Bolt deals 2 damage to any target. If this spell was "
    "kicked, it deals 2 damage to another target.",
)


def _table(card: CardDefinition, theirs=()):
    forest = _POOL["Forest"]
    game = Game(players=[
        PlayerState("Caster", library=[forest] * 10, hand=[card]),
        PlayerState("Bystander", library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_RICH)
    placed = []
    for name in theirs:
        permanent = Permanent(card=_POOL[name])
        game._put_permanent_onto_battlefield(1, permanent, None)
        placed.append(permanent)
    return game, placed


def _spent(game) -> int:
    return sum(_RICH.values()) - sum(game.players[0].mana_pool.values())


# -- the roles shape ---------------------------------------------------------


def test_the_invented_cards_compile():
    for card in (_TWO_SHATTERS, _TWO_BOLTS):
        program = compile_card_oracle(card)
        assert program.supported, (card.name, program.reason)


def test_an_unkicked_cast_announces_one_role_and_a_kicked_one_two():
    program = compile_card_oracle(_TWO_SHATTERS)
    whole = derive_cast_spec(_TWO_SHATTERS, program)
    assert len(spec_roles(whole)) == 2, "the card's every arm names two"

    unkicked = derive_cast_spec(_TWO_SHATTERS, program, optional_cost_payments={})
    assert not spec_roles(unkicked) and unkicked["kind"] == "artifact"

    kicked = derive_cast_spec(
        _TWO_SHATTERS, program, optional_cost_payments={"{2}": 1}
    )
    assert [role["role"] for role in spec_roles(kicked)] == [
        "artifact", "another artifact",
    ]


def test_the_view_drops_only_the_role_no_surviving_step_spends():
    """Read off the program, not off the card: the role that goes is the one
    whose only spending step was in the arm the announcement took away, and
    the kicked view is the program unchanged."""
    program = compile_card_oracle(_TWO_SHATTERS)
    instructions = tuple(program.instructions)
    assert _as_kicked(instructions, True) != ()
    assert instructions_as_announced(
        _TWO_SHATTERS, program, {"{2}": 1}
    ) == _as_kicked(instructions, True)

    (sequence,) = _as_kicked(instructions, False)
    (first,) = sequence.payload["steps"]
    described = first.payload["targets"]
    assert described["kind"] == "object" and "roles" not in described
    assert "role" not in described


def test_the_unkicked_twin_shatter_destroys_one_artifact_for_one_mana():
    game, (ring, mox) = _table(_TWO_SHATTERS, ["Sol Ring", "Mox Pearl"])
    result = game.cast_from_hand(
        0, _TWO_SHATTERS.name, target_permanent_ids=[mox.permanent_id]
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert not game.is_on_battlefield(mox) and game.is_on_battlefield(ring)
    assert _spent(game) == 1


def test_the_kicked_twin_shatter_destroys_two_different_artifacts():
    game, (ring, mox) = _table(_TWO_SHATTERS, ["Sol Ring", "Mox Pearl"])
    result = game.cast_from_hand(
        0, _TWO_SHATTERS.name, optional_cost_payments={"{2}": 1},
        target_permanent_ids=[mox.permanent_id, ring.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert not game.is_on_battlefield(mox) and not game.is_on_battlefield(ring)
    assert _spent(game) == 3


def test_the_second_target_is_named_exactly_when_the_spell_is_kicked():
    """Both directions, each refused with nothing spent: two targets for an
    unkicked cast, one for a kicked one, and the same artifact twice."""
    game, (ring, mox) = _table(_TWO_SHATTERS, ["Sol Ring", "Mox Pearl"])
    name = _TWO_SHATTERS.name
    two_unkicked = game.cast_from_hand(
        0, name, target_permanent_ids=[mox.permanent_id, ring.permanent_id]
    )
    assert not two_unkicked.supported and "702.33g" in two_unkicked.details
    one_kicked = game.cast_from_hand(
        0, name, optional_cost_payments={"{2}": 1},
        target_permanent_ids=[mox.permanent_id],
    )
    assert not one_kicked.supported
    twice = game.cast_from_hand(
        0, name, optional_cost_payments={"{2}": 1},
        target_permanent_ids=[mox.permanent_id, mox.permanent_id],
    )
    assert not twice.supported
    assert _spent(game) == 0
    assert game.is_on_battlefield(mox) and game.is_on_battlefield(ring)


def test_an_unkicked_cast_is_gated_on_its_one_targets_description():
    """The named target of the unkicked cast is checked against the one-target
    spec: a creature is not an artifact, kicked or not."""
    game, (bears, mox) = _table(_TWO_SHATTERS, ["Grizzly Bears", "Mox Pearl"])
    refused = game.cast_from_hand(
        0, _TWO_SHATTERS.name, target_permanent_ids=[bears.permanent_id]
    )
    assert not refused.supported and _spent(game) == 0

    picker = game.cast_target_spec(0, _TWO_SHATTERS, optional_cost_payments={})
    assert [t["name"] for t in picker["valid_targets"]] == ["Mox Pearl"]


# -- the "any target" shape --------------------------------------------------


def test_the_unkicked_twin_bolt_is_an_ordinary_burn_spell():
    game, (giant,) = _table(_TWO_BOLTS, ["Hill Giant"])
    spec = game.cast_target_spec(0, _TWO_BOLTS, optional_cost_payments={})
    assert spec["kind"] == "any"
    assert game.cast_from_hand(0, _TWO_BOLTS.name, target_player_index=1).supported
    resolve_stack(game)
    assert game.players[1].life == 18 and giant.damage_marked == 0
    assert _spent(game) == 1


def test_the_kicked_twin_bolt_deals_its_damage_to_each_of_two_targets():
    """The whole amount to each — a creature and a face — never the even split
    of one amount, which is what an unstamped division resolves as."""
    game, (giant,) = _table(_TWO_BOLTS, ["Hill Giant"])
    spec = game.cast_target_spec(0, _TWO_BOLTS, optional_cost_payments={"{2}": 1})
    assert (spec["kind"], spec["division"], spec["divided_target_count"]) == (
        "divided", "each", 2,
    )
    result = game.cast_from_hand(
        0, _TWO_BOLTS.name, optional_cost_payments={"{2}": 1},
        divided_targets=[(1, 0), (1, None)],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert giant.damage_marked == 2 and game.players[1].life == 18
    assert _spent(game) == 3


def test_the_kicked_twin_bolt_needs_two_different_targets():
    game, (giant,) = _table(_TWO_BOLTS, ["Hill Giant"])
    for announced in (
        {"divided_targets": [(1, None), (1, None)]},
        {"divided_targets": [(1, None)]},
        {"target_player_index": 1},
    ):
        refused = game.cast_from_hand(
            0, _TWO_BOLTS.name, optional_cost_payments={"{2}": 1}, **announced
        )
        assert not refused.supported, announced
    assert _spent(game) == 0 and game.players[1].life == 20


# -- what the rewrite must not claim -----------------------------------------


def test_only_a_kicked_condition_makes_the_second_target_conditional():
    """CR 601.2c exempts a mode and a cost and nothing else: under any other
    condition both targets are announced whichever way it resolves, so the
    pair is not this sentence and keeps the refusal it had."""
    line = (
        "Probe Card deals 2 damage to any target. If you control a Mountain, "
        "it deals 2 damage to another target."
    )
    result = compile_line(line, card_name="Probe Card")
    assert result.lowering_error is not None
    assert "another target" in result.lowering_error


def test_two_different_amounts_are_not_the_same_damage_twice():
    """A different amount per target is a card-dictated share (Cone of Flame's
    lowering), not this one — refused rather than dealt as the first amount to
    both."""
    line = (
        "Probe Card deals 2 damage to any target. If this spell was kicked, "
        "it deals 4 damage to another target."
    )
    result = compile_line(line, card_name="Probe Card")
    assert result.lowering_error is not None


def test_the_kicked_pair_lowers_to_one_arm_of_each_size():
    line = (
        "Probe Card deals 2 damage to any target. If this spell was kicked, "
        "it deals 2 damage to another target."
    )
    (wrapper,) = compile_line(line, card_name="Probe Card").instructions
    assert wrapper.kind == "if_then"
    assert wrapper.payload["condition"] == {"kind": "was_kicked"}
    (kicked,) = wrapper.payload["then"]
    (plain,) = wrapper.payload["else"]
    assert kicked.payload["targets"]["target_count"] == 2
    assert kicked.payload["targets"]["division"] == "each"
    assert plain.payload["targets"] == {"quantifier": "any_target", "kind": "any"}
    assert kicked.payload["amount"] == plain.payload["amount"] == 2
