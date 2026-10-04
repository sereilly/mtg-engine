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

from ..auras import (attached_block_ceiling, attached_combat_restrictions,
                     aura_restriction_active)
from ..combat_permissions import (ADDITIONAL_BLOCKS_UNTIL_EOT,
                                  CAN_BLOCK_ANY_NUMBER_UNTIL_EOT,
                                  MUST_BLOCK_ALL_UNTIL_EOT,
                                  MUST_BLOCK_ATTACKERS_UNTIL_EOT,
                                  MUST_BLOCK_UNTIL_EOT,
                                  CANT_BLOCK_ATTACKERS_UNTIL_EOT,
                                  CANT_BLOCK_UNTIL_EOT,
                                  printed_block_ceiling)
from ..combat_restrictions import (declaration_company_required,
                                  declaration_greater_power_required,
                                  declaration_tap_costs,
                                  participation_cap,
                                  restriction_condition_holds)
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
        modeled as effectively unlimited.

        The printed grant is counted over the compiled program's **static**
        lines, not over the whole oracle text. The same sentence is printed as
        an *activated* ability ("{W}: This creature can block an additional
        creature this turn.", Mounted Archers), and a text scan cannot tell the
        two apart -- it would hand that creature the extra block every combat,
        for free and whether or not the ability was ever activated, which is
        the "works more often than the card allows" failure rather than a
        missing one. The activated printing arrives instead through
        ``ADDITIONAL_BLOCKS_UNTIL_EOT`` below, written by its handler and swept
        with the turn.
        """
        if blocker.metadata.get(CAN_BLOCK_ANY_NUMBER_UNTIL_EOT):
            return 1_000_000
        printed = printed_block_ceiling(
            compile_card_oracle(blocker.effective_card).static_lines
        )
        # "That creature can block up to two additional creatures this turn."
        # (Yare.) A granted ceiling, added to the printed one for CR 509.1b's
        # reason: restrictions and the permissions that lift them are
        # cumulative, so a creature whose own line already blocks an additional
        # one keeps that and gains these.
        granted = int(blocker.metadata.get(ADDITIONAL_BLOCKS_UNTIL_EOT, 0) or 0)
        # "Enchanted creature can block any number of creatures." (Entangler.)
        # The printed permission one sentence-subject over, asked of the Auras
        # attached right now, so it ends when the Aura leaves.
        attached = attached_block_ceiling(blocker)
        return 1 + printed + granted + attached

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
        # and `ai_policy._legal_block_declaration` read.
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
        # CR 508.1g.
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

    def block_declaration_refusal(
        self,
        declared_blockers: list[Permanent],
    ) -> "tuple[Permanent, str] | None":
        """Which declared blocker's restriction this **set** disobeys, and why.

        CR 509.1b asks its restrictions of the declaration as a whole — "if any
        restrictions are being disobeyed, the declaration of blockers is
        illegal" — so none of these can live in ``_can_block_attacker``, a
        per-pair predicate with no way to say "and no more of you" (Caverns of
        Despair), "and at least two more of you" (Orcish Conscripts, and Mogg
        Flunkies' printed "can't block alone") or "and one of you bigger than
        me" (Okk).

        **Public, and returning the offending permanent, because the AI asks it
        too.** This is the blocking twin of
        :meth:`attack_declaration_refusal`, and it is written from the same
        defect: until this existed the three checks were inline in
        ``declare_blockers`` and nowhere else, so ``choose_combat_blockers``
        pruned against nothing. It proposed an over-cap map, the declaration
        refused it *whole*, ``ai_combat.declare_ai_blockers`` fell through to
        ``{}`` and ``web/game_flow`` to a safety valve that wipes every seat's
        blocks — the defender blocked with nobody, this combat and every later
        one, with no rule broken, nothing spent and nothing logged. The
        permanent is what lets the AI drop the creature this names instead.

        **One defending player's declaration, and only theirs (CR 802.4b).**
        These three checks used to add every *other* seat's ``combat_blockers``
        to their totals, on the reading that "each combat" spans the whole
        combat and a creature blocking under an earlier declaration does not
        stop being a blocker. CR 802.4b says the opposite in as many words:
        "When determining whether a defending player's blocks are legal, ignore
        any creatures attacking other players and **any blocking creatures
        controlled by other players**." So under a Caverns of Despair each
        defender may block with two, and the engine was refusing the second
        defender's legal declaration outright — a restriction firing more often
        than the rules allow, which is the same silent wrongness as one firing
        less often, pointed the other way. It is also why this takes a list and
        not a seat: once the other seats' blockers are ignored there is nothing
        left for a seat index to select.

        Asked of the collected ``Permanent`` objects rather than of indices: an
        index is unstable, and both callers have the permanents already.

        The Camouflage exemption is the **caller's**, not this predicate's: the
        piles were matched at random (CR 509.1a is replaced wholesale), so
        there is no declaration to declare illegal, and the declaration gate
        already skips this beside the four requirement checks it skips for the
        same reason.
        """
        # The board-wide cap first, for the reason the attack side takes it
        # first: it is the widest restriction here — it does not care who is
        # blocking or what they block — so it is the cheapest true answer, and
        # naming any other offender under it would be arbitrary in a different
        # way. The **last** blocker in the list is named, which makes the order
        # the caller hands them over in the caller's policy:
        # ``_legal_block_declaration`` sorts its worst block last, so a cap
        # drops that one.
        #
        # The permanents scanned are the whole board (``all_permanents``), not
        # one seat's: CR 802.4b scopes which *blockers* are counted, not where
        # the permanent printing the cap is allowed to sit.
        cap = participation_cap(self.all_permanents(), "block")
        if cap is not None and len(declared_blockers) > cap:
            return declared_blockers[-1], (
                f"no more than {cap} creature(s) can block each combat"
            )
        for blocker in declared_blockers:
            needed = declaration_company_required(blocker, "block")
            if needed is not None and len(declared_blockers) - 1 < needed:
                return blocker, (
                    f"{blocker.card.name} needs at least {needed} other "
                    "blocking creature(s)"
                )
        # "…unless a creature with **greater power** also blocks." (Okk.) The
        # comparison twin of the count above, and the same CR 509.1b
        # declaration-wide question.
        #
        # Power is read live off both creatures rather than off their printed
        # numbers: CR 613 computes it, so a pumped Okk needs a bigger companion
        # than one that has not been. ``is`` rather than an index comparison,
        # because the rule is about the *other* blockers and two 3/3s are not
        # one another.
        for blocker in declared_blockers:
            if not declaration_greater_power_required(blocker, "block"):
                continue
            if not any(
                other is not blocker
                and other.effective_power > blocker.effective_power
                for other in declared_blockers
            ):
                return blocker, (
                    f"{blocker.card.name} needs a blocking creature with "
                    "greater power beside it"
                )
        # "…unless you tap an untapped creature you control not declared as a
        # blocking creature this combat." (Hollow Warrior.) The attack side's
        # plan, asked of this defender's set (CR 802.4b scopes it to their own
        # blockers, which is all the list holds).
        owing = [b for b in declared_blockers if declaration_tap_costs(b, "block")]
        if owing:
            seat = self.controller_index_of(owing[0])
            if seat is None or self.declaration_tap_plan(
                seat, declared_blockers, "block"
            ) is None:
                return owing[-1], (
                    f"{owing[-1].card.name} has no untapped creature left to tap "
                    "for its block"
                )
        return None

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
        # "Each creature you control can't be blocked by more than one
        # creature." (Familiar Ground.) The same ceiling printed on a
        # *permanent* about a described set, so it is found by scanning the
        # board rather than read off the attacker's own program — and it is
        # collected into the same list, because CR 509.1b makes every
        # restriction apply and the smallest ceiling is still the answer.
        #
        # "You control" inside the noun phrase is relative to the permanent
        # printing it (CR 109.5), which is what scopes Familiar Ground to its
        # own controller's creatures; `observer` is that seat and `source` is
        # that permanent, exactly as the attack-side scan one file over asks.
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if instr.kind != "matching_cant_be_blocked_by_more_than":
                    continue
                if subject_matches(
                    self, attacker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    caps.append(int(instr.payload.get("count", 1)))
        return min(caps) if caps else None

    def _board_compels_block(self, blocker: Permanent) -> bool:
        """The board-reaching half of Watchdog's requirement.

        "All creatures block each combat if able." (Invasion Plans.) Printed on
        an enchantment nobody is blocking with, so it is found by scanning the
        board rather than read off the blocker's own program — the requirement
        twin of ``creatures_cant_block`` in ``_can_block_attacker`` and the
        block-side mirror of ``_must_attack_if_able``'s ``creatures_must_attack``
        scan, over the same ``subject`` payload and the same ``subject_matches``.

        The observer is the seat whose ability this is (CR 109.5), so a
        "creatures **you** control" printing would compel that seat's creatures
        rather than the blocker's controller's.
        """
        for source_perm in self.all_permanents():
            source_seat = self.controller_index_of(source_perm)
            for instr in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if instr.kind != "creatures_must_block":
                    continue
                if subject_matches(
                    self, blocker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    return True
        return False

    def _can_block_attacker(self, blocker: Permanent, attacker: Permanent) -> bool:
        if attacker.metadata.get("cant_be_blocked_until_eot"):
            return False

        # One-shot blanket restrictions ("Creatures without flying can't block
        # this turn", Destructive Tampering). Keywords are asked of layer 6, so
        # a creature granted flying after the spell resolved may block.
        for entry in self.blocking_restrictions_until_eot:
            # A toll is not a ban. "Creatures can't block **unless their
            # controller pays {X}**" (War Cadence) is CR 509.1b's second half —
            # a restriction with a condition that can be met — so its entry sits
            # here beside the blanket ones and is answered as a *cost*, by
            # ``_block_toll_of`` and the gate below. Read as a prohibition it
            # would stop every creature the noun phrase names from blocking at
            # all, which on War Cadence is the whole defending board.
            if entry.get("toll"):
                continue
            # "**Only** creatures in the chosen piles can block this turn."
            # (Stand or Fall.) The blocking twin of the attack gate's two
            # readings, in the same order and for the same reasons: the
            # creatures a resolution *named* are excepted by id (CR 400.7 — one
            # that left and returned is a new object the sentence never named),
            # and an entry scoped to one player's creatures is inert for every
            # other seat's.
            if blocker.permanent_id in (entry.get("except_permanent_ids") or ()):
                continue
            scoped_seat = entry.get("controller_seat")
            if scoped_seat is not None and self.controller_index_of(blocker) != scoped_seat:
                continue
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
        # Read as an *instruction* rather than out of a kind set, exactly as the
        # attack gate reads its twin and for the same reason: the clause can be
        # qualified — "…**if an enchantment is on the battlefield**" (Wirecat) —
        # and a kind-set membership test drops the condition and stops the
        # creature blocking for good. Every printed clause separately, because
        # CR 509.1b makes restrictions cumulative: one whose condition is false
        # answers only itself.
        for restriction in blocker_program.instructions:
            if restriction.kind != "cant_block":
                continue
            if restriction_condition_holds(
                self,
                restriction.payload.get("condition"),
                # CR 109.5: "you" inside the noun phrase is the seat whose
                # ability this is, which is the blocker's controller. The
                # defending player *is* that seat in this engine's combats, and
                # is passed as such rather than assumed equal.
                observer=self.controller_index_of(blocker),
                defender=self.controller_index_of(blocker),
                # "Another" is measured against the permanent whose line this
                # is — the blocker itself.
                source=blocker,
            ):
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
        # And the *named-attacker* half (Duct Crawler): "can't block **this
        # creature** this turn" denies one pairing rather than every block, so
        # it is asked here — where the pair is in hand — rather than beside the
        # three blanket reads above. By ``permanent_id``, so an attacker that
        # left and came back is a new object the old denial does not name
        # (CR 400.7).
        denied_attackers = blocker.metadata.get(CANT_BLOCK_ATTACKERS_UNTIL_EOT)
        if denied_attackers and attacker.permanent_id in denied_attackers:
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

        # "This creature can't block unless you control **more lands than
        # attacking player**." (Monstrous Hound.) The blocker's own comparison
        # between two boards, read off its program beside the three blanket
        # denials above rather than beside the attacker questions below —
        # nothing about the attacker enters it except which seat declared it.
        #
        # The seat compared against is the attacker's controller rather than the
        # active player: CR 508.1a makes them the same in every combat this
        # engine can build, and reading it off the attacker is the answer that
        # stays right if a creature changes hands mid-combat. Counted through
        # `subject_matches` with the blocker's controller as observer, for the
        # attack twin's reason — the phrase is the blocker's card's, so "you" is
        # its controller (CR 109.5).
        outnumber = next(
            (
                i for i in blocker_program.instructions
                if i.kind == "cant_block_unless_you_control_more"
            ),
            None,
        )
        if outnumber is not None:
            described = dict(outnumber.payload.get("subject") or {})
            mine_seat = self.controller_index_of(blocker)
            theirs_seat = self.controller_index_of(attacker)

            def _counted(seat: int | None) -> int:
                return sum(
                    1 for perm in self.controlled_by(seat)
                    if subject_matches(
                        self, perm, described, observer=mine_seat, source=blocker
                    )
                )

            if theirs_seat is None or _counted(mine_seat) <= _counted(theirs_seat):
                return False

        attacker_program = compile_card_oracle(attacker.effective_card)
        attacker_kinds = {i.kind for i in attacker_program.instructions}

        # "This creature can't be blocked." (Phantom Warrior.) Read as an
        # *instruction* rather than out of the kind set, exactly as the
        # ``cant_block`` gate above reads its twin and for the same reason: the
        # clause can be qualified — "…**as long as defending player controls an
        # artifact**" (Bouncing Beebles) — and a kind-set membership test drops
        # the condition and makes the creature unblockable for good. Every
        # printed clause separately, because CR 509.1b makes restrictions
        # cumulative: one whose condition is false answers only itself.
        for restriction in attacker_program.instructions:
            if restriction.kind != "cant_be_blocked":
                continue
            if restriction_condition_holds(
                self,
                restriction.payload.get("condition"),
                # CR 109.5: "you" inside the noun phrase is the attacker's
                # controller, whose card this is. "Defending player" is the seat
                # being attacked, which for a legal block is the blocker's
                # controller (CR 509.1a) — read off the blocker rather than the
                # combat map because that is the seat this call is deciding for.
                observer=self.controller_index_of(attacker),
                defender=self.controller_index_of(blocker),
                source=attacker,
            ):
                return False
        if any(
            # "Enchanted creature can't be blocked." (Cloak of Mists.) The
            # attached channel of the same restriction, asked beside the
            # attacker's own program for the reason `cant_block` above is asked
            # both ways: the sentence is one rule, and a reader that knew only
            # the printed half would enforce it for Phantom Warrior and not for
            # the creature an Aura made unblockable.
            restriction.kind == "cant_be_blocked"
            for restriction in attached_combat_restrictions(attacker)
        ):
            return False

        # "This creature can't be blocked **as long as it's attacking alone**."
        # (Dream Prowler.) CR 506.5's condition, asked at the declaration
        # rather than materialized on a recompute — for the reason the
        # conditional static below is: the answer changes the moment another
        # attacker joins or leaves, and blocking is the read that matters.
        # ``creature_attacking_alone`` is the one reader of the rule, shared
        # with Errantry's attack-side restriction.
        if (
            "cant_be_blocked_while_attacking_alone" in attacker_kinds
            and self.creature_attacking_alone(attacker)
        ):
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

        # Shadow (CR 702.28b), and it is the only evasion ability in this
        # function that restricts **both** creatures. "A creature with shadow
        # can't be blocked by creatures without shadow, and a creature without
        # shadow can't be blocked by creatures with shadow." Two prohibitions in
        # one sentence, which is why the test is an inequality rather than the
        # `attacker_has_x and not blocker_has_x` shape flying and fear use six
        # lines up: a shadow creature is *unable to block the ground*, and a
        # reading that kept only the first half would turn a printed drawback
        # into pure evasion — silently, and in the player's favour.
        #
        # Both reads through layer 6, like every other keyword here, so a
        # granted shadow (Dauthi Embrace, Shadow Rift) and a removed one
        # (Reality Anchor) are answered by the same two lines.
        attacker_has_shadow = self._has_keyword(attacker, "shadow")
        blocker_has_shadow = self._has_keyword(blocker, "shadow")
        if blocker_has_shadow and not attacker_has_shadow:
            return False
        if attacker_has_shadow and not blocker_has_shadow:
            # "This creature can block creatures with shadow as though it had
            # shadow." (Heartwood Dryad, Wall of Diffusion.) A permission over
            # the *first* half only, so it is asked here and not folded into
            # `blocker_has_shadow` above: the Dryad does not have shadow, and a
            # reading that pretended it did would forbid it from blocking the
            # ground creatures it is printed to stop. CR 702.28b is two
            # prohibitions and this text lifts exactly one of them.
            if not any(
                restriction.kind == "can_block_as_though_it_had"
                and restriction.payload.get("keyword") == "shadow"
                for restriction in (
                    *blocker_program.instructions,
                    *attached_combat_restrictions(blocker),
                )
            ):
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
            # CR 119.4: a player may pay N life only with a life total of at
            # least N. Asked here so an unpayable toll makes the block illegal
            # rather than being discovered at the charge, where CR 509 has
            # already locked the declaration in.
            if owed and self.players[blocker_seat].life < owed:
                return False
        if blocker_seat is not None:
            # The turn-scoped toll (War Cadence), owed once for this creature
            # rather than once per attacker it blocks — see ``_block_toll_of``.
            # Gated here as well as charged below for the reason every other
            # cost in this file is: a per-pair predicate is what "blocks if
            # able" reads, and a defender who cannot cover the toll is not able.
            toll = self._block_toll_of(blocker)
            if toll and plan_payment(
                self.players[blocker_seat].mana_pool,
                untapped_mana_lands(self.controlled_by(blocker_seat)),
                toll,
            ) is None:
                return False
            for cost in self._block_mana_costs_of(blocker, attacker):
                if plan_payment(
                    self.players[blocker_seat].mana_pool,
                    untapped_mana_lands(self.controlled_by(blocker_seat)),
                    cost,
                ) is None:
                    return False
            # "…unless you tap an untapped creature you control not declared as
            # a blocking creature this combat." (Hollow Warrior.) The tap cost,
            # gated for this creature alone like the mana above; several at
            # once are `block_declaration_refusal`'s question.
            if declaration_tap_costs(blocker, "block") and self.declaration_tap_plan(
                blocker_seat, [blocker], "block"
            ) is None:
                return False

        # "This creature can block only creatures with flying." (Shacklegeist.)
        # The mirror of the restriction above: that one names what may not be
        # blocked, this names the only thing that may — so an attacker *without*
        # the word is what fails. Asked of layer 6, so a creature granted flying
        # can be blocked by it and one that lost flying cannot.
        #
        # "**Enchanted creature** can block only creatures with flying." (Air
        # Bladder.) The same sentence printed on an Aura about its host, so the
        # attached channel is unioned in exactly as it is for
        # ``cant_block_subject`` above — one rule, and the only difference is
        # whose text it is printed on. Every one of them is asked: CR 509.1b
        # makes restrictions cumulative, and two of them naming two keywords
        # both have to be met.
        for only_with in (
            *blocker_program.instructions,
            *attached_combat_restrictions(blocker),
        ):
            if only_with.kind != "can_block_only_with_keyword":
                continue
            if not self._has_keyword(
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
        from ..auras import attached_subject_triggers
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
        ``handlers/_common.block_pair_permanents`` already reads, so the effect
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
        events. ``events._board_wide_block_filter`` is what keeps each condition
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
