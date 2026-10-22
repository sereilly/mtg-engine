"""Several targets of different kinds in one announcement (CR 601.2c).

"Target creature you control and target creature an opponent controls" is a
**roles** announcement: each role has its own description, and a later role
may be narrowed by what an earlier one named (``targeting.ROLE_RELATION_TESTS``).
This is the one place that answers it, at both ends of the object's life:

* **announcing** — :meth:`RoleTargetsMixin.role_target_options` is every legal
  target for the next role given the roles already chosen, and it is both the
  picker and the gate: the cast spec and the activation spec walk it to build
  the tree the browser is handed (:meth:`RoleTargetsMixin._role_target_walk`),
  and the activation gate asks the same list whether a named announcement is
  one of the walks (:meth:`RoleTargetsMixin._role_targets_legal`);
* **resolving** — CR 608.2b for a roles announcement one of whose roles is a
  player, or that named more than one seat
  (:meth:`RoleTargetsMixin._role_target_legality`,
  :meth:`RoleTargetsMixin._role_seat_target_legality`), asked by
  ``engine/legality_resolution.py``.

One module rather than a half in each of those, because a role's legality is
one question asked twice: the list that offered the target is the list that
judges it.
"""

from __future__ import annotations

from .models import CardDefinition, Permanent, PlayerState
from .targeting import role_is_stack, spec_roles
from .target_roles import role_relation_holds


def _role_object_key(obj) -> tuple:
    """*obj*'s identity for CR 115.3, whichever zone it is in.

    A roles announcement chooses one object per role and the same object may
    not answer two of them, so the walk carries a set of what is already taken.
    That set was ``{id(perm)}``, which is exactly right for a battlefield
    permanent and has no answer at all for a card in a graveyard: two copies of
    one card there are literally one ``CardDefinition`` object (the loader
    dedupes by ``oracle_id``), so ``id`` cannot tell them apart and ``is``
    would refuse the second copy for being the first.

    :class:`GraveyardTarget` is what can — it carries the pile and *which copy*
    — so its three fields are the key. Spread rather than used whole because
    the stamp holds a ``CardDefinition``, which has dict-valued fields and is
    therefore unhashable; ``id`` answers for the card because the loader shares
    one object per printing, which is the very fact that made ``id`` useless
    for the *copies*. The tag in front keeps the two kinds from ever colliding,
    which they could not anyway but which a reader should not have to prove.
    """
    if isinstance(obj, Permanent):
        return ("permanent", id(obj))
    # A **player** role's object is a seat (Donate's "target player"). ``id``
    # answers it for the battlefield arm's reason and not the graveyard arm's:
    # a game holds exactly one live ``PlayerState`` per seat, so identity is
    # what a seat *is*, where two graveyard copies of one card are one object
    # and needed a key built by hand.
    if isinstance(obj, PlayerState):
        return ("player", id(obj))
    # A **stack** role's object is a spell or ability there (Suffocating
    # Blast's "target spell"). Identity again, and it has to be: ``StackItem``
    # compares by value, and two casts of one card at one target are equal.
    from .game_types import StackItem

    if isinstance(obj, StackItem):
        return ("stack", id(obj))
    return ("graveyard", obj.seat, id(obj.card), obj.ordinal)


class RoleTargetsMixin:
    """Several targets of different kinds (CR 601.2c), announced and
    re-checked. Composed onto ``Game`` beside ``LegalityMixin``."""

    # -- Several targets of different kinds (CR 601.2c) ---------------------
    def named_role_objects(
        self, target_permanent_ids, target_role_refs, *,
        roles=(), target_stack_item=None,
    ) -> list:
        """The objects an activator named for a roles announcement, in role order.

        **A stack role is filled from the stack channel** (*target_stack_item*,
        which an activation has carried since Deathgrip), for the reason a
        cast's player role is filled from ``target_player_index``
        (``cast_target_validation._named_role_targets``): the announcement already has a field
        meaning exactly that, and a second arity beside it is a second answer
        to one question. Which slot is the stack one comes from *roles*, so an
        id list positional in role order carries ``None`` there, and a role ref
        marks the slot ``{"stack": True}``.

        **Two spellings of one announcement, and only one of them can say
        "graveyard".** ``target_permanent_ids`` is what every roles ability
        before Goblin Welder sends and is a permanent id per slot; a slot whose
        object is a card in a graveyard has no id to send — two copies of one
        card there are literally one ``CardDefinition`` — so it arrives as its
        pile and its slot instead.

        Rather than let the two lists interleave by position (which would make
        "which list does slot 1 come from?" a question with no answer on the
        wire), ``target_role_refs`` describes **every** role when it is present
        at all: one entry per slot, naming a permanent id or a graveyard
        address. The older list is what a caller sends when no slot needs the
        wider shape, which is every roles ability the pool had before this one.

        An entry that names nothing resolves to ``None``, which
        :meth:`_role_targets_legal` already refuses — an announcement with a
        hole in it is not one.
        """
        stack_slots = {
            index for index, role in enumerate(roles) if role_is_stack(role)
        }
        if target_role_refs:
            named = []
            for ref in target_role_refs:
                ref = ref if isinstance(ref, dict) else {}
                permanent_id = ref.get("permanent_id")
                if isinstance(permanent_id, int):
                    named.append(self.permanent_by_id(permanent_id))
                    continue
                if ref.get("stack"):
                    named.append(target_stack_item)
                    continue
                # …or a **seat**, for a role whose object is a player (Donate).
                # A third shape rather than a third list, for the reason the
                # graveyard address is one entry here rather than a second
                # positional list: which list a slot comes from is a question
                # a wire must never be left to answer.
                seat = ref.get("seat")
                if isinstance(seat, int):
                    named.append(
                        self.players[seat]
                        if 0 <= seat < len(self.players) else None
                    )
                    continue
                named.append(
                    self.graveyard_target_at(
                        ref.get("graveyard_seat"), ref.get("graveyard_index")
                    )
                )
            return named
        if stack_slots:
            # Positional, holes kept: with a slot that is not a permanent the
            # list cannot be compacted without losing which id is whose.
            return [
                target_stack_item if index in stack_slots
                else (self.permanent_by_id(pid) if isinstance(pid, int) else None)
                for index, pid in enumerate(target_permanent_ids or [])
            ]
        return [
            self.permanent_by_id(pid)
            for pid in (target_permanent_ids or [])
            if isinstance(pid, int)
        ]

    def role_object_at(self, candidate: dict):
        """The object a role candidate names — a permanent, or a card in a
        graveyard — or None when the slot no longer holds one.

        **A role is not always a battlefield permanent**, and this is the one
        place that stops being an assumption. "Choose target artifact a player
        controls **and target artifact card in that player's graveyard**"
        (Goblin Welder) walks the same roles the picker walks for Fumarole, and
        every step of the walk used to resolve its candidate through
        ``permanent_at`` alone — so a graveyard candidate came back ``None`` and
        was dropped, which is a slot the activator could never fill.

        The kind is the candidate's own, written by the enumerator that
        produced it (``_enumerate_targets``), so the walk does not have to know
        which spec kinds read which zone.
        """
        if candidate.get("kind") == "graveyard":
            return self.graveyard_target_at(
                candidate.get("seat"), candidate.get("index")
            )
        # …and a role is not always an *object* at all. "**Target player** gains
        # control of target permanent you control" (Donate) announces a seat in
        # slot 0, which the seat loop in ``_enumerate_targets`` already emits as
        # ``{"kind": "player", "seat": n}`` for every player-kind spec — so what
        # the walk needs is not a new enumeration but a way to resolve the
        # candidate that enumeration has been producing all along.
        if candidate.get("kind") == "player":
            seat = candidate.get("seat")
            if not isinstance(seat, int) or not (0 <= seat < len(self.players)):
                return None
            return self.players[seat]
        # …nor always in a zone a board or a pile is. "Counter **target spell**
        # and … deals 3 damage to target creature" (Suffocating Blast) announces
        # an object on the stack in slot 0, which ``_enumerate_stack_targets``
        # already emits for every stack spec — top-first, the convention the
        # client and the wire use, so it is turned back into the engine's
        # bottom-first list here and nowhere else in the walk.
        if candidate.get("kind") == "stack":
            index = candidate.get("stack_index")
            depth = len(self.stack)
            if not isinstance(index, int) or not (0 <= depth - 1 - index < depth):
                return None
            return self.stack[depth - 1 - index]
        return self.permanent_at(candidate.get("seat"), candidate.get("index"))

    def role_target_options(
        self, caster_index: int, card: CardDefinition, spec: dict,
        chosen: tuple, *, for_cast: bool, source_permanent=None,
        ability_instruction=None, ability_source=None,
    ) -> list[dict]:
        """Every legal target for the **next** role, given the roles already
        chosen - and the whole of what makes a roles spell safe.

        One call, and it is both the gate and the picker: ``cast_target_spec``
        walks it to build the list the browser offers, and
        :meth:`_validate_cast_targets` walks the same call over the targets a
        caster actually named. That is the shape ``trigger_mode_options``
        already has, and it is here for the reason CLAUDE.md keeps naming - a
        picker and a gate with two tables between them is this engine's
        recurring defect, and on a *target* list the failure is a spell cast at
        something nothing ever checked.

        Two narrowings live here and nowhere else, because neither is a
        property of one permanent:

        * **the dependency.** "target creature that **target Wall** blocked
          this turn" - which creatures are legal at all is decided by the block
          record on the Wall already chosen. ``subject_matches`` answers about a
          candidate alone and could never see it.
        * **CR 601.2c distinctness.** The same object can't be chosen for two
          targets of one spell unless the spell says otherwise, so a permanent
          already taken by an earlier role is not offered to a later one.

        Returns [] once every role is chosen, which is what ends the walk.
        """
        roles = spec_roles(spec)
        if len(chosen) >= len(roles):
            return []
        role = roles[len(chosen)]
        # ``for_cast=False`` even for a spell, and that is not a loosening.
        # The cast-time probe inside ``_enumerate_targets`` re-enters
        # ``_validate_cast_targets`` with **one** slot, which for a roles spell
        # is an incomplete announcement — so it would refuse every candidate,
        # and the recursion would be asking the whole-announcement gate a
        # question about a single permanent. The narrower path applies
        # ``_can_be_targeted``: the identical CR 702.16b/702.11b/shroud check
        # the cast gate runs over the targets a caster names, plus Wall of
        # Shadows' "abilities that can target only Walls" question, which it can
        # answer here because the role *is* the spec.
        candidates = self._enumerate_targets(
            caster_index, card, role, for_cast=False,
            ability_instruction=ability_instruction,
            source_permanent=source_permanent, ability_source=ability_source,
        )
        taken = {_role_object_key(obj) for obj in chosen if obj is not None}
        related = self._role_relation_test(role, roles, chosen)
        options: list[dict] = []
        for candidate in candidates:
            obj = self.role_object_at(candidate)
            if obj is None or _role_object_key(obj) in taken:
                continue
            if related is not None and not related(obj):
                continue
            options.append({**candidate, "role": role.get("role")})
        return options

    def _role_relation_test(self, role: dict, roles: list[dict], chosen: tuple):
        """The predicate *role*'s dependency imposes, or None when it has none.

        The relation itself is ``engine/targeting.ROLE_RELATION_TESTS``, which
        the resolution's CR 608.2b re-check reads too — the picker, this gate
        and that re-check are three questions about one relation, and this repo
        keeps finding the bug where they were three tables.

        A dependency that table does not implement offers **nothing**, never
        everything: an unanswerable narrowing must refuse, the same direction
        ``defending_player_only`` takes in the enumerator
        (``engine/legality_enumeration.py``). A role whose
        earlier target has not been chosen — or has left the battlefield — is
        in that same position, which ``role_relation_holds`` answers the same
        way.
        """
        if role.get("relation") is None:
            return None
        earlier_index = next(
            (
                index for index, entry in enumerate(roles)
                if entry.get("role") == role.get("depends_on")
            ),
            None,
        )
        earlier = (
            chosen[earlier_index]
            if earlier_index is not None and earlier_index < len(chosen)
            else None
        )
        return lambda perm: role_relation_holds(role, earlier, perm, self)

    def _role_target_walk(
        self, caster_index: int, card: CardDefinition, spec: dict,
        chosen: tuple, *, for_cast: bool, source_permanent=None,
        ability_instruction=None, ability_source=None,
    ) -> list[dict]:
        """The whole choice tree of a roles spell **or ability**, depth-first.

        Each entry is one legal target for the current role with the entries
        legal *after* it under ``next`` - so the browser can walk the roles in
        one payload rather than asking the server again between clicks, and so
        a role 0 candidate that leaves role 1 with nothing to choose is visible
        as an empty ``next`` rather than as a dead end discovered mid-prompt.

        The three ability keywords are carried, not defaulted away: an
        *activated* ability's roles (Sorrow's Path's two blockers) are
        enumerated with the same source-permanent and instruction narrowing
        every one-target ability gets, and a walk that dropped them would offer
        a list the activation gate then refuses.
        """
        options = self.role_target_options(
            caster_index, card, spec, chosen, for_cast=for_cast,
            source_permanent=source_permanent,
            ability_instruction=ability_instruction,
            ability_source=ability_source,
        )
        walked: list[dict] = []
        for option in options:
            perm = self.role_object_at(option)
            following = self._role_target_walk(
                caster_index, card, spec, chosen + (perm,), for_cast=for_cast,
                source_permanent=source_permanent,
                ability_instruction=ability_instruction,
                ability_source=ability_source,
            )
            if not following and len(chosen) + 1 < len(spec_roles(spec)):
                # CR 601.2c: every target of the spell is chosen, so a first
                # choice that leaves a later role with no legal object is not a
                # legal first choice at all. Dropped here rather than offered
                # and refused after the click.
                continue
            walked.append({**option, "next": following})
        return walked

    def _role_targets_legal(
        self, caster_index: int, card: CardDefinition, spec: dict,
        chosen: list, *, for_cast: bool, source_permanent=None,
        ability_instruction=None, ability_source=None,
    ) -> bool:
        """Whether *chosen* - one permanent per role, in role order - is a legal
        announcement, asked through the very list the picker was built from."""
        roles = spec_roles(spec)
        if len(chosen) != len(roles) or any(perm is None for perm in chosen):
            return False
        for index in range(len(roles)):
            options = self.role_target_options(
                caster_index, card, spec, tuple(chosen[:index]), for_cast=for_cast,
                source_permanent=source_permanent,
                ability_instruction=ability_instruction,
                ability_source=ability_source,
            )
            wanted = _role_object_key(chosen[index])
            if not any(
                _role_object_key(self.role_object_at(option)) == wanted
                for option in options
                if self.role_object_at(option) is not None
            ):
                return False
        return True

    def _role_target_legality(self, item, spec, holder) -> "list[bool] | None":
        """CR 608.2b for a **several-role** announcement one of whose roles is
        a player — "**Target player** gains control of **target permanent** you
        control" (Donate), "…2 damage to **target creature** and 2 damage to
        **target player** or planeswalker" (Lunge, Shower of Sparks) — one
        answer per role that named something, or None where the announcement
        cannot be read.

        **Legal is the announcement's question, asked again**, as it is one
        method down for a lone player target: is what this role named still
        among what ``role_target_options`` would offer for it now, given the
        objects the earlier roles named. That is the list the picker walked
        and the cast gate checked, so a seat that gained shroud in response
        (Ivory Mask, CR 702.18a) or left the game (CR 800.4a), a permanent
        that left or stopped answering its role's noun phrase, and a relation
        between two roles that no longer holds are each illegal by the rule
        that would have refused naming them.

        This is the *whole-object* half of the rule ("if all its targets … are
        now illegal, the spell … doesn't resolve"). The per-target half — an
        illegal target is not affected while the rest of the spell still
        happens — is ``handlers/_common.resolve_role_player`` for the seat and
        ``resolve_role_permanent`` for the object, each answering None for a
        role that is no longer legal.

        None for a role naming a card in a graveyard (no spell in the pool
        prints one beside a player; Goblin Welder is an ability) and for an
        announcement that named nothing for any role — a bare headless cast,
        which is the standing convention rather than a target gone illegal.
        """
        from .stack_targets import announcement_targets

        roles = spec_roles(spec)
        named = {
            target.position: target
            for target in announcement_targets(self, item, spec, holder)
        }
        if not named:
            return None
        objects: list = []
        for position in range(len(roles)):
            target = named.get(position)
            if target is None:
                objects.append(None)
            elif target.kind == "player":
                objects.append(self.players[target.seat])
            elif target.kind == "permanent":
                permanent = self.permanent_by_id(target.permanent_id)
                objects.append(
                    permanent if permanent is not None
                    and self.is_on_battlefield(permanent) else None
                )
            else:
                return None
        legality: list[bool] = []
        for position in sorted(named):
            chosen = objects[position]
            if chosen is None:
                legality.append(False)
                continue
            options = self.role_target_options(
                item.caster_index, item.card, spec, tuple(objects[:position]),
                for_cast=True,
            )
            wanted = _role_object_key(chosen)
            legality.append(any(
                _role_object_key(self.role_object_at(option)) == wanted
                for option in options
            ))
        return legality

    def _role_seat_target_legality(
        self, item, spec, holder, *, addresses: "list | None" = None,
    ) -> "list[bool] | None":
        """CR 608.2b for the **player roles** of a roles announcement that
        named more than one seat — one verdict per named player, in role
        order — or None where the announcement recorded no per-role seats and
        the question stays declined.

        Legal is the announcement's question asked again, as it is everywhere
        in this rule: still among what the role's own enumeration would offer
        the caster now. The roles walk enumerates each slot through
        ``_enumerate_targets`` with the role as the spec
        (:meth:`role_target_options`), so the same call over the same role
        is the list the picker was built from — a player who gained shroud in
        response (CR 702.18a) or left the game (CR 800.4a) is missing from it
        for the reason they could not have been named.

        A slot already holding ``None`` names nobody and has no verdict:
        blanking is idempotent, and a re-asked resolution must not count a
        target that is not there.

        What is *not* re-asked is the walk's relation between slots (the
        printed "another"): two players named as different players cannot
        come to be one.
        """
        from .target_roles import recorded_role_seats, role_seat_positions

        recorded = recorded_role_seats(holder)
        if recorded is None:
            return None
        roles = spec_roles(spec)
        verdicts: list[bool] = []
        for position in role_seat_positions(roles):
            seat = recorded[position] if position < len(recorded) else None
            if seat is None:
                continue
            offered = {
                entry.get("seat")
                for entry in self._enumerate_targets(
                    item.caster_index, item.card, dict(roles[position]),
                    for_cast=False,
                )
                if entry.get("kind") == "player"
            }
            verdicts.append(seat in offered)
            if addresses is not None:
                addresses.append(("player", "role", position, None))
        return verdicts
