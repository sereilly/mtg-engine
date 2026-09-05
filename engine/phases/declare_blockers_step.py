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
from ..combat_permissions import (ADDITIONAL_BLOCKS_UNTIL_EOT,
                                  CAN_BLOCK_ANY_NUMBER_UNTIL_EOT,
                                  MUST_BLOCK_ALL_UNTIL_EOT,
                                  CANT_BLOCK_UNTIL_EOT)
from ..combat_restrictions import declaration_company_required, participation_cap
from ..evasion_negation import negated_evasion_abilities
from ..landwalk import LANDWALK, land_satisfies, landwalk_requirement
from ..mana_payment import mana_cost_label, plan_payment, untapped_mana_lands
from ..delayed_triggers import fire_delayed_triggers
from ..layer_bridge import computed_abilities
from ..subject_filters import subject_matches
from ..models import Permanent
from ..oracle import compile_card_oracle
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


class DeclareBlockersStepMixin:
    def _max_blocks_for(self, blocker: Permanent) -> int:
        """How many attackers this creature may block at once (CR 509.1b). Normally
        1; each "can block an additional creature" grant (Two-Headed Giant of
        Foriys) adds one. Blaze of Glory grants "can block any number of creatures",
        modeled as effectively unlimited."""
        if blocker.metadata.get(CAN_BLOCK_ANY_NUMBER_UNTIL_EOT):
            return 1_000_000
        text = blocker.effective_card.oracle_text.lower()
        # "That creature can block up to two additional creatures this turn."
        # (Yare.) A granted ceiling, added to the printed one for CR 509.1b's
        # reason: restrictions and the permissions that lift them are
        # cumulative, so a creature whose own line already blocks an additional
        # one keeps that and gains these.
        granted = int(blocker.metadata.get(ADDITIONAL_BLOCKS_UNTIL_EOT, 0) or 0)
        return 1 + text.count("can block an additional creature") + granted

    def declare_blockers(
        self,
        controller_index: int,
        blocker_to_attacker: dict[int, int | list[int]],
        *,
        acting_index: int | None = None,
        _camouflage_resolution: bool = False,
    ) -> tuple[bool, str]:
        """CR 509.1: *controller_index*'s declare-blockers turn-based action.

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
                if self._block_mana_costs_of(blocker, attacker):
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
            # CR 118.4 again, over the whole declaration: a per-pair predicate
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
            self._pay_block_declaration_mana(controller_index, block_total, block_plan)
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
        self._fire_creature_blocks_triggers(controller_index, assignments)
        self._fire_delayed_block_triggers(controller_index, assignments)
        self._fire_becomes_blocked_triggers(controller_index, assignments)
        self._fire_delayed_block_pair_triggers(controller_index, assignments)
        self._fire_delayed_becomes_blocked_triggers(controller_index, assignments)
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

    def _minimum_blockers(self, attacker: Permanent) -> int:
        """How many creatures must block *attacker* at once, or 1 if any may.

        CR 509.1b: every restriction applies, so the answer is the **largest**
        minimum any of them imposes — a creature with menace and Gorilla
        Berserkers' line needs three blockers, not two, and taking the first
        match would have made the second restriction free.

        Menace is read as a keyword (CR 702.111a defines it as exactly this
        sentence with N=2) and the printed template as a restriction, because
        that is how each is written on a card; both answer the same question,
        and one caller asking it once is what stops the two disagreeing.
        """
        minimum = 2 if self._has_keyword(attacker, "menace") else 1
        for restriction in (
            *compile_card_oracle(attacker.effective_card).instructions,
            *attached_combat_restrictions(attacker),
        ):
            if restriction.kind != "cant_be_blocked_by_fewer_than":
                continue
            minimum = max(minimum, int(restriction.payload.get("count", 1)))
        return minimum

    def _maximum_blockers(self, attacker: Permanent) -> int | None:
        """How many creatures may block *attacker* at once, or None if any may.

        "This creature can't be blocked by more than one creature." (Stalking
        Tiger.) The ceiling to :meth:`_minimum_blockers`' floor, and the
        **smallest** ceiling wins for the same CR 509.1b reason the largest
        minimum does: every restriction applies, so obeying only the loosest
        would let a declaration break the tighter one.
        """
        caps = [
            int(restriction.payload.get("count", 1))
            for restriction in (
                *compile_card_oracle(attacker.effective_card).instructions,
                *attached_combat_restrictions(attacker),
            )
            if restriction.kind == "cant_be_blocked_by_more_than"
        ]
        return min(caps) if caps else None

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

        # And the board-wide half: "Creatures with flying can't attack **or
        # block**…" (Katabatic Winds). A restriction printed on a permanent
        # that reaches every creature on every battlefield, so it is found by
        # scanning the board rather than read off the blocker's own program —
        # the block twin of `creatures_cant_attack` in
        # `declare_attackers_step.can_attack`, over the same `subject` payload
        # and asked through the same one filter reader. "You control" inside
        # that phrase is relative to the permanent carrying the restriction
        # (CR 109.5), which is what the observer seat says.
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(source_perm.effective_card).instructions:
                if instr.kind != "creatures_cant_block":
                    continue
                if subject_matches(
                    self, blocker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
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
        #
        # ``subject_matches`` is the module-level import at the top of this
        # file. It was re-imported here, which made the name *local to this
        # whole function* — so the board scan added above, several screens
        # earlier in the same body, raised ``UnboundLocalError`` on the first
        # blocker it was asked about. A function-level re-import of a name the
        # module already has is not a no-op.

        # "Target creature can't be blocked by Walls **this turn**" (Tower of
        # Coireall): the same restriction granted for a turn rather than printed
        # on the attacker. A third channel beside the two below rather than a
        # branch of its own, because the class of blocker is the same filter
        # payload in all three — the difference is only where the record lives.
        from ..combat_restrictions import (
            granted_blocker_filters,
            granted_blocker_whitelists,
            restriction_condition_holds,
        )

        for described in granted_blocker_filters(attacker):
            if subject_matches(self, blocker, described):
                return False

        # "Target creature can't be blocked this turn **except by Walls**."
        # (Joven's Tools.) The granted *whitelist*, and its own loop for the
        # reason the static whitelist below has its own branch: a blocker
        # matching no member of the union is illegal, where the blacklist above
        # only rejects the ones that do match.
        #
        # Every grant separately, because each is its own restriction
        # (CR 509.1b): two of them must both be satisfied, and a blocker legal
        # under either one alone is not legal under both.
        for allowed in granted_blocker_whitelists(attacker):
            if not any(
                subject_matches(self, blocker, described) for described in allowed
            ):
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
                    subject_matches(
                        self, blocker, described,
                        observer=self.controller_index_of(attacker),
                        source=attacker,
                    )
                    for described in allowed
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
            # The restriction belongs to the *attacker* (its own printed line,
            # or an Aura's about the creature it enchants), so CR 109.5's
            # observer is the attacker's controller and the ability's source is
            # the attacker itself. Passed here rather than left out because
            # `_blocker_union` admits the whole testable key set: a phrase
            # narrowed by "you control" or by "another" would otherwise be
            # carried into a call that cannot answer it and silently dropped,
            # which on a blocking restriction is a block the card forbids.
            for described in restriction.payload.get("blocker_filters") or ():
                if subject_matches(
                    self, blocker, described,
                    observer=self.controller_index_of(attacker), source=attacker,
                ):
                    return False

        # Invisibility's "can't be blocked except by Walls" used to be its own
        # aura restriction and its own check here. It is not any more: the loop
        # above reads the whitelist form through the same subject rewrite as
        # every other attached restriction, so Invisibility, Seeker and Elven
        # Riders are one rule printed on three different kinds of card.

        # "Can't block creatures with power N or greater" (Ironclaw Orcs),
        # "…white creatures with power 2 or greater" (Orcish Veteran). The
        # printed noun phrase rides on the payload rather than the instruction
        # kind, read through the same `subject_matches` the blocked-by
        # restriction above uses — so the layers answer here too: a pumped 2/2
        # has power 4 and a creature laced white is a white creature.
        # An Aura prints the same restriction about the creature it is attached
        # to (Ironclaw Curse), so the two channels are unioned here exactly as
        # they are for the blocked-by restriction above: one sentence, and the
        # only difference is whose text it is on.
        blocker_program = compile_card_oracle(blocker.effective_card)
        for restriction in (
            *blocker_program.instructions,
            *attached_combat_restrictions(blocker),
        ):
            if restriction.kind != "cant_block_subject":
                continue
            for described in restriction.payload.get("blockee_filters") or ():
                if subject_matches(
                    self, attacker, described,
                    observer=self.controller_index_of(blocker), source=blocker,
                ):
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
        # "Nonblue creatures can't block creatures you control **unless their
        # controller pays 1 life for each blocking creature they control**."
        # (Heat Wave.) CR 509.1d's cost paid in life rather than mana, and the
        # per-creature half of it — this predicate can honestly say "you could
        # afford this one", and the declaration below adds up the creatures.
        if blocker_seat is not None:
            owed = self._block_life_cost_of(blocker, attacker)
            # CR 118.4: a player may pay N life only with a life total of at
            # least N. Asked here so an unpayable toll makes the block illegal
            # rather than being discovered at the charge, where CR 509 has
            # already locked the declaration in.
            if owed and self.players[blocker_seat].life < owed:
                return False
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

        # "Creatures with flying can block only creatures with flying."
        # (Chaosphere.) The restriction above printed about the board, so it is
        # found by scanning every permanent rather than read off the blocker —
        # the source is a World Enchantment nobody is attacking or blocking, and
        # the sentence says "creatures", so it reaches both seats' creatures
        # including its own controller's.
        #
        # Both halves through ``subject_matches``, with **no** observer: neither
        # noun phrase names a seat, and passing one would let a future "creatures
        # you control" printing silently mean the wrong board. CR 509.1b keeps
        # every such restriction cumulative, so each one is asked separately.
        for permanent in self.all_permanents():
            for restriction in compile_card_oracle(
                permanent.effective_card
            ).instructions:
                if restriction.kind != "subject_can_block_only":
                    continue
                if not subject_matches(
                    self, blocker, restriction.payload.get("subject") or {}
                ):
                    continue
                if not subject_matches(
                    self, attacker, restriction.payload.get("allowed") or {}
                ):
                    return False

        # "**Blue creatures** can't block creatures you control." (Heat Wave.)
        # CR 509.1b's restriction printed about a described *set* of blockers
        # rather than about the permanent carrying it, so it is found by the
        # same board scan the block-only restriction above needs and for the
        # same reason: the source is an enchantment nobody is attacking or
        # blocking.
        #
        # The observer is the seat controlling the **restricting permanent**,
        # not the blocker's: "creatures **you** control" on the blockee half is
        # that seat's "you" (CR 109.5), and this is precisely the card that
        # proves it — read with the blocker's seat it would protect the wrong
        # player's creatures, which in a duel is the opposite of the printed
        # card.
        for source_seat, source_perm in self.permanents_with_controller():
            for restriction in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if restriction.kind != "subject_cant_block_subject":
                    continue
                if not subject_matches(
                    self, blocker, restriction.payload.get("subject") or {},
                    observer=source_seat, source=source_perm,
                ):
                    continue
                for described in restriction.payload.get("blockee_filters") or ():
                    if subject_matches(
                        self, attacker, described,
                        observer=source_seat, source=source_perm,
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
        from ..auras import attached_subject_triggers
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
                    matched = [] if already_blocked else blockers[:1]
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
                fire_delayed_triggers(
                    self, "source_blocks_or_blocked_by",
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
