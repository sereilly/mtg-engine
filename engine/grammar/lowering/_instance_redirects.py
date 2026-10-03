"""Lowering CR 615.8's **next instance** redirects: "The next time <a source the
sentence names> would deal damage …, it deals that damage to … instead".

Split off ``lowering/redirection.py`` at Prophecy's first wave, when Shield
Dancer's redirect took that module past the thousand-line guard. The line is the
one the parse side already draws: every production here is read by
``effects/damage_instances._finish_named_source_effect`` — "the next time
<named source> would deal [combat] damage to <recipient> <duration>, …" — where
the source is **named by the sentence** (the ability's own permanent, or the one
target the ability announces) rather than chosen as the ability resolves
(CR 615.8's "a source of your choice", which stays with the redirects in
``redirection``) or described as a class. Soltari Guerrillas moves its own
damage onto a target; Shield Dancer turns an announced attacker's damage back
onto the attacker.

A floor for ``_counted_redirects``' reason exactly: ``redirection`` reads it —
``_lower_redirect_damage`` dispatches here on the two named-source shapes — and
it reads nothing back. ``_lower_named_source_redirect`` and its seat table moved
byte-identically, so no compiled program moved with them.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (_REST_OF_TURN, _describe_targets, _filter_payload,
                      _is_source, _is_you, _names_several_targets,
                      _restrictions_beyond)


#: Which seats a named-source redirect watches, by the printed seat word.
#: "an opponent" and "each opponent" are one record — the sentence describes the
#: damage event rather than choosing a seat (nothing is targeted), so the record
#: has to exist on every seat the event could land on before it happens. A word
#: outside this table refuses: a redirect armed on the wrong seats is a card
#: that either does nothing or covers damage it never mentioned.
_REDIRECT_PROTECTED_SEATS: dict[str, str] = {
    "you": "you",
    "opponent": "opponents",
    "each_opponent": "opponents",
}


def _lower_named_source_redirect(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """Soltari Guerrillas: "{0}: The next time this creature would deal combat
    damage to an opponent this turn, it deals that damage to target creature
    instead."

    The third way a redirect can name the source whose damage moves, beside the
    targeted one (Shimian Night Stalker) and the chosen one (Nova Pentacle): it
    is the ability's **own permanent**, so nothing is picked for it and the
    handler already holds it. Its own kind for that reason and not as payload,
    exactly as those two are two kinds — ``engine/targeting.py`` keys the picker
    on the kind, and this one raises a picker for the *new recipient* where
    theirs raise one for the source or none at all.

    What is new underneath is the **protected** seat. Every other recorded
    redirect is armed on its controller (``to_self``); this one watches the
    seats the sentence describes, which are the caster's opponents, and the
    record is one object shared between them — CR 615.8's "the next **time**" is
    one instance of one replacement effect, so a per-seat copy would fire once
    per opponent.

    Six refusals, each a way the sentence could otherwise mean more than it
    says:

    * the source must carry no narrowing beyond naming itself. A restated
      adjective has nothing left to narrow and would be dropped.
    * the protected seats must be a word this table reads. A record armed on
      the wrong seats covers damage the card never mentioned — or none.
    * the duration must be this turn, because that is what the sweeps give it.
    * the new recipient must be one target the **activating** player picks.
      Nova Pentacle's "of an opponent's choice" is a different prompt on a
      different kind, and several targets would be collected and dropped.
    * every key of that noun phrase must be one ``subject_matches`` can test,
      because the picker and the handler both ask it.
    * a chosen source alongside a named one names the source twice.
    """
    if node.from_chosen_source:
        raise LoweringError(
            "a redirect names its source once: either a chosen source or the "
            "ability's own permanent",
            node=node,
        )
    if _restrictions_beyond(
        node.dealt_by.filter, frozenset({"card_types", "is_source"})
    ):
        raise LoweringError(
            "the ability's own source carries no narrowing the record could "
            "honour",
            node=node,
        )
    protects = _REDIRECT_PROTECTED_SEATS.get(getattr(node.to, "kind", ""))
    if protects is None:
        raise LoweringError(
            "a named-source redirect watches its controller or their opponents",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    if node.chooser is not None:
        raise LoweringError(
            "the activating player picks a named-source redirect's new "
            "recipient",
            node=node,
        )
    recipient = node.new_recipient
    if (
        not isinstance(recipient, ast.TargetSpec)
        or recipient.quantifier != "target"
        or _names_several_targets(recipient)
    ):
        raise LoweringError(
            "no handler resolves this redirect's new recipient", node=node
        )
    described = _filter_payload(recipient.filter)
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "a redirect cannot test " + ", ".join(sorted(untestable)), node=node
        )
    payload: dict[str, object] = {
        "protects": protects,
        "combat_only": bool(node.combat_only),
    }
    if node.one_shot:
        # "**The next time** …" — one instance. Absent is every instance for
        # the duration, which is what ``uses=None`` already means on the record.
        payload["uses"] = 1
    _describe_targets(payload, recipient)
    return (
        OracleInstruction("redirect_source_damage_to_target_until_eot", "", payload),
    )


def _lower_redirect_onto_dealer(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """Shield Dancer: "{2}{W}: The next time target attacking creature would
    deal combat damage to this creature this turn, that creature deals that
    damage to itself instead."

    CR 614.9 with the dealer as the new recipient: the damage is still dealt, by
    the same source and in full, and only its recipient changes — so lifelink,
    "whenever ~ deals damage" and the damage records all see it, which is why
    this is a redirect record and not a prevention shield plus a ping.

    The protected recipient is the ability's own permanent or its controller;
    the record hangs off whichever it is (a record lives on what it watches,
    ``engine/damage_redirects.py``), answers to the announced source alone by
    identity, and names that same source as its taker. ``redirect_damage_from_
    target_until_eot`` arms it — the picker for that kind is the announced
    source's, which is exactly what this ability targets.

    Every refusal is a way the sentence could otherwise mean more than it says:

    * the source must be one announced target, and every key of its noun phrase
      one the picker and the resolution can test (CR 601.2c, 608.2b);
    * the protected recipient must be the source permanent or "you";
    * the duration must be this turn, which is what the sweeps give a record;
    * a chosen source, an opponent's pick, an offer and a point pool all have
      readings elsewhere and none here.
    """
    spec = node.dealt_by
    if (
        node.from_chosen_source
        or node.chooser is not None
        or node.optional
        or node.amount is not None
        or not isinstance(spec, ast.TargetSpec)
        or spec.quantifier != "target"
        or _names_several_targets(spec)
    ):
        raise LoweringError(
            "a redirect onto its own dealer names one announced source", node=node
        )
    if _is_source(node.to):
        protects = "source"
    elif _is_you(node.to):
        protects = "you"
    else:
        raise LoweringError(
            "a redirect onto its dealer protects this permanent or you", node=node
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    payload: dict[str, object] = {
        "protects": protects,
        "new_recipient": "damage_source",
    }
    if node.one_shot:
        payload["uses"] = 1
    if node.combat_only:
        payload["combat_only"] = True
    _describe_targets(payload, spec)
    untestable = untestable_filter_keys(
        (payload.get("targets") or {}).get("filter") or {}
    )
    if untestable:
        raise LoweringError(
            "a redirect cannot test " + ", ".join(sorted(untestable)), node=node
        )
    return (
        OracleInstruction("redirect_damage_from_target_until_eot", "", payload),
    )
