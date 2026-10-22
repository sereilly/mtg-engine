"""The control seam: who controls what (CR 613 layer 2), and which permanent is "that one".

This engine models control as **which battlefield list a permanent sits in**,
so "which permanents are on the battlefield", "which does this player
control" and "is this permanent still there" are all the control question,
and this module is the one place that reads zone membership to answer them
(``all_permanents``, ``permanents_with_controller``, ``controlled_by``,
``permanents_matching``, ``controller_index_of``, ``controls``,
``is_on_battlefield``). ``tests/engine/test_control_reads.py`` holds every
other module to it. A control change is a contribution with a timestamp
(``take_control``, ``end_control_changes_from``; ``engine/control.py``), and
``_sync_control`` projects the derived controller back onto the lists.

Beside the seam, the three things it is the reason for:

* **addressing one permanent** (CR 400.7) - by its stable id
  (``permanent_by_id``, ``permanent_id_of``, ``chosen_permanent``), by the
  slot the wire names (``permanent_at``, ``battlefield_index_of``), and the
  same question one zone over, a graveyard card (``graveyard_target_at`` and
  its siblings);
* **leaving the battlefield**, one transition
  (``remove_from_battlefield`` / ``remove_all_from_battlefield``), with an
  Aura's effects ending as it goes (``_remove_aura_effects``);
* **combat's slots kept honest across a removal**
  (``_renumber_combat_after_removal``) - the combat maps are keyed by
  battlefield index, so every removal and every control change renumbers
  them here.
"""

from __future__ import annotations

from ..aura_attachment import auras_attached_to, detach_aura
from ..control import (base_controller, change_control, control_changes,
                       end_control_change, last_controller,
                       set_last_controller, has_control_change,
                       set_base_controller)
from ..delayed_triggers import (end_source_tapped_delayed_triggers,
                                fire_delayed_triggers)
from ..events import Event, collect
from ..layer_bridge import computed_controller
from ..land_types import end_land_type_change, end_land_type_changes_tied_to
from ..linked_exile import LEAVES
from ..models import Permanent, PlayerState
from ..game_types import GraveyardTarget
from ..tokens import CREATED_WITH_PERMANENT_ID
from ..trigger_utils import make_trigger_event, matching_triggers
from ..turn_state import forget_controllers_upkeep
from ..oracle_types import single_chosen_id


class ControlSeamMixin:
    def _find_controlled_permanent(
        self,
        controller: PlayerState,
        permanent_name: str,
        permanent_index: int | None = None,
    ) -> tuple[int, Permanent] | None:
        # Positional, deliberately: the web layer addresses a permanent by its
        # *slot* on its controller's battlefield, so this returns the index into
        # that list and not just the permanent. It is the one question the
        # control seam cannot answer, because the seam has no slots.
        if permanent_index is not None:
            if permanent_index < 0 or permanent_index >= len(controller.battlefield):
                return None
            permanent = controller.battlefield[permanent_index]
            if permanent.card.name != permanent_name:
                return None
            return permanent_index, permanent

        for idx, permanent in enumerate(controller.battlefield):
            if permanent.card.name == permanent_name:
                return idx, permanent
        return None

    def _remove_aura_effects(self, aura: Permanent) -> None:
        """End the continuous effects an Aura applied (CR 611.3).

        The Aura's P/T contribution is *derived* while it is attached
        (aura_grants.aura_static_pt_grant via layer_bridge), so detaching it is the
        whole removal — there is no delta to subtract. What is still undone
        here are the metadata flags _apply_aura_effect stamps directly, plus
        the linked one-shots (control theft, animation, Animate Dead's
        sacrifice) that are not characteristics at all.
        """
        attached = aura.metadata.get("attached_to")
        if attached is None:
            return
        for key in aura.metadata.get("aura_granted_meta", []) or []:
            attached.metadata.pop(key, None)
        # A land-type change (Evil Presence, Phantasmal Terrain) is a layer-4
        # contribution keyed on this Aura, so ending it drops that one and
        # leaves anything else still making the land a type. Unconditional: an
        # Aura that recorded none has none to end.
        end_land_type_change(attached, source=aura)
        # Animate Artifact (and similar) replaced the permanent's card with an
        # animated artifact-creature version. Restore the original card so it stops
        # being a creature and the UI drops its power/toughness labels (CR 611.3).
        pre_animate_card = attached.metadata.pop("pre_animate_card", None)
        if pre_animate_card is not None:
            attached.card = pre_animate_card
        detach_aura(aura, attached)
        # Control effects (Control Magic, Steal Artifact) end when the Aura
        # leaves (CR 611.3 / 805.4a). Dropping the contribution is the whole
        # removal: whatever other layer-2 effect is still on the permanent
        # decides where it goes, and if none is, it returns to its base
        # controller.
        self.end_control_changes_from(aura)
        # Animate Dead: "When this Aura leaves the battlefield, that creature's
        # controller sacrifices it." Sacrificing isn't destroying, so
        # regeneration and other destruction replacements can't affect it
        # (CR 701.21a).
        if aura.metadata.get("sacrifice_attached_on_leave"):
            controller_index = self.controller_index_of(attached)
            if controller_index is not None:
                controller = self.players[controller_index]
                self.remove_from_battlefield(attached)
                self._permanent_to_graveyard(controller, attached)
                self.log.append(
                    f"{controller.name} sacrificed {attached.card.name} ({aura.card.name} left the battlefield)"
                )

    def _holding_seat(self, permanent: Permanent) -> int | None:
        """The seat whose battlefield list physically holds *permanent*, or None.

        The **zone** question, not the control one. Only the seam and the code
        that writes the zone may ask it; everything else wants
        :meth:`controller_index_of`, which applies layer 2 on top of this.

        Matches by identity, not ``in``: Permanent is a dataclass with value
        equality, so ``in`` would match a look-alike (an opponent's copy of the
        same card in the same state) after this object has left the battlefield.
        """
        return next(
            (
                i
                for i, p in enumerate(self.players)
                if any(perm is permanent for perm in p.battlefield)
            ),
            None,
        )

    def controller_index_of(self, permanent: Permanent) -> int | None:
        """Who controls *permanent* — CR 613 layer 2 — or None if it is on no
        battlefield (already left / phased out).

        Computed, not stored: the base controller (whoever put it onto the
        battlefield) with every recorded control-changing effect applied in
        timestamp order. ``_sync_control`` keeps the battlefield lists as the
        projection of this answer, so ``controlled_by`` and the web payload see
        the same thing without each applying the layer themselves.
        """
        seat = self._holding_seat(permanent)
        if seat is None:
            # CR 614.12: a permanent *about to enter* is judged "as it would
            # exist on the battlefield", and there it is controlled by the
            # seat it enters under. Answered only while the board's statics
            # are being asked what they will make of it
            # (``fold_board_statics_onto_entering``), so that "creatures
            # **you** control" has a seat to compare for the one permanent
            # the control seam cannot see yet.
            entering = getattr(self, "_entering_under", None)
            if entering is None or entering[0] is not permanent:
                return None
            seat = entering[1]
        if not has_control_change(permanent):
            return seat
        base = base_controller(permanent)
        return computed_controller(permanent, seat if base is None else base)

    def controller_or_last_known(self, permanent: Permanent) -> int | None:
        """Who controls *permanent*, or who last did if it has left (CR 608.2h).

        "If the effect requires information from a specific object … the effect
        uses the current information of that object if it's in the public zone
        it was expected to be in; if it's no longer in that zone … the effect
        uses the object's last known information." For a controller that is two
        reads: the control seam while the permanent is on a battlefield, and
        the seat the one removal transition stamped as it left. "That creature
        deals 4 damage to **its controller**" (Bomb Squad) asks it of a
        creature the same resolution has just destroyed — or that another
        Bomb Squad's trigger destroyed first.

        The seat it entered under is the last resort, for a permanent that left
        by a road older than the stamp; None only for an object that was never
        on a battlefield at all.
        """
        seat = self.controller_index_of(permanent)
        if seat is not None:
            return seat
        seat = last_controller(permanent)
        if seat is None:
            seat = base_controller(permanent)
        return seat if seat is not None and 0 <= seat < len(self.players) else None

    def owner_index_of(self, permanent: Permanent) -> int | None:
        """Index of the player who owns *permanent*'s card (CR 108.3), for
        routing it to the right graveyard/hand when it leaves the battlefield
        (CR 400.3).

        The base controller is the owner whenever the two differ, because every
        way a permanent enters play in this pool puts it under its owner's
        control. That used to be read off the *thief* (``stolen_owner_index``),
        which meant a second theft overwrote the first one's answer."""
        # Reanimation (Animate Dead on an opponent's creature card) records the
        # owner directly on the permanent.
        meta_owner = permanent.metadata.get("owner_player_index")
        if isinstance(meta_owner, int) and 0 <= meta_owner < len(self.players):
            return meta_owner
        base = base_controller(permanent)
        if base is not None and 0 <= base < len(self.players):
            return base
        return self.controller_index_of(permanent)

    def cant_gain_control(self, permanent: Permanent, seat) -> bool:
        """Whether *seat* is forbidden right now to gain control of *permanent*.

        Guardian Beast: "As long as this creature is untapped, noncreature
        artifacts you control ... **other players can't gain control of
        them**." CR 614.17 - a "can't" is not a replacement effect but follows
        the same rules, and the rule this one states is about the *gaining*,
        never about which sentence does the gaining.

        Which is why it lives on the seam rather than in one handler. Exactly
        one asked it - the artifact-only linked steal - so Gauntlets of Chaos
        and Juxtapose exchanged a protected artifact away and Magus of the
        Unseen borrowed one, all three with the Beast untapped and nothing
        failing. A list of the handlers that move control is the fire-site list
        this codebase keeps finding incomplete.

        "**Other** players": a permanent's own controller re-recording control
        of it is not a gain, so the seats are compared first.
        """
        holder = self.controller_index_of(permanent)
        if holder is None or holder == self.seat_index(seat):
            return False
        return self._untapped_artifact_protector_active(permanent)

    def take_control(
        self,
        permanent: Permanent,
        seat,
        *,
        source: Permanent,
        extra_meta: dict | None = None,
    ) -> bool:
        """Record *source*'s CR 613 layer-2 effect giving *seat* control of
        *permanent*, then project it onto the battlefield lists.

        Returns False (a no-op) if the target is on no battlefield.
        ``extra_meta`` tags the *source* with its own revert-condition marker
        (Old Man of the Sea's tapped-and-weaker), which is a condition to check
        and not a value to restore.
        """
        holding = self._holding_seat(permanent)
        if holding is None:
            return False
        # CR 614.17's prohibition, asked at the one place a steal records its
        # contribution rather than in each steal handler (see
        # :meth:`cant_gain_control`).
        if self.cant_gain_control(permanent, seat):
            return False
        # A board built by hand (a test, a debug menu) never recorded a base, so
        # the seat it is sitting on now is the base — captured before the
        # contribution, which is the whole point of keeping the two apart.
        if base_controller(permanent) is None:
            set_base_controller(permanent, holding)
        change_control(permanent, self.seat_index(seat), source=source)
        if extra_meta:
            source.metadata.update(extra_meta)
        self._sync_control()
        return True

    def end_control_changes_from(self, source: Permanent) -> None:
        """Drop every control effect *source* recorded, and re-project.

        The inverse of :meth:`take_control`, and deliberately not an *undo*:
        it removes one contribution and lets whatever is left decide. Control
        Magic ending while Aladdin still holds the artifact leaves Aladdin's
        effect applying; both ending returns the permanent to its base
        controller. The old remember-the-previous-controller version could
        express neither, and handed the permanent to whoever the thief happened
        to have recorded — a player that by then controlled nothing giving it.
        """
        dropped = [
            (seat, permanent)
            for seat, permanent in list(self.permanents_with_controller())
            if end_control_change(permanent, source=source)
        ]
        self._sync_control()
        for seat, permanent in dropped:
            now = self.controller_index_of(permanent)
            if now is not None and now != seat:
                self.log.append(
                    f"{permanent.card.name} returns to {self.players[now].name}'s control "
                    f"({source.card.name} left the battlefield)"
                )

    def permanents_controlled_via(self, source: Permanent) -> list[Permanent]:
        """Every permanent *source* currently has a control effect on."""
        return [
            permanent
            for permanent in self.all_permanents()
            if any(entry["source"] is source for entry in control_changes(permanent))
        ]

    def _sync_control(self) -> None:
        """Move every permanent whose battlefield list disagrees with layer 2.

        The battlefield lists are a *projection* of the derived controller, not
        the storage for it. Keeping them in step here is what lets the 164
        migrated readers — and the whole web payload, which addresses a
        permanent by its slot on a controller's battlefield — keep asking the
        seam without any of them applying the layer themselves.

        It is also the single place CR 302.6 is stamped: a permanent changes
        hands exactly when this moves it, so "summoning sick since it came
        under your control" cannot be applied by one control path and forgotten
        by another.
        """
        for holding, permanent in list(self.permanents_with_controller()):
            base = base_controller(permanent)
            if base is None or not (0 <= base < len(self.players)):
                # Nothing has ever taken control of it and it never recorded a
                # base: it is where it belongs, whatever list that is.
                if not has_control_change(permanent):
                    continue
                base = holding
                set_base_controller(permanent, holding)
            derived = computed_controller(permanent, base)
            if derived == holding or not (0 <= derived < len(self.players)):
                continue
            # NOT a removal, and deliberately not routed through
            # `remove_from_battlefield`: this is a *move* between two
            # battlefields, the projection of a derived controller change (CR
            # 613 layer 2). The permanent does not leave the battlefield, so
            # anything hung off the leave transition — dies triggers, Aura
            # cleanup, the combat remap this choke point exists to host — must
            # not fire here. The pair of statements is one operation and is
            # written open so that is visible.
            # CR 506.4: **a permanent is removed from combat … if its
            # controller changes.** One of the clauses of the numbered rule
            # itself, not 506.4c (which is about attacking a planeswalker, and
            # is the number several comments in this engine cite for a plain
            # removal). A different rule from the leave-the-battlefield one the
            # comment above declines, and it fires exactly here — this is the
            # one place a control change becomes a change of hands.
            #
            # Both halves are needed and each is wrong without the other. The
            # index-keyed maps are pruned through the same renumbering the
            # removal transition uses (an attacker's slot is the active player's
            # and a blocker's is its own defender's, which is what that function
            # already knows), and the per-permanent state is cleared so a filter
            # asking "attacking" agrees with the maps. Left as it was, an
            # attacker stolen mid-combat stayed stamped `attacking` under its
            # new controller while its old slot named whichever creature slid
            # into it.
            if permanent.attacking or self._is_blocking_creature(permanent):
                slot = next(
                    (
                        i for i, other
                        in enumerate(self.players[holding].battlefield)
                        if other is permanent
                    ),
                    None,
                )
                permanent.attacking = False
                permanent.defending_player_index = None
                permanent.blocked = False
                permanent.blocking_attacker_controller = None
                permanent.blocking_attacker_index = None
                self.log.append(
                    f"{permanent.card.name} left combat (it changed controllers)"
                )
                if slot is not None:
                    self._renumber_combat_after_removal({holding: [slot]})
            # "When you lose control of this artifact, …" (Gustha's Scepter).
            # This is the *other* half of CR 603.10d's event and the only place
            # in the engine a permanent changes hands, exactly as the CR 506.4
            # combat removal above is: the seat that loses it is the one it is
            # being taken from, and it is frozen here rather than read at
            # resolution because by then the permanent is somebody else's.
            #
            # The zone-change half fires from the leave transition below;
            # neither can see the other's event, which is why both exist.
            from ..trigger_utils import make_trigger_event, matching_triggers

            for trig in matching_triggers(
                permanent.effective_card,
                condition_kinds={"lose_control_of_source"},
            ):
                self._enqueue_triggered_batch(
                    [make_trigger_event(holding, permanent, trig)]
                )
            # …and the delayed half of the same event (Coffin Queen's "or you
            # lose control of this creature"). A delayed ability belongs to no
            # permanent, so the `matching_triggers` scan above cannot reach it
            # — the entry is on the game's own waiting list — and this is the
            # one place in the engine a permanent changes hands, so an
            # announcement wired into any single control-changing effect would
            # be one every other effect forgot.
            #
            # Fired **before** the permanent is moved between battlefields
            # below, for the scan above's reason: the ability is about the seat
            # losing it, and by the next line the permanent is somebody else's.
            fire_delayed_triggers(
                self, "bound_permanent_untaps_or_control_lost",
                subject=permanent,
            )
            self.players[holding].battlefield = [
                p for p in self.players[holding].battlefield if p is not permanent
            ]
            self.players[derived].battlefield.append(permanent)
            # CR 302.6: a creature is summoning-sick since it came under its
            # controller's control, not since it entered the battlefield — a
            # permanent that changes hands can't attack or use {T} abilities
            # this turn, in either direction.
            if self._is_creature(permanent):
                permanent.metadata["summoning_sickness_turn"] = self.turn
            # CR 702.30a: echo's window starts again when a permanent comes
            # under a new controller's control, so the record of which of its
            # controller's upkeeps it has seen is about the seat that has just
            # lost it and is dropped here (``engine/turn_state.py``).
            #
            # Here because this is the one place in the engine a permanent
            # changes hands, and a forget wired into any single
            # control-changing effect would be one every other effect forgot.
            # Unconditional on type, unlike CR 302.6's marker above it — echo is
            # a keyword of *permanents*, and an artifact that changes hands owes
            # a fresh one exactly as a creature does.
            forget_controllers_upkeep(permanent)

    # ------------------------------------------------------------------
    # The control seam (CR 613 layer 2)
    #
    # "Which permanents are on the battlefield", "which does this player
    # control" and "is this permanent still there" are asked all over the
    # engine, and each of them used to be answered by opening
    # ``player.battlefield`` by hand. That is not a zone question with an
    # incidental control answer — it *is* the control question, because this
    # engine models control as which battlefield list a permanent sits in.
    #
    # Everything below is the one place that reads zone membership. Wiring
    # layer 2 means changing these four methods and nothing else; a reader that
    # goes around them is a second opinion about who controls what, which is the
    # bug class ``tests/engine/test_control_reads.py`` guards.
    #
    # Each iterator snapshots the list it walks, so a caller may destroy or
    # steal permanents while iterating without skipping the next one.
    # ------------------------------------------------------------------

    def all_permanents(self) -> "Iterator[Permanent]":
        """Every permanent on the battlefield, in seat order."""
        for player in self.players:
            yield from list(player.battlefield)

    def permanents_with_controller(self) -> "Iterator[tuple[int, Permanent]]":
        """Every permanent paired with its controller's seat index."""
        for index, player in enumerate(self.players):
            for permanent in list(player.battlefield):
                yield index, permanent

    def seat_index(self, seat) -> int:
        """*seat* as a seat index, whether it arrived as one or as a
        :class:`PlayerState`. By identity: ``self.players.index(player)`` is an
        equality search over a mutable dataclass, so two seats that happen to
        hold equal state would resolve to the same index."""
        if isinstance(seat, int):
            return seat
        return next(i for i, player in enumerate(self.players) if player is seat)

    def apnap_seats(self, seats=None, *, include_lost: bool = False) -> list[int]:
        """The seats in **APNAP order** (CR 101.4): the active player, then
        each other player in turn order.

        The order players make simultaneous choices in — and the order objects
        that would receive a timestamp simultaneously are stamped in:

            613.7m  If two or more objects would receive a timestamp
                    simultaneously, such as by entering a zone simultaneously
                    … their relative timestamps are determined in APNAP order.
                    Objects controlled by the active player … have an earlier
                    relative timestamp in the order of that player's choice,
                    followed by each other player in turn order.

        ``Permanent.timestamp`` is taken as a permanent enters
        (``_put_permanent_onto_battlefield``), so a handler that puts several
        players' cards onto the battlefield "at once" stamps them in the order
        its loop walks the seats. Walking this list is what makes that order
        the rule's. Two of the pool's six such handlers walked ``range(len(
        players))`` instead (Living Death, Game Preserve), which is APNAP only
        while seat 0 is the active player.

        *seats* narrows the answer to those seats, still in APNAP order. A
        seat that has left the game is left out unless *include_lost*
        (CR 800.4a: a player who has left has no battlefield to put a card
        onto). Within one seat the order is "that player's choice", which a
        caller walking a pile in its own order has defaulted, not asked.
        """
        count = len(self.players)
        start = self.active_player_index if self.active_player_index is not None else 0
        wanted = None if seats is None else {int(seat) for seat in seats}
        return [
            seat
            for seat in ((start + offset) % count for offset in range(count))
            if (wanted is None or seat in wanted)
            and (include_lost or not self.players[seat].lost)
        ]

    def controlled_by(self, seat) -> "Iterator[Permanent]":
        """Every permanent *seat* controls. Takes a seat index or a
        :class:`PlayerState`, because both spellings are already in use and the
        question is the same one either way."""
        player = self.players[seat] if isinstance(seat, int) else seat
        return iter(list(player.battlefield))

    def controls(self, seat, permanent: Permanent) -> bool:
        """Whether *seat* controls *permanent*, by identity — the replacement
        for ``permanent in player.battlefield``, which compares by value."""
        return self.controller_index_of(permanent) == self.seat_index(seat)

    def permanents_matching(self, predicate) -> "Iterator[Permanent]":
        """Every permanent satisfying *predicate*, across all battlefields."""
        return (perm for perm in self.all_permanents() if predicate(perm))

    def is_on_battlefield(self, permanent: Permanent) -> bool:
        """Whether *permanent* is on the battlefield, **by identity**.

        ``permanent in player.battlefield`` is the shape this replaces, and it
        was wrong: :class:`Permanent` is a dataclass with value equality, so
        ``in`` answers yes for a look-alike — an opponent's untouched copy of
        the same card — after this object has left. That made an Aura whose
        enchanted creature had died survive CR 704.5m as long as some other
        player had an identical creature in an identical state."""
        return any(perm is permanent for perm in self.all_permanents())

    # ------------------------------------------------------------------
    # Addressing one permanent (CR 400.7)
    #
    # The seam above answers "which permanents"; this answers "*that* one".
    # Both questions used to be answered by opening ``player.battlefield``, and
    # the second one was answered *positionally* — ``player.battlefield[i]`` —
    # which is unstable by construction: anything leaving the battlefield
    # renumbers every later slot, so an index held across a resolution step
    # addresses a different permanent than the one it was taken for.
    #
    # ``Permanent.permanent_id`` is the stable answer, and these are the only
    # places that turn one into a permanent. Scattering the lookup would put
    # the same bounds-checking and the same "it may be gone by now" decision in
    # every caller, which is how the positional reads spread in the first place.
    # ------------------------------------------------------------------

    def permanent_by_id(self, permanent_id) -> "Permanent | None":
        """The battlefield permanent with this id, or None if it has left.

        None is the answer a caller wants: a permanent that is gone is *gone*,
        where ``battlefield[i]`` would hand back whichever permanent slid into
        that slot. Callers should treat None as "the target is no longer there"
        (CR 608.2b), not as an error."""
        found = self.find_permanent_by_id(permanent_id)
        return None if found is None else found[1]

    def find_permanent_by_id(self, permanent_id) -> "tuple[int, Permanent] | None":
        """``(controller seat, permanent)`` for this id, or None if it has left.

        The paired form, for the callers that need the seat as well — the seat
        is *derived* here rather than remembered by the caller, so a permanent
        that changed control since the id was taken resolves to whoever
        controls it now (CR 613 layer 2)."""
        if permanent_id is None:
            return None
        try:
            wanted = int(permanent_id)
        except (TypeError, ValueError):
            return None
        for seat, permanent in self.permanents_with_controller():
            if permanent.permanent_id == wanted:
                return seat, permanent
        return None

    def permanent_id_of(self, permanent: Permanent) -> int | None:
        """*permanent*'s stable id while it is on the battlefield, else None.

        None for a permanent that has left, so an id taken from here is always
        one ``permanent_by_id`` can still resolve — by identity, because a
        look-alike's id is a different number and asking by value would find
        it."""
        if permanent is None or not self.is_on_battlefield(permanent):
            return None
        return permanent.permanent_id

    def battlefield_index_of(self, permanent: Permanent) -> int | None:
        """*permanent*'s slot on its controller's battlefield, or None.

        **The bridge, not the destination.** The wire protocol still addresses
        a permanent by index, so the payload has to carry one until the client
        has finished migrating; this is where that index is derived, by
        identity, instead of each serializer running its own ``enumerate``."""
        seat = self.controller_index_of(permanent)
        if seat is None:
            return None
        for index, candidate in enumerate(self.controlled_by(seat)):
            if candidate is permanent:
                return index
        return None

    def permanent_at(self, seat, index) -> "Permanent | None":
        """The permanent in *seat*'s battlefield slot *index*, or None.

        The other half of the bridge: an index arriving from the wire has to be
        turned into a permanent exactly once, at the boundary, and then carried
        as an id. Bounds-checked, because every open-coded
        ``0 <= i < len(battlefield)`` guard is one that can be forgotten."""
        if index is None:
            return None
        try:
            wanted = int(index)
        except (TypeError, ValueError):
            return None
        if wanted < 0:
            return None
        battlefield = list(self.controlled_by(self.seat_index(seat)))
        if wanted >= len(battlefield):
            return None
        return battlefield[wanted]

    def chosen_permanent(self, seat, index, permanent_id) -> "Permanent | None":
        """The permanent a cast-time choice named, preferring its stable id.

        The read half of what ``_stack_push`` writes. A spell records both when
        its target is chosen (CR 601.2c) and resolution asks for both here, so
        the id answers whenever it still can and the index answers exactly as it
        always did when it cannot.

        **Additive on purpose.** Falling through to the index rather than
        failing means this can only turn a wrong answer into a right one: a
        target that has left the battlefield behaves as before (whatever slid
        into its slot, or nothing), rather than acquiring a fizzle the callers
        are not yet written for. Tightening that into a CR 608.2b refusal is a
        behaviour change and belongs in a change that says so.

        Scoped to *seat* like the index it replaces, so a permanent that changed
        controller is not silently still targeted from its old side.

        **And it reads the channel's two arities**, which is why the id was
        being ignored on the path that needs it most. ``StackItem`` carries one
        field, and its producers disagree: ``activation`` and ``casting`` stamp
        the whole ``target_permanent_ids`` *list*, a prompt's answer stamps a
        bare id. Asking ``isinstance(permanent_id, int)`` alone meant a caller
        that named its target the only stable way there is — CR 400.7's id, the
        address CLAUDE.md says to prefer — had the name silently dropped and got
        the index it did not send. ``deal_damage`` is where that showed: an
        ``any_target`` activation addressed by id alone fell past the permanent
        branch entirely and burned the *player*. The web layer fills an index in
        ``web/actions.py`` and masked it; the AI, a headless driver and a test
        do not.

        A **one**-element sequence is one address and resolves. A longer one is
        several, and a single-target read has no business picking from it — that
        falls through to the index exactly as before, rather than guessing slot
        zero, which is the multi-target list read as a single target and wrong
        in the direction that looks right. Still additive on purpose: this can
        only turn a dropped id into a used one.

        The wider question — one field carrying two arities across 119 reader
        sites — is `SET_PLAYBOOK.md`'s Known gaps, and settling it is a
        pool-wide refactor rather than a fix. This is the seam every caller
        already goes through, so it is the one place the disagreement can be
        absorbed without becoming a twelfth local normalisation.
        """
        named = single_chosen_id(permanent_id)
        if named is not None:
            found = self.permanent_by_id(named)
            if found is not None and self.controls(seat, found):
                return found
        return self.permanent_at(seat, index)

    # -- The same question one zone over -----------------------------------
    #
    # A graveyard slot is as unstable as a battlefield slot and has no id to
    # fall back on, so the four functions below are `permanent_id_of` /
    # `permanent_by_id` / `chosen_permanent` rewritten for a zone whose objects
    # cannot be told apart by identity at all.

    def graveyard_target_at(self, seat, index):
        """Name the card in *seat*'s graveyard slot *index*, or None.

        The write half. ``ordinal`` counts how many *earlier* slots hold the
        same ``CardDefinition`` object, which is the only thing that separates
        two copies of one card once the dedupe has made them one object.
        """
        if seat is None or not 0 <= seat < len(self.players):
            return None
        graveyard = self.players[seat].graveyard
        if not isinstance(index, int) or not 0 <= index < len(graveyard):
            return None
        card = graveyard[index]
        ordinal = sum(1 for other in graveyard[:index] if other is card)
        return GraveyardTarget(seat=seat, card=card, ordinal=ordinal)

    def graveyard_index_of(self, target) -> int | None:
        """Where *target* sits in its graveyard **now**, or None when no copy of
        that card is there any more.

        The read half. Clamps to the last surviving copy rather than failing
        when fewer copies remain than the ordinal asked for: with two copies of
        one card the engine cannot know *which* one left, because they are the
        same object, so the choice is between two indistinguishable answers and
        the one that keeps the two copies behaving alike is the honest one.
        "Gone" is reserved for the case the data model can actually establish —
        no copy of that card left in that graveyard.
        """
        if target is None or not 0 <= target.seat < len(self.players):
            return None
        graveyard = self.players[target.seat].graveyard
        positions = [i for i, card in enumerate(graveyard) if card is target.card]
        if not positions:
            return None
        return positions[min(target.ordinal, len(positions) - 1)]

    def chosen_graveyard_index(self, target, index):
        """The graveyard slot a cast-time choice named, re-located now.

        Mirrors the shape it is given — one slot, a list of them, or None —
        and gives each stamp one of three answers:

        * a stamp with a surviving copy re-locates to it, clamping to the last
          one where fewer remain than the ordinal asked for —
          ``graveyard_index_of``'s deliberately ambiguous case;
        * a stamp with **no** surviving copy answers None, because the chosen
          card is gone and the slot it sat in now names a different card. This
          used to fall through to the stale index on the claim that falling
          through "can only turn a wrong answer into a right one" — false for
          exactly this path: exile the Serra Angel a Resurrection targeted and
          the stale index reanimated the Grizzly Bears beneath it. CR 608.2b
          owns the gone target instead: a spell whose every stamp answers None
          is removed from the stack by ``illegal_targets_refusal`` before any
          handler runs, and a handler handed None for one slot of several
          leaves that slot's vanished card unaffected (the rule's last
          sentence) while the surviving targets still resolve;
        * no stamp at all keeps the caller's index — nothing was recorded, so
          there is no choice to have gone stale (an untargeted cast still
          resolves its own pick, exactly as before).
        """
        if isinstance(target, list):
            slots = index if isinstance(index, list) else []
            return [
                self.chosen_graveyard_index(stamp, slots[i] if i < len(slots) else None)
                for i, stamp in enumerate(target)
            ]
        if target is None:
            return index
        # A stamp is a **target** somebody announced, so it is re-located only
        # while it is still a legal one — gone from its pile, or under "Cards
        # in graveyards can't be the targets of spells or abilities" (Ground
        # Seal arriving in response), it answers None and CR 608.2b's last
        # sentence leaves that slot's card unaffected.
        if not self.graveyard_target_is_legal(target):
            return None
        return self.graveyard_index_of(target)

    def graveyard_target_is_legal(self, target) -> bool:
        """Whether the graveyard card *target* names is still a legal target
        (CR 608.2b).

        Two ways it stops being one: no copy of the card is left in that
        graveyard (``graveyard_index_of``'s "gone"), or the board now says no
        card in a graveyard may be targeted at all
        (``target_immunity.graveyard_cards_untargetable``, Ground Seal). The
        second is CR 608.2b's "other changes to the game state", and it is why
        this is a method rather than the bare ``graveyard_index_of(...) is not
        None`` the three resolution gates used to spell: the card being
        *there* and the card being *targetable* are different questions, and
        only the first is about where it sits.
        """
        if self.graveyard_index_of(target) is None:
            return False
        from ..target_immunity import graveyard_cards_untargetable

        return graveyard_cards_untargetable(self) is None

    def stamp_graveyard_targets(self, seat, index):
        """Every chosen graveyard slot, named. Mirrors the index's own shape."""
        if isinstance(index, list):
            return [self.graveyard_target_at(seat, slot) for slot in index]
        return self.graveyard_target_at(seat, index)

    def graveyard_target_seat(self, item, spec: dict) -> int:
        """Whose graveyard a stack item's chosen index counts into.

        The same defaulting the resolution side does, in one place so the stamp
        and the reader cannot disagree: a spec that says ``own_graveyard_only``
        is always the caster's own zone (that flag is read off the *handler*,
        not off the printed words), and everything else follows the target
        player the item recorded, behind ``_stack_push``'s standing convention.
        """
        if spec.get("own_graveyard_only"):
            return item.caster_index
        seat = item.target_player_index
        # "from **an opponent's** graveyard" (Misinformation). The pile is not a
        # target, so an announcement can legitimately arrive with no seat named
        # — and the caster's own graveyard, the default below, is the one pile
        # the printed word rules out. In a duel there is exactly one opponent
        # and the words name it; with more, a seat has to be named, and naming
        # none reaches the default rather than guessing which opponent.
        if (
            seat is None
            and spec.get("opponent_graveyard_only")
            and len(self.players) == 2
        ):
            return 1 - item.caster_index
        if seat is None or not 0 <= seat < len(self.players):
            # **The caster's own**, not the opposing seat. The opposing default
            # is the *battlefield* convention — a spell naming a permanent and
            # no player usually means an opponent's — and it is backwards one
            # zone over, where the pile a spell reaches into is usually its own
            # caster's. It was a disagreement rather than a preference, too:
            # Animate Dead's cast validation checks the chosen index against the
            # caster's graveyard while `_apply_aura_effect` read it out of the
            # opponent's, so naming your own Grizzly Bears reanimated their
            # Shivan Dragon.
            seat = item.caster_index
        return seat

    def remove_from_battlefield(
        self, permanent: Permanent, *, zone_change: bool = True
    ) -> Permanent | None:
        """Take *permanent* off the battlefield. The one transition out.

        Returns the permanent when it was there, None when it was not — so a
        caller that needs the object (most of the old ``battlefield.pop(idx)``
        sites did) gets it without a second lookup, and a caller that does not
        can ignore it.

        **Where it goes next is the caller's business.** A permanent leaves for
        a graveyard, exile, its owner's hand or library, or into the phased-out
        limbo an effect is holding it in, and those destinations have nothing in
        common. This does the one part they share.

        The reason it is one function is the reason ``become_tapped`` is one
        function. The battlefield was rebuilt or shortened in **41 places**, in
        three different spellings (filter-by-identity, ``pop`` by index, rebuild
        from a survivors list), and anything that has to happen when a permanent
        leaves therefore had 41 places to be wired into and 41 places to be
        forgotten. The live example is the one that motivated this: every combat
        map is keyed by battlefield index, so a permanent leaving mid-combat
        renumbers every attacker and blocker recorded after it, and there was no
        single place to put the remap.

        By **identity**, never by value: ``Permanent.__eq__`` compares by value,
        so ``list.remove`` and ``in`` match an opponent's look-alike card. That
        bug class is why ``.battlefield.remove()`` is banned outright by
        ``tests/engine/test_control_reads.py``.

        ``zone_change=False`` is CR 702.26b's phase-out; see
        :meth:`remove_all_from_battlefield`.
        """
        removed = self.remove_all_from_battlefield(
            (permanent,), zone_change=zone_change
        )
        return removed[0] if removed else None

    def remove_all_from_battlefield(
        self, permanents, *, zone_change: bool = True
    ) -> list[Permanent]:
        """Take several permanents off the battlefield at once.

        The shape a sweep needs — destruction, a mass bounce, a player leaving
        the game — rebuilding each affected battlefield **once** rather than
        once per permanent. Returns those actually removed, in the order they
        sat on their battlefields, so a caller can log or process exactly what
        left.

        Not simply a loop over :meth:`remove_from_battlefield`, because a sweep
        that rebuilds per victim is quadratic and, worse, renumbers between
        victims — which is the failure the callers were open-coding around when
        they built a ``survivors`` list themselves.

        **``zone_change=False`` is phasing out, and only phasing out**
        (CR 702.26d: "the phasing event doesn't actually cause a permanent to
        change zones or control… zone-change triggers don't trigger when a
        permanent phases in or out"). The list mechanics and the combat
        renumbering are exactly the same — the permanent stops being on a
        battlefield either way, and every combat map keyed by its slot must
        follow — and every *consequence* of leaving is what CR 702.26d and
        702.26g say must not happen: no leaves-the-battlefield ability triggers,
        no delayed "until this leaves" ability fires, no linked exile comes
        back, and the Auras and Equipment attached to it **stay attached** so
        they can phase in with it.

        The one consequence that still happens is CR 702.26f's: a "for as long
        as" effect that tracks the permanent ends, because it can no longer see
        it.

        A flag on this transition rather than a second removal path, for the
        reason this function exists at all: a phase-out that rebuilt the
        battlefield itself would be the 42nd open-coded removal, and the combat
        renumbering is the thing it would forget. And a flag rather than a
        caller that undoes the consequences afterwards, because undoing an
        announced trigger is not possible — Nine Lives would already have lost
        the game.
        """
        targets = [perm for perm in permanents if perm is not None]
        if not targets:
            return []
        departing = {id(perm) for perm in targets}
        # Where each departing permanent sat, per seat, *before* the rebuild —
        # everything combat records is a slot on one of these lists, and once
        # the lists are rebuilt the old numbers are unrecoverable.
        vacated: dict[int, list[int]] = {}
        for seat, player in enumerate(self.players):
            gone = [i for i, perm in enumerate(player.battlefield) if id(perm) in departing]
            if gone:
                vacated[seat] = gone
        # "When this enchantment leaves the battlefield, you lose the game."
        # (Nine Lives.) CR 603.6c: a leaves-the-battlefield ability triggers
        # when a permanent moves from the battlefield to another zone, and
        # CR 603.10 makes what it sees the last-known information — so the seat
        # and the ability are read here, while the permanent is still on a
        # battlefield, and announced once the rebuild below is done.
        #
        # Announced from this one transition rather than from the zone-change
        # callers, for the reason the exile-return at the bottom of this
        # function gives: the other forty would forget it. It had no fire site
        # at all until round 140 — the condition parsed on both sides of the
        # pipeline and Nine Lives compiled a real `player_loses_game` under it —
        # and nothing reached the gap while the card's prevention was
        # unimplemented, because the enchantment never left the battlefield.
        from ..trigger_utils import make_trigger_event, matching_triggers

        # Paired with the permanent whose *leaving* announces it, which is not
        # always the event's source permanent: Dance of Many's second trigger
        # belongs to the enchantment and fires on the token's departure, so the
        # filter below has to ask about the token while the stack item names
        # the enchantment.
        leaving: list[tuple[Permanent, dict]] = []
        # Every permanent attached through the single ``attached_to`` slot, read
        # once for the whole sweep rather than once per departing permanent: a
        # mass removal is the common case and this is the one board-wide scan in
        # the function. (The Aura *list* is on the host, so it costs nothing.)
        attachments = [
            perm for perm in self.all_permanents()
            if perm.metadata.get("attached_to") is not None
        ] if zone_change else []
        # CR 702.26d: a phase-out triggers none of these, so none of them is
        # gathered. Written as an empty scan rather than a branch around the
        # loop, so the loop below stays the one reading of what leaving
        # announces.
        for perm in targets if zone_change else ():
            seat = self.controller_index_of(perm)
            if seat is None:
                continue
            # CR 608.2h's last known information, for the one fact about a
            # permanent that is not on the object: who controlled it. Stamped
            # here, at the one transition off the battlefield and while the
            # seam can still answer, so anything that reads this permanent
            # after it is gone can ask (`controller_or_last_known`).
            set_last_controller(perm, seat)
            # Both kinds from one scan, because a permanent leaving the
            # battlefield **is** its controller losing control of it: the
            # object ceases to exist and nobody controls the new one (CR
            # 400.7). CR 603.10a and 603.10d both make these look back in
            # time, so the ability is still there to trigger although the
            # permanent has gone — which is the whole of why Gustha's Scepter's
            # exiled cards reach a graveyard instead of being stranded in exile
            # when the artifact is destroyed. The *other* way to lose control
            # is a change of hands, and that fires from `_sync_control`.
            for trig in matching_triggers(
                perm.effective_card,
                condition_kinds={
                    "leaves_battlefield", "lose_control_of_source",
                    # The other half of Ertai's Familiar's joined event, named
                    # here for `creature_attacks_or_blocks`' reason: one
                    # ability, two events, so both sites read the one kind.
                    "phases_out_or_leaves_battlefield",
                },
            ):
                leaving.append((perm, make_trigger_event(seat, perm, trig)))
            # "Whenever **a nontoken creature** leaves the battlefield, exile
            # all tokens with the same name as that creature." (Dual Nature.)
            # The same CR 603.6c event watched by a permanent that is neither
            # the one leaving nor attached to it, so the *board* is asked — by
            # the event bus's own collector and its subject filter, rather than
            # a third hand-written scan beside the two around this one.
            #
            # Collected here, before the rebuild, for CR 603.10a: the ability
            # looks back in time, so the noun phrase is asked of the permanent
            # as it last existed on the battlefield, and a watcher leaving in
            # the same sweep still sees it go (one removal taking Dual Nature
            # and the creatures together triggers it for each creature). The id,
            # name and seat are frozen for the reason the entry seam freezes
            # them: by resolution the object is a card in another zone with no
            # controller (CR 400.7), and the sentence still means what it was.
            for announced in collect(self, Event(
                kind="matching_permanent_leaves_battlefield",
                payload={
                    "event_subject_permanent_id": perm.permanent_id,
                    "event_subject_name": perm.effective_card.name,
                    "event_subject_controller": seat,
                },
                subject=perm,
            )):
                leaving.append((perm, announced))
            # "When enchanted creature leaves the battlefield, its controller
            # sacrifices a creature of their choice." (Funeral March.) The same
            # CR 603.6c event watched by what the departing permanent is
            # *carrying* — the mirror of the `attached_creature_dies` scan in
            # `_fire_creature_dies_triggers`, one event wider: a host exiled,
            # bounced or tucked never dies, and this is the one transition all
            # four moves pass through.
            #
            # The seat is frozen here, not read at resolution (CR 603.10,
            # idiom 6): by the time the ability resolves the host is in another
            # zone with no controller to ask, and under a control-change effect
            # the seat that controlled it was never its owner. Both spellings of
            # "attached" are asked because both exist — the list an Aura joins
            # and the single slot an Equipment sets.
            attached_context = {"event_subject_controller": seat}
            observers: list[Permanent] = list(auras_attached_to(perm))
            for other in attachments:
                if other.metadata.get("attached_to") is perm and not any(
                    other is already for already in observers
                ):
                    observers.append(other)
            for observer in observers:
                observer_seat = self.controller_index_of(observer)
                if observer_seat is None:
                    continue
                for trig in matching_triggers(
                    observer.effective_card,
                    condition_kinds={"attached_creature_leaves_battlefield"},
                ):
                    leaving.append((
                        perm,
                        make_trigger_event(
                            observer_seat, observer, trig,
                            trigger_context=dict(attached_context),
                        ),
                    ))
            # "When **the token** leaves the battlefield, sacrifice this
            # enchantment." (Dance of Many.) The same CR 603.6c event about a
            # different object: the ability belongs to the permanent that
            # *made* this token, not to the token, so the scan above cannot
            # reach it — the token names its maker by id (CR 400.7 makes a
            # returning permanent a different one, and the id is what says so)
            # and the lookup is that one hop.
            #
            # Read here, before the rebuild, for the reason the scan above is:
            # by the time the batch is enqueued the maker may have left in the
            # same sweep, and its seat would be unaskable.
            creator = self.permanent_by_id(
                perm.metadata.get(CREATED_WITH_PERMANENT_ID)
            )
            creator_seat = (
                self.controller_index_of(creator) if creator is not None else None
            )
            if creator_seat is None:
                continue
            for trig in matching_triggers(
                creator.effective_card,
                condition_kinds={"created_token_leaves_battlefield"},
            ):
                # The **maker** is the source permanent: it is whose ability
                # this is, and "sacrifice this enchantment" would otherwise
                # sacrifice the token that just left.
                leaving.append(
                    (perm, make_trigger_event(creator_seat, creator, trig))
                )

        removed: list[Permanent] = []
        for player in self.players:
            if not any(id(perm) in departing for perm in player.battlefield):
                continue
            survivors = []
            for perm in player.battlefield:
                (removed if id(perm) in departing else survivors).append(perm)
            player.battlefield = survivors
        if removed:
            self._renumber_combat_after_removal(vacated)
        # Only for the permanents that were really there: `targets` is what the
        # caller asked about and `removed` is what left, and a trigger announced
        # for a permanent already off the battlefield would fire on nothing.
        departed = {id(perm) for perm in removed}
        self._enqueue_triggered_batch(
            [event for watched, event in leaving if id(watched) in departed]
        )
        if not zone_change:
            # CR 702.26d: "zone-change triggers don't trigger when a permanent
            # phases in or out", and CR 702.26g keeps the attachments attached.
            # So none of the leaving consequences below happens — except one,
            # which CR 702.26f says explicitly *does*: an effect with a "for as
            # long as" duration that tracks this permanent ends when it phases
            # out, "because they can no longer see it".
            for perm in removed:
                end_source_tapped_delayed_triggers(self, perm)
            return removed
        # "…until this creature leaves the battlefield" (Kitesail Freebooter).
        # Here because this is the one transition out: a return wired into any
        # single caller would be a return the other forty forgot, which is the
        # reason this function exists at all.
        # "Exile that token **when Stangg leaves the battlefield**" (Stangg).
        # A delayed ability (CR 603.7) belongs to no permanent, so the scan
        # above cannot reach it, and CR 603.6c's event is any move off the
        # battlefield rather than a death — so it is announced here, from the
        # one transition every such move passes through, and not from the
        # graveyard path beside the dies-triggers.
        for perm in removed:
            fire_delayed_triggers(
                self, "bound_permanent_leaves_battlefield", subject=perm,
            )
            # "…leaves the battlefield **or becomes untapped**" (Merieke Ri
            # Berit). One ability answering to either event, so this site
            # announces the second key beside the first; `become_untapped` is
            # the other announcer. A separate call rather than a list of
            # aliases, because an entry armed under one key must not be woken
            # by the other's name.
            fire_delayed_triggers(
                self, "bound_permanent_leaves_or_untaps", subject=perm,
            )
            # "…or **you lose control of this creature**." (Coffin Queen.)
            # A permanent leaving the battlefield *is* its controller losing
            # control of it — CR 400.7 makes what comes back a different
            # object, and nobody controls the one that left — which is the
            # same reading the printed `lose_control_of_source` trigger takes
            # from this very scan. The other way to lose control is a change
            # of hands, and that fires from `_sync_control`.
            fire_delayed_triggers(
                self, "bound_permanent_untaps_or_control_lost", subject=perm,
            )
            # The other half of the condition above: a permanent off the
            # battlefield is not a tapped permanent on it, so the abilities it
            # created "for as long as this creature remains tapped" end here
            # too (CR 611.2b).
            end_source_tapped_delayed_triggers(self, perm)
        # An Aura's continuous effects end when it leaves (CR 611.3), and this
        # is the one transition it can leave by. It was wired into
        # ``_permanent_to_graveyard`` alone, which is the *destination* rather
        # than the departure — so an Aura bounced, exiled or tucked kept
        # applying: Control Magic returned to its controller's hand left the
        # creature stolen for the rest of the game, and Evil Presence exiled
        # left the land a Swamp. Idempotent, because ``_remove_aura_effects``
        # returns at once when nothing is attached, so the graveyard path's own
        # call stays harmless.
        for perm in removed:
            if "Aura" in perm.card.type_line:
                self._remove_aura_effects(perm)
        for perm in removed:
            self.return_linked_exile(perm, "left the battlefield", LEAVES)
        # "Target land becomes a Forest **until this creature leaves the
        # battlefield**." (Gaea's Liege, Graceful Antelope.) The window's
        # sweep, here for the reason the exile return above is: this is the
        # one transition out. It was a name-keyed hook on the graveyard path
        # alone, so a Liege bounced, exiled or tucked left its lands Forests
        # for good.
        reverted = 0
        for perm in removed:
            reverted += end_land_type_changes_tied_to(self.all_permanents(), perm)
        if reverted:
            # Whatever else says those lands are something reasserts itself
            # (CR 611.3), and every count and static scoped to a land type
            # has a different board to read.
            self._refresh_dynamic_creatures()
        return removed

    # ------------------------------------------------------------------
    # Combat's slots, kept honest across a removal
    # ------------------------------------------------------------------

    def _combat_seat_of_blocker(self, attacker_index: int) -> int | None:
        """Which seat a blocker index belongs to, given the attacker it blocks.

        ``combat_banding_damage`` and ``combat_multiblock_damage`` record blocker
        slots with no seat beside them, which is unambiguous in a duel and not
        in a CR 802 multi-defender combat. The seat is recoverable: a blocker
        blocks an attacker, and ``combat_attackers`` says which player that
        attacker is attacking. Read before any map is rewritten, so it answers
        from the pre-removal numbering.
        """
        seat = self.combat_attackers.get(attacker_index)
        if seat is None:
            return self.combat_defending_player_index
        return seat

    def _renumber_combat_after_removal(self, vacated: dict[int, list[int]]) -> None:
        """Keep every combat map pointing at the creatures it meant.

        Combat is recorded as **battlefield slots** — attacker index, blocker
        index — and a slot is not a name. A creature dying in the first-strike
        damage step shifts every later slot on its controller's battlefield down
        by one, so an attacker recorded as index 3 silently becomes whatever
        index 3 is now. That was the bug this whole thread of work was chasing,
        and consolidating removal into one transition is what made it fixable in
        one place instead of 41.

        Two things happen to a recorded slot. If its own creature left, the
        entry is **dropped** — a dead attacker is not attacking. Otherwise it is
        **shifted** down by the number of departing creatures that sat ahead of
        it on the same battlefield.

        The seat for each index is not guessed: an attacker index is always the
        active player's (``declare_attackers`` refuses any other controller), a
        blocker index in ``combat_blockers`` comes from its own outer key, and
        the two damage-assignment maps recover it through
        :meth:`_combat_seat_of_blocker`.
        """
        if not vacated:
            return

        def shift(seat: int | None, index: int) -> int | None:
            """*index* after the removal, or None if that creature is the one gone."""
            gone = vacated.get(seat) if seat is not None else None
            if not gone:
                return index
            if index in gone:
                return None
            return index - sum(1 for slot in gone if slot < index)

        attacker_seat = self.active_player_index
        # Snapshot the attacker->defender map before anything is rewritten; the
        # blocker-seat lookups below read it.
        blocker_seat_of = {
            attacker: self._combat_seat_of_blocker(attacker)
            for attacker in list(self.combat_attackers)
        }

        def shift_attacker(index: int) -> int | None:
            return shift(attacker_seat, index)

        self.combat_attackers = {
            moved: defender
            for attacker, defender in self.combat_attackers.items()
            if (moved := shift_attacker(attacker)) is not None
        }

        # Keys are attacker slots on the active seat, exactly like
        # combat_attackers; the values are permanent ids and never renumber.
        self.combat_attacked_planeswalkers = {
            moved: walker_id
            for attacker, walker_id in self.combat_attacked_planeswalkers.items()
            if (moved := shift_attacker(attacker)) is not None
        }

        rebuilt_blockers: dict[int, dict[int, list[int]]] = {}
        for defender_seat, blocks in self.combat_blockers.items():
            rebuilt: dict[int, list[int]] = {}
            for blocker, attackers in blocks.items():
                moved_blocker = shift(defender_seat, blocker)
                if moved_blocker is None:
                    continue
                moved_attackers = [
                    moved
                    for attacker in attackers
                    if (moved := shift_attacker(attacker)) is not None
                ]
                # A blocker whose every attacker has gone is no longer blocking
                # anything; dropping it keeps "is this creature blocking?" true.
                if moved_attackers:
                    rebuilt[moved_blocker] = moved_attackers
            if rebuilt:
                rebuilt_blockers[defender_seat] = rebuilt
        self.combat_blockers = rebuilt_blockers

        self.combat_bands = [
            moved_band
            for band in self.combat_bands
            if (moved_band := [
                moved for member in band if (moved := shift_attacker(member)) is not None
            ])
        ]

        self.combat_band_blocks = {
            moved_attacker: moved_blockers
            for attacker, blockers in self.combat_band_blocks.items()
            if (moved_attacker := shift_attacker(attacker)) is not None
            and (moved_blockers := [
                moved
                for blocker in blockers
                if (moved := shift(blocker_seat_of.get(attacker), blocker)) is not None
            ])
        }

        self.combat_banding_damage = {
            moved_attacker: moved_assignment
            for attacker, assignment in self.combat_banding_damage.items()
            if (moved_attacker := shift_attacker(attacker)) is not None
            and (moved_assignment := {
                moved: amount
                for blocker, amount in assignment.items()
                if (moved := shift(blocker_seat_of.get(attacker), blocker)) is not None
            })
        }

        rebuilt_multiblock: dict[int, dict[int, int]] = {}
        for blocker, assignment in self.combat_multiblock_damage.items():
            # This map keys by blocker, so its seat comes from an attacker the
            # blocker is blocking rather than from the key itself.
            seat = next(
                (blocker_seat_of.get(attacker) for attacker in assignment),
                self.combat_defending_player_index,
            )
            moved_blocker = shift(seat, blocker)
            if moved_blocker is None:
                continue
            moved_assignment = {
                moved: amount
                for attacker, amount in assignment.items()
                if (moved := shift_attacker(attacker)) is not None
            }
            if moved_assignment:
                rebuilt_multiblock[moved_blocker] = moved_assignment
        self.combat_multiblock_damage = rebuilt_multiblock

        self.combat_attacker_piles = {
            moved: side
            for attacker, side in self.combat_attacker_piles.items()
            if (moved := shift_attacker(attacker)) is not None
        }
        self.combat_defender_piles = {
            moved: side
            for creature, side in self.combat_defender_piles.items()
            if (moved := shift(self.combat_left_right_defender_index, creature)) is not None
        }

    def permanent_ids_at(self, seat, index):
        """The stable id(s) of whatever sits at *index* on *seat*'s battlefield.

        Takes the index shape the wire and the stack already speak — an int, a
        list of ints, or None — and returns the same shape in ids, so a caller
        recording a target keeps the two readable side by side. An entry that
        does not resolve becomes None rather than being dropped, because a
        multi-target list is positional and a shorter list would silently
        re-pair the surviving targets with the wrong slots."""
        if isinstance(index, list):
            return [self.permanent_ids_at(seat, entry) for entry in index]
        permanent = self.permanent_at(seat, index)
        return None if permanent is None else permanent.permanent_id
