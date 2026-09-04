"""Damage over a set the sentence **describes** rather than chooses.

CR 611.2c's set: nothing is targeted, nobody picks, and every permanent the
printed noun phrase names is dealt to — fixed when the effect begins. That is a
different question from CR 115's targeting, and it is the one question this
module answers.

A **floor**, not a family, for ``_amounts``' reason exactly: ``damage.py``
imports it and it imports nothing back, and inside ``lowering/`` a module a
family reads cannot itself be one.

Split out when ``lowering/damage.py`` reached the thousand-line guard, and the
split is what made the shape one shape again. It was *already* half-exiled:
``_lower_described_set_damage`` sat in ``_common`` — the module every family
reads, for payload shapes and small values — with a comment saying it was there
because ``damage.py`` was full, while the ``each`` spelling of the same clause
stayed inline in ``damage.py``. So one printed idiom had two lowerings in two
files, and they had already drifted: the inline one checked the head noun and
then *stripped* it, which is why Pyroclasm dealt its 2 to every land on the
table (see :func:`lower_each_matching_damage`).

:func:`_sweep_kind` followed at Mirage's second-wave integration, when
``damage.py`` reached the guard again with no branch at fault. It was the last
of the half-exile: two docstrings here already named it as the thing consulted
*before* the payload-carrying sweep below, and the module that documents a
decision is the module that should hold it. It is the same question this file
answers — which printed recipient set is one batch — asked of the three sets
that earned a fused kind of their own.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec
from ._common import _filter_payload


def describes_a_swept_set(node: ast.DealDamage) -> bool:
    """Whether *node*'s recipients are one described set rather than a choice.

    One definition, asked twice: by the gate that refuses a per-recipient
    multiplier on any other shape, and by the branch that honours one. Two
    spellings of "is this the sweep?" is how a gate and its dispatch come to
    disagree, which for a multiplier means a rider refused in one place and
    dropped in the other.
    """
    return (
        len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.TargetSpec)
        and node.recipients[0].quantifier == "each"
        and not node.recipients[0].targeted
    )


def refuse_unswept_multiplier(node: ast.DealDamage) -> None:
    """Refuse "…for each <objects>" on a damage clause that cannot apply it.

    The multiplier is a rider on the printed amount, and a rider reaching a
    branch that does not read it is *dropped* — here that is Baki's Curse
    dealing a flat 2 to the whole board while reporting itself supported, which
    is the one outcome this engine ranks below being unsupported. Only the
    described-set sweep multiplies per recipient, so every other shape refuses
    at the top of the lowering rather than each branch remembering to.
    """
    if node.per_each is not None and not describes_a_swept_set(node):
        raise LoweringError(
            "no damage handler multiplies this clause per recipient", node=node
        )


def _per_recipient_count(node: ast.DealDamage) -> dict:
    """"…for each **Aura attached to that creature**." (Baki's Curse.)

    A count taken once per member of the swept set, so it travels on its own
    payload key rather than as an ``x_from_count``: that key holds **one**
    number for the whole resolution, and a per-recipient multiplier folded into
    it would deal every creature the count taken off whichever one was read
    first — five creatures, one Aura between them, ten damage each.

    "That creature" is the recipient. The noun parser records the referent as
    ``target``, because a back-reference to the sentence's object is normally a
    target; a described set is the one shape where that object is *many*, and
    the handler resolves the relation against each of them in turn. It is
    rewritten to ``source`` on the way into ``count_spec`` because that is
    ``evaluate_count``'s own name for "the permanent this spec's relations
    resolve against" — and the handler passes the struck permanent as exactly
    that. Rewritten rather than given a fourth referent word, so the evaluator
    keeps one vocabulary and ``count_spec`` needs no branch.

    Only an attachment count is admitted. A phrase naming any other set would
    be counted once for the whole sweep, off a spec whose owner scope this
    strips — a number with no relation to the recipient at all.
    """
    filt = node.per_each
    if filt.attached_to != "target":
        raise LoweringError(
            "no damage handler counts this set per recipient", node=node
        )
    spec = count_spec(dataclasses.replace(filt, attached_to="source"), node)
    # The owner scope is dead on an attachment count — ``evaluate_count`` reads
    # the record kept on the permanent rather than scanning a battlefield — and
    # leaving it saying "you" would state a claim the card does not make: an
    # opponent's Aura on your creature is attached to your creature.
    spec.pop("owner", None)
    return spec


def lower_each_matching_damage(
    node: ast.DealDamage,
    recipient: ast.TargetSpec,
    amount,
    computed: bool,
) -> tuple[OracleInstruction, ...]:
    """"…deals 2 damage to **each creature you control**" (Sorrow's Path),
    "…to **each creature**" (Pyroclasm), "…to each creature **for each Aura
    attached to that creature**" (Baki's Curse).

    A creature sweep narrowed by a printed noun phrase, which is what
    ``_sweep_kind``'s three fused kinds each are with the narrowing baked into
    the kind's name. Here the narrowing is payload, so a card printing a
    different one needs no code — and the fused kinds keep their cards because
    ``_sweep_kind`` is consulted first.

    Creatures only, checked rather than assumed: CR 120.1a says damage cannot be
    dealt to an object that is not a battle, a creature or a planeswalker, so a
    sweep written over "each permanent" would mark damage nothing could ever
    read.

    **And the word stays in the payload.** It used to be checked here and then
    stripped, while ``deal_damage_each_matching`` walks ``all_permanents()`` and
    asks only what the payload says — so Pyroclasm dealt its 2 to every Mountain
    on the table and Sorrow's Path to every permanent its controller had.
    Nothing failed, because CR 704.5g only buries a *creature* with lethal
    damage; the damage simply sat unread. It still stamped the "was dealt damage
    this turn" record a printed noun phrase can test (Giant Shark) and still
    spent any prevention shield the land carried. The gate and the sweep were
    reading two different clauses, which is the shape this file exists to keep
    to one.
    """
    from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    if recipient.filter.card_types != ("creature",):
        raise LoweringError(
            "only a creature sweep is damaged by the printed noun phrase",
            node=node,
        )
    if computed:
        raise LoweringError(
            "a creature sweep cannot carry a computed damage amount", node=node
        )
    described = _filter_payload(recipient.filter)
    # Idiom 2: a restriction the matcher cannot test is one the handler would
    # silently ignore, which widens the sweep rather than narrowing it — every
    # creature on the board instead of the printed set.
    if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError(
            "the creature sweep cannot test this restriction", node=node
        )
    payload: dict[str, object] = {"amount": amount, "filter": described}
    if node.per_each is not None:
        payload["per_recipient_count"] = _per_recipient_count(node)
    return (OracleInstruction("deal_damage_each_matching", "", payload),)


def lower_counted_sweep_damage(
    node: ast.DealDamage, recipient: ast.TargetSpec
) -> tuple[OracleInstruction, ...]:
    """"…it deals damage to **each nonblue creature without flying** equal to
    half the number of Islands you control, rounded down." (Floodgate.)

    The two sweeps above with a *counted* amount instead of a printed one. Both
    of them refuse one outright ("a creature sweep cannot carry a computed
    damage amount"), and that refusal was about the amount reaching the handler:
    they emit ``amount`` as a literal and ``deal_damage_each_matching`` resolves
    it against ``context.x_value``.

    Which is exactly the channel a count already travels on.
    ``X_FROM_COUNT`` is evaluated at the single dispatch point
    (``mixins/oracle_instructions``) and substituted into the context's X
    *before* any handler runs, so a sweep asking for ``"x"`` gets the number the
    same way every counted single-recipient damage does — one number for the
    whole resolution, which is what CR 611.2c's fixed set wants.

    The set's own refusals are the two sweeps' unchanged: creatures only
    (CR 120.1a — damage marked on anything else is never read), and every key of
    the printed noun phrase testable by ``subject_matches``, because a narrowing
    the matcher drops burns a strictly larger board than the card prints.
    """
    from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    assert isinstance(node.amount, ast.CountOf)
    if node.per_each is not None or node.riders != ast.DamageRiders():
        raise LoweringError(
            "a counted sweep carries no multiplier and no riders", node=node
        )
    if recipient.filter.card_types != ("creature",):
        raise LoweringError(
            "only a creature sweep is damaged by the printed noun phrase",
            node=node,
        )
    described = _filter_payload(recipient.filter)
    leftover = set(described) - TESTABLE_SUBJECT_FILTER_KEYS
    if leftover:
        raise LoweringError(
            "the damage sweep cannot narrow by: " + ", ".join(sorted(leftover)),
            node=node,
        )
    from ...oracle_types import X_FROM_COUNT

    return (
        OracleInstruction(
            "deal_damage_each_matching", "",
            {
                "amount": "x",
                "filter": described,
                X_FROM_COUNT: count_spec(node.amount.filter, node),
            },
        ),
    )


def lower_described_set_damage(
    node, recipient, amount, computed: bool
) -> tuple[OracleInstruction, ...]:
    """"…deals 1 damage to each **Goblin** creature." (Goblin Shrine.)

    The same set as :func:`lower_each_matching_damage` reached by the other
    quantifier — "all" as well as "each" — and with no head-noun requirement,
    which is the one thing that keeps it separate: this one is where a sweep
    over a noun phrase that is not "creature" lands, and it refuses the printed
    quantifiers it does not recognise rather than guessing.

    Every refusal below is the same rule: a narrowing the matcher cannot test
    would be *dropped*, and a dropped narrowing on a sweep burns a strictly
    larger part of the board than the card prints.
    """
    from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    if recipient.quantifier not in ("all", "each") or recipient.targeted:
        raise LoweringError("unsupported damage target quantifier", node=node)
    if computed:
        raise LoweringError(
            "a described-set damage sweep cannot carry a computed amount",
            node=node,
        )
    described = _filter_payload(recipient.filter)
    leftover = set(described) - TESTABLE_SUBJECT_FILTER_KEYS
    if leftover:
        raise LoweringError(
            "the damage sweep cannot narrow by: " + ", ".join(sorted(leftover)),
            node=node,
        )
    return (
        OracleInstruction(
            "deal_damage_each_matching", "", {"amount": amount, "filter": described}
        ),
    )


def _sweep_kind(recipients: tuple[ast.Recipient, ...]) -> str | None:
    """Recognize the board-sweep damage shapes as their dedicated handlers.

    These are genuinely different effects, not riders: they damage every player
    *and* a filtered set of creatures as one state-based-action batch.
    """
    hits_players = any(
        isinstance(r, ast.PlayerRef) and r.kind in ("each_player", "each_opponent")
        for r in recipients
    )
    creature_specs = [
        r for r in recipients
        if isinstance(r, ast.TargetSpec) and r.quantifier == "each"
    ]
    if len(creature_specs) != 1:
        return None
    filt = creature_specs[0].filter
    if filt.card_types != ("creature",):
        return None

    if hits_players:
        if filt.without_keywords == ("flying",):
            return "earthquake_damage"
        if filt.with_keywords == ("flying",):
            return "hurricane_damage"
        if not filt.with_keywords and not filt.without_keywords:
            return "deal_damage_each_creature_and_player"
        return None
    if filt.attacking and not filt.with_keywords and not filt.without_keywords:
        return "deal_damage_each_attacking_creature"
    return None
