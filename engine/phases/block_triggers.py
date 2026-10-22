from __future__ import annotations

"""Block triggers (CR 509.2a, CR 509.3).

Every trigger the declare-blockers step announces once blocks are known:
"whenever this creature blocks" and "…becomes blocked", once per creature or
once per creature on the other side of the block as CR 509.3a–d draw it, the
same sentences printed on something attached to a combatant, the board-wide
forms ("whenever a creature becomes blocked by a creature with lesser
power"), the delayed forms a resolved spell leaves behind, "attacks and isn't
blocked" (CR 509.3g), and CR 509.3e's "by one or more Orcs" threshold.

Split out of ``DeclareBlockersStepMixin``, which declares the blocks and then
calls these through ``self``, and composed onto ``Game`` directly after
``BlockLegalityMixin``. ``fire_becomes_blocked_by_effect`` is the one an effect
calls: a creature an effect blocks becomes blocked outside any declaration.
"""

from ..delayed_triggers import fire_delayed_triggers
from ..models import Permanent
from ..trigger_utils import matching_triggers


#: CR 509.3e's threshold, as ``engine/oracle.py``'s condition table records it:
#: "blocks or becomes blocked by **one or more** Orcs" (Dwarven Soldier). Absent
#: means the sentence printed no number, which is the per-creature firing
#: CR 509.3b/509.3d give — so the two shapes are told apart by the payload and
#: neither dispatcher needs to know which card it is reading.
_PAIR_THRESHOLD_KEY = "block_pair_count"


def _meets_threshold(trig, admitted: list) -> bool:
    """Whether *admitted* satisfies the trigger's printed "N or more" (CR 509.3e).

    True with no threshold printed, because then every admitted creature is its
    own firing and the caller is already looping over them.
    """
    threshold = trig.condition.payload.get(_PAIR_THRESHOLD_KEY)
    if not isinstance(threshold, int):
        return True
    return len(admitted) >= threshold


def _threshold_blockers(trig, admitted: list) -> list:
    """Which admitted blockers a narrowed becomes-blocked trigger fires for.

    The mirror of :func:`_threshold_firings` on the other side of the block: no
    printed threshold is CR 509.3d's one firing per creature, and a printed one
    is CR 509.3e's single firing for the declaration — represented as the first
    creature that answered, because the firing still records a pair.
    """
    if not isinstance(trig.condition.payload.get(_PAIR_THRESHOLD_KEY), int):
        return admitted
    return admitted[:1] if _meets_threshold(trig, admitted) else []


def _threshold_firings(trig, admitted: list) -> list[dict]:
    """The firing contexts a narrowed block trigger produces for *admitted*.

    Without a printed threshold that is one firing per creature the phrase
    admits (CR 509.3b/509.3d). With one it is a single firing for the whole
    declaration (CR 509.3e), carrying every creature that answered — the pair
    is recorded by id for the same reason the unnarrowed half records it, so a
    sentence that does say "that creature" reads the set the event was about
    rather than whichever attacker the item happens to point at.
    """
    if not _meets_threshold(trig, admitted):
        return []
    if isinstance(trig.condition.payload.get(_PAIR_THRESHOLD_KEY), int):
        return [{"blocked_permanent_ids": [a.permanent_id for a in admitted]}]
    return [{"blocked_permanent_ids": [a.permanent_id]} for a in admitted]


class BlockTriggersMixin:
    def _fire_creature_blocks_triggers(
        self, controller_index: int, assignments: dict[int, list[int]],
        *, already_blocking: bool = False,
    ) -> None:
        """Put each blocker's own "whenever this creature blocks" triggers on
        the stack (e.g. Ydwen Efreet's coin flip) — once per blocking
        creature declared this call, regardless of how many attackers it
        blocks (unlike Cockatrice's per-attacker-blocked firing).

        "…blocks **a creature with flying**" (Snarespinner) narrows the same
        trigger by what was blocked, so it fires once for each blocked attacker
        the filter admits. The unnarrowed form keeps its once-per-blocker
        firing — CR 509.3c/509.3d draw exactly that line, and the filter's
        presence is what tells the two apart.

        *already_blocking* is the blocking side's twin of
        ``_fire_becomes_blocked_triggers``' ``already_blocked``, and CR 509.3a
        is why it exists: an effect that makes a creature block triggers the
        bare wording "only if it wasn't a blocking creature at that time".
        General Jarkeld's reassignment moves a creature from one attacker to
        another without it ever ceasing to be a blocking creature, so the bare
        half must not fire again — while CR 509.3b's "blocks **a creature**"
        half does, because it was not already blocking *that* attacker. Sorrow's
        Path is the other case and leaves the flag alone: its creatures are
        removed from combat first, so they really do start blocking again.
        """
        from ..aura_attachment import attached_subject_triggers
        from ..events import trigger_subject_matches
        from ..game_types import StackItem

        for blocker_idx, blocker, blocked in self._resolved_block_pairs(
            controller_index, assignments
        ):
            # "attacks or blocks" (Elder Gargaroth): the block half of the
            # union — the attack half fires in declare_attackers_step.
            # The blocker's own abilities, and then the joined block-pair
            # sentence printed on something *attached* to it (Infinite
            # Authority). One body, because the firing is identical: the same
            # noun phrase decides how many times it fires and the same pair
            # rides the context. What differs is only which permanent is the
            # ability's source, and which seat controls it (CR 113.7a) — so
            # those two travel beside the trigger rather than being re-derived
            # below.
            watchers = [
                (blocker, controller_index, trig)
                for trig in matching_triggers(
                    blocker.effective_card,
                    condition_kinds={
                        "creature_blocks",
                        "creature_attacks_or_blocks",
                        # The joined sentence's *blocks* half. Its noun phrase
                        # lands under `blocked_filter` like a card that prints
                        # this half on its own, so nothing below has to know it
                        # was joined.
                        "creature_blocks_or_blocked_by",
                    },
                )
            ] + [
                (attachment, seat, trig)
                for seat, attachment, trig in attached_subject_triggers(
                    self, blocker, {"creature_blocks_or_blocked_by"},
                    "combatant_attached",
                )
            ]
            for source, source_seat, trig in watchers:
                # Each firing records which blocked creature(s) it is *about*
                # (by stable id, CR 509.3f fixes the set at declaration), so an
                # effect saying "that creature" (Wall of Dust) resolves the
                # other half of the pair rather than the blocker the item's
                # target indices carry. The unnarrowed once-per-blocker firing
                # is about every attacker this blocker blocks; a narrowed
                # firing is about the one attacker that admitted it.
                if not trig.condition.payload.get("blocked_filter"):
                    # CR 509.3a's once-per-creature half, silent when the
                    # creature was already a blocking creature.
                    firing_contexts: list[dict] = [] if already_blocking else [{
                        "blocked_permanent_ids": [
                            attacker.permanent_id for _, attacker in blocked
                        ],
                    }]
                else:
                    admitted = [
                        attacker for _, attacker in blocked
                        if trigger_subject_matches(
                            self, trig, "blocked", attacker,
                            observer=source_seat, source=blocker,
                        )
                    ]
                    firing_contexts = _threshold_firings(trig, admitted)
                for firing_context in firing_contexts:
                    pushed = self._stack_push(
                        StackItem(
                            card=source.card,
                            caster_index=source_seat,
                            # The blocker's own controller/index, so the coin-flip
                            # handler can remove IT from combat without re-deriving
                            # who owns it.
                            target_player_index=controller_index,
                            target_permanent_index=blocker_idx,
                            x_value=None,
                            ability_instruction=trig.instruction,
                            ability_effect_kind=trig.effect_kind,
                            source_permanent=source,
                            ability_text=trig.source_line,
                            trigger_context=firing_context,
                        )
                    )
                    # Only if it actually went on: CR 603.4 can refuse the
                    # push (``trigger_condition_holds``), and a line saying
                    # "added to stack" under one saying it didn't trigger is a
                    # record contradicting itself.
                    if pushed is not None:
                        self.log.append(
                            f"{source.card.name} triggered on block (added to stack)"
                        )
            # "…whenever **this creature** blocks or becomes blocked by a
            # creature this combat, …" (Goblin Flotilla). The delayed spelling
            # of the joined block event, which belongs to no permanent's
            # compiled program and so is out of reach of the scan above — the
            # entry is one an ability *created*, and it watches the creature
            # that armed it by id.
            #
            # Once per pair, and the pair rides the same
            # ``blocked_permanent_ids`` key the printed static form writes: "that
            # creature" is then one reader for both spellings. The blocker is
            # the watched object and the attacker is the ``agent`` the printed
            # noun phrase narrows, which is the half the card describes.
            for _attacker_idx, attacker in blocked:
                fire_delayed_triggers(
                    self, "source_blocks_or_blocked_by",
                    subject=blocker, agent=attacker,
                    trigger_context={
                        "blocked_permanent_ids": [attacker.permanent_id],
                    },
                )
            # "Whenever **enchanted creature** attacks or blocks" (Imprison) —
            # the block half of the union whose attack half fires in
            # declare_attackers_step. Something attached to the blocker, not
            # the blocker itself: an Aura's ability is the Aura's (CR 113.7a),
            # so it is on no `effective_card` the scan above reads.
            for seat, attachment, trig in (
                () if already_blocking else attached_subject_triggers(
                    self, blocker, {"creature_attacks_or_blocks"},
                    "combatant_attached",
                )
            ):
                self._stack_push(
                    StackItem(
                        card=attachment.card,
                        # CR 603.3a: the attachment's controller controls the
                        # ability, and is the "you" its cost is offered to.
                        caster_index=seat,
                        target_player_index=seat,
                        target_permanent_index=None,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=attachment,
                        ability_text=trig.source_line,
                    )
                )
                self.log.append(
                    f"{attachment.card.name} triggered on "
                    f"{blocker.card.name}'s block (added to stack)"
                )

    def _resolved_block_pairs(
        self, controller_index: int, assignments: dict[int, list[int]]
    ) -> list[tuple[int, Permanent, list[tuple[int, Permanent]]]]:
        """``(blocker index, blocker, [(attacker index, attacker)])`` for a
        declaration, with every slot resolved exactly once.

        The combat maps are index-keyed by design, so reading a permanent out of
        one means a positional battlefield read — the thing
        ``tests/engine/test_control_reads.py`` ratchets. Doing it here, once, is
        what lets the two fire sites below take permanents rather than each
        re-resolving the same slots.
        """
        if not (0 <= controller_index < len(self.players)):
            return []
        defender = self.players[controller_index]
        attacker_controller = (
            self.players[self.active_player_index]
            if 0 <= self.active_player_index < len(self.players)
            else None
        )
        pairs: list[tuple[int, Permanent, list[tuple[int, Permanent]]]] = []
        for blocker_idx, attacker_indices in assignments.items():
            if not (0 <= blocker_idx < len(defender.battlefield)):
                continue
            blocked: list[tuple[int, Permanent]] = []
            if attacker_controller is not None:
                blocked = [
                    (idx, attacker_controller.battlefield[idx])
                    for idx in attacker_indices
                    if 0 <= idx < len(attacker_controller.battlefield)
                ]
            pairs.append((blocker_idx, defender.battlefield[blocker_idx], blocked))
        return pairs

    def _fire_unblocked_attack_triggers(self) -> None:
        """"Whenever this creature attacks and isn't blocked" (Merchant Ship,
        Floral Spuzzem) — CR 509.1h.

        The third of this step's fire sites, and it belongs here for the same
        reason the other two do: the condition is about the *declaration*, and
        it can only be evaluated once blocks are known. It used to be evaluated
        one step later, from inside ``resolve_combat_damage``, which was
        reliable and wrong — an ability that changes what combat damage does
        was resolving after the damage.

        Unlike its two neighbours it is **not** called from
        :meth:`declare_blockers`: an attacker with nobody blocking it is
        unblocked whether or not any declaration happened at all, and the
        defender with no legal block is auto-skipped without ever reaching
        that method. The caller is the declare-blockers step's completion in
        ``combat_phase``, the one point every path to locked blocks reaches,
        and ``combat_unblocked_triggers_fired`` is what makes it once.

        The ability names **no target**. "Attacks and isn't blocked" is about
        the attacker, which travels as the stack item's ``source_permanent``;
        one that targets chooses its target as it is put on the stack
        (``_choose_trigger_targets``), from the list the picker offers.
        """
        from ..aura_attachment import attached_subject_triggers
        from ..game_types import StackItem

        if self.combat_unblocked_triggers_fired:
            return
        self.combat_unblocked_triggers_fired = True
        if not (0 <= self.active_player_index < len(self.players)):
            return
        controller_index = self.active_player_index
        controller = self.players[controller_index]
        for idx in list(self.combat_attackers):
            if not (0 <= idx < len(controller.battlefield)):
                continue
            permanent = controller.battlefield[idx]
            if permanent.blocked or self._attacker_all_blockers(idx):
                continue
            # CR 506.2: which seat is being attacked, frozen into the
            # announcement (CR 603.10) rather than looked up when the ability
            # resolves — the attacker can leave combat in response, and
            # "defending player" would then name nobody.
            defending_index = self.combat_attackers.get(idx)
            # The attacker's own ability, then the same sentence printed on
            # something attached to it (Cloak of Confusion). One kind, two
            # dispatch scopes — the mirror of the scan in
            # `_fire_becomes_blocked_triggers`, and one body for the same
            # reason: only the ability's source and its controlling seat
            # differ. CR 113.7a: an Aura's ability is the Aura's, controlled by
            # the Aura's controller, so the seat is read off the attachment and
            # not borrowed from the attacker.
            watchers = [
                (permanent, controller_index, trig)
                for trig in matching_triggers(
                    permanent.effective_card, condition_kinds={"attacks_unblocked"}
                )
            ] + [
                (attachment, aura_seat, trig)
                for aura_seat, attachment, trig in attached_subject_triggers(
                    self, permanent, {"attacks_unblocked"}, "combatant_attached",
                )
            ]
            for source, source_seat, trig in watchers:
                self._stack_push(
                    StackItem(
                        card=source.card,
                        caster_index=source_seat,
                        target_player_index=source_seat,
                        target_permanent_index=None,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=source,
                        ability_text=trig.source_line,
                        trigger_context={
                            "trigger_defending_player_index": defending_index,
                        },
                    )
                )
                self.log.append(
                    f"{source.card.name} triggered (attacked and wasn't blocked)"
                )
            # "Until end of turn, whenever a creature you control attacks and
            # isn't blocked, …" (Gaze of Pain.) A delayed ability belongs to no
            # permanent, so the scan above cannot reach it — the entry is a
            # spell's and the spell is in a graveyard. Announced here, inside
            # the same per-attacker loop, because that is what makes the two
            # readings of one moment agree: the printed static on the attacker
            # and the delayed one a spell armed fire on exactly the same set of
            # creatures.
            #
            # The attacker is named as the source for `_fire_delayed_block_triggers`'s
            # reason: the sentence behind this opener says "…have **it** deal
            # damage equal to **its** power", and CR 603.7d's own-source
            # default would point that at the spell.
            fire_delayed_triggers(
                self, "creature_attacks_unblocked",
                subject=permanent,
                source_permanent=permanent,
            )

    def _fire_delayed_block_triggers(
        self, controller_index: int, assignments: dict[int, list[int]]
    ) -> None:
        """Announce ``creature_blocks`` for each creature this declaration made
        a blocker (CR 509.1i, CR 603.7).

        A delayed ability belongs to no permanent, so the scan
        ``_fire_creature_blocks_triggers`` runs over the battlefield cannot
        reach it - the entry is a spell's ("Whenever a creature blocks this
        turn, ...", Battle Cry) and the spell is in a graveyard. Its own pass
        for that reason rather than a branch inside the scan.

        Once per *blocking creature*, whatever it was declared against:
        CR 509.3c is the line the printed scan beside this one already draws,
        and this opener prints no narrowing by what was blocked.

        ``source_permanent`` is named rather than defaulted, exactly as the
        combat-damage site names its attacker: the sentence behind this opener
        says "..., <do something to **it**>", and CR 603.7d's own-source
        default would point the effect at the spell that created the ability.
        """
        for _blocker_idx, blocker, _blocked in self._resolved_block_pairs(
            controller_index, assignments
        ):
            fire_delayed_triggers(
                self, "creature_blocks",
                subject=blocker,
                source_permanent=blocker,
            )

    def _fire_becomes_blocked_triggers(
        self, controller_index: int, assignments: dict[int, list[int]],
        *, already_blocked: bool = False,
    ) -> None:
        """An attacker's own "whenever this creature becomes blocked" triggers.

        CR 509.3c/509.3d is the whole design: the bare wording fires **once**
        for the creature however many blockers it has, while "becomes blocked
        **by a creature**" fires once for *each* creature that blocks it. The
        subject filter is what separates them, so the count is read off the
        condition rather than off a per-card list — which is also why this
        dispatcher can exist at all. It never had one: `creature_becomes_blocked`
        parsed in both tables and no combat step fired it, the same shape as
        `creature_attacks_or_blocks` and `creature_you_control_dies` before it.

        *already_blocked* is for the second way a block happens: an effect that
        reassigns blockers between attackers that were **already** blocked
        (Sorrow's Path). CR 509.1h keeps such an attacker blocked throughout, so
        CR 509.3c's once-per-creature half does not fire again — it triggers
        "only if the attacking creature was an unblocked creature at that time"
        — while CR 509.3d's per-blocker half does, because that creature was not
        already blocking that attacker. One flag rather than a second
        dispatcher, so the two halves cannot drift apart.
        """
        if not (0 <= self.active_player_index < len(self.players)):
            return
        blockers_of: dict[int, tuple[Permanent, list[Permanent]]] = {}
        for _, blocker, blocked in self._resolved_block_pairs(
            controller_index, assignments
        ):
            for attacker_idx, attacker in blocked:
                blockers_of.setdefault(attacker_idx, (attacker, []))[1].append(blocker)
        for attacker_idx, (attacker, blockers) in blockers_of.items():
            self._announce_becomes_blocked(
                attacker_idx, attacker, blockers, already_blocked=already_blocked
            )

    def fire_becomes_blocked_by_effect(self, attackers: list[Permanent]) -> None:
        """Announce the becoming-blocked of *attackers* an **effect** blocked.

        "Target unblocked attacking creature becomes blocked." (Dazzling Beauty,
        Trap Runner); "Attacking creatures become blocked." (Fog Patch.) CR
        509.1h: an effect can say a creature becomes blocked, and CR 509.3c says
        what that is to a trigger — "Whenever [a creature] becomes blocked" "will
        also trigger if that creature becomes blocked by an effect … but only if
        the attacking creature was an unblocked creature at that time". So the
        caller hands over only the creatures that *were* unblocked, and each is
        announced once.

        What it announces is the **bare** half and nothing else. CR 509.3d's
        "becomes blocked **by a creature**" "won't trigger if the creature
        becomes blocked by an effect rather than a creature", and there is no
        blocker for its noun phrase to be about — which is the shape
        :meth:`_announce_becomes_blocked` already draws, handed an empty list of
        blockers. The three announcements beside the printed one are the same
        three the declaration makes, minus their blocker: the delayed ability
        bound to the attacker (Barreling Attack) and the board-wide bare reading
        (Close Quarters' "whenever a creature you control becomes blocked").

        No declare-blockers step entry point calls this: the declaration's own
        announcements are about pairs, and this is the one way a creature
        becomes blocked without one.
        """
        from ..events import emit

        if not (0 <= self.active_player_index < len(self.players)):
            return
        for attacker in attackers:
            attacker_idx = self.battlefield_index_of(attacker)
            if attacker_idx is None:
                continue
            self._announce_becomes_blocked(attacker_idx, attacker, [])
            fire_delayed_triggers(
                self, "bound_permanent_becomes_blocked", subject=attacker,
            )
            emit(
                self, "matching_creature_becomes_blocked",
                subject=attacker,
                combatant_permanent_id=attacker.permanent_id,
                blocked_permanent_ids=[],
                event_subject_permanent_id=attacker.permanent_id,
                event_subject_controller=self.controller_index_of(attacker),
                pair_announcement=False,
            )

    def _announce_becomes_blocked(
        self, attacker_idx: int, attacker: Permanent, blockers: list[Permanent],
        *, already_blocked: bool = False,
    ) -> None:
        """One attacker's own "whenever this creature becomes blocked" triggers,
        and the same sentence printed on something attached to it.

        *blockers* is empty when an **effect** blocked the creature
        (:meth:`fire_becomes_blocked_by_effect`). The bare wording then fires
        once with no blocker to be about, and every narrowed one finds nothing
        to admit — CR 509.3c and CR 509.3d drawing their line through one body
        rather than two.
        """
        from ..aura_attachment import attached_subject_triggers
        from ..events import trigger_subject_matches
        from ..game_types import StackItem
        from ..targeting import announces_a_target

        seat = self.active_player_index
        # CR 506.2: the seat this attacker is attacking, frozen into the
        # announcement (CR 603.10) under the key every other combat fire
        # site already stamps. "Whenever this creature becomes blocked,
        # **defending player** discards a card" (Alley Grifters) is the
        # phrase that needs it, and the attacker can leave combat before the
        # ability resolves — after which `defending_player_index_now` would
        # answer for a combat this trigger was never part of, or for nobody
        # at all. Read off `combat_attackers` rather than off the blocker's
        # controller: CR 509.1a makes those the same seat in every legal
        # declaration, and the map is the one that says which combat.
        defending_index = self.combat_attackers.get(attacker_idx)
        # The attacker's own abilities, then the joined block-pair sentence
        # printed on something attached to it (Infinite Authority, whichever
        # side of the block its host is on). The mirror of the scan in
        # `_fire_creature_blocks_triggers`, and one body for the same
        # reason: only the ability's source and its controlling seat differ.
        watchers = [
            (attacker, seat, trig)
            for trig in matching_triggers(
                attacker.effective_card,
                condition_kinds={
                    "creature_becomes_blocked",
                    # …and its *becomes blocked by* half, under
                    # `blocker_filter`.
                    "creature_blocks_or_blocked_by",
                },
            )
        ] + [
            (attachment, aura_seat, trig)
            for aura_seat, attachment, trig in attached_subject_triggers(
                self, attacker,
                {
                    "creature_blocks_or_blocked_by",
                    # "Whenever **enchanted creature** becomes blocked"
                    # (Bestial Fury) — the attacking half on its own, where
                    # the joined kind beside it is the pair. Both are the
                    # attacker's event and both are printed on something
                    # attached to it, so both are read from the attachment
                    # scan here; the attacker's own card is scanned above
                    # for the same two kinds. Leaving this one out is how a
                    # trigger compiles, claims, reports supported and never
                    # fires — the one failure `attached_subject_triggers`
                    # exists to make impossible to repeat per card.
                    "creature_becomes_blocked",
                },
                "combatant_attached",
            )
        ]
        for source, source_seat, trig in watchers:
            if not trig.condition.payload.get("blocker_filter"):
                # CR 509.3c: once for the creature. With no blocker (an
                # effect blocked it) the firing is about no blocker at all,
                # which ``None`` stands for below.
                matched: list[Permanent | None] = (
                    [] if already_blocked else (blockers[:1] or [None])
                )
            else:
                matched = [
                    b for b in blockers
                    if trigger_subject_matches(
                        self, trig, "blocker", b, observer=source_seat,
                        source=attacker,
                    )
                ]
                # CR 509.3e's "at least a certain number": one firing for
                # the whole declaration rather than one per creature, and
                # the blocker it is *about* is the first that answered — the
                # sentence printing this threshold names no creature back
                # (Dwarven Soldier says "this creature gets …"), so the pair
                # travels for the log rather than for an effect to read.
                # With no threshold printed the per-creature firing of
                # CR 509.3d stands, which is every other card here.
                matched = _threshold_blockers(trig, matched)
            # **A printed "target" is a choice, not the blocker.** "…you may
            # have it deal damage equal to its power to **target creature**"
            # (the Laccoliths) names any creature the controller picks
            # (CR 603.3d), and stamping the blocker into the target field is
            # what `_choose_trigger_targets` reads as "the event already made
            # the choice" — so every Laccolith shot the creature that blocked
            # it whatever its controller wanted. The blocker still travels as
            # ``blocked_permanent_ids`` below, which is where "that creature"
            # reads it, so only an ability that announces a target loses the
            # stamp.
            chooses = announces_a_target(trig.instruction)
            for blocker in matched:
                # **The blocker is what the trigger bound**, so it is the
                # stack item's target: "destroy that Wall" (Battering Ram)
                # names the creature that blocked, and by the time the
                # ability resolves nothing else could say which. Stamped by
                # id as well as by slot, because a removal in between
                # renumbers every later one (CR 400.7).
                blocker_seat = (
                    self.controller_index_of(blocker) if blocker is not None else None
                )
                stamped = blocker if not chooses else None
                pushed = self._stack_push(
                    StackItem(
                        card=source.card,
                        caster_index=source_seat,
                        target_player_index=(
                            blocker_seat if blocker_seat is not None else seat
                        ),
                        target_permanent_index=(
                            self.battlefield_index_of(stamped)
                            if stamped is not None else None
                        ),
                        target_permanent_id=(
                            stamped.permanent_id if stamped is not None else None
                        ),
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=source,
                        ability_text=trig.source_line,
                        # "That creature's controller" is the blocker's, and
                        # a blocker can leave before this resolves — so the
                        # seat is frozen now (CR 603.10), exactly as the
                        # death triggers freeze theirs.
                        trigger_context={
                            "event_subject_controller": blocker_seat,
                            # CR 506.2's seat, so a sentence after this
                            # event may say "defending player" and name one
                            # (`lowering/_events._DEFENDING_PLAYER_EVENTS`).
                            "trigger_defending_player_index": defending_index,
                            # The pair this firing is about, by stable id
                            # and under the key the *blocks* half already
                            # writes. `block_pair_permanents` prefers it to
                            # the item's target, which is the same blocker
                            # here — but an ability whose source is an Aura
                            # attached to the attacker has no reason to
                            # carry the blocker as its target at all.
                            "blocked_permanent_ids": (
                                [blocker.permanent_id] if blocker is not None else []
                            ),
                        },
                    )
                )
                # Only if it actually went on (CR 603.4 can refuse the push),
                # for the reason the block fire site above gives.
                if pushed is not None:
                    self.log.append(
                        f"{source.card.name} triggered on becoming blocked (added to stack)"
                    )

    def _fire_board_wide_block_triggers(
        self, controller_index: int, assignments: dict[int, list[int]]
    ) -> None:
        """"Whenever **a creature** becomes blocked by a creature with lesser
        power" / "…**a creature** blocks a creature with lesser power"
        (No Quarter) — CR 509.1a's pair announced to the whole table.

        The fourth block-fire shape and the only one whose watcher is neither
        combatant nor attached to one, which is exactly why it is announced
        through the event bus rather than by a scan: the two printed scans above
        read ``blocker.effective_card`` and ``attacker.effective_card``, and an
        enchantment sitting on a third player's battlefield is in neither.
        ``emit`` collects from every permanent, every emblem and every graveyard
        that carries the condition, which is what a board-wide watcher means —
        the same arrangement ``_fire_matching_creature_attacks_triggers`` has one
        step earlier.

        **Two announcements per pair, not one**, because the two kinds are two
        questions: which creature the firing is *about* decides which half "the
        blocking creature" and "the attacking creature" name, and a single kind
        would leave the effect unable to tell them apart. A card printing both
        lines (No Quarter prints exactly both) therefore fires once per line per
        pair, which is what the two printed sentences say.

        ``blocked_permanent_ids`` carries the **partner** under the key
        ``handlers/_targets.block_pair_permanents`` already reads, so the effect
        resolves the other half of the pair through the one reader every other
        block-pair effect goes through. ``target_permanent_id`` carries it too,
        for the stack item, the log and CR 400.7's identity.
        """
        from ..events import emit

        pairs = list(self._resolved_block_pairs(controller_index, assignments))
        for _blocker_idx, blocker, blocked in pairs:
            for _attacker_idx, attacker in blocked:
                emit(
                    self, "matching_creature_becomes_blocked",
                    subject=attacker,
                    combatant_permanent_id=attacker.permanent_id,
                    partner_permanent_id=blocker.permanent_id,
                    blocked_permanent_ids=[blocker.permanent_id],
                    target_permanent_id=blocker.permanent_id,
                    event_subject_permanent_id=attacker.permanent_id,
                    event_subject_controller=self.controller_index_of(attacker),
                    pair_announcement=True,
                )
                emit(
                    self, "matching_creature_blocks",
                    subject=blocker,
                    combatant_permanent_id=blocker.permanent_id,
                    partner_permanent_id=attacker.permanent_id,
                    blocked_permanent_ids=[attacker.permanent_id],
                    target_permanent_id=attacker.permanent_id,
                    event_subject_permanent_id=blocker.permanent_id,
                    event_subject_controller=self.controller_index_of(blocker),
                    pair_announcement=True,
                )
        self._announce_bare_board_wide_blocks(pairs)

    def _announce_bare_board_wide_blocks(self, pairs) -> None:
        """CR 509.3c/509.3d's other reading of the two announcements above.

        "Whenever **a creature** blocks" (Heat of Battle) fires once for each
        creature that blocks, and "Whenever **a Sliver** becomes blocked"
        (Spined Sliver) once for each creature that becomes blocked - however
        many creatures are on the other side of that block. The per-pair
        announcements above are the *narrowed* reading: "...blocks a creature
        with lesser power" (No Quarter) fires once per creature its phrase
        admits.

        Two announcements rather than one counted differently, because the count
        is what the ``emit`` makes: a trigger sees as many firings as there are
        events. ``event_filters._board_wide_block_filter`` is what keeps each condition
        on exactly one of the two, off the presence of its own partner phrase -
        so no card takes both, and a bare condition about an attacker blocked by
        three cannot fire three times.

        The same shape the two source-scoped scans one screen up already have,
        where the choice between "once" and "once per admitted creature" is read
        off ``trig.condition.payload``. Here it cannot be, because ``emit``
        collects the watchers instead of the fire site scanning for them.
        """
        from ..events import emit

        blocked_by: dict[int, tuple] = {}
        for _blocker_idx, blocker, blocked in pairs:
            emit(
                self, "matching_creature_blocks",
                subject=blocker,
                combatant_permanent_id=blocker.permanent_id,
                blocked_permanent_ids=[perm.permanent_id for _, perm in blocked],
                event_subject_permanent_id=blocker.permanent_id,
                event_subject_controller=self.controller_index_of(blocker),
                pair_announcement=False,
            )
            # "Whenever a creature **attacks or blocks**" (Powerstone
            # Minefield) — the block half of the board-wide union
            # ``_fire_matching_creature_attacks_triggers`` announces the other
            # half of. Here, in the bare announcement, because CR 509.3a is
            # this loop's count: once for the creature that blocks, however
            # many attackers it is blocking.
            emit(
                self, "matching_creature_attacks_or_blocks",
                subject=blocker,
                event_subject_permanent_id=blocker.permanent_id,
                event_subject_controller=self.controller_index_of(blocker),
            )
            for _attacker_idx, attacker in blocked:
                found = blocked_by.setdefault(
                    attacker.permanent_id, (attacker, [])
                )
                found[1].append(blocker)
        for attacker, blockers in blocked_by.values():
            emit(
                self, "matching_creature_becomes_blocked",
                subject=attacker,
                combatant_permanent_id=attacker.permanent_id,
                blocked_permanent_ids=[perm.permanent_id for perm in blockers],
                event_subject_permanent_id=attacker.permanent_id,
                event_subject_controller=self.controller_index_of(attacker),
                pair_announcement=False,
            )

    def _fire_delayed_becomes_blocked_triggers(
        self, controller_index: int, assignments: dict[int, list[int]]
    ) -> None:
        """"When **that creature** becomes blocked this turn, …" (Barreling
        Attack.)

        The delayed twin of the printed becomes-blocked scan above, and its own
        pass for that scan's stated reason: a delayed ability belongs to no
        permanent, so no ``effective_card`` scan can reach it.

        Announced **once per attacker**, which is CR 509.3c's reading — the
        creating spell's sentence names no blocker back, so there is nothing for
        a per-blocker firing to be about, and a creature blocked by three would
        otherwise take the bonus three times. The entry answers only for the
        attacker it was bound to; `DelayedTrigger.matches` is what checks that.
        """
        announced: set[int] = set()
        for _blocker_idx, _blocker, blocked in self._resolved_block_pairs(
            controller_index, assignments
        ):
            for _attacker_idx, attacker in blocked:
                if attacker.permanent_id in announced:
                    continue
                announced.add(attacker.permanent_id)
                fire_delayed_triggers(
                    self, "bound_permanent_becomes_blocked", subject=attacker,
                )

    def _fire_delayed_block_pair_triggers(
        self, controller_index: int, assignments: dict[int, list[int]]
    ) -> None:
        """The *becomes blocked* half of ``source_blocks_or_blocked_by``.

        The mirror of the announcement inside ``_fire_creature_blocks_triggers``
        with the two ends of the pair swapped: there the watched object is the
        blocker and the agent the attacker it blocked, here the watched object
        is the attacker and the agent each creature that blocked it (CR 509.3d).
        Its own pass rather than a branch of the printed scan beside it, for the
        reason ``_fire_delayed_block_triggers`` gives: a delayed ability belongs
        to no permanent, so no ``effective_card`` scan can reach it.
        """
        for _blocker_idx, blocker, blocked in self._resolved_block_pairs(
            controller_index, assignments
        ):
            for _attacker_idx, attacker in blocked:
                # The joined event (Goblin Flotilla) and its attacking half on
                # its own (Zombie Boa: "whenever this creature **becomes
                # blocked by** a creature of that color this turn"). An entry
                # is armed under exactly one of the two names, so announcing
                # both wakes each ability once.
                for event in (
                    "source_blocks_or_blocked_by", "source_becomes_blocked_by",
                ):
                    fire_delayed_triggers(
                        self, event,
                        subject=attacker, agent=blocker,
                        trigger_context={
                            "blocked_permanent_ids": [blocker.permanent_id],
                        },
                    )

    # `_apply_temporary_buff` and `_apply_flanking` were here, and both are
    # gone for one reason. CR 702.25a defines flanking as a triggered ability,
    # so it now compiles to one (`engine/flanking.py`) and reaches the stack
    # through the becomes-blocked dispatcher above — exactly the move rampage
    # made a set earlier, and for the same three defects: applied inline it
    # happened at *declaration* rather than on resolution (so nothing could be
    # responded to and CR 509.3f's fixed set was read too early), it applied one
    # -1/-1 however many instances the creature had (CR 702.25b), and it walked
    # the block map by battlefield index, which a removal renumbers. The old
    # docstring said flanking stayed because "the engine has no *card* for" it;
    # Mirage prints ten, plus an Aura that grants it and an enchantment that
    # takes it away, so the reason expired.
