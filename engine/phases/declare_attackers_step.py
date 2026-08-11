from __future__ import annotations

"""Declare attackers step (CR 508).

The active player declares attackers (and any attacking bands) as a turn-based
action, taps non-vigilance attackers, puts any attack triggers on the stack
(CR 508.2), then receives priority (CR 508.4) so the triggers resolve as players
pass. Also holds the attack-legality query (``can_attack``),
"must attack if able" enforcement, and the banding-declaration validation.
"""

from ..auras import aura_restriction_active
from ..models import Permanent, PlayerState
from ..oracle import compile_card_oracle
from ..trigger_utils import matching_triggers


class DeclareAttackersStepMixin:
    def declare_attackers(
        self,
        controller_index: int,
        attacker_indices: list[int],
        defending_player_index: int | None = None,
        bands: list[list[int]] | None = None,
        attacker_targets: dict[int, int] | None = None,
        attacker_planeswalker_ids: dict[int, int] | None = None,
    ) -> tuple[bool, str]:
        """Declare attackers (CR 508). Under CR 802 (attack multiple players), each
        attacker may name its own defending player via ``attacker_targets`` (attacker
        battlefield idx -> defending player idx). Any attacker not present in
        ``attacker_targets`` falls back to the shared ``defending_player_index`` —
        the original 2-player/back-compat shorthand of "everyone attacks this one
        opponent", still exactly how every existing (2-player) caller behaves.

        CR 508.1b: an attacker may instead attack a planeswalker an opponent
        controls — ``attacker_planeswalker_ids`` maps attacker battlefield idx to
        the attacked planeswalker's ``permanent_id``. Such an attacker's
        defending *player* (for blocks, restrictions and CR 508.5) is the
        planeswalker's controller, derived here rather than asked for twice."""
        if self.current_turn_phase != "combat" or self.current_step != "declare_attackers":
            return False, "attackers can only be declared during declare_attackers"
        if controller_index != self.active_player_index:
            return False, "only the active player may declare attackers"

        controller = self.players[controller_index]
        unique_indices = sorted(set(attacker_indices))
        living_opponents = self.opponents_of(controller_index)

        attacker_targets = dict(attacker_targets or {})
        attacker_planeswalker_ids = dict(attacker_planeswalker_ids or {})
        per_attacker_walker: dict[int, int] = {}
        for idx, walker_id in attacker_planeswalker_ids.items():
            if idx not in unique_indices:
                return False, f"planeswalker target given for non-attacker {idx}"
            walker = self.permanent_by_id(walker_id)
            if walker is None or not walker.has_type("planeswalker"):
                return False, "attacked planeswalker is not on the battlefield"
            walker_seat = self.controller_index_of(walker)
            if walker_seat is None or walker_seat == controller_index:
                return False, "a creature can only attack an opponent's planeswalker"
            # The walker names the defending player (CR 508.5); a contradictory
            # explicit seat for the same attacker is a malformed declaration.
            stated = attacker_targets.get(idx)
            if stated is not None and stated != walker_seat:
                return False, "attacker's defending player contradicts its attacked planeswalker"
            attacker_targets[idx] = walker_seat
            per_attacker_walker[idx] = walker_id

        per_attacker_defender: dict[int, int] = {}
        for idx in unique_indices:
            target = attacker_targets.get(idx, defending_player_index)
            if target is None:
                # No explicit target for this attacker: with exactly one living
                # opponent (2-player games, always) that's unambiguous — attack
                # them, exactly as every existing caller already assumes. Only a
                # genuine 3+ player choice requires an explicit target.
                if len(living_opponents) == 1:
                    target = living_opponents[0]
                else:
                    return False, f"no defending player chosen for attacker {idx}"
            per_attacker_defender[idx] = target

        living_opponents_set = set(living_opponents)
        for target in per_attacker_defender.values():
            if target < 0 or target >= len(self.players) or target == controller_index:
                return False, "invalid defending player"
            if target not in living_opponents_set:
                return False, "that player has already left the game"

        required_attackers: list[str] = []
        for idx, attacker in enumerate(controller.battlefield):
            if not self._is_creature(attacker) or attacker.tapped:
                continue
            if idx in unique_indices:
                continue
            if self._must_attack_if_able(attacker) and any(
                self.can_attack(attacker, opp) for opp in living_opponents
            ):
                required_attackers.append(attacker.card.name)
        if required_attackers:
            if len(required_attackers) == 1:
                return False, f"{required_attackers[0]} must attack if able"
            names = ", ".join(required_attackers)
            return False, f"{names} must attack if able"

        for idx in unique_indices:
            if idx < 0 or idx >= len(controller.battlefield):
                return False, "attacker index out of range"
            attacker = controller.battlefield[idx]
            if not self._is_creature(attacker):
                return False, "only creatures can attack"
            if attacker.tapped:
                return False, f"{attacker.card.name} is tapped"
            if not self.can_attack(attacker, per_attacker_defender[idx]):
                return False, f"{attacker.card.name} cannot attack"

        # CR 702.22c: validate any declared attacking bands before committing.
        validated_bands, band_error = self._validate_attacking_bands(
            bands, unique_indices, controller
        )
        if band_error is not None:
            return False, band_error

        self.combat_attackers = dict(per_attacker_defender)
        self.combat_attacked_planeswalkers = dict(per_attacker_walker)
        self.combat_defending_player_index = self._resolve_defending_player_index()
        self.combat_blockers = {}
        self.combat_blockers_declared_by = set()
        self.combat_bands = validated_bands
        self.combat_band_blocks = {}
        self.combat_banding_damage = {}
        self.combat_multiblock_damage = {}
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = True
        self.combat_blockers_locked = False
        self._prune_combat_state()

        for idx in unique_indices:
            attacker = controller.battlefield[idx]
            # CR 702.20b: attacking doesn't cause a creature with vigilance to tap.
            if not self._has_keyword(attacker, "vigilance"):
                self.become_tapped(attacker)
                self._turn_face_up(attacker)
            attacker.metadata["attacked_this_turn"] = True

        self._prune_combat_state()
        self.log.append(f"{controller.name} declared {len(unique_indices)} attacker(s)")
        if validated_bands:
            self.log.append(f"{controller.name} declared {len(validated_bands)} band(s)")
        if unique_indices:
            self._fire_attack_triggers(controller_index)
            self._fire_creature_attacks_triggers(controller_index, unique_indices)
            self._fire_delayed_attack_triggers(controller_index, unique_indices)
        # CR 508.4: once attackers have been declared (the turn-based action of the
        # declare attackers step), the active player receives priority.
        self.start_priority_window(self.active_player_index)
        return True, "declared attackers"

    def _fire_delayed_attack_triggers(
        self, controller_index: int, attacker_indices: list[int]
    ) -> None:
        """Delayed "whenever … creature(s) attack this turn" triggers created
        by a resolved loyalty ability (CR 603.7 — Basri Ket's −2, Basri,
        Devoted Paladin's −1). A batch entry fires once per attack with the
        count of matching attackers; a per-creature entry fires once per
        matching attacker, with that attacker as the trigger's source so its
        "on it" resolves to the creature. Entries stay armed for every combat
        this turn — cleanup clears them."""
        if not self.delayed_triggers:
            return
        controller = self.players[controller_index]
        attackers = [
            perm
            for idx in attacker_indices
            if (perm := self.permanent_at(controller, idx)) is not None
        ]
        if not attackers:
            return
        defending = next(iter(sorted(self.combat_defending_players())), None)
        events: list[dict] = []
        for entry in list(self.delayed_triggers):
            if entry.get("event") != "creatures_attack":
                continue
            matching = [
                perm for perm in attackers
                if not (entry.get("nontoken") and perm.metadata.get("is_token"))
            ]
            if not matching:
                continue
            seat = int(entry.get("controller_index", controller_index))
            instruction = entry.get("instruction")
            if instruction is None:
                continue
            if entry.get("batch"):
                events.append({
                    "controller_index": seat,
                    "source_permanent": None,
                    "card": entry.get("card"),
                    "instruction": instruction,
                    "effect_kind": "triggered_delayed",
                    "ability_text": entry.get("source_name", "delayed trigger"),
                    "trigger_context": {
                        "trigger_count": len(matching),
                        "trigger_defending_player_index": defending,
                    },
                })
            else:
                for perm in matching:
                    events.append({
                        "controller_index": seat,
                        "source_permanent": perm,
                        "card": entry.get("card"),
                        "instruction": instruction,
                        "effect_kind": "triggered_delayed",
                        "ability_text": entry.get("source_name", "delayed trigger"),
                        "trigger_context": {
                            "trigger_defending_player_index": defending,
                        },
                    })
        if events:
            self._enqueue_triggered_batch(events)

    def can_attack(self, attacker: Permanent, defending_player_index: int) -> bool:
        # "Can attack as though it had haste" (Instill Energy) lifts CR 302.6's
        # attack clause only — not its {T}-ability clause, which is why it is a
        # restriction here rather than a haste grant.
        if self._is_summoning_sick(attacker) and not aura_restriction_active(
            attacker, "attacks_as_though_hasty"
        ):
            return False

        program = compile_card_oracle(attacker.effective_card)
        instr_kinds = {i.kind for i in program.instructions}

        # The land type is *data* on the instruction rather than baked into its
        # name: a creature printed "unless defending player controls a Mountain"
        # is the same restriction with a different type. The chain that used to
        # produce this instruction matched an exact string naming Island, so any
        # other type fell through to a bare `static_line` and the creature
        # attacked freely while still reporting supported.
        without_land = next(
            (i for i in program.instructions if i.kind == "cant_attack_without_land_type"),
            None,
        )
        if without_land is not None:
            required = str(without_land.payload.get("land_type") or "island")
            # Honor text-changed land types (Magical Hack / Phantasmal Terrain):
            # a land turned into the named type counts, matching the upkeep
            # "no_islands" check. Scoped to lands so a creature subtype like
            # "Island Fish" never satisfies the restriction.
            return any(
                perm.card.primary_type == "land" and perm.has_type(required)
                for perm in self.controlled_by(defending_player_index)
            )

        if "cant_attack" in instr_kinds:
            return False

        # Animate Wall grants this while attached (auras.aura_restrictions).
        if "Defender" in attacker.card.keywords and not aura_restriction_active(
            attacker, "ignores_defender"
        ):
            return False

        # Island Sanctuary: defending player is protected from non-flying,
        # non-islandwalk attackers. Both keywords are asked through layer 6, so
        # islandwalk granted by a lord counts — reading the metadata flag and
        # the printed keyword list separately missed every other route to the
        # ability, which is the bug class tests/engine/test_layer_reads.py
        # guards.
        defending = self.players[defending_player_index]
        if defending.island_sanctuary_protected:
            if not (
                self._has_keyword(attacker, "flying")
                or self._has_keyword(attacker, "islandwalk")
            ):
                return False

        return True

    def _must_attack_if_able(self, attacker: Permanent) -> bool:
        if attacker.metadata.get("must_attack_until_eot"):
            return True
        program = compile_card_oracle(attacker.effective_card)
        return any(i.kind == "must_attack_each_combat" for i in program.instructions)

    def _fire_attack_triggers(self, controller_index: int) -> None:
        """Put "whenever one or more creatures you control attack" triggers on the stack.

        Covers Raging River and similar enchantments whose ability triggers once
        when the controller declares one or more attackers (CR 508.2/508.4, 603.3).
        Per CR 508.2 these abilities are placed on the stack as the declare attackers
        step's turn-based action completes — they don't resolve immediately; the
        active player then receives priority (the caller opens that window) and the
        triggers resolve as players pass priority with the stack non-empty.
        """
        from ..game_types import StackItem

        controller = self.players[controller_index]
        # CR 802.3a: a trigger not tied to a specific defending player applies once
        # across the whole attacking group; use the first attacker's defender as a
        # deterministic representative target (the only defender in the common
        # single-defender/2-player case).
        target_index = next(iter(self.combat_attackers.values()), controller_index)
        for permanent in list(controller.battlefield):
            for trig in matching_triggers(
                permanent.effective_card, condition_kinds={"one_or_more_attack"}
            ):
                self._stack_push(
                    StackItem(
                        card=permanent.card,
                        caster_index=controller_index,
                        target_player_index=target_index,
                        target_permanent_index=None,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=permanent,
                        ability_text=trig.source_line,
                    )
                )
                self.log.append(f"{permanent.card.name} triggered on attack (added to stack)")

    def _fire_creature_attacks_triggers(self, controller_index: int, attacker_indices: list[int]) -> None:
        """Put each attacker's own "whenever this creature attacks" triggers on
        the stack (e.g. Mijae Djinn's coin flip) — one per attacking creature
        that has the trigger, unlike _fire_attack_triggers' once-per-declaration
        team-wide version."""
        from ..game_types import StackItem

        controller = self.players[controller_index]
        for idx in attacker_indices:
            if not (0 <= idx < len(controller.battlefield)):
                continue
            permanent = controller.battlefield[idx]
            for trig in matching_triggers(
                permanent.effective_card, condition_kinds={"creature_attacks"}
            ):
                # "Whenever this creature attacks AND ISN'T BLOCKED" (Merchant
                # Ship, Pirate Ship riders) can't be evaluated until blockers
                # exist — deferred to _fire_unblocked_attack_triggers at the
                # combat damage step.
                if "isn't blocked" in (trig.source_line or "").lower():
                    continue
                self._stack_push(
                    StackItem(
                        card=permanent.card,
                        caster_index=controller_index,
                        # The attacker's own controller/index, so the coin-flip
                        # handler can remove IT from combat without re-deriving
                        # who owns it.
                        target_player_index=controller_index,
                        target_permanent_index=idx,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=permanent,
                        ability_text=trig.source_line,
                    )
                )
                self.log.append(f"{permanent.card.name} triggered on attack (added to stack)")

    # ------------------------------------------------------------------
    # Banding declaration (CR 702.22)
    # ------------------------------------------------------------------

    def _creature_has_banding(self, permanent: Permanent) -> bool:
        """Whether a creature currently has banding (printed or granted)."""
        if permanent.has_keyword("banding"):
            return True
        return self._has_keyword(permanent, "banding")

    def _validate_attacking_bands(
        self,
        bands: list[list[int]] | None,
        attacker_indices: list[int],
        controller: PlayerState,
    ) -> tuple[list[list[int]], str | None]:
        """Validate declared attacking bands (CR 702.22c). Returns (bands, error).

        A band is one or more attacking creatures with banding plus up to one
        attacking creature without banding; each creature may join only one band.
        """
        if not bands:
            return [], None
        attacker_set = set(attacker_indices)
        seen: set[int] = set()
        validated: list[list[int]] = []
        for group in bands:
            members = sorted(set(group))
            if len(members) < 2:
                return [], "a band must contain at least two creatures"
            banding_count = 0
            nonbanding_count = 0
            for idx in members:
                if idx not in attacker_set:
                    return [], "every band member must be a declared attacker"
                if idx in seen:
                    return [], "a creature may belong to only one band"
                seen.add(idx)
                if self._creature_has_banding(controller.battlefield[idx]):
                    banding_count += 1
                else:
                    nonbanding_count += 1
            if banding_count < 1:
                return [], "a band needs at least one creature with banding"
            if nonbanding_count > 1:
                return [], "a band may include at most one creature without banding"
            validated.append(members)
        return validated, None
