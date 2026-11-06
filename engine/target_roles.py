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
#: **Present only where the scalar cannot say it** — two or more seat roles
#: named, or (``several_seat_roles``) a spec several of whose roles a seat may
#: answer, whichever one the announcement named it in ("Choose any number of
#: target players or planeswalkers", Kaboom!: one player named, and the
#: scalar could not say which of twelve slots it answers).
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


#: The role relation "controlled by the player the earlier role **is** or
#: **controls**" — Sorrow's Path's "controlled by the same opponent" when the
#: earlier role is a creature, Keeper of the Dead's "target nonblack creature
#: **that player** controls" when it is a seat. One relation, because the
#: question is one: whose board is the candidate on? (:func:`role_seat_of`.)
SAME_CONTROLLER_ROLE = "same_controller_role"


#: The key a **count** carries naming the role whose seat it is taken on.
#: "…the number of creatures **target opponent** controls" (Superior Numbers)
#: is a target announced beside the spell's object (CR 601.2c) and read by
#: nothing but the count, so the count says which role answers its ``owner``
#: (``lowering/_roles.describe_counted_seat_roles``) and the resolution reads
#: that role's seat off the announcement
#: (``handlers/_amounts.count_from_payload``) — never the seat a scope left
#: in ``context.target``, which for the object's step is the object's
#: controller.
COUNTED_SEAT_ROLE = "owner_role"


def role_seat_of(earlier, game) -> int | None:
    """The seat an earlier role's chosen object **names**, for a relation that
    asks "whose?" of it: a player role's own seat, a permanent's controller
    (CR 613 layer 2, through the control seam), or None.

    By identity for a seat, because a game holds exactly one live
    ``PlayerState`` per seat (``legality_roles._role_object_key``'s reason) —
    and a player compares by value, so ``players.index`` could answer with an
    equal stranger.
    """
    if game is None or earlier is None:
        return None
    for seat, player in enumerate(getattr(game, "players", ()) or ()):
        if player is earlier:
            return seat
    if hasattr(earlier, "permanent_id"):
        return game.controller_index_of(earlier)
    return None


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
    #
    # The earlier role may be a **seat** as well — "target cards from **target
    # player's** graveyard" — whose pile is its own (:func:`role_seat_of`).
    "in_graveyard_of_role": lambda earlier, candidate, game: (
        game is not None
        and getattr(candidate, "seat", None) is not None
        and role_seat_of(earlier, game) == candidate.seat
    ),
    # "Return **two target cards from an opponent's graveyard** to their hand."
    # (Nullmage Advocate.) Several printed cards of one slot, each its own role
    # (``lowering/_roles.describe_graveyard_card_roles``), and both sides are
    # :class:`GraveyardTarget` stamps. Two questions in one relation, both
    # about the pair:
    #
    # * **the same pile** — "an opponent's graveyard" is one opponent's, so a
    #   three-seat announcement may not take one card from each (the card's
    #   2004-10-04 ruling: "unless a single opponent has at least two cards in
    #   their graveyard to target");
    # * **a later card in it** — CR 115.3 forbids naming one card for two of
    #   the slots, and asking for the next one *after* the earlier choice is
    #   that rule with a canonical order on top: the same set of cards is then
    #   one announcement rather than one per ordering, which is what keeps the
    #   walk the browser is handed (``legality_roles._role_target_walk``) the
    #   size of the choice and not of its permutations.
    #
    # The order is the pile's (CR 404.2), read through ``graveyard_index_of``
    # so two copies of one card are told apart by which copy each stamp is.
    "later_in_same_graveyard_role": lambda earlier, candidate, game: (
        game is not None
        and getattr(candidate, "seat", None) is not None
        and getattr(earlier, "seat", None) == candidate.seat
        and game.graveyard_index_of(earlier) is not None
        and game.graveyard_index_of(candidate) is not None
        and game.graveyard_index_of(candidate) > game.graveyard_index_of(earlier)
    ),
    #
    # …and "Choose target opponent … Destroy target nonblack creature **that
    # player** controls" (Keeper of the Dead), where the earlier role is the
    # seat itself (:data:`SAME_CONTROLLER_ROLE`, :func:`role_seat_of`).
    SAME_CONTROLLER_ROLE: lambda earlier, candidate, game: (
        game is not None
        and role_seat_of(earlier, game) is not None
        and role_seat_of(earlier, game) == game.controller_index_of(candidate)
    ),
    # "**Any number of target opponents** each discard their hands …" (Wheel
    # and Deal.) One printed instance of the word, so each opponent at most
    # once (CR 115.3) — which the walk's taken-set already enforces — and the
    # same *set* of opponents is one announcement rather than one per
    # ordering, which is what this relation is for: each seat role after the
    # first names a later seat than the one before it (:data:`LATER_SEAT_ROLE`,
    # ``later_in_same_graveyard_role``'s canonical order one zone over).
    "later_seat_role": lambda earlier, candidate, game: (
        game is not None
        and role_seat_of(earlier, game) is not None
        and role_seat_of(candidate, game) is not None
        and role_seat_of(candidate, game) > role_seat_of(earlier, game)
    ),
    # "Choose **any number of target players or planeswalkers**. For each of
    # them, …" (Kaboom!.) The same canonical order over a union of seats and
    # permanents, and the order the card's ruling handles them in
    # (:data:`LATER_IN_TURN_ORDER_ROLE`, :func:`turn_order_key`).
    "later_in_turn_order_role": lambda earlier, candidate, game: (
        game is not None
        and turn_order_key(earlier, game) is not None
        and turn_order_key(candidate, game) is not None
        and turn_order_key(candidate, game) > turn_order_key(earlier, game)
    ),
}

#: The relation key :data:`ROLE_RELATION_TESTS` reads for "a later seat than
#: the role before it" (Wheel and Deal's canonical order).
LATER_SEAT_ROLE = "later_seat_role"

#: The relation key for "**later in turn order** than the role before it":
#: "Choose any number of target players or planeswalkers. For each of them, …"
#: (Kaboom!). The card's ruling (2022-09-09) handles the targets "one at a
#: time in turn order", each player's group — the player and the permanents
#: they control — starting with the active player's; so the announcement's
#: canonical order *is* that order (:func:`turn_order_key`), the roles walk
#: offers each set of targets once rather than once per ordering, and a loop
#: over the roles in slot order is the ruling's order **between** groups.
#: Within one player's group the ruling lets the caster choose: the
#: :data:`TARGET_GROUP_ORDER` prompt (``handlers/_role_order.py``), whose
#: default — a seat nobody asks — is the slot order, the player and then their
#: planeswalkers by permanent id.
LATER_IN_TURN_ORDER_ROLE = "later_in_turn_order_role"

#: The prompt kind a loop over turn-order roles arms when one player's group
#: holds two or more of its targets (Kaboom!'s 2022-09-09 ruling: "You choose
#: the relative order of targets within that group"), and the resolution record
#: its answer is written to — the role names in the order they are handled.
TARGET_GROUP_ORDER = "target_group_order"


def turn_order_key(obj, game) -> "tuple[int, int, int] | None":
    """Where *obj* — a player, or a permanent — comes in the turn-order
    handling of :data:`LATER_IN_TURN_ORDER_ROLE`: its player's place from the
    active player (CR 101.4), the player before their permanents, and a
    permanent's id among them. None for anything else."""
    seat = role_seat_of(obj, game)
    players = list(getattr(game, "players", ()) or ())
    if seat is None or not players:
        return None
    group = (seat - int(getattr(game, "active_player_index", 0) or 0)) % len(players)
    if any(player is obj for player in players):
        return (group, 0, 0)
    return (group, 1, int(getattr(obj, "permanent_id", 0) or 0))


#: How many roles "**any number of** target players or planeswalkers" is
#: announced through — a bound on any table, for
#: :data:`ANY_NUMBER_OF_SEAT_ROLES`' reason: four seats and eight
#: planeswalkers among them.
ANY_NUMBER_OF_TARGET_ROLES = 12


def any_number_of_players_or_planeswalkers_roles() -> dict:
    """The ``roles`` description "any number of target players or
    planeswalkers" lowers to: :data:`ANY_NUMBER_OF_TARGET_ROLES` optional
    roles, each later in turn order than the one before it
    (:data:`LATER_IN_TURN_ORDER_ROLE`)."""
    roles: list[dict] = []
    for index in range(ANY_NUMBER_OF_TARGET_ROLES):
        role: dict = {
            "role": f"target {index + 1}", "kind": "player_or_planeswalker",
            OPTIONAL_ROLE: True,
        }
        if index:
            role[LATER_IN_TURN_ORDER_ROLE] = f"target {index}"
        roles.append(role)
    return {"kind": ROLES_TARGET_KIND, "roles": roles}


#: The damage recipient "**that player or planeswalker**" inside a loop over
#: announced targets (Kaboom!): whichever object the iteration is scoped to —
#: the permanent its role named, else the player. A payload value rather than
#: a description, because the loop's own announcement is the only one: the
#: step chooses nothing.
ITERATION_TARGET = "iteration_target"


def several_seat_roles(roles) -> bool:
    """Whether more than one of *roles* may be answered by a player — so the
    one scalar seat a stack object carries cannot say which slot it is, and an
    announcement records its seats per role (:data:`ROLE_SEATS`) even when it
    named one."""
    return len(role_seat_positions(roles)) > 1

#: How many seat roles "**any number of** target opponents" is announced
#: through: one optional role per possible opponent, each after the last
#: (:data:`LATER_SEAT_ROLE`), so an announcement names any subset of the
#: opponents, the empty one included (the card's ruling: "You can choose to
#: target zero opponents"). A spec is derived from the card alone, without a
#: table to count, so the count is a bound: seven opponents, an eight-seat
#: game — twice the four seats the web app seats (``web/session_store``). A
#: game with more opponents than this could not name the rest.
ANY_NUMBER_OF_SEAT_ROLES = 7


def any_number_of_opponents_roles() -> dict:
    """The ``roles`` description "any number of target opponents" lowers to:
    :data:`ANY_NUMBER_OF_SEAT_ROLES` optional opponent roles, each a later seat
    than the one before it."""
    return _any_number_of_seat_roles("opponent", ANY_NUMBER_OF_SEAT_ROLES, True)


def any_number_of_players_roles() -> dict:
    """The ``roles`` description "any number of target **players**" lowers to
    (Reward the Faithful, Cabal Conditioning): the opponents' chain with the
    caster admitted (CR 115.1 — a player may target themself), one role more
    so every seat of the same bound can be named, each a later seat than the
    one before it, so no player is named twice (CR 115.3)."""
    return _any_number_of_seat_roles("player", ANY_NUMBER_OF_SEAT_ROLES + 1, False)


def _any_number_of_seat_roles(noun: str, count: int, opponents_only: bool) -> dict:
    """*count* optional seat roles named "<noun> 1" … , each after the last."""
    roles: list[dict] = []
    for index in range(count):
        role: dict = {"role": f"{noun} {index + 1}", "kind": "player"}
        if opponents_only:
            role["opponents_only"] = True
        role[OPTIONAL_ROLE] = True
        if index:
            role[LATER_SEAT_ROLE] = f"{noun} {index}"
        roles.append(role)
    return {"kind": ROLES_TARGET_KIND, "roles": roles}


#: The role key "a permanent **the n-th opponent** controls", its value n
#: (0-based): "For each opponent, gain control of target permanent **that
#: player** controls." (Blatant Thievery.) One printed instance of the word per
#: opponent (CR 601.2c), so the announcement names one object per opponent —
#: "You gain control of only one permanent from each player" (the card's
#: 2004-10-04 ruling). Positional, so the walk offers role *n* only the
#: permanents of the opponent it is for and no two roles can name one
#: opponent's: the opponents are counted in turn order from the caster
#: (CR 101.4) among the players still in the game (CR 800.4a), by
#: :func:`per_opponent_seat` — the one reader the picker, the gates and the
#: announcement record share.
#:
#: **Not optional, and not all of them owed.** A spec derived from the card
#: alone has :data:`ANY_NUMBER_OF_SEAT_ROLES` of them, a bound on any table;
#: the roles past the caster's live opponents are **void** at this table —
#: dropped by :func:`live_roles`, which is asked wherever a game is in hand
#: (the cast spec, the cast gate) — and every one that is left is owed: an
#: opponent with nothing the noun phrase admits is a spell with no legal
#: announcement (CR 601.2c), which "optional role" could not have said.
PER_OPPONENT_ROLE = "per_opponent"

#: The ``choices`` key a per-opponent announcement records **who controlled
#: each permanent it named**, by permanent id — read back as the object
#: resolves: "If a permanent changes controller after being targeted but
#: before this spell resolves, you won't gain control of that permanent"
#: (Blatant Thievery's 2004-10-04 ruling; CR 608.2b — "that player controls"
#: is no longer true of it). Recorded because nothing else can answer it: the
#: role's opponent is counted among the players still in the game, and one who
#: leaves in response (CR 800.4a) renumbers every opponent after them.
ANNOUNCED_TARGET_CONTROLLERS = "announced_target_controllers"


def per_opponent_roles(described: dict, *, kind: str = "object") -> dict:
    """The ``roles`` description "for each opponent, … target <noun> that
    player controls" lowers to: :data:`ANY_NUMBER_OF_SEAT_ROLES` roles, the
    n-th a *described* object the n-th opponent controls
    (:data:`PER_OPPONENT_ROLE`)."""
    roles: list[dict] = []
    for index in range(ANY_NUMBER_OF_SEAT_ROLES):
        roles.append({
            "role": f"opponent {index + 1}'s target", "kind": kind,
            "filter": dict(described), PER_OPPONENT_ROLE: index,
        })
    return {"kind": ROLES_TARGET_KIND, "roles": roles}


def per_opponent_seat(game, caster_index: int, index: int) -> int | None:
    """The seat of *caster_index*'s *index*-th opponent (0-based), counted in
    turn order from the caster (CR 101.4) among the players still in the game
    (CR 800.4a), or None where there are not that many."""
    players = list(getattr(game, "players", ()) or ())
    count = len(players)
    live = [
        (caster_index + step) % count for step in range(1, count)
        if not getattr(players[(caster_index + step) % count], "lost", False)
    ]
    return live[index] if 0 <= index < len(live) else None


def live_roles(game, caster_index: int, spec: dict | None) -> dict | None:
    """*spec* with its per-opponent roles past *caster_index*'s live opponents
    dropped (:data:`PER_OPPONENT_ROLE`), or *spec* itself where it has none.

    They are always trailing — the n-th opponent exists only if the
    (n-1)-th does — so what is left is an ordinary roles spec of exactly one
    owed role per opponent, and every pure reader of a roles spec (the walk,
    the count, ``roles_may_end_at``) is right about it unchanged.
    """
    roles = spec_roles(spec)
    if not any(PER_OPPONENT_ROLE in role for role in roles):
        return spec
    kept = [
        role for role in roles
        if PER_OPPONENT_ROLE not in role
        or per_opponent_seat(game, caster_index, int(role[PER_OPPONENT_ROLE]))
        is not None
    ]
    return {**spec, "roles": kept}


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


#: The flag a role carries when CR 601.2c lets the announcement leave it
#: unanswered: "…it fights **up to one** target creature you don't control"
#: (Primal Might's second slot, ``target_descriptions._slot_roles_spec``) — and
#: every role of "**any number of** target opponents" (Wheel and Deal,
#: :func:`any_number_of_opponents_roles`), a chain of trailing optional roles
#: from the first. Read through :func:`roles_may_end_at` /
#: :func:`role_announcement` by the walk and the gates
#: (``engine/legality_roles.py``, the cast and activation gates), and by the
#: AI's role choosers and the browser's role picker, which offer to stop there.
OPTIONAL_ROLE = "optional_role"


def roles_may_end_at(roles, count: int) -> bool:
    """Whether an announcement answering only the first *count* of *roles* is
    complete — every role after them optional (:data:`OPTIONAL_ROLE`). True for
    ``count == len(roles)`` by definition, and the only answer for a roles list
    with no optional role in it."""
    return all(
        isinstance(role, dict) and role.get(OPTIONAL_ROLE)
        for role in list(roles)[count:]
    )


def role_announcement(roles, chosen) -> "list | None":
    """*chosen* as the announcement it is — one object per answered role, in
    role order — or None where it is not one.

    **An optional role may be left unanswered**, and the wire has two ways to
    say so: a shorter list, or a ``None`` in the slot (a ``target_role_refs``
    entry naming nothing, an id list with a hole). Both come out here as the
    shorter list, so every reader counts one shape. A hole anywhere else, a
    list longer than the roles, or a mandatory role left unanswered is no
    announcement at all (CR 601.2c: every owed target is chosen).
    """
    roles = list(roles)
    named = list(chosen)
    if len(named) > len(roles):
        return None
    while (
        named and named[-1] is None
        and isinstance(roles[len(named) - 1], dict)
        and roles[len(named) - 1].get(OPTIONAL_ROLE)
    ):
        named.pop()
    if any(obj is None for obj in named) or not roles_may_end_at(roles, len(named)):
        return None
    return named


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
