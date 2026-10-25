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
``legality_roles.role_target_options`` enumerates slot *n* with slots 0…n-1 settled,
the announcement gate re-asks that same call over what the caster named, and
``handlers/_targets.roles_still_legal`` asks it a third time at resolution.

**It is the half that grows with the pool**, which is the playbook's tiebreak
when both halves of a split are description builders. The single-slot payload
keys are a closed vocabulary CR 601.2 has not added to in decades; the roles
builders have gained one per set since Fumarole — the dependent relation
(Glyph of Delusion), the independent slots (Fumarole), the seat slot (Donate),
the graveyard slot (Goblin Welder), the slots a sentence spends one step at a
time (Lunge), and now a slot on the **stack** beside one that is not
(Suffocating Blast: "counter target spell and … deals 3 damage to target
creature").

``_common`` imports the three names its families read straight from here
rather than through ``_targets``: a re-export chain is a binding nobody reads
the middle of, and the split is invisible to every caller either way.
"""

import dataclasses

from ...oracle_types import OracleInstruction
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
#: ``engine/targeting.py``'s spec, by ``engine/legality_roles.py``'s enumerator and by
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
    ``engine/legality_roles.py`` enumerates role *n* only with roles 0…n-1 already
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
#: The matcher has the branch — it refuses rather than widening to "any
#: opponent", which is the whole reason these four are spelled out there — but
#: nothing hands ``legality_enumeration._enumerate_targets`` a seat, so a role
#: narrowed by one offers nothing and the announcement would be refused with a
#: message about targets rather than about the missing seat. A slot narrowed by
#: one of them is therefore handed back rather than made a role — **except** the
#: one shape :func:`_seat_bound_narrowing` rewrites first, where the seat is the
#: earlier role's own.
_UNENUMERABLE_CONTROLLERS = frozenset({
    "that_player", "defending_player", "target_player", "target_opponent",
})


def _seat_bound_narrowing(
    narrowing: dict, earlier_roles: list,
) -> "tuple[dict, dict]":
    """*narrowing* with a "**that player** controls" bound to the seat role in
    front of it, and the role relation that now carries it — or both unchanged.

    "Choose target opponent … **Destroy target nonblack creature that player
    controls.**" (Keeper of the Dead.) "That player" is the seat the sentence in
    front of it announced, and CR 602.2b announces both targets together — so
    the pronoun is not a seat the matcher can be handed (a resolution's frozen
    event, a mode's chooser) but **the earlier role's own answer**. That is a
    relation between two roles, which is what a role relation is
    (``target_roles.ROLE_RELATION_TESTS``): the walk enumerates the creature
    slot with the player slot settled and keeps the creatures that seat
    controls, the gate re-asks the same walk over what the activator named, and
    the resolution re-asks it once more (CR 608.2b) — one answer to "which
    board?", where the handler used to scan the chosen seat's board for its own
    first match.

    Only for the controller word itself and only after a **seat** role: a
    "that player" with no seat in front of it names a player some other record
    supplies, which is the hand-back the table above keeps.
    """
    from ...target_roles import SAME_CONTROLLER_ROLE, SEAT_ROLE_KINDS

    if narrowing.get("controller") != "that_player":
        return narrowing, {}
    antecedent = next(
        (
            role["role"] for role in reversed(earlier_roles)
            if role.get("kind") in SEAT_ROLE_KINDS
        ),
        None,
    )
    if antecedent is None:
        return narrowing, {}
    unbound = {key: value for key, value in narrowing.items() if key != "controller"}
    return unbound, {SAME_CONTROLLER_ROLE: antecedent}


#: The keys of a step's ``targets`` description that describe the *sentence*
#: rather than the slot, and so do not travel onto the role built from it.
#: Everything else does — see :func:`describe_sequence_target_roles`.
_ROLE_STRUCTURAL_KEYS = frozenset({"quantifier", "roles", "role"})


def _sequence_role_name(
    described: dict, taken: set, *, another: bool = False,
    typeless: str | None = None,
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

    *typeless* is the key for an object slot whose noun phrase prints **no**
    card type or subtype at all — "target **nonland permanent**" (Rushing
    River), whose whole narrowing is an exclusion. Given only by the caller
    that has other proof the sentence names two objects
    (:func:`plan_another_target_roles`, whose proof is the printed "another"):
    :func:`describe_sequence_target_roles` reads a missing name as one more
    reason to hand the line back, and a default here would have it claim
    announcements it declines today.
    """
    from ...target_roles import SEAT_ROLE_KINDS

    filt = described.get("filter") or {}
    if described.get("kind") in SEAT_ROLE_KINDS:
        name = "player"
    elif described.get("kind") == "spell":
        # "Counter **target spell** and … deals 3 damage to target creature."
        # (Suffocating Blast.) An object on the stack has no filter to read a
        # noun off either, and the printed head noun is the one word every
        # such slot shares.
        name = "spell"
    else:
        name = filt.get("type_filter") or filt.get("subtype_filter") or typeless
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
#: an object, and it is the same fact ``target_descriptions._slot_roles_spec`` states
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


def _names_different_nouns(first: dict, second: dict) -> bool:
    """Whether the two slots' noun phrases have different **heads**.

    "Destroy target **artifact or enchantment**. If this spell was kicked, it
    deals damage … to target **creature**." (Orim's Thunder.) The third way a
    line can prove it named two targets rather than one twice, and it is about
    the copy rather than about the board: a back-reference is lowered to a copy
    of its antecedent, and a copy may *lose* a narrowing on the way (Jabari's
    Influence's "it" drops "that attacked you this turn") but never changes
    what kind of thing the phrase names. So two slots whose printed nouns
    differ have no antecedent either could be a copy of.

    Weaker than :func:`_cannot_be_one_permanent` in one respect, which is why
    it is its own predicate: an artifact creature answers both of Orim's
    Thunder's phrases, and CR 115.3 lets one object be chosen once for each
    instance of the word "target". The roles walk refuses the repeat
    (``legality_roles.role_target_options``), as it does for every roles spell.
    """
    nouns = [
        (described.get("filter") or {}).get("type_filter")
        for described in (first, second)
    ]
    return all(isinstance(noun, str) for noun in nouns) and nouns[0] != nouns[1]


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


def _announced_slots(instructions) -> list[tuple[dict, object]]:
    """Every ``targets`` description under *instructions*, in printed order,
    beside **the instruction that carries it**."""
    found: list[tuple[dict, object]] = []
    for instruction in instructions:
        payload = getattr(instruction, "payload", None) or {}
        described = payload.get("targets")
        if isinstance(described, dict):
            found.append((described, instruction))
        for key in _ANNOUNCEMENT_BRANCH_KEYS:
            nested = payload.get(key)
            if isinstance(nested, (list, tuple)):
                found.extend(_announced_slots(nested))
    return found


def _announced_slot_descriptions(instructions) -> list[dict]:
    """Every ``targets`` description under *instructions*, in printed order."""
    return [described for described, _carrier in _announced_slots(instructions)]


def _spell_role_description(described: dict, carrier) -> dict:
    """*described* as a **spell role** carries it: with every stack narrowing
    its own step's picker enforces.

    A role *is* its description — the roles walk enumerates a slot from
    nothing else — and a counter keeps what narrows its spell on its own
    payload rather than in ``targets`` ("counter target **creature** spell" is
    ``card_types`` beside a bare description; ``payload_target_specs._counter_spec`` is
    the reader). Stamped as it stood, such a slot would offer every spell on
    the stack to a card that names some of them. So the step's own derived
    picker is asked, and each ``stack_*`` key it answers with rides the role
    under that name; ``target_descriptions._from_targets_payload`` hands them back.

    Anything else the step's picker says that a role has no word for refuses
    the line, which is the direction that cannot widen an announcement. No
    card prints one today: Suffocating Blast's "target spell" is bare.
    """
    from ...targeting import STACK_TARGET_KIND, derive_instruction_spec

    own = derive_instruction_spec((carrier,)) or {}
    unsaid = sorted(
        key for key in own
        if key != "kind" and not key.startswith("stack_")
    )
    if own.get("kind") != STACK_TARGET_KIND or unsaid:
        raise LoweringError(
            "the step that targets a spell is picked by more than a role can "
            "say" + (": " + ", ".join(unsaid) if unsaid else "")
        )
    return {
        **described,
        **{key: value for key, value in own.items() if key.startswith("stack_")},
    }


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
    reads through ``instruction_targets._from_instructions``: that returns the *first*
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

    **A spell beside anything that is not one is the first argument again**,
    one zone over: "Counter **target spell** and Suffocating Blast deals 3
    damage to **target creature**." A back-reference to a spell names a spell,
    so a stack slot beside a battlefield slot or a seat is two targets. That
    pair is the one this function **never hands back**: handed back, the line
    is read off its first description — a picker offering the spell alone and
    a creature slot nobody announced — so where the walk cannot take the other
    slot (an "any target", an "up to one", a third slot) the line refuses.

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
    from ...target_roles import SEAT_ROLE_KINDS

    # A line whose first step announces **cards in a graveyard** and whose
    # second announces something else (the Advocates) is two targets by the
    # same argument as a spell beside a permanent: a back-reference never
    # changes zone. Asked first, because a one-card graveyard step carries no
    # ``targets`` description for the slot count below to see.
    graveyard_roles = describe_graveyard_card_roles(instructions)
    if graveyard_roles is not None:
        return graveyard_roles
    # A line whose one object slot sits beside a **target seat printed inside
    # its count** ("…to target creature equal to … the number of creatures
    # target opponent controls", Superior Numbers) is two targets by the same
    # argument as a seat beside an object: there is no antecedent either could
    # be a copy of. Asked here, before the slot count below, because the seat
    # carries no ``targets`` description for that count to see.
    counted_roles = describe_counted_seat_roles(instructions)
    if counted_roles is not None:
        return counted_roles

    carried = _announced_slots(instructions)
    slots = list(enumerate(described for described, _carrier in carried))
    announced = [
        (position, described) for position, described in slots
        if described.get("quantifier") == "target"
    ]
    if len(slots) != 2 or len(announced) != 2:
        # **One spell beside anything else is still two targets**, whatever
        # the other slot's quantifier and however many there are: the proof
        # below is about the *kind* of thing each points at. So a line this
        # function cannot turn into roles — "counter target spell and … deals
        # 3 damage to **any target**", a third slot, an "up to one" — is not
        # handed back to be read off its first description, which is the
        # spell-only picker and the bystander the brief's four mis-plays were.
        # It refuses, naming what the walk would have to learn.
        lone_spell = [d.get("kind") for _p, d in slots].count("spell") == 1
        if lone_spell and len(slots) > 1:
            raise LoweringError(
                "a line targeting a spell and another object or player "
                "announces both (CR 601.2c), and the roles walk takes exactly "
                "one plain 'target' beside the spell"
            )
        return instructions
    kinds = [described.get("kind") for _position, described in announced]
    seats = len([kind for kind in kinds if kind in SEAT_ROLE_KINDS])
    objects = len([kind for kind in kinds if kind == "object"])
    spells = kinds.count("spell")
    if spells == 1:
        # "Counter **target spell** and Suffocating Blast deals 3 damage to
        # **target creature**." A spell on the stack beside something that is
        # not one: provably two targets, by this function's own argument — a
        # back-reference can never change what kind of thing it points at — so
        # CR 601.2c announces both. The line used to be left with its *first*
        # description alone, and driven that was a picker offering the spell
        # and nothing else, the cast accepted with no creature on any
        # battlefield, a named artifact dealt the damage, and an unnamed
        # creature slot answered by whichever creature the resolver's scan met
        # first; then it was refused outright, because no roles walk had a
        # stack slot. It has one now (``targeting.role_is_stack``): the walk
        # enumerates it off the stack picker, the announcement carries the
        # stack object beside the permanent ids on the two channels a
        # ``StackItem`` has always had, and each step is scoped to its own
        # (CR 608.2b: one illegal target is skipped and the other half still
        # happens).
        #
        # Beside one object or one seat, and nothing else: a second spell is
        # a back-reference by the same argument (Prohibit's "counter that
        # spell"), and any other kind is a slot the walk has no word for —
        # refused rather than handed back, because handed back is the
        # one-description card above.
        if seats + objects != 1:
            other = next(kind for kind in kinds if kind != "spell")
            raise LoweringError(
                f"a line targeting a spell and a {other!r} slot announces both "
                "(CR 601.2c), and no roles walk enumerates that pair"
            )
        announced = [
            (
                position,
                _spell_role_description(described, carried[position][1])
                if described.get("kind") == "spell" else described,
            )
            for position, described in announced
        ]
    # One seat beside one object, a **spell beside either**, or **two objects
    # no one permanent could answer both of** — the ways a line can prove it
    # named two targets rather than one twice. See
    # :data:`_CONTRADICTORY_CONTROLLERS`; everything else is handed back, which
    # is the 42-announcement remainder the paragraph above is about.
    elif not (
        (seats == 1 and objects == 1)
        or (
            objects == 2
            and (
                _cannot_be_one_permanent(announced[0][1], announced[1][1])
                # …or **two objects named by different nouns** (Orim's
                # Thunder), the copy's own evidence rather than the board's.
                or _names_different_nouns(announced[0][1], announced[1][1])
            )
        )
    ):
        return instructions
    roles: list[dict[str, object]] = []
    names: set = set()
    for _position, described in announced:
        name = _sequence_role_name(described, names)
        narrowing, relation = _seat_bound_narrowing(
            described.get("filter") or {}, roles,
        )
        if (
            name is None
            or untestable_filter_keys(narrowing)
            or narrowing.get("controller") in _UNENUMERABLE_CONTROLLERS
        ):
            if spells:
                # Beside a spell the pair is proven two targets, so a slot the
                # walk cannot name or enumerate is a line that cannot be
                # announced — not one to hand back to its first description.
                raise LoweringError(
                    "a line targeting a spell and another object announces "
                    "both (CR 601.2c), and the roles walk cannot enumerate "
                    "the other slot"
                )
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
        role.update(relation)
        roles.append(role)
    by_position = {
        position: role
        for (position, _described), role in zip(announced, roles)
    }
    return _stamp_slot_roles(tuple(instructions), roles, by_position, [])


#: The count ``owner`` words that name a seat the sentence **targets**, and the
#: seat role each one is announced as. "Target opponent" is CR 102.3's "a
#: player is never their own opponent" on the role (``opponents_only``), so the
#: picker cannot offer the caster their own seat for a card that says opponent.
_COUNTED_TARGET_SEATS: dict[str, dict] = {
    "target_opponent": {"kind": "player", "opponents_only": True},
    "target_player": {"kind": "player"},
}

#: The amount keys a count spec rides under, and the key a nested count is
#: subtracted under ("…in excess of the number of …", Superior Numbers).
_COUNT_PAYLOAD_KEYS = ("x_from_count",)
_NESTED_COUNT_KEYS = ("minus",)


def _counted_target_seats(spec, path: tuple = ()) -> list:
    """``(path, word)`` for every count in *spec* — and its subtrahends —
    scoped to a seat the sentence targets."""
    if not isinstance(spec, dict):
        return []
    found = []
    if spec.get("owner") in _COUNTED_TARGET_SEATS:
        found.append((path, spec["owner"]))
    for key in _NESTED_COUNT_KEYS:
        found.extend(_counted_target_seats(spec.get(key), path + (key,)))
    return found


def _with_owner_role(spec: dict, path: tuple, role: str) -> dict:
    """*spec* with the count at *path* told which role announces its seat."""
    from ...target_roles import COUNTED_SEAT_ROLE

    if not path:
        return {**spec, COUNTED_SEAT_ROLE: role}
    head, *rest = path
    return {**spec, head: _with_owner_role(spec[head], tuple(rest), role)}


def describe_counted_seat_roles(instructions) -> "tuple | None":
    """A line whose one object target sits beside a **target seat inside its
    count**, as ordered roles — or None for every other line.

    "Superior Numbers deals damage to **target creature** equal to the number
    of creatures you control in excess of the number of creatures **target
    opponent** controls." Two instances of the word "target", so CR 601.2c
    announces two — the cards' ruling (2008-08-01): "As you cast this, you
    target a creature and an opponent. The opponent does not have to be that
    creature's controller." The count is the only reader of the second, and
    ``count_spec`` lifts the seat onto its ``owner`` rather than a ``targets``
    description, so the picker derived a creature slot alone and the
    resolution took the seat from ``context.target`` — the **creature's
    controller** where that was an opponent, else the first opponent. At three
    seats the caster could not name the opponent at all.

    So the line becomes the roles walk Lunge's is — the object, then the seat
    (printed order; neither depends on the other) — and the count is told
    which role announces its seat (``target_roles.COUNTED_SEAT_ROLE``), which
    ``handlers/_amounts.count_from_payload`` reads off the announcement rather
    than off whatever a scope left in ``context.target``. The one step is put
    inside a ``sequence`` because that is where a step is scoped to its own
    role (``handlers/control_flow._run``): the damage acts on the creature, and
    nothing of the seat's.

    Narrow, for the line this must not claim: one instruction, one plain
    "target" object slot, one targeted seat in its count. Two targeted seats in
    one count is a walk this does not order and refuses.
    """
    from ...subject_filters import untestable_filter_keys

    steps = tuple(instructions)
    if len(steps) != 1:
        return None
    (step,) = steps
    payload = getattr(step, "payload", None) or {}
    described = payload.get("targets")
    if not (
        isinstance(described, dict)
        and described.get("kind") == "object"
        and described.get("quantifier") == "target"
    ):
        return None
    counted = [
        (key, path, word)
        for key in _COUNT_PAYLOAD_KEYS
        for path, word in _counted_target_seats(payload.get(key))
    ]
    if not counted:
        return None
    if len(counted) != 1:
        raise LoweringError(
            "a count scoped to two targeted seats is a walk the roles "
            "description does not order"
        )
    key, path, word = counted[0]
    narrowing = described.get("filter") or {}
    object_name = _sequence_role_name(described, set())
    if (
        object_name is None
        or untestable_filter_keys(narrowing)
        or narrowing.get("controller") in _UNENUMERABLE_CONTROLLERS
    ):
        raise LoweringError(
            "a target beside a seat its count targets announces both "
            "(CR 601.2c), and the roles walk cannot enumerate the object slot"
        )
    object_role = {
        k: v for k, v in described.items() if k not in _ROLE_STRUCTURAL_KEYS
    }
    object_role.update({"role": object_name, "count": 1, "filter": narrowing})
    seat_role = {"role": "player", **_COUNTED_TARGET_SEATS[word]}
    roles = [object_role, seat_role]
    stamped = dataclasses.replace(step, payload={
        **payload,
        key: _with_owner_role(payload[key], path, seat_role["role"]),
        "targets": {
            **described, "kind": "roles", "roles": roles, "role": object_name,
        },
    })
    return (OracleInstruction("sequence", "", {"steps": (stamped,)}),)


#: The role dependency "…and the **next** of the same printed cards, out of the
#: **same** graveyard". Spelled with the ``_role`` suffix every dependency in a
#: roles description carries (``target_roles.role_dependency`` finds it by
#: that); the answer is one row of ``target_roles.ROLE_RELATION_TESTS``.
LATER_IN_SAME_GRAVEYARD_ROLE = "later_in_same_graveyard_role"

#: What the picker calls each of several printed cards of one graveyard slot,
#: in order. The client shows a graveyard role by its name ("Choose the second
#: card for Nullmage Advocate (2 of 3)", ``roleTargetNoun``), and a roles walk
#: turns a name back into a slot, so the names are the words a person reads
#: and must differ.
_CARD_ORDINALS = ("first", "second", "third", "fourth", "fifth")

#: The spec keys a graveyard step's derived picker may carry beside the
#: narrowings a graveyard role takes (``target_descriptions._GRAVEYARD_ROLE_KEYS``):
#: the count and its two CR 601.2c/115.3 flags, which the roles become. Any
#: other key is a narrowing no role carries, and the line refuses rather than
#: dropping it.
_GRAVEYARD_COUNT_KEYS = frozenset({
    "kind", "max_targets", "exact_targets", "distinct_targets",
})


def _graveyard_step_roles(spec: dict, *, names: tuple) -> list[dict]:
    """The graveyard-card roles one step's derived *spec* is, one per card.

    Every role carries the same narrowing — the spec's own keys, in the names
    ``graveyard_card_matches`` reads, so the picker, the activation gate and
    the resolution ask one predicate — and every role after the first depends
    on the one before it through :data:`LATER_IN_SAME_GRAVEYARD_ROLE`: **the
    same pile**, which is what "N target cards from **an** opponent's
    graveyard" says (one opponent; the cards' 2004-10-04 rulings: "unless a
    single opponent has at least two cards in their graveyard to target"), and
    a later slot in it, which is CR 115.3's distinctness and makes one
    announcement one walk rather than N! orderings of the same cards.
    """
    from ...target_descriptions import _GRAVEYARD_ROLE_KEYS

    unsaid = sorted(
        key for key in spec
        if key not in _GRAVEYARD_COUNT_KEYS and key not in _GRAVEYARD_ROLE_KEYS
    )
    if unsaid:
        raise LoweringError(
            "a graveyard step announced beside another target is narrowed by "
            "more than a graveyard role can say: " + ", ".join(unsaid)
        )
    narrowing = {key: spec[key] for key in _GRAVEYARD_ROLE_KEYS if key in spec}
    roles: list[dict] = []
    for position, name in enumerate(names):
        role: dict = {
            "role": name, "kind": "graveyard_card", "count": 1, **narrowing,
        }
        if position:
            role[LATER_IN_SAME_GRAVEYARD_ROLE] = names[position - 1]
        roles.append(role)
    return roles


def _graveyard_card_noun(spec: dict) -> str:
    """The printed noun of a one-card graveyard slot: "card" for any card,
    "creature card" for Raise Dead's, "artifact card" for Reconstruction's."""
    if spec.get("any_card"):
        return "card"
    card_types = spec.get("card_types")
    if card_types:
        return " or ".join(str(word) for word in card_types) + " card"
    return f"{spec.get('card_type') or 'creature'} card"


def describe_graveyard_card_roles(instructions) -> "tuple | None":
    """A line announcing **cards in a graveyard** beside another target, as
    ordered roles — or None for every other line.

    "{T}: Return two target cards from an opponent's graveyard to their hand.
    Destroy target artifact or enchantment." (Nullmage Advocate; Forcemage,
    Pulsemage and Spurnmage print the shape with one or three cards and
    another second target.) Two sentences, two instances of the word
    "target", one announcement (CR 601.2c through CR 602.2b) — and a picker
    reading the first description alone (``instruction_targets._from_instructions``)
    asked for the cards and never for the permanent, which the second step
    then found by scanning.

    **Provably two targets**, by :func:`describe_sequence_target_roles`' own
    argument one zone over: a back-reference names an object in the zone its
    antecedent is in, and a card in a graveyard and a permanent on the
    battlefield are in different zones — as are a card in *an opponent's*
    graveyard and one in *your* graveyard (Pulsemage), which no one card can
    be at once (CR 404.1). So the line is never handed back to be read off
    its first description: a shape this cannot build refuses.

    The shape, exactly: two top-level steps; the first derives a graveyard
    picker (one card, or a printed count announced in full — "up to" would
    need an optional role, which a roles walk cannot say); the second derives
    either a plain "target" object description or a graveyard picker of its
    own. Each card of the first is a role (:func:`_graveyard_step_roles`), and
    the first step **spends them all** — it carries their names under
    ``role_group`` beside its own ``role``, which
    ``handlers/control_flow._role_scoped`` reads to hand the step every card
    it was announced with.
    """
    from ...subject_filters import untestable_filter_keys
    from ...targeting import GRAVEYARD_TARGET_KIND, derive_instruction_spec

    steps = tuple(instructions)
    if len(steps) != 2:
        return None
    cards_step, other_step = steps
    if (cards_step.payload or {}).get("targets", {}).get("kind") == "roles":
        return None
    cards_spec = derive_instruction_spec((cards_step,)) or {}
    if cards_spec.get("kind") != GRAVEYARD_TARGET_KIND:
        return None
    other_spec = derive_instruction_spec((other_step,)) or {}
    other_described = (other_step.payload or {}).get("targets")
    other_is_object = (
        isinstance(other_described, dict)
        and other_described.get("kind") == "object"
        and other_described.get("quantifier") == "target"
    )
    # "…Prevent all damage that would be dealt to **any target** this turn by a
    # source of your choice." (Shieldmage Advocate.) CR 115.4's union as one
    # role — the walk enumerates it as ``_enumerate_targets`` does any "any"
    # spec, players and permanents both — and the source the sentence chooses
    # (CR 609.7a, not a target) as the announcement's second stage, which the
    # roles description carries whole (``requires_source``).
    other_is_any = (
        isinstance(other_described, dict)
        and other_described.get("kind") == "any"
        and other_spec.get("kind") == "any"
        and set(other_spec) <= {"kind", "requires_source"}
    )
    if (
        other_spec.get("kind") != GRAVEYARD_TARGET_KIND
        and not other_is_object and not other_is_any
    ):
        if not other_spec or other_spec.get("kind") == "none":
            # The second step targets nothing (a draw, a life gain): one
            # announcement, already described by the first step alone.
            return None
        raise LoweringError(
            "a line announcing cards in a graveyard beside another target "
            "announces both (CR 601.2c), and no roles walk enumerates "
            f"a {other_spec.get('kind')!r} slot beside them"
        )
    count = cards_spec.get("max_targets") or 1
    if count > 1 and not cards_spec.get("exact_targets"):
        raise LoweringError(
            '"up to" cards in a graveyard beside another target need an '
            "optional role, which a roles walk cannot say"
        )
    if count > len(_CARD_ORDINALS):
        raise LoweringError("more graveyard cards than the roles walk names")
    noun = _graveyard_card_noun(cards_spec)
    names = (
        (noun,) if count == 1
        else tuple(f"{_CARD_ORDINALS[position]} {noun}" for position in range(count))
    )
    roles = _graveyard_step_roles(cards_spec, names=names)
    if other_is_object:
        narrowing = other_described.get("filter") or {}
        other_name = _sequence_role_name(other_described, set(names))
        if (
            other_name is None
            or untestable_filter_keys(narrowing)
            or narrowing.get("controller") in _UNENUMERABLE_CONTROLLERS
        ):
            raise LoweringError(
                "a line announcing cards in a graveyard beside another target "
                "announces both (CR 601.2c), and the roles walk cannot "
                "enumerate the other slot"
            )
        other_role = {
            key: value for key, value in other_described.items()
            if key not in _ROLE_STRUCTURAL_KEYS
        }
        other_role.update({"role": other_name, "count": 1, "filter": narrowing})
    elif other_is_any:
        other_name = "any target"
        other_role = {"role": other_name, "kind": "any", "count": 1}
    else:
        if other_spec.get("max_targets") not in (None, 1):
            raise LoweringError(
                "several graveyard cards in a line's second slot are a walk "
                "this builder does not order"
            )
        other_name = _graveyard_card_noun(other_spec)
        if other_name in names:
            other_name = f"other {other_name}"
        (other_role,) = _graveyard_step_roles(other_spec, names=(other_name,))
    roles.append(other_role)
    source_stage = {"requires_source": True} if other_spec.get("requires_source") else {}
    cards_targets = {
        **(cards_step.payload.get("targets") or {"quantifier": "target"}),
        "kind": "roles", "roles": roles, "role": names[0],
        "role_group": list(names), **source_stage,
    }
    other_targets = {
        **(other_described if isinstance(other_described, dict) else {"quantifier": "target"}),
        "kind": "roles", "roles": roles, "role": other_name, **source_stage,
    }
    return (
        dataclasses.replace(
            cards_step, payload={**cards_step.payload, "targets": cards_targets},
        ),
        dataclasses.replace(
            other_step, payload={**other_step.payload, "targets": other_targets},
        ),
    )


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
        # "Return target **nonland permanent** … return another target nonland
        # permanent" (Rushing River): no card type to name the slot by, and the
        # role name is a key rather than a label (the client shows a battlefield
        # role by its ``kind``), so CR 110.1's word for anything on the
        # battlefield is the name.
        name = _sequence_role_name(
            described, names, another=position == 1, typeless="permanent",
        )
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
            # an object an earlier role took (``legality_roles.role_target_options``)
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
