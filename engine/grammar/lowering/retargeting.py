"""Lowering a change of targets (CR 115.7).

The lowering twin of ``effects/retargeting.py``, split off ``lowering/stack.py``
at Invasion's closing round, when that module stood nineteen lines under the
thousand-line guard. It reuses the name the parse side has carried since Urza's
Destiny's Phase 0, so the mirror re-forms rather than forks — the arrangement
``lowering/search.py`` and ``lowering/reveal.py`` were each made by.

That parse module's docstring said a near-empty ``lowering/retargeting.py``
"would buy back the symmetry and cost the thing symmetry is for", and it was
right while there was one lowering here. There are two now, and the line under
them is the CR's own, the one ``effects/retargeting`` already drew: everything
left in ``stack`` acts on a stack object as a whole — it counters one, copies
one, announces its modes — and a retarget leaves the object where it is and
changes one of the choices made as it was announced (CR 601.2c).

    _lower_change_target         "Change the target of target spell with a
                                 single target …" — the effect *targets* the
                                 spell it re-aims, so the choice is one step
                                 and the write is the step behind it
    _lower_change_event_targets  "…change the target or targets." — the object
                                 is the one the firing event was about, and
                                 every target it has may change, so one
                                 instruction owns the whole loop

Neither reads anything ``stack`` keeps and ``stack`` reads nothing here; there
is no import between the two in either direction.
"""

from __future__ import annotations

from ...oracle_types import EVENT_CHOSEN_TARGETS, OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import _restrictions_beyond


#: Where the retarget's two steps pass the seat the controller picked. Named
#: once because the step that writes it and the step that reads it are two
#: instructions, and a literal in each is how they come to disagree — the same
#: reason ``lowering/redirection._REDIRECT_RECIPIENT_KEY`` is named once.
_NEW_TARGET_KEY = "retarget_new_target"

#: The retarget honours two narrowings of its spell: CR 115.9a's count of what
#: that spell chose, and the zone the head noun names. Everything else about the
#: noun phrase is refused by ``_restrictions_beyond``, because the handler
#: locates the spell itself and would ignore anything it was not told to check.
#:
#: ``zone`` is honoured **structurally** rather than by a check, which is the one
#: shape that may join this set without a matcher behind it: the handler
#: enumerates candidates off ``game.stack`` and has no other list to read, so a
#: phrase saying "on the stack" is asking for what it already does. It appears
#: here at all only because the bare head noun "spell" began recording the zone
#: — before that, "target spell" and "target permanent" produced identical
#: filters and this set had nothing to say about the difference.
_CHANGE_TARGET_HONOURED_FILTER_FIELDS = frozenset({"target_count", "zone"})

#: The bounds on the new target the resolution can actually offer, **beside**
#: the unbounded reading. ``None`` — the card prints no "the new target must
#: be…" sentence at all (Deflection, Divert) — is not a missing bound to be
#: filled in: it is the printed one, "any legal target this spell could have
#: chosen instead", and the resolution offers exactly the list the cast gate
#: would have. A *named* bound is a table row for the reason every other one
#: here is: a bound consumed by the parser and unknown to the handler is a
#: retarget free to aim anywhere.
_CHANGE_TARGET_NEW_TARGETS = frozenset({"player", "creature"})

#: What "…that targets only <this>" / "…and that target is a <noun>" may say the
#: object's **current** target has to be. A separate set from the bound above,
#: which it used to share: the two questions are asked by different readers and
#: only one of the answers is a thing a new target could be. ``"source"`` is the
#: card that separated them — Silver Wyvern's "that targets only this creature"
#: is an identity (``_single_target_is`` compares ``permanent_id`` against the
#: ability's own source), and "the new target must be **this creature**" is not
#: a sentence, because CR 115.7a requires *another* legal target.
_CHANGE_TARGET_CURRENT_TYPES = frozenset({"player", "creature", "source"})

#: The same, for "if that target is <player>". ``None`` is again the printed
#: reading — Deflection asks nothing about who the spell points at now — and
#: "you" is Reflecting Mirror's question. Anything else refuses: there is no
#: other player the picker could name before the effect is on the stack.
_CHANGE_TARGET_CURRENT_TARGETS = frozenset({"you"})


def _lower_change_event_targets(
    node: ast.ChangeEventTargets, produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """CR 115.7a — "…change the target or targets." (Psychic Battle.)

    One instruction, where :func:`_lower_change_target` below needs two: that
    sentence chooses *one* new target and writes it, so the choice is a step and
    the write is the step behind it. This one changes every target the object
    has, all or none, which is a number of choices only the resolution knows —
    so the handler owns the whole loop and suspends inside it.

    Refused unless the firing event froze the object the targets belong to
    (``_events.EVENT_PRODUCES``): "the target or targets" is a back-reference,
    and with nothing to refer back to the line would compile clean and change
    nothing.

    Read bare, the sentence is an order to the effect's own controller. Read
    behind "<player> may", ``lowering/control_flow._offered_target_change``
    folds the offer into this same instruction and writes who chooses and that
    they may decline — see there for why it is not a ``may`` around this.
    """
    if EVENT_CHOSEN_TARGETS not in produced:
        raise LoweringError(
            "\"the target or targets\" needs a trigger whose event chose them",
            node=node,
        )
    payload: dict[str, object] = {}
    if node.silent_for_same_name:
        payload["silent_for_same_name"] = True
    return (OracleInstruction("change_event_object_targets", "", payload),)


def _lower_change_target(node: ast.ChangeTarget) -> tuple[OracleInstruction, ...]:
    """CR 115.7a — "Change the target of target spell with a single target if
    that target is you. The new target must be a player." (Reflecting Mirror.)

    **Two instructions, in printed order**, because the sentence makes two
    decisions and the second reads the first: which player replaces you is
    chosen as the ability resolves, and the change is made with that answer in
    hand. That is the arrangement Backdraft's pair uses
    (``handlers/player_choices.py``) and the one the Nova Pentacle redirect
    uses, and it is what lets an interactive seat be *asked* — a prompt armed
    part-way through a resolution suspends it, and the step behind the prompt
    resumes when the answer arrives.

    Every refusal below is a way the sentence could otherwise mean more than it
    says, and each is a restriction the dispatcher would have no way to test:

    * the spell must be **chosen**, not named by an earlier sentence: there is
      no bound-spell reading of "that spell" here, and admitting one would
      retarget whatever happened to be on the stack.
    * the noun phrase must carry CR 115.9a's ``target_count``, and it must be
      **one**. Without it the phrase reads "target spell", which is every spell
      on the stack — a strictly larger card than any that prints this.
    * where the sentence *does* say what the spell's current target has to be,
      it must be **you**. There is no reading of another player's name that the
      picker could ask about, so anything else refuses rather than being
      dropped into a card that redirects spells aimed anywhere.
    * where it *does* bound the new target, the bound must be one the
      resolution can offer.

    Both of those are printed clauses rather than required ones, and a card
    printing neither is not a card missing them. Deflection is "Change the
    target of target spell with a single target." — every restriction it has is
    in the noun phrase, its new target may be anything that spell could legally
    have chosen, and the two ``None``s below are what say so. This used to
    refuse them, on the reading that an absent clause was an unimplementable
    one; what was actually absent was a candidate list that could hold a
    permanent, and that is in ``handlers/stack.py``, not here.
    """
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "target":
        raise LoweringError(
            "a retarget names the spell it changes rather than finding one",
            node=node,
        )
    filt = spec.filter
    if filt.target_count != 1:
        raise LoweringError(
            "no handler retargets a spell this phrase does not count the "
            "targets of",
            node=node,
        )
    leftover = _restrictions_beyond(filt, _CHANGE_TARGET_HONOURED_FILTER_FIELDS)
    if leftover:
        raise LoweringError(
            "no handler honours this retarget restriction: " + ", ".join(leftover),
            node=node,
        )
    current = node.current_target
    if current is not None and current.kind not in _CHANGE_TARGET_CURRENT_TARGETS:
        raise LoweringError(
            "a retarget asking about another player's target is offered by no "
            "picker",
            node=node,
        )
    if node.new_target is not None and node.new_target not in _CHANGE_TARGET_NEW_TARGETS:
        raise LoweringError(
            "no handler bounds this retarget's new target", node=node
        )
    # "…and **that target is a creature**" (Meddle). The object twin of
    # ``current_target``'s seat question, and a second key rather than a second
    # value of the first: the picker tests a permanent and a face with different
    # readers, and a card printing one prints neither of the other. Held to the
    # same closed set as the new-target bound, so a noun the picker cannot ask
    # about refuses instead of being consumed into a spell this re-aims from
    # anywhere.
    if (
        node.current_target_type is not None
        and node.current_target_type not in _CHANGE_TARGET_CURRENT_TYPES
    ):
        raise LoweringError(
            "no picker asks whether a spell's one target is a "
            f"{node.current_target_type}", node=node,
        )
    payload: dict[str, object] = {
        "result_key": _NEW_TARGET_KEY,
        "current_target": None if current is None else current.kind,
        "new_target": node.new_target,
    }
    # Emitted only when the card prints it, so every payload written before
    # Meddle existed stays byte-identical — a defaulted key would move
    # Deflection and Reflecting Mirror in the differential for a change that
    # says nothing about either of them, which is noise where the differential's
    # whole value is that it is not noisy.
    if node.current_target_type is not None:
        payload["current_target_type"] = node.current_target_type
    # "…target spell **or ability**" (Silver Wyvern). Emitted only when the card
    # prints the union, for the key above's reason: a defaulted ``False`` would
    # move Deflection, Reflecting Mirror, Rebound and Meddle in the differential
    # for a change that says nothing about any of them.
    #
    # The picker turns it into ``stack_include_abilities`` and the enumeration
    # folds the ability list in beside the spell one. Nothing else about the
    # retarget changes: an ability chose its targets at CR 602.2b exactly as a
    # spell chose them at CR 601.2c, and CR 115.7a moves either.
    if node.also_ability:
        payload["also_ability"] = True
    return (
        OracleInstruction("choose_new_spell_target", "", dict(payload)),
        # The ``targets`` description rides the step that actually names the
        # spell. It is what ``legality._ability_target_quantifiers`` reads to
        # decide the target is **mandatory** (CR 602.2b): without it the
        # activation gate treats the ability as targeting nothing, and the {X}
        # and the tap are paid on an empty stack for no effect. The spec itself
        # still comes from the kind table in ``engine/targeting.py``, which is
        # consulted first — this says *that* it targets, not what.
        OracleInstruction(
            "change_target_spell_target", "",
            {**payload, "targets": {"quantifier": "target", "count": 1}},
        ),
    )
