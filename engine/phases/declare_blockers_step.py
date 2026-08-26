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
from ..evasion_negation import negated_evasion_abilities
from ..subject_filters import subject_matches
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..pt import add_pt_modifier
from ..static_bonuses import conditional_static_holds
from ..trigger_utils import matching_triggers

# Landwalk keyword → the basic land subtype the defender must control for the
# attacker to be unblockable (CR 702.14). Sourced from the attacker's printed
# keywords or a granted "has_<type>walk" metadata flag (e.g. Goblin King).
_LANDWALK_TO_LAND_TYPE = {
    "plainswalk": "plains",
    "islandwalk": "island",
    "swampwalk": "swamp",
    "mountainwalk": "mountain",
    "forestwalk": "forest",
    "desertwalk": "desert",
}


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

        for blocker_idx, raw_attackers in blocker_to_attacker.items():
            # A blocker may be assigned one attacker (the common case) or several
            # (a creature that can block additional creatures).
            attacker_indices = raw_attackers if isinstance(raw_attackers, (list, tuple, set)) else [raw_attackers]
            attacker_indices = [int(a) for a in attacker_indices]
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                return False, "blocker index out of range"
            blocker = defender.battlefield[blocker_idx]
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
                if self._left_right_block_illegal(attacker_idx, blocker_idx, blocker):
                    continue
                if attacker_idx not in assigned:
                    return False, (
                        f"{blocker.card.name} must block {attacker.card.name} "
                        "(Blaze of Glory)"
                    )

        # Nested by defender (CR 802): only this defender's own entry is replaced,
        # so an earlier defender's declaration in the same combat survives.
        if assignments:
            self.combat_blockers[controller_index] = assignments
        else:
            self.combat_blockers.pop(controller_index, None)
        self.combat_blockers_declared_by.add(controller_index)
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
            for _attacker_idx, attacker in blocked:
                if attacker.permanent_id not in record:
                    record.append(attacker.permanent_id)
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
            described = {}
            subtype = restriction.payload.get("blocker_subtype")
            if subtype:
                described["subtype_filter"] = subtype
            blocker_type = restriction.payload.get("blocker_type")
            if blocker_type:
                # "artifact **creatures**" — both halves, so a non-creature
                # artifact (which could not block anyway) is not what is
                # described and an animated one is.
                described["type_filter_all"] = [blocker_type, "creature"]
            colour = restriction.payload.get("blocker_color")
            if colour:
                # Through `subject_matches`, so it is layer 5 that answers: a
                # Grizzly Bears laced red is a red creature, and the printed
                # line would say otherwise.
                described["color_filter"] = colour
            power = restriction.payload.get("blocker_power")
            if power is not None:
                # "power 3 **or greater**", against the blocker's *effective*
                # power (CR 613 layer 7) — a 2/2 that has been pumped stops
                # being a legal blocker while it is pumped.
                described["power"] = {"op": "ge", "value": int(power)}
            if described and subject_matches(self, blocker, described):
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
        for walk, land_type in _LANDWALK_TO_LAND_TYPE.items():
            # Switched off for blocking, but **not removed** — CR 702.14b makes
            # landwalk an evasion ability and this text lifts the restriction it
            # creates, nothing more. `_has_keyword` still answers True below and
            # everywhere else, which is why the skip lives here rather than as a
            # layer-6 removal.
            if walk in negated:
                continue
            # Computed through CR 613 layer 6, so a landwalk granted by an Aura
            # (Burrowing, Fishliver Oil) counts alongside a printed one and
            # ends when the Aura does — without this reader knowing an Aura
            # exists. It used to read a `has_<walk>` flag the Aura stamped
            # directly, which put the grant outside the layer system and needed
            # a matching `lost_<walk>` flag to express removal; both are still
            # collected into layer 6 for the effects that set them (Magical
            # Hack remapping a landwalk word away).
            if not self._has_keyword(attacker, walk):
                continue
            for perm in self.controlled_by(defender_index):
                if perm.card.primary_type != "land":
                    continue
                if perm.has_type(land_type):
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
        from ..events import trigger_subject_matches
        from ..game_types import StackItem

        for blocker_idx, blocker, blocked in self._resolved_block_pairs(
            controller_index, assignments
        ):
            # "attacks or blocks" (Elder Gargaroth): the block half of the
            # union — the attack half fires in declare_attackers_step.
            for trig in matching_triggers(
                blocker.effective_card,
                condition_kinds={
                    "creature_blocks",
                    "creature_attacks_or_blocks",
                    # The joined sentence's *blocks* half. Its noun phrase lands
                    # under `blocked_filter` like a card that prints this half on
                    # its own, so nothing below has to know it was joined.
                    "creature_blocks_or_blocked_by",
                },
            ):
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
                            observer=controller_index, source=blocker,
                        )
                    ]
                for firing_context in firing_contexts:
                    self._stack_push(
                        StackItem(
                            card=blocker.card,
                            caster_index=controller_index,
                            # The blocker's own controller/index, so the coin-flip
                            # handler can remove IT from combat without re-deriving
                            # who owns it.
                            target_player_index=controller_index,
                            target_permanent_index=blocker_idx,
                            x_value=None,
                            ability_instruction=trig.instruction,
                            ability_effect_kind=trig.effect_kind,
                            source_permanent=blocker,
                            ability_text=trig.source_line,
                            trigger_context=firing_context,
                        )
                    )
                    self.log.append(f"{blocker.card.name} triggered on block (added to stack)")

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

    def _fire_becomes_blocked_triggers(
        self, controller_index: int, assignments: dict[int, list[int]]
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
        """
        if not (0 <= self.active_player_index < len(self.players)):
            return
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
            for trig in matching_triggers(
                attacker.effective_card,
                condition_kinds={
                    "creature_becomes_blocked",
                    # …and its *becomes blocked by* half, under `blocker_filter`.
                    "creature_blocks_or_blocked_by",
                },
            ):
                if not trig.condition.payload.get("blocker_filter"):
                    matched = blockers[:1]
                else:
                    matched = [
                        b for b in blockers
                        if trigger_subject_matches(
                            self, trig, "blocker", b, observer=seat, source=attacker
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
                            card=attacker.card,
                            caster_index=seat,
                            target_player_index=(
                                blocker_seat if blocker_seat is not None else seat
                            ),
                            target_permanent_index=blocker_slot,
                            target_permanent_id=blocker.permanent_id,
                            x_value=None,
                            ability_instruction=trig.instruction,
                            ability_effect_kind=trig.effect_kind,
                            source_permanent=attacker,
                            ability_text=trig.source_line,
                            # "That creature's controller" is the blocker's, and
                            # a blocker can leave before this resolves — so the
                            # seat is frozen now (CR 603.10), exactly as the
                            # death triggers freeze theirs.
                            trigger_context={
                                "event_subject_controller": blocker_seat,
                            },
                        )
                    )
                    self.log.append(
                        f"{attacker.card.name} triggered on becoming blocked (added to stack)"
                    )

    def _apply_temporary_buff(self, permanent: Permanent, power: int, toughness: int) -> None:
        """Apply an "until end of turn" P/T change that the cleanup step reverts."""
        add_pt_modifier(permanent, power, toughness, until_eot=True)

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
