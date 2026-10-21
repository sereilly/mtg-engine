"""How a condition about **colour** becomes its payload.

The lowering-side mirror of ``color_conditions``, cut in the same commit and
along the same seam: a colour asked of the object the guarded effect targets —
on its own ("if it's red", Hydroblast), against the census of the whole
battlefield (Tsabo's Assassin), against one chosen permanent (Guard Dogs), a
described set (Jaded Response) or the other target (Dead Ringers) — or the
census asked about a printed colour with no object at all (the Invasion
Djinns). CR 105.2's colour set, asked of ``engine/color_census.py`` and
``engine/object_colors.py``.

Split out of ``conditions`` at Torment's Phase 0, when that module sat 48 lines
under the thousand-line guard. The seam was measured on both sides rather than
assumed from the parse half: the four commits that grew ``condition_counts``'
colour block (Invasion's census, Planeshift's Guard Dogs, Apocalypse's Dead
Ringers and Jaded Response) are the four that grew these six branches, and the
last three grew nothing else in either module but ``announces_target_pair``,
the referent question Dead Ringers needed, which stays (below). The branches
read ``CHOSEN_PERMANENT``, which nothing left in ``conditions`` does, and
``testable_filter_payload``, which the board count there also reads from
``_common``; no helper of ``conditions`` is read here.

One node of the six is parsed elsewhere: "if it's red" is ``ItIsColor``, an arm
of ``record_conditions``' "it's" branch, which names it as the one node on the
wrong side of its title. Its lowering came here anyway, because it is the
rule the others cite: the four branches about the target refuse under a
trigger for ``ItIsColor``'s reason — three by name and Guard Dogs' through the
census clause — and that sentence should be read in the file that holds the
reason.
``pronoun_target_referent`` and
``announces_target_pair``, the two answers those refusals turn on, stay in
``conditions``: they are asked of the guarded effect by
``statement_dispatch`` before any condition is lowered, whatever its subject,
and the package's ``__init__`` exports both from there.

Order is not part of the division, for the reason ``_record_conditions`` gives:
each branch is a bare ``isinstance`` on its own node class, so which module
reads a node first cannot change what it answers. ``conditions`` hands the node
down at the point the six stood, and a None back means it is not one of them.
A floor for ``conditions``' own reason — its only reader is ``conditions``,
and it reads nothing back.
"""

from __future__ import annotations

from .. import ast
from ..errors import LoweringError
from ._common import testable_filter_payload
from ._events import CHOSEN_PERMANENT


def lower_color_condition(
    condition: ast.Condition,
    produced: frozenset[str],
    event: str | None,
    referent: str | None,
    *,
    target_pair: bool,
) -> "dict[str, object] | None":
    """The payload of a colour condition, or None when *condition* is not one.

    The arguments are ``conditions._lower_condition``'s, passed as it received
    them, and they mean what its docstring says: *produced* is what earlier
    steps of this effect recorded (Guard Dogs' chosen permanent), *event* the
    firing trigger's kind, *referent* what "it" names beside the effect, and
    *target_pair* whether that effect announced exactly two permanents.
    """
    if isinstance(condition, ast.ItIsColor):
        # "Counter target spell **if it's red**." (Hydroblast, Pyroblast.) The
        # pronoun names the object this effect targets, the same referent the
        # keyword clause in ``conditions`` reads — and under a trigger it names
        # the event's subject instead, which nothing here can tell apart, so it
        # refuses there for that clause's reason.
        if event is not None:
            raise LoweringError(
                "'it' names no chosen target under this trigger", node=condition
            )
        if referent is None:
            # No branch to read the referent off, or a branch that targets
            # something this cannot ask about. Refusing is what keeps the
            # condition from being answered about the wrong half of the
            # resolution context — silently, and forever the same way.
            raise LoweringError(
                "'it' has no target to be a colour of here", node=condition
            )
        return {
            "kind": "target_is_color",
            "color": condition.color,
            "negated": condition.negated,
            "target": referent,
        }
    if isinstance(condition, ast.ColorIsMostCommon):
        # "…as long as **white is the most common color among all permanents**
        # or is tied for most common" (the Invasion Djinns). A census of the
        # whole battlefield against a printed colour: no seat, no pronoun and no
        # filter, so nothing here depends on the trigger or the effect beside
        # it. ``tied`` is the printed tail, carried because the two spellings
        # are opposite answers on a level board.
        return {
            "kind": "color_is_most_common",
            "color": condition.color,
            "tied": condition.tied,
        }
    if isinstance(condition, ast.SharesMostCommonColor):
        # "Destroy target creature **if it shares a color with the most common
        # color among all permanents** or a color tied for most common."
        # (Tsabo's Assassin, Barrin's Unmaking.) The pronoun is the target of
        # the effect this guards — :class:`ItIsColor`'s referent, refused for
        # that clause's two reasons: under a trigger "it" most often names the
        # event's subject, and with no single target beside it there is no
        # object to ask.
        #
        # A **permanent** only. The census is of permanents and the two cards
        # target one; a spell on the stack has colours too, but its referent is
        # resolved from the other half of the context and no card prints the
        # question about one, so it refuses rather than being answered about
        # whatever permanent the resolver could reach.
        if event is not None:
            raise LoweringError(
                "'it' names no chosen target under this trigger", node=condition
            )
        if referent != "permanent":
            raise LoweringError(
                "the colour census is asked of a targeted permanent, and this "
                "effect names none",
                node=condition,
            )
        return {"kind": "target_shares_most_common_color", "target": referent}
    if isinstance(condition, ast.SharesColorWithChosenPermanent):
        # "…**if it shares a color with that permanent**." (Guard Dogs.) Two
        # back-references and a gate for each. "It" is the target of the effect
        # this guards — the census clause's referent just above, refused for
        # its two reasons. "That permanent" is the one a "Choose a permanent …"
        # step earlier in this same effect recorded, admitted only where one
        # did: read under any other sentence the words name an object nobody
        # picked, and the evaluator would answer False for ever on a card
        # reporting supported.
        if event is not None:
            raise LoweringError(
                "'it' names no chosen target under this trigger", node=condition
            )
        if referent != "permanent":
            raise LoweringError(
                "a shared colour is asked of a targeted permanent, and this "
                "effect names none",
                node=condition,
            )
        if CHOSEN_PERMANENT not in produced:
            raise LoweringError(
                "'that permanent' names a permanent no step of this effect "
                "chose",
                node=condition,
            )
        return {
            "kind": "target_shares_color_with_chosen",
            "target": referent,
            "permanent_from": CHOSEN_PERMANENT,
        }
    if isinstance(condition, ast.SharesColorWithMatching):
        # "Counter target spell **if it shares a color with a creature you
        # control**." (Jaded Response.) "It" is the target of the effect this
        # guards — :class:`ItIsColor`'s referent, refused for that clause's two
        # reasons — and the far side is every permanent the printed phrase
        # admits, re-read as the instruction is followed (CR 608.2c).
        #
        # A **spell** only. The question about a targeted *permanent* is not
        # one this can settle: "destroy target creature if it shares a color
        # with a creature you control", aimed at the controller's own
        # creature, turns on whether an object is one of the things it is
        # compared with, and no card prints the sentence to rule on. A spell is
        # never a permanent, so there the clause has one reading.
        if event is not None:
            raise LoweringError(
                "'it' names no chosen target under this trigger", node=condition
            )
        if referent != "spell":
            raise LoweringError(
                "a colour shared with a described permanent is asked of a "
                "targeted spell, and this effect names none",
                node=condition,
            )
        return {
            "kind": "target_shares_color_with_matching",
            "target": referent,
            # Every key the phrase produces must be one ``subject_matches``
            # tests: a narrowing nothing can ask ("a creature you control" read
            # as "a creature") widens the set the spell is compared with, and
            # a wider set counters spells the card does not name.
            "filter": testable_filter_payload(
                condition.filter,
                refusal="nothing tests the permanents this colour is shared with",
                node=condition,
            ),
        }
    if isinstance(condition, ast.TargetsDifferInColor):
        # "…unless **either one is a color the other isn't**." (Dead Ringers.)
        # The two targets of the effect this guards, and admitted only where
        # that effect really announced two: beside one target, or a sweep, the
        # words name a pair nobody chose and the evaluator would answer the
        # same way for ever on a card reporting supported. Under a trigger the
        # pair is refused for ``ItIsColor``'s reason, at the head of this
        # function.
        if event is not None or not target_pair:
            raise LoweringError(
                "'either one' and 'the other' name the two targets of the "
                "effect beside them, and this effect announces no such pair",
                node=condition,
            )
        return {"kind": "targets_differ_in_color"}
    return None
