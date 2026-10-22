from __future__ import annotations

"""Declare blockers step (CR 509).

The defending player declares blockers as a turn-based action. This module holds
the declaration (its CR 509.1c requirements, Lure's among them, checked as it is
made), what blocking costs (CR 509.1d–f), Camouflage's and Raging River's piles,
and the records a block leaves: band block propagation (CR 702.22h), a blocker
removed from combat, the block history. Block legality (``_can_block_attacker``
and its landwalk helper, the minimum and maximum blockers, what the board
compels to block) is ``block_legality.py``, and the triggers a declaration sets
off (Cockatrice, rampage, flanking) are ``block_triggers.py``; both are composed
onto ``Game`` directly after this.
"""

import random

from ..aura_restrictions import (attached_combat_restrictions,
                                 aura_restriction_active)
from ..combat_permissions import (MUST_BLOCK_ALL_UNTIL_EOT,
                                  MUST_BLOCK_ATTACKERS_UNTIL_EOT,
                                  MUST_BLOCK_UNTIL_EOT)
from ..combat_restrictions import declaration_tap_costs
from ..mana_payment import mana_cost_label, plan_payment
from ..subject_filters import subject_matches
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..turn_state import record_block_involvement


class DeclareBlockersStepMixin:
    def declare_blockers(
        self,
        controller_index: int,
        blocker_to_attacker: dict[int, int | list[int]],
        *,
        acting_index: int | None = None,
        _camouflage_resolution: bool = False,
        cost_permanent_ids: list[int] | None = None,
    ) -> tuple[bool, str]:
        """CR 509.1: *controller_index*'s declare-blockers turn-based action.

        ``cost_permanent_ids`` is CR 509.1d's choice — which creature a Hollow
        Warrior's block taps — by id, exactly as ``declare_attackers`` takes it
        for CR 508.1h. None is the default plan, unchanged.

        ``acting_index`` is who is *making the choices* (CR 509.1a), which is
        normally the defending player and is another seat while "You choose
        which creatures block this combat and how those creatures block"
        (Melee) is in effect. It defaults to the declarer, so every caller that
        does not know about the substitution keeps meaning what it meant.

        The gate is here rather than only in the web action because a
        restriction the engine does not enforce is one that works more often
        than the card allows: the substituted seat must be the one
        ``block_chooser_index`` names, and while Melee is out the *defender*
        may no longer declare their own blocks.
        """
        if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
            return False, "blockers can only be declared during declare_blockers"
        if acting_index is None:
            acting_index = controller_index
        # A Camouflage resolution is exempt because it is not a declaration at
        # all: the piles were matched at random (CR 509.1a is replaced
        # wholesale), so there is no choice for another seat to be making.
        chooser_index = self.block_chooser_index(controller_index)
        if acting_index != chooser_index and not _camouflage_resolution:
            if not (0 <= chooser_index < len(self.players)):
                return False, "only defending player may declare blockers"
            chooser = self.players[chooser_index]
            return False, f"{chooser.name} chooses which creatures block this combat"
        if self.combat_attackers:
            if controller_index not in self.combat_defending_players():
                return False, "only defending player may declare blockers"
        elif controller_index == self.active_player_index or not (0 <= controller_index < len(self.players)):
            # No attackers at all this combat: nobody is formally "a defending
            # player" yet (combat_defending_players() is empty), but any non-active
            # player may still submit a trivial no-op declaration — matching the
            # historical single-defender behavior where the (sole) opponent was
            # always considered the defending player even before any attack.
            return False, "only defending player may declare blockers"
        # Camouflage replaces the declare-blockers turn-based action: blocks come
        # from the defender's piles (assign_camouflage_piles / the random AI
        # fallback), never from a normal declaration.
        if self.is_camouflage_active() and not _camouflage_resolution and self.combat_attackers:
            return False, "Camouflage is active: divide your creatures into piles instead of declaring blockers"

        self._prune_combat_state()
        defender = self.players[controller_index]
        attacker_controller = self.players[self.active_player_index]
        # CR 802.4a: a defending player may only block attackers aimed at them.
        own_attackers = {
            idx for idx, defending_idx in self.combat_attackers.items()
            if defending_idx == controller_index
        }
        assignments: dict[int, list[int]] = {}
        resolved_attackers: dict[int, Permanent] = {}
        # The blockers this declaration names, collected as the loop below
        # resolves them. The set-level restrictions further down read *objects*
        # rather than re-reading the battlefield by index, for the reason the
        # attack side gives: an index is unstable, and this loop has the
        # permanent in hand already.
        resolved_blockers: dict[int, Permanent] = {}

        for blocker_idx, raw_attackers in blocker_to_attacker.items():
            # A blocker may be assigned one attacker (the common case) or several
            # (a creature that can block additional creatures).
            attacker_indices = raw_attackers if isinstance(raw_attackers, (list, tuple, set)) else [raw_attackers]
            attacker_indices = [int(a) for a in attacker_indices]
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                return False, "blocker index out of range"
            blocker = defender.battlefield[blocker_idx]
            resolved_blockers[blocker_idx] = blocker
            if not blocker.is_creature:
                return False, "only creatures can block"
            if blocker.tapped:
                return False, f"{blocker.card.name} is tapped"
            if len(set(attacker_indices)) > self._max_blocks_for(blocker):
                return False, f"{blocker.card.name} cannot block that many creatures"
            for attacker_idx in dict.fromkeys(attacker_indices):  # dedupe, keep order
                if attacker_idx not in own_attackers:
                    return False, "blocker assigned to a creature not attacking this player"
                attacker = attacker_controller.battlefield[attacker_idx]
                resolved_attackers[attacker_idx] = attacker
                if not self._can_block_attacker(blocker, attacker):
                    return False, f"{blocker.card.name} cannot block {attacker.card.name}"
                if self._left_right_block_illegal(attacker_idx, blocker_idx, blocker):
                    return False, f"{blocker.card.name} is in the wrong pile to block {attacker.card.name}"
                assignments.setdefault(blocker_idx, []).append(attacker_idx)

        # **How many creatures must block at once.** Menace (CR 702.111b) is
        # the N=2 case and Gorilla Berserkers' printed "can't be blocked except
        # by three or more creatures" is the same restriction with its number
        # written out, so one check reads both through
        # :meth:`_minimum_blockers`. A restriction on the declaration as a whole
        # rather than on any single blocker pair (CR 509.1c), so it is checked
        # over the finished assignment — none, or at least N, is fine; anything
        # between is not. A Camouflage resolution is not a declaration (the
        # piles were matched at random), so there the illegal block simply does
        # not happen rather than invalidating the whole resolution.
        menace_blocker_counts: dict[int, int] = {}
        for assigned_attackers in assignments.values():
            for attacker_idx in assigned_attackers:
                menace_blocker_counts[attacker_idx] = menace_blocker_counts.get(attacker_idx, 0) + 1
        # …and how many **may** block at once (Stalking Tiger). The same loop
        # and the same reading of CR 509.1c: a ceiling is a restriction on the
        # finished declaration, not on any single blocker pair, so it is checked
        # here beside the floor rather than in `_can_block_attacker`. A
        # Camouflage resolution takes the same out the floor does — those blocks
        # simply do not happen.
        for attacker_idx, count in menace_blocker_counts.items():
            attacker = resolved_attackers[attacker_idx]
            maximum = self._maximum_blockers(attacker)
            if maximum is None or count <= maximum:
                continue
            reason = f"can't be blocked by more than {maximum} creature(s)"
            if _camouflage_resolution:
                for blocker_idx in list(assignments):
                    remaining = [a for a in assignments[blocker_idx] if a != attacker_idx]
                    if remaining:
                        assignments[blocker_idx] = remaining
                    else:
                        del assignments[blocker_idx]
                self.log.append(
                    f"{attacker.card.name} {reason}; those blocks do not happen"
                )
                continue
            return False, f"{attacker.card.name} {reason}"

        for attacker_idx, count in menace_blocker_counts.items():
            attacker = resolved_attackers[attacker_idx]
            minimum = self._minimum_blockers(attacker)
            if count == 0 or count >= minimum:
                continue
            # Menace names itself where the keyword is what set the bar: the
            # player is owed the printed reason their declaration bounced, and
            # "fewer than 2" is not what their card says.
            reason = (
                "has menace and can't be blocked by only one creature"
                if minimum == 2 and self._has_keyword(attacker, "menace")
                else f"can't be blocked by fewer than {minimum} creatures"
            )
            if _camouflage_resolution:
                for blocker_idx in list(assignments):
                    remaining = [a for a in assignments[blocker_idx] if a != attacker_idx]
                    if remaining:
                        assignments[blocker_idx] = remaining
                    else:
                        del assignments[blocker_idx]
                self.log.append(
                    f"{attacker.card.name} {reason}; those blocks do not happen"
                )
                continue
            return False, f"{attacker.card.name} {reason}"

        # Lure enforcement: every creature that can block a Lure attacker (aimed at
        # this defender) must do so. Skipped for Camouflage resolutions: blocks then
        # come from random pile assignment, not a declaration, so blocking
        # requirements don't constrain it.
        for attacker_idx in (own_attackers if not _camouflage_resolution else ()):
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            # Two sources for one requirement: an Aura granting it (Lure) and
            # the creature's own printed line (Marble Priest). Read together so
            # the check is written once — and the printed form may narrow which
            # creatures it compels ("All **Walls** able to block this creature
            # do so"), which the Aura form never does.
            printed = next(
                (
                    instr for instr in compile_card_oracle(attacker.effective_card).instructions
                    if instr.kind == "must_be_blocked_by_all_able"
                ),
                None,
            )
            if printed is None and not aura_restriction_active(
                attacker, "must_be_blocked_by_all_able"
            ):
                continue
            # The printed noun, already a subject-filter payload: the table
            # reads the whole phrase through `_printed_noun` and refuses one it
            # cannot express, so there is nothing to translate here. It used to
            # be a `blocker_subtype` word this loop turned into one filter key,
            # which is a second, smaller vocabulary — a narrowing it failed to
            # translate would silently compel the whole board, which is Lure
            # rather than Marble Priest, and "creatures with flying" (Talruum
            # Piper) had no word for it to carry at all.
            compelled: dict[str, object] = dict(
                (printed.payload if printed is not None else {}).get("blocker_filter") or {}
            )
            for blocker_idx, blocker in enumerate(defender.battlefield):
                if not blocker.is_creature or blocker.tapped:
                    continue
                if not self._can_block_attacker(blocker, attacker):
                    continue
                # CR 509.1c, last clause: "If a creature can't block unless a
                # player pays a cost, that player is not required to pay that
                # cost, even if blocking with that creature would increase the
                # number of requirements being obeyed." So a Hipparion that
                # *could* pay is still not compelled by Lure. Asked of the one
                # cost reader rather than of `_can_block_attacker`, which
                # answers the restriction question (may it?) and must keep
                # saying yes to a block the defender chooses to pay for.
                if self._owes_a_cost_to_block(blocker, attacker):
                    continue
                # The **attacker's** controller is the observer, because the
                # sentence is printed on the attacker: CR 109.5's "you" is the
                # seat whose ability it is, not the seat being asked to block.
                # No card in the pool prints a relative narrowing here yet —
                # which is exactly why it was the defender's seat and nothing
                # noticed — and the phrase is a whole noun phrase now, so one
                # that does would have been tested against the wrong side.
                if compelled and not subject_matches(
                    self, blocker, compelled,
                    observer=self.controller_index_of(attacker),
                    source=attacker,
                ):
                    continue
                if blocker_idx not in assignments:
                    return False, f"{blocker.card.name} must block {attacker.card.name} due to Lure"

        # "This creature must be blocked if able." (Canopy Stalker.) CR 509.1c:
        # a blocking *requirement*, and the weakest of the three here — **one**
        # able creature must block it, where Lure above demands every able one
        # and Blaze of Glory below demands one creature block everything. Folding
        # it into Lure would forbid the defender keeping a second blocker back,
        # which is a legal declaration and one this card does not take away.
        #
        # Read off the attacker's compiled program, like the power restriction in
        # `_can_block_attacker`, and off its *effective* card so a copy of it
        # carries the requirement (CR 707.2).
        for attacker_idx in (own_attackers if not _camouflage_resolution else ()):
            attacker = self.permanent_at(attacker_controller, attacker_idx)
            if attacker is None:
                continue
            program = compile_card_oracle(attacker.effective_card)
            if not any(i.kind == "must_be_blocked" for i in program.instructions):
                continue
            if any(attacker_idx in assigned for assigned in assignments.values()):
                continue
            able = any(
                blocker.is_creature
                and not blocker.tapped
                and self._can_block_attacker(blocker, attacker)
                # CR 509.1c: a creature that owes a cost to block is never
                # compelled by a requirement, whether or not its controller
                # could pay.
                and not self._owes_a_cost_to_block(blocker, attacker)
                and not self._left_right_block_illegal(attacker_idx, blocker_idx, blocker)
                for blocker_idx, blocker in enumerate(self.controlled_by(defender))
            )
            if able:
                return False, (
                    f"{attacker.card.name} must be blocked if able"
                )

        # Blaze of Glory enforcement: the marked creature "blocks each attacking
        # creature this turn if able" — every attacker (aimed at this defender) it
        # can legally block must be among its assignments. Also skipped for
        # Camouflage resolutions.
        for blocker_idx, blocker in enumerate(defender.battlefield if not _camouflage_resolution else ()):
            if not blocker.metadata.get(MUST_BLOCK_ALL_UNTIL_EOT):
                continue
            if not blocker.is_creature or blocker.tapped:
                continue
            assigned = set(assignments.get(blocker_idx, []))
            for attacker_idx in own_attackers:
                if attacker_idx >= len(attacker_controller.battlefield):
                    continue
                attacker = attacker_controller.battlefield[attacker_idx]
                if not self._can_block_attacker(blocker, attacker):
                    continue
                # CR 509.1c again: a cost to block lifts every requirement,
                # this one included.
                if self._owes_a_cost_to_block(blocker, attacker):
                    continue
                if self._left_right_block_illegal(attacker_idx, blocker_idx, blocker):
                    continue
                if attacker_idx not in assigned:
                    return False, (
                        f"{blocker.card.name} must block {attacker.card.name} "
                        "(Blaze of Glory)"
                    )

        # "Target creature blocks **this creature** this turn if able."
        # (Trumpeting Armodon.) CR 509.1c's requirement narrowed to one named
        # attacker, and the narrowest of the four in this step: Lure names the
        # attacker and compels everybody, Blaze of Glory names the blocker and
        # compels every attacker, Watchdog names the blocker and compels
        # anything at all, and this names both halves of the pair.
        #
        # The attackers are held by ``permanent_id`` and resolved here, so a
        # marked attacker that left combat, left the battlefield, or is aimed at
        # somebody else compels nothing.
        for blocker_idx, blocker in enumerate(
            self.controlled_by(controller_index) if not _camouflage_resolution else ()
        ):
            owed = blocker.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ()
            if not owed:
                continue
            if not blocker.is_creature or blocker.tapped:
                continue
            assigned = set(assignments.get(blocker_idx, []))
            for attacker_idx in own_attackers:
                attacker = self.permanent_at(attacker_controller, attacker_idx)
                if attacker is None or attacker.permanent_id not in owed:
                    continue
                if attacker_idx in assigned:
                    continue
                if not self._can_block_attacker(blocker, attacker):
                    continue
                # CR 509.1c, last clause: a cost to block lifts every
                # requirement, this one included.
                if self._owes_a_cost_to_block(blocker, attacker):
                    continue
                if self._left_right_block_illegal(
                    attacker_idx, blocker_idx, blocker
                ):
                    continue
                joined = sum(
                    1
                    for other in assignments.values()
                    if attacker_idx in other
                )
                if joined + 1 < self._minimum_blockers(attacker):
                    continue
                return False, (
                    f"{blocker.card.name} must block {attacker.card.name} "
                    "this turn if able"
                )

        # "This creature blocks each combat if able." (Watchdog.) CR 509.1c's
        # requirement aimed at the *blocker* rather than at an attacker, and the
        # weakest one in this step: it compels this creature to block
        # **something** — any one attacker aimed at this defender that it can
        # legally block — where Lure compels every able creature onto one
        # attacker and Blaze of Glory compels one creature onto every attacker.
        #
        # Read off the creature's own compiled program and off its *effective*
        # card, so a copy of it carries the requirement (CR 707.2), beside the
        # Aura channel every other combat requirement here already asks.
        for blocker_idx, blocker in enumerate(
            self.controlled_by(controller_index) if not _camouflage_resolution else ()
        ):
            if not blocker.is_creature or blocker.tapped:
                continue
            if assignments.get(blocker_idx):
                continue
            program = compile_card_oracle(blocker.effective_card)
            # And the granted half (Provoke): a requirement a spell put on this
            # one creature for the turn, swept by the cleanup step. Read beside
            # the three above because all four answer the same question — must
            # this creature block *something*? — and a reader that knew only
            # three of them would let the fourth through.
            if not blocker.metadata.get(MUST_BLOCK_UNTIL_EOT) and not any(
                i.kind == "must_block_each_combat" for i in program.instructions
            ) and not aura_restriction_active(
                blocker, "must_block_each_combat"
            ) and not self._board_compels_block(blocker):
                continue
            able = False
            for attacker_idx in own_attackers:
                attacker = self.permanent_at(attacker_controller, attacker_idx)
                if attacker is None:
                    continue
                if not self._can_block_attacker(blocker, attacker):
                    continue
                # CR 509.1c, last clause: a creature that can't block unless a
                # cost is paid is never *compelled* to, whether or not its
                # controller could pay.
                if self._owes_a_cost_to_block(blocker, attacker):
                    continue
                if self._left_right_block_illegal(
                    attacker_idx, blocker_idx, blocker
                ):
                    continue
                # CR 509.1c measures the requirement against "the maximum
                # possible number … **without disobeying any restrictions**".
                # Menace is a restriction (CR 509.1b), so a lone able creature
                # joining a menace attacker nobody else blocks would be an
                # illegal declaration — which means the requirement cannot be
                # obeyed there and this creature is not "able".
                joined = sum(
                    1
                    for assigned in assignments.values()
                    if attacker_idx in assigned
                )
                if joined + 1 < self._minimum_blockers(attacker):
                    continue
                able = True
                break
            if able:
                return False, f"{blocker.card.name} blocks each combat if able"

        # CR 509.1b's restrictions on the **declaration as a whole** — the
        # block cap (Caverns of Despair), the company floor (Orcish Conscripts,
        # Mogg Flunkies) and the greater-power comparison (Okk). All three used
        # to be written out here and **nowhere else**, which is precisely what
        # W2G4 had already fixed on the attack side: the AI's chooser could not
        # ask them, so it proposed a set the declaration refused *whole* and the
        # defender blocked with nobody. They live in
        # :meth:`block_declaration_refusal` now, which is what both this gate
        # and `ai_declarations._legal_block_declaration` read.
        #
        # A Camouflage resolution is exempt for the reason menace and Lure are —
        # the piles were matched at random, so there is no declaration to
        # declare illegal — and the exemption stays at the *call*, beside the
        # other four, rather than inside a predicate the AI also asks.
        if not _camouflage_resolution:
            set_refusal = self.block_declaration_refusal(
                [resolved_blockers[idx] for idx in assignments]
            )
            if set_refusal is not None:
                return False, set_refusal[1]

        # CR 509.1d-f: the total cost to block, locked in and paid before the
        # chosen creatures become blockers. Last of the legality checks and
        # first of the commitments, because a declaration this rejects must
        # leave nothing spent - the same order the attack side takes at
        # CR 508.1h.
        if not _camouflage_resolution:
            # CR 119.4 again, over the whole declaration: a per-pair predicate
            # can say "you could afford this one" and not "and again for the
            # next", so a defender at 2 life would declare three Heat-Waved
            # blockers and pay for two. Checked before anything is spent, the
            # same order the mana plan below takes.
            life_owed = self._block_declaration_life(
                assignments, resolved_blockers, resolved_attackers
            )
            if life_owed and self.players[controller_index].life < life_owed:
                return False, (
                    f"can't pay {life_owed} life to declare those blockers"
                )
            block_total, block_plan = self._block_declaration_mana_plan(
                controller_index, assignments, resolved_blockers, resolved_attackers
            )
            if block_total and block_plan is None:
                return False, (
                    f"can't pay {mana_cost_label(block_total)} to declare those blockers"
                )
            # The tap half (Hollow Warrior), drawing on what the mana plan
            # leaves: an animated land tapped for mana is not also the creature
            # tapped here.
            block_taps = self.declaration_tap_plan(
                controller_index,
                [resolved_blockers[idx] for idx in assignments],
                "block",
                unavailable=list(block_plan.tapped) if block_plan else (),
                preferred_ids=cost_permanent_ids or (),
            )
            if block_taps is None:
                return False, "can't tap a creature to pay those blockers' cost"
            named_refusal = self.declaration_cost_name_refusal(
                cost_permanent_ids, block_taps
            )
            if named_refusal is not None:
                return False, named_refusal
            self._pay_block_declaration_mana(controller_index, block_total, block_plan)
            self.pay_declaration_taps(controller_index, block_taps, "block")
            if life_owed:
                defender_paying = self.players[controller_index]
                defender_paying.life -= life_owed
                self.log.append(
                    f"{defender_paying.name} paid {life_owed} life to declare "
                    "blockers"
                )

        # Nested by defender (CR 802): only this defender's own entry is replaced,
        # so an earlier defender's declaration in the same combat survives.
        if assignments:
            self.combat_blockers[controller_index] = assignments
        else:
            self.combat_blockers.pop(controller_index, None)
        self.combat_blockers_declared_by.add(controller_index)
        self._record_block_history(controller_index, assignments)
        self._prune_combat_state()
        # CR 802.4: blocks lock in only once every defending player has declared
        # (or been auto-skipped) in APNAP order — not after this one defender.
        self.combat_blockers_locked = self._pending_block_declarer() is None
        self.log.append(f"{defender.name} declared {len(assignments)} blocker(s)")
        # 509.1i / 509.2a: abilities that trigger on blockers being declared fire now.
        # Two dispatchers, one per half of the block. A card printing the halves
        # joined ("blocks **or** becomes blocked by …") is fired by both, which
        # is what let the third, Cockatrice-specific fire site here be deleted:
        # it did the same work with the "non-Wall" test written out by hand.
        # One window for CR 603.3b, as the attack declaration's is: everything
        # the block sets off goes on the stack together, and each controller
        # orders theirs.
        with self.putting_triggers_on_stack():
            self._fire_creature_blocks_triggers(controller_index, assignments)
            self._fire_delayed_block_triggers(controller_index, assignments)
            self._fire_becomes_blocked_triggers(controller_index, assignments)
            self._fire_delayed_block_pair_triggers(controller_index, assignments)
            self._fire_delayed_becomes_blocked_triggers(controller_index, assignments)
            self._fire_board_wide_block_triggers(controller_index, assignments)
        # CR 509.2/802.4: once every defending player has declared, the active
        # player receives priority.
        if self.combat_blockers_locked:
            self.start_priority_window(self.active_player_index)
        return True, "declared blockers"

    def is_camouflage_active(self) -> bool:
        """True when Camouflage was cast this turn, so the defender's blocks come
        from piles randomly matched to attackers instead of declared blocks."""
        return self.camouflage_active_turn == self.turn

    def assign_camouflage_piles(
        self, defender_index: int, piles: dict[int, int | list[int]]
    ) -> tuple[bool, str]:
        """Camouflage: the defending player divides any number of their untapped
        creatures into piles — one pile per attacker; piles may be empty and
        creatures may be left out. ``piles`` maps a battlefield index to the pile
        number(s) (0-based) it goes into; a creature that can block additional
        creatures may sit in that many piles. Each pile is then matched to a
        different attacker at random, and every pile member that can block its
        attacker does so."""
        if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
            return False, "piles can only be assigned during declare_blockers"
        if not self.is_camouflage_active():
            return False, "Camouflage is not active"
        if defender_index not in self.combat_defending_players():
            return False, "only the defending player may assign piles"
        if self.combat_blockers_locked:
            return False, "blockers are already locked in"
        self._prune_combat_state()
        defender = self.players[defender_index]
        attackers = [a for a, d in self.combat_attackers.items() if d == defender_index]
        if not attackers:
            return self.declare_blockers(defender_index, {}, _camouflage_resolution=True)

        pile_lists: list[list[int]] = [[] for _ in attackers]
        for raw_idx, raw_piles in piles.items():
            blocker_idx = int(raw_idx)
            pile_numbers = raw_piles if isinstance(raw_piles, (list, tuple, set)) else [raw_piles]
            distinct = sorted({int(p) for p in pile_numbers})
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                return False, "creature index out of range"
            blocker = defender.battlefield[blocker_idx]
            if not blocker.is_creature:
                return False, "only creatures can be put into piles"
            if blocker.tapped:
                return False, f"{blocker.card.name} is tapped"
            if any(p < 0 or p >= len(pile_lists) for p in distinct):
                return False, f"pile numbers must be between 0 and {len(pile_lists) - 1}"
            if len(distinct) > self._max_blocks_for(blocker):
                return False, f"{blocker.card.name} cannot be put into that many piles"
            for pile_number in distinct:
                pile_lists[pile_number].append(blocker_idx)
        return self._resolve_camouflage_piles(defender_index, pile_lists)

    def resolve_camouflage_blocking(self, defender_index: int) -> tuple[bool, str]:
        """Camouflage with a non-choosing (AI) defender: divide the untapped
        creatures into random piles (round-robin over a shuffle), then resolve the
        random pile→attacker matching. Uses the module RNG, so a seeded run is
        reproducible."""
        if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
            return False, "blockers can only be declared during declare_blockers"
        if defender_index not in self.combat_defending_players():
            return False, "only defending player may declare blockers"
        defender = self.players[defender_index]
        attackers = [a for a, d in self.combat_attackers.items() if d == defender_index]
        if not attackers:
            return self.declare_blockers(defender_index, {}, _camouflage_resolution=True)

        candidates = [
            idx for idx, perm in enumerate(defender.battlefield)
            if perm.is_creature and not perm.tapped
        ]
        random.shuffle(candidates)
        piles: list[list[int]] = [[] for _ in attackers]
        for i, blocker_idx in enumerate(candidates):
            piles[i % len(piles)].append(blocker_idx)
        return self._resolve_camouflage_piles(defender_index, piles)

    def _resolve_camouflage_piles(self, defender_index: int, piles: list[list[int]]) -> tuple[bool, str]:
        """Match each Camouflage pile to a different attacker at random; every pile
        member that can legally block its matched attacker becomes a blocker."""
        defender = self.players[defender_index]
        attacker_controller = self.players[self.active_player_index]
        attackers = [a for a, d in self.combat_attackers.items() if d == defender_index]
        shuffled_attackers = list(attackers)
        random.shuffle(shuffled_attackers)

        assignment: dict[int, list[int]] = {}
        for pile, attacker_idx in zip(piles, shuffled_attackers):
            attacker = attacker_controller.battlefield[attacker_idx]
            for blocker_idx in pile:
                blocker = defender.battlefield[blocker_idx]
                if not self._can_block_attacker(blocker, attacker):
                    continue
                if self._left_right_block_illegal(attacker_idx, blocker_idx, blocker):
                    continue
                assignment.setdefault(blocker_idx, []).append(attacker_idx)
        self.log.append(
            f"Camouflage matched {len(piles)} pile(s) to attackers at random: "
            f"{len(assignment)} creature(s) block"
        )
        return self.declare_blockers(defender_index, assignment, _camouflage_resolution=True)

    def _left_right_block_illegal(self, attacker_idx: int, blocker_idx: int, blocker: Permanent) -> bool:
        """CR Raging River: an attacker assigned to a pile can only be blocked by a
        flyer or by a creature in that same pile. Returns True if this block breaks
        that restriction. A no-op when no left/right division is active."""
        if not self.combat_left_right_active:
            return False
        attacker_side = self.combat_attacker_piles.get(attacker_idx)
        if attacker_side is None:
            return False
        if self._has_keyword(blocker, "flying"):
            return False  # flyers may block regardless of pile
        return self.combat_defender_piles.get(blocker_idx) != attacker_side

    def assign_defender_piles(self, defender_index: int, piles: dict[int, str]) -> tuple[bool, str]:
        """Raging River: the defending player divides their non-flying creatures
        into a "left" and a "right" pile. ``piles`` maps a battlefield index to the
        side label. Every non-flying creature must be assigned exactly one side."""
        if not self.combat_left_right_active:
            return False, "no left/right division is active"
        if defender_index != self.combat_left_right_defender_index:
            return False, "only the defending player may divide their creatures"
        defender = self.players[defender_index]
        required = {
            idx for idx, perm in enumerate(defender.battlefield)
            if perm.is_creature and not self._has_keyword(perm, "flying")
        }
        chosen = {int(i): str(s).lower() for i, s in piles.items()}
        if set(chosen) != required or any(s not in ("left", "right") for s in chosen.values()):
            return False, "every non-flying creature must be assigned to left or right"
        self.combat_defender_piles = chosen
        self.combat_left_right_defender_locked = True
        self.log.append(f"{defender.name} divided their creatures into left/right piles")
        return True, "piles assigned"

    def assign_attacker_piles(self, attacker_index: int, piles: dict[int, str]) -> tuple[bool, str]:
        """Raging River: the attacking player labels each of their attacking
        creatures "left" or "right" (the pile it can be blocked from)."""
        if not self.combat_left_right_active:
            return False, "no left/right division is active"
        if attacker_index != self.active_player_index:
            return False, "only the attacking player may label their attackers"
        chosen = {int(i): str(s).lower() for i, s in piles.items()}
        if set(chosen) != set(self.combat_attackers) or any(s not in ("left", "right") for s in chosen.values()):
            return False, "every attacker must be labeled left or right"
        self.combat_attacker_piles = chosen
        self.combat_left_right_attacker_locked = True
        self.log.append("Attacker labeled each creature left/right")
        return True, "attacker piles assigned"

    def _block_mana_costs_of(
        self, blocker: Permanent, attacker: Permanent
    ) -> list[dict[str, int]]:
        """The mana *blocker* owes to be declared against *attacker* (CR 509.1d).

        "This creature can't block creatures with power 3 or greater unless you
        pay {1}." (Hipparion.) The cost is owed **per attacker blocked**, not
        per blocker: CR 509.1d totals the costs of the creatures chosen to
        block, and a creature that can block two attackers is disobeying the
        restriction twice if it pays once.

        Whether the restriction bites is a question about the *attacker* - its
        effective power, so a pumped 2/2 costs the same {1} a printed 3/3 does
        - which is why this takes the pair rather than the blocker alone.

        One reader for the gate in ``_can_block_attacker`` and the charge in
        ``declare_blockers``, exactly as ``_attack_mana_costs_of`` is on the
        other side: a cost checked by one rule and paid by another is how a
        declaration gets accepted and then left unpaid.

        **Two channels, because either end of the pair may print the cost.**
        Hipparion prints it on the blocker; Awesome Presence prints it on an
        Aura on the *attacker* ("…unless defending player pays {3} for each
        creature they control that's blocking it"), which is the same CR 509.1d
        cost owed by the same seat. The "for each" needs no multiplier here for
        Koskun Falls' reason on the attack side: this is asked once per pair and
        ``_block_declaration_mana_plan`` sums the pairs, so a per-pair {3} is
        already {3} per blocking creature.
        """
        costs: list[dict[str, int]] = []
        for instruction in compile_card_oracle(blocker.effective_card).instructions:
            if instruction.kind != "cant_block_power_n_or_greater_unless_pay":
                continue
            if attacker.effective_power < int(instruction.payload.get("power", 0)):
                continue
            cost = {
                symbol: int(amount)
                for symbol, amount in (instruction.payload.get("mana") or {}).items()
            }
            if cost:
                costs.append(cost)
        for restriction in (
            *compile_card_oracle(attacker.effective_card).instructions,
            *attached_combat_restrictions(attacker),
        ):
            if restriction.kind != "cant_be_blocked_unless_pay":
                continue
            cost = {
                symbol: int(amount)
                for symbol, amount in (restriction.payload.get("mana") or {}).items()
            }
            if cost:
                costs.append(cost)
        return costs

    def _owes_a_cost_to_block(self, blocker: Permanent, attacker: Permanent) -> bool:
        """Whether *blocker* owes **any** cost to block *attacker* (CR 509.1d).

        The one question CR 509.1c's last clause asks — "if a creature can't
        block unless a player pays a cost, that player is not required to pay
        that cost" — and so the one reader the five requirement checks in
        ``declare_blockers`` ask. They asked ``_block_mana_costs_of`` alone,
        which is every cost this step charges *in mana per pair* and none of
        the others: a Heat-Waved creature (life), one under War Cadence (a
        per-blocker toll) and Hollow Warrior (a tap) were each compelled by
        Lure to block and pay. Every currency the step charges is here.
        """
        return bool(
            self._block_mana_costs_of(blocker, attacker)
            or self._block_toll_of(blocker)
            or self._block_life_cost_of(blocker, attacker)
            or declaration_tap_costs(blocker, "block")
        )

    def _block_toll_of(self, blocker: Permanent) -> dict[str, int]:
        """The mana *blocker*'s controller owes **once** for blocking with it.

        "This turn, creatures can't block unless their controller pays {X} for
        each blocking creature they control." (War Cadence.) CR 509.1d again,
        and it takes the blocker **alone** where :meth:`_block_mana_costs_of`
        beside it takes the pair. That is the whole reason it is a second
        reader rather than a fourth channel in that one:

        * Hipparion's toll and Awesome Presence's are owed **per attacker
          blocked** — "for each creature they control that's blocking **it**" —
          so asking once per pair is what the card says, and a creature that
          blocks two attackers disobeys the restriction twice if it pays once.
        * War Cadence's is owed per **blocking creature**. A creature blocking
          two attackers (Two-Headed Giant of Foriys) is still one blocking
          creature, and charging it per pair would bill twice what the card
          asks.

        CR 802.4b is what makes the per-controller sum right in multiplayer:
        determining whether a defending player's blocks are legal ignores
        blocking creatures controlled by other players, so each defender pays
        for their own and ``_block_declaration_mana_plan`` — which is already
        per-controller — sums exactly the right set.

        Asked with no observer, for ``_attack_mana_costs_of``'s reason on the
        other side: the toll is a record on the game rather than text on a
        permanent, so there is no seat whose "you" the noun phrase could mean.
        """
        total: dict[str, int] = {}
        for entry in self.blocking_restrictions_until_eot:
            if not entry.get("toll"):
                continue
            cost = entry.get("mana") or {}
            if not subject_matches(self, blocker, dict(entry.get("filter") or {})):
                continue
            for symbol, amount in cost.items():
                total[symbol] = total.get(symbol, 0) + int(amount)
        return total

    def _block_life_cost_of(self, blocker: Permanent, attacker: Permanent) -> int:
        """The life *blocker*'s controller owes to block *attacker* (CR 509.1d).

        "Nonblue creatures can't block creatures you control unless their
        controller pays 1 life for each blocking creature they control." (Heat
        Wave.) Found by scanning the board, like the restriction it is a toll
        on: the source is an enchantment nobody is attacking or blocking.

        Both noun phrases are asked with the **restricting permanent's** seat as
        the observer — "creatures you control" is that seat's "you" (CR 109.5),
        which on this card is the difference between a toll on blocking the
        enchantment's controller and a toll on blocking anybody.

        One reader for the gate in ``_can_block_attacker`` and the charge in
        ``declare_blockers``, exactly as ``_block_mana_costs_of`` beside it is:
        a cost checked by one rule and paid by another is how a block gets
        accepted and then left unpaid.
        """
        owed = 0
        for source_seat, source_perm in self.permanents_with_controller():
            for restriction in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if restriction.kind != "subject_cant_block_subject_unless_pay_life":
                    continue
                if not subject_matches(
                    self, blocker, restriction.payload.get("subject") or {},
                    observer=source_seat, source=source_perm,
                ):
                    continue
                if not any(
                    subject_matches(
                        self, attacker, described,
                        observer=source_seat, source=source_perm,
                    )
                    for described in restriction.payload.get("blockee_filters") or ()
                ):
                    continue
                owed += int(restriction.payload.get("life", 0))
        return owed

    def _block_declaration_life(
        self,
        assignments: dict[int, list[int]],
        resolved_blockers: dict[int, Permanent],
        resolved_attackers: dict[int, Permanent],
    ) -> int:
        """The whole declaration's CR 509.1d life cost.

        Counted **per blocking creature**, which is what the card prints — "for
        each blocking creature they control" — and deliberately not per
        (blocker, attacker) pair the way the mana total beside it is. That
        difference is the two sentences', not an inconsistency: Hipparion's
        toll is owed for disobeying a restriction, and a creature blocking two
        attackers disobeys it twice, while Heat Wave counts creatures. A
        creature blocking two attackers pays once here, and the maximum over its
        attackers is what it owes — a creature restricted against only one of
        the two still pays the toll it triggered.
        """
        total = 0
        for blocker_idx, attacker_indices in assignments.items():
            blocker = resolved_blockers.get(blocker_idx)
            if blocker is None:
                continue
            owed = 0
            for attacker_idx in attacker_indices:
                attacker = resolved_attackers.get(attacker_idx)
                if attacker is not None:
                    owed = max(owed, self._block_life_cost_of(blocker, attacker))
            total += owed
        return total

    def _block_declaration_mana_plan(
        self,
        controller_index: int,
        assignments: dict[int, list[int]],
        resolved_blockers: dict[int, Permanent],
        resolved_attackers: dict[int, Permanent],
    ):
        """How the whole block declaration's CR 509.1d mana is paid, or None.

        The costs of *every* chosen blocker add into one total, which is the
        difference between this and ``_can_block_attacker``: a per-pair
        predicate can say "you could pay {1} for this block" and cannot say
        "and {1} again for the next", so a defender with one mana would declare
        two Hipparions and be charged for one.

        Nothing is excluded from what may pay, unlike the attack side: CR 509.1g
        does not tap blockers, so an animated land that is also blocking is
        still a land its controller may tap. The plan is made before anything is
        spent, so the gate and the charge read one board.
        """
        total: dict[str, int] = {}
        for blocker_idx, attacker_indices in assignments.items():
            blocker = resolved_blockers.get(blocker_idx)
            if blocker is None:
                continue
            # War Cadence's toll, added **once for the creature** and outside
            # the per-attacker loop below — see ``_block_toll_of``. Inside it, a
            # creature blocking two attackers would be billed twice for being
            # one blocking creature.
            for symbol, amount in self._block_toll_of(blocker).items():
                total[symbol] = total.get(symbol, 0) + amount
            for attacker_idx in attacker_indices:
                attacker = resolved_attackers.get(attacker_idx)
                if attacker is None:
                    continue
                for cost in self._block_mana_costs_of(blocker, attacker):
                    for symbol, amount in cost.items():
                        total[symbol] = total.get(symbol, 0) + amount
        if not total:
            return {}, None
        defender = self.players[controller_index]
        return total, plan_payment(
            defender.mana_pool,
            self.payment_lands(controller_index),
            total, payer=defender,
        )

    def _pay_block_declaration_mana(
        self, controller_index: int, total: dict[str, int], plan
    ) -> None:
        """Spend the plan :meth:`_block_declaration_mana_plan` made (CR 509.1f).

        Floating mana first and then untapped lands - the stated policy every
        cost with no priority window behind it takes in this engine. CR 509.1e
        does give the defender a window to activate mana abilities; the engine
        takes it on their behalf rather than pausing the turn-based action,
        which is the same shortcut the attack side takes at CR 508.1i.
        """
        if plan is None:
            return
        defender = self.players[controller_index]
        # The lands the plan named, tapped **for mana** (CR 605.3a) through the
        # one payer every effect-collected cost shares, re-planned over those
        # same lands as the attack side does.
        planned = list(plan.tapped)
        paid = self._pay_planned_cost(
            defender,
            lambda: plan_payment(
                defender.mana_pool,
                [
                    land for land in self.payment_lands(controller_index)
                    if any(land is named for named in planned)
                ],
                total, payer=defender,
            ),
        )
        # Said as it happened, for the attack side's reason.
        self.log.append(
            f"{defender.name} paid {mana_cost_label(total)} to declare blockers"
            if paid else
            f"{defender.name} could not pay {mana_cost_label(total)} in full "
            "to declare blockers: a land the payment counted on made nothing "
            "it could spend"
        )

    def _combat_blockers_for_attacker(self, attacker_idx: int) -> list[int]:
        """Battlefield indices (on this attacker's own defender's battlefield) of
        every creature blocking it. Resolved via the attacker's own defender since
        blocker indices are only unambiguous within one defender's battlefield."""
        defending_idx = self.combat_attackers.get(attacker_idx)
        if defending_idx is None:
            return []
        blocker_map = self.combat_blockers.get(defending_idx, {})
        return [blocker_idx for blocker_idx, a_idxs in blocker_map.items() if attacker_idx in a_idxs]

    def _is_blocking_creature(self, permanent: Permanent) -> bool:
        """True if *permanent* is currently blocking an attacker (Righteousness)."""
        for defending_index, blocker_map in self.combat_blockers.items():
            if not (0 <= defending_index < len(self.players)):
                continue
            defender = self.players[defending_index]
            for blocker_idx in blocker_map:
                if 0 <= blocker_idx < len(defender.battlefield) and defender.battlefield[blocker_idx] is permanent:
                    return True
        return False

    def _apply_band_block_propagation(self) -> None:
        """CR 702.22h/i: when one band member becomes blocked, every other creature
        in that band becomes blocked by the same blocker(s).

        Recomputed from ``combat_blockers`` so it stays correct as combat state is
        pruned. A no-op when no attacking bands were declared.
        """
        self.combat_band_blocks = {}
        if not self.combat_bands:
            return
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            return
        active = self.players[self.active_player_index]
        for band in self.combat_bands:
            band_blockers: set[int] = set()
            for member in band:
                band_blockers.update(self._combat_blockers_for_attacker(member))
            if not band_blockers:
                continue
            for member in band:
                if member < 0 or member >= len(active.battlefield):
                    continue
                extra = sorted(band_blockers - set(self._combat_blockers_for_attacker(member)))
                if extra:
                    self.combat_band_blocks[member] = extra
                active.battlefield[member].blocked = True

    def _remove_blocker_from_combat(
        self, defender_player_index: int, blocker_index: int,
        *, frees_blocked_attackers: bool = False,
    ) -> None:
        """Take a creature out of combat as a blocker (CR 506.4): drop it from
        ``combat_blockers`` and from every map keyed by its slot.

        **The attacker stays blocked.** CR 509.1h: "A creature remains blocked
        even if all the creatures blocking it are removed from combat." This
        used to unblock it unconditionally, and every caller in the pool happens
        to print that unblocking as its own printed clause — Ydwen Efreet, False
        Orders and Imprison all say "creatures it was blocking that had become
        blocked by only this creature this combat become unblocked", which is a
        thing those cards *do* rather than a thing removal does. So the default
        is the rule and ``frees_blocked_attackers`` is the clause; a caller that
        does not print it (General Jarkeld's reassignment, and any card printed
        next) gets CR 509.1h instead of inheriting three cards' extra sentence.
        """
        own_blocker_map = self.combat_blockers.get(defender_player_index, {})
        if blocker_index not in own_blocker_map:
            return
        freed_attackers = list(own_blocker_map.get(blocker_index, []))
        own_blocker_map.pop(blocker_index, None)
        if own_blocker_map:
            self.combat_blockers[defender_player_index] = own_blocker_map
        else:
            self.combat_blockers.pop(defender_player_index, None)
        self.combat_band_blocks.pop(blocker_index, None)
        # CR 506.4: it stops being a blocking creature, so the division of its
        # combat damage among the creatures it was blocking (CR 510.1a) is gone
        # with the block. Left behind, that map would divide the damage of
        # whatever is blocking from this slot next — the same class of staleness
        # `_renumber_combat_after_removal` exists for, one map further on.
        self.combat_multiblock_damage.pop(blocker_index, None)
        defender = self.players[defender_player_index]
        if 0 <= blocker_index < len(defender.battlefield):
            removed = defender.battlefield[blocker_index]
            removed.blocking_attacker_controller = None
            removed.blocking_attacker_index = None
        active = self.players[self.active_player_index]
        for a_idx in (freed_attackers if frees_blocked_attackers else ()):
            still_blocked = any(
                a_idx in atks
                for blocker_map in self.combat_blockers.values()
                for atks in blocker_map.values()
            )
            if not still_blocked and 0 <= a_idx < len(active.battlefield):
                active.battlefield[a_idx].blocked = False
        # CR 702.22h: band block propagation is recomputed from combat_blockers.
        self._apply_band_block_propagation()

    def _record_block_history(
        self, controller_index: int, assignments: dict[int, list[int]]
    ) -> None:
        """Stamp what each blocker in *assignments* is now blocking.

        The one place a block is written onto the permanents involved, and it is
        one place because a block happens in two ways: the declaration (CR
        509.1g) and an effect that makes a creature block (Sorrow's Path's
        reassignment). A record kept only by the declaration would answer
        "which creatures did that Wall block this turn?" with the blocks the
        *player* chose and none of the blocks an effect imposed — a silent
        undercount, since the reader (Glyph of Doom, Glyph of Delusion,
        Glyph of Reincarnation) cannot tell an empty record from no block.
        """
        if not (0 <= controller_index < len(self.players)):
            return
        defender = self.players[controller_index]
        for blocker_idx in assignments:
            if 0 <= blocker_idx < len(defender.battlefield):
                defender.battlefield[blocker_idx].metadata["blocked_this_combat"] = True
        # "…all creatures that were blocked by that creature **this turn**"
        # (Glyph of Doom). `blocked_this_combat` above cannot answer it: that
        # flag is cleared by `end_combat` and says only *that* the creature
        # blocked, not what. A turn may hold several combats and the sentence
        # spans all of them, so the pair is recorded per turn and by id — an
        # index renumbers the moment anything leaves (CR 400.7) — and swept
        # with the rest of the turn's records at cleanup.
        for _blocker_idx, blocker, blocked in self._resolved_block_pairs(
            controller_index, assignments
        ):
            record = blocker.metadata.setdefault("blocked_attacker_ids_this_turn", [])
            # "…the player who controlled that creature **the last time it
            # became blocked by that Wall**" (Glyph of Reincarnation). Who
            # controls the attacker is CR 613 layer 2 and moves; by the time
            # that sentence is read the creature is in a graveyard and has no
            # controller at all. So the seat is frozen here, beside the id it
            # keys, at the one moment the block happens — and overwritten on
            # each later block by the same blocker, which is precisely what
            # "the last time" says. Kept on the *blocker* rather than on the
            # attacker because the sentence asks about blocks by one named
            # Wall, not about every block the creature was in.
            controllers = blocker.metadata.setdefault(
                "blocked_attacker_controllers_this_turn", {}
            )
            for _attacker_idx, attacker in blocked:
                if attacker.permanent_id not in record:
                    record.append(attacker.permanent_id)
                seat = self.controller_index_of(attacker)
                if seat is not None:
                    controllers[attacker.permanent_id] = seat
                # The same pair written from the attacker's end. "…destroy all
                # creatures that **blocked or were blocked by** it this turn"
                # (Venomous Breath) reads a *two-way* relation off a creature
                # the spell named a whole combat earlier, and by end of combat
                # that creature is very often dead — which is the ordinary way
                # this card is played. Only the survivors can be destroyed, so
                # both halves have to be answerable from a *survivor's* own
                # record: one half already is (a blocker names the attackers it
                # blocked), and this is the other. Written in the same loop as
                # its mirror, so the two cannot disagree about a pair.
                mirror = attacker.metadata.setdefault(
                    "blocked_by_blocker_ids_this_turn", []
                )
                if blocker.permanent_id not in mirror:
                    mirror.append(blocker.permanent_id)
                # "…if it has blocked or been blocked **since your last
                # upkeep**" (Wiitigo). A window that spans the opponents' turns
                # in between, so neither record above can answer it: both are
                # swept with the turn. This one is an ordinal stamp beside the
                # attack stamp in ``turn_state``, written for both sides of the
                # pair here because "blocked or been blocked" is one question
                # asked of whichever creature is doing the asking.
                for perm in (blocker, attacker):
                    seat = self.controller_index_of(perm)
                    if seat is not None:
                        record_block_involvement(
                            perm, seat, self.seat_turn_counts.get(seat, 0)
                        )
