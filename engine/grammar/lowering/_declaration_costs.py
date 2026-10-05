"""What a declaration *costs* (CR 508.1h, CR 509.1d).

The additional costs a creature's controller must pay to declare it as an
attacker or a blocker — "unless you sacrifice two Islands" (Leviathan),
"unless their controller sacrifices a land of their choice for each green
creature they control that's attacking" (Flooded Woodlands, Reclamation),
"unless their controller pays {X} for each attacking creature they control"
(War Tax) and its blocking twin (War Cadence).

Split out of ``lowering/combat.py`` at Mercadian Masques' wave 2, when the two
mana tolls took that module past the thousand-line guard. The seam is one the
rules already draw and the enforcement already honours: a *restriction* is
answered by ``can_attack`` / ``_can_block_attacker`` asking whether a
declaration is legal at all, and a *cost* is answered by
``_attack_mana_costs_of`` / ``_block_mana_costs_of`` and charged over the whole
declaration. Everything here lowers into the second half; everything left in
``combat.py`` lowers into the first.

A floor, not a family: ``combat`` is the only module that asks, and this reads
``_common`` and the AST and nothing back — the single-importer shape
``_recipients`` and ``_bites`` already have, and for their reason exactly, that
the module exists because one family crossed the guard.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import OBJECT_ONLY_FILTER_KEYS, untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (
    _filter_payload, _is_source, RESTRICTION_TURNS, variable_mana_payload,
)


#: The two turn-scoped declaration tolls, mapped to the printed *state* their
#: "for each" tail must name. War Tax counts the payer's attacking creatures
#: (CR 508.1h) and War Cadence their blocking ones (CR 509.1d) — one sentence
#: with two verbs, and two kinds because the gate that answers each is a
#: different step of combat.
_PAY_TOLL_STATES: dict[str, str] = {
    "creatures_cant_attack_unless_pay_until_eot": "attacking",
    "creatures_cant_block_unless_pay_until_eot": "blocking",
}


def _lower_combat_pay_toll(
    node: ast.CombatRestriction,
) -> tuple[OracleInstruction, ...]:
    """"This turn, creatures can't attack unless their controller pays {X} for
    each attacking creature they control." (War Tax; War Cadence one verb over.)

    ``creatures_cant_attack_unless_sacrifice`` below with the cost paid in mana,
    plus the one thing that branch has no need of: a **window**. That sentence
    is a permanent's standing static, re-derived from the board at every
    declaration; this one is the effect of a resolving ability, so it is a
    record on the game and it has to be told when to end. A toll admitted with
    no duration would tax every combat for the rest of the game.

    The "for each" tail is held to "the payer's own creatures in the state this
    restriction is about", by equality against the subject with those two words
    lifted off — the sacrifice branch's check exactly, and for its reason: a
    tail naming any other set would charge for the wrong creatures while the
    card compiled clean.

    The count is *not* in the payload. Both declaration readers already ask once
    per attacker and once per (blocker, attacker) pair and sum what comes back,
    so "for each attacking creature they control" is what the sum already is —
    the same reading ``_attack_mana_costs_of`` records making of Koskun Falls'
    identical tail. Putting a multiplier here as well would charge it twice.
    """
    state = _PAY_TOLL_STATES[node.kind]
    payload = dict(node.payload)
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier not in ("all", "each"):
        raise LoweringError(
            "a board-wide declaration toll restricts a printed class of "
            "creatures",
            node=node,
        )
    per = payload["per"]
    if getattr(per, state) is not True or per.controller != "that_player":
        raise LoweringError(
            f"the scaling tail counts the {state} members its controller "
            "controls",
            node=node,
        )
    if dataclasses.replace(
        per, controller=None, **{state: None}
    ) != spec.filter:
        raise LoweringError(
            "the scaling tail names a different set than the restriction",
            node=node,
        )
    # Checked rather than defaulted, exactly as the blanket restrictions above
    # check theirs: the record is swept by the cleanup step, so a toll with any
    # other window would end at the wrong time or never. One turn only —
    # nothing prints a two-turn toll, and the sweep the entry rides counts
    # cleanups rather than carrying a window of its own.
    if RESTRICTION_TURNS.get(str(payload.get("duration"))) != 1:
        raise LoweringError(
            "a declaration toll with no end-of-turn duration has nothing to "
            "sweep it",
            node=node,
        )
    subject = _filter_payload(spec.filter)
    untestable = untestable_filter_keys(subject)
    if untestable or not subject:
        raise LoweringError(
            "the declaration gate cannot test the taxed class: "
            + (", ".join(sorted(untestable)) or "nothing was described"),
            node=node,
        )
    return (
        OracleInstruction(
            node.kind, "",
            {
                "subject": subject,
                "mana": variable_mana_payload(
                    payload["mana"], what="a declaration toll", node=node
                ),
            },
        ),
    )

def lower_declaration_cost(
    node: ast.CombatRestriction,
) -> "tuple[OracleInstruction, ...] | None":
    """The instruction for a declaration cost, or None when *node* is not one.

    One entry point rather than four exported branches, so ``combat.py`` asks
    the question once. None and not a raise: the caller has its own restriction
    branches to try, and a kind this module does not own is not an error.
    """
    if node.kind in _PAY_TOLL_STATES:
        return _lower_combat_pay_toll(node)
    # "This creature can't attack unless you sacrifice two Islands." (Leviathan
    # — "This cost is paid as attackers are declared".) CR 508.1h. The filter is
    # held to what the *charger* can test: `_sacrifice_candidate_indices` reads
    # a payload through the same matcher every other sacrifice does, and a
    # narrowing it cannot answer would either charge the wrong permanents or
    # charge none — so an untestable key refuses the line rather than riding
    # along.
    if node.kind == "cant_attack_unless_sacrifice":
        payload = dict(node.payload)
        if not _is_source(node.subject):
            raise LoweringError(
                "the attack cost is paid by the source's controller and "
                "restricts the source",
                node=node,
            )
        described = _filter_payload(payload["sacrifice_filter"])
        untestable = untestable_filter_keys(described, allowed=OBJECT_ONLY_FILTER_KEYS)
        if untestable:
            raise LoweringError(
                "the attack cost cannot be charged against: "
                + ", ".join(sorted(untestable)),
                node=node,
            )
        return (
            OracleInstruction(
                "cant_attack_unless_sacrifice", "",
                {"filter": described, "count": int(payload["sacrifice_count"])},
            ),
        )
    # "Green creatures can't attack unless their controller sacrifices a land of
    # their choice **for each green creature they control that's attacking**."
    # (Flooded Woodlands, Reclamation.) The board-wide twin of Leviathan's cost
    # above: the sentence is printed on a permanent naming a *class*, the payer
    # is that class's controller, and the cost is charged once per attacking
    # member — which is exactly the per-attacker shape `_attack_costs_of`
    # already returns, so the charge and the gate need nothing new.
    if node.kind == "creatures_cant_attack_unless_sacrifice":
        payload = dict(node.payload)
        spec = node.subject
        if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "all":
            raise LoweringError(
                "the board-wide attack cost restricts a printed class of "
                "creatures",
                node=node,
            )
        # The "for each" tail says what the cost scales with, and the only
        # scaling this shape has a charge for is **one per attacking member of
        # the very class the sentence restricts**. Held by equality against the
        # subject with those two words lifted off: a tail naming anything else
        # is a different card, and admitting it would charge for the wrong set
        # while the card compiled clean. Equality rather than a field-by-field
        # probe for the reason `_lower_cant_be` gives — a filter field added to
        # the AST later cannot slip through one.
        per = payload["per"]
        if per.attacking is not True or per.controller != "that_player":
            raise LoweringError(
                "the scaling tail counts the attacking members its controller "
                "controls",
                node=node,
            )
        if dataclasses.replace(per, attacking=None, controller=None) != spec.filter:
            raise LoweringError(
                "the scaling tail names a different set than the restriction",
                node=node,
            )
        subject = _filter_payload(spec.filter)
        untestable = untestable_filter_keys(subject)
        if untestable or not subject:
            raise LoweringError(
                "the attack gate cannot test the restricted class: "
                + (", ".join(sorted(untestable)) or "nothing was described"),
                node=node,
            )
        # "…a land **of their choice**". Lifted off rather than carried: it says
        # the paying player picks, which is what the charger does already
        # (`default_sacrifice_pick` stands in for a chooser it can hand off to),
        # so a payload key would be one nothing reads. What is *not* satisfied
        # by that is somebody else picking, and `chosen_by_opponent` is outside
        # the allowed set below, so it refuses.
        #
        # Named at the call site because ``_filter_payload`` now refuses the
        # word outright: it is the caller's claim that the choice is really
        # made somewhere, and an unnamed key is a refusal.
        described = _filter_payload(
            payload["sacrifice_filter"],
            carried_separately=frozenset({"their_choice"}),
        )
        described.pop("their_choice", None)
        untestable = untestable_filter_keys(described, allowed=OBJECT_ONLY_FILTER_KEYS)
        if untestable:
            raise LoweringError(
                "the attack cost cannot be charged against: "
                + ", ".join(sorted(untestable)),
                node=node,
            )
        return (
            OracleInstruction(
                "creatures_cant_attack_unless_sacrifice", "",
                {
                    "subject": subject,
                    "filter": described,
                    "count": int(payload["sacrifice_count"]),
                },
            ),
        )
    return None
