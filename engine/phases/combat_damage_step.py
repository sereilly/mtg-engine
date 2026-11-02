from __future__ import annotations

"""Combat damage step (CR 510).

Resolves combat damage, including the separate first-strike/double-strike
damage step (CR 510.4), trample, deathtouch, lifelink and protection. Where
each point goes — who assigns, what a division may say, the defending
player's banding assignment (CR 702.22j/k), the "as though it weren't
blocked" announcement, the automatic assignment and the band/blocker lookups
— is ``combat_damage_assignment``'s mixin, composed onto ``Game`` beside this
one; this module runs the passes and deals what they recorded.

**The step is in two halves, and the seam matters.** Assignment (CR 510.1) works
out where every point goes and can be *refused* — a negative amount, a trampler
holding back lethal — so it deals nothing while it can still say no. Dealing (CR
510.2) then runs the recorded events through CR 120.4 and can be *suspended*:
any one of them may stop to ask the affected player which effect applies to it
first (CR 616.1e). So the dealing half is a chain of resumable loops
(``engine/resumption.py``) rather than plain ``for`` statements, and this step's
own tail — the lifelink gain, the state-based actions, the log, and the
``combat_first_strike_done`` / ``combat_damage_resolved`` flags that are the
step's idea of how far through it is — is the *last step of the outermost loop*
rather than code written after it. Work after a resumable loop does not run when
one of its steps suspends and nothing records it, which for this step would mean
a combat that half-happened and then declared itself resolved.

Both strike passes go through :meth:`resolve_all_combat_damage` for the same
reason: the "call it, and call it again if that was only the first-strike pass"
idiom every caller used to write is safe only while a pass cannot be
interrupted.
"""

from ..combat_assignment import (AS_THOUGH_UNBLOCKED_LOG,
                                 DEFENDER_ANNOUNCED_THIS_STEP,
                                 DIVIDED_AMONG_DEFENDERS_LOG,
                                 combat_damage_assigned_by,
                                 divided_announcement_refusal,
                                 still_legal_divisions)
from ..damage_events import deal_damage, lifelink_life_gained
from ..models import Permanent
from ..damage_redirects import end_simultaneous_redirects
from ..prevention.static import end_simultaneous_damage
from ..resumption import run_resumable


class CombatDamageStepMixin:
    def _participates_in_first_strike(self, permanent: Permanent) -> bool:
        """CR 510.4: deals its combat damage in the first-strike step."""
        return self._has_keyword(permanent, "first strike") or self._has_keyword(
            permanent, "double strike"
        )

    def _participates_in_second_strike(self, permanent: Permanent) -> bool:
        """CR 510.4: deals its combat damage in the second step — everything
        without first strike, and double strikers again."""
        return self._has_keyword(permanent, "double strike") or not (
            self._has_keyword(permanent, "first strike")
            or self._has_keyword(permanent, "double strike")
        )

    def _strikes_in_pass(
        self, permanent: Permanent, run_first_pass: bool, has_first_strike_pass: bool
    ) -> bool:
        """Whether this creature deals its combat damage in the pass being run.

        With no first-strike step there is only one pass and everything strikes
        in it, which is why "no first strike step" is not the same question as
        "is this the second one" (CR 510.4).
        """
        if run_first_pass:
            return self._participates_in_first_strike(permanent)
        if has_first_strike_pass:
            return self._participates_in_second_strike(permanent)
        return True

    def _first_strike_pass_pending(self) -> bool:
        """CR 510.4: whether this combat has a separate first-strike damage step.

        True if any attacking or blocking creature has first or double strike —
        which includes an *unblocked* first striker dealing to the player, not
        only creatures locked in a block.
        """
        attacker_controller = self.players[self.active_player_index]
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blockers = self._attacker_all_blockers(attacker_idx)
            if not blockers:
                if self._participates_in_first_strike(attacker):
                    return True
                continue
            defending_index = self.combat_attackers[attacker_idx]
            defender = (
                self.players[defending_index]
                if 0 <= defending_index < len(self.players)
                else None
            )
            if defender is None:
                continue
            for blocker_idx in blockers:
                if blocker_idx >= len(defender.battlefield):
                    continue
                blocker = defender.battlefield[blocker_idx]
                if self._participates_in_first_strike(
                    attacker
                ) or self._participates_in_first_strike(blocker):
                    return True
        return False

    def resolve_combat_damage(
        self,
        controller_index: int,
        attacker_damage: dict[int, dict[int, int]] | None = None,
        blocker_damage: dict[int, int] | None = None,
        blocker_damage_split: dict[int, dict[int, int]] | None = None,
        as_though_unblocked=None,
        divided_among_defenders=None,
    ) -> tuple[bool, str]:
        """One combat damage pass (:meth:`_deal_combat_damage_pass`), as one
        window for CR 603.3b (``putting_triggers_on_stack``): what the
        damage sets off — two creatures' "whenever this deals combat
        damage", the deaths it causes — goes on the stack together and its
        controller orders it. A pass that stops to ask (CR 616.1e) resumes
        outside the window, and what the resumed half sets off goes on one
        at a time, as everything did before. None once the game has ended
        (CR 104.1): a first-strike kill used to be followed by the regular
        step (life -1 -> -4). A multiplayer game goes on (CR 800.4a).
        """
        if self.is_game_over():
            return True, "the game is over (CR 104.1)"
        with self.putting_triggers_on_stack():
            return self._deal_combat_damage_pass(
                controller_index, attacker_damage, blocker_damage,
                blocker_damage_split, as_though_unblocked,
                divided_among_defenders,
            )

    def _deal_combat_damage_pass(
        self,
        controller_index: int,
        attacker_damage: dict[int, dict[int, int]] | None = None,
        blocker_damage: dict[int, int] | None = None,
        blocker_damage_split: dict[int, dict[int, int]] | None = None,
        as_though_unblocked=None,
        divided_among_defenders=None,
    ) -> tuple[bool, str]:
        """One combat damage pass — the first-strike step or the regular one
        (CR 510.4). Both halves of the step are here: work out the assignment
        (which can be refused), then deal it (which cannot).

        Every event in the dealing half can stop to ask the affected player
        which effect applies to it first (CR 616.1e), so that half is a chain of
        resumable loops and this step's own tail is the last step of the
        outermost one — see :mod:`engine.resumption`. Use
        :meth:`resolve_all_combat_damage` rather than calling this twice by
        hand: a pass that suspends leaves the other one recorded behind it.

        ``as_though_unblocked`` is the ``permanent_id`` of each attacker the
        active player announces is assigning its combat damage "as though it
        weren't blocked" — the offer *taken*, said out loud. Ids rather than
        the battlefield slots ``attacker_damage`` is keyed by, because this is
        a new channel and a slot is the address that moves. For an attacker
        with the offer, an entry in ``attacker_damage`` is the other answer and
        neither is the default; see :meth:`_assign_attacker_combat_damage`.

        ``attacker_damage`` names the attackers the active player is saying
        something about, and **each one it names is held to CR 510.1c**: all of
        the creature's combat damage, among the creatures blocking it
        (:meth:`_attacker_division_refusal`). An attacker it does not name
        keeps the engine's default — so ``None`` and ``{}`` are one
        announcement, "nothing to add". ``{}`` used to mean "every blocked
        attacker assigns nothing", which no rule lets a blocked creature do;
        it was the wire's way of making combat damage vanish.

        ``divided_among_defenders`` is Butcher Orgg's offer taken: attacker id →
        ``{"player": n, <creature id>: n, …}`` (``combat_assignment``'s gate).
        """
        if self.current_turn_phase != "combat" or self.current_step != "combat_damage":
            return False, "combat damage can only be resolved during combat_damage"
        if controller_index != self.active_player_index:
            return False, "only active player may assign combat damage"
        if self.combat_damage_resolved:
            return False, "combat damage already resolved"

        self._prune_combat_state()
        if not self.combat_attackers:
            self.combat_damage_resolved = True
            return True, "no attackers"

        attacker_controller = self.players[self.active_player_index]

        # None means "no explicit assignment given", and so does an attacker
        # the dict leaves out: each such attacker takes the engine's default
        # where it is read (``_assign_attacker_combat_damage``). That lets a
        # caller supply only blocker_damage (CR 702.22k), or only the one
        # attacker it has a decision about, and still have the rest deal
        # normally.
        if attacker_damage is None:
            attacker_damage = {}

        # CR 510.1 / CR 702.22j: the defending player's announcement for the
        # attackers whose damage *they* assign comes before this one is read.
        # A person has made theirs (their dialog holds the step until they
        # have); a seat nobody is sitting at makes its own here, for this
        # step — so it is there however the step came to be resolved, and
        # again for a double striker's second (CR 510.4).
        from ..ai_combat import announce_defender_assignments

        announce_defender_assignments(self)

        ok, message = self._validate_blocker_damage_split(blocker_damage_split)
        if not ok:
            return False, message

        unblocked_ids = frozenset(int(pid) for pid in (as_though_unblocked or ()))
        ok, message = self._validate_unblocked_announcement(attacker_damage, unblocked_ids)
        if not ok:
            return False, message
        divided_among = {
            int(pid): split for pid, split in (divided_among_defenders or {}).items()
        }
        refusal = divided_announcement_refusal(
            self, attacker_damage, unblocked_ids, divided_among
        )
        if refusal is not None:
            return False, refusal

        has_first_strike_pass = self._first_strike_pass_pending()
        run_first_pass = has_first_strike_pass and not self.combat_first_strike_done

        sent_past_blockers: list[Permanent] = []
        ok, message, attacker_damage_events, defender_damage_events = (
            self._assign_attacker_combat_damage(
                attacker_damage, run_first_pass, has_first_strike_pass,
                unblocked_ids, sent_past_blockers, divided_among,
            )
        )
        if not ok:
            return False, message
        # The attackers that assign in this pass. The defending player's
        # announcement for each of them (CR 702.22j) is used up by it: `finish`
        # marks them unannounced, so a second combat damage step asks that
        # player again (CR 510.4). By permanent, because the slots may have
        # moved by the time the step's tail runs.
        assigned_this_pass = [
            attacker
            for attacker_idx in sorted(self.combat_attackers)
            if (attacker := self.permanent_at(self.active_player_index, attacker_idx))
            is not None
            and self._strikes_in_pass(attacker, run_first_pass, has_first_strike_pass)
        ]
        # Said out loud, once the assignment has been accepted and before a
        # point of it is dealt. A blocked creature's damage arriving on a
        # player is the one thing in this step a table cannot work out from
        # the board — the defender watching an opponent's Thorn Elemental walk
        # past their blocker is owed the reason — and the client's damage
        # animation, which rebuilds the strikes from the *previous* state and
        # the log, had no way to know: it drew the attacker hitting its
        # blocker while the life total fell.
        for attacker in sent_past_blockers:
            self.log.append(
                f"{attacker.card.name} assigns its combat damage "
                f"{AS_THOUGH_UNBLOCKED_LOG}"
            )
        # …and a division among defending player and creatures (Butcher Orgg).
        for attacker in assigned_this_pass:
            if attacker.permanent_id in divided_among:
                self.log.append(f"{attacker.card.name} {DIVIDED_AMONG_DEFENDERS_LOG}")

        # ------------------------------------------------------------------
        # Nothing below can be refused, and everything below can be suspended.
        #
        # A damage event stops to ask the affected player which effect applies
        # first (CR 616.1e), and while it waits *nothing has happened* — so the
        # blockers, attackers and band members behind it have to be recorded
        # rather than run past, and so does this step's own tail. Each loop here
        # is therefore the last thing its function does, and the tail is
        # `finish`, a step of the outermost loop, rather than code written after
        # it. See engine/resumption.py.
        # ------------------------------------------------------------------

        # CR 702.15b: damage dealt by a source with lifelink gains its controller
        # that much life. Accumulated per controller and applied after all combat
        # damage is dealt this step (the life-gain events happen simultaneously).
        lifelink_gain: dict[int, int] = {}
        # Life lost is accumulated as the events are applied, not summed from the
        # recorded amounts: damage redirected or replaced away never reduced
        # anyone's life, and `finish` reconstructs the before-life total by
        # adding these numbers back.
        life_lost_by_defender: dict[int, int] = {}
        # Which of the attacking side's creatures dealt combat damage to each
        # player this step, for the batched "one or more … deal combat damage"
        # triggers below. Per *player*, because that is what the trigger is once
        # per — and by permanent, because the trigger's subject is a noun phrase
        # tested against each one.
        damagers_by_defender: dict[int, list] = {}
        report: dict[str, str | None] = {"message": None}

        def add_lifelink(controller_index: int, amount: int) -> None:
            if amount > 0:
                lifelink_gain[controller_index] = lifelink_gain.get(controller_index, 0) + amount

        def _dealt_to_creature(victim, source, lifelink_seat: int):
            """What follows one creature being dealt combat damage: fire its
            "dealt damage" triggers and tally the dealer's lifelink. (Deathtouch is stamped by _mark_damage_on_permanent
            itself — CR 702.2b is about damage, not combat damage.)

            Handed to `_mark_damage_on_permanent` as its `then` rather than run
            after it, so it travels with the event — CR 702.2b and 704.5h both
            need damage to have *been dealt*, and damage prevented in full never
            was (CR 615.6)."""

            def dealt(amount: int) -> None:
                if amount <= 0:
                    return
                # The damage-source record is written by
                # ``_mark_damage_on_permanent`` itself now — one seam for
                # combat and non-combat damage alike.
                self._fire_dealt_damage_triggers(victim, amount, combat=True)
                add_lifelink(lifelink_seat, lifelink_life_gained(source, amount))

            return dealt

        # -- blockers deal, by defender, by blocker, by band member ----------

        def one_band_member(defending_idx: int, blocker, entry) -> None:
            member_idx, amount = entry
            amount = int(amount)
            if amount <= 0 or not (0 <= member_idx < len(attacker_controller.battlefield)):
                return
            member = attacker_controller.battlefield[member_idx]
            self._mark_damage_on_permanent(
                member, amount, source=blocker, combat=True,
                then=_dealt_to_creature(member, blocker, defending_idx), asks=True,
            )

        def one_blocker(defending_idx: int, entry) -> None:
            blocker_idx, attacker_idxs = entry
            defender = self.players[defending_idx]
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                return
            if not attacker_idxs:
                return
            # CR 702.22j/k: an explicit division of this blocker's damage among the
            # band members it blocks (validated above) wins over the single-target
            # default. Each portion is dealt separately, so each is its own CR
            # 120.4 event and protection (CR 702.16e) is asked of each.
            # Falls back to the defender's pre-committed CR 510.1d division for a
            # creature blocking multiple attackers (Two-Headed Giant of Foriys).
            split = (blocker_damage_split or {}).get(blocker_idx)
            if split is None:
                split = self.combat_multiblock_damage.get(blocker_idx)
            if split:
                blocker = defender.battlefield[blocker_idx]
                if combat_damage_assigned_by(blocker) <= 0:
                    return
                if not self._strikes_in_pass(blocker, run_first_pass, has_first_strike_pass):
                    return
                run_resumable(
                    self,
                    sorted(split.items()),
                    lambda member: one_band_member(defending_idx, blocker, member),
                )
                return
            # A blocker deals its combat damage to one of the creatures it blocks
            # (CR 510.1c, defender's choice; default the first). A creature blocking
            # several attackers (Two-Headed Giant of Foriys) still deals once.
            attacker_idx = attacker_idxs[0]
            # CR 702.22k: a blocker blocking a band (which always contains a creature
            # with banding) deals its damage where the *active* player chooses among
            # the band members it blocks. Also lets the defender pick which blocked
            # attacker a multi-block creature damages.
            band = self._attacker_band(attacker_idx)
            if blocker_damage and blocker_idx in blocker_damage:
                chosen = blocker_damage[blocker_idx]
                allowed = chosen in attacker_idxs or (band and chosen in band)
                if allowed and 0 <= chosen < len(attacker_controller.battlefield):
                    attacker_idx = chosen
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                return
            blocker = defender.battlefield[blocker_idx]
            attacker = attacker_controller.battlefield[attacker_idx]
            blocker_assigns = combat_damage_assigned_by(blocker)
            if blocker_assigns <= 0:
                return
            if not self._strikes_in_pass(blocker, run_first_pass, has_first_strike_pass):
                return
            self._mark_damage_on_permanent(
                attacker, blocker_assigns, source=blocker, combat=True,
                then=_dealt_to_creature(attacker, blocker, defending_idx), asks=True,
            )

        def one_defenders_blockers(entry) -> None:
            defending_idx, blocker_map = entry
            if defending_idx < 0 or defending_idx >= len(self.players):
                return
            run_resumable(
                self,
                sorted(blocker_map.items()),
                lambda blocker: one_blocker(defending_idx, blocker),
            )

        def blockers_deal() -> None:
            run_resumable(self, sorted(self.combat_blockers.items()), one_defenders_blockers)

        # -- attackers deal to the creatures blocking them -------------------

        def one_blocker_is_hit(entry) -> None:
            defending_idx, blocker_idx, damage, a_idx = entry
            if defending_idx >= len(self.players):
                return
            defending_player = self.players[defending_idx]
            if blocker_idx < 0 or blocker_idx >= len(defending_player.battlefield):
                return
            blocker_perm = defending_player.battlefield[blocker_idx]
            source_attacker = (
                attacker_controller.battlefield[a_idx]
                if 0 <= a_idx < len(attacker_controller.battlefield)
                else None
            )
            self._mark_damage_on_permanent(
                blocker_perm, damage, source=source_attacker, combat=True,
                then=_dealt_to_creature(
                    blocker_perm, source_attacker, self.active_player_index
                ),
                asks=True,
            )

        def attackers_deal_to_blockers() -> None:
            run_resumable(self, attacker_damage_events, one_blocker_is_hit)

        # -- attackers deal to the players they are attacking ----------------

        def one_defender_is_hit(entry) -> None:
            """Each recorded event is run through CR 120.4 here, not where it was
            recorded. That is what makes several attackers work: an effect that
            caps the life loss sees the total the previous attacker left behind,
            which is 616.1f's re-check falling out of the placement. Shields,
            redirects (Veteran Bodyguard) and the life floor are all one sequence
            in engine/damage_events.py — the recorded amount is raw."""
            defending_idx, damage, source_attacker, attacked_walker_id = entry
            if defending_idx < 0 or defending_idx >= len(self.players):
                return
            if attacked_walker_id is not None:
                # The creature is attacking a planeswalker (CR 508.1b). Damage
                # goes to the walker — removing loyalty (CR 120.3c) — and to
                # nothing at all if it has left the battlefield (CR 510.1b).
                walker = self.permanent_by_id(attacked_walker_id)
                if walker is None:
                    return
                self._mark_damage_on_permanent(
                    walker, damage, source=source_attacker, combat=True,
                    then=_dealt_to_creature(
                        walker, source_attacker, self.active_player_index
                    ),
                    asks=True,
                )
                return
            defender = self.players[defending_idx]

            def hit() -> None:
                # `hit` is its own restart: the whole event *and* everything this
                # step does with it re-runs when the answer arrives, which is why
                # none of the consequences below sit outside it.
                outcome = deal_damage(
                    self,
                    {
                        "recipient": defender,
                        "amount": damage,
                        "source": source_attacker,
                        "combat": True,
                    },
                    restart=hit,
                )
                if outcome.suspended or outcome.dealt <= 0:
                    return
                defender.life -= outcome.result
                life_lost_by_defender[defending_idx] = (
                    life_lost_by_defender.get(defending_idx, 0) + outcome.result
                )
                # CR 702.15b reads the damage *dealt*, which is why lifelink is
                # tallied here rather than where the event was recorded: a result
                # replacement (Ali from Cairo) lowers the life lost without lowering
                # the damage, and the two numbers only exist together at this point.
                add_lifelink(
                    self.active_player_index,
                    lifelink_life_gained(source_attacker, outcome.dealt),
                )
                # CR 903.10a: combat damage from a commander is tallied per
                # commander for the whole game. Here rather than at the event's
                # recording, for the reason lifelink is: the rule counts the
                # damage *dealt* (CR 120.4b), and a result replacement (Ali from
                # Cairo) lowers the life lost without lowering that.
                self.record_commander_combat_damage(
                    defender, source_attacker, outcome.dealt
                )
                self._on_player_dealt_damage(defender, outcome.dealt, source_attacker)
                # Eye for an Eye: combat damage counts too — the attacker's
                # controller takes the same amount. Applied here rather than by
                # routing through _deal_damage_to_player, which would run the event
                # a second time.
                self._apply_mirror_damage(defender, outcome.dealt, source_attacker)
                # "…deals damage to a player/opponent" (Hypnotic Specter) is
                # announced by `damage_events._announce`, from inside the
                # `deal_damage` call above — the one seam every damage event
                # passes through, which is why there is nothing to fire here.
                if source_attacker is not None:
                    # The delayed ones (Subira) belong to no permanent, so no
                    # battlefield scan can find them and they keep their own
                    # site (CR 603.7).
                    self._fire_delayed_combat_damage_triggers(
                        source_attacker, defender, outcome.dealt
                    )
                    # "Whenever **one or more** … deal combat damage to a
                    # player" is one trigger however many creatures dealt it, so
                    # the pairs are recorded here and fired once each at the end
                    # of the step — the per-attacker call above cannot batch
                    # what it is called once per attacker for.
                    if outcome.dealt > 0:
                        damagers_by_defender.setdefault(
                            self.players.index(defender), []
                        ).append(source_attacker)

            hit()

        def attackers_deal_to_players() -> None:
            run_resumable(self, defender_damage_events, one_defender_is_hit)

        # -- the step's own tail, as its last step ---------------------------

        def finish() -> None:
            # The batched "one or more … deal combat damage to a player"
            # triggers, once per player damaged (CR 603.3: the ability triggers
            # once however many creatures dealt the damage). Fired before the
            # state-based check below for the same reason every other trigger in
            # this step is: they go on the stack and resolve in the priority
            # window after it.
            self._fire_batched_combat_damage_triggers(damagers_by_defender)

            # This step's damage is dealt, so what the defending player
            # announced for it has been used (see `assigned_this_pass`).
            for attacker in assigned_this_pass:
                attacker.metadata.pop(DEFENDER_ANNOUNCED_THIS_STEP, None)
            # …and so is this step's simultaneous dealing (CR 510.2): a
            # Phantom that paid one counter for being blocked by two creatures
            # pays again in the next step, not again in this one.
            end_simultaneous_damage(self)
            # …and a shared "next time" one of its chunks opened (Glarecaster).
            end_simultaneous_redirects(self)

            # CR 702.15b: apply lifelink life gain for damage dealt this step.
            for controller_index, amount in lifelink_gain.items():
                if 0 <= controller_index < len(self.players):
                    self._gain_life(self.players[controller_index], amount, source_name="lifelink")

            # Written before the state-based check, so a loss follows its damage.
            if sum(life_lost_by_defender.values()) > 0:
                for defending_idx, damage in sorted(life_lost_by_defender.items()):
                    if not (0 <= defending_idx < len(self.players)) or damage <= 0:
                        continue
                    defender = self.players[defending_idx]
                    self.log.append(
                        f"{defender.name} took {damage} combat damage (life: {defender.life + damage} → {defender.life})"
                    )

            self._check_after_turn_based_actions()
            self._prune_combat_state()

            if run_first_pass:
                self.combat_first_strike_done = True
                self.log.append("Resolved first strike combat damage")
                report["message"] = "resolved first strike combat damage"
                return

            self.combat_damage_resolved = True
            self.log.append("Resolved combat damage")
            report["message"] = "resolved combat damage"

        run_resumable(
            self,
            [blockers_deal, attackers_deal_to_blockers, attackers_deal_to_players, finish],
            lambda step: step(),
        )
        # `finish` is what writes the message, so an absent one means the step
        # stopped part-way; the answer comes back for the rest of it.
        return True, report["message"] or "combat damage is waiting on a choice (CR 616.1e)"

    def resolve_all_combat_damage(
        self,
        controller_index: int,
        attacker_damage: dict[int, dict[int, int]] | None = None,
        blocker_damage: dict[int, int] | None = None,
        blocker_damage_split: dict[int, dict[int, int]] | None = None,
        as_though_unblocked=None,
        divided_among_defenders=None,
    ) -> tuple[bool, str]:
        """Every combat damage pass this combat still owes (CR 510.4).

        One pass when nothing has first strike, two when something does. That
        "call it, and call it again if it was only the first-strike pass" used to
        live at each caller, which was safe only while nothing could interrupt a
        pass: a first-strike pass that suspends leaves ``combat_damage_resolved``
        False, so the caller's second call would have re-run the *first* strike
        rather than waiting for it to finish. As a resumable loop the second pass
        is recorded behind the first instead, and runs once the answer arrives.
        """
        report: dict[str, tuple[bool, str]] = {}
        progress = {"first_step_dealt": False, "refused": False}
        active = self.active_player_index
        in_step = (
            self.current_turn_phase == "combat"
            and self.current_step == "combat_damage"
            and controller_index == active
            and not self.combat_damage_resolved
        )
        divided = {
            int(pid): split for pid, split in (divided_among_defenders or {}).items()
        }

        # One announcement, two steps. ``attacker_damage`` is keyed by
        # battlefield slot and says how much goes to which blocker *as the
        # board stands now*; the first-strike step can change the board under
        # it — a blocker dies and every later slot moves down, or the creature
        # it divided among is simply gone. So the announcement is remembered by
        # permanent, and restated for the second step from what is still true
        # of it (`restated` below).
        remembered: list[tuple[Permanent, list[tuple[Permanent | None, int]]]] = []
        if in_step and attacker_damage:
            self._prune_combat_state()
            for attacker_idx, split in attacker_damage.items():
                attacker = self.permanent_at(active, attacker_idx)
                defending_index = self.combat_attackers.get(int(attacker_idx))
                if attacker is None or defending_index is None:
                    continue
                remembered.append((
                    attacker,
                    [
                        (self.permanent_at(defending_index, blocker_idx), int(amount))
                        for blocker_idx, amount in (split or {}).items()
                    ],
                ))
            # CR 510.1e checks an assignment whole before any of it is dealt.
            # With two steps in one call that has to be asked here: the first
            # step examines only the creatures that strike in it, so an illegal
            # division for an ordinary attacker would be found after the first
            # strikers had dealt their damage. Recording, and dealing nothing.
            if self._first_strike_pass_pending() and not self.combat_first_strike_done:
                unblocked_ids = frozenset(int(pid) for pid in (as_though_unblocked or ()))
                ok, message = self._validate_unblocked_announcement(
                    attacker_damage, unblocked_ids
                )
                if ok:
                    ok, message, _to_blockers, _to_players = (
                        self._assign_attacker_combat_damage(
                            attacker_damage, False, True, unblocked_ids,
                            divided_among=divided,
                        )
                    )
                if not ok:
                    return False, message
        if (
            in_step and divided and not attacker_damage
            and self._first_strike_pass_pending() and not self.combat_first_strike_done
        ):
            # A division alone, checked whole before first strikers deal (CR 510.1e).
            self._prune_combat_state()
            ok, message, _to_blockers, _to_players = self._assign_attacker_combat_damage(
                {}, False, True, frozenset(), divided_among=divided,
            )
            if not ok:
                return False, message

        def restated() -> dict[int, dict[int, int]]:
            """The announcement, as it reads on the board the first-strike step
            left. Each attacker it named is still named — an entry is how an
            attacker with "as though it weren't blocked" says no, and dropping
            one would turn that no into a yes — with its division carried over
            where that is still a division of all its damage among the
            creatures still blocking it, and the default among them where it is
            not (CR 510.4: the second step is assigned afresh; this caller
            asked not to be stopped for it)."""
            second: dict[int, dict[int, int]] = {}
            for attacker, shares in remembered:
                attacker_idx = (
                    self.battlefield_index_of(attacker)
                    if self.controls(active, attacker)
                    else None
                )
                if attacker_idx is None or attacker_idx not in self.combat_attackers:
                    continue
                defending_index = self.combat_attackers[attacker_idx]
                division: dict[int, int] = {}
                for blocker, amount in shares:
                    if blocker is None or not self.controls(defending_index, blocker):
                        continue
                    blocker_idx = self.battlefield_index_of(blocker)
                    if blocker_idx is not None:
                        division[blocker_idx] = amount
                if self._attacker_division_refusal(attacker_idx, division) is not None:
                    division = self._default_attacker_division(attacker_idx)
                second[attacker_idx] = division
            return second

        def strike_pass() -> None:
            if self.combat_damage_resolved or progress["refused"]:
                return
            assignment = attacker_damage
            if progress["first_step_dealt"] and attacker_damage:
                assignment = restated()
            is_first_step = (
                in_step
                and not self.combat_first_strike_done
                and self._first_strike_pass_pending()
            )
            result = self.resolve_combat_damage(
                controller_index,
                attacker_damage=assignment,
                blocker_damage=blocker_damage,
                blocker_damage_split=blocker_damage_split,
                as_though_unblocked=as_though_unblocked,
                # Butcher Orgg's divisions, restated for a second step (CR 510.4).
                divided_among_defenders=(
                    still_legal_divisions(self, divided)
                    if progress["first_step_dealt"] else divided
                ),
            )
            report["last"] = result
            if not result[0]:
                # A refused assignment deals nothing (CR 510.1e); running the
                # other pass would only ask the same question again.
                progress["refused"] = True
            elif is_first_step:
                progress["first_step_dealt"] = True

        run_resumable(self, [strike_pass, strike_pass], lambda step: step())
        return report.get("last", (True, "combat damage already resolved"))
