"""A division printed under a condition asked at resolution (W1G2, Shower of
Coals).

"Shower of Coals deals 2 damage to each of up to three targets. / Threshold —
Shower of Coals deals 4 damage to each of those permanents and/or players
instead if there are seven or more cards in your graveyard." compiles to an
``if_then`` whose two arms carry the same cross-seat list. Two things in
``engine/divided_damage.py`` had only ever met a division at the top level or
behind a kicker:

* ``divided_instruction`` did not look inside an ``if_then``, so the cast gate
  found no division and refused the announcement ("divides nothing");
* ``divide`` handed a card-divided spell the share **stamped at the
  announcement**, which is the amount the card would have dealt as it was cast
  — not the amount the arm that resolves prints.

Neither change reaches a compiled program, so ``oracle_diff`` is blind to both
and this is their census. It names what must *not* have moved: a division
under a ``was_kicked`` arm is still unfound card-wide (Magma Burst, Pollen
Remedy), which the reviewed inventory in ``tests/ai/test_ai_valuation.py``
stands on.
"""

from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_paths
from engine.divided_damage import (
    EACH, FIXED, divide, divided_instruction, stamp_card_shares,
)
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from engine.targeting import instructions_as_announced

_W1G2_POOL = load_cards(manifest_set_paths(include_measured=True))
_W1G2_BY_NAME = {card.name: card for card in _W1G2_POOL}


def _w1g2_burn(amount, targets):
    return OracleInstruction("deal_damage", "", {"amount": amount, "targets": targets})


def _w1g2_gate(kind, then, otherwise):
    return OracleInstruction("if_then", "", {
        "condition": {"kind": kind}, "then": (then,), "else": (otherwise,),
    })


_W1G2_LIST = {"quantifier": "divided", "kind": "divided", "division": EACH, "max_targets": 3}


def test_a_division_both_arms_announce_is_found_and_is_the_replacing_arms():
    found = divided_instruction((
        _w1g2_gate("cards_in_zones", _w1g2_burn(4, dict(_W1G2_LIST)), _w1g2_burn(2, dict(_W1G2_LIST))),
    ))

    assert found is not None and found.payload["amount"] == 4


def test_arms_that_announce_different_lists_are_not_one_announcement():
    """A division in one arm and a single target in the other, or two
    different ceilings: nothing can say which list the caster is naming, so
    the division is not found and a divided announcement is refused."""
    single = {"quantifier": "any_target", "kind": "any"}
    wider = dict(_W1G2_LIST, max_targets=5)

    for otherwise in (_w1g2_burn(2, single), _w1g2_burn(2, wider)):
        assert divided_instruction((
            _w1g2_gate("cards_in_zones", _w1g2_burn(4, dict(_W1G2_LIST)), otherwise),
        )) is None


def test_a_kicker_arm_is_still_read_by_the_announcement_and_not_card_wide():
    """CR 601.2b settles a kicker before targets are chosen, so the one arm
    that cast will run is what the announcement reads
    (``instructions_as_announced``). Card-wide, a division that exists only
    for the kicked cast stays unfound — exactly as before."""
    assert divided_instruction((
        _w1g2_gate("was_kicked", _w1g2_burn(4, dict(_W1G2_LIST)), _w1g2_burn(2, dict(_W1G2_LIST))),
    )) is None

    for name in ("Magma Burst", "Pollen Remedy"):
        card = _W1G2_BY_NAME[name]
        program = compile_card_oracle(card)
        assert divided_instruction(program.instructions) is None, name
    remedy = _W1G2_BY_NAME["Pollen Remedy"]
    program = compile_card_oracle(remedy)
    assert divided_instruction(instructions_as_announced(remedy, program, {})) is not None


def test_each_takes_the_resolving_amount_not_the_stamp():
    """``EACH`` is "every target takes the whole amount", and the amount is
    the resolving instruction's. Entries stamped 4 at the announcement are
    dealt 2 by an arm that prints 2 — and a ``FIXED`` division still reads its
    stamp, because there the stamp *is* the printed share."""
    entries = stamp_card_shares([(1, None), (1, 0)], [4, 4])

    assert [share for _seat, _index, share in divide(2, entries, division=EACH)] == [2, 2]
    assert [share for _seat, _index, share in divide(4, entries, division=EACH)] == [4, 4]

    printed = stamp_card_shares([(1, None), (1, 0)], [1, 2])
    assert [share for _seat, _index, share in divide(3, printed, division=FIXED)] == [1, 2]


def _w1g2_walk(instruction, under=None):
    """Every nested instruction with the kind of the nearest ``if_then``
    condition it sits under (None at the top)."""
    if not isinstance(instruction, OracleInstruction):
        return
    yield instruction, under
    payload = instruction.payload or {}
    for key, value in payload.items():
        inner_under = under
        if instruction.kind == "if_then" and key in ("then", "else"):
            inner_under = (payload.get("condition") or {}).get("kind")
        items = value if isinstance(value, (tuple, list)) else (value,)
        for item in items:
            nested = item.get("instruction") if isinstance(item, dict) else item
            yield from _w1g2_walk(nested, inner_under)


def test_every_division_under_a_condition_in_the_pool_is_one_of_the_two_readings():
    """Both manifest roles. A spell whose division sits under an ``if_then``
    is either a kicker's (unfound card-wide, found for the announced cast) or
    one both arms announce (found card-wide). Anything else would be a card
    whose divided announcement the cast gate refuses, compiled supported."""
    examined, kicked, shared = 0, [], []
    for card in compilation_units(_W1G2_POOL):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        examined += 1
        under = {
            condition
            for root in program.instructions
            for instruction, condition in _w1g2_walk(root)
            if condition is not None
            and isinstance((instruction.payload or {}).get("targets"), dict)
            and instruction.payload["targets"].get("kind") == "divided"
        }
        if not under:
            continue
        found = divided_instruction(program.instructions)
        if under == {"was_kicked"}:
            assert found is None, card.name
            kicked.append(card.name)
        else:
            assert found is not None, (card.name, under)
            shared.append(card.name)

    assert examined >= 900, examined
    assert len(kicked) >= 2, kicked
    assert "Shower of Coals" in shared, shared


def test_each_of_up_to_n_targets_is_a_ceiling_and_firestorm_keeps_its_count():
    """"…to each of **up to three** targets" lowers to the cross-seat list with
    ``max_targets`` — the key a printed ceiling has always travelled under —
    where Firestorm's "each of X targets" keeps ``target_count``, which the
    cast gate holds an announcement to exactly. An announced X has no ceiling
    spelling ("up to X targets"), and that sentence still refuses."""
    from engine.grammar import compile_line

    ceiling = compile_line(
        "Pile Rain deals 2 damage to each of up to three targets.", card_name="Pile Rain",
    )
    counted = compile_line(
        "Firestorm deals X damage to each of X targets.", card_name="Firestorm",
    )
    open_ended = compile_line(
        "Pile Rain deals 2 damage to each of up to X targets.", card_name="Pile Rain",
    )

    assert ceiling.usable and counted.usable and not open_ended.usable
    assert ceiling.instructions[0].payload["targets"] == {
        "quantifier": "divided", "kind": "divided", "division": EACH, "max_targets": 3,
    }
    assert counted.instructions[0].payload["targets"] == {
        "quantifier": "divided", "kind": "divided", "division": EACH, "target_count": "x",
    }
