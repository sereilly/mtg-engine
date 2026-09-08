"""Lowering combat damage **assignment** — CR 510.1.

Split off ``lowering/combat.py`` at Urza's Saga's second wave, the third time
that module has crossed the thousand-line guard, and the third time the line was
already drawn somewhere else first: ``prohibitions`` left on the printed voice,
``requirements`` on CR 506.3's pair of words, and this leaves on the boundary
``engine/combat_assignment.py`` has argued at length since Floral Spuzzem. How
much combat damage a creature assigns, and to whom, is CR 510.1 — a *turn-based
action* taken after the declarations are over — where everything left in
``combat`` lowers CR 506, 508 and 509: who may be declared, who must be, and
who may not.

That module's docstring makes the same case in the negative, and it is worth
restating because it is what keeps this family from being folded back into one
of its neighbours. An assignment change is **not** a prevention shield (nothing
is prevented: no shield counter is spent and no replacement ever sees an event),
**not** a P/T change (the creature keeps its power for a lord, for a "power 3 or
greater" filter and for the noncombat damage its own abilities deal), and **not**
a combat restriction (the creature still attacks, is still blocked, and still
*receives* combat damage). Three near neighbours, and being none of them is
precisely why the rule has one home.

Two lowerings today and they are opposites: one assigns nothing anywhere (Floral
Spuzzem), the other assigns everything somewhere else (Outmaneuver). Both write
one mark on one permanent, swept with the turn, which is why they refuse the same
two shapes — a window the sweep does not end, and a subject the mark cannot be
written onto.

Asymmetric like ``zones``, ``library``, ``mana``, ``prohibitions`` and
``requirements``: the parse halves stay in ``effects/combat.py``, where each is
one branch of the "assigns" verb table, and the guard fired on the lowerings.

A family rather than a floor, because ``combat`` does not read it —
``grammar/by_node.py`` reaches both lowerings directly, one layer up — so nothing
here is below anything and no lowering family imports it.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (_describe_several_targets, _describe_targets,
                      _is_enchanted, _is_source, _is_target,
                      _names_several_targets, _REST_OF_TURN)


def _lower_assigns_combat_damage_as_unblocked(
    node: "ast.AssignsCombatDamageAsUnblocked",
) -> tuple[OracleInstruction, ...]:
    """"X target blocked creatures assign their combat damage this turn as
    though they weren't blocked." (Outmaneuver.)

    A mark on each chosen creature, swept with the turn — the same shape the
    "assigns no combat damage" lowering below produces, and the same two
    refusals for the same reason: a window the sweep does not end, or a subject
    the mark cannot be written onto, would be a record answering a different
    question from the one the card asks.

    The subject is a **chosen** one here rather than the source, which is the
    one difference: the card is a spell that names its creatures, so the
    description is carried and the handler resolves it. The count may be an
    announced X, which the several-target description already spells as the
    string ``"x"``.
    """
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "an assign-as-though-unblocked mark lasts the rest of the turn "
            "and nothing else ends it", node=node,
        )
    payload: dict[str, object] = {}
    if _names_several_targets(node.subject):
        assert isinstance(node.subject, ast.TargetSpec)
        _describe_several_targets(payload, node.subject)
    elif _is_target(node.subject):
        _describe_targets(payload, node.subject)
    else:
        raise LoweringError(
            "the assign-as-though-unblocked mark reaches the creatures the "
            "spell chooses", node=node,
        )
    return (
        OracleInstruction("assign_as_unblocked_until_eot", "", payload),
    )


def _lower_assigns_no_combat_damage(
    node: ast.AssignsNoCombatDamage,
) -> tuple[OracleInstruction, ...]:
    """"This creature assigns no combat damage this turn." (Floral Spuzzem.)

    The subject must be the effect's own source and the window must be the rest
    of the turn, because those are the two things the record behind it can say:
    it is a mark on one permanent, swept by the cleanup step with the rest of
    the turn's marks. A sentence naming somebody else's creature, or a window
    the sweep does not end, refuses rather than lowering onto a record that
    would answer a different question.
    """
    # "…you may have **it** assign no combat damage this turn" on an Aura
    # (Cloak of Confusion), where the pronoun was rebound to the permanent the
    # Aura is attached to. The same mark on a different permanent, so the
    # subject is payload rather than a second kind — and it is *which*
    # permanent, not a filter: nothing here chooses.
    if _is_enchanted(node.subject):
        subject = "attached"
    elif (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
    ):
        # "…when **target creature you control** attacks and isn't blocked, **it**
        # assigns no combat damage this turn" (Delif's Cone, Delif's Cube). The
        # delay's opener chose the creature and `rebinding` pointed the pronoun
        # at it (CR 603.7c), so the mark goes on the object the ability is
        # *about* rather than on its source — which for the Cube is the artifact
        # that armed it and is not a creature at all.
        subject = "bound"
    elif _is_source(node.subject):
        subject = ""
    else:
        raise LoweringError(
            "only the effect's own source or the permanent it is attached to "
            "can be marked as assigning no combat damage", node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "an assigns-no-combat-damage mark lasts the rest of the turn and "
            "nothing else ends it", node=node,
        )
    payload = {"subject": subject} if subject else {}
    return (OracleInstruction("assign_no_combat_damage_until_eot", "", payload),)
