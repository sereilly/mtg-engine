"""Census: every discard an offer's sentence makes **a cost** is marked one.

CR 118.12: "[A player] may [do something]. If [that player] [does, doesn't],
[effect]." — "The action [do something] is a cost, paid when the spell or
ability resolves." CR 118.12a reads "[do something] unless [a player does
something else]" the same way. A cost is not an effect (Library of Leng,
2004-10-04) and nothing *causes* it (Psychic Purge, 2004-10-04), so the
offer's lowering marks the discard (``lowering/control_flow._paid_as_cost``,
``as_cost``) and the discard handlers hand the mark to the seam
(``tests/regressions/test_kg5_costs_resolution_discard_costs.py`` drives the
boards).

Asked of every compiled program in the shipped pool:

* a discard in the action of an offer with a decline branch ("unless", "if you
  don't") is marked — the decline branch is always printed, never folded in;
* a discard in the action of an offer with only an accept branch is marked
  exactly when the line prints the rider ("if you do", "if the player
  does"): "you may discard any number of land cards. Put that many …"
  (Nantuko Cultivator) has an accept branch the sequence lowering folded in,
  and its discard is the effect;
* nothing else is marked — not a discard in either branch, not one outside
  an offer;
* every discard in a cost position is of a kind whose handler reads the mark
  (``COST_PAYABLE_DISCARD_KINDS``).

Backwards on e245e624c (nothing marked) the first assertion fails on all
seventeen cards.
"""

from __future__ import annotations

import re

from engine.card_loader import load_catalog
from engine.faces import compilation_units, unit_label
from engine.grammar.lowering.control_flow import COST_PAYABLE_DISCARD_KINDS
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction

#: The printed accept rider of CR 118.12's second form.
_IF_DOES = re.compile(r"\bif (?:you|they|the player|that player) (?:do|does)\b")


def _children(instruction: OracleInstruction):
    """``(key, step)`` for every instruction nested in *instruction*'s
    payload, a ``choose_one`` mode's included."""
    for key, value in instruction.payload.items():
        items = value if isinstance(value, (list, tuple)) else (value,)
        for item in items:
            if isinstance(item, OracleInstruction):
                yield key, item
            elif isinstance(item, dict) and isinstance(item.get("instruction"), OracleInstruction):
                yield key, item["instruction"]


def _discards(instruction: OracleInstruction, offer=None):
    """``(discard step, the offer whose action holds it or None)`` for every
    discard under *instruction*. A step in an offer's ``then`` / ``otherwise``
    is outside its cost, and a nested offer starts its own."""
    if "discard" in instruction.kind:
        yield instruction, offer
    for key, step in _children(instruction):
        if instruction.kind == "may":
            yield from _discards(step, instruction if key == "action" else None)
        else:
            yield from _discards(step, offer)


def _abilities(unit):
    """``(printed line, root instruction)`` for each compiled ability; a
    spell's own instructions are read against its whole text."""
    program = compile_card_oracle(unit)
    abilities = [
        (ability.source_line, ability.instruction)
        for ability in (*program.triggered_abilities, *program.activated_abilities)
        if ability.instruction is not None
    ]
    if abilities:
        return abilities
    return [(unit.oracle_text or "", root) for root in program.instructions]


def test_every_discard_an_offer_makes_a_cost_is_marked_and_nothing_else_is():
    marked: set[str] = set()
    unmarked_costs, wrongly_marked, unhonoured = [], [], []
    for unit in compilation_units(load_catalog()):
        for line, root in _abilities(unit):
            for step, offer in _discards(root):
                label = f"{unit_label(unit)}: {step.kind}"
                is_marked = bool(step.payload.get("as_cost"))
                if offer is None:
                    if is_marked:
                        wrongly_marked.append(label)
                    continue
                payload = offer.payload
                if payload.get("otherwise"):
                    a_cost = True
                elif payload.get("then"):
                    a_cost = bool(_IF_DOES.search(line.lower()))
                else:
                    a_cost = False
                if a_cost and step.kind not in COST_PAYABLE_DISCARD_KINDS:
                    unhonoured.append(label)
                elif a_cost and not is_marked:
                    unmarked_costs.append(label)
                elif is_marked and not a_cost:
                    wrongly_marked.append(label)
                if is_marked:
                    marked.add(unit_label(unit))
    assert not unmarked_costs, (
        "a discard CR 118.12 makes a cost is not marked as_cost — Library of "
        f"Leng and Dodecapod will read it as an effect's: {sorted(set(unmarked_costs))}"
    )
    assert not wrongly_marked, (
        "a discard that is an effect is marked as a cost — Library of Leng "
        f"would never be offered it: {sorted(set(wrongly_marked))}"
    )
    assert not unhonoured, (
        "a discard in an offer's cost whose handler does not read the mark "
        "(COST_PAYABLE_DISCARD_KINDS): teach the handler, then add the kind: "
        f"{sorted(set(unhonoured))}"
    )
    # A floor on what was examined: seventeen cards print such an offer when
    # this census was written (Masticore … Wrench Mind, Crypt Lurker,
    # Forbidden Ritual).
    assert len(marked) >= 15, sorted(marked)
    assert {"Masticore", "Balduvian Horde", "Forbidden Ritual"} <= marked
