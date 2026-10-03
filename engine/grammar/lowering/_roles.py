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
from ._targets import _targeted_specs, _targets_payload
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


def _sequence_role_name(
    described: dict, taken: set, *, another: bool = False
) -> str | None:
    """What the picker calls one step's slot, or None when it has no name.

    The printed noun, exactly as :func:`describe_independent_target_roles`
    names a slot — "Choose the creature for Lunge (1 of 2)". A seat has no
    filter to read one off, so it takes the word Donate's slot 0 already
    carries; every other slot is named by the head of its noun phrase, with
    the subtype as the fallback for a phrase that prints no card type.

    None where the name would be missing or would repeat one already taken: a
    roles walk turns a name back into a slot, so two slots sharing one is an
    announcement whose halves cannot be told apart at resolution.

    *another* is the slot's printed "**another**" (Withdraw's "then return
    another target creature"), which qualifies a repeated noun exactly as a
    printed controller does below — it is the word that tells the two slots
    apart, so it is the word the key carries.
    """
    from ...targeting import SEAT_ROLE_KINDS

    filt = described.get("filter") or {}
    if described.get("kind") in SEAT_ROLE_KINDS:
        name = "player"
    else:
        name = filt.get("type_filter") or filt.get("subtype_filter")
    # **A repeat of a name already taken is qualified by the seat the slot
    # names, not refused.** "Destroy target creature an opponent controls …
    # destroy target creature you control" (Crooked Scales) prints one noun
    # twice and the whole of what tells the two slots apart is that word —
    # which is also what makes them two announcements rather than one named
    # twice, so refusing on the shared noun would throw the pair away for the
    # very fact that admits it. The name is a *key* for an object role and not
    # a label: the client shows a battlefield role by its ``kind``
    # (``roleTargetNoun``, ``web/static/app.js``), so no caster reads it.
    if isinstance(name, str) and name in taken:
        controller = filt.get("controller")
        if isinstance(controller, str):
            name = f"{controller} {name}"
        else:
            name = f"another {name}" if another else None
    if not isinstance(name, str) or name in taken:
        return None
    return name


#: The ``controller`` values no one permanent can answer at once, which is what
#: makes two slots narrowed by them **two** announcements rather than one named
#: twice.
#:
#: A printed back-reference is lowered to a *copy* of its antecedent and so
#: names the same object; a pair of slots no permanent could answer both of
#: therefore cannot be one. That is the evidence
#: :func:`describe_sequence_target_roles` otherwise has only for a seat beside
#: an object, and it is the same fact ``targeting._slot_roles_spec`` states
#: about its own shared list: "the intersection of 'you control' and 'an
#: opponent controls' is *nothing*".
#:
#: One pair, because it is the one the pool prints. A second is a row here, and
#: the bar for adding one is the bar this pair meets: no permanent on any board
#: answers both printed words.
_CONTRADICTORY_CONTROLLERS = frozenset({frozenset({"you", "opponent"})})


def _cannot_be_one_permanent(first: dict, second: dict) -> bool:
    """Whether no single permanent could answer both slots' narrowings."""
    return frozenset({
        (first.get("filter") or {}).get("controller"),
        (second.get("filter") or {}).get("controller"),
    }) in _CONTRADICTORY_CONTROLLERS


#: Where, below a line's own steps, an announced target can be printed.
#:
#: CR 601.2c is about the **printed instance of the word "target"** and says
#: nothing about which half of a sentence it stands in: the target in "if you
#: lose the flip, destroy target creature you control" (Crooked Scales) is
#: chosen as the ability is activated, whichever way the coin then lands. So
#: the walk descends, and what keeps it from claiming a line it should not is
#: the evidence it demands afterwards, never where the words were printed.
#:
#: ``reflexive`` is deliberately absent: CR 603.12 makes it a separate ability
#: that chooses its own targets when the payment creates it, which is a
#: different announcement made at a later moment.
_ANNOUNCEMENT_BRANCH_KEYS = ("steps", "then", "else", "action", "otherwise")


def _announced_slot_descriptions(instructions) -> list[dict]:
    """Every ``targets`` description under *instructions*, in printed order."""
    found: list[dict] = []
    for instruction in instructions:
        payload = getattr(instruction, "payload", None) or {}
        described = payload.get("targets")
        if isinstance(described, dict):
            found.append(described)
        for key in _ANNOUNCEMENT_BRANCH_KEYS:
            nested = payload.get(key)
            if isinstance(nested, (list, tuple)):
                found.extend(_announced_slot_descriptions(nested))
    return found


def _stamp_slot_roles(instructions, roles: list, by_position: dict, seen: list):
    """*instructions* with each announced slot carrying the shared roles list.

    The same walk :func:`_announced_slot_descriptions` makes, in the same
    order, so a slot's position means the same thing to both — which is what
    lets a role be matched to the step carrying it without holding a
    description's object identity. Two steps may legitimately share one payload
    dict, and an identity map would then stamp one of them twice.
    """
    rewritten = []
    for instruction in instructions:
        payload = getattr(instruction, "payload", None) or {}
        updated = dict(payload)
        changed = False
        described = payload.get("targets")
        if isinstance(described, dict):
            position = len(seen)
            seen.append(described)
            role = by_position.get(position)
            if role is not None:
                updated["targets"] = {
                    **described,
                    "kind": "roles",
                    "roles": roles,
                    "role": role["role"],
                }
                changed = True
        for key in _ANNOUNCEMENT_BRANCH_KEYS:
            nested = payload.get(key)
            if not isinstance(nested, (list, tuple)):
                continue
            inner = _stamp_slot_roles(tuple(nested), roles, by_position, seen)
            if inner != tuple(nested):
                updated[key] = inner
                changed = True
        rewritten.append(
            dataclasses.replace(instruction, payload=updated)
            if changed else instruction
        )
    return tuple(rewritten)


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
    there is no antecedent either could be a copy of.

    **Two of a kind answer the same question a second way**, and only when
    they answer it outright: a back-reference names the *same object* as its
    antecedent, so a pair of slots **no one permanent could satisfy both of**
    cannot be one named twice either. Today that is one printed pair —
    "target creature an opponent controls" beside "target creature you
    control" (Crooked Scales) — and it is a table
    (:data:`_CONTRADICTORY_CONTROLLERS`), not a guess. Every other two of a
    kind is still handed back rather than guessed at; that remainder is in
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

    **The walk descends into branches, and the evidence is what narrows it.**
    This used to read the line's own steps alone — never ``then`` / ``else`` /
    ``action`` — on the ground that a roles walk answers every role or refuses
    the announcement, so a target only a taken branch would choose would become
    mandatory at announcement time. Under CR 601.2c that is not a wrongness:
    every printed instance of the word "target" is announced as the spell is
    cast or the ability activated, and the rule exempts only a mode and an
    alternative or additional cost — never which half of a sentence the word
    stands in. "If you lose the flip, destroy target creature you control"
    (Crooked Scales) is chosen with the coin still in the air.

    What the narrowing was really protecting is a *one*-target ability, where
    nothing but the branch target exists and refusing the announcement refuses
    the whole ability: Goblin Artisans with an empty stack. This function
    cannot reach one — it claims a line only when it announces **two** — so the
    exclusion cost the pool its two-in-branches cards and bought nothing here.
    ``legality._announced_target_slots`` keeps its own copy of the exclusion,
    which is where that argument does bite and is left alone.

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

    slots = list(enumerate(_announced_slot_descriptions(instructions)))
    announced = [
        (position, described) for position, described in slots
        if described.get("quantifier") == "target"
    ]
    if len(slots) != 2 or len(announced) != 2:
        return instructions
    kinds = [described.get("kind") for _position, described in announced]
    seats = len([kind for kind in kinds if kind in SEAT_ROLE_KINDS])
    objects = len([kind for kind in kinds if kind == "object"])
    # One seat beside one object, or **two objects no one permanent could
    # answer both of** — the two ways a line can prove it named two targets
    # rather than one twice. See :data:`_CONTRADICTORY_CONTROLLERS`; everything
    # else is handed back, which is the 42-announcement remainder the paragraph
    # above is about.
    if not (
        (seats == 1 and objects == 1)
        or (
            objects == 2
            and _cannot_be_one_permanent(announced[0][1], announced[1][1])
        )
    ):
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
    return _stamp_slot_roles(tuple(instructions), roles, by_position, [])


#: The branch keys a wrapper's nested steps sit under, for the *other-target*
#: pair below. :data:`_ANNOUNCEMENT_BRANCH_KEYS`, for the reason that table
#: gives: every printed instance of "target" in them is announced with the
#: spell or ability (CR 601.2c), whichever way the resolution then goes.
_ANOTHER_TARGET_BRANCH_KEYS = _ANNOUNCEMENT_BRANCH_KEYS


@dataclasses.dataclass(frozen=True)
class AnotherTargetRoles:
    """A sentence whose two targets the printed "**another**" proves are two.

    *steps* is the sentence with the word lifted off its spec, so no lowering
    reads it as CR 113.7's source exclusion; *slots* is each target's own
    description in printed order, and *roles* the shared ordered list both
    slots are stamped with once the steps are lowered.
    """

    steps: tuple
    slots: tuple
    roles: tuple


def _replace_spec(node, old, new):
    """*node* with the one ``TargetSpec`` object *old* replaced by *new*.

    By identity: the two specs of a two-target sentence are, once the word is
    lifted, equal by value, and only the object says which one was printed
    second.
    """
    if node is old:
        return new
    if isinstance(node, tuple):
        return tuple(_replace_spec(item, old, new) for item in node)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {}
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            replaced = _replace_spec(value, old, new)
            if replaced is not value:
                changes[field.name] = replaced
        return dataclasses.replace(node, **changes) if changes else node
    return node


def plan_another_target_roles(steps) -> "AnotherTargetRoles | None":
    """Read a printed "**another** target" as two announced slots, or None.

    "Return target creature to its owner's hand. Then return **another** target
    creature to its owner's hand unless its controller pays {1}." (Withdraw.)
    The parse resolves anaphora at parse time, so one target named twice and two
    targets named once can look identical by the time a line is lowered
    (:func:`describe_sequence_target_roles` sets out the 42-announcement
    remainder that leaves). The printed "another" is the one word that settles
    it: a back-reference names the *same* object as its antecedent, and
    "another" forbids exactly that — so a pair whose second slot prints it is
    two announcements by its own say-so (CR 115.3: the word "target" twice, and
    a sentence that forbids the repeat the rule would otherwise allow).

    Narrow, for the card this must not claim:

    * exactly two targeted phrases, the **second** printing the word — the
      shape ``_refuse_unfused_distinctness`` refuses, and nothing wider;
    * both a plain "target" object slot. "Up to one" may be answered with
      nothing, which a roles walk cannot say (``_slot_roles_spec``);
    * a narrowing the roles walk can enumerate in full, for
      :func:`describe_sequence_target_roles`' own reason.

    None leaves the sentence to ``_refuse_unfused_distinctness``.
    """
    from ...subject_filters import untestable_filter_keys

    specs = [spec for step in steps for spec in _targeted_specs(step)]
    if len(specs) != 2:
        return None
    first, second = specs
    if first.distinct_from_prior or not second.distinct_from_prior:
        return None
    if first.quantifier != "target" or second.quantifier != "target":
        return None
    plain = dataclasses.replace(second, distinct_from_prior=False)
    slots = (_targets_payload(first), _targets_payload(plain))
    roles: list[dict] = []
    names: set = set()
    for position, described in enumerate(slots):
        if not isinstance(described, dict) or described.get("kind") != "object":
            return None
        name = _sequence_role_name(described, names, another=position == 1)
        narrowing = described.get("filter") or {}
        if (
            name is None
            or untestable_filter_keys(narrowing)
            or narrowing.get("controller") in _UNENUMERABLE_CONTROLLERS
        ):
            return None
        names.add(name)
        role = {
            key: value for key, value in described.items()
            if key not in _ROLE_STRUCTURAL_KEYS
        }
        role.update({"role": name, "count": 1, "filter": narrowing})
        if position == 1:
            # The printed word, written down. The roles walk already refuses
            # an object an earlier role took (``legality.role_target_options``)
            # — that is what *enforces* it — and the key is what says this
            # slot's sentence asked for it rather than the walk's default.
            role["distinct"] = True
        roles.append(role)
    return AnotherTargetRoles(
        steps=_replace_spec(tuple(steps), second, plain),
        slots=slots,
        roles=tuple(roles),
    )


def _another_target_leaves(instructions, found: list) -> None:
    """Every instruction under *instructions* with no nested steps, in order."""
    for instruction in instructions:
        payload = getattr(instruction, "payload", None) or {}
        nested = [
            payload.get(key) for key in _ANOTHER_TARGET_BRANCH_KEYS
            if isinstance(payload.get(key), (list, tuple))
        ]
        if not nested:
            found.append(instruction)
        for branch in nested:
            _another_target_leaves(branch, found)


def _restamped(instructions, stamped: dict):
    """*instructions* with each leaf in *stamped* (by identity) replaced."""
    rewritten = []
    for instruction in instructions:
        if id(instruction) in stamped:
            rewritten.append(stamped[id(instruction)])
            continue
        payload = getattr(instruction, "payload", None) or {}
        updated = dict(payload)
        changed = False
        for key in _ANOTHER_TARGET_BRANCH_KEYS:
            branch = payload.get(key)
            if isinstance(branch, (list, tuple)):
                inner = _restamped(tuple(branch), stamped)
                if any(a is not b for a, b in zip(inner, branch)):
                    updated[key] = inner
                    changed = True
        rewritten.append(
            dataclasses.replace(instruction, payload=updated)
            if changed else instruction
        )
    return tuple(rewritten)


def stamp_another_target_roles(lowered, plan: AnotherTargetRoles) -> tuple:
    """*lowered* with each of *plan*'s two slots stamped onto the step it spends.

    The slot is the **leaf** that acts on the chosen object — the bounce, not
    the offer wrapped round it — exactly where
    :func:`describe_sequence_target_roles` stamps Lunge's two damage steps; the
    resolution scopes each leaf to its own role, and an offer to the role its
    branch spends (``handlers/control_flow._role_scoped``).

    Which leaf is which slot is asked of the engine's own picker rather than
    assumed: a leaf qualifies only when the slot's description says nothing its
    kind did not already say (``targeting.derive_instruction_spec`` answers the
    same for both), and exactly one leaf per slot, in printed order, must. A
    lowering that put the object somewhere else — or two leaves that could each
    be it — refuses the line rather than stamping a guess.
    """
    from ...targeting import derive_instruction_spec

    leaves: list = []
    _another_target_leaves(tuple(lowered), leaves)
    targeting = [
        leaf for leaf in leaves
        if derive_instruction_spec((leaf,)) is not None
    ]
    if len(targeting) != 2 or targeting[0] is targeting[1]:
        raise LoweringError(
            'a printed "another target" needs one acting step per target',
        )
    roles = list(plan.roles)
    stamped: dict = {}
    for leaf, described, role in zip(targeting, plan.slots, roles):
        candidate = dataclasses.replace(
            leaf, payload={**leaf.payload, "targets": described}
        )
        if derive_instruction_spec((candidate,)) != derive_instruction_spec((leaf,)):
            raise LoweringError(
                f"the step acting on the {role['role']} reads a different "
                "target than the sentence printed",
            )
        stamped[id(leaf)] = dataclasses.replace(leaf, payload={
            **leaf.payload,
            "targets": {
                **described, "kind": "roles", "roles": roles,
                "role": role["role"],
            },
        })
    return _restamped(tuple(lowered), stamped)
