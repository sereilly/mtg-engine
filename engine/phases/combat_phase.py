from __future__ import annotations

"""Combat phase (CR 506–511).

This module holds the phase-level combat machinery shared across the five combat
steps: stepping through the steps (``advance_combat_phase`` / ``_enter_combat_step``),
combat-state bookkeeping (``_reset_combat_state`` / ``_prune_combat_state`` /
``get_combat_state``), legality probes used to auto-skip empty declaration steps,
and the "attacking/blocking alone" queries. The per-step turn-based actions live
in the sibling step modules (``beginning_of_combat_step``, ``declare_attackers_step``,
``declare_blockers_step``, ``combat_damage_step``, ``end_of_combat_step``).
"""

from ..events import emit
from ..models import Permanent
from ..resumption import run_resumable


class CombatPhaseMixin:
    def combat_defending_players(self) -> set[int]:
        """CR 802.2: every player currently a defending player this combat — i.e.
        named as the target of at least one declared attacker. Empty before
        attackers are declared."""
        return set(self.combat_attackers.values())

    def _resolve_defending_player_index(self) -> int | None:
        """The single-scalar ``combat_defending_player_index`` convenience value
        (kept for 2-player back-compat and simple single-target UI reads).

        In a 2-player game this is always unambiguous — the other seat — even
        before any attacker has been declared, matching every existing 2-player
        caller/test that reads it at any point during combat. In FFA (3+
        players) it's only meaningful once exactly one distinct defender is
        under attack; the authoritative source there is
        ``combat_defending_players()``."""
        if len(self.players) == 2:
            return 1 - self.active_player_index
        defenders = self.combat_defending_players()
        return next(iter(defenders)) if len(defenders) == 1 else None

    def _pending_block_declarer(self) -> int | None:
        """CR 802.4: the next defending player, in APNAP order starting with the
        player after the active player, who still needs to declare blocks (or be
        auto-skipped) this declare-blockers step. None once every defender has."""
        defenders = self.combat_defending_players()
        if not defenders:
            return None
        n = len(self.players)
        for offset in range(1, n + 1):
            idx = (self.active_player_index + offset) % n
            if idx in defenders and idx not in self.combat_blockers_declared_by:
                return idx
        return None

    def _has_any_legal_attacker(self, attacker_index: int, defender_index: int) -> bool:
        if attacker_index < 0 or attacker_index >= len(self.players):
            return False
        if defender_index < 0 or defender_index >= len(self.players):
            return False
        if attacker_index == defender_index:
            return False

        for attacker in self.controlled_by(attacker_index):
            if not attacker.is_creature:
                continue
            if attacker.tapped:
                continue
            if self.can_attack(attacker, defender_index):
                return True
        return False

    def _has_any_legal_block(self, defender_index: int) -> bool:
        if defender_index < 0 or defender_index >= len(self.players):
            return False
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            return False

        self._prune_combat_state()
        if not self.combat_attackers:
            return False

        attacker_controller = self.players[self.active_player_index]
        for blocker in self.controlled_by(defender_index):
            if not blocker.is_creature or blocker.tapped:
                continue
            # CR 802.4a: this defender can only block attackers aimed at them.
            for attacker_idx, defending_idx in self.combat_attackers.items():
                if defending_idx != defender_index:
                    continue
                if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                    continue
                attacker = attacker_controller.battlefield[attacker_idx]
                if self._can_block_attacker(blocker, attacker):
                    return True
        return False

    def _combat_awaits_an_answer(self) -> bool:
        """Whether a decision is owed that the combat rail must wait for.

        CR 608.2 / CR 117.3b, the rule ``Game.waiting_prompt`` states and the
        priority rail already honours: while a prompt is owed the resolution
        that armed it is not finished, so no step advances and nobody receives
        priority. The combat rail did not ask. ``_resolve_priority_window``
        below returns with the held object still on the stack — that is its
        documented behaviour — and the next two lines closed the step and
        entered the following one anyway, so a "you may" offered in the
        declare-blockers step was still on screen when the combat damage step
        had already dealt its damage. Round 23 reverted Floral Spuzzem over
        exactly this and recorded the reason.

        The seat test is what keeps a headless or AI run identical: those seats
        never answer a prompt themselves — their defaults are drained by
        ``auto_resolve_pending_choices`` *after* the step — so blocking on one
        would stop the rail with nothing left to unblock it. It is the same
        question ``_resolve_priority_window`` asks before pausing at all.
        """
        waiting = self.waiting_prompt()
        return waiting is not None and waiting.player_index in self.interactive_seats

    def advance_combat_phase(self, allow_damage_skip: bool = True) -> None:
        # allow_damage_skip: when a player has flagged the combat-damage step on the
        # phase rail (hold priority), the caller passes False so the engine enters
        # the step and opens a priority window there instead of auto-resolving damage
        # and skipping straight to end-of-combat.
        if self._combat_awaits_an_answer():
            return
        combat_steps = list(self._phase_steps("combat"))
        if self.current_turn_phase != "combat":
            self._enter_combat_step(combat_steps[0])
            return

        try:
            idx = combat_steps.index(self.current_step)
        except ValueError:
            self._enter_combat_step(combat_steps[0])
            return

        if self.current_step == "end_of_combat":
            self.end_combat(step_already_started=True)
            self._enter_main_phase(precombat=False)
            return
        if self.current_step == "declare_attackers" and not self.combat_attackers_locked:
            # CR 802.2: under attack-multiple-players there's no single pre-picked
            # defender to check before attackers are even declared — each attacker
            # names its own when declared. The active player just needs SOME legal
            # attacker against ANY living opponent for this step not to auto-skip.
            living_opponents = self.opponents_of(self.active_player_index)
            if any(
                self._has_any_legal_attacker(self.active_player_index, opp)
                for opp in living_opponents
            ):
                return

            self.combat_attackers = {}
            self.combat_blockers = {}
            self.combat_attackers_locked = True
            self.combat_blockers_locked = True
            self._prune_combat_state()
            attacker_name = self.players[self.active_player_index].name
            self.log.append(f"{attacker_name} has no valid attackers; declare attackers step skipped")
        # Camouflage replaces the declare-blockers step: the defending player
        # divides their creatures into piles (assign_camouflage_piles), which are
        # then matched to attackers at random. Wait for that choice like a normal
        # blocker declaration; with no untapped creatures there is nothing to
        # divide, so resolve the (empty) piles immediately. Camouflage's spell text
        # names one specific defending player, so this stays single-defender.
        if (
            self.current_step == "declare_blockers"
            and not self.combat_blockers_locked
            and self.combat_attackers
            and self.is_camouflage_active()
        ):
            defender_index = self.combat_defending_player_index
            if defender_index is None:
                defender_index = next(iter(self.combat_defending_players()), None)
            if isinstance(defender_index, int):
                if any(p.is_creature and not p.tapped for p in self.controlled_by(defender_index)):
                    return  # awaiting the defender's pile assignment
                self.resolve_camouflage_blocking(defender_index)
            return
        if self.current_step == "declare_blockers" and not self.combat_blockers_locked:
            # CR 802.4: each defending player declares blocks in APNAP order,
            # starting with the player after the active player. Auto-skip any
            # defender (in turn) who has no legal blocks; stop and wait once we
            # reach one who has a real choice to make.
            while True:
                pending = self._pending_block_declarer()
                if pending is None:
                    self.combat_blockers_locked = True
                    self._prune_combat_state()
                    break
                if self._has_any_legal_block(pending):
                    return
                self.combat_blockers_declared_by.add(pending)
                self._prune_combat_state()
                defender_name = self.players[pending].name
                self.log.append(f"{defender_name} has no valid blockers; declare blockers step skipped")
        if self.current_step == "declare_blockers" and self.combat_blockers_locked and not self.combat_attackers:
            defender_index = self.combat_defending_player_index
            if isinstance(defender_index, int) and 0 <= defender_index < len(self.players):
                defender_name = self.players[defender_index].name
                self.log.append(f"{defender_name} has no valid blockers; declare blockers step skipped")
            else:
                self.log.append("No attackers; declare blockers step skipped")
        if self.current_step == "combat_damage" and not self.combat_damage_resolved:
            return  # Awaiting manual damage assignment

        if self.current_step == "declare_attackers":
            self.log.append(
                f"Declare attackers step complete: {len(self.combat_attackers)} attacker(s) declared"
            )
        if self.current_step == "declare_blockers":
            total_blockers = sum(len(m) for m in self.combat_blockers.values())
            self.log.append(
                f"Declare blockers step complete: {total_blockers} blocker(s) declared"
            )
            # CR 509.1h: an attacking creature becomes unblocked as blocks are
            # declared, and "whenever this creature attacks and isn't blocked"
            # triggers then — **in this step**, so the ability resolves in the
            # priority window below, before any combat damage is assigned.
            #
            # It used to fire from inside `resolve_combat_damage`, described
            # there as "the reliable choke point every combat flow passes
            # through". It was reliable and it was one step too late: Floral
            # Spuzzem's "if you do, this creature assigns no combat damage this
            # turn" was set *after* the damage it is printed to stop, so the
            # card destroyed an artifact and hit for two anyway.
            #
            # Here instead, because this line is the choke point *for the
            # declaration*: a declaration, an auto-skipped defender with no
            # legal block, and a Camouflage resolution all reach it, and none
            # of them reaches the other two's code.
            self._fire_unblocked_attack_triggers()

        # Close current combat step, then enter the next one.
        if self._receives_priority(self.current_step):
            self._resolve_priority_window()
            # The window may have stopped part-way through a resolution
            # (CR 608.2). Closing the step now would run the rest of combat
            # around an unanswered question — see ``_combat_awaits_an_answer``.
            if self._combat_awaits_an_answer():
                return
        self._on_step_or_phase_end("combat", self.current_step)

        next_idx = idx + 1
        if next_idx >= len(combat_steps):
            self._enter_main_phase(precombat=False)
            return
        if combat_steps[next_idx] == "combat_damage":
            self.combat_damage_resolved = False
            self.combat_first_strike_done = False
        self._enter_combat_step(combat_steps[next_idx])

        # Auto-resolve and skip combat_damage when no manual assignment is needed.
        if combat_steps[next_idx] == "combat_damage" and not self._needs_manual_damage_assignment():
            auto = self._build_auto_damage_assignment()

            def deal_the_damage() -> None:
                self.resolve_all_combat_damage(self.active_player_index, attacker_damage=auto)

            def leave_the_damage_step() -> None:
                if not allow_damage_skip:
                    # A player flagged the combat-damage step (hold priority). Combat
                    # damage has been dealt as the turn-based action (CR 510.1c); leave a
                    # priority window open for the active player (CR 510.4) instead of
                    # resolving the stack through to end-of-combat, so the flagged player
                    # can respond. The next advance (once players pass) moves on normally.
                    if self._receives_priority("combat_damage"):
                        self.start_priority_window(self.active_player_index)
                    return
                if self._receives_priority("combat_damage"):
                    self._resolve_priority_window()
                self._on_step_or_phase_end("combat", "combat_damage")
                eoc_idx = next_idx + 1
                if eoc_idx >= len(combat_steps):
                    self._enter_main_phase(precombat=False)
                    return
                self._enter_combat_step(combat_steps[eoc_idx])

            # Leaving the step is the loop's *last step*, not work after it.
            # Combat damage can stop to ask the affected player which effect
            # applies first (CR 616.1e), and running on would open end of combat
            # while the damage that step exists to deal was still owed
            # (engine/resumption.py).
            run_resumable(self, [deal_the_damage, leave_the_damage_step], lambda step: step())
            return

    def _enter_combat_step(self, step: str) -> None:
        if step == "beginning_of_combat":
            self._reset_combat_state(clear_damage_marked=False)
        if step == "declare_attackers":
            self.combat_attackers_locked = False
            self.combat_blockers_locked = False
            self.combat_defending_player_index = self._resolve_defending_player_index()
            self._record_who_could_attack()
        if step == "declare_blockers":
            self.combat_blockers_locked = not bool(self.combat_attackers)
        self._set_phase_and_step("combat", step)
        self._on_step_or_phase_begin("combat", step)
        if step == "beginning_of_combat":
            # "At the beginning of combat on your turn" (CR 507.1) — scanned
            # over the active player's battlefield only, which is what the
            # narrowing means; the bare "at the beginning of combat" form
            # would scan every battlefield, and no shipped card uses it.
            emit(
                self, "combat_your_turn",
                players=[self.players[self.active_player_index]],
            )
        # CR 508.1 / 509.1: declaring attackers and declaring blockers are
        # turn-based actions that happen *before* any player receives priority,
        # so no spell or ability can be cast/activated during that assignment.
        # A priority window is opened only once the declaration is made — see
        # declare_attackers / declare_blockers, which grant the active player
        # priority afterward (CR 508.4 / 509.4). Every other combat step opens a
        # priority window immediately on entry.
        if step in ("declare_attackers", "declare_blockers"):
            self.clear_priority_window()
        elif self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def _record_who_could_attack(self) -> None:
        """Stamp every creature that *could* have been declared an attacker.

        "Destroy all untapped creatures that didn't attack this turn, **except
        for creatures that couldn't attack**" (Season of the Witch) asks a
        question no later reading of the board can answer: by the end step a
        creature may have untapped, lost defender, or had its restriction end.
        So the answer is frozen at CR 508.1's turn-based action, the moment the
        declaration is made — and it is taken here rather than in
        ``declare_attackers`` because that method is the *player's* action and
        may never be called, while this step always begins.

        Only the active player's creatures are asked. A creature nobody could
        have attacked with — an opponent's, on a turn that is not theirs —
        could not attack, which is exactly the exemption the card prints.
        """
        opponents = self.opponents_of(self.active_player_index)
        for permanent in self.controlled_by(self.active_player_index):
            if not self._is_creature(permanent):
                continue
            if any(self.can_attack(permanent, seat) for seat in opponents):
                permanent.metadata["could_attack_this_turn"] = True

    def _reset_combat_state(self, clear_damage_marked: bool) -> None:
        self.combat_attackers = {}
        self.combat_attacked_planeswalkers = {}
        self.combat_blockers = {}
        self.combat_blockers_declared_by = set()
        self.combat_bands = []
        self.combat_band_blocks = {}
        self.combat_banding_damage = {}
        self.combat_multiblock_damage = {}
        self.combat_left_right_active = False
        self.combat_left_right_defender_index = None
        self.combat_defender_piles = {}
        self.combat_attacker_piles = {}
        self.combat_defending_player_index = None
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = False
        self.combat_blockers_locked = False
        self.combat_unblocked_triggers_fired = False
        for permanent in self.all_permanents():
            permanent.attacking = False
            permanent.defending_player_index = None
            permanent.blocked = False
            permanent.blocking_attacker_controller = None
            permanent.blocking_attacker_index = None
            if clear_damage_marked:
                permanent.damage_marked = 0
        # Clearing attacking status can change dynamic P/T (e.g. Gaea's Liege
        # reverts from the defender's Forest count to its controller's).
        self._refresh_dynamic_creatures()

    def _prune_combat_state(self) -> None:
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            self._reset_combat_state(clear_damage_marked=False)
            return
        active = self.players[self.active_player_index]
        n = len(self.players)

        valid_attackers: dict[int, int] = {}
        for attacker_idx, defending_idx in self.combat_attackers.items():
            if not (0 <= defending_idx < n) or defending_idx == self.active_player_index:
                continue
            if attacker_idx < 0 or attacker_idx >= len(active.battlefield):
                continue
            attacker = active.battlefield[attacker_idx]
            # is_creature, not the printed type: pruning by printed type silently
            # removed animated lands (Kormus Bell / Living Lands) from combat
            # right after they were legally declared as attackers.
            if not attacker.is_creature:
                continue
            valid_attackers[attacker_idx] = defending_idx
        self.combat_attackers = valid_attackers

        # An attacker that left combat takes its planeswalker target with it.
        # The reverse is deliberately NOT pruned: a walker that left the
        # battlefield keeps its entry, because its attacker is still attacking
        # *it* — the creature assigns no combat damage (CR 510.1b) rather than
        # falling back to attacking the player (CR 506.4c).
        self.combat_attacked_planeswalkers = {
            idx: walker_id
            for idx, walker_id in self.combat_attacked_planeswalkers.items()
            if idx in self.combat_attackers
        }

        # Populated only when every remaining attacker shares one defender
        # (2-player back-compat / simple single-target UI reads); the authoritative
        # source of "who's under attack" is combat_defending_players().
        defenders_now = self.combat_defending_players()
        self.combat_defending_player_index = self._resolve_defending_player_index()
        self.combat_blockers_declared_by &= defenders_now

        # CR 702.22f: an attacking creature removed from combat is removed from its
        # band. Drop departed members; a band that falls below two members is no
        # longer a band (it leaves no banding interaction for the rest of combat).
        if self.combat_bands:
            pruned_bands = [
                [m for m in band if m in self.combat_attackers] for band in self.combat_bands
            ]
            self.combat_bands = [band for band in pruned_bands if len(band) >= 2]

        # combat_blockers is nested by defender (CR 802: 2+ defenders may each have
        # declared blocks in the same combat, and blocker battlefield indices are
        # only unambiguous within one defender's own battlefield).
        pruned_blockers: dict[int, dict[int, list[int]]] = {}
        for defending_idx, blocker_map in self.combat_blockers.items():
            if not (0 <= defending_idx < n):
                continue
            defender = self.players[defending_idx]
            kept_for_defender: dict[int, list[int]] = {}
            for blocker_idx, attacker_idxs in blocker_map.items():
                if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                    continue
                blocker = defender.battlefield[blocker_idx]
                if not blocker.is_creature:
                    continue
                # Keep only attackers still valid AND still aimed at this defender.
                kept = [
                    a for a in attacker_idxs
                    if self.combat_attackers.get(a) == defending_idx
                ]
                if kept:
                    kept_for_defender[blocker_idx] = kept
            if kept_for_defender:
                pruned_blockers[defending_idx] = kept_for_defender
        self.combat_blockers = pruned_blockers

        # Preserve "was ever blocked" state: once a creature is blocked it stays
        # blocked through the entire combat damage phase even if its blocker dies
        # (e.g. killed by first-strike damage in the first pass).
        was_blocked = {
            idx: perm.blocked
            for idx, perm in enumerate(active.battlefield)
            if perm.blocked
        }

        for permanent in self.all_permanents():
            permanent.attacking = False
            permanent.defending_player_index = None
            permanent.blocked = False
            permanent.blocking_attacker_controller = None
            permanent.blocking_attacker_index = None

        all_blocked_attacker_idxs: set[int] = {
            a for blocker_map in self.combat_blockers.values() for atks in blocker_map.values() for a in atks
        }
        for attacker_idx, defending_idx in self.combat_attackers.items():
            attacker = active.battlefield[attacker_idx]
            attacker.attacking = True
            attacker.defending_player_index = defending_idx
            attacker.blocked = was_blocked.get(attacker_idx, False) or attacker_idx in all_blocked_attacker_idxs

        for defending_idx, blocker_map in self.combat_blockers.items():
            defender = self.players[defending_idx]
            for blocker_idx, attacker_idxs in blocker_map.items():
                blocker = defender.battlefield[blocker_idx]
                blocker.blocking_attacker_controller = self.active_player_index
                # `blocking_attacker_index` holds a single representative attacker
                # (the first) for the common one-block case; multi-block uses
                # combat_blockers.
                blocker.blocking_attacker_index = attacker_idxs[0] if attacker_idxs else None

        # CR 702.22h: propagate band blocks (no-op when no bands were declared).
        # Recomputed here so the propagated "blocked" status survives every prune.
        self._apply_band_block_propagation()

        # Attacking/defending status can change a creature's power and toughness
        # (e.g. Gaea's Liege uses the defending player's Forests while attacking),
        # so recompute dynamic P/T now that combat flags have settled.
        self._refresh_dynamic_creatures()

    def get_combat_state(self) -> dict[str, object]:
        self._prune_combat_state()
        return {
            "defending_player_index": self.combat_defending_player_index,
            # CR 802: every player currently under attack (may be 2+ in FFA).
            "defending_player_indices": sorted(self.combat_defending_players()),
            "attackers": [
                {
                    "attacker_index": k,
                    "defending_player_index": v,
                    # CR 508.1b: present (as the walker's permanent_id) when this
                    # attacker is attacking a planeswalker rather than the player.
                    "attacked_planeswalker_id": self.combat_attacked_planeswalkers.get(k),
                }
                for k, v in sorted(self.combat_attackers.items())
            ],
            "blockers": [
                {"blocker_index": blocker_idx, "attacker_index": a, "defending_player_index": defending_idx}
                for defending_idx, blocker_map in sorted(self.combat_blockers.items())
                for blocker_idx, atks in sorted(blocker_map.items())
                for a in atks
            ],
            "damage_resolved": self.combat_damage_resolved,
            "first_strike_done": self.combat_first_strike_done,
            "attackers_locked": self.combat_attackers_locked,
            "blockers_locked": self.combat_blockers_locked,
            # Camouflage (cast during this turn's declare-attackers step): the
            # defender assigns piles instead of declaring blockers.
            "camouflage_active": self.is_camouflage_active(),
            # Banding (CR 702.22): declared attacking bands and the per-attacker
            # blockers added by band propagation (702.22h).
            "bands": [list(band) for band in self.combat_bands],
            "band_blocks": {k: list(v) for k, v in self.combat_band_blocks.items()},
            # Raging River (CR 702 left/right division). Exposed for the UI so it can
            # draw each creature's pile and rearrange the board into left/right sides.
            # ``defender_piles`` keys are battlefield indices of the defending player;
            # ``attacker_piles`` keys are battlefield indices of the active player.
            "left_right_active": self.combat_left_right_active,
            "left_right_defender_index": self.combat_left_right_defender_index,
            "defender_piles": {int(k): v for k, v in self.combat_defender_piles.items()},
            "attacker_piles": {int(k): v for k, v in self.combat_attacker_piles.items()},
            "defender_piles_locked": self.combat_left_right_defender_locked,
            "attacker_piles_locked": self.combat_left_right_attacker_locked,
        }

    def creature_attacking_alone(self, permanent: Permanent) -> bool:
        """CR 506.5: a creature is *attacking alone* if it's attacking but no
        other creatures are. Returns False if the permanent isn't itself
        attacking."""
        if not permanent.attacking:
            return False
        attacking = sum(1 for perm in self.all_permanents() if perm.attacking)
        return attacking == 1

    def creature_blocking_alone(self, permanent: Permanent) -> bool:
        """CR 506.5: a creature is *blocking alone* if it's blocking but no
        other creatures are. Returns False if the permanent isn't itself
        blocking."""
        if permanent.blocking_attacker_index is None:
            return False
        blocking = sum(
            1
            for perm in self.all_permanents()
            if perm.blocking_attacker_index is not None
        )
        return blocking == 1

    def creatures_blocking(self, permanent: Permanent) -> list[Permanent]:
        """Every creature currently blocking ``permanent`` — the one-way half of
        :meth:`creatures_in_combat_with` (Feint, The Wretched).

        One reader for the relation, because "blocking it" and "blocking or
        blocked by it" are the same combat maps asked in different directions;
        a second walk of ``combat_attackers`` would be a second opinion about
        who is blocking whom, and band-propagated blocks (CR 702.22h) are
        exactly the kind of thing one of the two copies would forget.

        Returned as Permanent objects rather than indices: a caller may act on
        this after something has left the battlefield and renumbered the slots.
        """
        blockers: list[Permanent] = []
        if not self.players:
            return blockers
        active = self.players[self.active_player_index]
        for attacker_idx, defending_idx in self.combat_attackers.items():
            if not (0 <= attacker_idx < len(active.battlefield)):
                continue
            if active.battlefield[attacker_idx] is not permanent:
                continue
            if not (0 <= defending_idx < len(self.players)):
                continue
            defender = self.players[defending_idx]
            for blocker_idx in self._attacker_all_blockers(attacker_idx):
                if not (0 <= blocker_idx < len(defender.battlefield)):
                    continue
                blocker = defender.battlefield[blocker_idx]
                if blocker is not permanent and not any(p is blocker for p in blockers):
                    blockers.append(blocker)
        return blockers

    def creatures_in_combat_with(self, permanent: Permanent) -> list[Permanent]:
        """Every creature currently *blocking or blocked by* ``permanent``
        (Abu Ja'far's death trigger). Resolved against the live combat maps —
        band-propagated blocks (CR 702.22h) included — and returned as
        Permanent objects, because callers capture this the moment the source
        leaves the battlefield and act on it later (CR 603.10 last-known
        information), after indices have shifted."""
        opponents: list[Permanent] = []

        def _add(perm: Permanent | None) -> None:
            if perm is not None and perm is not permanent and not any(p is perm for p in opponents):
                opponents.append(perm)

        active = self.players[self.active_player_index] if self.players else None
        # As an attacker: every creature blocking it — the one-way reader, so
        # the two questions cannot answer differently.
        for blocker in self.creatures_blocking(permanent):
            _add(blocker)
        # As a blocker: every attacker it's blocking.
        for defending_idx, blocker_map in self.combat_blockers.items():
            if not (0 <= defending_idx < len(self.players)):
                continue
            defender = self.players[defending_idx]
            for blocker_idx, attacker_idxs in blocker_map.items():
                if not (0 <= blocker_idx < len(defender.battlefield)):
                    continue
                if defender.battlefield[blocker_idx] is not permanent:
                    continue
                for attacker_idx in attacker_idxs:
                    if active is not None and 0 <= attacker_idx < len(active.battlefield):
                        _add(active.battlefield[attacker_idx])
        # Band-propagated blocks (CR 702.22h): this creature is treated as
        # blocking every band member its declared block extended to.
        for attacker_idx, blocker_idxs in self.combat_band_blocks.items():
            if active is None or not (0 <= attacker_idx < len(active.battlefield)):
                continue
            for defending_idx, blocker_map in self.combat_blockers.items():
                if not (0 <= defending_idx < len(self.players)):
                    continue
                defender = self.players[defending_idx]
                for blocker_idx in blocker_idxs:
                    if 0 <= blocker_idx < len(defender.battlefield) and (
                        defender.battlefield[blocker_idx] is permanent
                    ):
                        _add(active.battlefield[attacker_idx])
        return opponents
