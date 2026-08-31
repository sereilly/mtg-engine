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
    _restrictions_beyond,
    _stamp_x_from_count,
    count_spec,
)
from ._events import _EVENT_SUBJECT_PLAYERS, EVENT_SUBJECT_PLAYER

def lower_where_x(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of <filter>" over a whole sentence.

    The definition is stamped onto the lowered instructions rather than folded
    into their amounts, because the count is taken **at resolution** (CR 608.2):
    a Shrine entering between the trigger and its resolution changes the answer,
    so lowering cannot know it. ``engine/mixins/oracle_instructions.py``
    resolves it into the context's X at the single dispatch point, which is what
    lets one clause serve every effect family instead of one.
    """
    damage = _damage_dealt_definition(node.definition)
    if damage is not None:
        return _lower_where_x_damage_dealt(node, damage, inner)
    if isinstance(node.definition, ast.CountOfDeaths):
        return _lower_where_x_deaths(node, inner, produced)
    if isinstance(node.definition, ast.CharacteristicOfSubject):
        return _lower_where_x_characteristic(node, inner, produced)
    if isinstance(node.definition, ast.CountOfDeathsThisWay):
        return _lower_where_x_this_way(node, inner, produced)
    if isinstance(node.definition, ast.ExiledForCost):
        return _lower_where_x_exiled_for_cost(node, inner)
    if isinstance(node.definition, ast.SacrificedForCost):
        return _lower_where_x_sacrificed_for_cost(node, inner)
    if isinstance(node.definition, ast.CountersOnSource):
        return _lower_where_x_counters(node, inner)
    if isinstance(node.definition, ast.TotalPowerSacrificedThisWay):
        return _lower_where_x_sacrificed_power(node, inner)
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
    spec = count_spec(_count_filter_for(definition.filter, inner, node, event), node,
                      multiplier=factor)
    return _stamp_x_from_count(inner, spec)


def _lower_where_x_exiled_for_cost(
    node: ast.WhereX, inner: tuple[OracleInstruction, ...]
) -> tuple[OracleInstruction, ...]:
    """"…, where X is **the exiled card's mana value**." (Necropolis.)

    Not a count of anything a zone holds: the card left the graveyard while the
    ability's own cost was being paid (CR 601.2h), so the number is last-known
    information the activation path recorded. Stamped like every other
    definition, at the same single dispatch point, so the sentence in front of
    it needs no special case.

    Mana value alone. Power and toughness are printed characteristics of a card
    (CR 208.2) and could be read here, but nothing records them — the channel
    carries the card, and a card's *computed* P/T does not exist off the
    battlefield (CR 613.1) — so admitting them would stamp a definition the
    resolution answers with a zero.
    """
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    if node.definition.characteristic != "mana_value":
        raise LoweringError(
            "only the exiled card's mana value is recorded by a cost payment",
            node=node,
        )
    return _stamp_x_from_count(
        inner, {"cost_exile_characteristic": node.definition.characteristic}
    )


def _lower_where_x_sacrificed_for_cost(
    node: ast.WhereX, inner: tuple[OracleInstruction, ...]
) -> tuple[OracleInstruction, ...]:
    """"…, where X is **the sacrificed creature's mana value**." (Burnt
    Offering.)

    :func:`_lower_where_x_exiled_for_cost` one zone over, and the same argument:
    the creature was eaten by the spell's own additional cost (CR 601.2b) before
    the spell was ever on the stack, so nothing on a board answers for it and
    the number is last-known information (CR 608.2h) the payment path recorded.

    Mana value alone, for that function's reason: the channel carries the
    permanent, and its *computed* P/T does not exist once it has left the
    battlefield (CR 613.1), so admitting "power" would stamp a definition the
    resolution answers with a zero. A card printing one is a refusal here rather
    than a silent nothing.
    """
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    if node.definition.characteristic != "mana_value":
        raise LoweringError(
            "only the sacrificed permanent's mana value is read back from a "
            "cost payment",
            node=node,
        )
    return _stamp_x_from_count(
        inner, {"cost_sacrifice_characteristic": node.definition.characteristic}
    )


def _lower_where_x_counters(
    node: ast.WhereX, inner: tuple[OracleInstruction, ...]
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of +1/+1 counters on it." (Primordial Ooze.)

    Not a count of a *set*, so it carries no filter: a counter is not an object
    and ``evaluate_count`` scans zones for objects. What it names is a number
    sitting on the ability's own source, which only a resolution knows — the
    same thing ``object_characteristic`` is for one named object's power.

    The kind rides the spec, so a card counting a differently-named counter this
    way needs no production. It is stamped like every other definition, so the
    whole sentence — the offer, the payment, and the "if you don't" behind it —
    reads one X.
    """
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"source_counters": node.definition.kind})


def _lower_where_x_sacrificed_power(
    node: ast.WhereX, inner: tuple[OracleInstruction, ...]
) -> tuple[OracleInstruction, ...]:
    """"…where X is the total power of the creatures sacrificed this way."
    (Sword of the Ages.)

    Not a count of a set on any board, so it carries no owner and no zone: the
    creatures were eaten by this ability's own cost (CR 601.2h) and are cards in
    a graveyard by the time X is read. What is summed is their last power on the
    battlefield (CR 608.2h), recorded as the cost was charged.

    Only "creatures" is admitted, because that is the only set the cost charger
    records — a card printing another noun would be aggregating over a payment
    nothing kept, and lowering refuses rather than reading a zero.
    """
    filt = node.definition.filter
    if filt.card_types != ("creature",) or _restrictions_beyond(
        filt, frozenset({"card_types"})
    ):
        raise LoweringError(
            "the sacrificed total is read off creatures and nothing narrower",
            node=node,
        )
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"cost_sacrifices_power": True})


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


def _count_filter_for(filt, inner: tuple[OracleInstruction, ...], node, event=None):
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
    # "At the beginning of each opponent's upkeep, … where X is the number of
    # nontoken permanents of the chosen color **they control**" (Psychic
    # Allergy). Nothing was targeted: the seat is the one the *event* was about,
    # frozen into the trigger's context by the upkeep step (CR 603.10). Which
    # events carry one is `_EVENT_SUBJECT_PLAYERS` — the same table the damage
    # recipient beside it reads, so the count and the damage cannot end up on
    # two different players.
    if not _names_a_player_target(inner):
        if event in _EVENT_SUBJECT_PLAYERS:
            return dataclasses.replace(
                filt, controller=None,
                zone_owner=ast.PlayerRef(EVENT_SUBJECT_PLAYER),
            )
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
    role = _referent_role(node, inner)
    names_a_spell = any(i.payload.get("bound_to_trigger") for i in inner)
    if names_a_spell and node.definition.characteristic != "mana_value":
        # A spell on the stack has no power or toughness to read (CR 208.1), so
        # a clause asking for one about a bound spell is a misreading of one
        # half or the other. Refused rather than answered with a zero the card
        # never printed.
        raise LoweringError(
            "a spell has no power or toughness to read", node=node
        )
    described: dict[str, object] = {
        "object": "triggering_spell" if names_a_spell else "target",
        "characteristic": node.definition.characteristic,
        "offset": node.definition.offset,
    }
    if role is not None:
        # Which of the sentence's targets the clause reads. Absent for every
        # one-target sentence, so nothing downstream has to special-case the
        # common shape — and *present* whenever the sentence named more than
        # one, because "the target" is not an answer then.
        described["role"] = role
    return _stamp_x_from_count(inner, {"object_characteristic": described})


#: What a role's own key licenses a printed back-reference to call it. "that
#: **blocked** creature" is the only way English has to point at the dependent
#: end of ``blocked_by_role`` without repeating the whole relative clause, and
#: the adjective has no filter payload of its own (``ObjectFilter.blocked`` is
#: deliberately unemitted), so it is matched against the *role* rather than
#: against a permanent. A second dependent relation adds a row.
_ROLE_BACKREFERENCE_ADJECTIVES: dict[str, str] = {"blocked_by_role": "blocked"}


def _target_roles(inner: tuple[OracleInstruction, ...]) -> list[dict]:
    """The ordered target roles the lowered sentence describes, if any."""
    for instruction in inner:
        targets = instruction.payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") == "roles":
            return list(targets.get("roles") or ())
    return []


def _referent_role(node: ast.WhereX, inner: tuple[OracleInstruction, ...]) -> str | None:
    """Which target role "the power of **that blocked creature**" names.

    None when the sentence named one target — "its" and "that creature" can
    only mean that one, and the resolution reads it off the single chosen slot
    as it always has.

    When the sentence named **roles**, a referent is required and must match
    exactly one of them. Both halves refuse rather than guess: a bare "its"
    over two targets of different kinds does not say which, and a referent
    matching both would read a characteristic off whichever slot happened to be
    first. Either way the card would still compile and still look supported,
    which is the failure this refusal exists for.
    """
    referent = node.definition.referent
    roles = _target_roles(inner)
    if not roles:
        if referent is not None and _referent_beyond_backreference(referent):
            raise LoweringError(
                "a where-clause referent this sentence cannot name", node=node
            )
        return None
    if referent is None:
        raise LoweringError(
            "this sentence names two targets, so 'its' does not say which",
            node=node,
        )
    if _referent_beyond_backreference(referent):
        raise LoweringError(
            "a where-clause referent this sentence cannot name", node=node
        )
    matched = [role["role"] for role in roles if _referent_matches_role(referent, role)]
    if len(matched) != 1:
        raise LoweringError(
            "a where-clause referent that names no single target role", node=node
        )
    return matched[0]


#: The referent fields a printed back-reference may set. Anything else is a
#: narrowing the match below cannot read, and reading it as though it were
#: absent would point the clause at a role the card never named.
_REFERENT_FIELDS = frozenset({"card_types", "subtypes", "blocked"})


def _referent_beyond_backreference(referent) -> bool:
    default = ast.ObjectFilter()
    return any(
        field.name not in _REFERENT_FIELDS
        and getattr(referent, field.name) != getattr(default, field.name)
        for field in dataclasses.fields(referent)
    )


def _referent_matches_role(referent, role: dict) -> bool:
    """Whether *referent*'s printed words describe *role* and no other."""
    filt = role.get("filter") or {}
    if tuple(referent.card_types) != (
        (filt["type_filter"],) if isinstance(filt.get("type_filter"), str) else ()
    ):
        return False
    if tuple(referent.subtypes) != (
        (filt["subtype_filter"],) if isinstance(filt.get("subtype_filter"), str) else ()
    ):
        return False
    for key, adjective in _ROLE_BACKREFERENCE_ADJECTIVES.items():
        if bool(getattr(referent, adjective, False)) != bool(role.get(key)):
            return False
    return True


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


def _damage_dealt_definition(definition) -> "tuple[ast.DamageDealtThisTurn, int] | None":
    """The damage history a where-clause defines, and the constant added to it.

    "…where X is **3 plus** the amount of damage dealt …" (Blazing Effigy). The
    sum is unwrapped here rather than in the branch below, exactly as
    ``lower_where_x`` unwraps ``ast.Times``: the base belongs to the clause, not
    to the history, and a definition that is a sum over anything *else* falls
    through to the refusals below rather than silently losing its left half.
    """
    base = 0
    if isinstance(definition, ast.Plus) and isinstance(definition.left, ast.Fixed):
        base = int(definition.left.value)
        definition = definition.right
    if isinstance(definition, ast.DamageDealtThisTurn):
        return definition, base
    return None


def _lower_where_x_damage_dealt(
    node: ast.WhereX,
    damage: "tuple[ast.DamageDealtThisTurn, int]",
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"…, where X is 3 plus the amount of damage dealt to this creature this
    turn by other sources named ~." (Blazing Effigy.)

    Stamped like every other where-clause and resolved at the same single
    dispatch point; what differs is only what is read. The record is
    ``engine/damage_ledger.py`` — a history, because the creature the clause
    asks about is in a graveyard by the time a dies-trigger asks, and the damage
    marked on it went with it (CR 400.7).

    Every narrowing the words printed rides on the spec, ``base`` included, so
    the reader applies all of them or none: a base honoured at one return site
    and forgotten at another is the dropped-rider bug with an arithmetic face,
    and here it is the difference between three damage and none.
    """
    definition, base = damage
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(
        inner,
        {
            "damage_ledger": {
                "recipient": definition.recipient,
                "source_name": definition.source_name,
                "others_only": definition.others_only,
                "base": base,
            }
        },
    )
