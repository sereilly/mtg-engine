"""One member of a set an earlier sentence chose, as the step that picks it.

"That player chooses and sacrifices **one of those creatures**" (Retribution,
Barrin's Spite) and "Exile **one of those creatures** and put two +1/+1 counters
on the other" (Cannibalize) are one noun phrase under two verbs. The phrase is
not a narrowing: "those creatures" is an identity — the set a sentence in front
of it announced, held under ``CHOSEN_TARGET_PERMANENTS`` — and no filter
describes it. So the selection is a *step*: one ``choose_permanent`` whose
candidates are that record (``among_record``), which writes the pick under
``CHOSEN_PERMANENT`` and the member it left under ``OTHER_CHOSEN_PERMANENT``,
and then the verb acting on the recorded id. Offered over the board instead,
either card would let its player give up, or take, any creature at all.

``_superlatives`` is the same decomposition for the other phrase that names one
object out of a set, and this module is named the way that one is: for what the
words pick out. The word is the parse side's — ``choices._names_a_chosen_member``
asks whether a sentence holds the ``one_of_those`` quantifier ``references``
reads — so the two ends of one phrase carry one name.

**Both functions lived in ``lowering/board.py`` until Planeshift's Phase 0, and
only one of them was ever about that module's subject.** The sacrifice was
written there. The exile was sent to sit beside it at Exodus, when its sixty
lines took ``lowering/exile.py`` past the thousand-line guard, on the grounds
that its shape was not the exile family's: a pick among a set an earlier
sentence chose, which is where its twin already sat. That reason named this
pair as a family a set before it had a file — what it called the board
family's shape is no more about sacrificing than about exiling.

The cut was measured rather than read off that sentence. Neither function calls
anything else ``board`` defines, and the five names only they imported — the
three record keys above, ``CHOSEN_PLAYER`` and ``untestable_filter_keys`` — left
with them. It is also the half that stands still: of the 204 lines ``board``
gained and kept after the tolls left it, thirteen were here, so the room this
leaves behind is ``_lower_sacrifice``'s.

A **floor**, not a family, for ``_bound_exiles``' reason: ``board`` reads the
sacrifice from inside ``_lower_sacrifice``, where its place in that function's
order is part of the production, and a family may not import a sibling.
``grammar/statement_dispatch.py`` reads the exile directly, ahead of the exile
family — the routing it was given when both of these were ``board``'s and
``exile`` could not import them, kept because moving the call into
``_lower_exile`` would be a reordering rather than a cut. It reads ``_common``
and ``_events``, and nothing reads back.
"""

from __future__ import annotations

from ...oracle_types import CHOSEN_TARGET_PERMANENTS, OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import _filter_payload
from ._events import CHOSEN_PERMANENT, CHOSEN_PLAYER, OTHER_CHOSEN_PERMANENT


def _lower_sacrifice_one_of_chosen(
    node: ast.Sacrifice, produced: frozenset[str]
) -> tuple[OracleInstruction, ...] | None:
    """"That player chooses and sacrifices **one of those creatures**."
    (Retribution.)

    Preacher's decomposition again (``destruction._lower_destroy_of_their_choice``
    states it in full): the pick belongs to a seat that is not the effect's
    controller, so it is the ordinary ``choose_permanent`` prompt — armed on
    that seat, answered into the resolution's scratchpad — and the sacrifice
    behind it acts on the recorded id. What is new is only that the candidates
    are a set an *earlier sentence* chose rather than a battlefield the prompt
    scans: a sacrifice offered over the board would let the player give up any
    creature they own, which is a strictly better card than the one printed.

    Returns None without claiming the sentence unless every part is there, so
    an ordinary "sacrifices a creature" keeps its own reading:

    * the subject must be one member of the chosen set (``one_of_those``);
    * the sacrificing player must be the one the first sentence named
      (``that_player``), and a step of this same effect must have recorded that
      seat — with no producer "that player" names nobody and the prompt would
      be armed on the caster, who is exactly the seat the card says must not
      choose (idiom 7);
    * that step must also have recorded the set, or there is nothing to offer.
    """
    subject = node.subject
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "one_of_those"
    ):
        return None
    # "**Their controller** chooses and sacrifices one of them." (Barrin's
    # Spite.) The same seat by its other name: the pair was chosen "controlled
    # by the same player", so its controller and "that player" are one answer —
    # the one the choosing step recorded, not an event's (none fired).
    #
    # Any other seat **refuses** rather than declining: falling through, the
    # generic sacrifice read the quantifier as "a" and offered the whole board.
    if node.player.kind not in ("that_player", "controller") or node.count is not None:
        raise LoweringError(
            "\"one of those\" is sacrificed by the player the choosing "
            "sentence named",
            node=node,
        )
    if CHOSEN_TARGET_PERMANENTS not in produced or CHOSEN_PLAYER not in produced:
        raise LoweringError(
            "\"one of those\" needs an earlier step of this effect that chose "
            "a set and named its controller",
            node=node,
        )
    described = _filter_payload(subject.filter)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the sacrifice prompt cannot test this restriction", node=node
        )
    return (
        OracleInstruction(
            "choose_permanent", "",
            {
                "result_key": CHOSEN_PERMANENT,
                # "**That player** chooses": the seat the sentence in front of
                # this one recorded, not the ability's controller.
                "chooser": "chosen_player",
                # …and the candidates are that same sentence's set. Named as a
                # record rather than copied into a filter, because "those
                # creatures" is an identity and no filter describes it.
                "among_record": CHOSEN_TARGET_PERMANENTS,
                # "Put a -1/-1 counter on **the other**" is the step behind the
                # sacrifice, and this is where the answer to it exists.
                "remainder_key": OTHER_CHOSEN_PERMANENT,
                "filter": described,
                "prompt": "Choose a creature to sacrifice.",
            },
        ),
        OracleInstruction(
            "sacrifice_recorded_permanent", "",
            {"permanents_from": CHOSEN_PERMANENT},
        ),
    )


def _lower_exile_one_of_chosen(
    node: "ast.Exile", subject, produced: frozenset[str]
) -> tuple[OracleInstruction, ...] | None:
    """"Exile **one of those creatures** and put two +1/+1 counters on the
    other." (Cannibalize.)

    ``_lower_sacrifice_one_of_chosen`` above one verb over, and the same
    decomposition: the pick is an ordinary ``choose_permanent`` prompt whose
    candidates are the set an *earlier sentence* chose, and the exile behind it
    acts on the recorded id. Offered over the board instead, the caster could
    exile any creature at all, which is a strictly better card than the printed
    one.

    **The chooser is the ability's controller** (CR 608.2c), which is the whole
    difference from Retribution: that card says "*that player* chooses" and
    names a seat, and this one says nothing — so no ``chooser`` rides the
    payload and the prompt is armed on the caster, which is what an unassigned
    choice means.

    Returns None without claiming the sentence unless the subject really is one
    member of a chosen set, so every ordinary "exile target creature" keeps its
    own reading. With the quantifier present and no set recorded the line
    *refuses*: "those creatures" would name nothing and the prompt would be
    offered an empty list, which is an exile that quietly happens to nobody.
    """
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "one_of_those"
    ):
        return None
    if CHOSEN_TARGET_PERMANENTS not in produced:
        raise LoweringError(
            "\"one of those\" needs an earlier step of this effect that chose "
            "a set",
            node=node,
        )
    described = _filter_payload(subject.filter)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the exile prompt cannot test this restriction", node=node
        )
    return (
        OracleInstruction(
            "choose_permanent", "",
            {
                "result_key": CHOSEN_PERMANENT,
                # Named as a record rather than copied into a filter, because
                # "those creatures" is an identity and no filter describes it.
                "among_record": CHOSEN_TARGET_PERMANENTS,
                # "…and put two +1/+1 counters on **the other**" is the step
                # behind this one, and this is where the answer to it exists.
                "remainder_key": OTHER_CHOSEN_PERMANENT,
                "filter": described,
                "prompt": "Choose a creature to exile.",
            },
        ),
        OracleInstruction(
            "exile_recorded_permanent", "",
            {"permanents_from": CHOSEN_PERMANENT},
        ),
    )
