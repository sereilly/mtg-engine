"""A modal triggered ability, and the mode chosen as it goes on the stack.

CR 700.2b: "The controller of a modal triggered ability chooses the mode(s) as
part of **putting that ability on the stack**. If one of the modes would be
illegal (due to an inability to choose legal targets, for example), that mode
can't be chosen. If no mode is chosen, the ability is removed from the stack."
CR 603.3c says the same from the trigger's side, and CR 603.3d then routes the
rest of the process through CR 601.2c — the targets are chosen right after the
mode, by the same player, at the same moment.

That ordering is the whole reason this module exists. The engine used to choose
a trigger's mode at *resolution*, which is one step too late for anything the
mode targets: by then nothing collects a target, so a targeted mode would run
against a target nobody picked. `engine/oracle.py` refused those cards outright
rather than admit one — the honest half of the gap — and the refusal read "a
targeted mode of a triggered ability has no picker".

This is the picker's half. It is deliberately **one** function, asked at two
moments that must not disagree:

* the enqueue path (`mixins/stack/resolution._choose_trigger_mode`) asks it to
  decide whether the ability can go on the stack at all, and
* the prompt it arms offers exactly what the same call returned.

A gate and a picker that answer from two tables is this engine's recurring
defect; here they answer from one call. The compiler's support gate asks a
third question — "does every mode describe a target the picker could
enumerate?" — through :func:`modal_trigger_mode_spec`, the same derivation
`trigger_mode_options` builds its enumeration from.
"""

from __future__ import annotations

from .oracle_types import OracleInstruction
from .targeting import derive_instruction_spec

#: The instruction kind a "Choose one —" head lowers to. Named once rather than
#: spelled at each reader: `engine/oracle.py` builds it, the enqueue path
#: detects it, and `handlers/control_flow.py` still executes the *non-modal*
#: form (a "gains flying or first strike" alternative inside an effect), which
#: is a different question at a different time.
MODAL_INSTRUCTION_KIND = "choose_one"

#: The payload key that makes a ``choose_one`` a **modal head** (CR 700.2).
#:
#: The kind alone cannot say it, because one kind carries two rules. CR 700.2
#: defines a modal ability by its printed *form* — "two or more options in a
#: bulleted list preceded by instructions … such as 'Choose one —'" — and only a
#: modal ability chooses as it goes on the stack (CR 700.2a/b). Every other
#: "A or B" an effect offers — "loses first strike **or** swampwalk" (Urborg),
#: "a +0/+1 counter **or** a +1/+0 counter" (Dwarven Armorer), "choose flying,
#: first strike, trample, or rampage 3" (Gabriel Angelfire) — is a choice
#: CR 608.2d makes "while applying the effect", which is the
#: ``handlers/control_flow.choose_one`` handler at resolution.
#:
#: Read off the kind, the push path took all nine shipped abilities of the
#: second shape as modal and asked at activation, so a player who saw the
#: response could not answer it with the other alternative. Only
#: ``oracle._modal_trigger_ability`` writes the key — the one place a bulleted
#: head is assembled — so an alternative the grammar lowers is unmodal by
#: construction rather than by a list.
MODAL_HEAD_KEY = "modal"


#: Trigger conditions this engine carries out **inline**, without ever putting
#: the ability on the stack.
#:
#: An enters-the-battlefield trigger is fired and executed inside the resolution
#: of the spell that put the permanent there
#: (``stack/resolution._apply_self_enters_battlefield_triggers``) — a standing
#: approximation of CR 603.3, which would give it its own stack object and its
#: own priority window. That approximation is why it is named here: a trigger
#: with no push has no moment at which CR 700.2b lets its mode be chosen, so a
#: *targeted* mode on one of these would reach resolution with no picker in
#: front of it and run against whatever the cast happened to target.
#:
#: The set is read by the compiler's gate (which refuses such a card) and by the
#: inline path itself (which is what makes the claim true), so the two cannot
#: drift. It shrinks — to empty — the day an ETB trigger uses the stack.
#: ``enters_or_dies`` (Goblin Marshal, Hunting Moa) is here for its **entry**
#: half only. Its death half is announced by `_permanent_to_graveyard` and goes
#: on the stack like any other death trigger; membership here is the claim that
#: the *entry* announcement is carried out inline, which is exactly the claim
#: ``enters_battlefield`` above makes and exactly as approximate. Left out, the
#: entry half would be announced by nothing at all — the card would make its
#: Goblins when it died and not when it arrived, which is a supported card
#: playing as half of itself.
INLINE_TRIGGER_CONDITIONS = frozenset({"enters_battlefield", "enters_or_dies"})


def modal_trigger_modes(instruction: OracleInstruction | None) -> tuple[dict, ...]:
    """The modes of *instruction* when it is a modal head, else ``()``.

    One reader for the payload shape, so "is this ability modal?" and "what are
    its modes?" are the same question asked once. A ``choose_one`` without
    :data:`MODAL_HEAD_KEY` answers ``()``: it is a CR 608.2d choice, and the
    ability goes on the stack with nothing chosen.
    """
    if instruction is None or instruction.kind != MODAL_INSTRUCTION_KIND:
        return ()
    if not instruction.payload.get(MODAL_HEAD_KEY):
        return ()
    return tuple(instruction.payload.get("modes") or ())


def modal_trigger_mode_spec(mode: dict) -> dict | None:
    """The target spec one mode chooses, or ``None`` when it chooses none.

    ``derive_instruction_spec`` is the same derivation a reflexive triggered
    ability's targets come from (CR 603.12) and, one layer down, the same
    ``_from_instructions`` an activated ability's spec comes from. A mode is
    not a special kind of effect — it is an effect that had to wait for a
    choice — so it must not get a second derivation.
    """
    instruction = mode.get("instruction")
    if instruction is None:
        return None
    return derive_instruction_spec((instruction,))


def modal_trigger_targeting_refusal(
    condition_kind: str, modes: tuple[dict, ...],
) -> str | None:
    """Why a modal trigger's targeted modes cannot be offered, or None.

    The gate that keeps this subsystem's picker and the engine's dispatch one
    answer. A mode may target only if the ability it belongs to is *pushed* —
    :data:`INLINE_TRIGGER_CONDITIONS` names the conditions that are not.
    """
    if condition_kind not in INLINE_TRIGGER_CONDITIONS:
        return None
    targeted = next(
        (mode for mode in modes if "targets" in (mode["instruction"].payload or {})),
        None,
    )
    if targeted is None:
        return None
    return (
        f"a targeted mode of an inline {condition_kind} trigger has no picker: "
        f"{targeted['label']!r}"
    )


def modal_trigger_mode_is_derivable(mode: dict) -> bool:
    """Whether the picker could enumerate this mode's targets.

    The compiler's gate. A mode whose instruction carries a ``targets`` payload
    the spec derivation cannot describe would reach the picker as a mode with
    no candidates, and CR 700.2b would then make it permanently unchoosable —
    a card that prints two modes and can only ever take one of them. Refusing
    the card instead keeps it in the backlog where it is visible.
    """
    instruction = mode.get("instruction")
    if instruction is None:
        return False
    if "targets" not in (instruction.payload or {}):
        return True
    return modal_trigger_mode_spec(mode) is not None
