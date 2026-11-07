"""No shipped ``for_each`` whose body is several steps puts a permanent onto
the battlefield — the measurement behind leaving such a body unbatched.

``handlers/control_flow.for_each`` opens one event (CR 603.6a) around its
repetitions only when the body is one instruction with nothing nested
(``_a_single_leaf``): a later step of the same repetition may read the
permanent an earlier one entered ("…create a token. It gains haste"), and a
newcomer held for the end of the event is not there to read. The Known-gaps
entry named the multi-step body as not batched. The pool prints none that
enters anything: every ``for_each`` whose body can put a permanent onto the
battlefield is a single leaf (March of Souls, Midnight Ritual, Mogg
Infestation, Parallel Evolution, Glyph of Reincarnation). This test is that
census, so a set that brings the first one has to decide what its repetitions
are — one event or several — before it ships.

"Can put a permanent onto the battlefield" is derived: the instruction kinds
whose handler reaches the entry seam (``test_kg3_batch_roads._entering_functions``,
three calls deep), and the two picks whose *answer* does (a card put from a
hand, a search whose destination is the battlefield).
"""
from __future__ import annotations

from engine.card_loader import load_catalog
from engine.handlers import EFFECT_HANDLERS
from engine.oracle import compiled_units
from tests.engine.test_kg3_batch_roads import _entering_functions, _trees

#: The picks whose answer, not their handler, puts the card down.
_ANSWERED_ENTRIES = frozenset({"put_chosen_card_from_hand_onto_battlefield"})


def _entering_kinds() -> frozenset[str]:
    reaching = _entering_functions(_trees())
    return frozenset(
        kind for kind, handler in EFFECT_HANDLERS.items()
        if getattr(handler, "__name__", None) in reaching
    ) | _ANSWERED_ENTRIES


def _enters(step, kinds) -> bool:
    """Whether *step* can put a permanent onto the battlefield. A step that
    names where its cards go (a search, a reveal) is held to what it names:
    "…put the revealed cards on the bottom" (Kaboom!) reaches the seam only
    in the handler's other spellings."""
    places = [step.payload.get("destination")] + list(
        step.payload.get("destinations") or ()
    )
    if any(isinstance(place, str) for place in places):
        return "battlefield" in places and (
            step.kind == "search_library" or step.kind in kinds
        )
    return step.kind in kinds


def _walk(instruction):
    yield instruction
    for value in (instruction.payload or {}).values():
        if hasattr(value, "kind"):
            yield from _walk(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if hasattr(item, "kind"):
                    yield from _walk(item)


def _single_leaf(steps) -> bool:
    if len(steps) != 1:
        return False
    return not any(
        hasattr(value, "kind")
        or (isinstance(value, (list, tuple)) and any(hasattr(v, "kind") for v in value))
        for value in (steps[0].payload or {}).values()
    )


def test_no_multi_step_for_each_body_puts_a_permanent_onto_the_battlefield():
    kinds = _entering_kinds()
    assert {"create_token", "reanimate_bound_card"} <= kinds, sorted(kinds)
    loops = 0
    leaves: set[str] = set()
    found: set[str] = set()
    for card, program in compiled_units(load_catalog()):
        if not program.supported:
            continue
        roots = list(program.instructions) + [
            ability.instruction for ability in program.triggered_abilities
            if ability.instruction is not None
        ] + [
            ability.instruction for ability in program.activated_abilities
            if ability.instruction is not None
        ]
        for root in roots:
            for step in _walk(root):
                if step.kind != "for_each":
                    continue
                loops += 1
                body = tuple(step.payload.get("effect") or ())
                if not any(_enters(inner, kinds) for top in body for inner in _walk(top)):
                    continue
                (leaves if _single_leaf(body) else found).add(card.name)
    assert loops >= 30, loops
    # The single-leaf ones are batched; the floor says the census sees them.
    assert len(leaves) >= 5, sorted(leaves)
    assert not found, (
        "a for_each whose body is several steps puts a permanent onto the "
        f"battlefield: {sorted(found)} — decide whether its repetitions are one "
        "event (CR 603.6a) before it ships"
    )
