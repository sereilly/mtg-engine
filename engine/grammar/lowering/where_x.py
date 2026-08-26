"""What defines the X a sentence's ``where`` clause names (CR 608.2).

Split out of ``lower`` when that module reached the thousand-line guard, and
the split needed one change to be legal: these four productions each began by
calling ``lower_statement`` on the sentence the clause wraps, which would be an
*upward* import from here. The caller lowers that sentence and passes the
result in as *inner*.

That inversion is not a workaround, it is the honest shape. Every one of these
does the same two things to an already-lowered sentence — check that it reads an
X at all, then stamp the definition onto it — and none of them cares how the
sentence was lowered. What differs between them is only *what is counted*.

The definition is stamped rather than folded into the amounts because the count
is taken at **resolution**: a permanent entering between the trigger and its
resolution changes the answer, so lowering cannot know it.
``engine/mixins/oracle_instructions.py`` resolves it at the single dispatch
point, which is what lets one clause serve every effect family.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _mentions_x,
    _stamp_x_from_count,
    count_spec,
)

def lower_where_x(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of <filter>" over a whole sentence.

    The definition is stamped onto the lowered instructions rather than folded
    into their amounts, because the count is taken **at resolution** (CR 608.2):
    a Shrine entering between the trigger and its resolution changes the answer,
    so lowering cannot know it. ``engine/mixins/oracle_instructions.py``
    resolves it into the context's X at the single dispatch point, which is what
    lets one clause serve every effect family instead of one.
    """
    if isinstance(node.definition, ast.CountOfDeaths):
        return _lower_where_x_deaths(node, inner, produced)
    if isinstance(node.definition, ast.CharacteristicOfSubject):
        return _lower_where_x_characteristic(node, inner, produced)
    if isinstance(node.definition, ast.CountOfDeathsThisWay):
        return _lower_where_x_this_way(node, inner, produced)
    # "…where X is **twice** the number of …" (Jovial Evil). The factor is
    # unwrapped here and handed to `count_spec`, so only the definitions this
    # branch can scale accept one: a `Times` over a death history or a mana
    # value falls to the refusal below rather than silently losing the "twice",
    # which would be half the damage the card prints.
    factor = 1
    definition = node.definition
    if isinstance(definition, ast.Times):
        factor = definition.factor
        definition = definition.of
    if not isinstance(definition, ast.CountOf):
        raise LoweringError("only a count can define X in a where-clause", node=node)
    if not _mentions_x(inner):
        # The clause defined an X the sentence never used, which means one of
        # them was misread. Refusing keeps that loud instead of executing the
        # sentence with the definition quietly discarded.
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    spec = count_spec(_count_filter_for(definition.filter, inner, node), node,
                      multiplier=factor)
    return _stamp_x_from_count(inner, spec)


def _names_a_player_target(inner: tuple[OracleInstruction, ...]) -> bool:
    """Whether the lowered sentence chose a *player* as its target.

    Read off the **picker's description** and nothing else. The `recipient`
    key cannot answer it: "deals X damage to target opponent" and "deals X
    damage to that player" (a trigger's upkeep player) both lower to
    `recipient: "target_player"`, because the seat comes off the resolution
    context either way. Only one of them chose a target, and only for that one
    is `context.target` the player the words name — so the description, which
    exists precisely to say a choice was offered, is the honest test.
    """
    for instruction in inner:
        targets = instruction.payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") in (
            "player", "player_or_planeswalker"
        ):
            return True
    return False


def _count_filter_for(filt, inner: tuple[OracleInstruction, ...], node):
    """The filter a where-clause's count is taken over, with "that player"
    resolved into a zone owner.

    "…where X is twice the number of white creatures **that player** controls"
    (Jovial Evil): the player is the one the sentence in front of the clause
    targeted, so the count is taken on *their* battlefield. `count_spec`
    refuses a controller narrowing outright — `permanent_matches_filter` cannot
    test a controller, so the key would be handed over and ignored — and the
    fix is to move the restriction to the axis the counter *does* read, which
    is whose zone it scans.

    Admitted only when the sentence actually named a player target. Without
    one, "that player" points at nothing and `count_from_payload` would fall
    back to the caster — counting the wrong board and reporting the card
    supported, which is the failure the refusal exists for.
    """
    if filt.controller != "that_player":
        return filt
    if not _names_a_player_target(inner):
        raise LoweringError(
            "'that player' in a count with no player target to name", node=node
        )
    return dataclasses.replace(
        filt, controller=None, zone_owner=ast.PlayerRef("target_player")
    )


def _lower_where_x_deaths(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…where X is the number of creatures that died under your control this
    turn." (Liliana's Standard Bearer.)

    The count is a per-seat turn history (``engine/models.py``'s
    ``creatures_died_under_your_control_this_turn``, kept since round 14 because
    the game-wide tally cannot answer "under your control"), so it reads a
    counter rather than a zone. Only the bare creature filter is admitted: the
    tracker counts creatures and nothing narrower, and a narrowing it cannot
    apply would be counted as if it were not there.
    """
    filt = node.definition.filter
    if filt.to_payload() != {"type_filter": "creature"} or filt.zone != "battlefield":
        raise LoweringError(
            "the death tracker counts creatures and cannot be narrowed", node=node
        )
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"history": "creatures_died_under_your_control"})


def _lower_where_x_characteristic(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…, where X is **its** mana value." (Great Defender, Subdue, Kry Shield.)

    Stamped like every other where-clause and resolved at the same single
    dispatch point, so the sentence in front of it needs no special case: what
    changes is only *what* is counted. "Its" is the object the sentence already
    named — the resolution reads it off the chosen target, which is the one
    object a resolution can name without a second choice.
    """
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    # "Its" is whatever object the sentence already named, and the sentence
    # names it one of two ways: by targeting a permanent, or by binding the
    # spell its trigger fired on ("Whenever a player casts an instant spell,
    # counter it unless that player pays {X}, where X is **its** mana value").
    # Decided here, where both the definition and the lowered sentence are in
    # hand, rather than by a resolution-time fallback order that would have to
    # guess when a sentence has both.
    names_a_spell = any(i.payload.get("bound_to_trigger") for i in inner)
    if names_a_spell and node.definition.characteristic != "mana_value":
        # A spell on the stack has no power or toughness to read (CR 208.1), so
        # a clause asking for one about a bound spell is a misreading of one
        # half or the other. Refused rather than answered with a zero the card
        # never printed.
        raise LoweringError(
            "a spell has no power or toughness to read", node=node
        )
    return _stamp_x_from_count(
        inner,
        {
            "object_characteristic": {
                "object": "triggering_spell" if names_a_spell else "target",
                "characteristic": node.definition.characteristic,
                "offset": node.definition.offset,
            }
        },
    )


def _lower_where_x_this_way(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of creatures that **died this way**."
    (Hellfire.)

    A back-reference, not a count of a zone: the objects are exactly the ones
    an earlier step of this same effect destroyed, and by the time this is asked
    they are in graveyards. So it is stamped like every other where-clause and
    resolved at the same dispatch point, reading the scratchpad key the sweep
    handlers write.

    Refused without a producer, for the reason every back-reference in this file
    is: "this way" with no earlier step names nothing, and `count_from_payload`
    would answer 0 — a card that reports supported and deals three damage
    flat.

    Only the bare creature filter is admitted. The record is a *number*, not the
    set, so a narrower noun phrase ("the number of **black** creatures that died
    this way") is a question nothing can re-ask — it would be counted as though
    the narrowing were not there.
    """
    filt = node.definition.filter
    if filt.to_payload() != {"type_filter": "creature"} or filt.zone != "battlefield":
        raise LoweringError(
            "'died this way' counts what the earlier step destroyed and cannot "
            "be narrowed further", node=node,
        )
    if "destroyed_this_way" not in produced:
        raise LoweringError(
            "'died this way' with no earlier step in this effect that destroyed "
            "anything", node=node,
        )
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"back_reference": "destroyed_this_way"})
