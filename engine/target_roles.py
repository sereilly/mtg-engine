"""The vocabulary every reader of a several-role announcement shares.

Most spells choose their targets from one set. "Target creature that **target
Wall** blocked this turn" (Glyph of Delusion) chooses two objects of different
kinds, and the second slot's legal set is decided by what was chosen for the
first. Such a spec carries an ordered ``roles`` list (:data:`ROLES_TARGET_KIND`)
of ordinary object descriptions, and ``engine/legality.py`` enumerates role
*n* with roles 0..n-1 settled.

What is here is the words the picker, the announcement gates, the stack and
the resolution agree on: which roles are seats (:data:`SEAT_ROLE_KINDS`,
:func:`role_is_seat`), where an announcement naming several players records
them (:data:`ROLE_SEATS`), how a role depends on an earlier one
(:data:`ROLE_RELATION_TESTS`), and which slot of a shared announcement a step
spends (:func:`payload_own_role`, :func:`payload_role_slot`). Reading a
``roles`` description into a spec is ``engine/target_descriptions.py``'s
``roles_spec``, beside the description reader it recurses through.

Split out of ``engine/targeting.py`` at the 2,000-line cap; a caller imports
a name from here.
"""

from __future__ import annotations


#: The spec ``kind`` a several-**role** target description takes.
#:
#: Every other kind names one picker over one list, because every other spell in
#: the pool chooses its targets from one set: "up to two target creatures" is two
#: slots of the same kind, and ``_enumerate_targets`` answers all of them at
#: once. "Target creature that **target Wall** blocked this turn" (Glyph of
#: Delusion) is not that. The two slots have different kinds, different
#: narrowings, and — the part no flag can express — the second slot's legal set
#: is decided by what was chosen for the first.
#:
#: So a roles spec carries an ordered ``roles`` list instead of a single kind,
#: and ``engine/legality.py`` enumerates role *n* only with roles 0…n-1 settled.
#: Anything that reads ``spec["kind"]`` and does not know this name sees a kind
#: it has no branch for, which is the loud direction: a roles spec silently
#: reduced to its first role would let a spell be cast with a target no gate
#: ever checked.
ROLES_TARGET_KIND = "roles"


#: The role kinds whose object is a **seat**, not a permanent or a card.
#:
#: One vocabulary, five readers: the picker's ``role_object_at``, the cast
#: gate's ``_named_role_targets``, the announcement stamper on the activation
#: path, ``resolve_role_player`` at resolution and the CR 608.2b re-check
#: beside it. Every one of them used to spell the question ``kind == "player"``
#: on its own, which was the whole of the vocabulary right up until a printed
#: "target player **or planeswalker**" (Lunge, Shower of Sparks) became a role:
#: CR 115.4's widened slot is answered by the same seats the narrow one is, and
#: a reader that did not know the second spelling would fill a *permanent*
#: slot from the seat channel and then find nothing in it.
#:
#: A frozenset rather than a second constant beside ``ROLES_TARGET_KIND``
#: because the readers ask "is this slot a seat?", never "which of the two
#: spellings is it?" — the difference between the two words is what the
#: *picker* offers, and that is settled by ``_enumerate_targets``.
SEAT_ROLE_KINDS = frozenset({"player", "player_or_planeswalker"})


def role_is_seat(role: dict | None) -> bool:
    """Whether *role*'s object is a seat rather than an object in a zone."""
    return bool(role) and role.get("kind") in SEAT_ROLE_KINDS


#: The ``choices`` key an announcement naming **more than one seat** records
#: them under: one entry per role, positional in role order, an ``int`` seat
#: where the role's object is a player and ``None`` everywhere else.
#:
#: "Choose any number of creatures **target player** controls. Choose the same
#: number of creatures **another target player** controls." (Cultural Exchange.)
#: Two instances of the word, both players, and a stack object has one field
#: that means "the player this targets" (``target_player_index``) — which every
#: roles reader filled every seat slot from, so the second player was never
#: announced at all and ``resolve_role_player`` refused the pair outright.
#:
#: **A fourth positional list beside the three a roles announcement already
#: has** (ids, graveyard stamps, indices —
#: ``activation._role_announcement_stamps``), for the reason those are lists:
#: a reader holding slot *n* asks each and exactly one replies. It rides
#: ``choices`` rather than a new ``StackItem`` field for the reason the divided
#: list does (``divided_targets``, the other announcement that names several
#: players): that dict is copied whole onto a copy (CR 707.10) and carried
#: whole into the resolution context, so no construction site has to remember
#: a new field.
#:
#: **Present only where the scalar cannot say it** — two or more seat roles.
#: An announcement with one seat role records nothing here and is read off
#: ``target_player_index`` exactly as it always was, which is every roles card
#: the pool held before this one; where the list is present the scalar still
#: holds the first seat named, so a reader of "the player this spell targets"
#: sees a player the spell really targets.
#:
#: A ``None`` in a seat slot is a slot that **names nobody**: either the
#: announcement left it out (which the gate refuses) or CR 608.2b found its
#: player an illegal target as the object resolved
#: (``stack_targets.blank_illegal_targets``) — and the step that spends that
#: role is then skipped, never re-aimed at the scalar.
ROLE_SEATS = "role_seats"


def recorded_role_seats(holder) -> "list | None":
    """The per-role seat list *holder* recorded (:data:`ROLE_SEATS`), or None.

    *holder* is anything carrying an announcement's ``choices`` — a stack item
    or the resolution context cut from it. None is every announcement that
    named at most one seat, and a ``ChosenMode``, which has no ``choices`` at
    all: a "choose one or more" mode naming two players is not something this
    engine can record, and it answers the way an unrecorded seat always has.
    """
    seats = (getattr(holder, "choices", None) or {}).get(ROLE_SEATS)
    return list(seats) if isinstance(seats, (list, tuple)) else None


def role_seat_positions(roles) -> list[int]:
    """Which slots of *roles* — a spec's or a payload's ordered list — are
    seats."""
    return [
        index for index, role in enumerate(roles or ())
        if isinstance(role, dict) and role_is_seat(role)
    ]


#: What each dependent-role relation asks of the pair, given the *earlier*
#: role's chosen permanent and a candidate for the later one.
#:
#: One table, three readers: ``engine/legality.py`` narrows the picker with it,
#: the same module's gate re-asks it over the targets a caster named, and the
#: handler re-asks it once more at resolution (CR 608.2b). A relation whose
#: picker and whose re-check were separate tables is the defect this repo keeps
#: finding; here the *only* way to add a relation is to add it where all three
#: look.
#:
#: A relation the grammar can describe and this table does not know refuses —
#: ``legality`` offers nothing for it and the re-check answers False — because
#: an unanswerable narrowing must never widen to "any".
#:
#: Each test takes ``(earlier, candidate, game)``. The game is there for the
#: relations that are not readable off the two objects: control is CR 613
#: layer 2 and only ``Game.controller_index_of`` answers it, and a relation
#: that read ``base_controller_index`` instead would be a second opinion about
#: who controls what — the thing the control seam exists to abolish. A test
#: that does not need it simply ignores the argument.
ROLE_RELATION_TESTS = {
    # "target creature that **target Wall** blocked this turn" (Glyph of
    # Delusion). The record is stamped on the blocker by the declare-blockers
    # step and read by id, never by slot: both permanents may leave and return
    # between the cast and the resolution, and CR 400.7 makes the returning one
    # a different object.
    "blocked_by_role": lambda earlier, candidate, game: (
        candidate.permanent_id
        in set(earlier.metadata.get("blocked_attacker_ids_this_turn") or ())
    ),
    # "two target blocking creatures controlled by **the same opponent**"
    # (Sorrow's Path). Which opponent is not a property of either creature —
    # each role's own filter already says "an opponent controls this one", and
    # two roles carrying that filter would admit one blocker from each of two
    # opponents in a CR 802 multi-defender combat. The relation is what makes
    # the second choice depend on the first, and it is asked of the control
    # seam because control moves (CR 613 layer 2).
    # "target artifact a player controls **and target artifact card in that
    # player's graveyard**" (Goblin Welder). The first relation whose two sides
    # are not both permanents: *earlier* is on a battlefield and *candidate* is
    # a :class:`GraveyardTarget`, one card in one pile. What the relation asks
    # is whose pile — the seat the earlier role's own "a player controls"
    # bound — and it is asked of the control seam because control moves
    # (CR 613 layer 2) and the answer has to be the same one the picker,
    # the announcement gate and the resolution all get.
    #
    # ``candidate.seat`` rather than the card's owner: a graveyard is a zone
    # belonging to a player (CR 404.1), and a card sitting in it is in *that*
    # player's graveyard however it got there.
    "in_graveyard_of_role": lambda earlier, candidate, game: (
        game is not None
        and getattr(candidate, "seat", None) is not None
        and game.controller_index_of(earlier) == candidate.seat
    ),
    "same_controller_role": lambda earlier, candidate, game: (
        game is not None
        and game.controller_index_of(earlier) is not None
        and game.controller_index_of(earlier) == game.controller_index_of(candidate)
    ),
}


def role_dependency(role: dict) -> tuple[str | None, str | None]:
    """*role*'s dependency as ``(relation key, earlier role name)``.

    One reader for **both** shapes a role is held in: the lowering's ``targets``
    payload, where the relation *is* the key (``"blocked_by_role": "blocker"``),
    and the derived spec, which lifts it into ``relation``/``depends_on`` so a
    picker can ask one question. Written once because the CR 608.2b re-check at
    resolution holds the payload while the picker holds the spec — and a reader
    that knew only the spec's spelling answered "no dependency" about the
    payload, which is a re-check that passes whatever the board says.
    """
    relation = role.get("relation")
    if isinstance(relation, str):
        depends_on = role.get("depends_on")
        return relation, depends_on if isinstance(depends_on, str) else None
    for key, value in role.items():
        if key.endswith("_role") and isinstance(value, str):
            return key, value
    return None, None


def role_relation_holds(role: dict, earlier, candidate, game=None) -> bool:
    """Whether *candidate* satisfies *role*'s dependency on *earlier*.

    True when the role has no dependency at all — the question does not arise
    for role 0 — and False whenever it has one this engine cannot answer or the
    earlier role resolves to nothing.

    *game* is passed by both callers (the picker in ``engine/legality_roles.py`` and
    the CR 608.2b re-check in ``engine/handlers/_targets.py``) and consumed by
    the relations that need it. It defaults to None so a relation asked without
    one refuses rather than answering from a narrower reading — the same
    direction an unknown relation takes.
    """
    relation, _depends_on = role_dependency(role)
    if relation is None:
        return True
    test = ROLE_RELATION_TESTS.get(relation)
    if test is None or earlier is None or candidate is None:
        return False
    return bool(test(earlier, candidate, game))


def spec_roles(spec: dict | None) -> list[dict]:
    """The ordered roles *spec* names, empty for every one-target spec.

    The one accessor, so a caller never has to test ``kind == "roles"`` *and*
    remember the key. An empty list is the honest answer for a spell that
    chooses one thing, and every loop written over it then reads the same for
    both shapes.
    """
    if not spec or spec.get("kind") != ROLES_TARGET_KIND:
        return []
    return list(spec.get("roles") or ())


def payload_role_slot(payload: dict | None, role: str | None) -> int | None:
    """Which slot of the chosen-target list *role* occupies, read straight off
    an instruction's own ``targets`` description.

    The resolution's form of :func:`role_slot`. A handler holds the payload the
    lowering wrote and not the derived spec, and re-deriving one to ask a
    question the payload already answers is the second reading this module
    exists to abolish. Same list, same order, one answer.
    """
    targets = (payload or {}).get("targets")
    if not isinstance(targets, dict) or targets.get("kind") != ROLES_TARGET_KIND:
        return None
    for index, entry in enumerate(targets.get("roles") or ()):
        if isinstance(entry, dict) and entry.get("role") == role:
            return index
    return None


def payload_own_role(payload: dict | None) -> str | None:
    """Which role of the shared announcement **this instruction** acts on.

    A roles announcement used to be one instruction naming every slot (Donate,
    Goblin Welder), so "which role is mine?" never arose: the handler asked for
    each by name. A sentence whose targets are announced together and *spent* a
    step at a time — "Lunge deals 2 damage to target creature **and** 2 damage
    to target player or planeswalker" — puts the same ``roles`` list on every
    step, and each step then has to say which one it is.

    The key rides inside the ``targets`` description rather than beside it,
    because it is a fact about the announcement and not about the effect: a
    reader holding the description holds the whole answer, and no payload can
    carry a role name with no roles list under it.

    None for every instruction that is not a step of such a sentence, which is
    every other instruction in the pool — so the scoping this feeds is inert
    until a lowering writes the key.
    """
    targets = (payload or {}).get("targets")
    if not isinstance(targets, dict) or targets.get("kind") != ROLES_TARGET_KIND:
        return None
    role = targets.get("role")
    return role if isinstance(role, str) else None


def role_slot(spec: dict | None, role: str | None) -> int | None:
    """Which slot of the chosen-target list *role* occupies, or None.

    The wire, the stack item and the resolution all carry a spell's targets as
    one positional list, and for a roles spell that list is in **dependency
    order** — the order :func:`spec_roles` reports. This is the one translation
    from a role's name to its slot, so the handler that reads "the subject" and
    the where-clause that reads "the blocked creature" cannot disagree about
    which of the two the caster picked.
    """
    if role is None:
        return None
    for index, entry in enumerate(spec_roles(spec)):
        if entry.get("role") == role:
            return index
    return None
