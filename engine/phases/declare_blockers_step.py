from __future__ import annotations

"""Declare blockers step (CR 509).

The defending player declares blockers as a turn-based action. This module holds
block legality (``_can_block_attacker`` and its landwalk helper), Lure
enforcement, the block-triggered abilities (Cockatrice/Thicket Basilisk), band
block propagation (CR 702.22h), and the Rampage/Flanking combat buffs that fire
when a creature becomes blocked.
"""

import random
import re

from ..auras import attached_combat_restrictions, aura_restriction_active
from ..combat_permissions import CANT_BLOCK_UNTIL_EOT
from ..combat_restrictions import declaration_company_required, participation_cap
from ..evasion_negation import negated_evasion_abilities
from ..landwalk import LANDWALK, land_satisfies, landwalk_requirement
from ..mana_payment import mana_cost_label, plan_payment, untapped_mana_lands
from ..delayed_triggers import fire_delayed_triggers
from ..layer_bridge import computed_abilities
from ..subject_filters import subject_matches
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..pt import add_pt_modifier
from ..static_bonuses import conditional_static_holds
from ..trigger_utils import matching_triggers
from ..turn_state import record_block_involvement

# Landwalk is not a fixed word list any more: what the defender must control is
# the ability's printed **quality**, and CR 702.14a lets that quality be a land
# subtype welded into the word ("islandwalk") or a supertype standing in front
# of the family word ("legendary landwalk", Livonya Silone). `engine/landwalk.py`
# reads both into one requirement, and the same reader admits the printed line
# in `engine.oracle` — so a quality nothing here can test keeps its card
# unsupported instead of shipping evasion that never applies.


class DeclareBlockersStepMixin:
    def _max_blocks_for(self, blocker: Permanent) -> int:
        """How many attackers this creature may block at once (CR 509.1b). Normally
        1; each "can block an additional creature" grant (Two-Headed Giant of
        Foriys) adds one. Blaze of Glory grants "can block any number of creatures",
        modeled as effectively unlimited."""
        if blocker.metadata.get("can_block_any_number_until_eot"):
            return 1_000_000
        text = blocker.effective_card.oracle_text.lower()
        return 1 + text.count("can block an additional creature")

    def declare_blockers(
        self,
        controller_index: int,
        blocker_to_attacker: dict[int, int | list[int]],
        *,
        _camouflage_resolution: bool = False,
    ) -> tuple[bool, str]:
        if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
            return False, "blockers can only be declared during declare_blockers"
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

        # Menace (CR 702.111b): an attacker with menace can't be blocked by
        # exactly one creature. A restriction on the declaration as a whole
        # rather than on any single blocker pair (CR 509.1c), so it is checked
        # over the finished assignment — none or two-plus blockers are fine,
        # one is not. A Camouflage resolution is not a declaration (the piles
        # were matched at random), so there the illegal block simply does not
        # happen rather than invalidating the whole resolution.
        menace_blocker_counts: dict[int, int] = {}
        for assigned_attackers in assignments.values():
            for attacker_idx in assigned_attackers:
                menace_blocker_counts[attacker_idx] = menace_blocker_counts.get(attacker_idx, 0) + 1
        for attacker_idx, count in menace_blocker_counts.items():
            if count != 1:
                continue
            attacker = resolved_attackers[attacker_idx]
            if not self._has_keyword(attacker, "menace"):
                continue
            if _camouflage_resolution:
                for blocker_idx in list(assignments):
                    remaining = [a for a in assignments[blocker_idx] if a != attacker_idx]
                    if remaining:
                        assignments[blocker_idx] = remaining
                    else:
                        del assignments[blocker_idx]
                self.log.append(
                    f"{attacker.card.name} has menace; a lone creature cannot block it"
                )
                continue
            return False, (
                f"{attacker.card.name} has menace and can't be blocked by only one creature"
            )

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
            # The printed noun, translated into the subject-filter vocabulary
            # the same way `_can_block_attacker` translates `cant_be_blocked_by`
            # a few screens down — one payload key means one filter key, and a
            # narrowing this loop failed to translate would silently compel the
            # whole board, which is Lure rather than Marble Priest.
            compelled: dict[str, object] = {}
            subtype = (printed.payload if printed is not None else {}).get("blocker_subtype")
            if subtype:
                compelled["subtype_filter"] = subtype
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
                if self._block_mana_costs_of(blocker, attacker):
                    continue
                if compelled and not subject_matches(
                    self, blocker, compelled, observer=controller_index, source=attacker
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
                and not self._block_mana_costs_of(blocker, attacker)
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
            if not blocker.metadata.get("must_block_all_until_eot"):
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
                if self._block_mana_costs_of(blocker, attacker):
                    continue
                if self._left_right_block_illegal(attacker_idx, blocker_idx, blocker):
                    continue
                if attacker_idx not in assigned:
                    return False, (
                        f"{blocker.card.name} must block {attacker.card.name} "
                        "(Blaze of Glory)"
                    )

        # "No more than two creatures can block each combat." (Caverns of
        # Despair.) The blocking twin of the attack cap, and a restriction on
        # the declaration as a whole (CR 509.1b) rather than on any one pairing,
        # so it is checked here rather than in `_can_block_attacker`. Counted
        # across **every** defender's declaration: the sentence says "each
        # combat", and one seat's blockers do not stop being blockers because
        # another seat declares next. A Camouflage resolution is exempt for the
        # reason menace and Lure are — the piles were matched at random, so
        # there is no declaration to declare illegal.
        if not _camouflage_resolution:
            block_cap = participation_cap(self.all_permanents(), "block")
            if block_cap is not None:
                already = sum(
                    len(other)
                    for seat, other in self.combat_blockers.items()
                    if seat != controller_index
                )
                if already + len(assignments) > block_cap:
                    return False, (
                        f"no more than {block_cap} creature(s) can block each combat"
                    )

        # "…can't block **unless at least two other creatures block**." (Orcish
        # Conscripts.) The floor to the cap above, and counted the same way and
        # for the same reason: CR 509.1b asks its restrictions of the whole
        # declaration, and a creature blocking under another defender's
        # declaration does not stop being a blocker because this seat declares
        # next. Camouflage is exempt beside the cap, for that block's reason —
        # the piles were matched at random, so there is no declaration to
        # declare illegal.
        if not _camouflage_resolution:
            blocking_total = len(assignments) + sum(
                len(other)
                for seat, other in self.combat_blockers.items()
                if seat != controller_index
            )
            for blocker_idx in assignments:
                blocker = resolved_blockers[blocker_idx]
                needed = declaration_company_required(blocker, "block")
                if needed is not None and blocking_total - 1 < needed:
                    return False, (
                        f"{blocker.card.name} needs at least {needed} other "
                        "blocking creature(s)"
                    )

        # CR 509.1d-f: the total cost to block, locked in and paid before the
        # chosen creatures become blockers. Last of the legality checks and
        # first of the commitments, because a declaration this rejects must
        # leave nothing spent - the same order the attack side takes at
        # CR 508.1g.
        if not _camouflage_resolution:
            block_total, block_plan = self._block_declaration_mana_plan(
                controller_index, assignments, resolved_blockers, resolved_attackers
            )
            if block_total and block_plan is None:
                return False, (
                    f"can't pay {mana_cost_label(block_total)} to declare those blockers"
                )
            self._pay_block_declaration_mana(controller_index, block_total, block_plan)

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
        self._fire_creature_blocks_triggers(controller_index, assignments)
        self._fire_delayed_block_triggers(controller_index, assignments)
        self._fire_becomes_blocked_triggers(controller_index, assignments)
        self._apply_flanking(controller_index)
        # CR 509.4/802.4: once every defending player has declared, the active
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

    def _can_block_attacker(self, blocker: Permanent, attacker: Permanent) -> bool:
        if attacker.metadata.get("cant_be_blocked_until_eot"):
            return False

        # One-shot blanket restrictions ("Creatures without flying can't block
        # this turn", Destructive Tampering). Keywords are asked of layer 6, so
        # a creature granted flying after the spell resolved may block.
        for entry in self.blocking_restrictions_until_eot:
            filt = entry.get("filter") or {}
            type_filter = filt.get("type_filter", "creature")
            if type_filter == "creature" and not blocker.is_creature:
                continue
            if type_filter != "creature" and not blocker.has_type(type_filter):
                continue
            if any(
                not self._has_keyword(blocker, kw)
                for kw in filt.get("with_keywords") or []
            ):
                continue
            if any(
                self._has_keyword(blocker, kw)
                for kw in filt.get("without_keywords") or []
            ):
                continue
            return False

        # **The blocker's own restriction, which nothing asked.**
        # "This creature can't block." compiled to a `cant_block` instruction,
        # reported the card supported, and was read by no one — the comment in
        # `engine/combat_restrictions.py` named this file as the enforcement
        # site, and this file had never mentioned the kind. Every question below
        # is about the *attacker*, which is how a restriction on the blocker
        # came to have no home at all.
        #
        # Off the effective card, like every other read here: a Clone of a
        # creature that can't block can't block either (CR 707.2).
        blocker_program = compile_card_oracle(blocker.effective_card)
        if "cant_block" in {i.kind for i in blocker_program.instructions}:
            return False
        # And the Aura-imposed half (Faith's Fetters).
        if aura_restriction_active(blocker, "cant_block"):
            return False
        # And the granted half (Panic): a restriction a spell put on this one
        # creature for the turn, swept by the cleanup step. Read beside the two
        # above because all three answer the same question about the blocker,
        # and a reader that knew only two of them would let the third through.
        if blocker.metadata.get(CANT_BLOCK_UNTIL_EOT):
            return False

        attacker_program = compile_card_oracle(attacker.effective_card)
        attacker_kinds = {i.kind for i in attacker_program.instructions}

        if "cant_be_blocked" in attacker_kinds:
            return False

        # "This creature can't be blocked as long as …" (Tome Anima). Asked
        # now rather than materialized on a recompute, because the condition
        # can change between recomputes and blocking is the read that matters.
        attacker_seat = self.controller_index_of(attacker)
        if attacker_seat is not None and any(
            cs.kind == "conditional_static"
            and cs.payload.get("cant_be_blocked")
            and conditional_static_holds(
                self, attacker_seat, attacker, cs.payload.get("condition") or {}
            )
            for cs in attacker_program.instructions
        ):
            return False

        attacker_has_flying = self._has_keyword(attacker, "flying")
        blocker_has_flying = self._has_keyword(blocker, "flying")
        blocker_has_reach = self._has_keyword(blocker, "reach")
        if attacker_has_flying and not (blocker_has_flying or blocker_has_reach):
            return False

        # Fear: attacker can't be blocked except by artifact creatures and/or black creatures
        attacker_has_fear = self._has_keyword(attacker, "fear")
        if attacker_has_fear:
            # Both halves through the layers: an animated artifact is an
            # artifact creature (613 layer 4) and a laced creature is black
            # (layer 5). No card in this pool has fear, so nothing here is
            # observable yet — which is exactly why it was written against the
            # printed card and never noticed.
            is_artifact_creature = blocker.is_creature and blocker.has_type("artifact")
            is_black_creature = "B" in blocker.effective_colors
            if not (is_artifact_creature or is_black_creature):
                return False

        # Protection (CR 702.16f): an attacking creature with protection from a
        # quality can't be blocked by creatures that have that quality.
        if self._is_protected_from(attacker, blocker):
            return False

        # "…can't be blocked by Walls" / "…by artifact creatures" — one
        # restriction whose noun phrase is payload (engine/combat_restrictions).
        # It used to be a Wall-only kind tested with a literal `has_type("wall")`;
        # the phrase is a filter now, so Argothian Pixies and Artifact Ward cost
        # a table row rather than a second branch here.
        #
        # Asked of `subject_matches`, which reads the layer system: an animated
        # artifact land *is* an artifact creature (613 layer 4) and Primal Clay's
        # third body *is* a Wall, and the printed line says otherwise for both.
        # An Aura prints the same restriction about the creature it is attached
        # to (Artifact Ward), so the two channels are unioned here rather than
        # asked in two places: the restriction is the same sentence and the
        # difference is only whose text it is printed on.
        from ..subject_filters import subject_matches

        # "Target creature can't be blocked by Walls **this turn**" (Tower of
        # Coireall): the same restriction granted for a turn rather than printed
        # on the attacker. A third channel beside the two below rather than a
        # branch of its own, because the class of blocker is the same filter
        # payload in all three — the difference is only where the record lives.
        from ..combat_restrictions import (
            granted_blocker_filters,
            restriction_condition_holds,
        )

        for described in granted_blocker_filters(attacker):
            if subject_matches(self, blocker, described):
                return False

        for restriction in (
            *attacker_program.instructions,
            *attached_combat_restrictions(attacker),
        ):
            # "…can't be blocked **except by** X" (Elven Riders, Evil Eye of
            # Orms-by-Gore, Seeker). The inverse of the restriction below, and
            # its own branch because it is a *whitelist*: a blocker matching no
            # member of the union is illegal, where the restriction below only
            # rejects blockers that do match. An empty union never reaches here
            # — `combat_restriction_for` refuses a phrase it cannot parse
            # rather than admitting one that would allow everything.
            if restriction.kind == "cant_be_blocked_except_by":
                allowed = restriction.payload.get("allowed_blockers") or ()
                if not any(
                    subject_matches(self, blocker, described) for described in allowed
                ):
                    return False
                continue
            if restriction.kind != "cant_be_blocked_by":
                continue
            # "…**as long as defending player controls a snow land**."
            # (Arctic Foxes.) A qualifier on the restriction, stripped once in
            # `combat_restrictions` rather than written into every row — and
            # asked here, because a condition read at the gate and ignored at
            # the enforcement would be an evasion ability that applies on every
            # board. The seat "defending player" names is the blocker's
            # controller; "you" is the attacker's, CR 109.5's observer for the
            # ability this text is.
            if not restriction_condition_holds(
                self,
                restriction.payload.get("condition"),
                observer=self.controller_index_of(attacker),
                defender=self.controller_index_of(blocker),
            ):
                continue
            # The printed noun phrase, already read into subject filters by
            # `combat_restrictions._blocker_union` — the same vocabulary the
            # whitelist form above uses. This used to be four payload keys
            # translated back into filter keys by four branches here: two
            # vocabularies for one thing, so a noun both parsers could read
            # needed a capture *and* a branch, and without the branch the
            # restriction was parsed and never applied.
            #
            # Every field still goes through `subject_matches`, so the layers
            # answer: a Grizzly Bears laced red is a red creature, an animated
            # artifact is an artifact creature, and a pumped 2/2 has power 4.
            for described in restriction.payload.get("blocker_filters") or ():
                if subject_matches(self, blocker, described):
                    return False

        # Invisibility's "can't be blocked except by Walls" used to be its own
        # aura restriction and its own check here. It is not any more: the loop
        # above reads the whitelist form through the same subject rewrite as
        # every other attached restriction, so Invisibility, Seeker and Elven
        # Riders are one rule printed on three different kinds of card.

        # "Can't block creatures with power N or greater" (Ironclaw Orcs). The
        # threshold rides on the payload rather than the instruction kind, so a
        # card printed with any other number is the same restriction.
        blocker_program = compile_card_oracle(blocker.effective_card)
        power_block = next(
            (i for i in blocker_program.instructions if i.kind == "cant_block_power_n_or_greater"),
            None,
        )
        if power_block is not None and attacker.effective_power >= int(power_block.payload["power"]):
            return False

        # "...can't block creatures with power 3 or greater **unless you pay
        # {1}**." (Hipparion.) CR 509.1b's restriction with CR 509.1d's cost
        # hung off it. This is the *gate* half - a cost the defender cannot
        # cover makes the block illegal - and `_block_mana_costs_of` is the one
        # reader, shared with the charge in `declare_blockers`, so a block can
        # never be accepted and then left unpaid.
        #
        # Per-creature, which is all a per-pair predicate can honestly say: the
        # declaration-wide check adds several blockers' costs together, the way
        # `_declaration_mana_plan` does on the attack side.
        blocker_seat = self.controller_index_of(blocker)
        if blocker_seat is not None:
            for cost in self._block_mana_costs_of(blocker, attacker):
                if plan_payment(
                    self.players[blocker_seat].mana_pool,
                    untapped_mana_lands(self.controlled_by(blocker_seat)),
                    cost,
                ) is None:
                    return False

        # "This creature can block only creatures with flying." (Shacklegeist.)
        # The mirror of the restriction above: that one names what may not be
        # blocked, this names the only thing that may — so an attacker *without*
        # the word is what fails. Asked of layer 6, so a creature granted flying
        # can be blocked by it and one that lost flying cannot.
        only_with = next(
            (
                i for i in blocker_program.instructions
                if i.kind == "can_block_only_with_keyword"
            ),
            None,
        )
        if only_with is not None and not self._has_keyword(
            attacker, str(only_with.payload.get("required_keyword") or "")
        ):
            return False

        # Landwalk (CR 702.14): the attacker can't be blocked if the defending
        # player controls a land of the matching basic type. The blocker is one of
        # the defending player's creatures, so its controller is the defender.
        if self._attacker_has_active_landwalk(attacker, blocker):
            return False

        return True

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
        return costs

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
            untapped_mana_lands(self.controlled_by(controller_index)),
            total,
        )

    def _pay_block_declaration_mana(
        self, controller_index: int, total: dict[str, int], plan
    ) -> None:
        """Spend the plan :meth:`_block_declaration_mana_plan` made (CR 509.1f).

        Floating mana first and then untapped lands - the stated policy every
        cost with no priority window behind it takes in this engine. CR 509.1e
        does give the defender a window to activate mana abilities; the engine
        takes it on their behalf rather than pausing the turn-based action,
        which is the same shortcut the attack side takes at CR 508.1g.
        """
        if plan is None:
            return
        defender = self.players[controller_index]
        for symbol, amount in plan.from_pool.items():
            defender.mana_pool[symbol] = int(defender.mana_pool.get(symbol, 0)) - amount
        for land in plan.tapped:
            self.become_tapped(land)
        self.log.append(
            f"{defender.name} paid {mana_cost_label(total)} to declare blockers"
        )

    def _negated_evasion_abilities(self) -> frozenset[str]:
        """Evasion abilities that currently restrict no block at all, because
        some permanent on the battlefield says they don't (CR 509.1b).

        "Creatures with islandwalk can be blocked as though they didn't have
        islandwalk" (Undertow and its seven Legends siblings). The source is a
        permanent nobody is attacking or blocking, so this is asked of the
        **board** rather than of the attacker — and of every permanent, not
        only the defender's: the sentence says "creatures", so an Undertow its
        own controller is attacking through switches off their islandwalk too.
        """
        negated: set[str] = set()
        for perm in self.all_permanents():
            negated.update(negated_evasion_abilities(perm.effective_card.oracle_text or ""))
        return frozenset(negated)

    def _attacker_has_active_landwalk(self, attacker: Permanent, blocker: Permanent) -> bool:
        defender_index = self.controller_index_of(blocker)
        if defender_index is None:
            return False
        negated = self._negated_evasion_abilities()
        # Every ability the attacker currently has, asked one at a time whether
        # it is a landwalk — rather than a fixed table of walk words, which
        # could not hold a quality-first one. Computed through CR 613 layer 6,
        # so a landwalk granted by an Aura (Burrowing, Fishliver Oil) counts
        # alongside a printed one and ends when the Aura does, without this
        # reader knowing an Aura exists; the `has_<walk>` metadata flags an
        # older channel stamped are collected into layer 6 too.
        for ability in sorted(computed_abilities(attacker)):
            requirement = landwalk_requirement(ability)
            if requirement is None:
                continue
            # Switched off for blocking, but **not removed** — CR 702.14b makes
            # landwalk an evasion ability and this text lifts the restriction it
            # creates, nothing more. `_has_keyword` still answers True
            # everywhere else, which is why the skip lives here rather than as a
            # layer-6 removal.
            # A named ability ("islandwalk") or the whole family, which is what
            # "creatures with **landwalk abilities**" negates (Staff of the
            # Ages). The family marker covers a *qualified* landwalk too — "snow
            # forestwalk" is a landwalk, and `requirement` is not None precisely
            # because it is one.
            if ability in negated or LANDWALK in negated:
                continue
            for perm in self.controlled_by(defender_index):
                if land_satisfies(perm, requirement):
                    return True
        return False

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

    def _remove_blocker_from_combat(self, defender_player_index: int, blocker_index: int) -> None:
        """Take a creature out of combat as a blocker (CR 702.22f-style
        cleanup, but for the blocking side): drop it from ``combat_blockers``
        and unblock any attacker whose only blocker it was. Shared by False
        Orders' "remove target creature ... from combat" and Ydwen Efreet's
        "remove this creature from combat" (coin-flip block-fail)."""
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
        for a_idx in freed_attackers:
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

    def _fire_creature_blocks_triggers(self, controller_index: int, assignments: dict[int, list[int]]) -> None:
        """Put each blocker's own "whenever this creature blocks" triggers on
        the stack (e.g. Ydwen Efreet's coin flip) — once per blocking
        creature declared this call, regardless of how many attackers it
        blocks (unlike Cockatrice's per-attacker-blocked firing).

        "…blocks **a creature with flying**" (Snarespinner) narrows the same
        trigger by what was blocked, so it fires once for each blocked attacker
        the filter admits. The unnarrowed form keeps its once-per-blocker
        firing — CR 509.3c/509.3d draw exactly that line, and the filter's
        presence is what tells the two apart.
        """
        from ..auras import attached_subject_triggers
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
                    firing_contexts: list[dict] = [{
                        "blocked_permanent_ids": [
                            attacker.permanent_id for _, attacker in blocked
                        ],
                    }]
                else:
                    firing_contexts = [
                        {"blocked_permanent_ids": [attacker.permanent_id]}
                        for _, attacker in blocked
                        if trigger_subject_matches(
                            self, trig, "blocked", attacker,
                            observer=source_seat, source=blocker,
                        )
                    ]
                for firing_context in firing_contexts:
                    self._stack_push(
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
                    self.log.append(f"{source.card.name} triggered on block (added to stack)")
            # "Whenever **enchanted creature** attacks or blocks" (Imprison) —
            # the block half of the union whose attack half fires in
            # declare_attackers_step. Something attached to the blocker, not
            # the blocker itself: an Aura's ability is the Aura's (CR 113.7a),
            # so it is on no `effective_card` the scan above reads.
            for seat, attachment, trig in attached_subject_triggers(
                self, blocker, {"creature_attacks_or_blocks"}, "combatant_attached",
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
            for trig in matching_triggers(
                permanent.effective_card, condition_kinds={"attacks_unblocked"}
            ):
                self._stack_push(
                    StackItem(
                        card=permanent.card,
                        caster_index=controller_index,
                        target_player_index=controller_index,
                        target_permanent_index=None,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=permanent,
                        ability_text=trig.source_line,
                        trigger_context={
                            "trigger_defending_player_index": defending_index,
                        },
                    )
                )
                self.log.append(
                    f"{permanent.card.name} triggered (attacked and wasn't blocked)"
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
        from ..auras import attached_subject_triggers
        from ..events import trigger_subject_matches
        from ..game_types import StackItem

        blockers_of: dict[int, tuple[Permanent, list[Permanent]]] = {}
        for _, blocker, blocked in self._resolved_block_pairs(
            controller_index, assignments
        ):
            for attacker_idx, attacker in blocked:
                blockers_of.setdefault(attacker_idx, (attacker, []))[1].append(blocker)
        for attacker_idx, (attacker, blockers) in blockers_of.items():
            seat = self.active_player_index
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
                    self, attacker, {"creature_blocks_or_blocked_by"},
                    "combatant_attached",
                )
            ]
            for source, source_seat, trig in watchers:
                if not trig.condition.payload.get("blocker_filter"):
                    matched = [] if already_blocked else blockers[:1]
                else:
                    matched = [
                        b for b in blockers
                        if trigger_subject_matches(
                            self, trig, "blocker", b, observer=source_seat,
                            source=attacker,
                        )
                    ]
                for blocker in matched:
                    # **The blocker is what the trigger bound**, so it is the
                    # stack item's target: "destroy that Wall" (Battering Ram)
                    # names the creature that blocked, and by the time the
                    # ability resolves nothing else could say which. Stamped by
                    # id as well as by slot, because a removal in between
                    # renumbers every later one (CR 400.7).
                    blocker_seat = self.controller_index_of(blocker)
                    blocker_slot = self.battlefield_index_of(blocker)
                    self._stack_push(
                        StackItem(
                            card=source.card,
                            caster_index=source_seat,
                            target_player_index=(
                                blocker_seat if blocker_seat is not None else seat
                            ),
                            target_permanent_index=blocker_slot,
                            target_permanent_id=blocker.permanent_id,
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
                                # The pair this firing is about, by stable id
                                # and under the key the *blocks* half already
                                # writes. `block_pair_permanents` prefers it to
                                # the item's target, which is the same blocker
                                # here — but an ability whose source is an Aura
                                # attached to the attacker has no reason to
                                # carry the blocker as its target at all.
                                "blocked_permanent_ids": [blocker.permanent_id],
                            },
                        )
                    )
                    self.log.append(
                        f"{source.card.name} triggered on becoming blocked (added to stack)"
                    )

    def _apply_temporary_buff(self, permanent: Permanent, power: int, toughness: int) -> None:
        """Apply an "until end of turn" P/T change that the cleanup step reverts."""
        add_pt_modifier(permanent, power, toughness, until="end_of_turn")

    def _apply_flanking(self, controller_index: int) -> None:
        """Resolve Flanking (CR 702.25) on declared blocks: each blocking
        creature without flanking gets -1/-1 until end of turn.

        **Rampage used to be resolved here too**, and it is not any more. CR
        702.23a defines it as a triggered ability, so it now compiles to one
        (``engine/rampage.py``) and goes on the stack through the
        becomes-blocked dispatcher above like every other trigger — which is
        what buys 702.23b's "calculated only once per combat, when the
        triggered ability resolves". Applied inline here it was calculated at
        declaration, read only the first of several instances (702.23c), and
        missed band-propagated blocks. Flanking stays because CR 702.25a is a
        triggered ability the engine has no *card* for: the keyword is not in
        `IMPLEMENTED_KEYWORDS`, so nothing in the pool reaches it, and moving
        it would be inventing a card's worth of work with nothing to verify it
        against.
        """
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            return
        attacker_controller = self.players[self.active_player_index]
        if controller_index < 0 or controller_index >= len(self.players):
            return
        defender = self.players[controller_index]

        # Scoped to attackers aimed at this defender (CR 802.4a) — flanking acts
        # on the block just declared against controller_index specifically.
        for attacker_idx, defending_idx in self.combat_attackers.items():
            if defending_idx != controller_index:
                continue
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blocker_indices = self._combat_blockers_for_attacker(attacker_idx)
            if not blocker_indices:
                continue

            # CR 702.25a: Flanking — each non-flanking blocker gets -1/-1 per instance.
            if self._has_keyword(attacker, "flanking"):
                for blocker_idx in blocker_indices:
                    if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                        continue
                    blocker = defender.battlefield[blocker_idx]
                    if self._has_keyword(blocker, "flanking"):
                        continue
                    self._apply_temporary_buff(blocker, -1, -1)
                    self.log.append(
                        f"{blocker.card.name} gets -1/-1 from {attacker.card.name}'s flanking"
                    )
        # Flanking may drop a blocker's toughness to 0; clean it up now.
        self.check_state_based_actions()
