"""**Which of several slots a caster is asked for**, as the ``targets`` payload.

Split off ``_targets`` at the thousand-line guard, on the last clause of that
module's own docstring: it holds CR 601.2b-d — how many objects a sentence
announces, whether the caster or the card chooses them, how a divided spell
shares one amount out — and *"which of several slots is asked for first"*,
which is this module and nothing else.

The seam is the CR's own. An ordinary description says what one slot admits and
is answered in one click; an **ordered roles** description says that a sentence
announced several objects, in what order the caster is asked for them, and what
each slot's legality owes to the ones already chosen (CR 601.2c). The readers
differ accordingly: everything in ``_targets`` is read by the handler that acts
on the one chosen object, and everything here is read by a *walk* —
``legality.role_target_options`` enumerates slot *n* with slots 0…n-1 settled,
the announcement gate re-asks that same call over what the caster named, and
``handlers/_common.roles_still_legal`` asks it a third time at resolution.

**It is the half that grows with the pool**, which is the playbook's tiebreak
when both halves of a split are description builders. The single-slot payload
keys are a closed vocabulary CR 601.2 has not added to in decades; the roles
builders have gained one per set since Fumarole — the dependent relation
(Glyph of Delusion), the independent slots (Fumarole), the seat slot (Donate),
the graveyard slot (Goblin Welder), and now the slots a sentence spends one
step at a time (Lunge).

``_common`` imports the three names its families read straight from here
rather than through ``_targets``: a re-export chain is a binding nobody reads
the middle of, and the split is invisible to every caller either way.
"""

import dataclasses

from .. import ast
from ..errors import LoweringError

from ._filters import _filter_payload
#: A printed relation whose *other end is itself a target*, and the key the
#: dependent role carries to say which role answers it.
#:
#: "target creature that **target Wall** blocked this turn" (Glyph of Delusion)
#: names two targets of different kinds in one noun phrase: the creature the
#: effect acts on, and the Wall whose block record decides which creatures are
#: legal at all. The relation cannot be a plain filter key — ``subject_matches``
#: answers about one permanent, and this one is answered by a *record on the
#: other target* — so the two are described as ordered **roles** instead
#: (:func:`describe_target_roles`), and this table is what makes that shape
#: general: a second such relation is a row here, not a second builder.
#: Keyed by the ``ObjectFilter`` field, valued by the *name* the other end takes
#: as a role and the key the dependent role points back with.
DEPENDENT_TARGET_RELATIONS: dict[str, tuple[str, str]] = {
    "blocked_by_target_object": ("blocker", "blocked_by_role"),
}

#: The role name of the object a roles description's effect actually acts on.
#: One name, read by the lowering that builds the description, by
#: ``engine/targeting.py``'s spec, by ``engine/legality.py``'s enumerator and by
#: the handler at resolution — so "which of the two did the player pick for the
#: counters?" has one answer rather than four positional conventions.
PRIMARY_TARGET_ROLE = "subject"


def describe_target_roles(
    payload: dict[str, object], recipient: ast.TargetSpec
) -> bool:
    """Describe *recipient* as ordered target **roles**, or return False.

    True when the noun phrase named a second target inside itself — one of
    :data:`DEPENDENT_TARGET_RELATIONS` — and the description was written onto
    *payload*; False when it did not, so the caller falls through to the
    ordinary one-target description it already had.

    **The roles are listed in dependency order, not printed order.** Glyph of
    Delusion prints the creature first and the Wall second, but which creatures
    are legal at all is decided by the Wall's block record, so the Wall is role
    0 and the creature role 1. That order is the whole wire convention: the
    picker walks the roles in it, the caster's answers travel in it, and
    ``engine/legality.py`` enumerates role *n* only with roles 0…n-1 already
    settled. Describing them in printed order would ask the caster for a
    creature before anything could say which creatures the card allows.
    """
    filt = recipient.filter
    relation = next(
        (
            field
            for field in DEPENDENT_TARGET_RELATIONS
            if getattr(filt, field, None) is not None
            and not isinstance(getattr(filt, field), bool)
        ),
        None,
    )
    if relation is None:
        return False
    role_name, role_key = DEPENDENT_TARGET_RELATIONS[relation]
    inner = getattr(filt, relation)
    inner_payload = _filter_payload(inner)
    subject_payload = _filter_payload(
        filt, carried_separately=frozenset({relation})
    )
    if not inner_payload or not subject_payload:
        raise LoweringError(
            "a target role with no narrowing would offer every permanent",
            node=recipient,
        )
    payload["targets"] = {
        "kind": "roles",
        "roles": [
            {
                "role": role_name,
                "kind": "object",
                "count": 1,
                "filter": inner_payload,
            },
            {
                "role": PRIMARY_TARGET_ROLE,
                "kind": "object",
                "count": 1,
                "filter": subject_payload,
                role_key: role_name,
            },
        ],
    }
    return True


def describe_independent_target_roles(
    payload: dict[str, object], specs: "tuple[ast.TargetSpec, ...]"
) -> None:
    """Describe several targeted phrases of **one** announcement as ordered roles.

    "Destroy target creature **and target land**." (Fumarole.) The sibling of
    :func:`describe_target_roles` with the dependency taken out: there the
    second slot's legal set is decided by what was chosen for the first, and
    here the two phrases narrow nothing but themselves. Same shape, because it
    is the same question — a spell whose slots are *differently* restricted, so
    the picker has to walk them in order and ask for each one separately
    (CR 601.2c chooses every target as part of one announcement).

    The role name is the printed noun, which is what the picker shows the
    caster ("Choose the land for Fumarole (2 of 2)"). Two slots naming the same
    noun refuse: "target creature and target creature" is "two target
    creatures", a homogeneous count this shape would describe as two pickers
    over one list and then be unable to tell apart at resolution.

    A phrase with no type at all refuses for the same reason
    :func:`describe_target_roles` refuses an unnarrowed role — a slot offering
    every permanent is a slot the caster cannot be asked a meaningful question
    about, and its name would collide with the next such slot.
    """
    roles: list[dict[str, object]] = []
    for spec in specs:
        filter_payload = _filter_payload(spec.filter)
        # "Destroy target **Plains** and target white creature." (Reign of
        # Chaos.) The printed noun of a slot is not always a card type: a
        # subtype names one just as well, and it is the word the caster is
        # asked for. The type is preferred where both are printed ("target
        # Griffin **creature**"), because that is the head of the phrase.
        #
        # A fallback rather than a second reader: the role name is only ever a
        # label and a key, and every narrowing the slot enforces is in the
        # filter beside it — which ``subject_matches`` tests by subtype exactly
        # as it tests by type.
        noun = filter_payload.get("type_filter") or filter_payload.get(
            "subtype_filter"
        )
        if not isinstance(noun, str):
            raise LoweringError(
                "a target role needs a printed noun to be asked for", node=spec
            )
        if any(role["role"] == noun for role in roles):
            raise LoweringError(
                f"two target roles both named {noun!r}", node=spec
            )
        roles.append({
            "role": noun,
            "kind": "object",
            "count": 1,
            "filter": filter_payload,
        })
    payload["targets"] = {"kind": "roles", "roles": roles}



#: The ``controller`` values ``subject_matches`` answers **only from a seat its
#: caller supplies**, and which a roles walk therefore cannot enumerate against.
#:
#: "Destroy target nonblack creature **that player** controls" (Keeper of the
#: Dead) names the seat the sentence in front of it chose. The matcher has the
#: branch — it refuses rather than widening to "any opponent", which is the
#: whole reason these four are spelled out there — but nothing hands
#: ``legality._enumerate_targets`` a seat, so a role narrowed by one offers
#: nothing and the announcement is refused with a message about targets rather
#: than about the missing seat. Declining the conversion leaves such a card's
#: program exactly where it was, which is honest about what is not built: the
#: picker needs the *earlier role's* seat pushed into the enumeration, which is
#: a relation between two roles and a round of its own (SET_PLAYBOOK, Known
#: gaps).
_UNENUMERABLE_CONTROLLERS = frozenset({
    "that_player", "defending_player", "target_player", "target_opponent",
})


#: The keys of a step's ``targets`` description that describe the *sentence*
#: rather than the slot, and so do not travel onto the role built from it.
#: Everything else does — see :func:`describe_sequence_target_roles`.
_ROLE_STRUCTURAL_KEYS = frozenset({"quantifier", "roles", "role"})


def _sequence_role_name(described: dict, taken: set) -> str | None:
    """What the picker calls one step's slot, or None when it has no name.

    The printed noun, exactly as :func:`describe_independent_target_roles`
    names a slot — "Choose the creature for Lunge (1 of 2)". A seat has no
    filter to read one off, so it takes the word Donate's slot 0 already
    carries; every other slot is named by the head of its noun phrase, with
    the subtype as the fallback for a phrase that prints no card type.

    None where the name would be missing or would repeat one already taken: a
    roles walk turns a name back into a slot, so two slots sharing one is an
    announcement whose halves cannot be told apart at resolution.
    """
    from ...targeting import SEAT_ROLE_KINDS

    if described.get("kind") in SEAT_ROLE_KINDS:
        name = "player"
    else:
        filt = described.get("filter") or {}
        name = filt.get("type_filter") or filt.get("subtype_filter")
    if not isinstance(name, str) or name in taken:
        return None
    return name


def describe_sequence_target_roles(
    instructions: "tuple[object, ...]",
) -> "tuple[object, ...]":
    """One line's steps, rewritten so its **two** announced targets are roles.

    "Lunge deals 2 damage to target creature and 2 damage to target player or
    planeswalker." Two instances of the word "target", so CR 601.2c announces
    two objects — and the steps carried one description each, which the picker
    reads through ``targeting._from_instructions``: that returns the *first*
    spec any step describes, so the caster was asked for a creature, the seat
    slot was never announced, and the second step resolved against the target
    the first one was still holding. Lunge dealt both points to the creature.

    **The hard half is telling that sentence from the one it looks like.** A
    printed back-reference is resolved by the parser into a *copy* of its
    antecedent ("Untap target Griffin. **It** gets +2/+2" becomes two identical
    ``TargetSpec``s), so by the time a line is lowered, one target named twice
    and two targets named once are the same shape. 46 announcements in the pool
    carry two or more of them and 42 are the first kind, where building roles
    would ask the caster for a second target the card never prints.

    What separates them here is the one thing a back-reference can never do:
    **change what kind of thing it points at.** "It" names an object because
    its antecedent was one; "they" names a seat for the same reason. So a line
    whose two announced targets are one seat and one object announces two —
    there is no antecedent either could be a copy of. Two of a kind may be
    either, and this refuses them rather than guessing; that remainder is in
    SET_PLAYBOOK's Known gaps with the cards it costs.

    Narrow in four further ways, each of which is a card this must not claim:

    * the plain quantifier "target" only. "Up to one" may be answered with
      nothing and a roles walk answers every role or refuses the announcement
      (``_slot_roles_spec`` declines the same shape for the same reason), and
      a ``divided`` slot is a list rather than a slot at all (Fiery Justice).
    * exactly two such steps. Three would be a real announcement this cannot
      order, and guessing an order is guessing which target is asked for first.
    * a filter the matcher can test in full. A role narrowed by a key
      ``subject_matches`` refuses is one the picker would offer past and the
      resolution ignore — the silent widening every neighbour here refuses.
    * a description that is not already a roles one, so a lowering that built
      its own slots (Fumarole, Goblin Welder) keeps them.
    * the line's **own** steps, never a branch inside one. This walks the
      instructions the line lowered to and does not descend into ``then`` /
      ``else`` / ``action``, which is the same narrowing
      ``legality._announced_target_slots`` already makes and for the same
      reason: a roles walk answers every role or refuses the announcement, so a
      target that only a taken branch would choose would become mandatory at
      announcement time. Goblin Artisans — "if you lose the flip, counter
      target artifact spell you control" — would then be unactivatable with an
      empty stack. (``_from_instructions`` *does* read branches, for the
      picker; the asymmetry is deliberate and this side keeps the strict half.)

    The description is *shared*: both steps carry the same ordered list, each
    with the ``role`` key naming its own slot, so the picker reads one
    announcement off either step and the resolution scopes each step to its own
    (``engine/handlers/control_flow.py``). Every other key of each step's
    original description is kept, because the handlers behind them go on
    reading ``filter`` and ``quantifier``; only ``kind`` moves, and it is what
    tells every reader the announcement is several.
    """
    from ...subject_filters import untestable_filter_keys
    from ...targeting import SEAT_ROLE_KINDS

    slots = [
        (position, instruction.payload["targets"])
        for position, instruction in enumerate(instructions)
        if isinstance(instruction.payload.get("targets"), dict)
    ]
    announced = [
        (position, described) for position, described in slots
        if described.get("quantifier") == "target"
    ]
    if len(slots) != 2 or len(announced) != 2:
        return instructions
    kinds = [described.get("kind") for _position, described in announced]
    if len([kind for kind in kinds if kind in SEAT_ROLE_KINDS]) != 1:
        return instructions
    if len([kind for kind in kinds if kind == "object"]) != 1:
        return instructions
    roles: list[dict[str, object]] = []
    names: set = set()
    for _position, described in announced:
        name = _sequence_role_name(described, names)
        if name is None:
            return instructions
        narrowing = described.get("filter") or {}
        if untestable_filter_keys(narrowing):
            return instructions
        if narrowing.get("controller") in _UNENUMERABLE_CONTROLLERS:
            return instructions
        names.add(name)
        # **Every narrowing the step's own description carried**, not just the
        # kind and the filter. A seat slot's restrictions are keys beside its
        # kind rather than inside a filter — "target **opponent**"
        # (``opponents_only``), "…who attacked this turn", "…who has more life
        # than you do" — and a role built from the kind alone would offer the
        # activator their own seat for a card that says opponent. The picker
        # reads a role through the same ``_from_targets_payload`` every
        # one-target spell goes through, so a key carried here is a key
        # enforced there.
        role: dict[str, object] = {
            key: value for key, value in described.items()
            if key not in _ROLE_STRUCTURAL_KEYS
        }
        role["role"] = name
        if described["kind"] == "object":
            role["count"] = 1
            role["filter"] = narrowing
        roles.append(role)
    by_position = {
        position: role
        for (position, _described), role in zip(announced, roles)
    }
    return tuple(
        instruction if position not in by_position else dataclasses.replace(
            instruction,
            payload={
                **instruction.payload,
                "targets": {
                    **instruction.payload["targets"],
                    "kind": "roles",
                    "roles": roles,
                    "role": by_position[position]["role"],
                },
            },
        )
        for position, instruction in enumerate(instructions)
    )
